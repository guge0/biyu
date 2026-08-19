@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_biyu_ui.ps1" -Mode Test -Port 8090
set "BIYU_EXIT=%errorlevel%"
if not "%BIYU_EXIT%"=="0" pause
exit /b %BIYU_EXIT%
