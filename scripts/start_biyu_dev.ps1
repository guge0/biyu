param([int]$Port = 8090)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $projectRoot
if ($Port -eq 8080) {
    Write-Host '[X] Development Biyu must not use port 8080.' -ForegroundColor Red
    exit 2
}
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $projectRoot 'install_biyu.ps1') -SkipPull -OnlyIfNeeded
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$resolutionOutput = @(& '.venv\Scripts\python.exe' -m biyu.runtime_config resolve --role development)
if ($LASTEXITCODE -ne 0) {
    $resolutionOutput | ForEach-Object { Write-Host $_ -ForegroundColor Red }
    exit 2
}
$resolution = ($resolutionOutput -join "`n") | ConvertFrom-Json
$dataRoot = [System.IO.Path]::GetFullPath([string]$resolution.data_root)
$env:BIYU_ENV = 'test'
$env:BIYU_RUNTIME_ROLE = 'development'
$env:BIYU_DATA_ROOT = $dataRoot
$env:BIYU_DATA_ROOT_SOURCE = [string]$resolution.source
$env:BIYU_TEST_DATA_ROOT = $dataRoot
$env:BIYU_PROJECT_ROOT = $projectRoot
$listener = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) {
    Write-Host "[X] Port $Port is already occupied. Nothing was stopped." -ForegroundColor Red
    exit 2
}
& '.venv\Scripts\python.exe' -m uvicorn biyu.ui.app:app --host 127.0.0.1 --port $Port
exit $LASTEXITCODE
