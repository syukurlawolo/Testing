# Live deployment — Telegram signals and MT4 execution

Depth for turning the locked method into a running robot. Only needed when the user is
planning or building live deployment; backtest work does not require it.

## What the robot actually needs

Less than it looks. The engine reads exactly three things: the previous bar's close, the
current bar's close, and its own memory of open position / pending order / last exit bar.
No indicators, no lookback buffers, no database, no GPU.

That last item is the whole problem. See "The state gap" below.

## The state gap (read this before proposing any architecture)

`run()` starts at bar 0 and replays the entire file on every call. It is deliberately
stateless between invocations. For a backtest that is what makes it honest.

For live it means:

- Re-running mid-day re-derives every historical trade and knows nothing about the position
  currently open at the broker.
- With no persisted state the wrapper cannot know whether an entry is already live, so it
  will happily announce a second one.
- The locked method allows **one position at a time**, so a duplicate entry is a direct
  violation of the ruleset, not just noise.

So a live robot is the locked engine **plus** three additions that must live outside the
locked file:

1. **A state file** — open position, pending order, bar index of last exit.
2. **A scheduler** — fires on each closed H4 bar (H4 → six checks a day: 00/04/08/12/16/20).
3. **A delivery layer** — Telegram message, and/or a signal file for the EA.

Never modify the locked file to carry state. The lock hash covers its module globals; adding
a mutable field trips `--verify` and destroys the audit trail. Write a separate wrapper that
imports it read-only.

## Price feed: read MT4's own `.hst` history, not a CSV

`XAUUSD240.hst` inside the MT4 data directory is the best live source — MT4 refreshes it
while the terminal is open and logged in, so no CSV export step is needed:

`%APPDATA%\MetaQuotes\Terminal\<instance-id>\history\<Server>\XAUUSD240.hst`

Binary layout, version 401 — **header 148 bytes, then 60-byte records**:

```
t(i64)  O,H,L,C (4 x f64)  vol(i64)
```

Decode with `struct.unpack('<q4dq', b[off:off+48])` after skipping 148 bytes. **Time and
volume are int64, not int32** — reading them as `<i` shifts every price field by 4 bytes and
produces huge/negative floats plus timestamps outside any sane range, so the whole file decodes
to garbage and the reader raises "no plausible bars". That single wrong width is what made the
bot's `.hst` path fail silently while it kept serving a stale fallback.

The reliable way to pin the stride: try candidate record sizes against the file length and
require a zero remainder — `(len - 148) % rec == 0` gives exactly one answer among
40/44/48/52/56/60/64 (60 for this broker). Then confirm the decode by eye on the LAST records
(they should be the most recent H4 bars) and by replaying it through the locked engine: **bars
sourced from `.hst` must reproduce the locked trade count exactly** (346 for H4). A mismatched
count means the binary decode is wrong, not the strategy.

**Watch the timestamp zone.** Raw `.hst` timestamps on this broker decode to the bar time
minus **2 hours** versus the CSV the user exports (an `.hst` bar stamped 17:00 is the CSV's
19:00). So `.hst` is effectively GMT while the export is server time. Never feed both sources
into the same state file without normalising — a silent 2-hour shift moves every bar boundary
and therefore every entry.

**Prefer the EA feed CSV over `.hst` whenever it exists.** `signal_live_h4.py` reads
`MQL4/Files/XAUUSD_H4_FEED.csv` first and falls back to `.hst` only when the feed is missing or
older than `FEED_MAX_AGE_MIN` (currently 300 min). Print
which source was used and its file age on every run; silently serving the stale fallback is the
failure shape. Validate the feed against the old export by checking one overlapping bar is
identical (same O/H/L/C, same clock) before trusting it — the EA writing server time is what
makes bar boundaries match the locked method, so a zone shift here moves every entry.

**Two different age limits, and confusing them is the bug.** `FEED_MAX_AGE_MIN` decides *which
file to read*; it is not a data-quality gate. Set it to one full timeframe plus slack (300 min
on H4), because the EA only rewrites the CSV when a bar closes plus a 60-second heartbeat — a
90-minute limit means one missed heartbeat makes the fresh feed look dead and the reader falls
back to `.hst`, which can be **days** older. The robot then computes signals from two-day-old
bars and announces them as live. The real gate is separate: `MAX_DATA_AGE_H` (5.0) checked on
the newest bar's timestamp against `SERVER_UTC_OFFSET_H`, and everything that sends must obey
it.

- **A source-selection failure is invisible unless you print the source.** Every run must print
  `<filename> bars N <first> -> <last> (server TZ) age Xh` — a run that says `.hst` while a feed
  exists is the defect, and nothing else in the output reveals it.
- **When data is too old, send NOTHING — do not send a warning to the trade channel.** Return
  before `scan()`, print the reason plus the source filename, and record `data_stale` in the
  state for `/status`. Announcing "data mati" as a signal message trains the user to ignore the
  channel; the only place a stale-data notice belongs is a report he asked for.
- **`/status` and the sender must share the constant.** A report that says "data is fine" while
  the sender refuses to send is worse than either alone — replace any hardcoded `> 6` style
  threshold in the report with the same `MAX_DATA_AGE_H` the sender uses.
- **Prove the gate by simulating a dead feed, not by trusting the branch.** Slice the bars to an
  older cut, patch `read_bars()` to return the slice plus a `.hst` Path, and assert the output
  contains the stale line and that the state file gained no new `sent` key.

**A frozen `.hst` mtime is NOT evidence the feed is dead — MT4 streams into memory and only
flushes history to disk when it closes, when the symbol/timeframe reloads, or when the
terminal pulls older history.** An open, logged-in terminal showing a live price can leave
every `.hst` untouched for an entire session; that is normal behaviour and the normal shape of
it is *many* frozen files at once (H1, H4, M15, M5, M1 all stuck at the startup minute), not
only the timeframe you happen to be looking at. Before concluding "data beku", establish
whether the feed is alive by other means — the terminal window title (`tasklist /V` shows
`<account>: <Server> - [<SYMBOL>,<TF>]`, which proves both login and which chart is open) and
the user watching the price move. Say "data tidak masuk ke disk" and not "data mati"; they
lead to opposite fixes.

Three observations that look like breakage and are not; check each before diagnosing:

- **Let the user be the tie-breaker on the terminal's state.** He can see the connection status
  and the moving price; a screenshot or one sentence from him outranks any file-derived
  inference. Two consecutive wrong diagnoses ("the H4 chart isn't open", "the account isn't
  logged in") both came from reading profile/config files instead of `tasklist /V`. Reading
  `terminal.ini` for a `DataPath` is not a shortcut — the data folder path is the
  `%APPDATA%\MetaQuotes\Terminal\<instance-id>` directory itself.

**The feed only advances while MT4 is running and logged in.** A closed terminal freezes
`XAUUSD240.hst`, and the robot then reports "no new signal" forever. Always print the newest
bar's timestamp and age in status output, and tell the user MT4 must stay open.

**For a robot, the durable answer is an MQL4 feeder EA, not reading `.hst` or an outside API.**
The EA lives inside MT4, so it reads the live price directly (zero basis, unlike `GC=F` at
~$33/oz) and writes each closed H4 bar to a plain CSV — bypassing the flush problem entirely.
Propose it in that order of preference and be explicit about the trade-off: it needs
`Tools → Options → Expert Advisors → Allow automated trading`, and it must be built and then
tested by the user on demo, because MQL4 cannot be verified from here. Do not offer it as
"certainly works" — the user is on a broker where EA permissions differ.

How the feeder is shaped, so it is re-specified rather than re-invented: `OnInit()` dumps the
last `InpKeepBars` bars immediately (the user must see file output within seconds, not after a
4-hour wait) and `OnTick()` re-dumps only when `iTime(sym, PERIOD_H4, 0)` changes, plus a
throttled status file (`server_time`, `local_time`, `bid`, `terminal_connected`,
`last_bar_time`). It never opens an order. Both files land in `MQL4/Files/`, which starts
empty — probe that folder to confirm the EA is alive instead of asking the user to describe
his chart.

**The three `Disable automated trading when…` checkboxes must stay UNCHECKED.** They only ever
*turn the EA off* — on account change, profile change, or symbol/timeframe change. The third
one is actively hostile to this workflow: forcing a history reload by switching H4→H1→H4 kills
the feeder, and it dies silently. Tick `Allow automated trading` and the toolbar AutoTrading
button; leave the three Disable boxes and the DLL/WebRequest imports alone.

**MQL4 compilation cannot be driven from here — hand it back with exact steps, do not keep
trying.** `metaeditor.exe /compile:<path> /log:<path>` exits 0 and produces no `.ex4`, and a
second instance is refused while MetaEditor is already running. Writing the `.mq4` plus the
F7 → drag-to-chart instructions IS the deliverable; the user compiles. Say that plainly the
first time instead of burning calls on it. Confirm the EA is alive by reading
`MQL4/Files/*_STATUS.txt` afterwards — that is real evidence, unlike "the smiley is there".

## The three hosting options, honestly compared

| Option | Automatic execution | Cost | Real catch |
|---|---|---|---|
| **A. VPS + n8n** | No — needs an extra bridge | VPS only | **n8n cannot talk to MT4.** MT4 only accepts orders from an EA inside its own terminal. n8n adds a layer to maintain without adding the capability asked for |
| **B. VPS Windows + MT4 + EA** | **Yes** | ~$6–15/mo | Only path to true automation. Needs a Windows VPS, MT4 kept logged in, and an EA written in MQL4 (not Python) |
| **C. Local PC + MT4** | Yes, while the PC runs | $0 | PC must be awake and online at each H4 close. Missed bars are missed, not replayed |

When the user asks for "execution in MT4 AND signals in Telegram", only B delivers both.

**Recommend C → B, never straight to A.** Run Telegram-only on the local machine for two to
four weeks first. The method is backtested, not forward-tested; a bug in an EA executes itself
with real money. Telegram captures ~90% of the benefit at zero cost and zero risk.

Rejecting A is a real finding, not a preference: it is the option that costs money and still
does not satisfy the stated requirement.

## VPS sizing for option B

Grounded in published MT4-VPS figures, not guesses:

| Component | Spec | Why |
|---|---|---|
| OS | Windows Server 2019/2022 64-bit | MT4 has no Linux build |
| CPU | **2 vCPU, high clock** | MT4 is single-threaded per terminal; prefers GHz over cores. 2 × 3.0 GHz beats 4 × 2.0 GHz |
| RAM | **4 GB** | Windows Server idles at 1.0–1.5 GB; MT4 with charts + EA is 200–500 MB; Python wrapper ~150 MB. A 2 GB plan leaves ~800 MB and no headroom |
| Disk | 60 GB SSD | Windows ~25 GB, MT4 + history ~5 GB |
| Bandwidth | 1–2 TB/mo | MT4 is light; latency matters, throughput does not |
| Location | **nearest the broker's server** | Only VPS choice that actually affects fills. Under 5 ms target |
| SLA | 99.9% written, "forex VPS" provider | Cheap general-purpose VPS restarts silently and throttles CPU, which strands the EA |

Operational ceiling to quote: sustain CPU under 80% and RAM under 75%.

Also worth telling the user: some FX brokers give a free VPS at a trading-volume threshold.
Ask the broker before renting anything.

## Telegram delivery

- **The user's first question after any `/status` change is "does it answer, and does it show the
  latest price?"** Answer it with a run, not an assurance: quote the rendered report. And separate
  the two facts plainly when they differ — the report price is the last H4 close, the live price
  comes from `XAUUSD_H4_STATUS.txt` (`bid`, `ask`, `spread`, `server_time`), and the gap between
  them can be several dollars. `read_ea_status()` parses that file, marks it `fresh` when the mtime
  is ≤5 minutes, and the report prints `Harga sekarang` above `Close lilin terakhir`. It is
  display-only: it must never enter `live_state()`, `scan()` or any entry/TP/SL arithmetic, and
  say so in the same message so the number cannot be mistaken for a method change.
- **A feed whose mtime is older than the bar cadence is normal, not a fault.** The feeder EA
  rewrites the CSV when an H4 bar closes plus a heartbeat; mtime drifting toward two hours means
  the heartbeat is not firing, which is worth one sentence and no alarm while the bar is still
  inside `MAX_DATA_AGE_H`.
- Bot token from `@BotFather`, chat id from `@userinfobot`. Both free, two minutes.
- **Never accept the token pasted into chat.** Put it in `config.json` or an env var and read
  it from there. If it was ever typed into a conversation, treat it as leaked and have it
  regenerated.
- A silent Telegram is the expected state most of the time on H4 — six possible signals a day,
  often none. Say this up front so silence is not mistaken for a broken robot.
- **A stale price feed produces silence, not an error.** That is the dangerous failure mode:
  no signal looks identical to "nothing to do". Have the wrapper report feed age, and alarm
  when the newest bar is older than one H4 period.

## Scheduling on Windows without a VPS

Register the runner with Task Scheduler: six daily runs, five minutes after each H4 bar
closes in local time (H4 closes on the MT4 server at 03/07/11/15/19/23 GMT+3 → local
07/11/15/19/23/03 GMT+7).

```bash
schtasks /Create /TN "XAUUSD_Locked_H4_Signal" ^
  /TR "\"C:\...\run_signal.bat\"" ^
  /SC DAILY /ST 07:05 /RI 240 /DU 24:00 /F
```

Four failures cost real time here. Each reports success while doing nothing:

1. **`DisallowStartIfOnBatteries=true` on a laptop.** The task never starts, yet
   `Last Result` still reads `0`. Default `schtasks /Create` sets it. Create the task from an
   **XML definition** with `<DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>`
   and `<StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>`, or the robot is silently dead
   whenever the machine is unplugged. Otherwise assume the setting is the cause and prove it.
2. **`python` is not on the task's PATH.** The batch ran fine interactively and failed under
   the scheduler with `'"python"' is not recognized`. Resolve the interpreter once
   (`python -c "import sys; print(sys.executable)"`) and hardcode that absolute path in the
   wrapper — the venv path, not the launcher.
3. **`/RL HIGHEST` needs elevation.** Without an elevated shell it fails with
   `ERROR: Access is denied`. Omit it; the task runs as the logged-in user.
4. **A colon in `%TIME%` silently kills the log redirect.** `run_%TIME%.log` contains `15:39:02`,
   dots and colons are illegal in filenames, and the redirect produces no file with no error.
   Build the stamp from `wmic os get localdatetime` (`!LDT:~0,4!-!LDT:~4,2!...`) instead.

Verification sequence that separates "task fired" from "task lied": delete the logs, run
`schtasks /Run`, wait ~15 s, then check that a **log file actually appeared** and is non-empty.
`schtasks /Query /FO LIST /V` is necessary but not sufficient — `Last Result: 0` with no log
file means the action never ran. Probe with a one-line bat writing to a known path before
wrapping the real work, and delete the probe tasks afterwards.

### Session lock and sleep stop the trigger, not just the network

The same host condition that kills networking also stops the schedule: on a managed laptop,
`Last Run Time` can sit hours behind a `PT5M` repetition while `Next Run Time` keeps showing a
valid future slot and a manual `schtasks /Run` still returns `Last Result: 0`. Read it as
**host down, code fine**: compare `Last Run Time` against the newest log filename in `logs/`,
then leave the machine locked for one or two repetition intervals and re-check — that test
costs nothing and cleanly separates lock/sleep from a scheduler defect. Combined with a frozen
`.hst` (newest bar hours old, `terminal.exe` still alive but disconnected) this is the normal
shape of "the robot went quiet overnight" on a work machine. Answer it by naming the three
things that must stay alive — **machine awake, MT4 logged in, network** — not by telling the
user to keep Hermes open; the scheduler calls python directly and Hermes is not in that path.

## Bot message layout (copy-paste friendly)

The user's signal ends up pasted into a phone app by hand, so the Telegram message
is a *data entry form*, not a report. `fmt_signal()` builds it as:

- `Entry` / `TP` / `SL` — bold label, then `<code>` around the bare number only, then
the delta in plain text. Tapping the number copies just that number.
- Supporting facts below (`Level broken`, `TP target`, `Signal bar`, `Valid for`) stay
plain — they do not need to be copied and making them tappable invites mis-pastes.
- Final line is the action (`→ Pasang BUY LIMIT di <entry>`) plus the expiry rule in
  plain words (`Batalkan kalau belum terisi dalam 8 jam`), because that is the line
the trader actually acts on.

Verify a layout change by rendering `fmt_signal()` on a dict with fixed numbers and
printing the raw HTML — the markup is what matters, and a screenshot cannot show
whether the `<code>` tags landed in the right place. Then send one clearly labelled
**CONTOH TAMPILAN — BUKAN SINYAL** message with invented numbers so the user can test
the tap himself; never send an unlabelled example, and never leave him wondering
whether the number he is about to paste is real.

## Proof-of-life test: "does it work if I close Hermes?"

When the user asks whether the robot still runs without Hermes, do not assert it — prove it
with a scheduled one-off they can watch, and keep the proof file afterwards:

1. Create a one-shot task: `schtasks /Create /SC ONCE /ST HH:MM /SD DD/MM/YYYY /TR "<bat>"`,
   where the `.bat` is a wrapper in `hermes\scripts\` calling a script kept in `trading\`.
2. The script must self-guard: send only if now is inside `[due, due+30min]`. A late trigger
   then cannot fire a stale message, and the guard replaces the need to delete anything.
3. The message must be unmistakably a test: first line says it is an example, and a line says
   the numbers are invented. Never send an unlabelled example when no real signal exists — the
   user has already challenged one such message, and a false signal costs more trust than a
   failed test.
4. Tell the user exactly what to do (close Hermes, screen stays unlocked) and where the result
   is logged, then check the log and quote the timestamp it printed.

Reuse the real task's XML settings (`DisallowStartIfOnBatteries=false`, no `<Duration>`) so the
proof is proof for the real schedule too. The script stays on disk afterwards; the task is not
rescheduled, which is enough to prevent a repeat.

## `/report` — monthly history that must equal the backtest

A report the user compares against the backtest on his own is only useful if it is *the same
engine*, so build it from `track_orders()` and nothing else:

- One walk over the bars with the locked params yields both finished and live orders (`state`,
  `bar`, `sig_ts`, `exit_i`). Derive the month's rows, the exit label (`TP` / `LOSS` /
  `lagi running`), the WR line and the trailing PLANNING block from that single source.
- **Verify against the reference totals before sending:** 354 orders, 348 finished, 204 TP /
  144 SL, WR 58,62%, 6 cancelled on the current feed. If those move, the report and the
  backtest have forked and that is the finding — do not ship it with a note.
- **PLANNING row comes from `live_state()`**, not from the last row: `flat` → the two conditional
  levels with their `$3` limit entries, TP/SL and the 8-hour expiry; `pending` → the live order
  and hours left; `open` → the filled position framed as running. Only a `pending` may be
  phrased as an instruction to place something.
- Bars still forming are excluded and that exclusion must be visible in the message, otherwise
  a short list reads as missing signals.

## Keeping the bot honest about signal freshness

The state file alone is not enough. After downtime, the newest derived trade can be hours or
days stale, and announcing it hands the user a limit order the method would have cancelled.

- Store announced signal keys plus `last_signal_key`; on each run, take everything **after**
  that key *and* newer than the age bound.
- **One function must build the key, or dedupe never matches.** The comparison key and the key
  written into state have to come from the same helper (`sig_key(trade)`). A live signal built
  on the fly with an ad-hoc `f"{type}|{entry}|{ts}"` string never equals the stored
  `action|entry_time|level` form, so `already_announced` is always False and the same signal is
  re-announced on every run — forever, since each new run's key is equally wrong. When a
  duplicate keeps firing despite a correct-looking state file, diff the **actual key strings**
  before touching the state.
- **Claim before sending: persist the key, THEN call Telegram.** Send-then-save means any
  exception between the two (a type error on the state, a crash, a kill) leaves a delivered
  message with no record, so the next run re-sends it. Write `sent` / `last_signal_key` /
  `sent_total` and `save_state()` first; a failed send is then a visible miss, which is
  recoverable, instead of an unbounded repeat.
- **Normalise the state on load, never assume its shape.** `load_state()` must coerce
  `sent` (dict → `list(keys)`, non-list → `[]`) and `sent_total` (non-int → `len(sent)`). A
  `"sent": {}` from an older version makes `.append()` raise *after* the message went out, which
  is the exact mechanism behind a signal that repeats every schedule tick while the log looks
  successful.
- **Never cap the number of new signals with a slice like `new[-3:]`** —
a multi-bar gap silently drops real, recent signals. If you must bound the first-ever run,
bound it by the freshness rule below, not by count.
- **The freshness bound must NOT depend on state.** The `last_signal_key` guard does nothing on
a fresh install or a wiped `signal_state.json` (`last_key` is None, `sent` is empty), so the
first `--run` walks the whole history and shoots every historical trade at Telegram — 348
messages in one tick on the live dataset. Apply the age filter unconditionally, *before* any
state-based trimming, and print `N historical trade(s) ignored`. Test it with an empty state
plus `--run --dry`; the only acceptable output is 0 sent. This is the mirror image of the
count-cap trap above: do not bound by count, do bound by freshness, always.
- Drop any signal older than a few bars (`3` H4 bars is a sensible ceiling, since the locked
  TTL is 2). Report the number skipped, not each one, or the log floods.
- On a first run with empty state, do **not** dump historical trades as signals; emit at most
  the newest and only if it is fresh.
- **Every "age" computation must subtract the broker offset first.** Bar stamps are server
  time (GMT+2 on this broker), so `now_utc - bar_ts` prints **negative** ages (`age -2.0h`)
  and a status line that looks obviously wrong but is easy to ship. Keep one module constant
  (`SERVER_UTC_OFFSET_H = 2.0`) and derive both the display time and the age from it. Confirm
  the convention from the EA status file itself: `server_time` and `local_time` on the same
  row give the offset directly (08:51 vs 13:51 WIB ⇒ GMT+2). A negative age or a timestamp
  that will not reconcile against the user's clock is a bug in the report, never in the data.
- Verify no-duplication by running twice with a repaired/broken state: run 1 and run 2 must both
  print "nothing to send", and the only acceptable count of new signals on real data is 0.
- **A timeout during a bundle rebuild leaves the file untouched, and a hash-carrying bundle
  refuses to restore when one embedded file's bytes change.** After editing an embedded file,
  update `EXPECTED` for **every** entry whose bytes you replaced — including state/config files
  — or `--verify` reports `embedded bytes do not match recorded hash` and `cmd_restore()` exits
  non-zero with `REFUSING TO RESTORE`. That refusal is the guard working; fix the recorded hash
  rather than bypassing the check.

A recurring trap in testing this: asserting against a state you hand-built with an off-by-one
key gives a false failure. Print the expected keys next to the actual before concluding the
bot is broken — three times in one session the bug was in the test, not the runner.

## Disabling and re-enabling the task when the user says "stop it"

When the user says the robot is spamming and to stop it, disabling the task is the *first* move,
not the last — but it has a consequence that must be stated in the same breath: **`/status` goes
silent too**, because the same task is what drains Telegram. Expect "kenapa /status tidak
menjawab" next, and say up front that the answer is "re-enable it", not a newly broken bot.

```bash
schtasks /Change /TN "\XAUUSD_Locked_H4_Signal" /Disable   # stop now
schtasks /Change /TN "\XAUUSD_Locked_H4_Signal" /Enable    # bring back
```

- **Find the real task name before disabling.** Guessing `XAUUSD_SIGNAL` / `XAUUSD_Telegram_Status`
  returns "cannot find the file" and wastes a round trip; `schtasks /Query /FO LIST /V` and read
  the name off the listing.
- **`Last Result: 1` with `FAILED rc=` rows in `errors.log` is history until you date it.** Those
  rows survive every fix; the only question is whether any timestamp is *newer* than the run that
  carried the patch. Read the newest `logs/run_*.log`, confirm `nothing to send`, and say the old
  failures are pre-fix — otherwise a clean run gets reported as still broken, or worse, a real
  regression gets waved through as a leftover.
- **Re-enable only after the fix is inside the bundle, not just in `trading/`.** Booting a task onto
  a working copy that a later `--restore` would overwrite is how the same bug comes back a week
  later. Order: patch → `--verify` → hash-sync every copy → re-enable → `schtasks /Run` once and
  read the log it writes.

## "Does the EA keep running if I close MT4 / shut the laptop?" — no, and say what survives

A recurring question, and the wrong answer ("it runs in the background") gets money placed on
a robot that is not running. Answer it as a chain, then as a consequence table.

**The chain:** an EA is not a separate program — it is a DLL-shaped script hosted *inside* the
terminal's process. Laptop off → nothing. MT4 closed → the EA dies with it. AutoTrading button
red → the EA is alive but every `OrderSend` is refused, silently. Screen locked with a corporate
NAC → MT4 stays up, prices stop arriving, orders cannot go out.

**Only the Telegram sender survives without MT4**, because it is plain Python fired by Task
Scheduler and reads a file. It sends messages; it cannot place orders. Do not let that be heard
as "so the robot is fine".

| State when the machine went down | What happens |
|---|---|
| Position already filled | **Safe.** SL and TP sit at the broker's server; the broker closes it, not the EA. Keep saying this — it is the reassurance the user actually needs |
| Pending order not yet filled | **The dangerous one.** It stays live at the broker and the EA is not there to delete it at TTL expiry, so it can fill hours later at a price the method would have refused. Call this out explicitly — it looks harmless because nothing is open |
| Flat, waiting for a signal | Nothing happens, and the signal is missed silently |

**Verdict shape:** on a machine whose lock kills the network, local auto-execution will be
holey, and the user will not know which signals were missed except by reading logs. The only
true 24/7 answer is another always-on Windows host (block B above). Offer the staged path —
Telegram-only → EA on DEMO → small lot live — and do not build the trading EA before the user
has chosen, because a "yes, build it" is not the same as "run it on my real account".

**When the answer is "signals only", stop proposing infrastructure.** Rotate the effort onto
making the signal message and `/status` trustworthy, and say plainly that no EA is being built.

## EA design (MQL4)

- Python writes `signal.json`; the EA reads it, executes, and reports the result back.
- The EA must be idempotent — a signal file left on disk must not be executed twice. Stamp
  each signal with an id the EA records after acting.
- The EA must not compute entry/TP/SL. Same rule as the n8n bridge: one source of truth.
- Requires `Tools → Options → Expert Advisors → Allow automated trading` and the AutoTrading
  button on. Both are off by default and are the most common reason an EA silently does nothing.
- MQL4 code cannot be fully verified without the user's terminal. Build it, then have the user
  run it on demo and report; do not claim it works untested.

## Diagnosing "My laptop loses network when locked"

Stop and distinguish two causes before proposing anything. They have opposite remedies, and
recommending a VPS for a power-settings problem wastes the user's money.

| Cause | Test | Remedy |
|---|---|---|
| **Windows sleep** (power plan) | Run `ping -t 8.8.8.8` in a console, press Win+L, stay locked, log back in and inspect. Ping survives briefly and dies around the sleep timeout → sleep | Set the machine never to sleep while plugged in. Lock screen alone does not stop programs or the network |
| **Corporate NAC** cuts the network on session lock | Same test: ping stops the moment the screen locks, resumes seconds after login | Nothing local will fix it. VPS is the only answer |

Check the power plan first — it is free and fast:

```bash
powercfg /getactivescheme
powercfg /query SCHEME_CURRENT SUB_SLEEP | grep -iE "Alias|Current AC|Current DC"
```

`STANDBYIDLE` in seconds on AC is the sleep timeout; a non-zero value is a prime suspect.
`RTCWAKE` = 0x2 means wake timers are enabled, so scheduled tasks can still fire.

Do not assume the corporate-network case without the test. Do not suggest input-simulation
scripts that defeat the office policy — mention the risk once and let the user decide.

## Non-technical risk to raise once, plainly

Running a trading robot on a **company-owned** laptop is a policy matter, not a technical one:
trading files on corporate assets can surface in an IT audit. State it once, without
lecturing, and let the user decide. Ask whose laptop it is before recommending any host.

## Credentials posture

Never echo a bot token or chat id, even in a config dump. Store in `config.json` or env vars;
report "configured" / "not configured" instead of the value.
