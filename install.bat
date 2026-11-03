@echo off
chcp 65001 >nul
echo ================================================
echo  TK-Mix-Remix installer
echo ================================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.9+ first:
    echo         https://www.python.org/downloads/  ^(check "Add Python to PATH"^)
    pause
    exit /b 1
)
echo [OK] Python found.

echo [..] Installing Python packages ...
python -m pip install -q -r "%~dp0scripts\requirements.txt"
if errorlevel 1 (
    echo [ERROR] pip install failed. Check your network and retry.
    pause
    exit /b 1
)
echo [OK] requests / openpyxl installed.

where ffmpeg >nul 2>nul
if errorlevel 1 (
    echo [WARN] FFmpeg not found. Installing via winget ...
    winget install -e --id Gyan.FFmpeg --accept-source-agreements --accept-package-agreements
    where ffmpeg >nul 2>nul
    if errorlevel 1 (
        echo [WARN] Please reopen this window. If still missing, install manually:
        echo        winget install Gyan.FFmpeg
    ) else (
        echo [OK] FFmpeg installed.
    )
) else (
    echo [OK] FFmpeg found.
)

echo.
echo ================================================
echo  Install finished. ^(熠剪自动化^)
echo  Next: copy this whole folder to
echo    C:\Users\^<you^>\.workbuddy\skills\tk-mix-remix
echo  then say "TK混剪" or "熠剪" in WorkBuddy.
echo ================================================
pause
