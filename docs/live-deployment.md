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
t(i32)  reserved(i32)  O,H,L,C (5 x f64)  vol(i32)
```

Decode with `struct.unpack('<ii5di', rec)` after skipping 148 bytes, and verify the first
timestamp is plausible before trusting the offset. Guessing record sizes by 
trying `(len - h) % 44/48/52` fails; solving for the header as
`for h in range(120, 180): if (len(b) - h) % 44 == 0` lands on 140, which reveals the real
60-byte stride starting at 148. Sanity-check any decode by replaying it through the locked
engine: **bars sourced from `.hst` must reproduce the locked trade count exactly** (346 for
H4). A mismatched count means the binary decode is wrong, not the strategy.

MT4 server time is usually GMT+3 while the user is GMT+7, so an age computed from the raw
timestamp can go slightly negative on the newest bar. That is timezone skew, not corruption.

**The feed only advances while MT4 is running and logged in.** A closed terminal freezes
`XAUUSD240.hst`, and the robot then reports "no new signal" forever. Always print the newest
bar's timestamp and age in status output, and tell the user MT4 must stay open.

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

## Keeping the bot honest about signal freshness

The state file alone is not enough. After downtime, the newest derived trade can be hours or
days stale, and announcing it hands the user a limit order the method would have cancelled.

- Store announced signal keys plus `last_signal_key`; on each run, take everything **after**
the last announced key. **Never cap the number of new signals with a slice like `new[-3:]`** —
a multi-bar gap silently drops real, recent signals. If you must bound the first-ever run,
bound it by the freshness rule below, not by count.
- Drop any signal older than a few bars (`3` H4 bars is a sensible ceiling, since the locked
  TTL is 2). Report the number skipped, not each one, or the log floods.
- On a first run with empty state, do **not** dump historical trades as signals; emit at most
  the newest and only if it is fresh.
- Verify no-duplication by running twice: run 1 announces, run 2 must print "nothing to send".

A recurring trap in testing this: asserting against a state you hand-built with an off-by-one
key gives a false failure. Print the expected keys next to the actual before concluding the
bot is broken — three times in one session the bug was in the test, not the runner.

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
