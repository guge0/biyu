param(
    [switch]$SkipSidecarBuild
)

# S-3C:组装「解压即用」便携包(三级回落启动器入包)+ 打 zip + 体积/SHA256 报告。
# 在仓库根执行:powershell -NoProfile -ExecutionPolicy Bypass -File packaging\make_portable.ps1
#
# 布局(与既有便携包一致,组装改为脚本化,不再手工拷):
#   biyu-v1.0.0-portable/
#     biyu-sidecar.exe + _internal/   ← dist/biyu-sidecar onedir 平铺到包根
#     config/ docs/ prompts/ assets/ packaging-version.json(同上,随 onedir 一起)
#     electron-shell/                 ← 壳源码三件 + icons(壳模式用系统 electron,不带 node_modules)
#     启动笔驭.bat + sidecar-launch.ps1 + 笔驭.ico  ← 三级回落启动器(源模板在 packaging\portable\)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pk = Join-Path $repo 'packaging'
$src = Join-Path $pk 'dist\biyu-sidecar'
$stage = Join-Path $pk 'dist\biyu-v1.0.0-portable'
$zip = Join-Path $pk 'dist\biyu-v1.0.0-portable.zip'

# ---------- 1) sidecar 必须已构建 ----------
if (-not (Test-Path -LiteralPath (Join-Path $src 'biyu-sidecar.exe'))) {
    if ($SkipSidecarBuild) { throw "sidecar 未构建且指定了 -SkipSidecarBuild:$src" }
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $pk 'build_sidecar.ps1')
    if ($LASTEXITCODE -ne 0) { throw 'build_sidecar.ps1 failed' }
}

# ---------- 2) 重组装 staging(删旧重建,不残留旧文件) ----------
if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
New-Item -ItemType Directory -Path $stage | Out-Null
Copy-Item -Path (Join-Path $src '*') -Destination $stage -Recurse -Force
# Key 红线:私人 models.yaml 永不入包(与 build_sidecar.ps1 同款闸)
if (Test-Path -LiteralPath (Join-Path $stage 'config\models.yaml')) { throw 'FORBIDDEN: models.yaml must never be staged' }

# ---------- 3) electron 壳源码(不带 node_modules:壳模式复用系统 electron) ----------
$shellDir = Join-Path $stage 'electron-shell'
New-Item -ItemType Directory -Path $shellDir | Out-Null
foreach ($f in @('main.js', 'package.json', 'package-lock.json')) {
    Copy-Item -LiteralPath (Join-Path $pk "electron\$f") -Destination (Join-Path $shellDir $f) -Force
}
Copy-Item -LiteralPath (Join-Path $pk 'electron\icons') -Destination (Join-Path $shellDir 'icons') -Recurse -Force

# ---------- 4) 三级回落启动器(源模板在 packaging\portable\;bat 转 CRLF+无BOM 保证 cmd 正确解析) ----------
Copy-Item -LiteralPath (Join-Path $pk 'portable\sidecar-launch.ps1') -Destination (Join-Path $stage 'sidecar-launch.ps1') -Force
$batText = [System.IO.File]::ReadAllText((Join-Path $pk 'portable\启动笔驭.bat'))
$batText = $batText -replace "`r?`n", "`r`n"
[System.IO.File]::WriteAllText((Join-Path $stage '启动笔驭.bat'), $batText, [System.Text.UTF8Encoding]::new($false))
Copy-Item -LiteralPath (Join-Path $pk 'electron\icons\biyu.ico') -Destination (Join-Path $stage '笔驭.ico') -Force

# ---------- 5) MinGit 入包(零前置:建书/示例书的本地历史依赖 git,干净机没有) ----------
# vendor 缓存(packaging\vendor\mingit.zip)不入库(*.zip 全局忽略);缺则下载(npmmirror 主,GitHub 备)。
$vendorZip = Join-Path $pk 'vendor\mingit.zip'
if (-not (Test-Path -LiteralPath $vendorZip)) {
    New-Item -ItemType Directory -Path (Split-Path $vendorZip) -Force | Out-Null
    Write-Host '[portable] downloading MinGit (bundled git for clean machines)...'
    $ok = $false
    foreach ($url in @(
        'https://registry.npmmirror.com/-/binary/git-for-windows/v2.50.1.windows.1/MinGit-2.50.1-64-bit.zip',
        'https://github.com/git-for-windows/git/releases/download/v2.50.1.windows.1/MinGit-2.50.1-64-bit.zip'
    )) {
        try {
            Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $vendorZip -TimeoutSec 300
            if ((Get-Item -LiteralPath $vendorZip).Length -gt 10MB) { $ok = $true; break }
        } catch { Write-Host "  source failed: $url" }
    }
    if (-not $ok) { throw 'MinGit download failed (put MinGit-2.50.1-64-bit.zip at packaging\vendor\mingit.zip and retry)' }
}
Expand-Archive -LiteralPath $vendorZip -DestinationPath (Join-Path $stage 'git') -Force
if (-not (Test-Path -LiteralPath (Join-Path $stage 'git\cmd\git.exe'))) { throw 'MinGit layout unexpected: git\cmd\git.exe missing' }

# ---------- 6) zip(条目名 UTF-8:Windows 10+ 资源管理器解压中文文件名不乱码) ----------
if (Test-Path -LiteralPath $zip) { Remove-Item -LiteralPath $zip -Force }
Add-Type -AssemblyName System.IO.Compression, System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::CreateFromDirectory(
    $stage, $zip, [System.IO.Compression.CompressionLevel]::Optimal, $false, [System.Text.Encoding]::UTF8)

# ---------- 7) 体积与产物报告 ----------
$files = Get-ChildItem -LiteralPath $stage -Recurse -File
$mb = [math]::Round(($files | Measure-Object -Property Length -Sum).Sum / 1MB, 1)
$hash = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash
Write-Host ''
Write-Host '=== biyu portable assembled ==='
Write-Host " dir : $stage  ($($files.Count) files, $mb MB)"
Write-Host " zip : $zip"
Write-Host " sha256: $hash"
