param([switch]$SkipPull, [switch]$OnlyIfNeeded)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $repo
$venvPython = Join-Path $repo '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $venvPython)) {
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw '未找到 Git。请先安装 Git for Windows：https://git-scm.com/download/win'
    }
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
        throw '未找到 Python。请先安装 Python 3.12，并勾选 Add Python to PATH。'
    }
    & python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
    if ($LASTEXITCODE -ne 0) {
        throw 'Python 版本过低。笔驭至少需要 Python 3.10，建议安装 Python 3.12，并勾选 Add Python to PATH。'
    }
}
$statePath = Join-Path $repo '.venv\.biyu-install-state'
$head = (& git rev-parse HEAD 2>$null)
$projectFile = Join-Path $repo 'pyproject.toml'
$sha256 = [System.Security.Cryptography.SHA256]::Create()
$stream = [System.IO.File]::OpenRead($projectFile)
try {
    $projectHash = ([System.BitConverter]::ToString($sha256.ComputeHash($stream))).Replace('-', '')
} finally {
    $stream.Dispose()
    $sha256.Dispose()
}
$wantedState = "$head|$projectHash"
if ($OnlyIfNeeded -and (Test-Path -LiteralPath $venvPython) -and (Test-Path -LiteralPath $statePath)) {
    if ((Get-Content -Raw -LiteralPath $statePath).Trim() -eq $wantedState) {
        Write-Host '代码和依赖没有变化，直接启动。'
        exit 0
    }
}
if (-not $SkipPull -and (Test-Path -LiteralPath (Join-Path $repo '.git'))) {
    & git pull --ff-only
    if ($LASTEXITCODE -ne 0) { throw '更新失败。为保护本地文件，笔驭没有继续安装；请处理上方 Git 提示后重试。' }
    $head = (& git rev-parse HEAD 2>$null)
    $wantedState = "$head|$projectHash"
}
if (-not (Test-Path -LiteralPath $venvPython)) {
    & python -m venv (Join-Path $repo '.venv')
    if ($LASTEXITCODE -ne 0) { throw '创建独立运行环境失败。' }
}
& $venvPython -m pip install --upgrade pip setuptools wheel
if ($LASTEXITCODE -ne 0) { throw '更新安装工具失败，请检查网络后重试。' }
& $venvPython -m pip install --upgrade $repo
if ($LASTEXITCODE -ne 0) { throw '安装笔驭失败，请保留本窗口中的错误信息。' }

Set-Content -LiteralPath $statePath -Encoding UTF8 -Value $wantedState
Write-Host '笔驭安装完成。双击 start_biyu_ui.bat 即可启动。' -ForegroundColor Green
