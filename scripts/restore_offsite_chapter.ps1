param(
    [Parameter(Mandatory=$true)][string]$Repository,
    [Parameter(Mandatory=$true)][string]$Snapshot,
    [Parameter(Mandatory=$true)][string]$ChapterPath,
    [Parameter(Mandatory=$true)][string]$StagingDirectory
)

if (-not (Get-Command restic -ErrorAction SilentlyContinue)) { throw "Install restic before running this script." }
if (-not $env:RESTIC_PASSWORD_COMMAND) { throw "Set RESTIC_PASSWORD_COMMAND from offline recovery credentials or a password manager." }
if ($StagingDirectory -match '(?i)[\\/]data([\\/]|$)') { throw "Restore target must be a staging directory outside data; the author moves files back manually." }
New-Item -ItemType Directory -Force -Path $StagingDirectory | Out-Null
restic -r $Repository restore $Snapshot --target $StagingDirectory --include $ChapterPath
