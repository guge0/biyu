from __future__ import annotations

import json
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
        if page in {"memory.html", "voiceprint.html"}:
            expected.append("声纹" if page == "memory.html" else "本书记忆")
        assert labels == expected, (page, links)
        assert links[0][1] == "/"
        assert links[1][1].startswith("/workbench.html")


def test_workbench_keeps_contextual_memory_and_voiceprint_paths() -> None:
    html = (STATIC / "workbench.html").read_text(encoding="utf-8")
    nav = re.search(r'<nav class="top-nav">.*?</nav>', html, re.DOTALL)
    assert nav is not None
    assert "/memory.html" not in nav.group(0)
    assert "/voiceprint.html" not in nav.group(0)
    assert 'id="memory-link" href="/memory.html"' in html
    assert 'id="voiceprint-link" href="/voiceprint.html"' in html


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

    class EditableDistribution:
        def read_text(self, name: str) -> str | None:
            assert name == "direct_url.json"
            return json.dumps({"dir_info": {"editable": True}})

    monkeypatch.setattr(app_module.metadata, "distribution", lambda _: EditableDistribution())
    monkeypatch.setattr(app_module.subprocess, "check_output", lambda *args, **kwargs: "00a7b752\n")
    response = TestClient(app_module.app).get("/api/version")
    assert response.status_code == 200
    payload = response.json()
    assert payload["version"] == "0.1.0"
    assert payload["build"] == "20260819 · 00a7b752"
    assert payload["runtime"] == "测试版"
    assert payload["role"] == "测试版"
    assert payload["checkout"] == "biyu-dev"
    assert payload["repo"] == "guge0/biyu"
    assert payload["sha"] == "00a7b752"

    html = (STATIC / "index.html").read_text(encoding="utf-8")
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    assert 'id="version-label"' in html
    assert 'fetch("/api/version")' in script
    assert "版本无法确认" in script


def test_non_editable_distribution_reports_production_wheel(monkeypatch) -> None:
    import biyu.ui.app as app_module

    class WheelDistribution:
        def read_text(self, name: str) -> str | None:
            assert name == "direct_url.json"
            return json.dumps({"archive_info": {"hash": "sha256=fixture"}})

    monkeypatch.setattr(app_module.metadata, "distribution", lambda _: WheelDistribution())
    response = TestClient(app_module.app).get("/api/version")
    assert response.json()["runtime"] == "生产版"
