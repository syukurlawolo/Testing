@echo off
REM ===========================================================================
REM  XAUUSD locked H4 -> Telegram  :  scheduled runner
REM  Called by Windows Task Scheduler a few minutes after each H4 bar closes.
REM ===========================================================================

setlocal enabledelayedexpansion
set PYTHON=C:\Users\Sharing Vision\AppData\Local\hermes\installs\fc4f1887bf2abbca\environments\2e19130fd4aa4722848f8f2366139b70\venv\Scripts\python.exe
set BOT=C:\Users\Sharing Vision\AppData\Local\hermes\trading\signal_live_h4.py
set LOGDIR=C:\Users\Sharing Vision\AppData\Local\hermes\trading\logs

if not exist "%LOGDIR%" mkdir "%LOGDIR%"

REM Sortable colon-free timestamp: YYYY-MM-DD_HHMMSS
for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value') do set LDT=%%I
set STAMP=!LDT:~0,4!-!LDT:~4,2!-!LDT:~6,2!_!LDT:~8,2!!LDT:~10,2!!LDT:~12,2!

cd /d "C:\Users\Sharing Vision\AppData\Local\hermes\trading"

"%PYTHON%" "%BOT%" --run > "%LOGDIR%\run_!STAMP!.log" 2>&1
set RC=!errorlevel!

REM Also answer any /status command that arrived since the last check.
"%PYTHON%" "%BOT%" --poll >> "%LOGDIR%\run_!STAMP!.log" 2>&1

if not "!RC!"=="0" (
    echo [!STAMP!] FAILED rc=!RC! >> "%LOGDIR%\errors.log"
)

endlocal & exit /b %RC%
