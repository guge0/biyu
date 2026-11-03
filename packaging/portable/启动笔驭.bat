@echo off
rem Biyu v1.0.0 portable launcher (S-3C three-level fallback)
rem Level 1: system electron found  -> shell mode (packaged electron-shell source)
rem Level 2: no electron            -> sidecar + default browser (sidecar-launch.ps1)
rem Level 3: files missing/AV ate them -> human-readable message, never flash-close
setlocal EnableExtensions
set "ROOT=%~dp0"
chcp 65001 >nul
title 笔驭 便携版

rem 零前置:便携包自带 MinGit(建书/示例书需要 git),有则优先用包内版本
if exist "%ROOT%git\cmd\git.exe" set "PATH=%ROOT%git\cmd;%PATH%"

where electron >nul 2>nul
if %errorlevel%==0 (
  electron "%ROOT%electron-shell"
  goto :end
)

if exist "%ROOT%biyu-sidecar.exe" (
  if not exist "%ROOT%sidecar-launch.ps1" (
    echo [笔驭] 启动文件缺失：sidecar-launch.ps1 不在，包可能没解压完整或被杀毒软件拆了。
    echo        请重新解压完整压缩包，或把整个笔驭文件夹加入杀毒软件信任区。
    pause
    goto :end
  )
  rem 绝对路径调 PowerShell:精简/异常 PATH 环境下也不依赖 PATH 解析
  "%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%ROOT%sidecar-launch.ps1"
  if errorlevel 9009 pause
  goto :end
)

echo [笔驭] 没有找到 biyu-sidecar.exe，笔驭无法启动。
echo        最常见原因：压缩包没解压完整，或杀毒软件把程序隔离了。
echo        请重新解压整个压缩包；若杀毒软件反复拦截，请把整个笔驭文件夹加入信任区。
pause

:end
endlocal
