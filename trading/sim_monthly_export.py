# -*- coding: utf-8 -*-
"""
Export hasil simulasi rem bulanan ke template backtesting standar.

Format (sama seperti xauusd_method_LOCKED_H4.export_csv):
  Pair;Action;Tanggal Entry;Tanggal Exit;Entry;TP;SL;Keterangan
  separator ';'  |  CRLF  |  tanggal DD-Mmm-YY HH:MM
"""
import importlib.util
import os
import pandas as pd

TRADING = r"C:\Users\Sharing Vision\AppData\Local\hermes\trading"
OUTDIR = r"C:\Users\Sharing Vision\Documents\OTHER\Testing"
HEADER = ["Pair", "Action", "Tanggal Entry", "Tanggal Exit",
          "Entry", "TP", "SL", "Keterangan"]
DATE_FMT = "%d-%b-%y %H:%M"

spec = importlib.util.spec_from_file_location("sim", os.path.join(TRADING, "sim_monthly_guard.py"))
sim = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sim)
mod = sim.mod
full = mod.load_bars(mod.REFERENCE["dataset"])


def rows_of(t):
    # iterrows() menamai Series-nya sesuai index baris, sehingga r["entry"] dan
    # r["exit"] bertabrakan dengan kolom Exit/Entry. Pakai itertuples + getattr.
    out = []
    for r in t.itertuples(index=False):
        out.append(["XAUUSD", r.action,
                    r.entry_time.strftime(DATE_FMT),
                    r.exit_time.strftime(DATE_FMT),
                    f"{r.entry:.2f}", f"{r.tp:.2f}", f"{r.sl:.2f}", r.result])
    return pd.DataFrame(out, columns=HEADER)


def write(t, name):
    path = os.path.join(OUTDIR, name)
    rows_of(t).to_csv(path, sep=";", index=False, lineterminator="\r\n")
    back = pd.read_csv(path, sep=";")
    tp = int((back["Keterangan"] == "TP").sum())
    sl = int((back["Keterangan"] == "SL").sum())
    print(f"{name}: {len(back)} baris | TP {tp} | SL {sl} | "
          f"WR {round(tp / len(back) * 100, 1)}%")
    return path


if __name__ == "__main__":
    t, ev = sim.run_monthly_guard(full, stop_mode="both")
    p1 = write(t, "BACKTEST_REM_BULANAN_1500loss_2000profit.csv")

    t_loss, _ = sim.run_monthly_guard(full, stop_mode="loss")
    p2 = write(t_loss, "BACKTEST_REM_BULANAN_1500LOSS_only.csv")

    # pembanding: metode terkunci tanpa rem
    t_base = mod.run(full, start=sim.START)
    p3 = write(t_base, "BACKTEST_METODE_TERKUNCI_TANPA_REM.csv")

    # rekap bulanan ke samping, supaya gampang dicek
    mt = sim.monthly_table(t)
    mt.to_csv(os.path.join(OUTDIR, "REKAP_BULANAN_REM_1500_2000.csv"),
              sep=";", index=False, lineterminator="\r\n")
    evdf = pd.DataFrame(ev)
    if len(evdf):
        evdf[["month", "kind", "date", "month_pips"]].to_csv(
            os.path.join(OUTDIR, "REKAP_BULAN_DIHENTIKAN.csv"),
            sep=";", index=False, lineterminator="\r\n")
    print("\nrekap bulanan:")
    print(mt.to_string(index=False))
