« PUBLISHING THE FROZEN SYSTEM »

Applies whenever the system leaves this machine: a git repo, an archive, a
handoff to another computer. The goal is that whoever clones it can reproduce
`--verify` PASS on both methods without asking a single question.

SHIP EVERYTHING
---------------
A partial mirror is a trap: it looks finished and fails months later on the one
missing piece. Always include:

    xauusd_method_LOCKED.py       xauusd_method_LOCKED_H4.py
    xauusd_bundle.py              signal_live_h4.py
    run_signal.bat  poll_only.bat  register_tasks.bat  CEK_STATUS.bat
    PANDUAN.md  docs/*.md         skill/SKILL.md
    data/XAUUSD240.csv            (needed for --verify to reproduce)
    data/template-backtest.csv

Without the CSV, `--verify` cannot reproduce 346 trades and the whole promise
of the freeze is untestable on a fresh machine.

NEVER SHIP
----------
    tg.json / any token or chat id      -> credentials
    *.hst                               -> MT4 writes it, large, machine-specific
    logs/, signals_log.jsonl, __pycache__ -> runtime noise (gitignore them)

GIT SETUP THAT PREVENTS DAMAGE
------------------------------
- `.gitattributes` with `*.bat text eol=crlf` and `*.py *.md text eol=lf`.
  Without it git's autocrlf warning fires on every `.bat` and there is no proof
  the CRLF survived; cmd.exe misreads a `.bat` converted to LF.
- `.gitignore` covering `tg.json`, `*token*.json`, `.env*`, logs, `*.hst`.

BEFORE COMMITTING: SCAN THE ARTEFACTS, NOT JUST THE FILE LIST
-------------------------------------------------------------
A base64 bundle hides its payload from a plain `grep`. Decode it and scan the
decoded bytes for token shapes (`bot<digits>:<secret>`, `\d{8,10}:[A-Za-z0-9_-]{35}`,
`gh[pousr]_…`, `AIza…`, an embedded chat id). A hash line matching the pattern
is a false positive — check what matched, not merely that something did.

Report the result as a verdict: "no credentials inside the bundle".

VERIFY THE REPO, NOT THE COMMIT
-------------------------------
A commit on disk proves nothing about the clone. After committing:

    git clone <repo> /tmp/clone_test
    cd /tmp/clone_test
    sha256sum trading/xauusd_method_LOCKED.py trading/xauusd_method_LOCKED_H4.py
    python trading/xauusd_method_LOCKED_H4.py --verify     # must PASS, 346
    python trading/xauusd_method_LOCKED.py --verify        # must PASS, 165
    python trading/xauusd_bundle.py --verify               # must be all "ok"
    git ls-files | grep -i tg.json                         # must be empty

The sha256 comparison is the part people skip: it is the only proof that
line-ending normalisation did not mutate a locked file.

CHANGING THE RESTORE TARGET
---------------------------
`xauusd_bundle.py` defaults `TARGET_DIR` to the standard Hermes trading folder.
To prove recovery onto a *different* machine, copy the bundle, edit `TARGET_DIR`
to an empty throwaway directory, run `--restore`, then `--verify`. Afterwards
restore the file with `git checkout -- trading/xauusd_bundle.py` — a test that
leaves a redirected `TARGET_DIR` in the committed bundle is a silent landmine.

DELIVERING WHEN ACCESS IS MISSING
---------------------------------
Do not stall and do not end with instructions only. Stage what is already
correct so the user's remaining action is a single click:

  1. commit the repo in a DURABLE path (`~/Documents/OTHER/<name>`), never under
     the pruned scratch dir
  2. `git remote add origin <url>` so `git push` needs no further setup
  3. a `PUSH.bat` that runs `git push -u origin main` and prints a cause table
     on failure
  4. a `CARA-PUSH.md`: how to mint a Personal Access Token, which scope (`repo`),
     and the error-to-cause table (`Authentication failed`, "password auth was
     removed", `Permission denied`, `Updates were rejected`)
  5. a `SYNC.bat` so later changes refresh the repo in one click — see
     `references/repo-sync-to-git.md`. Staging the repo once without a sync
     script leaves the next session redoing the copy by hand and re-breaking it.

Name the blocking fact plainly in the reply — "no token on this machine, so I
cannot push" — then hand over the staged repo. Do not open a browser to solve a
credential prompt and do not ask for a password or token in chat: the user
pushes. Report the number of unpushed commits so the gap is visible.

HONEST CAVEATS TO CARRY INTO THE REPORT
---------------------------------------
- `signal_state.json` committed to the repo is a SNAPSHOT, not the live memory.
  Say so; otherwise the user assumes their sent-signal history travelled with it.
- The `.bat` runners carry an ABSOLUTE venv python path. On another machine it
  is wrong until edited, and that is the most common reason the robot goes
  silent after a move. Put that step in the README as its own numbered step.
- MT4 cannot be shipped. No MT4, no `.hst`, no new signal — regardless of how
  perfect the restore was.
