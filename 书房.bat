@echo off
setlocal
cd /d "%~dp0"

set "BIYU_TRACK=creative"
set "CLAUDE_CMD=%APPDATA%\npm\claude.cmd"

if exist "%CLAUDE_CMD%" goto launch

where claude.cmd >nul 2>nul
if errorlevel 1 goto missing
set "CLAUDE_CMD=claude.cmd"

:launch
call "%CLAUDE_CMD%" %*
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" pause
exit /b %EXIT_CODE%

:missing
echo [X] Claude Code was not found.
echo     Install it first, then double-click this file again.
pause
exit /b 1
