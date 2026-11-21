@echo off
setlocal
title DarkShadow Next-Gen Pure Python Dependency Updater
echo ===========================================================================
echo   Updating Python packages in your existing DarkShadow .venv
echo   Includes: Playwright, browser-use, Windows UIA, LangGraph, Pydantic-AI,
echo             Mem0, Official MCP SDK, and latest google-genai
echo   (Your .env, memory.db, and contacts.json are 100%% untouched!)
echo ===========================================================================
echo.

if exist ".venv\Scripts\python.exe" (
    set "PY_EXE=.venv\Scripts\python.exe"
) else if exist "..\.venv\Scripts\python.exe" (
    set "PY_EXE=..\.venv\Scripts\python.exe"
) else (
    set "PY_EXE=python"
)

echo Using Python: %PY_EXE%
"%PY_EXE%" -m pip install --upgrade pip
"%PY_EXE%" -m pip install --upgrade -r windows_requirements.txt
echo.
echo [Optional] Installing Playwright Chromium drivers (Edge CDP works even without download)...
"%PY_EXE%" -m playwright install chromium

echo.
echo ===========================================================================
echo   DONE! All Next-Gen DarkShadow Python packages are installed.
echo   1. Run Launch_Edge_Debug.bat for Edge CDP + Playwright MCP + browser-use
echo   2. Run darkshadow_desktop.py to launch upgraded DarkShadow!
echo ===========================================================================
pause
