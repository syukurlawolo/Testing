---
name: xauusd-sr-breakout
description: Use for XAUUSD S/R breakout backtests, live signals, git backup and restore.
version: 1.6.0
author: Hermes Agent
license: MIT
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
bundle in `trading/` was once rebuilt to v1.3.0 while the skill asset was still
v1.1.0, so a reinstall would have restored the buggy pre-fix signal engine.
Discipline: after every approved change, three copies must be hash-identical —
`trading/xauusd_bundle.py`, `<skill>/assets/xauusd_bundle.py`, and the copy in
the git repo — and each one must separately pass `--verify` on its own.

A drift check the user can see, not just a claim: print both sha256 side by side
and the word IDENTIK/BERBEDA, then run `--verify` from the skill copy. When they
differ, the skill copy is the one that matters — it is the copy a reinstall
leaves behind.

### Never let a scheduled helper delete itself

One-off demo senders must not `del "%~f0"` or `os.remove(__file__)`. Any script
that proves a path works (scheduled send, restore, health check) is the evidence
a future session needs; a self-deleting helper leaves the user with nothing to
inspect and the agent unable to reproduce it. Leave the script in place, guard
it with its own time window so it cannot re-fire, and clean up only when the
user asks. The same rule applies to helpers written for a single demonstration
only — write them as keepable files from the start, because "temporary" scripts
become permanent the moment the user says *keep everything*.

### The git repo IS the anti-amnesia contract — keep it synced

When the user's standing requirement is "kalau Hermes amnesia, saya tinggal
panggil git-nya", the repo is not a backup artefact, it is the boot contract.
It must hold, all at once: the full `trading/` tree, the method skill, **every
Hermes skill** under `skills/`, the reference data, and a `PULIHKAN.md` written
so that "paste one sentence to Hermes" restores the system without any
conversation history. Ship a `SYNC.bat` (laptop → repo, auto-commit) next to the
user's `PUSH.bat`, and treat *sync clean = no new commit on a second run* as the
proof that the repo equals the live machine. Recipe, including the copy trap
that wipes the backup, is in `references/repo-sync-to-git.md`.

**Any change to `signal_live_h4.py`, either `*_LOCKED*.py`, a runner `.bat`, or
the skill itself is not finished until `SYNC.bat` runs clean.** A hash-equal
`trading/` with a stale repo restores the wrong engine on the next reinstall —
this has already happened once with the v1.1.0/v1.3.0 bundle split.

### Scheduled tasks stop silently — `Next Run Time` is not evidence of life

The trigger can keep advancing `Next Run Time` (19:15 → 19:25 → 19:30) while
`Last Run Time` and every file in `trading/logs/` stay frozen for hours, with
`Status: Ready` and `Last Result: 0` throughout. Sleeping through a due time is
not proof either — a `sleep` in your own shell keeps running with the screen
locked. The only trustworthy check is `Last Run Time` plus the newest log
timestamp, and the fix is `schtasks /Run` only as a stopgap.

When the user wants instant `/status` answers or signals that survive a locked
screen, propose replacing the 5-minute schedule with a long-lived background
process that polls Telegram every few seconds and autostarts with Windows. Say
plainly that its cost is one live Python process the machine must keep running.

The two remedies are NOT interchangeable, so name the failing one correctly:
repairing the trigger only helps if the trigger is at fault; a trigger that is
merely being pre-empted by sleep/lock recovers on its own as soon as the machine
is awake, so "fix the schedule" would change nothing. Diagnose first, then pick.

#### Draining the Telegram queue is a DIAGNOSTIC, not the fix

Running `signal_live_h4.py --poll` by hand proves the code path and clears the
queue, so the user sees a reply and the incident looks closed while the trigger
stays broken. Always state the distinction in the same message — a manual poll
success is evidence about the code, never evidence that the schedule works —
otherwise the user reads the reply as "fixed" and hits the same silence again.

- **The Telegram queue is the evidence, so read it before touching anything.**
  `getUpdates` with **no** offset returns pending updates *and leaves them in the
  queue*. Run that first: a `/status` still sitting there with a timestamp older
  than the last scheduled slot proves nothing consumed it — that separates a dead
  schedule from a send failure, and it dates the request precisely. Only then may
  you drain with `--poll`, and you must label that reply as a diagnostic, not a fix. `<status>` in task
listings is not a status: interpret the `Status` line from
`schtasks /Query /V /FO LIST` as informative only and corroborate with
`Last Run Time` + the newest log filename.

### A second channel is for WAKING him; Telegram is for COPYING

When the user asks for a push channel besides Telegram, add it as a redundant
sink, never as a replacement: `send_all()` fans out to Telegram **and** ntfy and
returns `{"telegram": bool, "ntfy": bool}`. One channel failing must never
suppress the other — prove it by temporarily renaming the config file and
re-running: Telegram must still report `True`.

- **Priority is a contract, not a per-message choice.** Reserve `priority 5`
  (urgent, overrides Do Not Disturb) for NEW SIGNALS ONLY; `/status`-class
  replies use 3. If a routine reply is also urgent, the long vibration stops
  meaning "there is a trade to place" and the user learns to ignore it.
- **ntfy is plain text.** Telegram HTML tags must be stripped (`re.sub(r"<[^>]+>", "")`)
  before sending, which means the module needs `import re` at top level —
  omitting it is a NameError on the first real send.
- **A missing config file disables the channel silently** (`load_ntfy()` returns
  `{}`, `ntfy_send()` returns False) so an unconfigured push can never block the
  primary channel. Never raise on it.
- **The topic name IS the password.** Anyone who knows it can read the signals
  and inject fakes. Keep it in `trading/ntfy.json` (never in the bundle, never in
  the git repo — grep the repo for it before committing), and tell the user
  plainly that it is a secret, not just a setting.
- **Say what each channel is good for instead of pretending they are equal.**
  ntfy wakes the phone; Telegram is where a number can be tapped and copied. If
  the user complains "the numbers in ntfy can't be copied", do not fake it —
  explain that Android notification text is not per-word selectable, and offer
  either a tap-through to the Telegram message or keeping ntfy as the alarm only.

### `/posisi` — what is running, what must be deleted, what just fired

After a fill the user's real question is *"is this still my trade, or do I take
it off?"*. Answer it as three labelled blocks, each ending in an imperative
(`→ Aksi: biarkan` / `hapus ordernya`), never as one flat list:

1. **Yang sedang berjalan** — 🟢 filled position ("biarkan, jangan diubah") and
   🟡 unfilled pending ("biarkan menunggu", plus hours left).
2. **Terjadi apa di lilin terakhir** — only the exits that happened on the newest
   bar: ❌ HANGUS (TTL expired), ✅ TP, 🛑 SL. These are the delete-this ones.
3. **Sinyal baru di lilin ini** — say "tidak ada" explicitly and add that waiting
   is not a fault, otherwise silence looks like a broken robot.

Implementation in `signal_live_h4.py`: `track_orders()` walks the bars once with
the locked params and keeps finished AND live orders (each with `state`, `bar`,
`sig_ts`, `exit_i`); `build_positions_report()` formats it. Register it in the
`cmd_poll` dispatcher and in the `/help` and unknown-command fallback lists.

- **Never do expiry arithmetic as `bars_left × 4`.** H4 bars skip the weekend, so
  a bar count overstates the remaining window by days. Compute
  `sig_ts + Timedelta(hours=TTL_BARS * 4)` against the newest bar's timestamp.
- **Stale data invalidates every action line.** When the newest bar is older than
  ~6h, print the DATA MATI warning above all three blocks and say the actions
  below cannot be trusted — never let "biarkan posisi" be read as advice on a
  market that has not been seen for hours.
- **Test the report against truncated history, not only the live state.** The
  current market is usually flat, so the "position running" and "pending"
  branches never render. Re-run `build_positions_report()` with `read_hst`
  monkey-patched to return `df.iloc[:cut]` for a bar where an order was live;
  that is the only way to see the two branches actually produce text.

The method is flat by design most of the time: silence plus "tidak ada order yang
perlu dijaga" is the correct output, and telling the user so in one sentence
prevents him from forcing trades.

### `cmd_poll` must answer EVERY command in the batch, and never stay silent

Draining advances `tg_offset` past *every* pending update, so any command the loop
`continue`s over is destroyed, not deferred. Two ways this bites:

- **Per-update dedupe destroys siblings.** A `handled` / `uid == handled` marker that
  stores only the last answered `update_id` skips the earlier messages of the same
  batch, and the offset then marks them consumed. Answer every recognized command in
  the loop and rely on `tg_offset` alone for dedupe — that is what it is for.
- **An unknown command must still get a reply.** `continue` on anything not in the
  allow-list makes a typo (`/statuss`) indistinguishable from a dead robot. Reply with
  the command list instead: as long as *something* comes back, the user knows the
  schedule works.

When the user asks "how long should I wait for /status?", give numbers, not a
paragraph: 0 to one poll interval (5 min by default) is normal, ~2.5 min is typical,
and **more than 10 min means blocked, not slow**. Add that `/status` replies are sent
silently by design — the user must open the chat, waiting for a notification guarantees
a false "it didn't work".

A dropped reply the user waited for is a defect in the robot, not a cosmetic quirk: say
so plainly at the top of the reply, before explaining the schedule, otherwise the silent
drop gets blamed on Windows.

When answering, first read the Telegram queue (`getUpdates` with no offset) and
compare the stored `tg_offset`; a message still sitting there proves nothing
consumed it, which separates a dead schedule from a send failure.

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

When you change the bundle's own behaviour, the new bundle must be rebuilt from the
regenerated skeleton, not hand-edited: the embedded base64 blocks make any
manual edit a corruption risk. Regenerate, then re-run all four subcommands.

**The skeleton rarely survives** — builders stage it in the pruned scratch dir, so
almost always the rebuild script is gone while the bundle is not. Do not stop there
and do not rewrite the bundle by hand: patch the embedded entry programmatically.
The bundle is plain Python holding `{name: sha256}` in an `EXPECTED` dict plus a
`{name: ("<base64 chunk>", ...)}` payload block per file, so the edit is exactly
four steps — (a) hash the changed file, (b) replace its hash line in `EXPECTED`,
(c) regex out its payload block (`"<name>": \(\n(?:        "[^"]*"\n)+\)`) and
substitute a freshly wrapped base64 block at 76 chars per line, (d) bump
`BUNDLE_VERSION`. Then prove it: `--verify` must report every file matching, and
the same new hash must appear in all three copies (`trading/`, skill `assets/`,
git repo). `--verify` OK is the proof the payload decodes and matches — a hand
typed bundle that fails it is the only real corruption risk.

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
- **A platform that only offers a mobile app has no automation path worth promising.**
  When the user describes a click-by-click flow in a phone app (open app → enable
  location → tap "post signal" → pick channel → pick symbol → OK) and asks "any idea
  how to automate this?", answer in three tiers and do not merge them: (1) UI
  automation of the phone (Accessibility/Appium) — say plainly it is fragile: every
  app update moves the buttons, the phone must stay awake and unlocked, and platform
  rules may treat it as a violation with the user's account at stake; (2) half-
  automatic — the robot formats the signal so it can be pasted into the app, cutting
  the work to seconds with no fragility; (3) execute on the user's own account via
  MT4 instead, which needs no app at all. Then ask which one, and **which revenue the
  user is actually after** (subscribers to the channel vs profit from their own
  account) — the right tier depends entirely on that answer, and guessing it wastes
  the session. Check whether the platform has a web version before proposing phone
  automation at all: a browser flow is repeatable where screen-tapping is not.
#### `/status` is read in five seconds — lead with the ACTION, not the data

This user tunes `/status` by telling you to "make the words easier". The shape that works:

1. **One verdict line with a traffic light**, then nothing else until the action.
   🔴 `DATA MATI — jangan trading` (data older than ~6h) · 🟡 `ADA ORDER BELUM TERISI`
   · 🟢 `POSISI SEDANG BERJALAN` · ⚪ `TIDAK ADA YANG PERLU DIPASANG`.
2. **The order to place, in imperative.** `Pasang BUY STOP/LIMIT di:` then the entry
   alone on its line as `<code>`, then `TP … SL …` on one line, then `Sisa waktu: N jam`.
   These are the only copyable values — same `<code>`-only rule as the signal message.
3. **What is being waited for, in conditional language.** `BUY kalau tutup di atas X` /
   `SELL kalau tutup di bawah Y` — the level, not the technical term "resistance".
4. **`➖➖➖ rincian ➖➖➖`, then everything else.** Last candle time, nearest levels with
   distance, the last finished trade's result, and the method id/version/health line go
   BELOW the divider so the user can stop reading at the top.

Banned in the top half: the words limit/breakout/close/resistance as labels, indentation-led
key/value blocks, and the same fact stated twice (price used to appear in the header *and* in
the signal block). Strip `real_now`/age arithmetic to a single parenthetical
`(data 4.3 jam lalu)` — say `jam`, not `h`.

- **Signal numbers must be individually copyable.** This user posts signals into a
phone app with three separate fields (entry / SL / TP), so he wants to tap *one
number* and paste it into *one field* — not copy the whole message. Wrap only the
bare number in `<code>` and leave the labels and the deltas as normal text:
  `f"<b>Entry</b>  <code>{t['entry']:.2f}</code>   (limit)"`. Telegram copies a
  `<code>` span on tap in the mobile client, which is why this works without
  inline buttons. Offer this layout before writing it and say the cost — the
  numbers render in a slightly boxed monospace style. Do not add copy buttons,
  do not wrap the labels, and do not make a wall of tappable fields: the user
  asked for the numbers, so only the numbers.

Patch it in `signal_live_h4.py` (`fmt_signal`), then prove the render by calling
`fmt_signal()` on a hand-built signal dict and printing it — never screenshot-guess
the HTML. Each new-format feature gets one Telegram message titled as a
**CONTOH TAMPILAN — BUKAN SINYAL** with invented numbers in it, so the user can
test the tap without wondering whether a real signal just arrived.
- **The final line of a signal says where the order goes, not just its price.**
  When the robot's output is pasted by a human, end the message with the single
  action to perform (`→ Pasang BUY LIMIT di 3905.42`) and the expiry rule in
  plain words (`Batalkan kalau belum terisi dalam 8 jam`). The trader reads the
  last line, not the table.

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
  clone-based verification that must pass before calling a push done. For a repo
  meant to survive an amnesiac Hermes, also read `references/repo-sync-to-git.md`.
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
  back $3 to the level instead of chasing) is the substance of the correction. That correction
  alone is not enough; he will then ask for the stop version to be *tested*. Answer with the
  files and the measured breakdown, never with "stop is worse" or "stop is better" from theory
  — the empirical answer is in `references/order-type-experiment.md`.
- After the stop test comes back a tie, he will ask the practical follow-ups — *can I place it
  beforehand, far before the breakout?* Answer the two-level confusion directly: the **level** is
  static, the **entry** is only valid once a bar CLOSES beyond it, so placing a buy-stop *and* a
  sell-stop in advance is a different (untested) method, not his. The honest offer is either
  "place it when the notification arrives, ~30s" or "build the MT4 EA that places it for you".
- Close with a one-paragraph summary in plain speech — that is the version he will re-read.

**Rule hypotheticals ("level A broken, then level B in the same candle — then what?").** His
questions often describe two things the engine cannot do at once. Check the engine first, then
run a ~25-line synthetic-bar simulation and show the printed trace, then name the false premise.
The engine holds ONE slot, enforces a one-bar cooldown after an exit, confirms by CLOSE not
touch, and resolves a bar that hits both SL and TP as SL. Worked example, the probe that shows
the scenario is near-impossible on real data, and the answering shape are in
`references/rule-questions-and-simulations.md`.

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
| `signal_state.json` | Open position / pending order / closed trades |
| `xauusd_STOP_variant_H4.py`, `xauusd_STOP_variant_H1.py` | Experiment copies of the two locked methods (stop instead of limit). Never in the bundle, never in the repo. See `references/order-type-experiment.md`. |
| `signal_live_h4.py` | H4 Telegram bot: `--run` / `--poll` / `--status` / `--dry` / `--test`; `send_all()` fans out to Telegram + ntfy |
| `ntfy.json` | Push topic + server for the second channel. **Secret — never in the bundle or the repo.** |
| `xauusd_bundle.py` | Self-restoring bundle: 11 files base64-embedded, `--verify`/`--restore`/`--list`/`--diff` |
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
8. **Do not bother sweeping the order type.** Limit vs stop is *identical* on this method
   (346/346 trades, byte-identical CSV) because the breakout bar almost always closes past
   `level ± $3` already. Effort belongs on buffer, cap, and RR instead. Evidence and the
   reusable method for running any such variant test: `references/order-type-experiment.md`.

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

- **Never claim an automation works because you wrote it.** A scheduled task, a
  sync script, or a `.bat` is proven only by running it and reading the result;
  run it a second time to prove it is idempotent. Stating "done" before the
  first execution has already happened is a defect this user catches, and he
  reads a quiet change of state as a lie, not an oversight. When you find such a
  mistake in yourself, name it plainly at the top of the reply before the
  results table.
- **A scheduled task with no `Last Run` for hours is a host problem until proven
  otherwise**, but a scheduled task that was never tested is an agent problem.
  Check both before blaming the machine.

## Task Scheduler: repetition needs `<Duration>`

A `CalendarTrigger` with `<Repetition><Interval>PT5M</Interval></Repetition>` and **no `<Duration>`** never repeats — Windows reads the duration as zero. The task still reports `Status: Ready` and a `Next Run Time` that keeps advancing, so it looks healthy while never firing. `schtasks /Query /V` even prints `Repeat: Every: 0 Hour(s), 5 Minute(s)`, which is misleading.

- Always include `<Duration>P1D</Duration>` inside `<Repetition>`.
- Diagnose with `Last Run Time`, never `Next Run Time`: if `Last Run` is hours old while the machine was on and logged in, the repetition is dead.
- Then prove it: count files in `trading/logs/run_*.log`, wait past two trigger boundaries, and confirm the count rises twice with no manual run.

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
