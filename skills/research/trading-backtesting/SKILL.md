---
name: trading-backtesting
description: "Use when backtesting trading strategies for XAUUSD/gold."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [windows]
metadata:
  hermes:
    tags: [trading, backtesting, mt4, xauusd, forex, quant]
    category: research
    related_skills: []
---

# Trading Strategy Backtesting (XAUUSD / MT4)

Backtest trading strategies on the user's real MT4 market data and deliver
results in their trade-log template. The user frames this work as a multi-agent
orchestration and expects results presented through those roles, in **Bahasa
Indonesia**: **Agen 1 Data Analyst** (read data, propose strategies) → **Agen 2
Backtest Engine** (win rate / profit factor / max drawdown, pick the best) →
**Agen 3 Signal Generator** (current-candle signal) → **Agen 4 Risk Validator**
(execute-or-reject verdict).

## When to Use

- The user asks to backtest, research, or validate a trading strategy (XAUUSD/gold or another MT4 instrument), often framed as the Agen 1–4 orchestration.
- The user asks for real market data from their MT4 terminal, or supplies a CSV whose price scale must be verified first.
- The user wants results written to `Downloads\template-backtest.csv` in their trade-log format.

## Workflow

1. **Verify data integrity before trusting any file.** Gold trades around
   $2000–5000; USDJPY around 140–165. A file labeled `XAUUSD` with prices ~160
   is USDJPY renamed — check the price scale against the instrument FIRST, or a
   mislabeled file silently wastes the whole session. Cross-check against the
   broker's own `.hst` files when available. When the user names a file whose
   scale conflicts with the levels/template they supplied, list the Downloads
   directory for a sibling export (e.g. `XAUUSD60.csv` vs `XAUUSD60_REAL.csv`)
   and pick the one matching the supplied levels — do not ask; state the swap.
   Also glob the whole target folder (`ls *.csv`, and search sibling folders such
   as `Documents\OTHER\<INSTRUMENT>*`) for multi-timeframe bundles
   (`XAU_1m/5m/15m/30m/1h/4h/1d_data.csv`, header `Date;Open;High;Low;Close;Volume`
   with `YYYY.MM.DD HH:MM` timestamps) — that is the user's long-history source
   and is preferable to a 4-month export when they ask for a multi-year period.
   A backtest start date earlier than the file's first bar is silently clipped —
   report the ACTUAL first/last trade dates, never echo the requested range.

1b. **The file's date range bounds every conclusion.** A 4-month export and a
   22-year series are different experiments: the S/R levels themselves may only
   become reachable recently (levels bottoming at $3341 with gold first trading
   there in Aug 2025 means a "2015–2026" backtest produces trades only in
   2025–2026). Print first/last bar, bar count, and price min/max before the
   first backtest line, and say which era the results describe.

1c. **Verify the S/R level set covers the data's price range before running.**
   Check the top level against the data's max high and the bottom level against
   its min low. A truncated list (top level $4848 while price prints $5597)
   leaves a blind zone above the highest level — no breakout can trigger and no
   TP target exists there, so whole price regions produce zero signals. Report
   the uncovered span and ask whether the list was cut short rather than
   silently backtesting the gap.

1d. **When concatenating the long-history file with a fresh MT4 export, split
   on the gap.** The two H1 sources may not abut (long history ends Jan, the
   export starts Jun). Run the backtest per-segment — split on any timestamp
   gap >48h so no open position bridges the missing months — otherwise a
   position "fills" at the next real bar weeks later and corrupts PnL.

2. **Source real data from MT4 by parsing `.hst` files directly.** History lives
   under `%APPDATA%\MetaQuotes\Terminal\<hash>\history\<server>\`, NOT in the
   install folder (a Start-Menu shortcut points only at the install folder).
   Parse the `.hst` — see `references/mt4-hst-format.md`, or run
   `scripts/parse_mt4_hst.py`. Parsing is deterministic and needs no GUI
   automation or login.

2a. **A stale `.hst` is a chart-open problem, not a feed problem.** MT4 only
   writes the history file for the timeframe whose chart is open, so a frozen
   `XAUUSD240.hst` beside a fresh `XAUUSD60.hst` means nobody had the H4 chart
   open. Check mtimes across the `.hst` family and grep the profile's `.chr`
   files for `period=` before blaming the network or shopping for an API. When
   the user asks for a real-time source instead, read
   `references/realtime-price-sources.md` — it carries the tested spot/futures
   endpoint matrix and the measured reason GC=F must never be priced as XAUUSD.

2b. **Read the user's drawn S/R levels from the chart-object file** when they
   ask to backtest "based on my lines". The red horizontal lines live in
   `%APPDATA%\MetaQuotes\Terminal\<hash>\profiles\<profile>\chartNN.chr` — a
   text file of `<object>` blocks; a horizontal line carries `value_0=<price>`
   and `color=255` (red), and `symbol=`/`period=` name the chart (240 = H4).
   Check the running chart's timeframe via its window title (`[XAUUSD,H4]`) or
   `computer_use list_windows`. The `.chr` is saved only on profile switch/exit,
   so it is often STALE — if levels look incomplete, ask the user to save the
   chart or type the levels (or Ctrl+B and paste the object list) rather than
   trusting the stale file. Drawn lines are NOT in the accessibility tree (only
   toolbars are) and are not reliably pixel-readable by a vision model — don't
   burn time reading them off a screenshot.

3. **Run a no-lookahead backtest engine.** Enforce these correctness rules on
   every engine or the numbers are fiction:
   - Signal computed on bar `i-1`, executed at the OPEN of bar `i`.
   - Exits are direction-aware: the exit function must receive the position
     direction (long exits up at target / down at stop; short the reverse).
   - Breakout/Donchian compares the close to the prior N bars EXCLUDING the
     current bar — off-by-one here either kills all signals or leaks lookahead.
   - **Gap-through guard:** for fade/limit entries with a level stop, reject the
     entry if the open gaps past the stop. Without it, a stop that lands on the
     profitable side of a gapped entry books phantom profit and inflates PF.
     Self-check: no trade labeled "SL" may carry positive PnL.
   - Account for spread/slippage as an explicit cost per round trip.
   - Keep the position-direction representation consistent end-to-end. Mixing
     integer ±1 in the trade log with a summary that compares against the
     string "Buy" flips every long PnL's sign and silently corrupts WR/PF —
     pick one representation and normalize at the boundary.
   - Validate a new rule/gate by first confirming the engine WITHOUT it still
     reproduces a previously-known result (same n / WR / PF). An accumulator
     that gates entries but is never written (a leftover `pass` in the
     monthly-PnL attribution) disables the gate with no error — only the
     known-good comparison catches it.
   - **Limit/stop orders need a validity window.** If the entry sits a buffer
     away from the breakout level, the bar that triggers the signal did NOT
     fill it — fill on a later bar when price reaches the entry, and expire the
     order after a few bars. Filling on the signal bar books entries that price
     never touched.
   - **Ambiguous bars (SL and TP both inside one bar) resolve as SL.** Being
     conservative here is the only honest choice on OHLC data; the alternative
     inflates win rate on exactly the volatile bars that decide live results.
   - Name the timestamp column `ts`, not `dt` — `row.dt` collides with pandas'
     `.dt` datetime accessor and raises `Can only use .dt accessor with
     datetimelike values` on a Series row.
   - Pre-assign computed fields to locals, not `Series` attribute access
     (`row.h`), when the frame's column names are short; attribute access
     shadows pandas methods unpredictably as the frame evolves.

4. **Re-test the entry under the CURRENT exit scheme.** A strategy whose edge
   lives in its exit levels loses it when exits are swapped for fixed pips.
   Fibonacci 0.618 wins with 0.786-SL / swing-extreme TP (R:R ≈ 7:1) but goes
   negative under fixed-pip SL/TP; Bollinger mean-reversion is what holds up
   under fixed pips. Sweep entry methods per exit scheme — never carry a prior
   winner forward blindly.

4b. **Separate "tune the parameters" from "rebuild the levels", and
   walk-forward both.** When optimizing S/R levels, filtering out the levels
   that bleed money usually generalizes; replacing the user's drawn levels with
   data-mined pivot clusters usually does NOT. Measured on the same dataset:
   dropping the worst levels held up out-of-sample (IS PF 2.91 → OOS 3.31) while
   a rebuild from the most-touched pivot clusters collapsed (IS 2.19 → OOS 0.93,
   negative). Pivot clusters with 50+ touches are the levels price already
   chopped through — they look strongest in-sample and are the most overfit.
   Always split: in-sample for selection, out-of-sample for the verdict, and
   report both rows before recommending. The "drop the bleeders" heuristic is
   itself overfit-prone across regimes: a level that bleeds in one era can be
   the contributor in the next, so dropping the in-sample losers has been
   observed to raise IS PF (0.81→1.70) while LOWERING OOS PF (0.98→0.88).   A
   drop list that does not hold out-of-sample is a rejection, not a
   recommendation. The one rebuild that DID hold out-of-sample is structural,
   not touch-count: fractal swing highs/lows (lookback k=5), cluster points
   within $8, enforce $30 min spacing, fit on TRAIN only. On gold it beat the
   drawn levels on the test era (train PF 1.10 → test PF 1.03, full-period
   PF 1.06 vs 0.90) but the edge is thin (~$0.77/trade gross, negative after
   $1/oz round-trip) and one level carried most of the net — label it
   CANDIDATE, not a recommendation.

4b-bis. **Optimize on the dataset you will deliver on, not a proxy dataset.**
   Parameters tuned on a long multi-year series do NOT transfer to the short
   export the user actually trades: on real gold the same cap sweep peaked at
   max-TP $20 on 2004–2026 H1 (PF 2.25) but at $30 on a Jun–Oct 2026 export
   (PF 2.08), while that $20 carried across delivered PF 1.39 — a third of the
   net, well below the user's original untuned rule. Different price eras have
   different per-hour volatility, so a pip cap is regime-specific. Sweep the cap
   on the target file, then confirm the winner on the long series only as a
   sanity check. If the two disagree, trust the target file and say the long
   sample disagreed.

4c-bis. **A "validated" plateau claim is only as good as the sweep's smoothness.**
   Before calling a parameter optimum, print PF/net across a dense sweep (e.g.
   caps 8/10/12/15/18/20/22/25/30/35/40/50). A smooth single-hump curve is a
   real optimum; an oscillating one (1.87 → 1.67 → 1.53 → 1.39 → 1.56 → 2.08 →
   1.62 → 1.84) means the sample is too small to locate an optimum at all, and
   the honest output is "use the user's original or the broad middle, not my
   point estimate". Do not present a jagged curve's local max as a finding.

4d-bis. **Before declaring a stored result "unreproducible", recover the original script
   from session history and re-run it.** Scratch/temp pruning deletes files, not the
   conversation that wrote them: every `write_file` call keeps its full content in
   `~/AppData/Local/hermes/state.db`, so a pruned script is byte-identical recoverable.
   Query `SELECT tool_calls FROM messages WHERE tool_calls LIKE '%<script>.py%' AND
   tool_calls LIKE '%write_file%'`, take the LATEST write to that path (a patched script has
   several), and re-write it. Restore its local imports too, then re-run and compare.
   This matters because "the claim was fabricated" and "my replacement engine resolves exits
   differently" are completely different findings, and only the recovered script separates
   them: the original reproduced its own figures exactly while the rewritten engine did not.
   Matching trade counts (±4) with a 15-point WR gap is the signature of an exit-resolution
   difference (intrabar TP-vs-SL tie-break, pending-fill rule, or `>` vs `>=` on order TTL) —
   not of fake data. Diff the two engines on the divergent trades before concluding anything,
   and downgrade any earlier "could not be reproduced" statement to "not reproduced by my
   engine" once the original works.

4e-bis. **Raising win rate: widen the stop, then prove it is not just a smaller edge.**
   Widen the SL ratio first — it is the direct lever (RR 0.6→1.0 moved WR 40.5%→59% on
   identical bars) because each loss then equals each win in dollars. That is arithmetic, not
   a better signal, so say so. Then apply the gates: tune on a TRAIN slice and judge on a
   holdout; re-run survivors on a second era's dataset; print a ±1-step neighbourhood to
   distinguish a plateau from a spike; report how many configs were tried (200 sweeps → ~3
   clear any threshold by chance); and quote `sqrt(wr(1-wr)/n)` so n=122 reads as "59% ± 4.5pp".
   A config that only clears the target on the sample it was tuned on is a CANDIDATE for
   forward-testing, never a recommendation — record the failing check in the strategy file and
   assert it in the verifier so the caveat cannot be dropped later.

4d. **When a delivered recommendation loses on the user's own data, lead the
   reply with that loss.** State the comparative row, the reason (wrong
   optimization dataset / regime shift / weak split), and what beat it — do not
   bury it under new numbers or restate it as a refinement. The user is running
   real money off these files; a silently superseded recommendation is the
   worst possible output. Export both the failing variant and the corrected one
   so the record is auditable, and name the files so they are not confused.

4c. **Cap distance is usually the real culprit, not the level set.** Bucket
   trades by actual TP distance (e.g. $20–30 / $30–40 / $40–50) and print WR and
   net per bucket before touching any level. A generous max-TP cap silently
   drags the average target into the worst bucket; tightening the cap often
   beats every level edit. Also print per-level and per-target-level P/L tables
   — "which levels bleed" and "which targets never get reached" are different
   findings with different fixes.

5. **Output to the user's trade-log template** at
   `Downloads\template-backtest.csv`, semicolon-delimited, columns exactly:
   `Pair;Action;Tanggal Entry;Tanggal Exit;Entry;TP;SL;Keterangan`. Date
   format `DD-Mon-YY HH:MM` (e.g. `25-Jun-26 15:00`); `Action` is `Buy`/`Sell`.
   `Keterangan` takes ONLY `SL` (loss) or `TP` (take profit) — never `CLOSE`:
   the user wants every row classified win/loss, so hold each entry until its
   SL or TP is hit, and if data ends first classify by unrealized PnL sign
   (profit → TP, loss → SL). Deliver with `MEDIA:<path>`.

## User conventions

- **Pip = 0.10 for gold.** A move of 10.00 (e.g. 2000.00 → 2010.00) is 100 pips.
  So "SL 200–400 pips, TP 200–500 pips" means $20–40 / $20–50 on gold.
- Their trade-log template uses fixed **SL = 300 pips ($30) / TP = 500 pips
  ($50), R:R ≈ 1.67** — use these (not an arbitrary 250/400) when filling the
  log. TP sits closer than SL, so a random walk reaches TP first ~62% of the
  time; break-even at R:R 1.67 (win $50 / lose $30) needs only ~37.5% win rate.
  Do not state that "SL is hit first 62% of the time" — under this geometry the
  narrow leg is the TP.
- Money-management rules when the user gives them: max 2 concurrent positions;
  no new same-direction entry within 100 pips ($10) of an existing entry.
- Monthly risk caps ("max loss 1800 pips / max profit 2000 pips"): stop opening
  NEW entries once the month's realized PnL crosses either threshold; attribute
  each trade's PnL to its CLOSE month; already-open positions still run to
  TP/SL; reset each calendar month. Report the per-month breakdown so the cap's
  effect is visible — caps trade drawdown protection off against total return.
- The user's breakout method ("level-to-level"): horizontal S/R lines are the TP
  targets. Buy = break above a line → enter line+buffer (~20–30 pips), TP = next
  line above (cap 500 pips if the gap is wider), SL = previous line below; sell
  mirrors. The lines are the red horizontal lines drawn on their MT4 chart.
- **When the user's stated risk:reward conflicts with the template, follow the
  request and label it.** A specified `SL = 0.6 × TP` (R:R 0.6:1, SL narrower
  than TP) means a random walk hits SL ~62% of the time, so break-even needs
  ~38% WR — a 55–65% WR under that scheme is a genuinely strong edge. Export
  with the requested levels but state the break-even WR and the contrast with
  the template's 1.67:1 rows so the difference is not mistaken for an error.
- Verify the export mechanically before delivering: header byte-identical to
  the template (`od -c` on both), row count equal to the engine's trade count,
  and a re-read assertion that every row satisfies the stated rules (TP
  distance ≤ cap, |SL−Entry|/|TP−Entry| = the specified R:R). Report
  "0 violations" only after that check passes.
- State assumptions explicitly (pip scale, spread, sample size). Flag that a few
  months of one regime is not proof — walk-forward validation is the honest next
  step before live money,  and say so rather than overselling a backtest.

## ML intraday pipeline (LGB/XGB) — what actually happens

- **Locked reusable pipeline:** `C:\Users\Sharing Vision\XAUUSD_ML_Pipeline\xauusd_pipeline.py`
  (also `scripts/xauusd_pipeline.py` in this skill) is the canonical end-to-end
  script — data → no-lookahead features → LGB/XGB → single-position backtest →
  trade-log template. Change only its CONFIG block; the correctness rules are
  locked in its docstring.
- **Multi-timeframe merge lookahead (critical):** `merge_asof(base, ctx,
  direction="backward")` where `ctx` bars are timestamped at their OPEN time
  silently leaks the still-forming higher-TF bar's close into the lower-TF
  features — the fake edge is huge (measured test AUC 0.83 → 0.52 after the
  fix). Shift the context timestamp by +bar-period (H1 +1h, H4 +4h, D1 +1d) so
  a bar is only usable after it closes, BEFORE merging. Verify: val AUC ≈ test
  AUC; reject any AUC/accuracy that looks "too good" for the horizon.
- `fetch_mt4_data()` / "MT4 API Tools" do not exist; the real data path is
  parsing `.hst` files (see above). There is no live-tick API and no
  economic-calendar tool — "current price" = last close in the freshest
  `.hst`, and the news check is a best-effort web search, not a real-time feed.
  For a genuine external quote, gold-api.com and the TradingView scanner both
  serve spot XAUUSD without a key; Yahoo serves gold **futures** only, and its
  basis against the broker's spot measured ~$33/oz — never feed it into
  entries, TP or SL. Details: `references/realtime-price-sources.md`.
- Check WHICH periods exist first: M5 (`XAUUSD5.hst`) and D1
  (`XAUUSD1440.hst`) are often absent from MT4 history — only M15/M30/H1/H4
  may be present. Do not promise a 5-TF dataset without checking.
- A user-supplied CSV labeled "4H" can silently be DAILY data: if the time
  column holds only `00:00` and rows are one per weekday over years, it is
  daily (true 4H has 6 bars/day at 00/04/08/12/16/20 and ~16k rows for 7y).
  Verify the time column's distinct values before trusting the label.
- User CSV exports are headerless and comma-delimited:
  `date,time,open,high,low,close,volume` (MqlRates order — HIGH before LOW,
  `YYYY.MM.DD,HH:MM`). Load with `header=None` + explicit names. These CSVs
  are tz-naive while `.hst`-parsed data is tz-aware UTC — strip tz on the
  `.hst` side (`pd.to_datetime(...).dt.tz_localize(None)`) before `merge_asof`,
  or the merge fails on a dtype mismatch.
- Direction prediction is a dead end: a gradient-boosted model on gold OHLCV
  gets ~0.5 test AUC for forward direction at EVERY horizon (0.5h–24h), even
  with 22 years / ~494k M15 bars (test AUC ~0.52, accuracy ≈ base rate). No
  threshold or hyperparameter tuning produces PF reliably > 1. The honest
  verdict is NO TRADE — do not chase a >60% win rate on direction. If a result
  shows strong direction AUC, suspect the multi-TF lookahead bug above before
  believing it. Better targets to try: volatility/range expansion, regime, or
  the user's rule-based S/R breakout.
- This Windows env: `pip` is absent from the Hermes venv but bootstraps via
  `python -m ensurepip`; numpy/pandas/scikit-learn/lightgbm/xgboost then
  install cleanly as cp314 win_amd64 wheels.
