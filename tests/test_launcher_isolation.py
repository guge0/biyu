from pathlib import Path
import subprocess

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]


def test_windows_has_one_author_launcher() -> None:
    launcher = (ROOT / "start_biyu_ui.bat").read_text(encoding="utf-8")

    assert '-Port 8080' in launcher
    assert '-Mode' not in launcher
    assert not (ROOT / "start_biyu_ui_dev.bat").exists()
    assert "8080,1,8089" not in launcher
    assert "BIYU_DATA_ROOT_2" not in launcher


def test_shared_launcher_restarts_biyu_but_refuses_other_occupant_and_sets_environment() -> None:
    text = (ROOT / "scripts" / "start_biyu_ui.ps1").read_text(encoding="utf-8")

    assert "Test-NetConnection" not in text
    assert "Get-NetTCPConnection" in text
    assert "Existing Biyu service found" in text
    assert "Stop-Process -Id $listener.OwningProcess" in text
    assert "did not release port" in text
    assert "uvicorn\\s+biyu\\.ui\\.app:app" in text
    assert "Port $Port is occupied by another program" in text
    assert "exit 2" in text
    assert "$env:BIYU_ENV = 'prod'" in text
    assert "BIYU_RUNTIME_ROLE" in text
    assert "Production" not in text
    assert "Test mode" not in text
    assert "-File (Join-Path $projectRoot 'install_biyu.ps1') -SkipPull" in text


def test_version_endpoint_does_not_expose_internal_runtime_role(monkeypatch) -> None:
    import biyu.ui.app as app_module

    monkeypatch.setenv("BIYU_RUNTIME_ROLE", "production")
    assert TestClient(app_module.app).get("/api/version").json()["runtime"] == "笔驭"
    monkeypatch.setenv("BIYU_RUNTIME_ROLE", "test")
    assert TestClient(app_module.app).get("/api/version").json()["runtime"] == "笔驭"


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


def test_author_launcher_script_is_ascii_for_windows_powershell_5() -> None:
    script = ROOT / "scripts" / "start_biyu_ui.ps1"
    script.read_bytes().decode("ascii")
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-Port", "9999"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 2, result.stdout + result.stderr
    assert "Biyu uses port 8080" in result.stdout


def test_installer_checks_unchanged_state_before_network_pull() -> None:
    text = (ROOT / "install_biyu.ps1").read_text(encoding="utf-8-sig")
    assert text.index("if ($OnlyIfNeeded") < text.index("git pull --ff-only")
