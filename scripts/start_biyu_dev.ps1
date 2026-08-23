param([int]$Port = 8090)

$ErrorActionPreference = 'Stop'
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
    $developmentRoot = if ([string]::IsNullOrWhiteSpace($env:BIYU_TEST_DATA_ROOT)) { Join-Path (Split-Path -Parent $projectRoot) 'BiyuTestData' } else { [System.IO.Path]::GetFullPath($env:BIYU_TEST_DATA_ROOT) }
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
$env:BIYU_ENV = 'test'
$env:BIYU_RUNTIME_ROLE = 'development'
$env:BIYU_DATA_ROOT = $dataRoot
$env:BIYU_DATA_ROOT_SOURCE = [string]$resolution.source
$env:BIYU_TEST_DATA_ROOT = $dataRoot
$env:BIYU_PROJECT_ROOT = $projectRoot
$env:PYTHONPATH = (Join-Path $projectRoot 'src')
$listener = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) {
    $owner = Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue
    if ($owner -and $owner.Path -and ([System.IO.Path]::GetFullPath($owner.Path) -like "$projectRoot\.venv\Scripts\*")) {
        Write-Host "Stopping the existing development service (PID $($owner.Id))..."
        Stop-Process -Id $owner.Id -Force
        Start-Sleep -Milliseconds 500
    } else {
        Write-Host "[X] Port $Port is occupied by another application; nothing was stopped." -ForegroundColor Red
        exit 2
    }
}
& '.venv\Scripts\python.exe' -m uvicorn biyu.ui.app:app --host 127.0.0.1 --port $Port
exit $LASTEXITCODE
