param([int]$Port = 8090)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $projectRoot
if ($Port -eq 8080) {
    Write-Host '[X] Development Biyu must not use port 8080.' -ForegroundColor Red
    exit 2
}
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $projectRoot 'scripts\install_biyu.ps1') -SkipPull -OnlyIfNeeded
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# Development has its own explicit first-run initializer. It never falls back
# to the author's production data root.
$configRoot = if ([string]::IsNullOrWhiteSpace($env:BIYU_USER_CONFIG_DIR)) { Join-Path $HOME '.biyu' } else { [System.IO.Path]::GetFullPath($env:BIYU_USER_CONFIG_DIR) }
$developmentConfig = Join-Path $configRoot 'runtime-development.json'
if (-not (Test-Path -LiteralPath $developmentConfig)) {
    $developmentRoot = Join-Path (Split-Path -Parent $projectRoot) 'BiyuTestData'
    New-Item -ItemType Directory -Path $developmentRoot -Force | Out-Null
    New-Item -ItemType Directory -Path $configRoot -Force | Out-Null
    @{ schema_version = 1; data_root = $developmentRoot; role = 'development' } | ConvertTo-Json | Set-Content -LiteralPath $developmentConfig -Encoding UTF8
    Write-Host "Created persistent development data location: $developmentConfig"
}
$resolutionOutput = @(& '.venv\Scripts\python.exe' -m biyu.runtime_config resolve --role development)
if ($LASTEXITCODE -ne 0) {
    $resolutionOutput | ForEach-Object { Write-Host $_ -ForegroundColor Red }
    exit 2
}
$resolution = ($resolutionOutput -join "`n") | ConvertFrom-Json
$dataRoot = [System.IO.Path]::GetFullPath([string]$resolution.data_root)
$persistentRoot = [System.IO.Path]::GetFullPath([string]$resolution.persistent_data_root)
if ($resolution.temporary) {
    Write-Host " data source: temporary override ($dataRoot)" -ForegroundColor Yellow
}
$verificationOutput = @(& '.venv\Scripts\python.exe' -m biyu.runtime_config verify --role development --actual-root $dataRoot)
if ($LASTEXITCODE -ne 0) {
    Write-Host '[X] Runtime data root does not match persistent configuration.' -ForegroundColor Red
    Write-Host " persistent: $persistentRoot" -ForegroundColor Red
    Write-Host " actual:     $dataRoot" -ForegroundColor Red
    exit 2
}
$env:BIYU_ENV = 'test'
$env:BIYU_RUNTIME_ROLE = 'development'
$env:BIYU_DATA_ROOT = $dataRoot
$env:BIYU_DATA_ROOT_SOURCE = [string]$resolution.source
$env:BIYU_TEST_DATA_ROOT = $persistentRoot
$env:BIYU_PROJECT_ROOT = $projectRoot
$env:PYTHONPATH = (Join-Path $projectRoot 'src')
$listener = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) {
    $guardOutput = @(& '.venv\Scripts\python.exe' (Join-Path $projectRoot 'scripts\runtime_guard.py') --port $Port --data-root $dataRoot)
    $guardCode = $LASTEXITCODE
    $guardOutput | ForEach-Object { Write-Host $_ -ForegroundColor $(if ($guardCode -eq 3) { 'Yellow' } else { 'Red' }) }
    if ($guardCode -eq 3) {
        Write-Host "Stopping the existing development service (PID $($listener.OwningProcess))..."
        Stop-Process -Id $listener.OwningProcess -Force
        Start-Sleep -Milliseconds 500
    } else {
        exit $guardCode
    }
}
$shortSha = (& git -C $projectRoot rev-parse --short=8 HEAD 2>$null)
if ([string]::IsNullOrWhiteSpace($shortSha)) { $shortSha = 'uncommitted' }
$remoteUrl = (& git -C $projectRoot remote get-url origin 2>$null)
$remoteSlug = if ($remoteUrl -match 'github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$') { $Matches[1] } else { 'remote-unset' }
$sourceLabel = if ($resolution.temporary) { 'temporary override' } else { 'persistent' }
$identity = "Biyu | $(Split-Path -Leaf $projectRoot) | $remoteSlug | $shortSha | $dataRoot | $sourceLabel"
Write-Host " $identity"
& '.venv\Scripts\python.exe' -m uvicorn biyu.ui.app:app --host 127.0.0.1 --port $Port
exit $LASTEXITCODE
