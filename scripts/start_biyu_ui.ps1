param([int]$Port = 8080)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $projectRoot

if ($Port -ne 8080) {
    Write-Host '[X] 笔驭固定使用 8080 端口。' -ForegroundColor Red
    exit 2
}

$listener = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
    Select-Object -First 1
if ($listener) {
    $owner = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)" -ErrorAction SilentlyContinue
    Write-Host "[X] 端口 $Port 已被占用；启动器不会换端口或复用旧服务。" -ForegroundColor Red
    Write-Host "    PID: $($listener.OwningProcess)"
    if ($owner) { Write-Host "    Process: $($owner.CommandLine)" }
    Write-Host '    请关闭旧启动窗口或进程，再重新双击 start_biyu_ui.bat。'
    exit 2
}

if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    Write-Host '首次启动，正在安装笔驭...'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $projectRoot 'install_biyu.ps1') -SkipPull
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $projectRoot 'install_biyu.ps1') -SkipPull -OnlyIfNeeded
if ($LASTEXITCODE -ne 0) {
    Write-Host '[X] 笔驭运行包刷新失败，未启动服务。' -ForegroundColor Red
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
$identity = "笔驭 · $env:BIYU_CHECKOUT_NAME · $remoteSlug · $shortSha · $env:BIYU_DATA_ROOT"

$host.UI.RawUI.WindowTitle = '笔驭'
$url = "http://127.0.0.1:$Port"
Write-Host ''
Write-Host '=========================================='
Write-Host ' 笔驭'
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
