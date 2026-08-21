param(
    [string]$PythonPath = (Join-Path $PSScriptRoot '..\.venv\Scripts\python.exe'),
    [string]$ProjectRoot = (Join-Path $PSScriptRoot '..'),
    [switch]$Disable
)

$ErrorActionPreference = 'Stop'
$taskName = 'BiyuDailyBackup'

if ($Disable) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "[OK] $taskName disabled"
    exit 0
}

$projectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$runner = Join-Path $projectRoot 'scripts\run_biyu_backup.py'
if (-not (Test-Path -LiteralPath $PythonPath)) { throw "Python runtime not found: $PythonPath" }
if (-not (Test-Path -LiteralPath $runner)) { throw "Backup runner not found: $runner" }

$arguments = ('"{0}"' -f $runner)
$action = New-ScheduledTaskAction -Execute $PythonPath -Argument $arguments -WorkingDirectory $projectRoot
$trigger = New-ScheduledTaskTrigger -Daily -At '03:15'
$settings = New-ScheduledTaskSettingsSet -Hidden -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force -Description 'Biyu daily directly-readable data backup' | Out-Null
Write-Host "[OK] $taskName enabled: daily 03:15; missed runs start when Windows is available"
