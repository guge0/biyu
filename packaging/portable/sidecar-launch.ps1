# S-3C · 笔驭 v1.0 浏览器模式启动器(便携包三级回落第二级)。
# 本机没有 Electron 运行时时由 启动笔驭.bat 调起:拉起 biyu-sidecar 并自动打开默认浏览器。
# 语义与 Electron 壳(packaging/electron/main.js)对齐:同一数据根、同一 env 契约、同一杀进程语义。
$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
$Root = $PSScriptRoot
$host.UI.RawUI.WindowTitle = '笔驭 · 浏览器模式（便携）'

function Stop-Fail {
    param([string[]]$Lines)
    Write-Host ''
    Write-Host '──────────────────────────────' -ForegroundColor DarkGray
    foreach ($line in $Lines) { Write-Host "  $line" -ForegroundColor Yellow }
    Write-Host '──────────────────────────────' -ForegroundColor DarkGray
    Write-Host ''
    Read-Host '  按回车键关闭本窗口'
    exit 1
}

try {
    # ---------- 0) 包完整性自检(杀软隔离/解压不完整 → 人话报错,不闪退) ----------
    $exe = Join-Path $Root 'biyu-sidecar.exe'
    $internal = Join-Path $Root '_internal'
    if (-not (Test-Path -LiteralPath $exe)) {
        Stop-Fail @(
            '笔驭没有启动起来：找不到 biyu-sidecar.exe。',
            '最常见的原因：',
            '  1. 压缩包没有解压完整 —— 请重新解压整个 zip 再试；',
            '  2. 杀毒软件把程序当成了威胁并隔离 —— 请打开杀毒软件的',
            '     「隔离区/恢复区」，把 biyu-sidecar.exe 恢复并加入信任区。'
        )
    }
    if (-not (Test-Path -LiteralPath $internal)) {
        Stop-Fail @(
            '笔驭没有启动起来：程序目录不完整（缺少 _internal 文件夹）。',
            '这说明压缩包解压不完整，或杀毒软件删掉了部分文件。',
            '请重新解压整个 zip；如果杀毒软件反复拦截，请把整个笔驭文件夹加入信任区。'
        )
    }
    if (-not (Test-Path -LiteralPath (Join-Path $Root 'config'))) {
        Stop-Fail @(
            '笔驭没有启动起来：缺少 config 文件夹（连接配置模板不在）。',
            '请重新解压完整的压缩包后再试。'
        )
    }

    # ---------- 1) 数据根:与 Electron 壳同语义(%APPDATA%\biyu-studio + runtime-production.json) ----------
    $dataRoot = Join-Path $env:APPDATA 'biyu-studio'
    New-Item -ItemType Directory -Path $dataRoot -Force | Out-Null
    $cfgDir = if ($env:BIYU_USER_CONFIG_DIR) { $env:BIYU_USER_CONFIG_DIR } else { Join-Path $env:USERPROFILE '.biyu' }
    New-Item -ItemType Directory -Path $cfgDir -Force | Out-Null
    $cfgPath = Join-Path $cfgDir 'runtime-production.json'
    $current = $null
    try { $current = Get-Content -LiteralPath $cfgPath -Raw -ErrorAction Stop | ConvertFrom-Json } catch { }
    if ($null -eq $current -or [string]$current.data_root -ne $dataRoot) {
        $payload = '{"data_root": ' + ($dataRoot | ConvertTo-Json) + '}'
        [System.IO.File]::WriteAllText($cfgPath, $payload, [System.Text.UTF8Encoding]::new($false))
    }

    # ---------- 2) 构建信息(packaging-version.json,由构建脚本写入) ----------
    $sha = 'unknown'; $buildDate = 'unknown'
    try {
        $v = Get-Content -LiteralPath (Join-Path $Root 'packaging-version.json') -Raw | ConvertFrom-Json
        if ($v.sha) { $sha = [string]$v.sha }
        if ($v.build) { $buildDate = [string]$v.build }
    } catch { }

    # ---------- 3) 单实例防多开:已跑的笔驭直接开浏览器聚焦,不再起第二个服务 ----------
    $Ports = 8765..8774
    function Test-BiyuAlive {
        param([int]$Port)
        try {
            $r = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$Port/api/version" -TimeoutSec 2
            return ($r.StatusCode -eq 200 -and $r.Content -match '"version"')
        } catch { return $false }
    }
    foreach ($p in $Ports) {
        if (Test-BiyuAlive -Port $p) {
            Write-Host "笔驭已经在运行了（端口 $p），不会再开第二个 —— 现在帮你打开浏览器。"
            Start-Process "http://127.0.0.1:$p/"
            exit 0
        }
    }
    function Test-PortFree {
        param([int]$Port)
        $listener = $null
        try {
            $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
            $listener.Start()
            return $true
        } catch { return $false }
        finally { if ($listener) { try { $listener.Stop() } catch { } } }
    }
    $port = 0
    foreach ($p in $Ports) { if (Test-PortFree -Port $p) { $port = $p; break } }
    if ($port -eq 0) {
        Stop-Fail @(
            '笔驭没有启动起来：本机 8765-8774 端口都被别的程序占用了。',
            '请关掉占用这些端口的程序（常见：别的本地服务），再重新双击「启动笔驭」。'
        )
    }

    # ---------- 4) 以 Electron 壳同一套 env 契约拉起 sidecar ----------
    $env:BIYU_ENV = 'prod'
    $env:BIYU_RUNTIME_ROLE = 'production'
    $env:BIYU_DATA_ROOT = $dataRoot
    $env:BIYU_DATA_ROOT_SOURCE = 'persistent'
    $env:BIYU_PRODUCTION_DATA_ROOT = $dataRoot
    $env:BIYU_PROJECT_ROOT = $Root
    $env:BIYU_CHECKOUT_NAME = 'biyu-studio'
    $env:BIYU_SHORT_SHA = $sha
    $env:BIYU_REMOTE_SLUG = 'guge0/biyu-studio'
    $env:BIYU_SEED_SAMPLE_BOOK = '1'
    $env:BIYU_SIDECAR_PORT = "$port"
    $env:BIYU_LAUNCH_MODE = 'browser_portable'
    $url = "http://127.0.0.1:$port/"

    # 浏览器自动打开:后台小进程轮询 /api/version,就绪即开默认浏览器(start_biyu_ui.ps1 同款做法)
    # 注意:URL 拼接先 TrimEnd('/'),否则 "http://…:8765/" + "/api/version" 变双斜杠 404,浏览器永远开不了。
    # 就绪后在 %TEMP% 落一个标记文件,便于排障时确认「自动打开」确实触发过。
    $poller = @('-NoProfile', '-WindowStyle', 'Hidden', '-Command',
        "`$u='$url'; `$p=`$u.TrimEnd('/'); for(`$i=0;`$i -lt 120;`$i++){try{Invoke-WebRequest -UseBasicParsing -Uri (`$p+'/api/version') -TimeoutSec 1 | Out-Null; Set-Content (Join-Path `$env:TEMP 'biyu-browser-opened.flag') 'ok'; Start-Process `$u; exit 0}catch{Start-Sleep -Milliseconds 500}}")
    Start-Process powershell.exe -WindowStyle Hidden -ArgumentList $poller | Out-Null

    Write-Host ''
    Write-Host '═══════════════════════════════════════════════'
    Write-Host '  笔驭 · 浏览器模式（便携）'
    Write-Host "  地址  : $url  （浏览器马上会自动打开）"
    Write-Host "  数据  : $dataRoot"
    Write-Host "  版本  : $buildDate · $sha"
    Write-Host '  说明  : 本机没有专用窗口组件，已自动切换为浏览器模式，功能一致。'
    Write-Host '          这个黑窗口是笔驭的「电源」，使用期间请别关；'
    Write-Host '          要退出就关掉它（或在本窗口按 Ctrl+C）。'
    Write-Host '═══════════════════════════════════════════════'
    Write-Host ''

    # 前台挂住:服务报错直接显示在本窗口;关窗/Ctrl+C 连带停掉服务,不留后台残留
    Push-Location -LiteralPath $Root
    try { & $exe } finally { Pop-Location }
    $code = $LASTEXITCODE
    if ($code -ne 0) {
        Stop-Fail @(
            "笔驭服务异常退出了（退出码 $code）。",
            '常见原因与建议：',
            '  1. 杀毒软件拦截了 biyu-sidecar.exe —— 把它加入信任区再试；',
            '  2. 端口被抢占 —— 重新双击一次会自动换端口；仍失败就重启电脑再试；',
            '  3. 程序文件损坏 —— 重新解压压缩包。'
        )
    }
} catch {
    Stop-Fail @(
        '启动器遇到未预期的错误：',
        "$($_.Exception.Message)",
        '请截图这个窗口，反馈给开发者。'
    )
}
