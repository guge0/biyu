from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_new_user_readme_has_complete_install_and_start_path() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")

    for required in (
        "https://github.com/guge0/biyu.git",
        "git clone",
        "安装笔驭.bat",
        "start_biyu_ui.bat",
        "Python 3.12",
        "Claude Code",
        "docs/images/",
        "BiyuData",
        "API Key",
        "本地加密文件",
    ):
        assert required in text


def test_author_launcher_uses_fixed_port_and_no_development_second_root() -> None:
    text = (ROOT / "start_biyu_ui.bat").read_text(encoding="utf-8")

    assert "-Port 8080" in text
    assert "-Mode" not in text
    assert "BIYU_DATA_ROOT_2" not in text
    assert "8080,1,8089" not in text
    for line in text.splitlines():
        if line.lstrip().upper().startswith("REM "):
            line.encode("ascii")


def test_public_entry_does_not_expose_local_deployment_topology() -> None:
    public_text = "\n".join(
        (ROOT / path).read_text(encoding="utf-8")
        for path in ("README.md", "start_biyu_ui.bat", "scripts/start_biyu_ui.ps1")
    )

    for forbidden in (
        r"D:\BiyuProductionData",
        r"E:\webnovel\BiyuTestData",
        "-Mode Production",
        "-Mode Test",
        "生产版与测试版",
    ):
        assert forbidden not in public_text
    assert not (ROOT / "start_biyu_ui_dev.bat").exists()


def test_installer_rejects_unsupported_python_with_human_message() -> None:
    text = (ROOT / "scripts" / "install_biyu.ps1").read_text(encoding="utf-8")

    assert "Python 3.10" in text
    assert "sys.version_info" in text
    assert "Get-FileHash" not in text
    assert "System.Security.Cryptography.SHA256" in text
    assert "function Get-SourceFingerprint" in text
    assert "Join-Path $repo 'src'" in text
    assert '$wantedState = "$head|$sourceHash"' in text
    venv_assignment = "$venvPython = Join-Path $repo '.venv\\Scripts\\python.exe'"
    existing_venv_gate = "if (-not (Test-Path -LiteralPath $venvPython)) {"
    assert text.index(venv_assignment) < text.index("Get-Command python")
    assert text.index(existing_venv_gate) < text.index("Get-Command python")


def test_installer_resolves_repository_root_from_scripts_directory() -> None:
    text = (ROOT / "scripts" / "install_biyu.ps1").read_text(encoding="utf-8")

    assert "$repo = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)" in text


def test_launcher_starts_current_checkout_without_install_refresh() -> None:
    launcher = (ROOT / "scripts" / "start_biyu_ui.ps1").read_text(encoding="utf-8")

    assert "install_biyu.ps1') -SkipPull -OnlyIfNeeded" not in launcher


def test_settings_write_requires_runtime_endpoint_and_persistent_author_data_root() -> None:
    bridge = (ROOT / "src" / "biyu" / "cli" / "settings_bridge.py").read_text(encoding="utf-8")
    config = (ROOT / "src" / "biyu" / "config.py").read_text(encoding="utf-8")
    launcher = (ROOT / "scripts" / "start_biyu_ui.ps1").read_text(encoding="utf-8")

    assert "PRODUCTION_SETTINGS_URL" not in bridge
    assert "BIYU_SETTINGS_EDITOR_URL" in bridge
    assert "BIYU_SETTINGS_DATA_ROOT" in bridge
    assert 'Path.home() / "BiyuData"' in config
    assert "Join-Path $HOME 'BiyuData'" not in launcher
    assert "biyu.runtime_config resolve --role production" in launcher
    assert "runtime-production.json" in (ROOT / "scripts" / "install_biyu.ps1").read_text(encoding="utf-8")
    assert "$env:BIYU_DATA_ROOT" in launcher
    assert "$env:BIYU_ENV = 'prod'" in launcher
    assert "D:\\BiyuProductionData" not in launcher
    assert "E:\\webnovel\\BiyuTestData" not in launcher


def test_development_launcher_imports_current_checkout_source() -> None:
    launcher = (ROOT / "scripts" / "start_biyu_dev.ps1").read_text(encoding="utf-8")
    assert "$env:PYTHONPATH = (Join-Path $projectRoot 'src')" in launcher
    assert "Stopping the existing development service" in launcher
    assert "runtime_guard.py" in launcher
    assert "$guardCode -eq 3" in launcher
    assert "owner.Path" not in launcher


def test_production_launcher_keeps_install_separate_and_uses_conflict_guard() -> None:
    launcher = (ROOT / "scripts" / "start_biyu_ui.ps1").read_text(encoding="utf-8")
    assert "runtime_guard.py" in launcher
    assert "-OnlyIfNeeded" not in launcher
