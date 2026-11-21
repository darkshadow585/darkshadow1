@echo off
setlocal
title DarkShadow - Microsoft Edge CDP Automation Profile
color 0b
echo ===================================================================
echo     DarkShadow - Microsoft Edge CDP (Port 9222) Automation Setup
echo ===================================================================
echo.

set "EDGE_EXE="
if exist "%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe" (
    set "EDGE_EXE=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
) else if exist "%ProgramFiles%\Microsoft\Edge\Application\msedge.exe" (
    set "EDGE_EXE=%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"
) else if exist "%LocalAppData%\Microsoft\Edge\Application\msedge.exe" (
    set "EDGE_EXE=%LocalAppData%\Microsoft\Edge\Application\msedge.exe"
)

set "PROFILE_DIR=%LOCALAPPDATA%\DarkShadowEdgeProfile"

echo [1/2] Launching Microsoft Edge with Remote Debugging on 127.0.0.1:9222...
if defined EDGE_EXE (
    start "" "%EDGE_EXE%" --remote-debugging-port=9222 --remote-debugging-address=127.0.0.1 --remote-allow-origins=* --user-data-dir="%PROFILE_DIR%" --no-first-run --no-default-browser-check
) else (
    start "" msedge --remote-debugging-port=9222 --remote-debugging-address=127.0.0.1 --remote-allow-origins=* --user-data-dir="%PROFILE_DIR%" --no-first-run --no-default-browser-check
)

echo [2/2] Waiting for CDP endpoint on http://127.0.0.1:9222/json/version (up to 8s)...
powershell -NoProfile -Command "$ok=$false; for($i=0; $i -lt 16; $i++) { foreach($u in @('http://127.0.0.1:9222/json/version','http://[::1]:9222/json/version')) { try { $v = Invoke-RestMethod -Uri $u -TimeoutSec 1; Write-Host ('[SUCCESS] CDP Connected at ' + $u) -ForegroundColor Green; Write-Host ('Browser: ' + $v.Browser); Write-Host ('WebSocket: ' + $v.webSocketDebuggerUrl); Write-Host 'Keep this Edge window open so DarkShadow can interact with your web tabs!'; $ok=$true; break } catch {} } if($ok){break}; Start-Sleep -Milliseconds 500 }; if(-not $ok){ Write-Host '[FAILED] CDP Port 9222 did not respond.' -ForegroundColor Red; Write-Host 'Fix: Close any Edge window using DarkShadowEdgeProfile (or disable Edge Startup Boost) and re-run this script.' -ForegroundColor Yellow }"
echo.
pause

