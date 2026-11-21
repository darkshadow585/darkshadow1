@echo off
setlocal enabledelayedexpansion
title DarkShadow Desktop AI - Gemini 3.8 Live
color 0b

:: Suppress harmless Qt DPI warnings
set "QT_LOGGING_RULES=qt.qpa.*=false;qt.webenginecontext.*=false"

echo ===================================================================
echo             DarkShadow Desktop AI (Gemini 3.8 Live WebSocket)
echo ===================================================================
echo.

cd /d "%~dp0"

:: 1. Detect Python or Virtual Environment
set "PYTHON_EXE="
if exist "%~dp0.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
) else if exist "%~dp0darkshadow-main\.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%~dp0darkshadow-main\.venv\Scripts\python.exe"
) else (
    set "PYTHON_EXE=python"
)

:: 2. Locate desktop_python directory
set "DESKTOP_DIR="
if exist "%~dp0desktop_python\darkshadow_desktop.py" (
    set "DESKTOP_DIR=%~dp0desktop_python"
) else if exist "%~dp0darkshadow-main\desktop_python\darkshadow_desktop.py" (
    set "DESKTOP_DIR=%~dp0darkshadow-main\desktop_python"
) else if exist "%~dp0darkshadow_desktop.py" (
    set "DESKTOP_DIR=%~dp0"
)

if "%DESKTOP_DIR%"=="" (
    echo [ERROR] darkshadow_desktop.py not found!
    pause
    exit /b 1
)

cd /d "%DESKTOP_DIR%"

echo [OK] Launching DarkShadow Native Voice-to-Voice Core...
echo [i] Model: gemini-3.8-live (Bidirectional Real-Time Audio)
echo [i] Voice: Puck (Lively, High-Energy, Friendly Co-Pilot)
echo [i] Tip: DarkShadow runs seamlessly behind your windows.
echo          Minimize this terminal to enjoy the 3D Starlight Orb!
echo.

"%PYTHON_EXE%" darkshadow_desktop.py
if %errorlevel% neq 0 (
    echo.
    echo [!] Application exited with code %errorlevel%.
    pause
)
