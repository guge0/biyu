from pathlib import Path
import subprocess

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]


def test_windows_launchers_have_fixed_distinct_modes_and_ports() -> None:
    production = (ROOT / "start_biyu_ui.bat").read_text(encoding="utf-8")
    test = (ROOT / "start_biyu_ui_dev.bat").read_text(encoding="utf-8")

    assert '-Mode Production -Port 8080' in production
    assert '-Mode Test -Port 8090' in test
    assert "8080,1,8089" not in production
    assert "BIYU_DATA_ROOT_2" not in production


def test_shared_launcher_refuses_occupied_port_and_sets_environment() -> None:
    text = (ROOT / "scripts" / "start_biyu_ui.ps1").read_text(encoding="utf-8")

    assert "Test-NetConnection" not in text
    assert "Get-NetTCPConnection" in text
    assert "exit 2" in text
    assert "$env:BIYU_ENV = 'prod'" in text
    assert "$env:BIYU_ENV = 'test'" in text
    assert "BIYU_RUNTIME_ROLE" in text
    assert "-File (Join-Path $projectRoot 'install_biyu.ps1') -SkipPull" in text


def test_version_endpoint_uses_explicit_runtime_role(monkeypatch) -> None:
    import biyu.ui.app as app_module

    monkeypatch.setenv("BIYU_RUNTIME_ROLE", "production")
    assert TestClient(app_module.app).get("/api/version").json()["runtime"] == "生产版"
    monkeypatch.setenv("BIYU_RUNTIME_ROLE", "test")
    assert TestClient(app_module.app).get("/api/version").json()["runtime"] == "测试版"


def test_installer_parses_in_windows_powershell_5() -> None:
    command = (
        "$tokens=$null;$errors=$null;"
        "[System.Management.Automation.Language.Parser]::ParseFile("
        f"'{ROOT / 'install_biyu.ps1'}',[ref]$tokens,[ref]$errors)|Out-Null;"
        "if($errors.Count){$errors|% Message;exit 1}"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_installer_checks_unchanged_state_before_network_pull() -> None:
    text = (ROOT / "install_biyu.ps1").read_text(encoding="utf-8-sig")
    assert text.index("if ($OnlyIfNeeded") < text.index("git pull --ff-only")
