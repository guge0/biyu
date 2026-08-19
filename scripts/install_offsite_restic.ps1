param([Parameter(Mandatory=$true)][string]$Repository)

if (-not (Get-Command restic -ErrorAction SilentlyContinue)) { throw "Install restic before running this script." }
if (-not $env:RESTIC_PASSWORD_COMMAND) { throw "Set RESTIC_PASSWORD_COMMAND from a password manager; do not store recovery credentials in this repository or beside the backup medium." }
restic -r $Repository snapshots | Out-Host
