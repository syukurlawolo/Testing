@echo off
REM Answer Telegram /status commands. Runs every 5 minutes.
setlocal enabledelayedexpansion
set PYTHON=C:\Users\Sharing Vision\AppData\Local\hermes\installs\fc4f1887bf2abbca\environments\2e19130fd4aa4722848f8f2366139b70\venv\Scripts\python.exe
set BOT=C:\Users\Sharing Vision\AppData\Local\hermes\trading\signal_live_h4.py
set LOGDIR=C:\Users\Sharing Vision\AppData\Local\hermes\trading\logs
if not exist "%LOGDIR%" mkdir "%LOGDIR%"
cd /d "C:\Users\Sharing Vision\AppData\Local\hermes\trading"
"%PYTHON%" "%BOT%" --poll >> "%LOGDIR%\poll.log" 2>&1
endlocal & exit /b 0
