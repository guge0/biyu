param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Production', 'Test')]
    [string]$Mode,
    [Parameter(Mandatory = $true)]
    [int]$Port
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $projectRoot

$expectedPort = if ($Mode -eq 'Production') { 8080 } else { 8090 }
if ($Port -ne $expectedPort) {
    Write-Host "[X] $Mode mode must use port $expectedPort." -ForegroundColor Red
    exit 2
}

$listener = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
    Select-Object -First 1
if ($listener) {
    $owner = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)" -ErrorAction SilentlyContinue
    Write-Host "[X] Port $Port is already occupied. This launcher will not switch ports or reuse an old service." -ForegroundColor Red
    Write-Host "    PID: $($listener.OwningProcess)"
    if ($owner) { Write-Host "    Process: $($owner.CommandLine)" }
    Write-Host '    Close that old startup window/process, then double-click this launcher again.'
    exit 2
}

if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    if ($Mode -eq 'Test') {
        Write-Host '[X] Test environment is not installed. Run install_biyu.ps1 first.' -ForegroundColor Red
        exit 2
    }
    Write-Host 'First run: installing Biyu...'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $projectRoot 'install_biyu.ps1') -SkipPull
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

if ($Mode -eq 'Production') {
    $env:BIYU_ENV = 'prod'
    $env:BIYU_RUNTIME_ROLE = 'production'
    $productionDataRoot = 'D:\BiyuProductionData'
    $env:BIYU_DATA_ROOT = $productionDataRoot
    $env:BIYU_PRODUCTION_DATA_ROOT = $productionDataRoot
    if (-not (Test-Path -LiteralPath $productionDataRoot -PathType Container)) {
        Write-Host "[X] Production requires an explicit BIYU_DATA_ROOT; configured root is missing: $productionDataRoot" -ForegroundColor Red
        exit 2
    }
    Remove-Item Env:BIYU_DATA_ROOT_2 -ErrorAction SilentlyContinue
    $title = 'BIYU PRODUCTION / daily writing'
} else {
    $env:BIYU_ENV = 'test'
    $env:BIYU_RUNTIME_ROLE = 'test'
    $env:BIYU_DATA_ROOT = 'E:\BiyuTestData'
    $env:BIYU_TEST_DATA_ROOT = 'E:\BiyuTestData'
    Remove-Item Env:BIYU_PRODUCTION_DATA_ROOT -ErrorAction SilentlyContinue
    Remove-Item Env:BIYU_DATA_ROOT_2 -ErrorAction SilentlyContinue
    $title = 'BIYU TEST / engineering only'
}

$env:BIYU_PROJECT_ROOT = $projectRoot
$env:BIYU_CHECKOUT_NAME = Split-Path -Leaf $projectRoot
$shortSha = (& git -C $projectRoot rev-parse --short=8 HEAD 2>$null)
if ([string]::IsNullOrWhiteSpace($shortSha)) { $shortSha = 'uncommitted' }
$remoteUrl = (& git -C $projectRoot remote get-url origin 2>$null)
$remoteSlug = if ($remoteUrl -match 'github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$') { $Matches[1] } else { 'remote-unset' }
$env:BIYU_SHORT_SHA = $shortSha
$env:BIYU_REMOTE_SLUG = $remoteSlug
$roleLabel = if ($Mode -eq 'Production') { '生产版' } else { '测试版' }
$identity = "$roleLabel · $env:BIYU_CHECKOUT_NAME · $remoteSlug · $shortSha · $env:BIYU_DATA_ROOT"

$host.UI.RawUI.WindowTitle = $title
$url = "http://127.0.0.1:$Port"
Write-Host ''
Write-Host '=========================================='
Write-Host " $title"
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
