"""S-3C 便携包自足启动契约(packaging/portable/ + make_portable.ps1 + electron 便携布局)。

锚定「解压即用、零前置」的静态契约:三级回落启动器、单实例防多开、_internal 自诊、
中文/空格路径、Electron 壳对便携平铺布局的识别、/api/version 的 launch_mode 通道。
真实双击走查证据见 _biyu交付记录/<日期>/S-3C/(工单验收以走查为准,单测只是回归闸)。
"""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PK = REPO / "packaging"
PORTABLE = PK / "portable"


def test_portable_launcher_sources_exist() -> None:
    for rel in ("启动笔驭.bat", "sidecar-launch.ps1"):
        assert (PORTABLE / rel).is_file(), f"missing portable launcher source: {rel}"
    assert (PK / "make_portable.ps1").is_file(), "missing make_portable.ps1"


def test_bat_three_level_fallback() -> None:
    text = (PORTABLE / "启动笔驭.bat").read_text(encoding="utf-8")
    # 一级:检测到 electron → 壳模式
    assert "where electron" in text
    assert "electron-shell" in text
    # 二级:无 electron → sidecar + 自动开浏览器(sidecar-launch.ps1)
    assert "sidecar-launch.ps1" in text
    # 三级:连 ps1 都缺(包被杀软拆了)也不闪退黑窗:人话 + pause
    assert "pause" in text
    # 中文与空格路径:控制台切 UTF-8 防中文乱码;根路径引用一律带引号
    assert "chcp 65001" in text
    assert '"%ROOT%' in text


def test_sidecar_launch_single_instance_and_diagnostics() -> None:
    text = (PORTABLE / "sidecar-launch.ps1").read_text(encoding="utf-8-sig")
    # 单实例防多开:先探测已跑实例,在跑就直接开浏览器,不再起第二个服务
    assert "Test-BiyuAlive" in text
    assert "已经在运行" in text
    # 包完整性自诊:exe/_internal 缺失给出杀软隔离/重新解压的人话建议
    assert "_internal" in text
    assert "杀毒软件" in text
    # env 契约与 Electron 壳(packaging/electron/main.js)对齐
    assert "BIYU_SIDECAR_PORT" in text
    assert "BIYU_DATA_ROOT" in text
    assert "BIYU_DATA_ROOT_SOURCE" in text
    assert "browser_portable" in text
    # 数据根与 Electron 壳同源:%APPDATA%\biyu-studio + runtime-production.json
    assert "biyu-studio" in text
    assert "runtime-production.json" in text
    # 起服务失败不闪退:人话报错 + 按回车才关窗
    assert "Read-Host" in text


def test_bat_bundles_portable_git_on_path() -> None:
    """零前置:干净机没有 git;包内 MinGit 必须被启动器提到 PATH 最前(建书/示例书依赖)。"""
    text = (PORTABLE / "启动笔驭.bat").read_text(encoding="utf-8")
    assert r"%ROOT%git\cmd\git.exe" in text
    assert 'set "PATH=%ROOT%git\\cmd;%PATH%"' in text


def test_make_portable_bundles_mingit() -> None:
    text = (PK / "make_portable.ps1").read_text(encoding="utf-8-sig")
    assert "MinGit" in text
    assert r"git\cmd\git.exe" in text


def test_browser_opener_polls_correct_url() -> None:
    """回归闸:曾因 URL 拼成 //api/version 404,浏览器「自动打开」从未触发。"""
    text = (PORTABLE / "sidecar-launch.ps1").read_text(encoding="utf-8-sig")
    assert "TrimEnd('/')" in text
    assert "biyu-browser-opened.flag" in text


def test_electron_shell_supports_portable_sibling_layout() -> None:
    text = (PK / "electron" / "main.js").read_text(encoding="utf-8")
    # 便携布局:electron-shell/ 源码目录旁边就是平铺的 sidecar onedir(exe 在包根)
    assert "path.join(here, '..', 'biyu-sidecar.exe')" in text


def test_make_portable_never_stages_private_models_yaml() -> None:
    text = (PK / "make_portable.ps1").read_text(encoding="utf-8-sig")
    # Key 红线与 build_sidecar.ps1 同款闸
    assert "FORBIDDEN: models.yaml must never be staged" in text
    # 便携包组装内容:启动器两件 + 壳源码 + 图标
    assert "启动笔驭.bat" in text
    assert "sidecar-launch.ps1" in text
    assert "笔驭.ico" in text


def test_version_api_carries_launch_mode() -> None:
    text = (REPO / "src" / "biyu" / "ui" / "app.py").read_text(encoding="utf-8")
    assert "launch_mode" in text
    assert "BIYU_LAUNCH_MODE" in text


def test_runtime_identity_marks_browser_portable() -> None:
    text = (REPO / "src" / "biyu" / "ui" / "static" / "runtime-identity.js").read_text(encoding="utf-8")
    assert "browser_portable" in text
    assert "浏览器模式（便携）" in text
