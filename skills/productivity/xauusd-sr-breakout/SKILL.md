---
name: xauusd-sr-breakout
description: Use for XAUUSD S/R breakout backtests, live signals, and restoring the frozen system.
---

# XAUUSD S/R Breakout — FROZEN Strategy `XAUUSD-SR-BREAKOUT-CAP30`

## ⛔ READ FIRST — the system is FROZEN, never re-derive it

The method and the boot procedure are frozen. A fresh Hermes install MUST
reproduce the identical robot. Do NOT re-tune, re-optimise, or "improve" it,
and do not rebuild from memory — restore the frozen bytes:

```
python assets/xauusd_bundle.py --restore
```

That one command writes every file back to `...\hermes\trading\` byte-for-byte
and is the entire recovery procedure. Then follow **`references/restore-and-boot.md`**
for the mandatory boot order (verify both methods, `register_tasks.bat`, health
check) and for the traps that silently break the schedule.

`assets/xauusd_bundle.py` is the only copy that survives a reinstall. Treat it
as the source of truth; the files in `trading/` are the working copies.

**After changing ANY file the bundle embeds (especially `signal_live_h4.py` and
the two `*_LOCKED*.py`), re-run `--verify`, then copy the rebuilt bundle over
`assets/xauusd_bundle.py` and diff the two hashes.** They silently drift: the
bundle in `trading/` was rebuilt to v1.3.0 while the skill asset was still
v1.1.0, so a reinstall would have restored the buggy pre-fix signal engine.

### Never let a scheduled helper delete itself

One-off demo senders must not `del "%~f0"` or `os.remove(__file__)`. The 18:10
proof-of-life demo did exactly that and left the user with nothing to inspect.
Leave the script in place, mark the task as fired (the script's own time-window
guard is enough), and clean up only when the user asks.

### A bundle cannot contain itself — always stage the script outside its target

The bundle embeds the files it restores, so `xauusd_bundle.py` is NOT inside its
own payload. The moment you delete or wipe the folder it lives in, the script
that would fix things is gone too. Two rules follow:

- **Before any loss simulation** (`rm -rf <target>`), copy the bundle to a path
  outside the target first and run the restore from there. Never test recovery
  by deleting the folder that holds the only runnable copy.
- **Before any publish** (git, upload, archive), copy the bundle out of the tree
  being packaged and read it from that copy — the packaged tree will not include
  it, and `cp` on it after a wipe fails with "No such file or directory".

When you change the bundle's own behaviour, the new bundle must be rebuilt from
the regenerated skeleton, not hand-edited: the embedded base64 blocks make any
manual edit a corruption risk. Regenerate, then re-run all four subcommands.

### Distinguish file hash from lock hash in every report

Two checks that must both hold, and they are DIFFERENT things:

| check | H4 | H1 |
|---|---|---|
| file sha256 | `acc7d5beddae99db...` | `bfb360af0f850474...` |
| internal lock hash | `0c76e240d109d608...` | `dda75a33ab3beb2a...` |

Do not confuse a file hash with a lock hash — a file hash covers the bytes, the
lock hash covers the rules. Reporting the wrong one causes false drift alarms.

## LIVE SIGNAL BOT (Telegram)

`trading/signal_live_h4.py` imports the locked H4 file and calls `run()`; it never
reimplements strategy logic. Subcommands: `--run` (send new signals), `--poll`
(answer /status), `--check`, `--status`, `--sources`, `--test`.

Lessons learned the hard way — do not re-break these:

- **`run()` only returns FINISHED trades — including a signal that has fired but
  not filled yet.** This is the single worst bug in the whole robot: the very
  moment a signal fires, `run()` cannot see it, so nothing is sent, and the
  trader only learns about it after it has already exited. `scan()` must
  additionally ask `live_state()` for a `pending`/`open` signal and append it to
  `new` before sending. Verified by writing a synthetic `.hst` with one extra
  breakout bar: before the fix 0 new signals, after it 1 (BUY 3934.48).
- **Scheduled-task `<Duration>P1D</Duration>` silently kills the whole robot.**
  `schtasks /Create /SC DAILY /RI 240 /DU 24:00` writes a repetition window of
  one day; after midnight the task simply never fires again and still reports
  success. Always register from XML with **no `<Duration>` element** and confirm
  with `schtasks /Query /TN <name> /XML`. PowerShell's `$task.NextRunTime` can
  read EMPTY while `schtasks /Query /FO LIST` shows a valid time — trust
  `schtasks`, not the PowerShell object.
- **Do not set `Repetition.Duration = ''` via PowerShell.** It corrupts the
  trigger (NextRun becomes empty and the task stops firing). Re-create the task
  from XML instead.
- **`run()` only returns FINISHED trades.** A pending limit that has not filled
  yet is invisible to it, yet that is exactly what a trader is holding. Use
  `live_state()` in the bot to walk the bars with the locked params and report
  `pending` / `open` / `flat`. Verified 346/346 against the engine.
- **Telegram `getUpdates` must be called WITH the stored offset.** Without it
  Telegram re-serves the same update forever and `/status` gets answered on
  every poll. Store `tg_offset` after each batch.
- **Never cap the number of new signals** (`new[-3:]`-style). An uptime gap then
  silently drops real signals. Filter by bar age instead (`MAX_SIGNAL_AGE_H4_BARS`).
- **Login mode of Task Scheduler.** Use the XML definition with
  `<DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>` — on a laptop
  the GUI-created default silently refuses to run on battery and still reports
  `Last Result: 0`. Also set the FULL path to python.exe; the scheduler's PATH
  does not include the venv.
- **"Do I have to keep Hermes running?" — no, and answer it by naming what does."**
  The robot is a plain Python script fired by Windows Task Scheduler; Hermes is only the
  builder. The three things that must stay alive are the machine awake, MT4 open and logged
  in, and the network. Also say the 24h scratch prune touches only `hermes\cache\scratch` —
  never `hermes\trading\`, `signal_state.json`, the logs, or the frozen bundle in
  `assets/`. This user has decided a false signal once already; never leave doubt about what
  is generated by the rules and what was typed by you.
- `.bat` log filenames must not contain `%TIME%` colons; build a stamp from
  `wmic os get localdatetime` instead.

## TWO LOCKED FILES — H1 and H4 are siblings, never parent/child

| | `xauusd_method_LOCKED.py` | `xauusd_method_LOCKED_H4.py` |
|---|---|---|
| Method id | `...BT2-CAP30` | `...BT2-CAP30-H4` |
| Version | v1.0.0 | v1.0.0 |
| Timeframe | H1 | **H4** |
| Start | 2026-01-01 | **2025-05-01** |
| Dataset | `~/Downloads/XAUUSD60_REAL.csv` | `~/Downloads/XAUUSD240.csv` |
| Result | 165 trades / WR 56.4% / PF 2.15 | **346 trades / WR 58.7% / PF 2.38** |
| Net / DD | +$1480.24 / −$102 | **+$3510.48 / −$108** |
| Lock hash | `dda75a33ab3beb2a...` | `0c76e240d109d608...` |
| File sha256 | `bfb360af0f850474...` | `acc7d5beddae99db...` |
| Output CSV | `XAUUSD_Backtest_BT2_CAP30_REAL.csv` | `XAUUSD_Backtest_LOCKED_CAP30_H4_FROM_2025-05-01.csv` |

Both are fully self-contained (pandas only, no cross-imports). **Editing either one does not
affect the other** — verified: sha256 of the H1 file was unchanged after the H4 file was
created and nine drift tests ran. Neither imports the other.

Rules are identical. Only three things differ: `TIMEFRAME`, `START_DEFAULT`, and the reference
block. `TTL_BARS = 2` on H4 therefore means **8 hours**, not 2 — this is intentional.

### H4 beats H1 on everything — audited, not an artefact

Same overlapping window (May-2025 → Jan-2026), same method:

| metric | H1 | H4 |
|---|---|---|
| trades | 169 | 122 |
| win rate | 49.1% | **58.2%** |
| profit factor | 1.60 | **2.33** |
| net | +$929.60 | **+$1208.34** |
| max DD | −$246.00 | **−$90.00** |
| net/DD | 3.78 | **13.43** |

Two rival explanations were killed explicitly, and those numbers live in the H4 file's
docstring so they cannot be re-litigated silently:

1. **Not intrabar resolution.** Flipping every ambiguous bar to TP (most optimistic for both)
gives H4 PF 2.66 vs H1 1.76 — the gap survives. Ambiguity hit 4 of 122 H4 trades vs 4 of 169 H1.
2. **Not the 2-bar TTL.** Sweeping TTL 1–6 moves H4 only between PF 2.29–2.38 and H1 between
1.60–1.64. Flat plateau; the locked value sits on it, not on a spike.

Real cause: **fewer, cleaner signals** — 122 H4 entries against 169 H1 entries on the same bars.

`TTL_BARS` is a module global that `run()` reads at call time, so a script can override it for
a sensitivity sweep, but it must be restored immediately. Never leave it changed in the file —
the lock hash covers it.

## THE LOCKED FILE (start here)

`~/AppData/Local/hermes/trading/xauusd_method_LOCKED.py` — v1.0.0, id
`XAUUSD-SR-BREAKOUT-BT2-CAP30`. **This single self-contained file is the source of truth for
the cap-$30 method.** It reproduces the reference output byte-for-byte:

| Metric | Value |
|---|---|
| Dataset | `~/Downloads/XAUUSD60_REAL.csv` (2093 bars, 22-Jun→28-Okt-2026) |
| Trades | 165 (93 W / 72 L) |
| Win rate | **56.4%** |
| Profit Factor | **2.15** |
| Net | +$1480.24 / oz |
| Max DD | −$102.00 |
| Net / DD | 14.51 |
| Expectancy | $8.97 / trade |

```bash
python xauusd_method_LOCKED.py --verify    # exit 0 intact, 2 drift, 3 mismatch
python xauusd_method_LOCKED.py --export    # regenerate the reference CSV
python xauusd_method_LOCKED.py --csv <path> [--start YYYY-MM-DD]
```

Lock hash `dda75a33ab3beb2a...`. No imports from `bt2.py` or `backtest_engine.py` — it runs
standalone in any directory. **The cooldown rule is what makes this version correct:**
a new signal is blocked on the exit bar (`i - last_exit_i > cooldown`, cooldown=0).

`backtest_engine.py` is **deprecated for reporting**. It omitted the cooldown rule and shifted
loop/`prev_close` handling, producing 170 trades / WR 40.6% / PF 1.14 with **zero entries in
common** with the locked method. Every figure previously quoted from it — including WR57's
59% / PF 1.44 — is built on the wrong engine and must be recomputed on
`xauusd_method_LOCKED.py` before being quoted again.

## When to Use

- Backtesting or re-verifying the XAUUSD S/R breakout ruleset.
- Producing or sending live XAUUSD signals (hourly H1 scan, Telegram alerts).
- Wiring this strategy into n8n / MT4 / an external orchestrator over HTTP.
- Planning live deployment: choosing Telegram-only vs MT4 EA, local PC vs VPS, sizing a VPS.
  See `references/live-deployment.md` — read it before advising on hosting, scheduling, or EA design.
- Publishing, mirroring, or restoring the system to another machine or repo. Read
  `references/publish-and-verify.md` for what ships, what never ships, and the
  clone-based verification that must pass before calling a push done.
- Any request to quote this strategy's win rate, Profit Factor, or drawdown.
- Building, scheduling, or debugging the Telegram signal robot. Read
  `references/live-deployment.md` first — it carries the `.hst` decoder, the Windows
  Task Scheduler failure modes, and the signal-freshness rules.

## Explaining the method to the user

The user asks for the method "in human language" and models it on his own phrasing — a
step-by-step story of what the robot does, not a code walkthrough and not a parameter table.

- Write it as **numbered plain-language sections**, each one a behaviour, in the order the
  engine actually executes: the fixed level list → what it looks at each bar → the breakout
  test → the order it places → the expiry → TP → SL → one-position rule → the tie-break.
- Quote the tiny code fragment only *after* the sentence it explains (`prev_close <= L < close`),
  as proof the words match the file. Never lead with code.
- Draw the arithmetic out as a worked example with real numbers from the level list
  (level 3341.15 → buy limit 3344.15 → next level 3402.33 → $58.18 capped to $30 → TP 3374.15,
  SL 3326.15). Abstract descriptions do not land; a concrete ticket does.
- State plainly what the robot does **not** do (no trend, no indicators, no pyramiding, no
  break-even moves, no news, no lot sizing). The boundary is the most-repeated question.
- Correct wrong mental models explicitly rather than quietly using the right term: this user
  called it an "entry stop" — it is a **limit** order, and the why (it waits for price to come
  back $3 to the level instead of chasing) is the substance of the correction.
- Close with a one-paragraph summary in plain speech — that is the version he will re-read.

Do not slip into restating the mechanics as a feature list, and do not soften the honest
caveats: the high win rate comes from the 0.6 RR (win $30 / lose $18), not from superior
prediction. Say that in the same breath as the WR figure.

Strategy is **frozen at v1.0.1**. Parameters are byte-identical to v1.0.0 (the user chose cap $30
again explicitly). Only the `backtest_reference` block was corrected. Never tune parameters
silently. Any change requires a new `strategy_id`, a fresh backtest, and explicit user approval.

## Locked parameters (do not change)

| Param | Value |
|---|---|
| Entry buffer | `$3.00` from level |
| TP cap | `$30.00` from entry |
| SL | `0.6 × TP distance` |
| Order TTL | **2 bars** (locked file, matches reference) |
| Timeframe | H1 |
| Positions | 1 at a time |
| Breakout confirm | H1 **close** crosses level (not intrabar wick) |

## Rules

- **BUY**: H1 close crosses a level upward → limit BUY at `level + $3.00`
- **SELL**: H1 close crosses a level downward → limit SELL at `level − $3.00`
- **TP**: nearest level ahead, capped at `entry ± $30.00`
- **SL**: `entry ∓ (tp_distance × 0.6)`
- No new signal while a position or pending order exists.

## 38 red_levels

```
5588.06 5388.69 5313.63 5233.88 5158.82 5095.43 5022.29 4946.21
4848.09 4792.35 4724.22 4674.34 4629.67 4573.13 4522.37 4485.45
4431.23 4379.14 4348.00 4313.65 4242.80 4184.34 4144.23 4101.26
4062.25 4023.16 3988.70 3931.48 3868.45 3787.70 3733.87 3703.29
3676.37 3622.54 3572.38 3474.51 3402.33 3341.15
```

## Two frozen strategies exist — do not confuse them

Both live in `~/AppData/Local/hermes/trading/` and share the 38 red_levels.

| | CAP30 (original) | CAP20-FIXED (user's file) |
|---|---|---|
| File | `strategy_FROZEN.json` | `strategy_CAP20.json` |
| Lock | `strategy.lock` | `strategy_CAP20.lock` |
| Verifier | `verify_frozen.py` | `verify_cap20.py` |
| State | `state.json` | `state_cap20.json` |
| TP rule | next level, capped $30 | **flat $20, ignores levels** |
| SL rule | 0.6 × TP distance | flat $12 |
| Version | v1.0.1 | v2.0.0 |
| Reported perf | 173 trades / WR 40.5% / PF 1.13 | 176 trades / WR 57.4% / PF 2.24 |

**The TP rule is the critical difference.** CAP30 measures to the next level then caps it;
CAP20-FIXED always uses exactly $20 no matter where the next level sits. In the user's source
file **0 of 176 TPs landed on a level** — that is how the flat-$20 rule was identified.

Select with `XAU_STRATEGY=cap20` (default `cap30`). Each gets its own state file, so one
strategy holding a position never masks the other's signal.

```bash
python verify_frozen.py          # cap30: params + full backtest reproduction
python verify_cap20.py           # cap20: params + rule-consistency vs source file
XAU_STRATEGY=cap20 python signal_engine.py --status
```

### Provenance of the CAP20 numbers — read before quoting

The CAP20 parameters were **reverse-engineered from the user's trade rows**, not chosen.
Each is provably constant: TP exactly $20.00 and SL exactly $12.00 on all 176 rows, zero
overlapping trades, and all 29 traded levels resolve to known red_levels at buffer $3.
That part is verified — `verify_cap20.py` exits 0.

But the **performance figures are the user's, not reproduced locally.** Running the same rules
through `backtest_engine.py` on `XAU_1h_data.csv` gives at best n=148–154, WR ~40.7%,
PF ~1.14 — nowhere near 176/57.4%/2.24. The gap is unresolved. `strategy_CAP20.json` records
`reproduced_by_local_engine: false` and explains why. Never present CAP20's PF 2.24 as
independently verified.

## WR57 candidate — reaches 57% but does NOT generalise

`strategy_WR57.json` v3.0.0, status **CANDIDATE** (never FROZEN until forward-tested).
Verifier `verify_wr57.py`.

| Param | Frozen cap30 | WR57 candidate |
|---|---|---|
| buffer | $3.0 | **$2.5** |
| RR (SL) | 0.6 | **1.0** |
| ttl | 3 bars | **8 bars** |
| cap | $30 | $30 |

On `XAUUSD60 new.csv`: **122 trades, WR 59.0%, PF 1.44, net +$653.20, DD −$180** — clears
the 57% target on 3 walk-forward slices (59.4 / 58.1 / 59.0) and 19 rolling 30-trade windows
(median 60%, 58% of windows ≥57%).

**It fails the 20-year test: WR 43.5%, PF 0.77, net −$483 on `XAU_1h_data.csv` 2016-2026.**
The rule is tuned to the 2026 sample. `verify_wr57.py` deliberately asserts this failure stays
true — if that check ever passes, the caveat is stale and the strategy must be re-evaluated.

Why the win rate rises: widening SL from 0.6× to 1.0× of TP distance is the whole lever.
WR goes up because each loss is the same size as each win, not because the signals got better.
PF 1.44 with avg $5.35/trade leaves little room for cost.

Statistical honesty: 122 trades gives a 4.45pp standard error, so the true WR is plausibly
50–68%. 200 configs were swept; 6 cleared 57% where chance alone predicts 2–3.

## The 38 levels only exist in a 10-month price window

The locked levels span **3341.15 – 5588.06**. Gold traded 381–2788 from 2004 to 2024, so the
breakout engine **cannot fire** there. On `XAU_1h_data.csv` (125,206 bars, 2004→2026-01) only
**2,833 bars = 2.26%** fall inside the level zone, starting **2025-04-16**. A "20-year backtest"
of this method is really a **~10-month test** (Apr-2025 → Jan-2026). Always state this instead of
quoting the file's nominal span — otherwise the sample looks 20× bigger than it is.

Result on that file: 180 trades, WR 48.3%, PF 1.55, net +$923.60, DD −$246.00, expectancy
$5.13/trade. Second half deteriorates (WR 51.1%→45.6%, PF 1.73→1.39, DD −150→−246).
29 of 38 levels traded; level 3341.15 alone produced 32 trades at WR 31.2% / −$96, and
4101.26 + 4348.00 + 4313.65 carried +$450 of the +$924. Level concentration is the main risk.

## Performance — reproduced figures only

For the cap-$30 ruleset on `XAUUSD60 new.csv` (2146 bars, 22-Jun → 30-Oct-2026), reproduced
with `backtest_engine.py` (buffer $3, cap $30, RR 0.6, TTL 3):

| Metric | Verified value |
|---|---|
| Trades | 173 |
| Win rate | 40.5% |
| Profit Factor | **1.13** |
| Net | +$242.65 / oz |
| Max drawdown | −$223.49 |
| Net / DD | 1.09 |

**The edge is thin.** PF 1.13 with Net/DD ~1.1 is a marginal system, not a strong one. Size
accordingly and do not present it as high-conviction.

History: v1.0.0 recorded 169 trades / WR 55.6% / PF 2.08 / Net +$1,456 / MaxDD −$102. Those
figures were produced by a scratch script that was first pruned, then **recovered from session
history** — and on re-run they reproduce exactly. So the numbers are real; they are simply the
output of a *different* engine than `backtest_engine.py`, which yields 173 / 40.5% / 1.13 on
the same file. Matching trade counts (±4) with a 15-point WR gap points at exit resolution
(intrabar TP-vs-SL tie-break) or the pending-fill rule, not at fabricated data.

**SETTLED: `bt2.py`'s 169/55.6%/2.08 numbers are the correct lineage.** That engine's logic is
what `xauusd_method_LOCKED.py` now preserves (165/56.4%/2.15 on `XAUUSD60_REAL.csv`; a lower
trade count because that dataset ends 28-Okt vs 30-Okt). `backtest_engine.py` is the defective
one — it lacks the exit-bar cooldown and therefore grows a completely different trade set.
An independent bar-by-bar re-walk of the locked trades disagrees on only 2 of 165, so the
figures below are sound under the method's own rules. See `references/backtest-reproducibility.md` for the recovery
recipe and the ambiguity table.

Why it matters: an unreproducible number is worse than a weak one, because it gets traded on.
When a claim and the engine disagree, the engine wins — and the correction gets reported to
the user loudly, not quietly absorbed.

See `references/backtest-reproducibility.md` for the failure mechanism and re-derivation
procedure.

## Files (all under `~/AppData/Local/hermes/trading/`)

| File | Purpose |
|---|---|
| `strategy_FROZEN.json` | **Single source of truth** for params + levels |
| `strategy.lock` | Checksum guard against drift |
| `backtest_engine.py` | Backtester (`run`/`stats`); permanent, never in scratch |
| `signal_engine.py` | Live scanner; reads params from the frozen JSON only |
| `verify_frozen.py` | Proves strategy intact + reproduces backtest |
| `signal_service.py` | HTTP bridge for n8n / external callers |
| `config.json` | CSV path, Telegram token/chat id |
| `state.json` | Open position / pending order / closed trades |
| `signal_live_h4.py` | H4 Telegram bot: `--run` / `--poll` / `--status` / `--dry` / `--test` |
| `xauusd_bundle.py` | Self-restoring bundle: 9 files base64-embedded, `--verify`/`--restore`/`--list`/`--diff` |
| `run_signal.bat`, `poll_only.bat` | Scheduled runners; FULL absolute path to the venv python |
| `register_tasks.bat` | Recreates both Windows scheduled tasks incl. `DisallowStartIfOnBatteries=false` |
| `CEK_STATUS.bat` | Manual health check: status + both verifiers + schedule |

Cron wrapper: `~/AppData/Local/hermes/scripts/xauusd_signal.py`

## Commands

```bash
cd ~/AppData/Local/hermes/trading
python verify_frozen.py          # ALWAYS run first: checks drift + reproduces backtest
python signal_engine.py --dry    # scan once, print, no Telegram
python signal_engine.py --status # show open position + running stats
python signal_engine.py          # scan and send to Telegram

# HTTP bridge for n8n (test against a sandbox config, never production state)
python signal_service.py --port 8787
python signal_service.py --port 8788 --config <sandbox>/config_test.json
```

## Raising win rate without fooling yourself

The user asks for a target WR ("get me 57%"). The efficient path, in order:

1. **Widen the SL ratio first — it is the direct lever.** RR 0.6 → 1.0 moved WR 40.5% → 59%
   on the same bars. Understand *why*: losses become the same dollar size as wins, so WR rises
   without the signals improving. Say this out loud, or the user thinks the edge improved.
2. **Sweep buffer, TTL, and RR jointly on a TRAIN slice**, then judge on a holdout slice. Every
   config that wins only in-sample is a rejection.
3. **Re-run the survivors on a second dataset from a different era.** `XAU_1h_data.csv`
   (2004-2026) is the brake on 2026-only tuning. Every 2026 winner so far dies there — the
   WR57 config earns PF 0.77 across 20 years.
4. **Check the shape is a plateau, not a spike.** Perturb ±1 step in each parameter and print
   the block. A lone high cell surrounded by collapse is noise.
5. **Report how many configs you tried.** 200 sweeps → ~3 clear any threshold by chance;
   6 clearing 57% is suggestive, not proof.
6. **Compute the standard error before quoting.** `sqrt(wr(1-wr)/n)`; n=122 gives ±4.5pp, so
   "59%" honestly means "50–68%".
7. **Charge realistic cost.** Gold round-trip ≈ $0.3–1.0/oz. At $5.35/trade the system survives
   $2; at $1.40/trade it does not.

If steps 2–4 fail, deliver it as a **CANDIDATE** with the failing check recorded in the
strategy JSON and **asserted by the verifier** so the caveat cannot be quietly dropped later.
Never promote a tuned config to FROZEN on the strength of the sample it was tuned on.

## Pitfalls

- **Never store the backtester in the scratch dir.** Hermes prunes scratch after 24h idle;
that destroyed the engine that produced the original numbers. `backtest_engine.py` lives
permanently beside the strategy. Recovery recipe (scripts ARE restorable from session history):
`references/backtest-reproducibility.md`.
- **`python -c` one-liners and `&&` chains hide exit codes.** A failing verifier piped into
`tail` still reports the pipeline's last exit. Run verifiers un-piped and read `exit=$?`.
- **`&&`-chained shell also swallows exit status** — capture `python x.py > f 2>&1; echo $?`
before echoing anything else, not `python x.py && echo ok`.
- **Sort before comparing timestamps.** A single-position overlap check that sorted by the
`DD-Mmm-YY` *string* but compared parsed datetimes reported 40 false overlaps. Assign parsed
columns first, then sort on those.
- **Verify level lists by set-difference against the source, never by eye.** Hand-transcribing
38 levels dropped `4062.25` and mistyped `4724.22` as `4724.34`. Load both, `set(new) - set(old)`,
assert empty.
- **Don't hand-transcribe decimal arrays at all** — generate them with `json.dump` from the
source file. Two transcription errors in one 38-item list is the expected rate.
- `signal_engine.py` takes `--csv`; `signal_service.py` takes `--config`. Mixing them up gives
`unrecognized arguments`.
- For a breakout to fire, the crossing bar must be the **last** row of the CSV — the engine
evaluates the latest closed bar only. A test fixture whose cross happens mid-file reports
"no signal" and looks like a broken engine.
- Reverse-engineering a user's trade file: derive params from columns (TP−Entry, SL−Entry),
not from a `Keterangan` label. Check whether TP lands on a level to distinguish
next-level-targeting from a flat distance — 0 of 176 TPs on a level proved the rule was a
flat $20, not "next level capped".
- `XAU_1h_data.csv` is semicolon-delimited **with** a `Date;Open;High;Low;Close;Volume` header;
`XAUUSD60 new.csv` is comma-delimited with no header. Load them differently.
- **Always run the strategy's verifier before trusting a signal run.** `verify_frozen.py` exits
2 on parameter drift, 3 on backtest mismatch. Both are blockers.
- **When a verification disagrees with the stored reference, report the disagreement.** Do not
edit the reference to match the engine — that converts an unknown into a claim.
- The engine raises `SystemExit` if `strategy_FROZEN.json` is missing or `status != FROZEN`.
Never bypass it by hardcoding params back into the script.
- **cap $20 and pivot-cluster (touch-count) level rebuilds both failed out-of-sample**
(PF 1.39 and 0.93). Do not resurrect them. The one rebuild that held out is structural —
fractal k=5, cluster tol $8, min dist $30, fit on TRAIN only (`strategy_SWING.json`) — but its
edge is thin (~$0.77/trade gross, negative after $1/oz) and one level carried most of the net.
- The CSV must be refreshed from MT4 before scanning. A stale CSV produces no signals rather
than wrong ones, but it will also never fire.
- When a bar hits both TP and SL, this engine resolves it as **SL**. Pin every exit ambiguity
the same way rather than leaving it implicit — see the ambiguity table in
`references/backtest-reproducibility.md`.
- **`run()` re-walks the whole file from bar 0 every call — it carries no state across
  invocations.** For backtesting that is correct and must not be "fixed". For live it is the
  central defect: a re-run in mid-session does not know about the position already open at the
  broker, so it will emit a fresh entry signal while one is running. Any live wrapper MUST
  persist `pos` / `pending` / `last_exit_bar` in a state file and replay the locked engine's
  decisions before announcing anything. Never add the state to the locked file — the lock hash
  covers the module globals.
- **Never cap a batch of pending signals with a slice.** A `new[-3:]` guard looks like spam
  protection and is really silent data loss: any multi-bar gap (laptop asleep, MT4 closed)
  truncates the newest real signal out of the state, and it never gets announced. Bound by
  freshness (drop signals older than a few bars) instead of by count.
- **`Last Run Time` drifting hours behind the `PT5M` schedule means the laptop is asleep or
  locked, not that the robot is broken.** A managed machine that locks on idle stops firing
  scheduled tasks without writing any error; `schtasks /Run` succeeding instantly while the
  trigger does nothing proves the code is fine and the host is the fault. Report it as the host
  failing and name the three things that must stay alive (machine awake, MT4 logged in, network)
  — never restate it as "Hermes must be running". Hermes is not in the runtime path.
- **A scheduled Windows task can report `Last Result: 0` and still never have run.** Never
  accept the scheduler's status as proof; delete the logs, trigger the task, and confirm a
  non-empty log file appeared. `DisallowStartIfOnBatteries` (default on for `schtasks /Create`)
  and a missing `python` on the task's PATH are the two causes that reproduce every time.
  Full recipe: `references/live-deployment.md`.
- **Re-deriving "today's closed bars" from the locked engine truncates the open position.**
  `stats()` on a truncated window misreports drawdown and breaks the `--verify` reference.
  The lock is for auditing; the live path keeps its own state and reads only the signal.
- **`--export` fails with a bare `PermissionError` when the target CSV is open in Excel.**
  Write to a different `--out` and `cmp` it against the reference instead of telling the user
  the export broke.

## Reporting style for this user

- Give the verdict first, then the table, then what is still blocked. Indonesian.
- When asked to publish, mirror, or bundle the system, ship **everything**: both
  locked methods, the bundle, every runner `.bat`, both docs, the skill, and the
  reference data needed to reproduce `--verify`. "Tanpa terkecuali" is literal —
  never pick a subset on the user's behalf.
- Never commit credentials, and never accept one pasted into chat. Read tokens
  from a file the user places themselves; put `tg.json` in `.gitignore` and say
  in the README why it is absent.
- Before reporting a push as done, verify: commit exists, the file count matches
  what you intended, `git ls-files | grep -i tg.json` is empty, and a **fresh
  clone** of the repo passes both `--verify` runs. A commit on disk is not a
  verified repo.
- When access is missing, deliver the staging instead of stalling: a committed
  repo in a durable path (`~/Documents/OTHER/…`, not the pruned scratch dir), the
  `origin` remote set, a one-click `PUSH.bat`, and a `CARA-PUSH.md` with a
  token/permission troubleshooting table.
- State a number only when you reproduced it. If a claim failed to reproduce, say so at the
  top of the reply, not buried at the end — this user actively checks for results that drift
  between runs and treats a quiet change as a defect.
- Do not present a reconstructed engine's output as confirmation of an older claim. Say
  plainly which figures are reproduced and which are merely recorded.

## Changing the strategy (only with explicit user approval)

1. Copy `strategy_FROZEN.json` → `strategy_<newid>.json` with a **new** `strategy_id` and version.
2. Backtest it on at least two datasets, including a held-out period.
3. Only if it beats cap-30 out-of-sample, promote it and delete `strategy.lock` to re-lock.
