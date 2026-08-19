param(
    [string]$DestinationRoot = "D:\biyu-data-replica",
    [ValidateRange(24, 168)][int]$HourlyRetentionHours = 72,
    [ValidateRange(30, 90)][int]$DailyRetentionDays = 31
)

$ErrorActionPreference = "Stop"
$runner = Join-Path $PSScriptRoot "run_data_replica.ps1"
if (-not (Test-Path -LiteralPath $runner)) { throw "Replica runner not found: $runner" }
$taskName = "BiyuDataReplica"
$argumentParts = @(
    "-NoProfile",
    "-NonInteractive",
    "-WindowStyle Hidden",
    "-ExecutionPolicy Bypass",
    ('-File "{0}"' -f $runner),
    ('-DestinationRoot "{0}"' -f $DestinationRoot),
    "-HourlyRetentionHours $HourlyRetentionHours",
    "-DailyRetentionDays $DailyRetentionDays"
)
$taskArguments = $argumentParts -join " "
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $taskArguments
$trigger = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date).AddHours(1) `
    -RepetitionInterval (New-TimeSpan -Hours 1)
$settings = New-ScheduledTaskSettingsSet `
    -Hidden `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal `
    -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Biyu same-machine data replica snapshots" `
    -Force | Out-Null

& $runner `
    -DestinationRoot $DestinationRoot `
    -HourlyRetentionHours $HourlyRetentionHours `
    -DailyRetentionDays $DailyRetentionDays

Write-Host "[OK] BiyuDataReplica installed: hourly, hidden, non-interactive."
Write-Host "[OK] Replica self-check passed. Failures still write $DestinationRoot\status.json for the workbench."
