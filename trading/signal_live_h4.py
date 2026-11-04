#!/usr/bin/env python3
"""
================================================================================
XAUUSD LOCKED H4  -  LIVE SIGNAL BOT  ->  TELEGRAM
================================================================================

Reads the H4 bars that MetaTrader 4 keeps writing, replays the LOCKED method
(xauusd_method_LOCKED_H4.py) on them, and pushes new signals to Telegram.

DESIGN RULE: this file NEVER re-implements the strategy. It imports the locked
method and calls run(). If the locked file's parameters drift, the lock hash
fails there first and this bot refuses to start. That is deliberate - there is
exactly one copy of the trading logic in the world, and it is the locked file.

HOW IT STAYS IN SYNC WITH A LIVE ACCOUNT
----------------------------------------
The locked engine replays history from bar 0 every time, so it has no idea what
is currently open on your MT4. Two state files bridge that gap:

  state.json       - what we believe is live: open position, pending order,
                     last processed bar, last exit bar index
  signals_log.jsonl - every signal ever emitted, one JSON object per line

A signal is only sent ONCE. Re-running the bot is safe: it replays, compares
against state.json, and stays quiet unless something genuinely new happened.

WHEN TO RUN
-----------
Task Scheduler, once per H4 bar close + a few minutes:
  MT4 server time (MaxrichGroup, GMT+3):  03:05 07:05 11:05 15:05 19:05 23:05
  WIB (GMT+7):                            07:05 11:05 15:05 19:05 23:05 03:05

If a run is missed the bot catches up on the next one - it diffs state, it does
not rely on being called at an exact second.

USAGE
-----
  python signal_live_h4.py --check      # verdict only, no Telegram
  python signal_live_h4.py --run        # scan + send anything new
  python signal_live_h4.py --test       # send a test message to Telegram
  python signal_live_h4.py --status     # show state + last bars
  python signal_live_h4.py --sources    # find MT4 history files
================================================================================
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import re
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

HERE = Path(__file__).resolve().parent
LOCKED_METHOD = HERE / "xauusd_method_LOCKED_H4.py"
CONFIG_CANDIDATES = [
    HERE / "config.json",
    Path(r"C:\Users\Sharing Vision\Documents\OTHER\agen\tg.json"),
    Path.home() / ".xauusd" / "config.json",
]

STATE_FILE = HERE / "signal_state.json"
LOG_FILE = HERE / "signals_log.jsonl"
LOCK_FILE = HERE / "signal_live.lock"

# ntfy: phone push that cannot be silently muted like Telegram can.
# The topic is a shared secret - anyone who knows it can read the signals.
NTFY_FILE = HERE / "ntfy.json"
NTFY_SERVER = "https://ntfy.sh"

# MT4 terminal data folders to search for XAUUSD240.hst
MT4_ROOTS = [
    Path(os.environ.get("APPDATA", "")) / "MetaQuotes" / "Terminal",
    Path(r"C:\Program Files (x86)\MetaTrader 4"),
]

SYMBOL = "XAUUSD"
PERIOD_MIN = 240

# The broker writes bar timestamps in its own server clock, not UTC.
# Maxrich runs GMT+2 (confirmed against the EA status file: server_time
# 08:51 vs local_time 13:51 WIB = GMT+7). Any "age" calculation has to
# subtract this offset before comparing against the real clock.
SERVER_UTC_OFFSET_H = 2.0

# How many H4 bars back a signal may still be actionable. The locked method's
# limit expires after TTL_BARS = 2 bars, so a signal older than that is history.
MAX_SIGNAL_AGE_H4_BARS = 3


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def load_config() -> dict:
    """
    Accept the several shapes a user's config might arrive in:
      {"token": "...", "chat_id": "..."}
      {"bot_token": "...", "chat_id": ...}
      "token:chat_id"          (raw one-liner, no JSON)
    """
    for p in CONFIG_CANDIDATES:
        if not p.exists():
            continue
        raw = p.read_text(encoding="utf-8-sig", errors="replace").strip()
        if not raw:
            continue
        cfg = None
        try:
            cfg = json.loads(raw)
        except json.JSONDecodeError:
            pass
        if isinstance(cfg, dict):
            tok = (cfg.get("token") or cfg.get("bot_token")
                   or cfg.get("telegram_token") or "")
            chat = (cfg.get("chat_id") or cfg.get("telegram_chat_id")
                    or cfg.get("chat") or "")
            if tok:
                return dict(token=str(tok).strip(), chat_id=str(chat).strip(),
                            source=str(p))
        elif ":" in raw:
            # raw "token:chat_id" form; token itself contains one colon
            parts = raw.split(":")
            if len(parts) >= 3:
                return dict(token=":".join(parts[:2]).strip(),
                            chat_id=":".join(parts[2:]).strip(), source=str(p))
            return dict(token=raw, chat_id="", source=str(p))
    raise SystemExit(
        "No Telegram config found. Expected one of:\n  "
        + "\n  ".join(str(p) for p in CONFIG_CANDIDATES)
        + '\nFormat: {"token": "<bot token>", "chat_id": "<chat id>"}'
    )


# ---------------------------------------------------------------------------
# MT4 .hst reader
# ---------------------------------------------------------------------------


def read_hst(path: Path) -> list[dict]:
    """
    Parse an MT4 build-600+ .hst file (versions 400/401).

    Layout confirmed against a real MaxrichGroup XAUUSD240.hst:
      header 148 bytes, then 60-byte records:
        int32   time (unix seconds, server time)
        int32   reserved
        5 x f64 open, high, low, close, volume
        ...     trailing fields ignored
    Server time is GMT+3 (typical MetaQuotes broker); converted to naive
    server-clock timestamps so bar boundaries line up with the locked method.
    """
    b = path.read_bytes()
    if len(b) < 200:
        raise ValueError(f"{path.name}: file too small ({len(b)} bytes)")

    ver = struct.unpack("<i", b[0:4])[0]
    if ver not in (400, 401):
        raise ValueError(f"{path.name}: unsupported .hst version {ver}")

    hdr = 148
    rec = 60
    n = (len(b) - hdr) // rec
    if n <= 0:
        raise ValueError(f"{path.name}: no records")

    out = []
    for i in range(n):
        o = hdr + i * rec
        # V401 stores time and volume as int64, not int32. Reading them as
        # int32 shifts every price field by 4 bytes and yields garbage
        # (huge/negative floats, timestamps outside any sane range), which
        # is why this used to raise "no plausible bars".
        t = struct.unpack("<q", b[o:o + 8])[0]
        if not (1_000_000_000 < t < 2_200_000_000):
            continue
        o_, h_, l_, c_ = struct.unpack("<4d", b[o + 8:o + 40])
        v = struct.unpack("<q", b[o + 40:o + 48])[0]
        if not (100 < o_ < 100_000):
            continue
        out.append(dict(ts=t, o=o_, h=h_, l=l_, c=c_, v=v))

    if not out:
        raise ValueError(f"{path.name}: no plausible bars after parsing")
    return out


def find_hst_files() -> list[Path]:
    """Locate XAUUSD240.hst across every MT4 terminal data folder."""
    found = []
    for root in MT4_ROOTS:
        if not root or not str(root) or not Path(root).exists():
            continue
        for p in Path(root).rglob(f"{SYMBOL}{PERIOD_MIN}.hst"):
            found.append(p)
    return sorted(found, key=lambda p: p.stat().st_mtime, reverse=True)


# ---------------------------------------------------------------------------
# EA feed CSV reader (preferred source)
# ---------------------------------------------------------------------------
#
# The .hst file is only rewritten sporadically - MT4 keeps live bars in memory
# and flushes to disk on exit / timeframe switch, so the file on disk can be a
# day or more behind the price on the chart. The companion EA
# (MQL4/Experts/XAU_H4_FeedWriter.mq4) reads the live bars straight out of the
# terminal and rewrites MQL4/Files/XAUUSD_H4_FEED.csv on every H4 close, so
# that file is always the freshest view available without an external API.
#
# Feed CSV layout (semicolon-free, comma separated, MT4 FileWrite):
#   date,time,open,high,low,close,volume
#   2026.11.04,05:00,3934.79,4022.29,3926.64,4019.14,133555
# Timestamps are in the broker's server clock, the same clock the locked
# method's bar boundaries are built on, so no timezone shift is applied.

FEED_NAME = f"{SYMBOL}_H4_FEED.csv"
FEED_STATUS = f"{SYMBOL}_H4_STATUS.txt"

# How old the EA feed may be before it stops being trusted as a SOURCE.
# The EA only rewrites the CSV when an H4 bar closes, plus a 60-second heartbeat,
# so a healthy feed is normally under 5 minutes old. 90 minutes was too tight:
# one missed heartbeat pushed the robot onto the .hst fallback, which can be
# DAYS older, and it then treated two-day-old levels as live signals. One full
# H4 bar plus slack is the right horizon - anything fresher than that is still
# describing the bar we are trading.
FEED_MAX_AGE_MIN = 300

# Separate, stricter question: is the data we ended up with FRESH ENOUGH to act
# on? Falling back to .hst is fine for chart context, but a signal computed from
# days-old bars is worse than no signal, so --run refuses to announce anything
# past this age. /status still answers, with a warning.
MAX_DATA_AGE_H = 5.0


def read_ea_status() -> dict:
    """Read the EA's live snapshot (bid/ask/spread). {} when unavailable.

    The feed CSV only gains a row when an H4 bar CLOSES, so the newest close can
    be hours old while the market is moving. This side file is what tells the
    user where price actually is right now; it is display-only and never feeds
    the method's calculations.
    """
    out = {}
    try:
        paths = [p.parent / FEED_STATUS for p in find_feed_files()]
        paths = [p for p in paths if p.exists()]
        if not paths:
            return out
        f = max(paths, key=lambda p: p.stat().st_mtime)
        age_min = (time.time() - f.stat().st_mtime) / 60
        kv = {}
        for line in f.read_text(errors="replace").splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                kv[k.strip()] = v.strip()
        out = {
            "bid": float(kv.get("bid") or 0) or None,
            "ask": float(kv.get("ask") or 0) or None,
            "spread": float(kv.get("spread") or 0) or None,
            "server_time": kv.get("server_time"),
            "connected": kv.get("terminal_connected") == "1",
            "age_min": age_min,
            "fresh": age_min <= 5,
        }
    except Exception:
        return {}
    return out


def find_feed_files() -> list[Path]:
    """Locate the EA's H4 feed CSV across every MT4 terminal data folder."""
    found = []
    for root in MT4_ROOTS:
        if not root or not str(root) or not Path(root).exists():
            continue
        for p in Path(root).rglob(FEED_NAME):
            found.append(p)
    return sorted(found, key=lambda p: p.stat().st_mtime, reverse=True)


def read_feed(path: Path) -> list[dict]:
    """Parse the EA feed CSV into the same bar dicts read_hst() returns."""
    import csv as _csv
    import datetime as _dt

    out = []
    with path.open("r", encoding="latin-1", newline="") as fh:
        for row in _csv.reader(fh):
            if len(row) < 6:
                continue
            try:
                ts = _dt.datetime.strptime(
                    f"{row[0].strip()} {row[1].strip()}", "%Y.%m.%d %H:%M")
                o_ = float(row[2]); h_ = float(row[3])
                l_ = float(row[4]); c_ = float(row[5])
            except (ValueError, IndexError):
                continue        # header line and any malformed row
            if not (100 < o_ < 100_000):
                continue
            v = 0
            if len(row) > 6:
                try:
                    v = int(float(row[6]))
                except ValueError:
                    v = 0
            out.append(dict(ts=int(ts.replace(tzinfo=_dt.timezone.utc).timestamp()),
                            o=o_, h=h_, l=l_, c=c_, v=v))

    if not out:
        raise ValueError(f"{path.name}: no plausible bars after parsing")
    out.sort(key=lambda r: r["ts"])
    return out


def feed_status(path: Path) -> dict:
    """Read the EA status file written next to the feed CSV."""
    sp = path.parent / FEED_STATUS
    info = {}
    if not sp.exists():
        return info
    try:
        for line in sp.read_text(encoding="latin-1", errors="replace").splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                info[k.strip()] = v.strip()
    except OSError:
        pass
    return info


def read_bars() -> tuple[list[dict], Path, str]:
    """
    Return (bars, source_path, source_kind), preferring the EA feed.

    The feed is used when it exists and was written within FEED_MAX_AGE_MIN
    minutes; otherwise fall back to the freshest .hst.
    """
    import time as _time

    feeds = find_feed_files()
    if feeds:
        best = feeds[0]
        age_min = (_time.time() - best.stat().st_mtime) / 60.0
        if age_min <= FEED_MAX_AGE_MIN:
            try:
                return read_feed(best), best, "feed"
            except ValueError:
                pass        # fall through to .hst
    return read_hst(freshest_hst()), freshest_hst(), "hst"


def bars_source_report() -> str:
    """One-line human summary of which source a run is reading."""
    try:
        bars, src, kind = read_bars()
    except (SystemExit, ValueError) as exc:
        return f"source: NONE ({exc})"
    import time as _time
    age_min = (_time.time() - src.stat().st_mtime) / 60.0
    last = bars[-1]
    import datetime as _dt
    last_ts = _dt.datetime.utcfromtimestamp(last["ts"]).strftime("%d-%b %H:%M")
    tag = "EA feed" if kind == "feed" else ".hst (stale source)"
    return (f"source: {tag}  file age {age_min:.0f} min  "
            f"bars {len(bars)}  last bar {last_ts}  close {last['c']:.2f}")


def freshest_hst() -> Path:
    files = find_hst_files()
    if not files:
        raise SystemExit(
            f"No {SYMBOL}{PERIOD_MIN}.hst found. Open MT4, load the {SYMBOL} H4 "
            f"chart once so MT4 writes its history file, then retry.\n"
            f"Searched: " + ", ".join(str(r) for r in MT4_ROOTS if r))
    return files[0]


# ---------------------------------------------------------------------------
# Locked method
# ---------------------------------------------------------------------------


def load_locked():
    """Import the locked method by path without polluting sys.path permanently."""
    import importlib.util

    if not LOCKED_METHOD.exists():
        raise SystemExit(f"Locked method not found: {LOCKED_METHOD}")
    spec = importlib.util.spec_from_file_location("locked_h4", LOCKED_METHOD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # Refuse to run on a drifted method.
    if mod.METHOD_LOCK_HASH and mod._lock_payload() != mod.METHOD_LOCK_HASH:
        raise SystemExit(
            "REFUSING TO RUN: the locked method's parameters have drifted from "
            "its recorded hash.\nRun xauusd_method_LOCKED_H4.py --verify to see "
            "what changed.")
    return mod


def bars_to_frame(bars: list[dict]):
    import pandas as pd
    df = pd.DataFrame(bars)
    df["ts"] = pd.to_datetime(df["ts"], unit="s")
    return df[["ts", "o", "h", "l", "c"]].sort_values("ts").reset_index(drop=True)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            st = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            # "sent" must be a list. An older/partial write left it as {} here,
            # and then `st["sent"].append(k)` raised INSIDE the send loop - after
            # the Telegram message had already gone out but BEFORE save_state(),
            # so last_signal_key and the sent list were never persisted. Every
            # 5-minute run then re-sent the same signal forever. Normalising on
            # read makes that state self-healing instead of a permanent loop.
            if isinstance(st.get("sent"), dict):
                st["sent"] = list(st["sent"].keys())
            if not isinstance(st.get("sent"), list):
                st["sent"] = []
            if not isinstance(st.get("sent_total"), int):
                st["sent_total"] = len(st["sent"])
            return st
        except json.JSONDecodeError:
            pass
    return dict(last_bar=None, last_signal_key=None, open_position=None,
                pending=None, last_exit_bar=None, sent=[], sent_total=0)


def save_state(st: dict) -> None:
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=2, default=str), encoding="utf-8")
    tmp.replace(STATE_FILE)


def log_signal(rec: dict) -> None:
    with LOG_FILE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, default=str) + "\n")


def sig_key(t: dict) -> str:
    """Stable identity for a trade so it is never announced twice."""
    return (f"{t['action']}|{t['entry_time']}|{t['level']:.2f}")


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------


def load_ntfy() -> dict:
    """
    Read the ntfy topic. Absent file = ntfy silently disabled, never an error:
    the bot must keep delivering to Telegram even if push is not configured.
    """
    try:
        cfg = json.loads(NTFY_FILE.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    topic = str(cfg.get("topic") or "").strip()
    if not topic:
        return {}
    return {"topic": topic,
            "server": str(cfg.get("server") or NTFY_SERVER).rstrip("/")}


def ntfy_send(text: str, title: str = "XAUUSD", priority: int = 3,
              tags: list | None = None, dry: bool = False) -> bool:
    """
    Push to the phone through ntfy.

    priority 5 (urgent) pops over other apps and can override Do Not Disturb -
    reserved for NEW SIGNALS. /status answers use 3, so the urgent channel keeps
    its meaning: urgent only ever means 'there is a trade to place'.
    Telegram HTML tags are stripped, because ntfy shows plain text.
    """
    cfg = load_ntfy()
    if not cfg:
        return False
    plain = re.sub(r"<[^>]+>", "", text)
    plain = (plain.replace("&amp;", "&").replace("&lt;", "<")
                  .replace("&gt;", ">").replace("&quot;", '"'))
    if dry:
        print(f"\n--- NTFY DRY RUN (not sent, priority {priority}) ---\n"
              f"{title}\n{plain}\n--------------------------")
        return True
    body = json.dumps({
        "topic": cfg["topic"], "title": title, "message": plain,
        "priority": priority, "tags": tags or [],
    }).encode()
    req = urllib.request.Request(
        cfg["server"] + "/", data=body,
        headers={"Content-Type": "application/json"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return 200 <= r.status < 300
        except Exception as e:
            if attempt == 2:
                print(f"ntfy send failed after 3 tries: {e}")
                return False
            time.sleep(2 * (attempt + 1))
    return False


def send_all(text: str, title: str = "XAUUSD", priority: int = 3,
             tags: list | None = None, dry: bool = False) -> dict:
    """
    Deliver through every configured channel. One channel failing must never
    stop the other: the whole point of two channels is redundancy.
    """
    cfg = load_config()
    tg_ok = tg_send(cfg.get("token", ""), cfg.get("chat_id", ""), text,
                    dry=dry, loud=(priority >= 5))
    nt_ok = ntfy_send(text, title=title, priority=priority, tags=tags, dry=dry)
    return {"telegram": tg_ok, "ntfy": nt_ok}


def tg_send(token: str, chat_id: str, text: str, dry: bool = False,
            loud: bool = False) -> bool:
    """
    Send a Telegram message.

    loud=True is for SIGNALS ONLY. It asks Telegram for an audible
    notification and keeps the message high in the chat, so a new signal cannot
    be mistaken for a routine /status reply. /status itself stays silent on
    purpose: a bot that pings you every five minutes trains you to ignore it.
    """
    if dry:
        print("\n--- DRY RUN (not sent) ---\n" + text + "\n--------------------------")
        return True
    if not token or not chat_id:
        print("Telegram not configured (token/chat_id missing) - printing instead:")
        print(text)
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id, "text": text,
        "parse_mode": "HTML", "disable_web_page_preview": "true",
    }
    if loud:
        payload["disable_notification"] = "false"   # force the alert through
        payload["protect_content"] = "false"
    data = urllib.parse.urlencode(payload).encode()
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, data=data, timeout=20) as r:
                body = json.loads(r.read().decode())
            if body.get("ok"):
                return True
            print(f"Telegram error: {body.get('description')}")
            if "chat not found" in str(body.get("description", "")).lower():
                return False
        except urllib.error.HTTPError as e:
            print(f"Telegram HTTP {e.code}: {e.read()[:200]!r}")
        except Exception as e:
            print(f"Telegram send failed ({attempt + 1}/3): {e}")
        time.sleep(3)
    return False


def fmt_signal(t: dict, now_bar) -> str:
    import pandas as pd

    d = t["entry_time"]
    act = t["action"]
    arrow = "🟢 BUY" if act == "Buy" else "🔴 SELL"
    dist = abs(t["tp"] - t["entry"])

    # A live signal (fired, not yet exited) is the one that actually matters:
    # it is an order waiting to be placed. Say so loudly.
    if t.get("_live"):
        kind = t.get("_kind")
        if kind == "open":
            head = f"<b>{arrow} XAUUSD — POSISI TERBUKA</b>"
            tail = [
                f"<i>Limit sudah terisi. TP/SL sedang berjalan.</i>",
                f"<i>Jangan buka posisi baru sampai yang ini ditutup.</i>",
            ]
        else:
            head = f"<b>{arrow} SINYAL BARU XAUUSD</b>"
            tail = [
                f"<b>→ Pasang {act.upper()} LIMIT di {t['entry']:.2f}</b>",
                f"<i>Batalkan kalau belum terisi dalam 8 jam (2 lilin H4).</i>",
            ]
    else:
        head = f"<b>{arrow} XAUUSD</b>  ·  H4 · locked cap-$30"
        tail = [
            f"<i>Set a {act.upper()} LIMIT at {t['entry']:.2f}.</i>",
            f"<i>The order is cancelled if price does not retrace within 8h.</i>",
        ]

    lines = [
        head,
        "",
        f"<b>Entry</b>  <code>{t['entry']:.2f}</code>   (limit)",
        f"<b>TP</b>       <code>{t['tp']:.2f}</code>   (+{dist:.2f})",
        f"<b>SL</b>       <code>{t['sl']:.2f}</code>   (-{abs(t['entry'] - t['sl']):.2f})",
        "",
        f"Level broken : <b>{t['level']:.2f}</b>",
        f"TP target    : {t['tp_level']:.2f}",
        f"Signal bar   : {d:%d-%b-%Y %H:%M}",
        f"Valid for    : 2 H4 bars (8 hours)",
        "",
        *tail,
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Scan
# ---------------------------------------------------------------------------


def scan(mod, bars: list[dict], full: bool = False) -> dict:
    """
    Replay the locked method over the freshest bars and report what is NEW
    relative to the last stored state.

    full=True ignores history and reports the most recent trades (for --check).
    """
    df = bars_to_frame(bars)
    import pandas as pd
    trades = mod.run(df, start=mod.START_DEFAULT)

    if len(trades) == 0:
        return dict(bars=len(df), last_bar=str(df.ts.iloc[-1]), trades=0,
                    new=[], position=None)

    trades = trades.sort_values("entry_time").reset_index(drop=True)
    st = load_state()
    seen = set(st.get("sent", []))
    last_key = st.get("last_signal_key")

    # A signal is only actionable while its 2-bar limit window is still open.
    # Anything older than MAX_SIGNAL_AGE_H4_BARS bars is history, not a signal -
    # sending it would have you placing a limit that MT4 would never fill.
    newest_ts = df.ts.iloc[-1]
    cutoff = newest_ts - pd.Timedelta(hours=4 * MAX_SIGNAL_AGE_H4_BARS)

    # Everything not yet announced.
    new = []
    for _, t in trades.iterrows():
        k = sig_key(t._asdict() if hasattr(t, "_asdict") else t.to_dict())
        if k not in seen and k != last_key:
            new.append(t.to_dict())

    if not full and last_key:
        # Only report trades strictly AFTER the last one we announced. This is
        # what makes re-running safe: if uptime gapped and 10 old signals pile
        # up, we do not spam Telegram with all of them - but we must NEVER drop
        # a genuinely new signal, so there is no count cap here. Stale ones are
        # filtered by the bar-age guard below instead.
        keys = [sig_key(t) for t in new]
        if last_key in keys:
            new = new[keys.index(last_key) + 1:]
        elif keys and not seen:
            # First ever run on an empty state: do not dump years of history.
            new = new[-1:]

    # Hard safety net, independent of state: a fresh install (or a wiped
    # signal_state.json) has last_key=None and sent={}, so the guard above
    # does nothing and the FIRST --run would blast every historical trade to
    # Telegram. Any trade older than the actionable window is history, never a
    # signal, whether or not the state file remembers it.
    if not full:
        bounded, old = [], 0
        for t in new:
            if pd.Timestamp(t["entry_time"]) >= cutoff:
                bounded.append(t)
            else:
                old += 1
        if old:
            print(f"  {old} historical trade(s) ignored - outside the "
                  f"{MAX_SIGNAL_AGE_H4_BARS}-bar signal window")
        new = bounded

    # Drop anything whose limit window has already closed.
    if not full:
        fresh, stale = [], 0
        for t in new:
            if pd.Timestamp(t["entry_time"]) >= cutoff:
                fresh.append(t)
            else:
                stale += 1
        if stale:
            print(f"  {stale} old signal(s) skipped - their limit window "
                  f"already closed (not actionable)")
        new = fresh

    # Current position = a trade whose exit came from the newest bars.
    last_t = trades.iloc[-1].to_dict()

    # ------------------------------------------------------------------
    # A signal that has fired but has NOT been filled yet does not exist in
    # run()'s output at all - run() only returns FINISHED trades. That is
    # exactly the signal a trader needs, so build it here from live_state(),
    # which walks the same bars with the same locked parameters.
    # ------------------------------------------------------------------
    if not full:
        ls = live_state(mod, df)
        if ls["kind"] in ("pending", "open"):
            i = ls["info"]
            live_sig = {
                "action": i["type"],
                "entry": i["entry"], "tp": i["tp"], "sl": i["sl"],
                "level": i["level"], "tp_level": i["tp_level"],
                "entry_time": pd.Timestamp(i["sig_ts"]),
                "exit_time": None,
                "result": "OPEN" if ls["kind"] == "open" else "PENDING",
                "pl_usd": 0.0, "pl_pips": 0.0, "bars": ls["bars_used"],
                "_live": True, "_kind": ls["kind"],
            }
            # Identity MUST come from sig_key(), the same function that wrote
            # the saved key. The old code built its own
            # "type|entry|YYYY-MM-DD HH:MM" string here, which never matched the
            # saved "action|entry_time|level" form - so a live signal was
            # considered brand new on every single run and re-announced forever.
            k = sig_key(live_sig)
            already = k in seen or k == last_key
            if not already and pd.Timestamp(i["sig_ts"]) >= cutoff:
                # Do not duplicate: run() may already list this one as a
                # finished trade only after it exits, so at this point it is
                # guaranteed absent.
                new.append(live_sig)
            elif already:
                print(f"  live signal already announced ({i['type']} "
                      f"{i['entry']:.2f})")

    return dict(bars=len(df), last_bar=str(df.ts.iloc[-1]), trades=len(trades),
                new=new, position=last_t, state=st)


# ---------------------------------------------------------------------------
# Live status report (/status command)
# ---------------------------------------------------------------------------


def fmt_age(hours: float) -> str:
    """'3.2h' -> readable Indonesian-ish duration."""
    if hours < 1:
        return f"{int(hours * 60)} menit"
    if hours < 48:
        return f"{hours:.1f} jam"
    return f"{hours / 24:.1f} hari"


def next_level_up(price: float, levels) -> float | None:
    for lv in sorted(levels):
        if lv > price:
            return lv
    return None


def next_level_down(price: float, levels) -> float | None:
    for lv in sorted(levels, reverse=True):
        if lv < price:
            return lv
    return None


def live_state(mod, df) -> dict:
    """
    Where is the method RIGHT NOW?

    The locked engine's run() only returns FINISHED trades - a pending limit
    that has not been filled yet never appears in its output, yet that is
    exactly the signal a trader is holding. So we walk the same bars with the
    same locked parameters (never re-inventing them - they are read off the
    locked module) and stop at the last bar, reporting the open state.

    Returns dict(kind=...):
      'pending'  - signal fired, limit not filled yet, window still open
      'open'     - limit filled, position running
      'flat'     - nothing on
    """
    import pandas as pd

    lv = sorted(set(mod.RED_LEVELS))
    buf, cap, rr, ttl = mod.BUFFER_USD, mod.CAP_USD, mod.SL_RR_RATIO, mod.TTL_BARS
    d = df[df["ts"] >= pd.Timestamp(mod.START_DEFAULT)].reset_index(drop=True)

    pos = pending = prev_close = None
    last_exit_i = -10 ** 9

    for i in range(len(d)):
        r = d.iloc[i]
        hi, lo, cl, ts = r["h"], r["l"], r["c"], r["ts"]

        if pos is not None:
            if pos["type"] == "Buy":
                sl_hit, tp_hit = lo <= pos["sl"], hi >= pos["tp"]
            else:
                sl_hit, tp_hit = hi >= pos["sl"], lo <= pos["tp"]
            hit = ("SL" if (sl_hit and tp_hit)
                   else ("TP" if tp_hit else ("SL" if sl_hit else None)))
            if hit:
                pos, last_exit_i = None, i

        if pos is None and pending is not None:
            if i - pending["bar"] > ttl:
                pending = None
            else:
                if pending["type"] == "Buy":
                    filled = hi >= pending["entry"]
                else:
                    filled = lo <= pending["entry"]
                if filled:
                    pos = dict(pending)
                    pos.update(ts=ts, bars=0, fill_i=i)
                    pending = None

        if pos is not None:
            pos["bars"] = pos.get("bars", 0) + 1

        if pos is None and pending is None and prev_close is not None \
                and (i - last_exit_i > 0):
            up = next((L for L in lv if prev_close <= L < cl), None)
            dn = next((L for L in lv if prev_close >= L > cl), None)
            if up is not None:
                entry = up + buf
                above = [x for x in lv if x > entry]
                if above:
                    tgt = min(above)
                    dist = min(tgt - entry, cap)
                    if dist > 1.0:
                        pending = dict(bar=i, sig_ts=ts, type="Buy", entry=entry,
                                       tp=entry + dist, sl=entry - dist * rr,
                                       level=up, tp_level=tgt)
            elif dn is not None:
                entry = dn - buf
                below = [x for x in lv if x < entry]
                if below:
                    tgt = max(below)
                    dist = min(entry - tgt, cap)
                    if dist > 1.0:
                        pending = dict(bar=i, sig_ts=ts, type="Sell", entry=entry,
                                       tp=entry - dist, sl=entry + dist * rr,
                                       level=dn, tp_level=tgt)

        prev_close = cl

    newest_i = len(d) - 1
    if pos is not None:
        # A position filled on the newest bar has not had a full bar to run in;
        # report it as open either way, but note whether the fill is brand new.
        filled_this_bar = pos.get("fill_i") == newest_i
        return dict(kind="open", info=pos, bars_used=pos.get("bars", 0),
                    ttl=ttl, newest_i=newest_i, filled_this_bar=filled_this_bar)
    if pending is not None:
        return dict(kind="pending", info=pending,
                    bars_used=newest_i - pending["bar"], ttl=ttl,
                    newest_i=newest_i, filled_this_bar=False)
    return dict(kind="flat", info=None, bars_used=0, ttl=ttl,
                newest_i=newest_i, filled_this_bar=False)


def track_orders(mod, df) -> dict:
    """
    Walk the bars once and report EVERY order the plan has produced, with its
    current state - not just the one that is still live.

    The distinct states a trader must act on differently:
      baru        signal just fired, nothing filled and nothing placed yet
      terisi      entry touched, position is running -> leave it alone
      menunggu    stop not touched yet -> keep it, count the hours left
      batal       window closed unfilled -> DELETE the pending order
      TP / SL     finished -> delete the order, take the result
    """
    import pandas as pd

    lv = sorted(set(mod.RED_LEVELS))
    buf, cap, rr, ttl = mod.BUFFER_USD, mod.CAP_USD, mod.SL_RR_RATIO, mod.TTL_BARS
    d = df[df["ts"] >= pd.Timestamp(mod.START_DEFAULT)].reset_index(drop=True)

    rows: list[dict] = []
    pos = pending = prev_close = None
    last_exit_i = -10 ** 9

    for i in range(len(d)):
        r = d.iloc[i]
        hi, lo, cl, ts = r["h"], r["l"], r["c"], r["ts"]

        if pos is not None:
            if pos["type"] == "Buy":
                sl_hit, tp_hit = lo <= pos["sl"], hi >= pos["tp"]
            else:
                sl_hit, tp_hit = hi >= pos["sl"], lo <= pos["tp"]
            hit = ("SL" if (sl_hit and tp_hit)
                   else ("TP" if tp_hit else ("SL" if sl_hit else None)))
            if hit:
                pos["state"] = hit
                pos["exit_ts"] = ts
                pos["exit_i"] = i
                rows.append(pos)
                pos, last_exit_i = None, i

        if pos is None and pending is not None:
            if i - pending["bar"] > ttl:
                pending["state"] = "batal"
                pending["exit_i"] = i
                rows.append(pending)
                pending = None
            else:
                filled = (hi >= pending["entry"] if pending["type"] == "Buy"
                          else lo <= pending["entry"])
                if filled:
                    pos = dict(pending)
                    pos.update(ts=ts, bars=0, fill_i=i)
                    pending = None

        if pos is not None:
            pos["bars"] = pos.get("bars", 0) + 1

        if pos is None and pending is None and prev_close is not None \
                and (i - last_exit_i > 0):
            up = next((L for L in lv if prev_close <= L < cl), None)
            dn = next((L for L in lv if prev_close >= L > cl), None)
            if up is not None:
                entry = up + buf
                above = [x for x in lv if x > entry]
                if above:
                    tgt = min(above)
                    dist = min(tgt - entry, cap)
                    if dist > 1.0:
                        pending = dict(bar=i, sig_ts=ts, type="Buy", entry=entry,
                                       tp=entry + dist, sl=entry - dist * rr,
                                       level=up, tp_level=tgt, state="menunggu")
            elif dn is not None:
                entry = dn - buf
                below = [x for x in lv if x < entry]
                if below:
                    tgt = max(below)
                    dist = min(entry - tgt, cap)
                    if dist > 1.0:
                        pending = dict(bar=i, sig_ts=ts, type="Sell", entry=entry,
                                       tp=entry - dist, sl=entry + dist * rr,
                                       level=dn, tp_level=tgt, state="menunggu")

        prev_close = cl

    newest_i = len(d) - 1
    if pos is not None:
        pos["state"] = "terisi"
        rows.append(pos)
    if pending is not None:
        pending["state"] = "menunggu"
        rows.append(pending)
    return dict(rows=rows, newest_i=newest_i, ttl=ttl, last_bar=d.iloc[-1])


def build_positions_report() -> str:
    """
    /posisi - what is running, what must be deleted, and whether anything new
    has fired. This answers the question the trader actually asks after a fill:
    'is this still my trade, or do I take it off?'
    """
    import pandas as pd

    mod = load_locked()
    bars, hst, _src = read_bars()
    df = bars_to_frame(bars)
    tr = track_orders(mod, df)
    rows, ttl = tr["rows"], tr["ttl"]
    newest_ts = pd.Timestamp(df.ts.iloc[-1])
    newest_close = float(df.c.iloc[-1])
    real_now = datetime.now(timezone.utc).replace(tzinfo=None)
    data_age_h = max(0.0, (real_now - newest_ts.to_pydatetime()).total_seconds() / 3600)

    live = [r for r in rows if r["state"] in ("terisi", "menunggu")]
    done = [r for r in rows if r["state"] in ("TP", "SL", "batal")]

    L = []
    L.append(f"<b>POSISI &amp; ORDER XAUUSD</b> · "
             f"{datetime.now().strftime('%d-%b %H:%M')} WIB")
    L.append(f"Harga {newest_close:.2f} · data {fmt_age(data_age_h)} lalu")
    L.append("")

    # When the data is old, every 'action' below is a guess about a market we
    # are not seeing. Say so first and loudly, before any price is trusted.
    if data_age_h > 6:
        L.append("🔴 <b>DATA MATI — jangan ambil keputusan dari laporan ini.</b>")
        L.append(f"   Lilin terakhir {newest_ts:%d-%b %H:%M}, "
                 f"seharusnya paling lama 4 jam lalu.")
        L.append("   Buka MT4, cek jam &amp; ikon koneksi, lalu ketik /posisi lagi.")
        L.append("")

    # --- what is on right now -------------------------------------------
    L.append("<b>Yang sedang berjalan</b>")
    if not live:
        L.append("  Tidak ada. Tidak ada order yang perlu dijaga.")
        if data_age_h <= 6:
            L.append("  → Kalau Anda punya order nyata di MT4, "
                     "<b>hapus</b> — metode tidak mengakui order itu.")
    for r in sorted(live, key=lambda x: x.get("sig_ts", pd.Timestamp.min)):
        act = "BUY" if r["type"] == "Buy" else "SELL"
        if r["state"] == "terisi":
            L.append("")
            L.append(f"🟢 <b>{act} — SUDAH TERISI / POSISI BERJALAN</b>")
            L.append(f"Entry <code>{r['entry']:.2f}</code>")
            L.append(f"SL <code>{r['sl']:.2f}</code>   TP <code>{r['tp']:.2f}</code>")
            L.append(f"Terisi {pd.Timestamp(r['ts']):%d-%b %H:%M} · "
                     f"sudah {r.get('bars', 0)} lilin H4")
            L.append("→ <b>Aksi: biarkan. Jangan diubah, jangan ditambah.</b>")
        else:
            # Count real elapsed time, not bars x 4: H4 bars skip the weekend
            # gap, so a bar count badly understates how long is left.
            deadline = pd.Timestamp(r["sig_ts"]) + pd.Timedelta(hours=ttl * 4)
            sisa = max(0.0, (deadline - newest_ts.to_pydatetime()).total_seconds() / 3600)
            L.append("")
            L.append(f"🟡 <b>{act} — BELUM TERISI</b>")
            L.append(f"Entry <code>{r['entry']:.2f}</code>")
            L.append(f"SL <code>{r['sl']:.2f}</code>   TP <code>{r['tp']:.2f}</code>")
            L.append(f"Sinyal {pd.Timestamp(r['sig_ts']):%d-%b %H:%M} · "
                     f"sisa <b>{sisa:.0f} jam</b> sebelum hangus")
            L.append("→ <b>Aksi: biarkan menunggu.</b> Batalkan hanya bila "
                     f"sisa {sisa:.0f} jam habis tanpa terisi.")
    L.append("")

    # --- what changed on the newest bar ----------------------------------
    L.append("<b>Terjadi apa di lilin terakhir</b>")
    changed = [r for r in rows
               if r["state"] in ("TP", "SL", "batal")
               and r.get("exit_i") == tr["newest_i"]]
    if not changed:
        L.append("  Tidak ada perubahan. Semua seperti lilin sebelumnya.")
    for r in changed:
        act = "BUY" if r["type"] == "Buy" else "SELL"
        if r["state"] == "batal":
            L.append(f"  ❌ {act} {r['entry']:.2f} <b>HANGUS</b> — tidak terisi "
                     f"dalam {ttl} lilin. <b>Hapus ordernya.</b>")
        else:
            mark = "✅" if r["state"] == "TP" else "🛑"
            L.append(f"  {mark} {act} {r['entry']:.2f} kena <b>{r['state']}</b>. "
                     f"<b>Hapus ordernya.</b>")
    L.append("")

    # --- anything new on this bar? ---------------------------------------
    fresh = [r for r in rows if r.get("bar") == tr["newest_i"]]
    L.append("<b>Sinyal baru di lilin ini</b>")
    if not fresh:
        L.append("  Tidak ada. Metode belum memberi sinyal baru.")
        L.append("  <i>Tidak perlu dipaksa — menunggu bukan kesalahan.</i>")
    for r in fresh:
        act = "BUY" if r["type"] == "Buy" else "SELL"
        L.append(f"  🆕 {act} entry {r['entry']:.2f} "
                 f"SL {r['sl']:.2f} TP {r['tp']:.2f}")
    L.append("")

    if done:
        L.append("➖➖➖ <i>riwayat terakhir</i> ➖➖➖")
        for r in done[-5:]:
            act = "BUY" if r["type"] == "Buy" else "SELL"
            L.append(f"  {act} {r['entry']:.2f} → <b>{r['state']}</b> "
                     f"({pd.Timestamp(r.get('exit_ts', r['sig_ts'])):%d-%b %H:%M})")
        L.append("")

    L.append(f"<i>Metode: {mod.METHOD_ID} v{mod.METHOD_VERSION} · "
             f"aturan: stop order, TTL {ttl} lilin H4</i>")
    return "\n".join(L)


def build_status_report() -> str:
    """
    Everything a trader wants at a glance: where price is, whether there is a
    live signal, since when, and how long is left on it.
    """
    import pandas as pd

    mod = load_locked()
    bars, hst, _src = read_bars()
    df = bars_to_frame(bars)

    trades = mod.run(df, start=mod.START_DEFAULT).sort_values("entry_time")
    last = trades.iloc[-1].to_dict()
    newest_ts = pd.Timestamp(df.ts.iloc[-1])
    newest_close = float(df.c.iloc[-1])

    # --- how fresh is the data? MT4 not running = no new bars -------------
    real_now = datetime.now(timezone.utc).replace(tzinfo=None)
    data_age_h = (real_now - newest_ts.to_pydatetime()).total_seconds() / 3600
    # A partially-formed bar can sit slightly in the future on the server clock;
    # never show a negative age.
    data_age_h = max(data_age_h, 0.0)

    ls = live_state(mod, df)
    ttl = ls["ttl"]

    arrow = "🟢 BUY" if last["action"] == "Buy" else "🔴 SELL"
    up = next_level_up(newest_close, mod.RED_LEVELS)
    dn = next_level_down(newest_close, mod.RED_LEVELS)

    # --- jawabannya: rencana pasang order, dua arah -----------------------
    L = []
    L.append(f"<b>STATUS XAUUSD</b> · {datetime.now().strftime('%d-%b %H:%M')} WIB")
    L.append("")

    # --- harga live (dari file EA, hanya untuk tampilan) -------------------
    ea = read_ea_status()
    if ea.get("bid") and ea.get("fresh"):
        sp = f" · spread {ea['spread']:.2f}" if ea.get("spread") else ""
        L.append(f"💰 <b>Harga sekarang</b>  bid <code>{ea['bid']:.2f}</code>"
                 f"  ask <code>{ea['ask']:.2f}</code>{sp}")
        if newest_close:
            d = ea["bid"] - newest_close
            L.append(f"<i>{d:+.2f} dari close lilin {newest_close:.2f}</i>")
    elif ea.get("bid"):
        L.append(f"💰 Harga terakhir tercatat <code>{ea['bid']:.2f}</code> "
                 f"<i>(EA diam {fmt_age(ea['age_min'] / 60)})</i>")
    else:
        L.append("<i>Harga live tidak terbaca — file status EA tidak ditemukan.</i>")
    L.append("")

    if data_age_h > MAX_DATA_AGE_H:
        L.append("🔴 <b>DATA MATI — JANGAN PASANG APA PUN.</b>")
        L.append("MT4 tidak memperbarui harga. Buka MT4, login, lalu ketik /status lagi.")
        L.append(f"<i>Harga terakhir {newest_close:.2f} dari {fmt_age(data_age_h)} lalu.</i>")
        L.append("<i>Sinyal otomatis juga dimatikan selama data belum segar — "
                 "robot tidak akan mengirim apa pun.</i>")
        L.append("")
        L.append("➖➖➖ <i>rincian</i> ➖➖➖")
        L.append(f"Lilin H4 terakhir : {newest_ts:%d-%b %H:%M}")
        return "\n".join(L)

    sc = plan_scenarios(newest_close, mod, ls)

    # The method places an order ONLY on the bar after a close crosses a level.
    # Anything that reads like "place these now" outside that state is wrong and
    # gets acted on, so the verdict follows live_state() and nothing else.
    live = ls["kind"]          # flat | pending | open

    if live == "flat":
        L.append(f"⚪ <b>TIDAK ADA YANG PERLU DIPASANG</b>")
        L.append("")
        L.append(f"Close lilin terakhir <b>{newest_close:.2f}</b>")
        L.append("<i>Metode belum memerintahkan order apa pun. Menunggu 1 lilin "
                 "H4 tutup melewati garis level.</i>")
    elif live == "pending":
        i = ls["info"]
        sisa = max(0, (ttl - ls["bars_used"]) * 4)
        act = "BUY" if i["type"] == "Buy" else "SELL"
        emoji = "🟢" if act == "BUY" else "🔴"
        L.append(f"🟡 <b>ADA ORDER {act} BELUM TERISI</b>")
        L.append("")
        L.append(f"{emoji} <b>{act} LIMIT</b>")
        L.append(f"Entry <code>{i['entry']:.2f}</code>")
        L.append(f"SL <code>{i['sl']:.2f}</code>")
        L.append(f"TP <code>{i['tp']:.2f}</code>")
        L.append("")
        L.append(f"<i>Sisa waktu <b>{sisa} jam</b> sebelum hangus. Kalau belum "
                 f"terisi sampai itu, hapus ordernya.</i>")
    else:  # open
        i = ls["info"]
        act = "BUY" if i["type"] == "Buy" else "SELL"
        emoji = "🟢" if act == "BUY" else "🔴"
        L.append(f"🟢 <b>POSISI {act} SEDANG BERJALAN</b>")
        L.append("")
        L.append(f"{emoji} <b>{act}</b>")
        L.append(f"Entry <code>{i['entry']:.2f}</code>")
        L.append(f"SL <code>{i['sl']:.2f}</code>")
        L.append(f"TP <code>{i['tp']:.2f}</code>")
        L.append("")
        L.append("<i>Sudah terisi. Biarkan berjalan sampai TP atau SL — "
                 "posisi yang sudah masuk tidak punya batas waktu.</i>")

    L.append("")

    L.append("➖➖➖ <i>rincian</i> ➖➖➖")
    L.append(f"Close lilin H4 terakhir : {newest_ts:%d-%b %H:%M} "
             f"(data {fmt_age(data_age_h)} lalu)")
    L.append("<i>Ini harga penutupan lilin, bukan harga live yang bergerak.</i>")
    L.append("Syarat sinyal: 1 lilin H4 <b>tutup</b> melewati garis level.")
    for s in sc:
        L.append(f"  {s['side']} lahir bila tutup di "
                 f"{'atas' if s['side'] == 'BUY' else 'bawah'} {s['level']:.2f}")
    if up is not None:
        L.append(f"Resistance terdekat : {up:.2f}  (+{up - newest_close:.2f})")
    if dn is not None:
        L.append(f"Support terdekat    : {dn:.2f}  ({dn - newest_close:+.2f})")
    L.append(f"Trade terakhir ({arrow}) : <b>{last['result']}</b> "
             f"({last['pl_usd']:+.2f}) · "
             f"{pd.Timestamp(last['exit_time']):%d-%b %H:%M}")


    # --- health line ------------------------------------------------------
    # "sent" only counts what this state file has announced since it was last
    # reset, so a bare 0 reads as "the robot never sent anything" right after a
    # reset - which is exactly when the user is most suspicious. Report the
    # high-water mark instead and say what the number actually means.
    st = load_state()
    sent = st.get("sent", [])
    n_sent = len(sent) if isinstance(sent, (list, dict)) else 0
    seen_max = st.get("sent_total", n_sent)
    if n_sent == 0:
        sent_txt = (f"{seen_max} sinyal pernah terkirim"
                    if seen_max else "belum ada sinyal terkirim")
    else:
        sent_txt = f"{n_sent} sinyal terkirim sejak {st.get('reset_at', 'reset terakhir')}"
    L.append("")
    L.append(f"<i>{mod.METHOD_ID} v{mod.METHOD_VERSION} · "
             f"{len(trades)} trade historis · {sent_txt}</i>")
    return "\n".join(L)


def plan_scenarios(newest_close: float, mod, ls: dict) -> list:
    """
    The concrete breakout scenarios the method is waiting for, worked out with
    the LOCKED parameters. Nothing here re-invents a number: buffer, cap, RR and
    TTL all come off the locked module, exactly like live_state() does.
    """
    lv = sorted(set(mod.RED_LEVELS))
    buf, cap, rr = mod.BUFFER_USD, mod.CAP_USD, mod.SL_RR_RATIO

    out = []

    up = next_level_up(newest_close, lv)
    if up is not None:
        entry = up + buf
        above = [x for x in lv if x > entry]
        if above:
            tgt = min(above)
            dist = min(tgt - entry, cap)
            if dist > 1.0:
                out.append(dict(
                    side="BUY", level=up, entry=entry, tp=entry + dist,
                    sl=entry - dist * rr, dist=dist, tp_level=tgt,
                    capped=(tgt - entry) > cap,
                ))

    dn = next_level_down(newest_close, lv)
    if dn is not None:
        entry = dn - buf
        below = [x for x in lv if x < entry]
        if below:
            tgt = max(below)
            dist = min(entry - tgt, cap)
            if dist > 1.0:
                out.append(dict(
                    side="SELL", level=dn, entry=entry, tp=entry - dist,
                    sl=entry + dist * rr, dist=dist, tp_level=tgt,
                    capped=(entry - tgt) > cap,
                ))

    return out


def build_plan_report() -> str:
    """
    /plan - a full trading plan, not just a status line.

    /status says 'what is happening'. /plan says 'what I will do, at what price,
    with what risk, and what would cancel it'. Every number is derived from the
    locked module, so the plan can never drift from the method.
    """
    import pandas as pd

    mod = load_locked()
    bars, hst, _src = read_bars()
    df = bars_to_frame(bars)

    newest_ts = pd.Timestamp(df.ts.iloc[-1])
    newest_close = float(df.c.iloc[-1])
    real_now = datetime.now(timezone.utc).replace(tzinfo=None)
    data_age_h = max((real_now - newest_ts.to_pydatetime()).total_seconds() / 3600, 0.0)

    ls = live_state(mod, df)
    ttl = ls["ttl"]
    buf, cap, rr = mod.BUFFER_USD, mod.CAP_USD, mod.SL_RR_RATIO

    L = []
    L.append("<b>🗺️ RENCANA TRADING XAUUSD · H4</b>")
    L.append(f"<i>{datetime.now().strftime('%d-%b-%Y %H:%M')} WIB</i>")
    L.append("")

    # --- 1. where we stand ------------------------------------------------
    L.append("<b>1. POSISI SEKARANG</b>")
    L.append(f"  Harga : <b>{newest_close:.2f}</b>  "
             f"<i>(close H4 {newest_ts:%d-%b %H:%M})</i>")
    L.append(f"  Data  : {fmt_age(data_age_h)} lalu")
    if data_age_h > 6:
        L.append("  ⚠️ <b>Data basi.</b> MT4 tertutup/belum login —")
        L.append("     rencana di bawah belum bisa dieksekusi.")
    L.append("")

    # --- 2. is there already something on? --------------------------------
    L.append("<b>2. YANG SUDAH BERJALAN</b>")
    if ls["kind"] == "open":
        i = ls["info"]
        arrow = "🟢 BUY" if i["type"] == "Buy" else "🔴 SELL"
        sisa = max(0, (ttl - ls["bars_used"]) * 4)
        L.append(f"  {arrow} <b>posisi terbuka</b> @ {i['entry']:.2f}")
        L.append(f"  TP {i['tp']:.2f}   SL {i['sl']:.2f}")
        L.append(f"  Sudah {ls['bars_used']} lilin ({ls['bars_used'] * 4} jam).")
        risk = abs(i["entry"] - i["sl"])
        reward = abs(i["tp"] - i["entry"])
        L.append(f"  Risiko {risk:.2f}  ·  Imbalan {reward:.2f}  ·  "
                 f"R:R 1:{reward / risk:.2f}" if risk else "")
        L.append("")
        L.append("  <b>Rencana:</b> jangan buka posisi baru. Metode ini hanya")
        L.append("  memegang satu posisi. Tunggu TP atau SL kena.")
    elif ls["kind"] == "pending":
        i = ls["info"]
        arrow = "🟢 BUY" if i["type"] == "Buy" else "🔴 SELL"
        sisa = max(0, (ttl - ls["bars_used"]) * 4)
        sisa_bar = max(0, ttl - ls["bars_used"])
        L.append(f"  {arrow} <b>limit menunggu terisi</b> @ {i['entry']:.2f}")
        L.append(f"  TP {i['tp']:.2f}   SL {i['sl']:.2f}")
        L.append(f"  Sisa waktu: <b>{sisa} jam</b> ({sisa_bar} lilin H4 lagi)")
        L.append("")
        L.append("  <b>Rencana:</b>")
        L.append(f"  1. Pasang {i['type'].upper()} LIMIT di <b>{i['entry']:.2f}</b>")
        L.append(f"  2. Begitu terisi, pasang TP {i['tp']:.2f} & SL {i['sl']:.2f}")
        L.append(f"  3. Kalau belum terisi sampai {sisa} jam lagi, batalkan.")
        L.append("     Limit hangus = tidak ada trade. Itu normal, bukan kerugian.")
    else:
        L.append("  Tidak ada posisi, tidak ada limit aktif.")
        L.append("  <b>Rencana:</b> tunggu salah satu skenario di poin 3.")
    L.append("")

    # --- 3. the scenarios -------------------------------------------------
    L.append("<b>3. SKENARIO YANG DINANTIKAN</b>")
    scen = plan_scenarios(newest_close, mod, ls)

    if ls["kind"] == "open":
        # Showing entries here would contradict point 2. While a position is
        # running the method takes no new trade, full stop.
        L.append("  <b>Tidak berlaku sekarang</b> — masih ada posisi terbuka.")
        L.append("  Metode ini hanya memegang satu posisi. Skenario di bawah")
        L.append("  baru aktif setelah posisi sekarang ditutup (TP/SL).")
        L.append("")
    elif ls["kind"] == "pending":
        L.append("  <b>Tidak berlaku sampai limit sekarang selesai</b>")
        L.append("  (terisi, hangus, atau dibatalkan).")
        L.append("")

    if not scen:
        L.append("  Tidak ada level valid di arah mana pun.")
    for n, s in enumerate(scen, 1):
        jarak_level = abs(s["level"] - newest_close)
        L.append("")
        L.append(f"  <b>{n}. {s['side']}</b>")
        L.append(f"     Syarat : 1 lilin H4 <b>tutup</b> di "
                 f"{'atas' if s['side'] == 'BUY' else 'bawah'} "
                 f"<b>{s['level']:.2f}</b>")
        L.append(f"     Jarak dari harga sekarang: {jarak_level:.2f} poin")
        L.append(f"     Entry  : <b>{s['entry']:.2f}</b> "
                 f"<i>(limit {buf:.2f} di belakang level)</i>")
        L.append(f"     TP     : <b>{s['tp']:.2f}</b> "
                 f"<i>({s['dist']:.2f}"
                 f"{' — dipotong dari ' + format(s['tp_level'], '.2f') if s['capped'] else ''})</i>")
        L.append(f"     SL     : <b>{s['sl']:.2f}</b> "
                 f"<i>({rr * 100:.0f}% dari jarak TP)</i>")
        L.append(f"     Hasil  : menang <b>+{s['dist']:.2f}</b> · "
                 f"kalah <b>−{s['dist'] * rr:.2f}</b> USD per 1.00 lot")
        L.append(f"     Batas  : limit hangus dalam {ttl * 4} jam kalau tidak tersentuh")

    # --- 4. what cancels the plan ----------------------------------------
    L.append("")
    L.append("<b>4. YANG MEMBATALKAN RENCANA</b>")
    L.append(f"  • Lilin H4 tutup tapi <b>tidak</b> melewati level mana pun")
    L.append("  • Limit tidak tersentuh dalam batas waktu di atas")
    L.append("  • Masih ada posisi terbuka (metode ini 1 posisi saja)")
    L.append("  • Bar exit terakhir belum lewat 1 lilin (cooldown)")
    L.append("")
    L.append("<i>Semua angka di atas dihitung oleh metode terkunci — bukan "
             "perkiraan saya.</i>")

    st = load_state()
    L.append("")
    L.append(f"<i>{mod.METHOD_ID} v{mod.METHOD_VERSION} · "
             f"{len(st.get('sent', []))} sinyal terkirim</i>")
    return "\n".join(L)


def build_month_report(month: str | None = None) -> str:
    """
    /report - every order the locked method produced this month, in a table.

    Same engine as the backtest (track_orders walks the exact same code path that
    produced the 348-trade baseline), so the list here can never disagree with
    the backtest. The last row is the still-open plan, labelled Planning.
    """
    import pandas as pd

    mod = load_locked()
    bars, _hst, _src = read_bars()
    df = bars_to_frame(bars)
    tr = track_orders(mod, df)
    rows = tr["rows"]

    # Which month? default = month of the newest bar, not of the PC clock: around
    # midnight on the 1st those differ, and the data is the honest answer.
    newest_ts = pd.Timestamp(df.ts.iloc[-1])
    if month:
        month = month.strip()
    else:
        month = f"{newest_ts.month:02d}" if False else newest_ts.strftime("%Y-%m")
    if len(month) == 2:
        month = f"{newest_ts.year}-{month}"
    try:
        per = pd.Period(month, freq="M")
    except Exception:
        return (f"❓ Format bulan tidak dikenali: <b>{month}</b>\n"
                f"Pakai <code>/report</code>, <code>/report 11</code>, "
                f"atau <code>/report 2026-11</code>.")

    sel = [r for r in rows if pd.Timestamp(r["sig_ts"]).to_period("M") == per]
    sel.sort(key=lambda r: pd.Timestamp(r["sig_ts"]))

    ttl = tr["ttl"]
    newest_i = tr["newest_i"]
    rr = mod.SL_RR_RATIO
    buf, cap = mod.BUFFER_USD, mod.CAP_USD

    # --- classify every row into the exit label the user asked for ---------
    def label(r) -> str:
        st = r["state"]
        if st == "TP":
            return "TP"
        if st == "SL":
            return "LOSS"
        if st == "batal":
            return "BATAL (limit hangus)"
        if st == "terisi":
            return "RUNNING"
        # 'menunggu' = pending never touched. It is still Planning only while its
        # window is open; once the window has passed it expired, full stop.
        left = ttl - (newest_i - r.get("fill_i", r.get("bar", 0)))
        return "RUNNING (limit menunggu)" if left >= 0 else "BATAL (limit hangus)"

    lt = []
    lt.append(f"<b>📋 REPORT SINYAL XAUUSD · {per.strftime('%B %Y')}</b>")
    lt.append(f"<i>Metode baku {mod.METHOD_ID} v{mod.METHOD_VERSION} · H4</i>")
    lt.append("")

    if not sel:
        lt.append(f"Belum ada sinyal di bulan ini (data s/d {newest_ts:%d-%b %Y %H:%M}).")
        lt.append("")
        lt.append("<b>PLANNING</b>")
        lt.append(_report_plan_line(mod, df, tr, newest_ts, buf, cap, rr))
        return "\n".join(lt)

    tp = sum(1 for r in sel if r["state"] == "TP")
    sl = sum(1 for r in sel if r["state"] == "SL")
    bat = sum(1 for r in sel if r["state"] == "batal")
    run = len(sel) - tp - sl - bat
    done = tp + sl

    # --- the table ---------------------------------------------------------
    # Telegram is ~40 monospace chars wide on a phone. Values sit on their own
    # line under each header so nothing wraps mid-number.
    lt.append(f"<b>tanggal | jenis | entry | tp | sl | keterangan</b>")
    lt.append("<pre>")
    for r in sel:
        ts = pd.Timestamp(r["sig_ts"])
        act = "BUY" if r["type"] == "Buy" else "SELL"
        lt.append(f"{ts:%d-%b %H:%M} | {act:<4} | {r['entry']:.2f}")
        lt.append(f"   tp {r['tp']:.2f}  sl {r['sl']:.2f} | {label(r)}")
    lt.append("</pre>")

    # --- planning row ------------------------------------------------------
    lt.append("")
    lt.append("<b>PLANNING (baris terakhir)</b>")
    lt.append(_report_plan_line(mod, df, tr, newest_ts, buf, cap, rr))

    # --- recap -------------------------------------------------------------
    lt.append("")
    lt.append("<b>REKAP BULAN INI</b>")
    lt.append(f"  Total sinyal : {len(sel)}")
    if done:
        lt.append(f"  Selesai      : {done}  (TP {tp} · LOSS {sl})")
        lt.append(f"  Win rate     : <b>{100 * tp / done:.2f}%</b>")
        pl = tp * cap - sl * cap * rr
        lt.append(f"  Estimasi P/L : <b>{pl:+.2f}</b> USD per 1.00 lot")
    if bat:
        lt.append(f"  Limit hangus : {bat}")
    if run:
        lt.append(f"  Masih jalan  : {run}")
    lt.append("")
    lt.append("<i>Angka di atas berasal dari mesin yang sama dengan backtest "
             "348 trade (WR 58,62%). Kalau backtest berubah, tabel ini ikut "
             "berubah — tidak mungkin berbeda.</i>")
    return "\n".join(lt)


def _report_plan_line(mod, df, tr, newest_ts, buf, cap, rr) -> str:
    """One planning row: what to place next, at which price, and how."""
    import pandas as pd

    ls = live_state(mod, df)
    ttl = tr["ttl"]
    L = []

    if ls["kind"] in ("pending", "open"):
        i = ls["info"]
        act = "BUY" if i["type"] == "Buy" else "SELL"
        sisa = max(0, (ttl - ls["bars_used"]) * 4)
        L.append(f"<pre>{pd.Timestamp(i['sig_ts']):%d-%b %H:%M} | {act:<4} | "
                 f"{i['entry']:.2f}")
        L.append(f"   tp {i['tp']:.2f}  sl {i['sl']:.2f} | "
                 f"{'RUNNING' if ls['kind'] == 'open' else 'MENUNGGU TERISI'}</pre>")
        if ls["kind"] == "open":
            L.append("Sudah terisi — jangan pasang apa pun lagi sampai TP/SL kena.")
        else:
            L.append(f"Pasang <b>{act} LIMIT</b> di <b>{i['entry']:.2f}</b>, "
                     f"batalkan kalau {sisa} jam lagi belum terisi.")
        return "\n".join(L)

    scen = plan_scenarios(float(df.c.iloc[-1]), mod, ls)
    if not scen:
        return "Tidak ada level valid — tidak ada yang dipasang."

    L.append(f"<i>Harga acuan: close H4 {newest_ts:%d-%b %H:%M} = "
             f"{float(df.c.iloc[-1]):.2f}</i>")
    for s in scen:
        side = "BUY" if s["side"] == "BUY" else "SELL"
        jenis = "BUY LIMIT" if side == "BUY" else "SELL LIMIT"
        arah = "atas" if side == "BUY" else "bawah"
        L.append("")
        L.append(f"<b>{side} — pasang kalau 1 lilin H4 tutup {arah} "
                 f"{s['level']:.2f}</b>")
        L.append(f"  Jenis  : <b>{jenis}</b> di <b>{s['entry']:.2f}</b>")
        L.append(f"  TP <code>{s['tp']:.2f}</code>   SL <code>{s['sl']:.2f}</code>")
        L.append(f"  Kapan  : <i>jangan pasang sekarang.</i> Tunggu lilin H4 "
                 f"tutup di {arah} {s['level']:.2f}, baru pasang limitnya.")
        L.append(f"  Batas  : hangus {ttl * 4} jam kalau tidak tersentuh")
    return "\n".join(L)


def tg_get_updates(token: str, offset: int | None = None) -> list[dict]:
    """
    Fetch pending messages.

    Passing offset is what CONFIRMS everything before it, so Telegram stops
    re-serving it. Without it the same /status is answered on every poll.
    """
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    if offset is not None:
        url += f"?offset={offset}&timeout=0"
    try:
        with urllib.request.urlopen(url, timeout=25) as r:
            return json.loads(r.read().decode()).get("result", [])
    except Exception as e:
        print(f"getUpdates failed: {e}")
        return []


def cmd_poll() -> int:
    """
    Read Telegram messages, answer /status and /harga, then exit.

    Deliberately stateless: it only answers what you ask. It never places orders
    and never changes any trading state.
    """
    cfg = load_config()
    token, chat_id = cfg["token"], cfg["chat_id"]
    st = load_state()
    offset = st.get("tg_offset")

    updates = tg_get_updates(token, offset)
    if not updates:
        print("no new messages")
        return 0

    answered = 0
    for u in updates:
        msg = (u.get("message") or u.get("edited_message") or {})
        text = (msg.get("text") or "").strip().lower()
        cid = str((msg.get("chat") or {}).get("id", ""))
        if not text.startswith("/"):
            continue
        cmd = text.split()[0].split("@")[0]
        # Anything the robot does not know still gets an answer, so a typo never
        # looks like the robot is dead. This matters: silence is indistinguishable
        # from a broken schedule.
        if cmd in ("/mulai", "/start", "/help", "/bantuan"):
            reply = ("<b>Robot XAUUSD H4 aktif.</b>\n\n"
                     "<b>/report</b> — semua sinyal bulan ini + planning\n"
                     "<b>/plan</b> — skenario lengkap: entry, TP, SL, risiko\n"
                     "<b>/status</b> — apa yang harus saya pasang sekarang\n"
                     "<b>/posisi</b> — order mana yang jalan, mana yang harus dihapus\n\n"
                     "<code>/report 10</code> untuk bulan lain.\n"
                     "Sinyal baru saya kirim otomatis begitu lilin H4 tutup.\n"
                     "<i>Ketik perintah kapan saja, tidak perlu menunggu.</i>")
        elif cmd in ("/report", "/laporan", "/rekap", "/history", "/riwayat"):
            arg = text.split()[1] if len(text.split()) > 1 else None
            reply = build_month_report(arg)
        elif cmd in ("/posisi", "/pos", "/position", "/order", "/running"):
            reply = build_positions_report()
        elif cmd in ("/plan", "/rencana"):
            reply = build_plan_report()
        elif cmd in ("/status", "/harga", "/price", "/signal"):
            reply = build_status_report()
        else:
            reply = ("Perintah itu belum ada.\n\n"
                     "<b>/report</b> — semua sinyal bulan ini + planning\n"
                     "<b>/plan</b> — skenario entry, TP, SL, risiko\n"
                     "<b>/status</b> — apa yang harus dipasang sekarang\n"
                     "<b>/posisi</b> — order jalan / harus dihapus")
        # /status answers are priority 3: they must never look like a signal.
        send_all(reply, title="Status XAUUSD", priority=3)
        answered += 1

    # Storing the offset is what makes Telegram stop re-serving these messages,
    # so the same command can never be answered twice.
    st["tg_offset"] = updates[-1]["update_id"] + 1
    save_state(st)
    print(f"answered {answered} message(s)")
    return 0


def describe_source(bars: list[dict]) -> str:
    """
    Bar timestamps are the broker's SERVER clock, not UTC. The Maxrich feed
    writes GMT+2, so treating them as UTC made "now - last bar" come out
    negative and printed times two hours ahead. Convert server -> UTC with
    SERVER_UTC_OFFSET_H before comparing against the real clock.
    """
    off = timedelta(hours=SERVER_UTC_OFFSET_H)
    last_srv = datetime.fromtimestamp(bars[-1]["ts"], timezone.utc)
    first_srv = datetime.fromtimestamp(bars[0]["ts"], timezone.utc)
    age_h = (datetime.now(timezone.utc) - (last_srv - off)).total_seconds() / 3600
    return (f"bars {len(bars)}  {first_srv:%Y-%m-%d %H:%M} -> {last_srv:%Y-%m-%d %H:%M} "
            f"(server GMT+{SERVER_UTC_OFFSET_H:g})  age {age_h:.1f}h")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_sources() -> int:
    files = find_hst_files()
    if not files:
        print(f"No {SYMBOL}{PERIOD_MIN}.hst found under:")
        for r in MT4_ROOTS:
            print(f"  {r}")
        return 1
    print(f"Found {len(files)} {SYMBOL}{PERIOD_MIN}.hst file(s):\n")
    for f in files:
        mt = datetime.fromtimestamp(f.stat().st_mtime)
        size = f.stat().st_size
        try:
            bars = read_feed(f)
            info = describe_source(bars)
        except Exception as e:
            info = f"PARSE ERROR: {e}"
        print(f"  {f}")
        print(f"    modified {mt:%Y-%m-%d %H:%M}   {size:,} bytes")
        print(f"    {info}\n")
    print(f"Using freshest: {files[0]}")
    return 0


def cmd_test() -> int:
    cfg = load_config()
    mod = load_locked()
    bars, hst, _src = read_bars()
    msg = (
        "<b>XAUUSD locked H4 · test message</b>\n\n"
        f"Method : {mod.METHOD_ID} v{mod.METHOD_VERSION}\n"
        f"Lock   : OK ({mod._lock_payload()[:16]}...)\n"
        f"Source : {hst.name}\n"
        f"Bars   : {describe_source(bars)}\n\n"
        f"<i>This is a connectivity test. No trade signal.</i>"
    )
    ok = tg_send(cfg["token"], cfg["chat_id"], msg)
    print("Test message " + ("SENT" if ok else "FAILED"))
    return 0 if ok else 1


def cmd_status() -> int:
    mod = load_locked()
    bars, hst, _src = read_bars()
    st = load_state()
    cfg = None
    try:
        cfg = load_config()
    except SystemExit:
        pass

    print("=" * 68)
    print(f"{mod.METHOD_ID} v{mod.METHOD_VERSION}   [{mod.TIMEFRAME}]")
    print("=" * 68)
    print(f"lock       : {mod._lock_payload()[:24]}...")
    print(f"source     : {hst}")
    print(f"bars       : {describe_source(bars)}")
    print(f"telegram   : {'configured (' + cfg['source'] + ')' if cfg and cfg.get('chat_id') else 'NOT configured'}")
    _last_dt = datetime.fromtimestamp(bars[-1]["ts"], timezone.utc)
    _last_ago = (datetime.now(timezone.utc)
                 - (_last_dt - timedelta(hours=SERVER_UTC_OFFSET_H))).total_seconds() / 3600
    print(f"last bar   : {_last_dt:%Y-%m-%d %H:%M} server "
          f"({_last_ago:.1f}h ago)")
    print(f"last signal: {st.get('last_signal_key')}")
    print(f"sent total : {len(st.get('sent', []))}")
    if st.get("open_position"):
        print(f"open pos   : {st['open_position']}")
    return 0


def cmd_check() -> int:
    mod = load_locked()
    bars, hst, _src = read_bars()
    r = scan(mod, bars, full=True)

    print("=" * 68)
    print("CHECK - no Telegram, no state change")
    print("=" * 68)
    print(f"source : {hst.name}   {describe_source(bars)}")
    print(f"trades replayed from {mod.START_DEFAULT}: {r['trades']}")
    if r["new"]:
        print(f"\nNot yet announced: {len(r['new'])}")
        for t in r["new"][-5:]:
            print(f"  {t['action']:<4} entry {t['entry']:.2f}  "
                  f"TP {t['tp']:.2f}  SL {t['sl']:.2f}  "
                  f"level {t['level']:.2f}  {t['entry_time']}")
    else:
        print("\nNo unannounced trades. Nothing to send.")
    if r["position"]:
        p = r["position"]
        print(f"\nMost recent trade in history:")
        print(f"  {p['action']} entry {p['entry']:.2f} -> exit {p['exit_time']} "
              f"= {p['result']}  ({p['pl_usd']:+.2f})")
    return 0


# ---------------------------------------------------------------------------
# Per-bar briefing (the message the user asked for: one verdict per H4 close)
# ---------------------------------------------------------------------------

QUIET_FROM = 23   # WIB hour after which 'nothing happened' briefings are held
QUIET_TO = 7      # WIB hour before which they are held


def _bar_close_wib(ts) -> datetime:
    """Server bar timestamp -> the wall clock in WIB when that bar CLOSED."""
    import pandas as pd
    close_srv = pd.Timestamp(ts) + pd.Timedelta(hours=4)
    # server clock is SERVER_UTC_OFFSET_H ahead of UTC; local is UTC+7
    return (close_srv.to_pydatetime()
            - timedelta(hours=SERVER_UTC_OFFSET_H)
            + timedelta(hours=7))


def _in_quiet_hours() -> bool:
    h = datetime.now().hour
    return h >= QUIET_FROM or h < QUIET_TO


def build_bar_briefing(regime: int = 7) -> tuple[str, str, str]:
    """
    What to send right after an H4 bar closes.

    Returns (kind, title, text). kind is one of:
      signal | filled | closed | expired | waiting | running | stale

    The whole point is that the user never has to wonder: every H4 close gets an
    answer, and the answer always says what to do about the NEXT bar. 'waiting'
    (nothing happened) is the only kind that may be withheld during quiet hours;
    everything else asks the user to act and always goes out.
    """
    import pandas as pd

    mod = load_locked()
    bars, hst, _src = read_bars()
    df = bars_to_frame(bars)
    st = load_state()

    newest_ts = pd.Timestamp(df.ts.iloc[-1])
    newest_close = float(df.c.iloc[-1])
    off = timedelta(hours=SERVER_UTC_OFFSET_H)
    last_srv = datetime.fromtimestamp(bars[-1]["ts"], timezone.utc) - off
    age_h = (datetime.now(timezone.utc) - last_srv).total_seconds() / 3600

    # --- 0. data dead: say so once, then stay quiet ------------------------
    if age_h > MAX_DATA_AGE_H:
        prev = st.get("stale_notified_for")
        if prev == f"{newest_ts:%Y-%m-%d %H:%M}":
            return "stale", "", ""          # already warned for this bar
        st["stale_notified_for"] = f"{newest_ts:%Y-%m-%d %H:%M}"
        save_state(st)
        txt = (f"🔴 <b>DATA MATI — jangan ambil keputusan</b>\n\n"
               f"Lilin terakhir {newest_ts:%d-%b %H:%M} server, sudah "
               f"{fmt_age(age_h)} lalu.\n"
               f"MT4 kemungkinan tertutup atau belum login.\n\n"
               f"Sinyal otomatis saya hentikan sampai data segar lagi.\n"
               f"Buka MT4, login, lalu ketik /status.")
        return "stale", "DATA MATI XAUUSD", txt
    st.pop("stale_notified_for", None)

    ls = live_state(mod, df)
    ttl = ls["ttl"]
    ea = read_ea_status()
    # The EA's bid/ask describes the CURRENT market. It is only meaningful when
    # the newest bar is the one still forming; on a replay of older bars it would
    # quote today's price next to a two-day-old plan, which is worse than useless.
    live_px = (ea.get("bid")
               if ea.get("fresh") and age_h <= 4.5 else None)

    # --- 1. something just finished? ---------------------------------------
    # A trade whose exit bar IS the newest bar (or the one before it, since the
    # driver may fire a minute after the close) is news worth telling.
    tr = track_orders(mod, df)
    newest_i = tr["newest_i"]

    # Is there a brand-new signal on this bar? Checked FIRST, because on a bar
    # where a trade closes the method immediately re-arms (a fresh breakout can
    # happen the very next bar), and in that case the signal is the actionable
    # news - the exit is already history.
    #
    # Deliberately NOT scan(): scan compares against live_state(), which only
    # knows what is open RIGHT NOW. A signal born on an older bar that already
    # exited (or is several bars back) is invisible to it, so scan would keep
    # offering stale entries as 'new'. track_orders() replays every signal with
    # its own timestamp and state, which is what "born on this bar" needs.
    for x in tr["rows"]:
        if pd.Timestamp(x["sig_ts"]) != newest_ts:
            continue
        k = sig_key({"action": x["type"],
                     "entry_time": pd.Timestamp(x["sig_ts"]),
                     "level": x["level"]})
        seen = st.setdefault("sent", [])
        if k in seen or k == st.get("last_signal_key"):
            continue
        seen.append(k)
        st["sent_total"] = int(st.get("sent_total", 0)) + 1
        st["last_signal_key"] = k
        st["open_position"] = {
            "action": x["type"], "entry": x["entry"], "tp": x["tp"],
            "sl": x["sl"], "signal_time": str(x["sig_ts"]), "level": x["level"],
        }
        save_state(st)
        sig = {"action": x["type"], "entry": x["entry"], "tp": x["tp"],
               "sl": x["sl"], "level": x["level"],
               "tp_level": x.get("tp_level"),
               "entry_time": pd.Timestamp(x["sig_ts"]),
               "exit_time": None,
               "result": "OPEN" if x["state"] == "terisi" else "PENDING",
               "pl_usd": 0.0, "pl_pips": 0.0, "bars": 0}
        return "signal", "", fmt_signal(sig, df.ts.iloc[-1])

    finished = [x for x in tr["rows"]
                if x.get("exit_i") in (newest_i, newest_i - 1)
                and x["state"] in ("TP", "SL")]
    for x in finished:
        k = f"exit|{x['sig_ts']}|{x['exit_ts']}|{x['state']}"
        seen = st.setdefault("notified_exits", [])
        if k in seen:
            continue
        seen.append(k)
        st["notified_exits"] = seen[-40:]
        save_state(st)
        act = "BUY" if x["type"] == "Buy" else "SELL"
        if x["state"] == "TP":
            pl = abs(x["tp"] - x["entry"])
            head = (f"✅ <b>{act} {x['entry']:.2f} — KENA TP</b>\n\n"
                    f"Tutup di <code>{x['tp']:.2f}</code>.\n"
                    f"<b>Hasil +{pl:.2f} USD</b> per 1.00 lot.\n"
                    f"Durasi {max(1, (x['exit_i'] - x.get('fill_i', x['exit_i']))) * 4} jam.")
        else:
            pl = abs(x["entry"] - x["sl"])
            head = (f"❌ <b>{act} {x['entry']:.2f} — KENA SL</b>\n\n"
                    f"Tutup di <code>{x['sl']:.2f}</code>.\n"
                    f"<b>Hasil −{pl:.2f} USD</b> per 1.00 lot.\n"
                    f"Kerugian ini sudah diperhitungkan metode — "
                    f"jangan balas dendam buka posisi baru.")
        # A trade that just closed is ALSO the answer to "what now?", so the
        # forward-looking part is never dropped - only the bare 'waiting' header
        # would be redundant here.
        scen = plan_scenarios(newest_close, mod, ls)
        tail = ["", "Metode jeda 1 lilin dulu. <b>Jangan pasang order baru sekarang.</b>"]
        if scen:
            nxt = newest_ts + pd.Timedelta(hours=4)
            tail.append("")
            tail.append(f"<b>Yang ditunggu di lilin {nxt:%H:%M}:</b>")
            for s in scen:
                up = s["side"] == "BUY"
                d = abs(s["level"] - newest_close)
                tail.append(f"  {'🟢' if up else '🔴'} tutup "
                            f"<b>{'di atas' if up else 'di bawah'} "
                            f"{s['level']:.2f}</b> → {s['side']} limit "
                            f"{s['entry']:.2f} <i>({d:.2f} poin)</i>")
            tail.append("  ⚪ tutup di antaranya → tidak ada apa-apa")
        return "closed", f"HASIL {act} XAUUSD {'TP' if x['state'] == 'TP' else 'SL'}", \
            head + "\n" + "\n".join(tail)

    # --- 2. a pending order that expired unfilled? -------------------------
    if ls["kind"] == "flat":
        for x in tr["rows"]:
            if x["state"] != "batal":
                continue
            k = f"expired|{x['sig_ts']}"
            seen = st.setdefault("notified_exits", [])
            if k in seen or x.get("exit_i") != newest_i:
                continue
            seen.append(k)
            st["notified_exits"] = seen[-40:]
            save_state(st)
            act = "BUY" if x["type"] == "Buy" else "SELL"
            txt = (f"❌ <b>{act} LIMIT {x['entry']:.2f} — HANGUS</b>\n\n"
                   f"Sudah {ttl * 4} jam tidak tersentuh. "
                   f"<b>Hapus ordernya di MT4.</b>\n\n"
                   f"Ini <b>bukan kerugian</b> — tidak ada uang keluar, "
                   f"cuma tidak jadi trading.")
            scen = plan_scenarios(newest_close, mod, ls)
            if scen:
                txt += "\n\n<b>Yang ditunggu sekarang:</b>"
                for s in scen:
                    txt += (f"\n  {s['side']} kalau tutup "
                            f"{'di atas' if s['side'] == 'BUY' else 'di bawah'} "
                            f"{s['level']:.2f}")
            return "expired", f"HANGUS {act} XAUUSD", txt

    # --- 3. (signal check moved above: it must win over an exit note) ------

    # --- 4. position open: short 'still running' note ----------------------
    if ls["kind"] == "open":
        i = ls["info"]
        act = "BUY" if i["type"] == "Buy" else "SELL"
        txt = [f"🟢 <b>{act} {i['entry']:.2f} masih berjalan</b>",
               f"TP <code>{i['tp']:.2f}</code> · SL <code>{i['sl']:.2f}</code>"]
        if live_px:
            txt.append(f"Harga sekarang <b>{live_px:.2f}</b> — "
                       f"<b>{live_px - i['entry']:+.2f}</b> dari entry.")
        txt.append(f"Sudah {ls['bars_used'] * 4} jam berjalan.")
        txt.append("Kalau TP/SL kena, saya kabari.")
        return "running", f"POSISI {act} JALAN", "\n".join(txt)

    # --- 5. pending open: remind the window -------------------------------
    if ls["kind"] == "pending":
        i = ls["info"]
        act = "BUY" if i["type"] == "Buy" else "SELL"
        sisa_h = max(0, (ttl - ls["bars_used"]) * 4)
        txt = [f"⏳ <b>{act} LIMIT {i['entry']:.2f} — belum terisi</b>",
               f"Sisa waktu <b>{sisa_h} jam</b>.",
               f"TP <code>{i['tp']:.2f}</code> · SL <code>{i['sl']:.2f}</code>"]
        if live_px:
            d = live_px - i["entry"]
            txt.append(f"Harga sekarang {live_px:.2f} — masih "
                       f"{abs(d):.2f} poin "
                       f"{'di atas' if d > 0 else 'di bawah'} entry.")
        txt.append("Biarkan ordernya. Kalau hangus, saya kabari untuk hapus.")
        return "filled", f"{act} LIMIT MENUNGGU", "\n".join(txt)

    # --- 6. nothing at all: the 'waiting' briefing ------------------------
    scen = plan_scenarios(newest_close, mod, ls)
    why = []
    if len(df) >= 2:
        prev_c = float(df.c.iloc[-2])
        why.append(f"Lilin {newest_ts:%H:%M} tutup <b>{newest_close:.2f}</b> "
                   f"(sebelumnya {prev_c:.2f}) — tidak menembus garis mana pun.")
    else:
        why.append(f"Lilin tutup <b>{newest_close:.2f}</b> — tidak ada penembusan.")

    txt = [f"📊 <b>XAUUSD · lilin {newest_ts:%d-%b %H:%M} tutup</b>", ""]
    txt += why
    txt.append("Tidak ada sinyal. <b>Jangan pasang order apa pun.</b>")
    if live_px:
        txt.append(f"Harga sekarang <b>{live_px:.2f}</b>.")
    if scen:
        nxt = newest_ts + pd.Timedelta(hours=4)
        txt.append("")
        txt.append(f"<b>Yang ditunggu di lilin {nxt:%H:%M}:</b>")
        for s in scen:
            up = s["side"] == "BUY"
            emo = "🟢" if up else "🔴"
            d = abs(s["level"] - (live_px or newest_close))
            txt.append(f"  {emo} tutup <b>{'di atas' if up else 'di bawah'} "
                       f"{s['level']:.2f}</b> → {s['side']} limit "
                       f"{s['entry']:.2f} <i>({d:.2f} poin)</i>")
        txt.append("  ⚪ tutup di antaranya → tidak ada apa-apa")

    return "waiting", f"XAUUSD {newest_ts:%H:%M}", "\n".join(txt)


def cmd_briefing() -> int:
    """
    Driver entry: send the per-bar briefing unless it is a quiet-hours 'waiting'.

    Runs are gated on the bar itself, not the clock, so a 5-minute schedule can
    call this freely: each bar produces at most one message.
    """
    # Claim the bar BEFORE building the message. build_bar_briefing() saves its
    # own bookkeeping (which exits were announced), and that save would happily
    # overwrite a marker written afterwards - which is exactly how the same
    # 'nothing happened' note went out on every run.
    st = load_state()
    newest = st.get("last_bar")
    if st.get("briefed_bar") == newest:
        print(f"  briefing: already sent for bar {newest}")
        return 0

    kind, title, text = build_bar_briefing()
    if not text:
        print(f"  briefing: nothing to say ({kind})")
        return 0

    if kind == "waiting" and _in_quiet_hours():
        print(f"  briefing: {kind} suppressed (quiet hours "
              f"{QUIET_FROM:02d}:00-{QUIET_TO:02d}:00 WIB)")
        return 0

    prio = 5 if kind in ("signal", "closed") else 3
    res = send_all(text, title=title, priority=prio)
    ok = res["telegram"] or res["ntfy"]
    print(f"  briefing {kind}: {'SENT' if ok else 'FAILED'} "
          f"(telegram={res['telegram']} ntfy={res['ntfy']})")
    if ok:
        st = load_state()          # re-read: build_bar_briefing may have saved
        st["briefed_bar"] = newest
        save_state(st)
    return 0


def cmd_run(dry: bool = False) -> int:
    return _run(dry)


def _run(dry: bool = False) -> int:
    mod = load_locked()
    cfg = None
    try:
        cfg = load_config()
    except SystemExit as e:
        print(f"WARNING: {e}\nSignals will print to console only.")

    bars, hst, _src = read_bars()
    st = load_state()

    # --- data-freshness gate ------------------------------------------------
    # A signal is only worth sending if the bar it came from is recent. When MT4
    # or the EA is down, read_bars() still returns something (the .hst fallback,
    # possibly days old), and the method happily computes trades on it. Sending
    # those would tell the user to place a limit around a price the market left
    # long ago. Refuse, say why, and let /status carry the warning instead.
    off = timedelta(hours=SERVER_UTC_OFFSET_H)
    last_srv = datetime.fromtimestamp(bars[-1]["ts"], timezone.utc) - off
    data_age_h = (datetime.now(timezone.utc) - last_srv).total_seconds() / 3600
    if data_age_h > MAX_DATA_AGE_H:
        print(f"  DATA STALE: last bar {last_srv:%Y-%m-%d %H:%M} server "
              f"({data_age_h:.1f}h old) - no signal sent")
        print(f"  (limit {MAX_DATA_AGE_H:g}h; source {hst.name})")
        print("  Check MT4 is open, logged in, and the EA is on the chart.")
        dbg = load_state()
        dbg["data_stale"] = {
            "age_h": round(data_age_h, 1),
            "last_bar": f"{last_srv:%Y-%m-%d %H:%M}",
            "source": hst.name,
            "checked": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        if not dry:
            save_state({**dbg})
        return 0
    st.pop("data_stale", None)
    r = scan(mod, bars)
    if r.get("state"):
        st.update(r["state"])
        st.pop("data_stale", None)

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{stamp}] {hst.name}  {describe_source(bars)}")
    print(f"  replayed {r['trades']} trades from history; "
          f"{len(r['new'])} new signal(s)")

    if not r["new"]:
        print("  nothing to send")
        st["last_bar"] = r["last_bar"]
        save_state(st)
        return 0

    sent_ok = 0
    for t in r["new"]:
        # Record the signal in state BEFORE sending it. The old order sent first
        # and saved last, so any exception between the two (a malformed "sent"
        # entry, a crash, a closed console) meant the same signal was re-sent on
        # every following run, every 5 minutes, indefinitely. Claiming it first
        # turns a failed send into a missed message - visible and harmless -
        # instead of an infinite repeat of a stale one.
        k = sig_key(t)
        claimed = False
        if not dry:
            already = (k in st["sent"]) or (k == st.get("last_signal_key"))
            if not already:
                st["sent"].append(k)
                st["sent_total"] = int(st.get("sent_total", 0)) + 1
                st["last_signal_key"] = k
                st["open_position"] = {
                    "action": t["action"], "entry": t["entry"], "tp": t["tp"],
                    "sl": t["sl"], "signal_time": str(t["entry_time"]),
                    "level": t["level"],
                }
                save_state(st)
                claimed = True
            else:
                print(f"  already announced, skipping: {t['action']} "
                      f"{t['entry']:.2f}")
                continue

        msg = fmt_signal(t, r["last_bar"])
        # priority 5 = urgent: pops over other apps, can beat Do Not Disturb.
        # Only ever used for a real signal, so 'urgent' keeps its meaning.
        act = "BUY" if t["action"] == "Buy" else "SELL"
        res = send_all(msg, title=f"SINYAL {act} XAUUSD · entry {t['entry']:.2f}",
                       priority=5, tags=["chart_with_upwards_trend"], dry=dry)
        ok = res["telegram"] or res["ntfy"]
        print(f"  {'SENT' if ok else 'FAILED'}: {t['action']} "
              f"{t['entry']:.2f} TP {t['tp']:.2f} SL {t['sl']:.2f} "
              f"(telegram={res['telegram']} ntfy={res['ntfy']})")
        if not ok and claimed:
            # Delivery failed after we claimed it. Put it back so the next run
            # retries - and so a real signal is never silently swallowed.
            try:
                st["sent"].remove(k)
                st["sent_total"] = max(0, int(st.get("sent_total", 1)) - 1)
                if st.get("last_signal_key") == k:
                    st["last_signal_key"] = st["sent"][-1] if st["sent"] else None
                st.pop("open_position", None)
                save_state(st)
            except ValueError:
                pass
        if ok and not dry:
            log_signal({**{k2: (str(v) if k2.endswith("_time") else v)
                           for k2, v in t.items()}, "announced": stamp})
            sent_ok += 1

    st["last_bar"] = r["last_bar"]
    if not dry:
        save_state(st)
    print(f"  done: {sent_ok} sent")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="XAUUSD locked H4 -> Telegram")
    ap.add_argument("--run", action="store_true", help="scan and send new signals")
    ap.add_argument("--check", action="store_true", help="verdict only")
    ap.add_argument("--test", action="store_true", help="send a Telegram test")
    ap.add_argument("--status", action="store_true", help="state and source info")
    ap.add_argument("--sources", action="store_true", help="find MT4 history files")
    ap.add_argument("--poll", action="store_true",
                    help="answer /status commands sent to the bot")
    ap.add_argument("--briefing", action="store_true",
                    help="send the per-bar verdict (one message per H4 close)")
    ap.add_argument("--dry", action="store_true", help="with --run: do not send")
    a = ap.parse_args(argv)

    if a.sources:
        return cmd_sources()
    if a.test:
        return cmd_test()
    if a.status:
        return cmd_status()
    if a.check:
        return cmd_check()
    if a.poll:
        return cmd_poll()
    if a.briefing:
        return cmd_briefing()
    if a.run:
        return _run(a.dry)

    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
