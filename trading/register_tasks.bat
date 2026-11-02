@echo off
REM ==========================================================================
REM  Daftarkan ulang kedua task penjadwal XAUUSD H4.
REM  Jalankan ini setelah install Hermes baru / setelah folder trading dipulihkan.
REM  Klik dua kali, atau jalankan dari Command Prompt.
REM ==========================================================================

set DIR=C:\Users\Sharing Vision\AppData\Local\hermes\trading
cd /d "%DIR%"

echo ============================================================
echo   MEMASANG JADWAL ROBOT XAUUSD H4
echo ============================================================
echo.

REM --- Hapus kalau sudah ada, supaya tidak dobel ---
schtasks /Delete /TN "XAUUSD_Locked_H4_Signal" /F >nul 2>&1
schtasks /Delete /TN "XAUUSD_Telegram_Status" /F >nul 2>&1

REM --- Task 1: kirim sinyal tiap lilin H4 tutup (5 menit setelahnya) ---
schtasks /Create /TN "XAUUSD_Locked_H4_Signal" ^
 /TR "\"%DIR%\run_signal.bat\"" ^
 /SC DAILY /ST 07:05 /RI 240 /DU 24:00 /F >nul
if errorlevel 1 (
    echo   GAGAL membuat XAUUSD_Locked_H4_Signal
) else (
    echo   OK  XAUUSD_Locked_H4_Signal   ^(07:05 11:05 15:05 19:05 23:05 03:05^)
)

REM --- Task 2: balas /status tiap 5 menit ---
schtasks /Create /TN "XAUUSD_Telegram_Status" ^
 /TR "\"%DIR%\poll_only.bat\"" ^
 /SC MINUTE /MO 5 /F >nul
if errorlevel 1 (
    echo   GAGAL membuat XAUUSD_Telegram_Status
) else (
    echo   OK  XAUUSD_Telegram_Status    ^(tiap 5 menit^)
)

echo.
echo ------------------------------------------------------------
echo   PENTING: matikan syarat "hanya saat listrik" untuk kedua task,
echo   kalau tidak laptop yang pakai baterai akan diam saja.
echo ------------------------------------------------------------
for %%T in ("XAUUSD_Locked_H4_Signal" "XAUUSD_Telegram_Status") do (
    powershell -NoProfile -Command ^
      "$s=Get-ScheduledTask -TaskName %%T -ErrorAction SilentlyContinue; if($s){$s.Settings.DisallowStartIfOnBatteries=$false; $s.Settings.StopIfGoingOnBatteries=$false; Set-ScheduledTask -TaskName %%T -Settings $s.Settings | Out-Null; Write-Host '  OK  baterai diizinkan untuk' %%T }" 2>nul
)

echo.
echo ------------------------------------------------------------
echo   JADWAL SEKARANG
echo ------------------------------------------------------------
for %%T in ("XAUUSD_Locked_H4_Signal" "XAUUSD_Telegram_Status") do (
    echo.
    schtasks /Query /TN %%T /FO LIST 2>nul | findstr /i "TaskName Status Next"
)

echo.
echo Selesai. Cek kesehatan robot dengan CEK_STATUS.bat
echo.
pause
