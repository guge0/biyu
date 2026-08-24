from pathlib import Path
import os
from datetime import date

from fastapi.testclient import TestClient
import hashlib
import re


def test_runtime_version_exposes_checkout_identity(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BIYU_RUNTIME_ROLE", "test")
    monkeypatch.setenv("BIYU_PROJECT_ROOT", str(Path.cwd()))
    monkeypatch.setenv("BIYU_DATA_ROOT", r"E:\webnovel\BiyuTestData")
    from biyu.ui import app as app_module

    monkeypatch.setattr(app_module.subprocess, "check_output", lambda *args, **kwargs: "00a7b752\n")

    payload = TestClient(app_module.app).get("/api/version").json()
    assert payload["role"] == "笔驭"
    assert payload["checkout"] == "biyu-dev"
    assert payload["repo"] == "guge0/biyu"
    assert payload["build"] == f"{date.today():%Y%m%d} · 00a7b752"
    assert payload["data_root"].endswith(r"BiyuTestData")


def test_settings_page_contains_runtime_identity_hook() -> None:
    html = Path("src/biyu/ui/static/settings.html").read_text(encoding="utf-8")
    script = Path("src/biyu/ui/static/runtime-identity.js").read_text(encoding="utf-8")
    assert 'id="runtime-identity"' in html
    assert "/runtime-identity.js?v=" in html
    assert "info.version" in script
    assert "info.checkout" not in script
    assert "info.data_root" not in script
    assert "update-dot" in script
    assert "update_available" in script


def test_dynamic_html_versions_match_current_asset_hashes() -> None:
    from biyu.ui import app as app_module

    pages = sorted(Path("src/biyu/ui/static").glob("*.html"))
    assert pages
    for page in pages:
        rendered = app_module.render_static_html(page)
        refs = re.findall(r'(?:src|href)="/([^"?]+)\?v=([^"]+)"', rendered)
        for name, version in refs:
            asset = Path("src/biyu/ui/static") / name
            assert asset.is_file(), (page.name, name)
            assert version == hashlib.sha256(asset.read_bytes()).hexdigest()[:8], (page.name, name)
