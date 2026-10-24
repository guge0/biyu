param(
    [switch]$SkipVersionStamp
)

# S-3 T1:一键构建 biyu-sidecar(onedir)+ home 载荷 staging + 体积报告。
# 在仓库根执行:powershell -NoProfile -ExecutionPolicy Bypass -File packaging\build_sidecar.ps1

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pk = Join-Path $repo 'packaging'
$venvPython = Join-Path $repo '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) { throw "project venv python not found: $venvPython" }

# ---------- 1) home 载荷 staging(BIYU_PROJECT_ROOT 指向的内容) ----------
$homeDir = Join-Path $pk 'home-staging'
if (Test-Path -LiteralPath $homeDir) { Remove-Item -LiteralPath $homeDir -Recurse -Force }
New-Item -ItemType Directory -Path (Join-Path $homeDir 'config') | Out-Null

# Key 红线:只带免 Key 件;models.yaml(私人 Key 配置)永不入包。
$configFiles = @('models.yaml.example', 'default.yaml', 'auditor.yaml', 'editor.yaml', 'published_version.json')
foreach ($f in $configFiles) {
    Copy-Item -LiteralPath (Join-Path $repo "config\$f") -Destination (Join-Path $homeDir "config\$f")
}
if (Test-Path -LiteralPath (Join-Path $homeDir 'config\models.yaml')) { throw "FORBIDDEN: models.yaml must never be staged" }

New-Item -ItemType Directory -Path (Join-Path $homeDir 'docs') | Out-Null
Copy-Item -LiteralPath (Join-Path $repo 'docs\index.html') -Destination (Join-Path $homeDir 'docs\index.html')
Copy-Item -LiteralPath (Join-Path $repo 'prompts') -Destination (Join-Path $homeDir 'prompts') -Recurse

# ---------- 2) 构建信息(供壳注入 BIYU_SHORT_SHA;/api/version 回显) ----------
$shortSha = (& git -C $repo rev-parse --short=8 HEAD 2>$null)
if ([string]::IsNullOrWhiteSpace($shortSha)) { $shortSha = 'uncommitted' }
$buildDate = Get-Date -Format 'yyyyMMdd'
if (-not $SkipVersionStamp) {
    # 无 BOM 写入:PS5.1 的 Set-Content -Encoding UTF8 会带 BOM,Node 端 JSON.parse 失败。
    $versionJson = @{ version = '1.0.0'; build = $buildDate; sha = $shortSha } | ConvertTo-Json
    [System.IO.File]::WriteAllText(
        (Join-Path $homeDir 'packaging-version.json'),
        $versionJson,
        [System.Text.UTF8Encoding]::new($false)
    )
}

# ---------- 3) 图标(缺则生成) ----------
$ico = Join-Path $pk 'electron\icons\biyu.ico'
if (-not (Test-Path -LiteralPath $ico)) {
    & $venvPython (Join-Path $pk 'make_icon.py') | Write-Host
    if ($LASTEXITCODE -ne 0) { throw 'make_icon.py failed' }
}

# ---------- 4) PyInstaller ----------
# 注:$ErrorActionPreference='Stop' 会把原生命令 stderr 当终止错误,
# 故用文件存在性探测代替试运行,并在 pip/PyInstaller 调用期间局部放宽 EAP。
$pyinstallerPkg = Join-Path $repo '.venv\Lib\site-packages\PyInstaller'
if (-not (Test-Path -LiteralPath $pyinstallerPkg)) {
    Write-Host '[build] installing build-time tooling (pyinstaller)...'
    $ErrorActionPreference = 'Continue'
    & $venvPython -m pip install -r (Join-Path $pk 'requirements-build.txt') --disable-pip-version-check
    $pipCode = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    if ($pipCode -ne 0) { throw 'pip install pyinstaller failed' }
}

Push-Location $repo
try {
    $ErrorActionPreference = 'Continue'
    & $venvPython -m PyInstaller (Join-Path $pk 'sidecar.spec') --noconfirm `
        --distpath (Join-Path $pk 'dist') --workpath (Join-Path $pk 'build')
    $buildCode = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    if ($buildCode -ne 0) { throw "pyinstaller failed (exit $buildCode)" }
}
finally { Pop-Location }

# ---------- 5) 体积与产物报告 ----------
$distDir = Join-Path $pk 'dist\biyu-sidecar'
$files = Get-ChildItem -LiteralPath $distDir -Recurse -File
$bytes = ($files | Measure-Object -Property Length -Sum).Sum
$mb = [math]::Round($bytes / 1MB, 1)
Write-Host ''
Write-Host "=== biyu-sidecar built ==="
Write-Host " dir : $distDir"
Write-Host " size: $mb MB ($($files.Count) files)"
Write-Host " sha : $shortSha  build: $buildDate"
