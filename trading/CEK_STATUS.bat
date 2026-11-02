@echo off
REM ==========================================================================
REM  Cek cepat: apakah robot XAUUSD H4 sehat?
REM  Klik dua kali file ini kapan saja.
REM ==========================================================================
setlocal
set PY=C:\Users\Sharing Vision\AppData\Local\hermes\installs\fc4f1887bf2abbca\environments\2e19130fd4aa4722848f8f2366139b70\venv\Scripts\python.exe
set DIR=C:\Users\Sharing Vision\AppData\Local\hermes\trading
cd /d "%DIR%"

title Cek Robot XAUUSD H4
echo ============================================================
echo   STATUS ROBOT SINYAL XAUUSD H4
echo ============================================================
echo.

"%PY%" signal_live_h4.py --status

echo.
echo ------------------------------------------------------------
echo   INTEGRITAS METODE TERKUNCI
echo ------------------------------------------------------------
"%PY%" xauusd_method_LOCKED_H4.py --verify
echo   exit code: %errorlevel%
echo.
echo ------------------------------------------------------------
echo   JADWAL OTOMATIS
echo ------------------------------------------------------------
schtasks /Query /TN "XAUUSD_Locked_H4_Signal" /FO LIST | findstr /i "TaskName Next Status Last"
echo.
pause
