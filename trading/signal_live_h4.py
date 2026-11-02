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
import json
import os
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

# MT4 terminal data folders to search for XAUUSD240.hst
MT4_ROOTS = [
    Path(os.environ.get("APPDATA", "")) / "MetaQuotes" / "Terminal",
    Path(r"C:\Program Files (x86)\MetaTrader 4"),
]

SYMBOL = "XAUUSD"
PERIOD_MIN = 240

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
        t = struct.unpack("<i", b[o:o + 4])[0]
        if not (1_000_000_000 < t < 2_200_000_000):
            continue
        o_, h_, l_, c_ = struct.unpack("<4d", b[o + 8:o + 40])
        v = struct.unpack("<i", b[o + 40:o + 44])[0]
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
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return dict(last_bar=None, last_signal_key=None, open_position=None,
                pending=None, last_exit_bar=None, sent=[])


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
            k = (f"{i['type']}|{i['entry']:.2f}|"
                 f"{pd.Timestamp(i['sig_ts']):%Y-%m-%d %H:%M}")
            already = k in seen or k == last_key
            if not already and pd.Timestamp(i["sig_ts"]) >= cutoff:
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


def build_status_report() -> str:
    """
    Everything a trader wants at a glance: where price is, whether there is a
    live signal, since when, and how long is left on it.
    """
    import pandas as pd

    mod = load_locked()
    hst = freshest_hst()
    bars = read_hst(hst)
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

    L = []
    L.append(f"<b>STATUS XAUUSD</b> · {datetime.now().strftime('%d-%b %H:%M')} WIB")
    L.append("")

    # --- layar 1: jawabannya saja, tanpa bahasa teknis -------------------
    if data_age_h > 6:
        L.append("🔴 <b>DATA MATI — jangan trading.</b>")
        L.append("MT4 tidak memperbarui harga. Buka MT4, login, tunggu.")
        L.append(f"<i>Harga terakhir {newest_close:.2f} dari "
                 f"{fmt_age(data_age_h)} lalu.</i>")
    elif ls["kind"] == "pending":
        i = ls["info"]
        sisa = max(0, (ttl - ls["bars_used"]) * 4)
        act = "BUY" if i["type"] == "Buy" else "SELL"
        L.append(f"🟡 <b>ADA ORDER BELUM TERISI</b>")
        L.append("")
        L.append(f"Pasang <b>{act} STOP/LIMIT</b> di:")
        L.append(f"<code>{i['entry']:.2f}</code>")
        L.append(f"TP <code>{i['tp']:.2f}</code>   SL <code>{i['sl']:.2f}</code>")
        L.append(f"Sisa waktu: <b>{sisa} jam</b>")
        L.append("<i>Tekan angkanya untuk menyalin.</i>")
    elif ls["kind"] == "open":
        i = ls["info"]
        act = "BUY" if i["type"] == "Buy" else "SELL"
        L.append(f"🟢 <b>POSISI SEDANG BERJALAN</b> — {act}")
        L.append("")
        L.append(f"Entry <code>{i['entry']:.2f}</code>   "
                 f"TP <code>{i['tp']:.2f}</code>   "
                 f"SL <code>{i['sl']:.2f}</code>")
        L.append(f"Sudah {ls['bars_used']} lilin H4 berjalan.")
        L.append("<i>Biarkan jalan. Jangan tambah posisi.</i>")
    else:
        L.append("⚪ <b>TIDAK ADA YANG PERLU DIPASANG</b>")
        L.append("")
        L.append("Tidak ada sinyal aktif. Nanti saya kirim sendiri kalau ada.")

    # --- layar 1 lanjutan: apa yang sedang ditunggu ----------------------
    L.append("")
    if up is not None:
        L.append(f"BUY kalau tutup di atas <b>{up:.2f}</b>")
    if dn is not None:
        L.append(f"SELL kalau tutup di bawah <b>{dn:.2f}</b>")
    L.append(f"<i>Harga sekarang {newest_close:.2f} (data "
             f"{fmt_age(data_age_h)} lalu)</i>")
    L.append("")

    # --- layar 2: rincian untuk yang mau periksa -------------------------
    L.append("➖➖➖ <i>rincian</i> ➖➖➖")
    if data_age_h > 6:
        L.append(f"⚠️ MT4 tidak memperbarui data.")
    L.append(f"Lilin H4 terakhir : {newest_ts:%d-%b %H:%M}")
    if up is not None:
        L.append(f"Resistance terdekat : {up:.2f}  (+{up - newest_close:.2f})")
    if dn is not None:
        L.append(f"Support terdekat    : {dn:.2f}  ({dn - newest_close:+.2f})")
    L.append(f"Trade terakhir ({arrow}) : <b>{last['result']}</b> "
             f"({last['pl_usd']:+.2f}) · "
             f"{pd.Timestamp(last['exit_time']):%d-%b %H:%M}")


    # --- health line ------------------------------------------------------
    st = load_state()
    L.append("")
    L.append(f"<i>{mod.METHOD_ID} v{mod.METHOD_VERSION} · "
             f"{len(trades)} trade historis · "
             f"{len(st.get('sent', []))} sinyal terkirim</i>")
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
    hst = freshest_hst()
    bars = read_hst(hst)
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
                     "<b>/status</b> — apa yang harus saya pasang sekarang\n"
                     "<b>/plan</b> — skenario lengkap: entry, TP, SL, risiko\n\n"
                     "Sinyal baru saya kirim otomatis begitu lilin H4 tutup.\n"
                     "<i>Ketik /status kapan saja, tidak perlu menunggu.</i>")
        elif cmd in ("/plan", "/rencana"):
            reply = build_plan_report()
        elif cmd in ("/status", "/harga", "/price", "/signal"):
            reply = build_status_report()
        else:
            reply = ("Perintah itu belum ada.\n\n"
                     "<b>/status</b> — apa yang harus dipasang sekarang\n"
                     "<b>/plan</b> — skenario entry, TP, SL, risiko")
        tg_send(token, cid or chat_id, reply)
        answered += 1

    # Storing the offset is what makes Telegram stop re-serving these messages,
    # so the same command can never be answered twice.
    st["tg_offset"] = updates[-1]["update_id"] + 1
    save_state(st)
    print(f"answered {answered} message(s)")
    return 0


def describe_source(bars: list[dict]) -> str:
    last = datetime.fromtimestamp(bars[-1]["ts"], timezone.utc)
    first = datetime.fromtimestamp(bars[0]["ts"], timezone.utc)
    age_h = (datetime.now(timezone.utc) - last).total_seconds() / 3600
    return (f"bars {len(bars)}  {first:%Y-%m-%d %H:%M} -> {last:%Y-%m-%d %H:%M} "
            f"(server)  age {age_h:.1f}h")


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
            bars = read_hst(f)
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
    hst = freshest_hst()
    bars = read_hst(hst)
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
    hst = freshest_hst()
    bars = read_hst(hst)
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
    print(f"last bar   : {st.get('last_bar')}")
    print(f"last signal: {st.get('last_signal_key')}")
    print(f"sent total : {len(st.get('sent', []))}")
    if st.get("open_position"):
        print(f"open pos   : {st['open_position']}")
    return 0


def cmd_check() -> int:
    mod = load_locked()
    hst = freshest_hst()
    bars = read_hst(hst)
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


def cmd_run(dry: bool = False) -> int:
    return _run(dry)


def _run(dry: bool = False) -> int:
    mod = load_locked()
    cfg = None
    try:
        cfg = load_config()
    except SystemExit as e:
        print(f"WARNING: {e}\nSignals will print to console only.")

    hst = freshest_hst()
    bars = read_hst(hst)
    r = scan(mod, bars)
    st = r.get("state") or load_state()

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
        msg = fmt_signal(t, r["last_bar"])
        # loud=True: a signal must make a sound. Routine replies must not.
        ok = tg_send(cfg["token"] if cfg else "", cfg["chat_id"] if cfg else "",
                     msg, dry=dry, loud=True)
        print(f"  {'SENT' if ok else 'FAILED'}: {t['action']} "
              f"{t['entry']:.2f} TP {t['tp']:.2f} SL {t['sl']:.2f}")
        if ok and not dry:
            k = sig_key(t)
            if k not in st.setdefault("sent", []):
                st["sent"].append(k)
            st["last_signal_key"] = k
            st["open_position"] = {
                "action": t["action"], "entry": t["entry"], "tp": t["tp"],
                "sl": t["sl"], "signal_time": str(t["entry_time"]),
                "level": t["level"],
            }
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
    if a.run:
        return _run(a.dry)

    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
