from pathlib import Path

from fastapi.testclient import TestClient

from biyu.ui.app import app


ROOT = Path(__file__).resolve().parents[1]
LANDING = ROOT / "docs" / "index.html"


def test_shelf_keeps_about_entry_and_remains_homepage():
    html = (ROOT / "src" / "biyu" / "ui" / "static" / "index.html").read_text(encoding="utf-8")
    assert 'href="/about.html"' in html
    assert 'class="active"' in html and 'href="/"' in html
    assert '<h1>书架</h1>' in html


def test_about_route_serves_the_repository_landing_file_without_copy():
    response = TestClient(app).get("/about.html")
    assert response.status_code == 200
    assert 'src="/about-content.html"' in response.text
    assert 'aria-current="page">介绍</a>' in response.text
    content = TestClient(app).get("/about-content.html")
    assert content.status_code == 200
    assert content.text == LANDING.read_text(encoding="utf-8")
    assert not (ROOT / "src" / "biyu" / "ui" / "static" / "about.html").exists()


def test_about_route_explains_missing_landing_page(monkeypatch):
    import biyu.ui.app as app_module

    monkeypatch.setenv("BIYU_PROJECT_ROOT", str(ROOT / "missing-project"))
    response = TestClient(app_module.app).get("/about.html")
    assert response.status_code == 200
    assert "介绍页不在" in response.text
    assert "404" not in response.text


def test_landing_page_is_responsive_and_self_contained():
    text = LANDING.read_text(encoding="utf-8")
    assert 'name="viewport"' in text
    assert "http://" not in text and "https://" not in text
