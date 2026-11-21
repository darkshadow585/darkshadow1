@echo off
title DarkShadow - Microsoft Edge CDP Automation Profile
color 0b
echo ===================================================================
echo     DarkShadow - Microsoft Edge CDP (Port 9222) Automation Setup
echo ===================================================================
echo.
echo [1/2] Launching Microsoft Edge with Remote Debugging Port 9222...
start "" msedge --remote-debugging-port=9222 --remote-allow-origins=* --user-data-dir="%LOCALAPPDATA%\DarkShadowEdgeProfile" --no-first-run

timeout /t 2 >nul

echo [2/2] Checking CDP status on http://localhost:9222/json/version...
powershell -Command "try { $v = (Invoke-RestMethod -Uri http://localhost:9222/json/version -TimeoutSec 2); Write-Host '[SUCCESS] CDP Port 9222 Connected!' -ForegroundColor Green; Write-Host ('Browser: ' + $v.Browser); Write-Host 'Keep this Edge window open so DarkShadow can interact with your web tabs!'; } catch { Write-Host '[NOTE] If port did not open, close running Edge windows from Task Manager and re-run this file.' -ForegroundColor Yellow; }"
echo.
pause
