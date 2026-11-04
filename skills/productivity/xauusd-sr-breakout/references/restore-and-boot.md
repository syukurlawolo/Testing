« RESTORE / BOOT CONTRACT — XAUUSD H4 SIGNAL ROBOT »

PURPOSE
-------
This file exists so that a FRESH Hermes install reproduces the EXACT same
robot: same trading rules, same file hashes, same schedule. Nothing about the
method may change between installs. If a number here disagrees with live
output, the LIVE file is wrong — restore from the bundle.

THE ONE COMMAND
---------------
    python assets/xauusd_bundle.py --restore

That is the whole recovery procedure. It writes every file to
C:\Users\Sharing Vision\AppData\Local\hermes\trading\ with frozen bytes.

The bundle is also kept (byte-identical) at:
  - ...\hermes\trading\xauusd_bundle.py
  - C:\Users\Sharing Vision\Downloads\hermes_locked_methods\xauusd_bundle.py
  - C:\Users\Sharing Vision\Documents\OTHER\agen\xauusd_bundle.py
  - <this skill>\assets\xauusd_bundle.py            <-- survives reinstall

Any single copy can rebuild everything. They must all be the SAME bundle —
check with `sha256sum` on each and expect one hash to appear across all copies
(currently `3b9dfc5b…`, v1.4.0 — numbers move with every approved change; the
real check is that all copies agree).

If the copies disagree, the skill asset is the one to trust after a reinstall
and the `trading/` copy is the one the live robot runs. Rebuild once, copy it
over all four locations, and re-check. A stale copy has already shipped here
once (v1.1.0 in the skill, v1.3.0 live) and would have restored the pre-fix
signal engine.

FROZEN FILE HASHES (sha256 of the file on disk)
-----------------------------------------------
    xauusd_method_LOCKED.py      bfb360af0f850474291f78a5b3c3cca5414a8417065f142985489bec3b710275
    xauusd_method_LOCKED_H4.py   acc7d5beddae99db4044ca26305cb57c815ca62f02b65167fb4bded4450d2271
    signal_live_h4.py            a1c5557c97ad9f6c6a0e827d743737bffd9e5bb92519ce61075f595d30a2b7d7

Recompute these with `sha256sum` after any approved change instead of trusting
the prefixes recorded here; a stale hash in this file is worse than no hash.

DO NOT confuse these with the INTERNAL LOCK HASH reported by --verify:
    H4 lock : 0c76e240d109d60831e32483447f673a78406a0dc26ff5324df2a6bda62593b4
    H1 lock : dda75a33ab3beb2a71819b41c42d1ab6e45ce2c0a659ec6ce3f4dabe5f5e96ea
The lock hash covers the RULES (levels, params). The file hash covers the
BYTES. Both must be right. Confusing them causes false alarms.

EXPECTED --verify OUTPUT (must match exactly)
---------------------------------------------
    H4: lock OK (0c76e240...), 346 trades, WR 58.7, PF 2.38, net 3510.48,
        DD -108.0, expectancy 10.15, "RESULT : PASS"
    H1: lock OK (dda75a33...), 165 trades, "RESULT : PASS"

BOOT ORDER AFTER A FRESH INSTALL
--------------------------------
  1. python assets/xauusd_bundle.py --restore
  2. python trading/xauusd_method_LOCKED_H4.py --verify   -> must say PASS
     python trading/xauusd_method_LOCKED.py --verify      -> must say PASS
  3. Confirm tg.json still has the bot token and chat_id 5632172284
     (never copy credentials into the skill or into chat).
  4. register_tasks.bat        (must be run as a normal user, NOT elevated)
  5. CEK_STATUS.bat            (health check)

STEP 4 IS MANDATORY AND EASY TO MISS
------------------------------------
Scheduled tasks live in Windows, not in the Hermes folder. A reinstall can
leave them dangling with stale paths, or they may be gone entirely. Always
re-run register_tasks.bat and confirm BOTH tasks report Next Run Time.

THE TRAP THAT COST HOURS: "Last Result: 0" AND NOTHING HAPPENS
--------------------------------------------------------------
Windows marks a task successful even when it never runs. Two causes, both hit:
  a) DisallowStartIfOnBatteries was true and the laptop was on battery.
     Fix: register_tasks.bat rewrites Settings via PowerShell. Verify with:
       powershell -c "$s=Get-ScheduledTask -TaskName 'XAUUSD_Locked_H4_Signal'; $s.Settings.DisallowStartIfOnBatteries"
     must print False.
  b) `python` is not on the Task Scheduler PATH. run_signal.bat must use the
     FULL absolute path to the Hermes venv python.exe. A reinstall changes that
     path — check it and update run_signal.bat if the install id changed.

AFTER A HERMES REINSTALL, THE PYTHON PATH WILL PROBABLY CHANGE
--------------------------------------------------------------
Old: ...\installs\fc4f1887bf2abbca\environments\2e19130fd4aa4722848f8f2366139b70\venv\Scripts\python.exe
Find the live one with:
    ls ~/AppData/Local/hermes/installs/*/environments/*/venv/Scripts/python.exe
Then update the PYTHON= line in run_signal.bat and poll_only.bat. This is the
single most likely reason the robot goes silent after a reinstall.

STATE FILE RULE (do not break this)
-----------------------------------
signal_state.json is the bot's memory of what it already sent. The bundle
contains a SNAPSHOT, and restore NEVER overwrites a live state file — it only
writes one when absent. Overwriting would make the bot re-send old signals.
Verified: an empty state does not flood Telegram, because MAX_SIGNAL_AGE_H4_BARS
(3 bars / 12h) discards expired signals. Still, keep the real state intact.

WHAT IS NOT IN THE BUNDLE, BY DESIGN
------------------------------------
  - tg.json (Telegram token + chat id)  -> credentials, never bundled
  - signal_state.json live content       -> preserved, not overwritten
  - XAUUSD240.hst                        -> MT4 writes it
  - the Windows scheduled tasks          -> register_tasks.bat recreates them

HOW THIS WAS PROVEN (repeat these tests after any change)
---------------------------------------------------------
  1. rm -rf trading            (simulated total loss)
  2. python xauusd_bundle.py --restore
  3. sha256 of both LOCKED files match the values above
  4. both --verify runs print PASS with 346 / 165 trades
  5. python signal_live_h4.py --status  -> reads .hst, telegram configured
  6. python signal_live_h4.py --run --dry -> "0 new signal(s)", no flood
  7. both scheduled tasks show a Next Run Time
All seven passed after a real deletion of the folder.
