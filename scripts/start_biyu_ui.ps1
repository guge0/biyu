param([int]$Port = 8080)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $projectRoot

if ($Port -ne 8080) {
    Write-Host '[X] Biyu uses port 8080.' -ForegroundColor Red
    exit 2
}

$listener = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
    Select-Object -First 1
if ($listener) {
    $owner = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)" -ErrorAction SilentlyContinue
    $commandLine = if ($owner) { [string]$owner.CommandLine } else { '' }
    $isBiyu = $commandLine -match 'uvicorn\s+biyu\.ui\.app:app' -or $commandLine -match 'python(?:\.exe)?\s+.*biyu\.ui\.app:app'
    if ($isBiyu) {
        Write-Host "Existing Biyu service found (PID $($listener.OwningProcess)); restarting it with the current code." -ForegroundColor Yellow
        Stop-Process -Id $listener.OwningProcess -Force -ErrorAction SilentlyContinue
        for ($i = 0; $i -lt 20; $i++) {
            if (-not (Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)) { break }
            Start-Sleep -Milliseconds 250
        }
        if (Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
            Write-Host "[X] The old Biyu service did not release port $Port." -ForegroundColor Red
            exit 2
        }
    } else {
        Write-Host "[X] Port $Port is occupied by another program; Biyu will not switch ports." -ForegroundColor Red
        Write-Host "    PID: $($listener.OwningProcess)"
        if ($owner) { Write-Host "    Process: $($owner.CommandLine)" }
        Write-Host '    Close that program, then double-click start_biyu_ui.bat again.'
        exit 2
    }
}

if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    Write-Host 'First run: installing Biyu...'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $projectRoot 'install_biyu.ps1') -SkipPull
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $projectRoot 'install_biyu.ps1') -SkipPull -OnlyIfNeeded
if ($LASTEXITCODE -ne 0) {
    Write-Host '[X] Biyu package refresh failed; the service was not started.' -ForegroundColor Red
    exit $LASTEXITCODE
}

$dataRoot = $env:BIYU_DATA_ROOT
if ([string]::IsNullOrWhiteSpace($dataRoot)) {
    $dataRoot = Join-Path $HOME 'BiyuData'
}
$dataRoot = [System.IO.Path]::GetFullPath($dataRoot)
if (-not (Test-Path -LiteralPath $dataRoot)) {
    New-Item -ItemType Directory -Path $dataRoot -Force | Out-Null
}

# Runtime roles remain internal safety metadata; users run one product entry.
$env:BIYU_ENV = 'prod'
$env:BIYU_RUNTIME_ROLE = 'production'
$env:BIYU_DATA_ROOT = $dataRoot
$env:BIYU_PRODUCTION_DATA_ROOT = $dataRoot
Remove-Item Env:BIYU_DATA_ROOT_2 -ErrorAction SilentlyContinue
$env:BIYU_PROJECT_ROOT = $projectRoot
$env:BIYU_CHECKOUT_NAME = Split-Path -Leaf $projectRoot

$shortSha = (& git -C $projectRoot rev-parse --short=8 HEAD 2>$null)
if ([string]::IsNullOrWhiteSpace($shortSha)) { $shortSha = 'uncommitted' }
$remoteUrl = (& git -C $projectRoot remote get-url origin 2>$null)
$remoteSlug = if ($remoteUrl -match 'github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$') { $Matches[1] } else { 'remote-unset' }
$env:BIYU_SHORT_SHA = $shortSha
$env:BIYU_REMOTE_SLUG = $remoteSlug
$identity = "Biyu | $env:BIYU_CHECKOUT_NAME | $remoteSlug | $shortSha | $env:BIYU_DATA_ROOT"

$host.UI.RawUI.WindowTitle = 'Biyu'
$url = "http://127.0.0.1:$Port"
Write-Host ''
Write-Host '=========================================='
Write-Host ' Biyu'
Write-Host " $url"
Write-Host " code: $projectRoot"
Write-Host " data: $env:BIYU_DATA_ROOT"
Write-Host " $identity"
Write-Host ' Ctrl+C to stop'
Write-Host '=========================================='

Start-Process powershell.exe -WindowStyle Hidden -ArgumentList @(
    '-NoProfile', '-Command',
    "`$u='$url'; for(`$i=0;`$i -lt 60;`$i++){try{Invoke-WebRequest -UseBasicParsing -Uri (`$u+'/api/version') -TimeoutSec 1 | Out-Null; Start-Process `$u; exit 0}catch{Start-Sleep -Milliseconds 500}}"
)

& '.venv\Scripts\python.exe' -m uvicorn biyu.ui.app:app --host 127.0.0.1 --port $Port
exit $LASTEXITCODE
