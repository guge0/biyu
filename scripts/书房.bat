@echo off
setlocal
cd /d "%~dp0.."

set "BIYU_TRACK=creative"
set "CLAUDE_CMD=%APPDATA%\npm\claude.cmd"
if exist "%CLAUDE_CMD%" goto launch
set "CLAUDE_CMD=%APPDATA%\npm\claude.exe"
if exist "%CLAUDE_CMD%" goto launch

where claude >nul 2>nul
if not errorlevel 1 (
  set "CLAUDE_CMD=claude"
  goto launch
)
where claude.cmd >nul 2>nul
if not errorlevel 1 (
  set "CLAUDE_CMD=claude.cmd"
  goto launch
)
where claude.exe >nul 2>nul
if not errorlevel 1 (
  set "CLAUDE_CMD=claude.exe"
  goto launch
)
goto missing

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
