# -*- coding: utf-8 -*-
"""
SIMULASI ATURAN BULANAN - METODE TERKUNCI H4 (CAP30)
=====================================================
Metode TIDAK diubah: xauusd_method_LOCKED_H4.py hanya di-import,
run() di bawah ini adalah salinan baris-per-baris dari versi terkunci.

Dua aturan baru yang diuji:
  1. LOSS BULANAN MAKS 1500 PIPS
     -> kalau akumulasi rugi bulan itu mencapai -1500 pips, bulan itu
        BERHENTI: tidak ada sinyal baru sampai bulan berikutnya.
  2. PROFIT BULANAN MAKS 2000 PIPS
     -> kalau akumulasi untung bulan itu mencapai +2000 pips, bulan itu
        BERHENTI dengan cara yang sama.
     Pengecualian: order yang SUDAH running saat batas tersentuh
     dibiarkan sampai TP/SL-nya (boleh lewat sedikit dari 2000).

PIPS: 1 pip = 0.10 USD.  2000 -> 2010 = 100 pips.

Yang dihitung saat berhenti HANYA trade yang SUDAH ditutup (realised).
Order yang masih running saat bulan berganti dibuang (dengan catatan).
"""
import importlib.util
import os
import sys
import pandas as pd

TRADING = r"C:\Users\Sharing Vision\AppData\Local\hermes\trading"
PIP = 0.10   # 1 pip = $0.10 (2000.00 -> 2010.00 = 100 pips)
MONTH_LOSS_PIPS = 1500.0     # negatif = rugi
MONTH_PROFIT_PIPS = 2000.0   # positif = untung

spec = importlib.util.spec_from_file_location(
    "mod", os.path.join(TRADING, "xauusd_method_LOCKED_H4.py"))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

LEVELS = sorted(set(mod.RED_LEVELS))
BUFFER, CAP, RR, TTL, START = (mod.BUFFER_USD, mod.CAP_USD, mod.SL_RR_RATIO,
                               mod.TTL_BARS, mod.START_DEFAULT)


def run_monthly_guard(df, loss_pips=MONTH_LOSS_PIPS, profit_pips=MONTH_PROFIT_PIPS,
                      stop_mode="both", levels=None, start=None):
    """Salinan run() terkunci + rem bulanan. stop_mode: both|loss|profit|none."""
    lv = sorted(set(levels if levels is not None else LEVELS))
    d = df[df["ts"] >= pd.Timestamp(start or START)].reset_index(drop=True)

    trades, stopped_events = [], []
    pos = None
    pending = None
    prev_close = None
    last_exit_i = -10**9

    cur_month = None
    m_pips = 0.0          # realised pips bulan berjalan
    halted = False

    def month_of(ts):
        return ts.strftime("%Y-%m")

    for i in range(len(d)):
        r = d.iloc[i]
        hi, lo, cl, ts = r["h"], r["l"], r["c"], r["ts"]

        # ---------- reset rem setiap ganti bulan ----------
        mo = month_of(ts)
        if cur_month is None:
            cur_month = mo
        elif mo != cur_month:
            cur_month, m_pips, halted = mo, 0.0, False

        # ---------- 1. exit check ----------
        if pos is not None:
            if pos["type"] == "Buy":
                sl_hit, tp_hit = lo <= pos["sl"], hi >= pos["tp"]
            else:
                sl_hit, tp_hit = hi >= pos["sl"], lo <= pos["tp"]
            hit = "SL" if (sl_hit and tp_hit) else ("TP" if tp_hit else ("SL" if sl_hit else None))
            if hit:
                px = pos["tp"] if hit == "TP" else pos["sl"]
                pl = (px - pos["entry"]) if pos["type"] == "Buy" else (pos["entry"] - px)
                pips = round(pl / PIP, 1)
                trades.append(dict(
                    pair="XAUUSD", action=pos["type"],
                    entry_time=pos["ts"], exit_time=ts,
                    entry=pos["entry"], tp=pos["tp"], sl=pos["sl"],
                    result=hit, pl_usd=pl, pl_pips=pips,
                    level=pos["level"], tp_level=pos["tp_level"], bars=pos["bars"],
                ))
                m_pips += pips
                pos, last_exit_i = None, i

                # ---------- rem dicek SETELAH trade ditutup ----------
                if not halted:
                    if stop_mode in ("both", "loss") and m_pips <= -abs(loss_pips):
                        halted = True
                        stopped_events.append(dict(
                            month=mo, kind="LOSS", bar=ts, date=ts,
                            month_pips=round(m_pips, 1),
                            note="stop bulan ini: rugi mencapai batas"))
                    elif stop_mode in ("both", "profit") and m_pips >= abs(profit_pips):
                        halted = True
                        stopped_events.append(dict(
                            month=mo, kind="PROFIT", bar=ts, date=ts,
                            month_pips=round(m_pips, 1),
                            note="stop bulan ini: untung mencapai batas"))

        # ---------- 2. fill / expiry (hanya kalau tidak dihentikan) ----------
        if pos is None and pending is not None:
            if halted:
                pending = None          # order batal karena bulan dihentikan
            elif i - pending["bar"] > TTL:
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

        # ---------- 3. sinyal baru (diblokir saat halted) ----------
        if (not halted and pos is None and pending is None
                and prev_close is not None and (i - last_exit_i) > 0):
            up = next((L for L in lv if prev_close <= L < cl), None)
            dn = next((L for L in lv if prev_close >= L > cl), None)
            if up is not None:
                entry = up + BUFFER
                above = [x for x in lv if x > entry]
                if above:
                    tgt = min(above)
                    dist = min(tgt - entry, CAP)
                    if dist > 1.0:
                        pending = dict(bar=i, type="Buy", entry=entry, tp=entry + dist,
                                       sl=entry - dist * RR, level=up, tp_level=tgt)
            elif dn is not None:
                entry = dn - BUFFER
                below = [x for x in lv if x < entry]
                if below:
                    tgt = max(below)
                    dist = min(entry - tgt, CAP)
                    if dist > 1.0:
                        pending = dict(bar=i, type="Sell", entry=entry, tp=entry - dist,
                                       sl=entry + dist * RR, level=dn, tp_level=tgt)

        prev_close = cl

    return pd.DataFrame(trades), stopped_events


def monthly_table(t):
    """Rekap per bulan: n, TP, SL, pips, usd."""
    if len(t) == 0:
        return pd.DataFrame()
    x = t.copy()
    x["month"] = pd.to_datetime(x["exit_time"]).dt.strftime("%Y-%m")
    g = x.groupby("month").agg(
        n=("result", "size"),
        tp=("result", lambda s: (s == "TP").sum()),
        sl=("result", lambda s: (s == "SL").sum()),
        pips=("pl_pips", "sum"),
        usd=("pl_usd", "sum"),
    ).reset_index()
    g["wr"] = (g["tp"] / g["n"] * 100).round(1)
    g["pips"] = g["pips"].round(1)
    g["usd"] = g["usd"].round(2)
    return g


def summary(t, label):
    if len(t) == 0:
        return dict(label=label, n=0)
    s = mod.stats(t)
    eq = t.pl_pips.cumsum()
    dd = float((eq - eq.cummax()).min())
    s["label"] = label
    s["pips"] = round(t.pl_pips.sum(), 1)
    s["maxdd_pips"] = round(dd, 1)
    return s


if __name__ == "__main__":
    path = mod.REFERENCE["dataset"]
    full = mod.load_bars(path)
    print(f"dataset : {path}")
    print(f"bars    : {len(full)}  {full.ts.iloc[0]} -> {full.ts.iloc[-1]}")
    print(f"pips    : 1 pip = {PIP} USD harga (2000->2010 = 100 pips) ; "
          f"batas rugi {MONTH_LOSS_PIPS} pips ; "
          f"batas untung {MONTH_PROFIT_PIPS} pips\n")

    # ---- gate: mode none WAJIB sama persis dengan metode terkunci ----
    t_base = mod.run(full, start=START)
    t_none, _ = run_monthly_guard(full, stop_mode="none")
    print("=== GATE: salinan vs metode terkunci ===")
    s_ref, s_none = mod.stats(t_base), mod.stats(t_none)
    same = (s_ref["n"] == s_none["n"] and abs(s_ref["net"] - s_none["net"]) < 0.02
            and abs(s_ref["wr"] - s_none["wr"]) < 0.02)
    print(f"  terkunci : n={s_ref['n']} WR={s_ref['wr']} net={s_ref['net']} DD={s_ref['maxdd']}")
    print(f"  salinan  : n={s_none['n']} WR={s_none['wr']} net={s_none['net']} DD={s_none['maxdd']}")
    print(f"  -> {'MATCH' if same else '*** MISMATCH ***'}\n")

    for mode in ("both", "loss", "profit"):
        t, ev = run_monthly_guard(full, stop_mode=mode)
        s = summary(t, mode)
        print(f"=== mode {mode} ===")
        print(f"  n={s['n']} TP={s['wins']} SL={s['losses']} WR={s['wr']}% "
              f"PF={s['pf']} net={s['net']} USD / {s['pips']} pips "
              f"DD={s['maxdd']} USD / {s['maxdd_pips']} pips")
        print(f"  bulan dihentikan: {len(ev)}")
        for e in ev:
            print(f"    {e['month']}  {e['kind']:<6} di {e['date']}  "
                  f"pips bulan itu {e['month_pips']:+.1f}")
        print()
