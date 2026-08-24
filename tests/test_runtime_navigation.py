from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient


STATIC = Path("src/biyu/ui/static")
PRODUCTION_PAGES = (
    "index.html",
    "book.html",
    "workbench.html",
    "memory.html",
    "overview.html",
    "voiceprint.html",
    "good-sentences.html",
    "summaries.html",
)


def _top_nav_links(page: str) -> list[tuple[str, str]]:
    html = (STATIC / page).read_text(encoding="utf-8")
    nav = re.search(r'<nav class="top-nav">.*?</nav>', html, re.DOTALL)
    assert nav is not None, page
    return [
        (text.strip(), href)
        for href, text in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>([^<]+)</a>', nav.group(0))
        if text.strip() != "笔驭"
    ]


def test_production_top_navigation_keeps_shelf_and_workbench_contract() -> None:
    for page in PRODUCTION_PAGES:
        links = _top_nav_links(page)
        labels = [text for text, _ in links]
        expected = ["书架", "工作台"]
        if page == "index.html":
            expected.append("介绍")
        if page in {"memory.html", "voiceprint.html"}:
            expected.append("声纹" if page == "memory.html" else "本书记忆")
        assert labels == expected, (page, links)
        assert links[0][1] == "/"
        assert links[1][1].startswith("/workbench.html")


def test_workbench_keeps_contextual_memory_and_voiceprint_paths() -> None:
    html = (STATIC / "workbench.html").read_text(encoding="utf-8")
    book = (STATIC / "book.html").read_text(encoding="utf-8")
    nav = re.search(r'<nav class="top-nav">.*?</nav>', html, re.DOTALL)
    assert nav is not None
    assert "/memory.html" not in nav.group(0)
    assert "/voiceprint.html" not in nav.group(0)
    assert 'id="memory-link"' not in html
    assert 'id="voiceprint-link"' not in html
    assert 'href="/memory.html?book=' in book
    assert 'href="/voiceprint.html?book=' in book
    assert "本书记忆" in book
    assert "本书声纹" in book


def test_workbench_1280_identity_row_grows_before_chapter_actions() -> None:
    css = (STATIC / "styles.css").read_text(encoding="utf-8")

    responsive = re.search(r"@media \(max-width:1280px\)\{(?P<body>.*?)\n\}", css, re.DOTALL)
    assert responsive is not None
    identity = re.search(
        r"\.workbench \.workbench-identity-row\{(?P<body>[^}]*)\}",
        responsive.group("body"),
    )
    assert identity is not None
    assert "height:auto" in identity.group("body")
    assert "min-height:0" in identity.group("body")


def test_shelf_create_book_is_two_fields_and_empty_state_is_local() -> None:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    form = re.search(r'<form id="create-book-form".*?</form>', html, re.DOTALL)
    assert form is not None
    assert form.group(0).count("<input") == 1
    assert form.group(0).count("<select") == 1
    assert "书名" in form.group(0)
    assert "题材" in form.group(0)
    assert 'id="create-book-empty-button"' in html
    assert "/propose.html" not in form.group(0)


def test_runtime_version_endpoint_and_visible_shelf_badge(monkeypatch) -> None:
    import biyu.ui.app as app_module

    monkeypatch.setattr(app_module.subprocess, "check_output", lambda *args, **kwargs: "00a7b752\n")
    response = TestClient(app_module.app).get("/api/version")
    assert response.status_code == 200
    payload = response.json()
    assert payload["version"] == "0.1.0"
    assert payload["build"] == "20260819 · 00a7b752"
    assert payload["runtime"] == "笔驭"
    assert payload["role"] == "笔驭"
    assert payload["checkout"] == "biyu-dev"
    assert payload["repo"] == "guge0/biyu"
    assert payload["sha"] == "00a7b752"

    html = (STATIC / "index.html").read_text(encoding="utf-8")
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    assert 'id="version-label"' in html
    assert 'fetch("/api/version")' in script
    assert "info.version" in script
    assert "info.checkout" not in script
    assert "info.data_root" in script
    assert "你的书存在：" in script
    assert 'id="data-root-location"' in html
    assert "版本无法确认" in script


def test_temporary_data_root_notice_keeps_prototype_regular_weight() -> None:
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    match = re.search(r"\.data-root-location\.temporary\s*\{(?P<body>[^}]*)\}", css)
    assert match is not None
    assert "font-weight: 400" in match.group("body")
    assert "font-weight: 600" not in match.group("body")


def test_production_version_reads_local_release_manifest_and_marks_update(
    monkeypatch, tmp_path: Path,
) -> None:
    import json
    import biyu.ui.app as app_module

    manifest = tmp_path / "published-version.json"
    manifest.write_text(json.dumps({"version": "0.2.0", "build": "20260823"}), encoding="utf-8")
    monkeypatch.setenv("BIYU_RUNTIME_ROLE", "production")
    monkeypatch.setenv("BIYU_RELEASE_MANIFEST", str(manifest))
    monkeypatch.setattr(app_module.subprocess, "check_output", lambda *args, **kwargs: "00a7b752\n")

    payload = TestClient(app_module.app).get("/api/version").json()
    assert payload["update_available"] is True
    assert payload["latest_version"] == "0.2.0"
    assert payload["update"] == {
        "available": True,
        "current": "0.1.0",
        "published": "0.2.0",
        "published_build": "20260823",
        "source": str(manifest),
    }


def test_development_version_does_not_show_production_update_red_dot(monkeypatch, tmp_path: Path) -> None:
    import json
    import biyu.ui.app as app_module

    manifest = tmp_path / "published-version.json"
    manifest.write_text(json.dumps({"version": "9.9.9"}), encoding="utf-8")
    monkeypatch.setenv("BIYU_RUNTIME_ROLE", "development")
    monkeypatch.setenv("BIYU_RELEASE_MANIFEST", str(manifest))
    payload = TestClient(app_module.app).get("/api/version").json()
    assert payload["update_available"] is False
    assert payload["update"]["published"] == "9.9.9"


def test_shelf_version_badge_has_update_dot_and_release_label() -> None:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    assert 'id="update-dot"' in html
    assert 'id="version-details"' in html
    assert 'id="version-current"' in html
    assert 'id="version-latest"' in html
    assert 'aria-expanded="false"' in html
    assert 'version-details' in script
    assert 'versionBadge' in script
    assert 'update.available' in script
    assert 'update-dot' in script
    assert ".update-dot" in css
    assert ".update-dot[hidden]" in css
