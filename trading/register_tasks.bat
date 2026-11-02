@echo off
REM ==========================================================================
REM  Daftarkan ulang kedua task penjadwal XAUUSD H4.
REM
REM  PENTING: skrip ini memakai XML, BUKAN "schtasks /SC". Alasannya:
REM  /SC DAILY membuat trigger dengan <Duration>P1D</Duration>, artinya
REM  jadwal HANYA BERLAKU 1 HARI lalu berhenti sendiri TANPA pesan error.
REM  Itu penyebab robot pernah diam total. XML di bawah tidak punya
REM  <Duration>, jadi berulang tanpa batas.
REM ==========================================================================

set DIR=C:\Users\Sharing Vision\AppData\Local\hermes\trading
cd /d "%DIR%"

echo ============================================================
echo   MEMASANG JADWAL ROBOT XAUUSD H4
echo ============================================================
echo.

REM --- Hapus dulu supaya tidak dobel ---
schtasks /Delete /TN "XAUUSD_Locked_H4_Signal" /F >nul 2>&1
schtasks /Delete /TN "XAUUSD_Telegram_Status" /F >nul 2>&1

REM --- Task 1: kirim sinyal tiap lilin H4 tutup (5 menit setelahnya) ---
schtasks /Create /TN "XAUUSD_Locked_H4_Signal" /XML "%DIR%\signal_task.xml" /F >nul
if errorlevel 1 (
    echo   GAGAL membuat XAUUSD_Locked_H4_Signal
) else (
    echo   OK  XAUUSD_Locked_H4_Signal   ^(tiap 4 jam, mulai 07:05^)
)

REM --- Task 2: balas /status dan /plan tiap 5 menit ---
schtasks /Create /TN "XAUUSD_Telegram_Status" /XML "%DIR%\poll_task.xml" /F >nul
if errorlevel 1 (
    echo   GAGAL membuat XAUUSD_Telegram_Status
) else (
    echo   OK  XAUUSD_Telegram_Status    ^(tiap 5 menit^)
)

echo.
echo ------------------------------------------------------------
echo   KALAU "Next Run Time" KOSONG
echo ------------------------------------------------------------
echo   StartBoundary di XML sudah lewat tanggalnya. Buka
echo   signal_task.xml / poll_task.xml, ubah ke HARI INI dengan
echo   jam yang belum lewat, lalu jalankan skrip ini lagi.
echo ------------------------------------------------------------
for %%T in ("XAUUSD_Locked_H4_Signal" "XAUUSD_Telegram_Status") do (
    echo.
    schtasks /Query /TN %%T /FO LIST 2>nul | findstr /i "TaskName Status Next"
)

echo.
echo Selesai. Cek kesehatan robot dengan CEK_STATUS.bat
echo.
pause
