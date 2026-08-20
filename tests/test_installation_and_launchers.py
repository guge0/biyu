from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_new_user_readme_has_complete_install_and_start_path() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")

    for required in (
        "https://github.com/guge0/biyu.git",
        "git clone",
        "安装笔驭.bat",
        "start_biyu_ui.bat",
        "GitHub",
        "Python 3.12",
        "D:\\BiyuProductionData",
        "E:\\webnovel\\BiyuTestData",
        "API Key",
        "本地加密文件",
    ):
        assert required in text


def test_author_launcher_uses_fixed_port_and_no_development_second_root() -> None:
    text = (ROOT / "start_biyu_ui.bat").read_text(encoding="utf-8")

    assert "-Mode Production -Port 8080" in text
    assert "BIYU_DATA_ROOT_2" not in text
    assert "8080,1,8089" not in text
    for line in text.splitlines():
        if line.lstrip().upper().startswith("REM "):
            line.encode("ascii")


def test_installer_rejects_unsupported_python_with_human_message() -> None:
    text = (ROOT / "install_biyu.ps1").read_text(encoding="utf-8")

    assert "Python 3.10" in text
    assert "sys.version_info" in text


def test_settings_write_requires_runtime_endpoint_and_uses_author_data_default() -> None:
    bridge = (ROOT / "src" / "biyu" / "cli" / "settings_bridge.py").read_text(encoding="utf-8")
    config = (ROOT / "src" / "biyu" / "config.py").read_text(encoding="utf-8")
    launcher = (ROOT / "scripts" / "start_biyu_ui.ps1").read_text(encoding="utf-8")

    assert "PRODUCTION_SETTINGS_URL" not in bridge
    assert "BIYU_SETTINGS_EDITOR_URL" in bridge
    assert "BIYU_SETTINGS_DATA_ROOT" in bridge
    assert 'Path.home() / "BiyuData"' in config
    assert "$env:BIYU_ENV = 'prod'" in launcher
    assert "$expectedPort = if ($Mode -eq 'Production') { 8080 } else { 8090 }" in launcher
