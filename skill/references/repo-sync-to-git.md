« REPO SYNC — laptop to git as the anti-amnesia contract »

USE WHEN the user says "keep everything", "backup semua skill", "kalau kamu
lupa, saya panggil git-nya", or when a repo under Documents/OTHER is the
recovery path for the whole Hermes state.

The contract is one sentence the user can paste into a blank Hermes:

    Pulihkan semuanya dari repo <path>. Baca PULIHKAN.md, ikuti urutannya,
    jangan menebak apa pun.

That sentence only works if the repo is self-describing. Build accordingly.

WHAT THE REPO MUST HOLD
-----------------------
trading/        byte-identical copy of hermes\trading  (.py .bat .xml .md JSON state)
skill/          SKILL.md + references/ + assets/ of the method skill
skills/         EVERY Hermes skill: <category>/<skill>/SKILL.md + support files
docs/ data/     reproducibility inputs (dataset CSV, template)
PULIHKAN.md     the restore order, written for a Hermes with no memory
SYNC.bat        laptop -> repo, auto-commit
PUSH.bat        repo -> GitHub (user owns the token, not you)

PULIHKAN.md must carry: what each folder is, the numbered restore order, the
reference numbers that prove success, and the standing prohibitions (never
re-tune, never send an unlabelled demo, never let a helper delete itself,
never commit a token). Numbers in the text, not "as agreed".

THE COPY TRAP THAT WIPES THE BACKUP
-----------------------------------
`xcopy <src>\skills\* <repo>\skills\ /E` run from inside the repo, preceded by
`rmdir /S /Q skills`, copies NOTHING and exits 0. It cannot copy a folder onto
a folder of the same name, so the "backup" is silently empty and the commit
deletes every skill. Two defences, use both:

  1. robocopy, which mirrors correctly and reports real codes:

        robocopy "%H%\skills" "%REPO%skills" /MIR /NFL /NDL /NJH /NJS /NP
                 /XD ".locks" "__pycache__"
                 /XF ".usage.json" ".usage.json.lock" ".bundled_manifest"
                     ".curator_ledger.jsonl" ".curator_state" "*.pyc" "*.lock"
         if errorlevel 8 ( echo GAGAL & goto :end )

     Keep every option on ONE line. A `^` continuation followed by an
     indented next line terminates the command early and silently drops the
     rest of the switches.

  2. COUNT the result and refuse to commit on a bad count:

        for /f %%c in ('dir /b /s "%REPO%skills\SKILL.md" ^| find /c /v ""') do set N=%%c

     Expect the same count as `find . -name SKILL.md` in hermes\skills.

RESIDUE: a wiped parent leaves the deleted children STAGED. A later `git add -A`
commits the deletions. After any suspicious sync run `git status --short` and
look for a wall of `D  skills/...` lines before pushing anything.

EXCLUDES MUST MATCH EXACTLY
---------------------------
.usage.json      tracked runtime counters
.usage.json.lock
.bundled_manifest
.curator_ledger.jsonl   curator history, churns constantly
.curator_state
.locks/ __pycache__ *.pyc
An exclude list that only covers `.bundled_manifest` commits a churning usage
file, and every sync then creates a diff that is not a change.

VERIFY A SYNC, DO NOT TRUST IT
------------------------------
A sync script is unfinished until it has been run twice:

  1. run it  -> it must create a commit (or report no change)
  2. run it again -> it MUST report "no change" and create no commit
     `git log --oneline -1` on both runs must show the same hash

Then compare hashes of the twelve trading files and the skill asset against the
live ones, and grep the tree for token shapes before declaring it clean.

SAY WHAT THE REPO DOES NOT PROTECT
----------------------------------
A local repo survives an amnesiac agent; it does not survive a dead disk. If
commits are still unpushed, the protection is theoretical. State the push
status honestly as the one remaining action instead of implying the backup is
done.
