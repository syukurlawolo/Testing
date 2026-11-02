@echo off
REM ==========================================================================
REM  SYNC repo  <-  kondisi TERBARU di laptop
REM
REM  Jalankan ini setelah ada perubahan apa pun di robot / skill.
REM  Yang disalin: hermes\trading, skill xauusd-sr-breakout, SEMUA skill,
REM  dan .bat pendukung. Yang TIDAK disalin: tg.json (token), log, cache.
REM
REM  Setelah sync, commit dibuat otomatis. Push tetap manual: PUSH.bat
REM ==========================================================================
setlocal
cd /d "%~dp0"

set "H=%LOCALAPPDATA%\hermes"
set "REPO=%~dp0"

echo ============================================================
echo   SYNC: hermes  -^>  repo git
echo ============================================================
echo.

REM --- 1. file robot + metode -------------------------------------------
echo [1/4] trading\ ...
xcopy "%H%\trading\*.py"  "%REPO%trading\" /Y /Q >nul
xcopy "%H%\trading\*.bat" "%REPO%trading\" /Y /Q >nul
xcopy "%H%\trading\*.xml" "%REPO%trading\" /Y /Q >nul
xcopy "%H%\trading\*.md"  "%REPO%trading\" /Y /Q >nul
copy /Y "%H%\trading\signal_state.json" "%REPO%trading\" >nul
if exist "%REPO%trading\__pycache__" rmdir /S /Q "%REPO%trading\__pycache__"

REM --- 2. skill metode ---------------------------------------------------
echo [2/4] skill\ ...
copy /Y "%H%\skills\productivity\xauusd-sr-breakout\SKILL.md" "%REPO%skill\SKILL.md" >nul
xcopy "%H%\skills\productivity\xauusd-sr-breakout\references\*" "%REPO%skill\references\" /E /Y /Q >nul
xcopy "%H%\skills\productivity\xauusd-sr-breakout\assets\*"     "%REPO%skill\assets\" /E /Y /Q >nul

REM --- 3. SELURUH skill -------------------------------------------------
echo [3/4] skills\ (semua skill) ...
REM  NOTE: xcopy is SKIPPED here on purpose. It cannot copy a folder into a
REM  folder of the same name, so it silently wipes the backup. Use robocopy.
REM  /MIR mirrors exactly: deletes what no longer exists in hermes.
robocopy "%H%\skills" "%REPO%skills" /MIR /NFL /NDL /NJH /NJS /NP /XD ".locks" "__pycache__" /XF ".usage.json" ".usage.json.lock" ".bundled_manifest" ".curator_ledger.jsonl" ".curator_state" "*.pyc" "*.lock" >nul
if errorlevel 8 (
    echo   ROBCOPY GAGAL - backup skill TIDAK terbarui. Batalkan push.
    goto :end
)

REM --- 4. commit --------------------------------------------------------
echo [4/4] commit ...
echo.
git add -A
git status --short
echo.
git diff --cached --quiet
if errorlevel 1 (
    git commit -q -m "Sync: kondisi terbaru hermes (trading + semua skill)"
    echo.
    echo COMMIT DIBUAT: 
    git log --oneline -1
) else (
    echo Tidak ada perubahan. Repo sudah sama dengan kondisi terkini.
)

echo.
echo ------------------------------------------------------------
echo   Selesai. Untuk mengirim ke GitHub: jalankan PUSH.bat
echo ------------------------------------------------------------
echo.
:end
pause
