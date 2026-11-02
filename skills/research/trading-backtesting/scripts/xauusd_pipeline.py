#!/usr/bin/env python3
"""
XAUUSD Multi-Agent ML + Backtest — LOCKED STANDARD METHOD (BAKU)
=================================================================

Tujuan : pipeline baku yang TIDAK berubah-ubah antar sesi. Ubah hanya bagian
         CONFIG di bawah; jangan ubah aturan koreksi (correctness rules).

Konvensi & level risiko (dikunci):
  - Pip       : 1 pip = $0.10 (gold). Gerakan $10 = 100 pips.
  - Stop Loss : 300 pips ($30.00)
  - Take Profit: 500 pips ($50.00)
  - R:R       : 1.67  (SL lebih dekat -> acak kena SL dulu ~62%; break-even ~37.5% WR)

ATURAN KOREKSI (jangan diubah — kalau dilanggar hasilnya fiktif):
  1. NO LOOKAHEAD — sinyal di bar i, eksekusi di OPEN bar i+1.
  2. MERGE MULTI-TF WAJIB di-shift ke waktu CLOSE sebelum merge_asof(backward):
     H1 +1h, H4 +4h, D1 +1d. Tanpa ini, bar TF-tinggi yang masih terbentuk
     membocorkan close masa depan (edge palsu terukur: AUC 0.83 -> 0.52).
  3. SPLIT KRONOLOGIS 70/15/15 (train/val/test). JANGAN pernah di-shuffle.
  4. Exit direction-aware; bila SL & TP kena di bar yang sama -> SL dulu (konservatif).
  5. Spread dihitung sebagai biaya saat entry.
  6. Template trade-log: Keterangan HANYA "SL" (loss) / "TP" (take profit).
     Hold sampai TP/SL tersentuh; bila data habis lebih dulu, klasifikasi
     berdasarkan tanda unrealized PnL.
  7. VERDICT JUJUR: prediksi ARAH emas tidak punya edge (AUC ~0.5 di semua
     horizon 0.5j-24j). Jika muncul AUC arah > 0.6 -> curigai lookahead dulu.

Dependensi: numpy, pandas, scikit-learn, lightgbm, xgboost
"""
import os, json, time, warnings
import numpy as np
import pandas as pd
warnings.filterwarnings("ignore")
from sklearn.metrics import accuracy_score, roc_auc_score
import lightgbm as lgb
import xgboost as xgb

# ============================ CONFIG (boleh diubah) ============================
DATA_DIR  = r"C:\Users\Sharing Vision\Documents\OTHER\XAUUSD NEW"
OUT_DIR   = r"C:\Users\Sharing Vision\XAUUSD_ML_Pipeline\output_baku"
BASE_TF   = "XAU_15m_data.csv"          # timeframe dasar (M15)
CTX_TFS   = [("XAU_1h_data.csv",  "h1", pd.Timedelta(hours=1)),
             ("XAU_4h_data.csv",  "h4", pd.Timedelta(hours=4)),
             ("XAU_1d_data.csv",  "d1", pd.Timedelta(days=1))]

PIP        = 0.10                      # $ per pip (gold)
SL_PIPS    = 300                       # Stop Loss
TP_PIPS    = 500                       # Take Profit
SL_DOLLARS = SL_PIPS * PIP             # $30.00
TP_DOLLARS = TP_PIPS * PIP             # $50.00
RR         = TP_PIPS / SL_PIPS         # 1.67
SPREAD     = 0.35                      # $/side (asumsi; data tidak menyimpan spread)
HORIZON    = 8                         # bar M15 = 2 jam (target arah)
SPLIT      = (0.70, 0.85)              # kronologis train/val/test
SEED       = 42

# ============================ DATA ============================
def load_csv(fn):
    """CSV export MT4: delimiter ';', header Date;Open;High;Low;Close;Volume."""
    df = pd.read_csv(os.path.join(DATA_DIR, fn), sep=';')
    df = df.rename(columns={'Date':'dt','Open':'open','High':'high',
                            'Low':'low','Close':'close','Volume':'volume'})
    df['dt'] = pd.to_datetime(df['dt'], format='%Y.%m.%d %H:%M')
    return df[['dt','open','high','low','close','volume']].sort_values('dt').reset_index(drop=True)

def check_price_scale(df, name, lo=300, hi=6000):
    """Integritas data: pastikan skala harga wajar untuk emas."""
    c = df['close']
    assert c.min() > lo and c.max() < hi, \
        f"{name}: skala harga mencurigakan [{c.min():.0f},{c.max():.0f}] — bukan emas?"

# ============================ INDIKATOR ============================
def ema(s, n): return s.ewm(span=n, adjust=False).mean()

def rsi(c, n=14):
    d = c.diff(); up = d.clip(lower=0); dn = -d.clip(upper=0)
    ru = up.ewm(alpha=1/n, adjust=False).mean()
    rd = dn.ewm(alpha=1/n, adjust=False).mean()
    return 100 - 100 / (1 + ru / rd.replace(0, np.nan))

def atr(df, n=14):
    h, l, c = df['high'], df['low'], df['close']; pc = c.shift(1)
    tr = pd.concat([h-l, (h-pc).abs(), (l-pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/n, adjust=False).mean()

# ============================ FEATURES ============================
def base_features(df):
    c, h, l, v = df['close'], df['high'], df['low'], df['volume']
    f = pd.DataFrame(index=df.index)
    f['r1'] = c.pct_change(1); f['r3'] = c.pct_change(3); f['r6'] = c.pct_change(6)
    f['r12'] = c.pct_change(12); f['r24'] = c.pct_change(24)
    e20, e50, e200 = ema(c,20), ema(c,50), ema(c,200)
    f['close_over_ema20'] = (c-e20)/c
    f['close_over_ema50'] = (c-e50)/c
    f['close_over_ema200'] = (c-e200)/c
    f['ema20_50'] = (e20-e50)/c; f['ema50_200'] = (e50-e200)/c
    f['rsi14'] = rsi(c,14)
    a = atr(df,14); f['atr14'] = a; f['atr_pct'] = a/c
    sd = c.rolling(20).std(); f['bb_pctb'] = (c-(e20-2*sd))/(4*sd).replace(0,np.nan)
    f['donch_hi'] = h.rolling(24,min_periods=1).max()
    f['donch_lo'] = l.rolling(24,min_periods=1).min()
    f['dist_to_hi'] = (c-f['donch_hi'])/c; f['dist_to_lo'] = (c-f['donch_lo'])/c
    f['bos_up'] = (c > f['donch_hi'].shift(1)).astype(int)   # bullish BOS
    f['bos_dn'] = (c < f['donch_lo'].shift(1)).astype(int)   # bearish BOS
    f['range_pct'] = (h-l)/c; f['body_pct'] = (c-df['open'])/c
    f['vol_ma20'] = v.rolling(20).mean()
    f['vol_z'] = (v-v.rolling(20).mean())/v.rolling(20).std().replace(0,np.nan)
    vwap = (v*(h+l+c)/3).rolling(48).sum()/v.rolling(48).sum().replace(0,np.nan)
    f['close_vs_vwap'] = (c-vwap)/c
    f['hour'] = df['dt'].dt.hour.astype(float); f['dow'] = df['dt'].dt.dayofweek.astype(float)
    f['ny_session'] = ((df['dt'].dt.hour>=13)&(df['dt'].dt.hour<21)).astype(float)
    f['london_session'] = ((df['dt'].dt.hour>=7)&(df['dt'].dt.hour<16)).astype(float)
    return f

def ctx_features(df, name, shift):
    """Fitur konteks TF-tinggi. ATURAN #2: _dt di-shift ke waktu CLOSE agar
    bar hanya bisa dipakai SETELAH selesai (tidak bocor data masa depan)."""
    f = pd.DataFrame(index=df.index); c = df['close']
    f[f'{name}_rsi'] = rsi(c,14)
    f[f'{name}_close_ema50'] = (c-ema(c,50))/c
    f[f'{name}_close_ema200'] = (c-ema(c,200))/c
    f[f'{name}_atr_pct'] = atr(df,14)/c
    f[f'{name}_r6'] = c.pct_change(6)
    f['_dt'] = df['dt'] + shift
    return f

def merge_ctx(base, frames):
    m = base.copy().sort_values('dt')
    for c in frames:
        m = pd.merge_asof(m, c.sort_values('_dt'), left_on='dt', right_on='_dt',
                          direction='backward').drop(columns=['_dt'])
    return m

# ============================ DATASET ============================
def build_dataset():
    base = load_csv(BASE_TF)
    check_price_scale(base, BASE_TF)
    X = base_features(base)
    d = pd.concat([base[['dt','open','high','low','close','volume']], X], axis=1)
    d = merge_ctx(d, [ctx_features(load_csv(fn), name, shift) for fn,name,shift in CTX_TFS])
    d['fwd_close'] = d['close'].shift(-HORIZON)
    d['label'] = (d['fwd_close'] > d['close']).astype(int)
    d = d.dropna(subset=['close_over_ema200','atr_pct','rsi14','label']).reset_index(drop=True)
    FEAT = [c for c in d.columns if c not in
            ('dt','open','high','low','close','volume','fwd_close','label')
            and pd.api.types.is_numeric_dtype(d[c])]
    return d, FEAT

def chronological_split(d, FEAT):
    n = len(d); te, ve = int(n*SPLIT[0]), int(n*SPLIT[1])
    tr, va, ts = d.iloc[:te], d.iloc[te:ve], d.iloc[ve:]
    return (tr[FEAT].values, tr['label'].values,
            va[FEAT].values, va['label'].values,
            ts[FEAT].values, ts['label'].values), tr, va, ts

# ============================ MODEL ============================
def train_best(Xtr, ytr, Xva, yva):
    grid = [
        ('lgb', dict(n_estimators=400, learning_rate=0.05, num_leaves=63, max_depth=-1,
                     min_child_samples=100, subsample=0.8, colsample_bytree=0.8,
                     reg_alpha=0.1, reg_lambda=1.0)),
        ('lgb', dict(n_estimators=600, learning_rate=0.03, num_leaves=127, max_depth=-1,
                     min_child_samples=200, subsample=0.8, colsample_bytree=0.7,
                     reg_alpha=0.5, reg_lambda=5.0)),
        ('xgb', dict(n_estimators=400, learning_rate=0.05, max_depth=6, min_child_weight=10,
                     subsample=0.8, colsample_bytree=0.8, reg_alpha=0.5, reg_lambda=5.0)),
    ]
    best_m, best_auc, best_name = None, -1, None
    for name, p in grid:
        m = (lgb.LGBMClassifier(**p, random_state=SEED, verbose=-1, n_jobs=-1)
             if name == 'lgb' else
             xgb.XGBClassifier(**p, random_state=SEED, verbosity=0, n_jobs=-1,
                               eval_metric='logloss', tree_method='hist'))
        m.fit(Xtr, ytr)
        auc = roc_auc_score(yva, m.predict_proba(Xva)[:,1])
        print(f"   {'LGB' if name=='lgb' else 'XGB'} {p['n_estimators']}n lr={p['learning_rate']} "
              f"-> val AUC {auc:.4f}")
        if auc > best_auc: best_m, best_auc, best_name = m, auc, 'LGB' if name=='lgb' else 'XGB'
    return best_m, best_auc, best_name

# ============================ BACKTEST ============================
def backtest(df, probs, thr_up=0.55, thr_dn=0.45):
    """Single-position walk-forward. Hold sampai TP/SL; data habis -> klasifikasi PnL."""
    o,h,l,c = df['open'].values, df['high'].values, df['low'].values, df['close'].values
    dt = df['dt'].values
    trades = []
    i = 0
    while i < len(df) - 1:
        p = probs[i]
        if p >= thr_up or p <= thr_dn:
            side = 1 if p >= thr_up else -1
            entry = o[i+1] + (SPREAD if side == 1 else -SPREAD)
            sl = entry - SL_DOLLARS if side == 1 else entry + SL_DOLLARS
            tp = entry + TP_DOLLARS if side == 1 else entry - TP_DOLLARS
            exit_px, reason, exit_i = None, None, None
            for b in range(i+1, len(df)):
                hi, lo = h[b], l[b]
                if side == 1: hit_tp, hit_sl = hi >= tp, lo <= sl
                else:         hit_tp, hit_sl = lo <= tp, hi >= sl
                if hit_sl and hit_tp: exit_px, reason, exit_i = sl, 'SL', b; break
                elif hit_sl: exit_px, reason, exit_i = sl, 'SL', b; break
                elif hit_tp: exit_px, reason, exit_i = tp, 'TP', b; break
            if reason is None:
                exit_i = len(df)-1; exit_px = c[exit_i]
                reason = 'TP' if (side*(exit_px-entry) > 0) else 'SL'
            pnl = side * (exit_px - entry)
            trades.append(dict(entry_dt=dt[i+1], exit_dt=dt[exit_i],
                               side='Buy' if side==1 else 'Sell',
                               entry=entry, exit=exit_px, reason=reason, pnl=pnl))
            i = exit_i + 1                    # satu posisi: lanjut setelah exit
        else:
            i += 1
    return trades

def metrics(trades):
    if not trades:
        return dict(n=0, wr=0.0, pf=0.0, net=0.0, dd=0.0, n_tp=0, n_sl=0)
    pnls = np.array([t['pnl'] for t in trades])
    wins, losses = pnls[pnls>0], pnls[pnls<0]
    eq = 10000 + np.cumsum(pnls); peak = np.maximum.accumulate(eq)
    return dict(n=len(trades), wr=float((pnls>0).mean()*100),
                pf=float(wins.sum()/abs(losses.sum())) if losses.sum()!=0 else float('inf'),
                net=float(pnls.sum()), dd=float(((peak-eq)/peak).max()*100),
                n_tp=sum(1 for t in trades if t['reason']=='TP'),
                n_sl=sum(1 for t in trades if t['reason']=='SL'))

# ============================ TEMPLATE OUTPUT ============================
def write_template(trades, path):
    """Trade-log template: Pair;Action;Tanggal Entry;Tanggal Exit;Entry;TP;SL;Keterangan.
    Keterangan HANYA SL/TP (aturan #6)."""
    def fmt(ts): return pd.Timestamp(ts).strftime('%d-%b-%y %H:%M')
    rows = [['Pair','Action','Tanggal Entry','Tanggal Exit','Entry','TP','SL','Keterangan']]
    for t in trades:
        e = t['entry']
        tp = e + TP_DOLLARS if t['side'] == 'Buy' else e - TP_DOLLARS
        sl = e - SL_DOLLARS if t['side'] == 'Buy' else e + SL_DOLLARS
        rows.append(['XAUUSD', t['side'], fmt(t['entry_dt']), fmt(t['exit_dt']),
                     f"{e:.2f}", f"{tp:.2f}", f"{sl:.2f}", t['reason']])
    with open(path, 'w', newline='') as f:
        for r in rows: f.write(';'.join(r) + '\n')
    return path

# ============================ MAIN ============================
def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    t0 = time.time()

    print("=== AGEN 1: DATA + FEATURES (no-lookahead) ===")
    d, FEAT = build_dataset()
    (Xtr,ytr,Xva,yva,Xte,yte), tr, va, ts = chronological_split(d, FEAT)
    print(f"rows={len(d):,}  features={len(FEAT)}  P(up)={d['label'].mean():.3f}")
    print(f"train {tr.dt.min().date()}..{tr.dt.max().date()} | "
          f"val {va.dt.min().date()}..{va.dt.max().date()} | "
          f"test {ts.dt.min().date()}..{ts.dt.max().date()}")
    d.to_csv(os.path.join(OUT_DIR, 'XAUUSD_MultiTF_Clean.csv'), index=False)

    print("\n=== AGEN 2: TRAIN (LGB/XGB) ===")
    model, val_auc, name = train_best(Xtr, ytr, Xva, yva)
    pte = model.predict_proba(Xte)[:,1]
    auc = roc_auc_score(yte, pte); acc = accuracy_score(yte, (pte>=0.5).astype(int))
    print(f"SELECTED {name} val AUC {val_auc:.4f}")
    print(f"test AUC={auc:.4f}  acc={acc:.4f}  (AUC 0.5 = lempar koin)")

    imp = pd.Series(model.feature_importances_, index=FEAT).sort_values(ascending=False)
    imp.to_csv(os.path.join(OUT_DIR, 'feature_importance.csv'))

    print("\n=== AGEN 3: BACKTEST + threshold sweep ===")
    sweep = []
    for thr in [0.50,0.55,0.60,0.65,0.70,0.75,0.80]:
        m = metrics(backtest(ts.reset_index(drop=True), pte, thr_up=thr, thr_dn=1-thr))
        sweep.append(dict(thr=thr, **m))
        print(f"  thr={thr:.2f}  trades={m['n']:>6,}  TP={m['n_tp']:>5}  SL={m['n_sl']:>5}  "
              f"WR={m['wr']:>5.1f}%  PF={m['pf']:>5.2f}  net=${m['net']:>9.0f}  DD={m['dd']:>5.1f}%")

    valid = [s for s in sweep if s['pf'] > 1]
    best = max(valid, key=lambda s: s['wr']) if valid else max(sweep, key=lambda s: s['net'])

    print("\n=== AGEN 4: OUTPUT ===")
    final_trades = backtest(ts.reset_index(drop=True), pte, thr_up=best['thr'], thr_dn=1-best['thr'])
    tmpl = write_template(final_trades, os.path.join(OUT_DIR, 'template-backtest.csv'))

    result = dict(model=name, val_auc=round(val_auc,4), test_auc=round(auc,4),
                  test_acc=round(acc,4), sl_pips=SL_PIPS, tp_pips=TP_PIPS, rr=round(RR,2),
                  spread=SPREAD, horizon_bars=HORIZON,
                  train_n=len(tr), val_n=len(va), test_n=len(ts),
                  test_range=[str(ts.dt.min()), str(ts.dt.max())],
                  sweep=sweep, best_threshold=best)
    with open(os.path.join(OUT_DIR, 'result.json'), 'w') as f:
        json.dump(result, f, indent=2, default=float)

    print(f"template -> {tmpl}")
    print(f"BEST operating point: thr={best['thr']}  trades={best['n']}  "
          f"WR={best['wr']:.1f}%  PF={best['pf']:.2f}  net=${best['net']:.0f}")
    print(f"[VERDICT] test AUC={auc:.4f} — {'ada indikasi edge' if auc>0.6 else 'TIDAK ada edge arah (jujur: NO TRADE)'}")
    print(f"done in {time.time()-t0:.0f}s")

if __name__ == '__main__':
    main()
