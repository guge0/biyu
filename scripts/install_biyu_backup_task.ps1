param(
    [string]$SourcePath = (Join-Path $PSScriptRoot '..\data'),
    [string]$DestinationRoot = 'D:\BiyuBackup',
    [string]$PythonPath = (Join-Path $PSScriptRoot '..\.venv\Scripts\python.exe')
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$runner = Join-Path $PSScriptRoot 'run_biyu_backup.py'
if (-not (Test-Path -LiteralPath $PythonPath)) { throw "Python runtime not found: $PythonPath" }
if (-not (Test-Path -LiteralPath $runner)) { throw "Backup runner not found: $runner" }

$taskName = 'BiyuDailyBackup'
$arguments = "`"$runner`""
$action = New-ScheduledTaskAction -Execute $PythonPath -Argument $arguments -WorkingDirectory $projectRoot
$trigger = New-ScheduledTaskTrigger -Daily -At '03:15'
$settings = New-ScheduledTaskSettingsSet -Hidden -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force -Description 'Biyu daily directly-readable data backup' | Out-Null
Write-Host "[OK] $taskName installed: daily 03:15 -> $DestinationRoot"
