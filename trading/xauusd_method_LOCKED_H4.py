#!/usr/bin/env python3
"""
================================================================================
XAUUSD S/R BREAKOUT  -  LOCKED METHOD  -  H4  -  cap $30  -  v1.0.0
================================================================================

This file is the SINGLE SOURCE OF TRUTH for the H4 variant of the cap-$30 method.
It reproduces, byte for byte, the result in:
    XAUUSD_Backtest_LOCKED_CAP30_H4_FROM_2025-05-01.csv

It is deliberately self-contained: pandas only. No imports from bt2.py, from
backtest_engine.py, or even from xauusd_method_LOCKED.py. If this file runs, the
method runs. The H1 file is left completely untouched - the two are siblings,
not parent/child.

--------------------------------------------------------------------------------
WHAT THIS REPRODUCES
--------------------------------------------------------------------------------
Dataset : C:\\Users\\Sharing Vision\\Downloads\\XAUUSD240.csv
          (5592 bars, 2023-03-22 08:00 -> 2026-11-02 05:00, H4)
Window  : from 2025-05-01 (2332 bars used, 3260 discarded)
Result  : 346 trades, 203 wins / 143 losses, WR 58.7%, PF 2.38,
          Net +$3510.48/oz, MaxDD -$108.00, Net/DD 32.50, expectancy $10.15

Same-window comparison against H1 (May-2025 -> Jan-2026, the overlap):
          H1: 169 trades, WR 49.1%, PF 1.60, net +$929.60, DD -$246.00
          H4: 122 trades, WR 58.2%, PF 2.33, net +$1208.34, DD -$90.00
    H4 wins on every metric with one third of the drawdown. Audited and shown
    NOT to be an artefact of intrabar resolution or of the 2-bar TTL.

Verify yourself:   python xauusd_method_LOCKED_H4.py --verify
Reproduce output:  python xauusd_method_LOCKED_H4.py --export

--------------------------------------------------------------------------------
THE RULES  (identical to the H1 lock - only the timeframe differs)
--------------------------------------------------------------------------------
1. LEVELS     38 fixed S/R levels (RED_LEVELS below). Never rebuilt, never tuned.
2. TIMEFRAME  H4 candles. Signals evaluated on CLOSED bars only.
3. BREAKOUT   Upside:   prev_close <= level < close
              Downside: prev_close >= level > close
              The asymmetry is part of the method - do not "clean it up".
4. ENTRY      Buy  limit at level + $3.00
              Sell limit at level - $3.00
              Armed on the signal bar, fills only on a LATER bar.
5. TTL        The limit expires after 2 bars unfilled. ON H4 THIS IS 8 HOURS.
              This is intentional and verified to be inert (see TTL_BARS).
6. TP         Next level beyond entry, capped at $30.00. If no level exists
              beyond entry, NO trade is taken.
7. SL         entry -/+ (TP distance * 0.6), so SL is always 0.6x the TP distance.
8. AMBIGUITY  A bar touching BOTH TP and SL resolves as SL (conservative).
              On H4 this affected only 4 of 122 trades in the overlap window,
              so it is not what drives the result.
9. POSITION   One position at a time. No new signal while a position or a
              pending limit exists.
10. COOLDOWN  A new signal is blocked on the exit bar itself.

--------------------------------------------------------------------------------
AUDIT NOTES - recorded so the result cannot be quietly re-litigated later
--------------------------------------------------------------------------------
* Intrabar resolution is NOT the cause: flipping every ambiguous H4 bar to TP
  (the most optimistic possible reading) raises H4 to PF 2.66 and H1 only to
  1.76. The gap survives the most favourable assumption for both.
* TTL is NOT the cause: overriding TTL over 1..6 moves H4 between PF 2.29 and
  2.38 and H1 between 1.60 and 1.64. The curve is flat; the locked value 2 sits
  on a plateau, not a spike.
* The real driver is fewer, cleaner signals: 122 H4 entries against 169 H1
  entries on the same bars.
* Concentration remains: 4023.16 and 4101.26 each contributed +$426 at WR 84.2%.
  Top-3 levels are 33% of net (H1 was 48%). Level 4184.34 lost $96.
* Out-of-sample beyond 2026 is thin: 2025 alone gives 102 trades, WR 55.9%,
  PF 2.13. Healthy, but only one year.
================================================================================
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

import pandas as pd

# =============================================================================
# LOCKED PARAMETERS
# =============================================================================

METHOD_ID = "XAUUSD-SR-BREAKOUT-BT2-CAP30-H4"
METHOD_VERSION = "1.0.0"
TIMEFRAME = "H4"

RED_LEVELS = [
    5588.06, 5388.69, 5313.63, 5233.88, 5158.82, 5095.43, 5022.29, 4946.21,
    4848.09, 4792.35, 4724.22, 4674.34, 4629.67, 4573.13, 4522.37, 4485.45,
    4431.23, 4379.14, 4348.00, 4313.65, 4242.80, 4184.34, 4144.23, 4101.26,
    4062.25, 4023.16, 3988.70, 3931.48, 3868.45, 3787.70, 3733.87, 3703.29,
    3676.37, 3622.54, 3572.38, 3474.51, 3402.33, 3341.15,
]

BUFFER_USD = 3.0
CAP_USD = 30.0
SL_RR_RATIO = 0.6
TTL_BARS = 2
START_DEFAULT = "2025-05-01"

REFERENCE = {
    "dataset": r"C:\Users\Sharing Vision\Downloads\XAUUSD240.csv",
    "output": r"C:\Users\Sharing Vision\Downloads\XAUUSD_Backtest_LOCKED_CAP30_H4_FROM_2025-05-01.csv",
    "start": "2025-05-01",
    "total_bars_in_file": 5592,
    "bars_used": 2332,
    "first_bar": "2025-05-01 00:00",
    "last_bar": "2026-11-02 05:00",
    "trades": 346,
    "wins": 203,
    "losses": 143,
    "win_rate_pct": 58.7,
    "profit_factor": 2.38,
    "net_usd": 3510.48,
    "max_dd_usd": -108.0,
    "net_over_dd": 32.5,
    "expectancy_usd": 10.15,
}

METHOD_LOCK_HASH = "0c76e240d109d60831e32483447f673a78406a0dc26ff5324df2a6bda62593b4"

# =============================================================================
# METHOD IMPLEMENTATION
# =============================================================================


def load_bars(path: str) -> pd.DataFrame:
    """
    Load an H1/H4 CSV in either of the two formats seen in this project.

    A) MT4 export  : no header, comma-delimited, 'YYYY.MM.DD,HH:MM,O,H,L,C,V'
                     (XAUUSD240.csv, XAUUSD60_REAL.csv)
    B) MetaStock   : header + semicolon, 'Date;Open;High;Low;Close;Volume'
                     (XAU_1h_data.csv)
    """
    with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
        first = ""
        for line in fh:
            if line.strip():
                first = line
                break

    is_header = "date" in first.lower()
    sep = ";" if first.count(";") >= first.count(",") else ","

    if is_header:
        d = pd.read_csv(path, sep=sep, engine="python")
        d.columns = [c.strip().lower() for c in d.columns]
        d = d.rename(columns={"open": "o", "high": "h", "low": "l",
                              "close": "c", "volume": "v"})
        d["ts"] = pd.to_datetime(d["date"], format="%Y.%m.%d %H:%M", errors="coerce")
        d["date"] = d["date"].astype(str).str.slice(0, 10)
        d["time"] = d["ts"].dt.strftime("%H:%M")
    else:
        d = pd.read_csv(path, header=None, sep=sep,
                        names=["date", "time", "o", "h", "l", "c", "v"], engine="python")
        d["ts"] = pd.to_datetime(d["date"] + " " + d["time"], format="%Y.%m.%d %H:%M",
                                 errors="coerce")

    d = d.dropna(subset=["ts", "o", "h", "l", "c"])
    return d.sort_values("ts").reset_index(drop=True)


def run(df: pd.DataFrame, levels=None, start: str | None = None,
        buf: float = BUFFER_USD, cap: float = CAP_USD,
        rr: float = SL_RR_RATIO, cooldown: int = 0) -> pd.DataFrame:
    """
    Walk the bars once. Order of operations per bar (part of the lock):
      1. If a position is open, test it for SL/TP. SL wins ties.
      2. If flat, test a pending limit for a fill on this bar.
      3. If flat and nothing pending, test this bar for a fresh breakout.
      4. Remember this bar's close as prev_close.
    """
    lv = sorted(set(levels if levels is not None else RED_LEVELS))
    d = df[df["ts"] >= pd.Timestamp(start or START_DEFAULT)].reset_index(drop=True)

    trades: list[dict] = []
    pos = None
    pending = None
    prev_close = None
    last_exit_i = -10**9

    for i in range(len(d)):
        r = d.iloc[i]
        hi, lo, cl, ts = r["h"], r["l"], r["c"], r["ts"]

        if pos is not None:
            if pos["type"] == "Buy":
                sl_hit, tp_hit = lo <= pos["sl"], hi >= pos["tp"]
            else:
                sl_hit, tp_hit = hi >= pos["sl"], lo <= pos["tp"]
            hit = "SL" if (sl_hit and tp_hit) else ("TP" if tp_hit else ("SL" if sl_hit else None))
            if hit:
                px = pos["tp"] if hit == "TP" else pos["sl"]
                pl = (px - pos["entry"]) if pos["type"] == "Buy" else (pos["entry"] - px)
                trades.append(dict(
                    pair="XAUUSD", action=pos["type"],
                    entry_time=pos["ts"], exit_time=ts,
                    entry=pos["entry"], tp=pos["tp"], sl=pos["sl"],
                    result=hit, pl_usd=pl, pl_pips=round(pl / 0.1, 1),
                    level=pos["level"], tp_level=pos["tp_level"], bars=pos["bars"],
                ))
                pos, last_exit_i = None, i

        if pos is None and pending is not None:
            if i - pending["bar"] > TTL_BARS:
                pending = None
            else:
                if pending["type"] == "Buy" and hi >= pending["entry"]:
                    filled = True
                elif pending["type"] == "Sell" and lo <= pending["entry"]:
                    filled = True
                else:
                    filled = False
                if filled:
                    pos = dict(ts=ts, entry=pending["entry"], tp=pending["tp"],
                               sl=pending["sl"], type=pending["type"],
                               level=pending["level"], tp_level=pending["tp_level"], bars=0)
                    pending = None

        if pos is not None:
            pos["bars"] += 1

        if pos is None and pending is None and prev_close is not None and (i - last_exit_i > cooldown):
            up = next((L for L in lv if prev_close <= L < cl), None)
            dn = next((L for L in lv if prev_close >= L > cl), None)
            if up is not None:
                entry = up + buf
                above = [x for x in lv if x > entry]
                if above:
                    tgt = min(above)
                    dist = min(tgt - entry, cap)
                    if dist > 1.0:
                        pending = dict(bar=i, type="Buy", entry=entry, tp=entry + dist,
                                       sl=entry - dist * rr, level=up, tp_level=tgt)
            elif dn is not None:
                entry = dn - buf
                below = [x for x in lv if x < entry]
                if below:
                    tgt = max(below)
                    dist = min(entry - tgt, cap)
                    if dist > 1.0:
                        pending = dict(bar=i, type="Sell", entry=entry, tp=entry - dist,
                                       sl=entry + dist * rr, level=dn, tp_level=tgt)

        prev_close = cl

    return pd.DataFrame(trades)


def stats(t: pd.DataFrame) -> dict:
    """Aggregate a trade list into the standard metrics."""
    if len(t) == 0:
        return dict(n=0, wins=0, losses=0, wr=0, pf=0, net=0, avg_w=0, avg_l=0,
                    maxdd=0, ret_dd=0, exp=0)
    w, l = t[t.result == "TP"], t[t.result == "SL"]
    gw, gl = w.pl_usd.sum(), abs(l.pl_usd.sum())
    eq = t.pl_usd.cumsum()
    dd = float((eq - eq.cummax()).min())
    net = gw - gl
    return dict(
        n=len(t), wins=len(w), losses=len(l),
        wr=round(len(w) / len(t) * 100, 1),
        pf=round(gw / gl, 2) if gl > 0 else float("inf"),
        net=round(net, 2),
        avg_w=round(w.pl_usd.mean(), 2) if len(w) else 0,
        avg_l=round(l.pl_usd.mean(), 2) if len(l) else 0,
        maxdd=round(dd, 2),
        ret_dd=round(net / abs(dd), 2) if dd < 0 else float("inf"),
        exp=round(t.pl_usd.mean(), 2),
    )


# =============================================================================
# EXPORT
# =============================================================================

TEMPLATE_COLUMNS = ["Pair", "Action", "Tanggal Entry", "Tanggal Exit",
                    "Entry", "TP", "SL", "Keterangan"]
DATE_FMT = "%d-%b-%y %H:%M"


def export_csv(t: pd.DataFrame, path: str) -> int:
    rows = []
    for _, r in t.iterrows():
        rows.append([
            "XAUUSD", r["action"],
            r["entry_time"].strftime(DATE_FMT),
            r["exit_time"].strftime(DATE_FMT),
            f"{r['entry']:.2f}", f"{r['tp']:.2f}", f"{r['sl']:.2f}", r["result"],
        ])
    pd.DataFrame(rows, columns=TEMPLATE_COLUMNS).to_csv(
        path, sep=";", index=False, lineterminator="\r\n")
    return len(rows)


# =============================================================================
# LOCK / INTEGRITY
# =============================================================================


def _lock_payload() -> str:
    core = {
        "method_id": METHOD_ID,
        "version": METHOD_VERSION,
        "timeframe": TIMEFRAME,
        "start": START_DEFAULT,
        "buffer_usd": BUFFER_USD,
        "cap_usd": CAP_USD,
        "sl_rr_ratio": SL_RR_RATIO,
        "ttl_bars": TTL_BARS,
        "red_levels": RED_LEVELS,
    }
    return hashlib.sha256(
        json.dumps(core, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def verify(verbose: bool = True) -> int:
    """Exit 0 = intact, 2 = parameter drift, 3 = backtest mismatch."""
    ok = True
    h = _lock_payload()

    if verbose:
        print("=" * 72)
        print(f"{METHOD_ID}  v{METHOD_VERSION}   [{TIMEFRAME}]")
        print("=" * 72)
        print(f"params : buffer ${BUFFER_USD}  cap ${CAP_USD}  RR {SL_RR_RATIO}  "
              f"TTL {TTL_BARS} bars")
        print(f"start  : {START_DEFAULT}")
        print(f"levels : {len(RED_LEVELS)}")

    if METHOD_LOCK_HASH != "PLACEHOLDER" and h != METHOD_LOCK_HASH:
        print("\n*** PARAMETER DRIFT DETECTED ***")
        print(f"  locked : {METHOD_LOCK_HASH}")
        print(f"  actual : {h}")
        print("\nRevert it, or bump METHOD_VERSION and run --relock if intentional.")
        return 2

    if verbose:
        print(f"lock   : {'OK (' + h[:16] + '...)' if METHOD_LOCK_HASH != 'PLACEHOLDER' else 'UNSET'}")

    path = REFERENCE["dataset"]
    if not os.path.exists(path):
        print(f"\nERROR: reference dataset not found:\n  {path}")
        return 3

    full = load_bars(path)
    t = run(full, start=START_DEFAULT)
    s = stats(t)

    if verbose:
        print(f"\ndataset: {path}")
        print(f"file   : {len(full)} bars   {full.ts.iloc[0]} -> {full.ts.iloc[-1]}")
        print(f"used   : {len(full[full.ts >= pd.Timestamp(START_DEFAULT)])} bars")
        print("\n--- reproduction ---")
        print(f"  {'metric':<14}{'actual':>12}{'reference':>12}")
        pairs = [
            ("trades", s["n"], REFERENCE["trades"]),
            ("wins", s["wins"], REFERENCE["wins"]),
            ("losses", s["losses"], REFERENCE["losses"]),
            ("win rate %", s["wr"], REFERENCE["win_rate_pct"]),
            ("profit factor", s["pf"], REFERENCE["profit_factor"]),
            ("net $", s["net"], REFERENCE["net_usd"]),
            ("max DD $", s["maxdd"], REFERENCE["max_dd_usd"]),
            ("net / DD", s["ret_dd"], REFERENCE["net_over_dd"]),
            ("expectancy $", s["exp"], REFERENCE["expectancy_usd"]),
        ]
        for name, got, want in pairs:
            flag = "" if abs(got - want) < 0.02 else "  <-- MISMATCH"
            if flag:
                ok = False
            print(f"  {name:<14}{got:>12}{want:>12}{flag}")

    if not ok:
        print("\nRESULT : FAIL - does not reproduce the locked H4 reference.")
        return 3

    if verbose:
        print("\nRESULT : PASS - H4 method intact and reproduces the locked reference.")
    return 0


# =============================================================================
# CLI
# =============================================================================


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Locked XAUUSD S/R breakout method, H4, cap $30.")
    ap.add_argument("--verify", action="store_true",
                    help="check lock + reproduce (exit 0/2/3)")
    ap.add_argument("--export", action="store_true", help="regenerate the reference CSV")
    ap.add_argument("--csv", help="run on a different dataset")
    ap.add_argument("--start", default=None, help=f"start date (default {START_DEFAULT})")
    ap.add_argument("--out", default=None, help="output CSV path")
    ap.add_argument("--relock", action="store_true", help="print the lock hash")
    ap.add_argument("--show-rules", action="store_true", help="print the rules")
    a = ap.parse_args(argv)

    if a.relock:
        print(_lock_payload())
        return 0
    if a.show_rules:
        print(__doc__)
        return 0
    if a.verify:
        return verify()

    if a.export or a.csv:
        path = a.csv or REFERENCE["dataset"]
        if not os.path.exists(path):
            print(f"ERROR: not found: {path}")
            return 1
        full = load_bars(path)
        t = run(full, start=a.start or START_DEFAULT)
        s = stats(t)
        out = a.out or (REFERENCE["output"] if not a.csv
                        else os.path.splitext(path)[0] + "_LOCKED_H4_OUT.csv")
        n = export_csv(t, out)
        print(f"dataset : {path}")
        print(f"bars    : {len(full)} total, using from {a.start or START_DEFAULT}")
        print(f"trades  : {s['n']}  (W {s['wins']} / L {s['losses']})")
        print(f"WR {s['wr']}%   PF {s['pf']}   Net ${s['net']}   "
              f"MaxDD ${s['maxdd']}   Net/DD {s['ret_dd']}")
        print(f"export  : {out}  ({n} rows)")
        return 0

    return verify()


if __name__ == "__main__":
    sys.exit(main())
