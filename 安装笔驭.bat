@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install_biyu.ps1"
if errorlevel 1 (
  echo.
  echo [X] ???????????????
  pause
  exit /b 1
)
echo.
pause
endlocal

