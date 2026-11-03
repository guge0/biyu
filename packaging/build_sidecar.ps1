param(
    [switch]$SkipVersionStamp
)

# S-3 T1/T2:一键构建 biyu-sidecar(onedir)+ 根级载荷铺进 exe 目录 + 体积报告。
# 在仓库根执行:powershell -NoProfile -ExecutionPolicy Bypass -File packaging\build_sidecar.ps1
#
# 载荷布局约定:exe 目录同时兼任 BIYU_PROJECT_ROOT——
#  · get_project_root() 消费者(config/models.yaml.example、docs/index.html、prompts/assets 模板)
#  · 冻结后 Path(__file__).parents[3] 消费者(prompts/writer|editor、config/editor.yaml、assets/声纹库)
# 两类都落在 exe 旁,单一事实源。

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pk = Join-Path $repo 'packaging'
$venvPython = Join-Path $repo '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) { throw "project venv python not found: $venvPython" }

# ---------- 1) 图标(缺则生成) ----------
$ico = Join-Path $pk 'electron\icons\biyu.ico'
if (-not (Test-Path -LiteralPath $ico)) {
    & $venvPython (Join-Path $pk 'make_icon.py') | Write-Host
    if ($LASTEXITCODE -ne 0) { throw 'make_icon.py failed' }
}

# ---------- 2) PyInstaller ----------
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

# ---------- 3) 根级载荷铺进 exe 目录(兼任 BIYU_PROJECT_ROOT) ----------
$distDir = Join-Path $pk 'dist\biyu-sidecar'

# Key 红线:只带免 Key 件;models.yaml(私人 Key 配置)永不入包。
$configFiles = @('models.yaml.example', 'default.yaml', 'auditor.yaml', 'editor.yaml', 'published_version.json')
New-Item -ItemType Directory -Path (Join-Path $distDir 'config') -Force | Out-Null
foreach ($f in $configFiles) {
    Copy-Item -LiteralPath (Join-Path $repo "config\$f") -Destination (Join-Path $distDir "config\$f") -Force
}
if (Test-Path -LiteralPath (Join-Path $distDir 'config\models.yaml')) { throw "FORBIDDEN: models.yaml must never be staged" }

New-Item -ItemType Directory -Path (Join-Path $distDir 'docs') -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $repo 'docs\index.html') -Destination (Join-Path $distDir 'docs\index.html') -Force
Copy-Item -LiteralPath (Join-Path $repo 'prompts') -Destination (Join-Path $distDir 'prompts') -Recurse -Force
Copy-Item -LiteralPath (Join-Path $repo 'assets') -Destination (Join-Path $distDir 'assets') -Recurse -Force

# ---------- 4) 构建信息(供壳注入 BIYU_SHORT_SHA;/api/version 回显) ----------
$shortSha = (& git -C $repo rev-parse --short=8 HEAD 2>$null)
if ([string]::IsNullOrWhiteSpace($shortSha)) { $shortSha = 'uncommitted' }
# 整改清单 #4:工作树有未提交改动时,包内代码与 HEAD 对不上。正式包拒绝构建;
# 测试包须显式设 BIYU_ALLOW_DIRTY_BUILD=1,构建戳带 -dirty 后缀,保证可追溯。
$dirty = (& git -C $repo status --porcelain --untracked-files=normal -- src packaging config prompts assets 2>$null)
if ($dirty) {
    if ($env:BIYU_ALLOW_DIRTY_BUILD -ne '1') {
        throw "工作树有未提交改动(src/packaging/config/prompts/assets),拒绝打正式包。先提交;确需测试包请设 BIYU_ALLOW_DIRTY_BUILD=1。"
    }
    $shortSha = "$shortSha-dirty"
    Write-Warning "正在用未提交的工作树打测试包,构建戳标为 $shortSha"
}
$buildDate = Get-Date -Format 'yyyyMMdd'
if (-not $SkipVersionStamp) {
    # 无 BOM 写入:PS5.1 的 Set-Content -Encoding UTF8 会带 BOM,Node 端 JSON.parse 失败。
    $versionJson = @{ version = '1.0.0'; build = $buildDate; sha = $shortSha } | ConvertTo-Json
    [System.IO.File]::WriteAllText(
        (Join-Path $distDir 'packaging-version.json'),
        $versionJson,
        [System.Text.UTF8Encoding]::new($false)
    )
}

# ---------- 5) 体积与产物报告 ----------
$files = Get-ChildItem -LiteralPath $distDir -Recurse -File
$bytes = ($files | Measure-Object -Property Length -Sum).Sum
$mb = [math]::Round($bytes / 1MB, 1)
Write-Host ''
Write-Host "=== biyu-sidecar built ==="
Write-Host " dir : $distDir  (exe 目录兼任 BIYU_PROJECT_ROOT)"
Write-Host " size: $mb MB ($($files.Count) files)"
Write-Host " sha : $shortSha  build: $buildDate"
