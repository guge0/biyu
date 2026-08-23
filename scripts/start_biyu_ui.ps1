param([int]$Port = 8080)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $projectRoot

if ($Port -ne 8080) {
    Write-Host '[X] Biyu uses port 8080.' -ForegroundColor Red
    exit 2
}

if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    Write-Host 'First run: installing Biyu...'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $projectRoot 'scripts\install_biyu.ps1') -SkipPull
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

$resolutionOutput = @(& '.venv\Scripts\python.exe' -m biyu.runtime_config resolve --role production)
if ($LASTEXITCODE -ne 0) {
    Write-Host '[X] Biyu data location configuration is missing or invalid.' -ForegroundColor Red
    $resolutionOutput | ForEach-Object { Write-Host $_ -ForegroundColor Red }
    exit 2
}
try {
    $resolution = ($resolutionOutput -join "`n") | ConvertFrom-Json
} catch {
    Write-Host '[X] Biyu could not read its persistent data location configuration.' -ForegroundColor Red
    exit 2
}

$dataRoot = [System.IO.Path]::GetFullPath([string]$resolution.data_root)
$env:BIYU_ENV = 'prod'
$env:BIYU_RUNTIME_ROLE = 'production'
$env:BIYU_DATA_ROOT = $dataRoot
$env:BIYU_DATA_ROOT_SOURCE = [string]$resolution.source
$env:BIYU_PRODUCTION_DATA_ROOT = $dataRoot
Remove-Item Env:BIYU_DATA_ROOT_2 -ErrorAction SilentlyContinue
$env:BIYU_PROJECT_ROOT = $projectRoot
$env:PYTHONPATH = (Join-Path $projectRoot 'src')
$env:BIYU_CHECKOUT_NAME = Split-Path -Leaf $projectRoot

$url = "http://127.0.0.1:$Port"
$listener = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) {
    $owner = Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue
    if ($owner -and $owner.Path -and ([System.IO.Path]::GetFullPath($owner.Path) -like "$projectRoot\.venv\Scripts\*")) {
        Write-Host "Stopping the existing Biyu service (PID $($owner.Id))..."
        Stop-Process -Id $owner.Id -Force
        Start-Sleep -Milliseconds 500
    } else {
        Write-Host "[X] Port $Port is occupied by another application; nothing was stopped." -ForegroundColor Red
        exit 2
    }
}

$shortSha = (& git -C $projectRoot rev-parse --short=8 HEAD 2>$null)
if ([string]::IsNullOrWhiteSpace($shortSha)) { $shortSha = 'uncommitted' }
$remoteUrl = (& git -C $projectRoot remote get-url origin 2>$null)
$remoteSlug = if ($remoteUrl -match 'github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$') { $Matches[1] } else { 'remote-unset' }
$env:BIYU_SHORT_SHA = $shortSha
$env:BIYU_REMOTE_SLUG = $remoteSlug
$identity = "Biyu | $env:BIYU_CHECKOUT_NAME | $remoteSlug | $shortSha | $env:BIYU_DATA_ROOT"

$host.UI.RawUI.WindowTitle = 'Biyu'
Write-Host ''
Write-Host '=========================================='
Write-Host ' Biyu'
Write-Host " $url"
Write-Host " code: $projectRoot"
Write-Host " data: $env:BIYU_DATA_ROOT"
Write-Host " $identity"
Write-Host ' Ctrl+C to stop'
Write-Host '=========================================='

Start-Process powershell.exe -WindowStyle Hidden -ArgumentList @('-NoProfile', '-Command', "`$u='$url'; for(`$i=0;`$i -lt 60;`$i++){try{Invoke-WebRequest -UseBasicParsing -Uri (`$u+'/api/version') -TimeoutSec 1 | Out-Null; Start-Process `$u; exit 0}catch{Start-Sleep -Milliseconds 500}}")
& '.venv\Scripts\python.exe' -m uvicorn biyu.ui.app:app --host 127.0.0.1 --port $Port
exit $LASTEXITCODE
