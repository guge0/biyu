@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_biyu.ps1"
if errorlevel 1 (
  echo.
  echo [X] 安装没有完成，请查看上方说明。
  pause
  exit /b 1
)
echo.
pause
endlocal
