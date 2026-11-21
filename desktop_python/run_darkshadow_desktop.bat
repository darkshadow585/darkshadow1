@echo off
setlocal enabledelayedexpansion
title DarkShadow Desktop AI — Python Co-Pilot
color 0b

echo ==========================================================
echo   DarkShadow Desktop AI (PySide6 WebGL2 + Python)
echo ==========================================================
echo.

cd /d "%~dp0"

:: Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in system PATH!
    pause
    exit /b 1
)

echo [✓] Launching DarkShadow Transparent WebGL2 Desktop Overlay...
echo [i] Model: gemini-4-hydrogen (Configured in .env)
echo [i] Tip: Say "Hey Dark Shadow" or right-click the System Tray icon.
echo.

python darkshadow_desktop.py
if %errorlevel% neq 0 (
    echo.
    echo [!] Application exited with code %errorlevel%.
    pause
)
