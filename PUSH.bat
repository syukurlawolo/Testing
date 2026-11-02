@echo off
REM ==========================================================================
REM  PUSH repo XAUUSD ke GitHub
REM  Klik dua kali file ini. Git akan meminta username + token Anda.
REM ==========================================================================

cd /d "%~dp0"

echo ============================================================
echo   PUSH KE github.com/syukurlawolo/Testing
echo ============================================================
echo.
echo Commit yang akan dikirim:
git log --oneline -1
echo.
echo File: 
git ls-files | find /c /v ""
echo.
echo ------------------------------------------------------------
echo   Saat diminta password, tempelkan PERSONAL ACCESS TOKEN
echo   (bukan password GitHub Anda).
echo ------------------------------------------------------------
echo.

git push -u origin main

if errorlevel 1 (
    echo.
    echo ============================================================
    echo   PUSH GAGAL
    echo ============================================================
    echo.
    echo Kemungkinan penyebab:
    echo   1. Username atau token salah
    echo   2. Token tidak punya izin "repo" / "Contents: Read and write"
    echo   3. Token sudah kedaluwarsa
    echo.
    echo Buat token baru di:
    echo   https://github.com/settings/tokens
    echo   Centang scope: repo
    echo.
) else (
    echo.
    echo ============================================================
    echo   BERHASIL
    echo ============================================================
    echo.
    echo Lihat di: https://github.com/syukurlawolo/Testing
    echo.
)

pause
