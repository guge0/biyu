from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import pytest
from fastapi.testclient import TestClient


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _fixture_book(data_root: Path) -> Path:
    book = data_root / "fixture-book"
    _write(
        book / "book.json",
        json.dumps(
            {
                "id": "fixture-book",
                "title": "只读合同测试书",
                "display_name": "只读合同测试书",
                "genre": "xuanhuan",
                "kind": "real",
            },
            ensure_ascii=False,
        ),
    )
    _write(book / "北极星.md", "# 北极星\n\n## 一句话故事\n守住不该变化的东西。\n")
    _write(book / "大纲.md", "# 大纲\n\n## 第一幕\n开门。\n")
    _write(
        book / "worldbook.yaml",
        "narrative_anchors:\n  基调: 克制\nfacts:\n  - 门不可响\npower_system: {}\n"
        "forbidden: []\ngeography: []\nfactions: []\ntimeline: []\n",
    )
    _write(
        book / "characters.yaml",
        "characters:\n  - name: 林舟\n    tier: protagonist\n    role: 保管人\n",
    )
    _write(book / "outlines/ch1.md", "# 第一章\n\n林舟开门。\n")
    _write(book / "chapters/_pending/ch1.md", "# 第一章\n\n门没有响。\n")
    _write(book / "logs/ch1/planning.md", "status: 已批\n方案正文。\n")
    _write(
        book / "logs/ch1/workbench_state.json",
        json.dumps({"step": "reading", "updated_at": "2026-08-17T10:00:00+00:00"}),
    )
    # A managed v1 plus an externally changed outline exposes read-time sync.
    _write(book / "logs/ch1/outlines/outline_v1.md", "# 第一章\n\n旧细纲。\n")
    _write(
        book / "logs/ch1/outlines/outline_v1.json",
        json.dumps({"version": 1, "created_at": "2026-08-16T10:00:00+00:00"}),
    )
    _write(book / "logs/ch1/outlines/current", "v1\n")
    _write(book / "summaries/纪要_20260817_1.md", "# 会诊纪要\n\n没有修改。\n")
    _write(
        book / "反馈账.jsonl",
        json.dumps(
            {
                "id": "good-1",
                "book": "fixture-book",
                "chapter": 1,
                "round": 1,
                "scope": "sentence",
                "action": "good",
                "text": "门没有响。",
                "candidate_sha": "fixture",
                "anchor": 1,
                "created_at": "2026-08-17T10:00:00+00:00",
            },
            ensure_ascii=False,
        )
        + "\n",
    )
    return book


def _disk_snapshot(root: Path) -> dict[str, tuple[str, int, int]]:
    result: dict[str, tuple[str, int, int]] = {}
    for path in [root, *sorted(root.rglob("*"), key=lambda item: str(item))]:
        stat = path.stat()
        relative = "." if path == root else path.relative_to(root).as_posix()
        result[relative] = (
            "dir" if path.is_dir() else "file",
            stat.st_size,
            stat.st_mtime_ns,
        )
    return result


@pytest.fixture
def readonly_app(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> tuple[TestClient, Path, Path, Path]:
    data_root = tmp_path / "data-root"
    data_root.mkdir()
    book = _fixture_book(data_root)
    backup_root = tmp_path / "backup-root"
    backup_root.mkdir()

    monkeypatch.setenv("BIYU_DATA_ROOT", str(data_root))
    monkeypatch.delenv("BIYU_DATA_ROOT_2", raising=False)
    monkeypatch.setenv("BIYU_BACKUP_ROOT", str(backup_root))

    import biyu.ui.settings as settings
    import biyu.ui.workbench as workbench
    from biyu.ui.app import app

    monkeypatch.setattr(workbench, "get_data_root", lambda: data_root)
    monkeypatch.setattr(workbench, "get_data_root_2", lambda: None)
    monkeypatch.setattr(settings, "feature_enabled", lambda _name: True)
    return TestClient(app), tmp_path, data_root, book


PAGE_READS: list[tuple[str, tuple[str, ...]]] = [
    (
        "书架",
        (
            "/api/version",
            "/api/backup/status?scope=production",
            "/api/session",
            "/api/books",
        ),
    ),
    (
        "工作台",
        (
            "/api/workbench/books",
            "/api/workbench/books/fixture-book/chapters/1",
            "/api/voiceprint/books/fixture-book",
        ),
    ),
    (
        "读稿页",
        ("/api/workbench/books/fixture-book/chapters/1",),
    ),
    (
        "设定集",
        ("/api/settings/books/fixture-book",),
    ),
    (
        "整书概览",
        (
            "/api/workbench/books",
            "/api/overview/books/fixture-book",
        ),
    ),
    (
        "纪要",
        (
            "/api/books",
            "/api/summaries?book=fixture-book",
            "/api/summaries/fixture-book/%E7%BA%AA%E8%A6%81_20260817_1.md",
        ),
    ),
    (
        "好句",
        (
            "/api/workbench/books",
            "/api/good-sentences/books/fixture-book",
        ),
    ),
]


@pytest.mark.parametrize(("page", "urls"), PAGE_READS, ids=[item[0] for item in PAGE_READS])
def test_opening_each_read_page_keeps_disk_identical(
    readonly_app: tuple[TestClient, Path, Path, Path],
    page: str,
    urls: tuple[str, ...],
) -> None:
    client, snapshot_root, _data_root, _book = readonly_app
    before = _disk_snapshot(snapshot_root)

    for url in urls:
        response = client.get(url)
        assert response.status_code == 200, f"{page} {url}: {response.text}"

    assert _disk_snapshot(snapshot_root) == before, f"{page} 只打开也改变了盘面"


@pytest.mark.parametrize(
    "reader_name",
    ["characters", "worldbook", "setup_asset_versions", "chapter_snapshot"],
)
def test_low_level_readers_never_materialize_versions(
    readonly_app: tuple[TestClient, Path, Path, Path],
    reader_name: str,
) -> None:
    _client, snapshot_root, _data_root, book = readonly_app
    from biyu.config import load_characters_yaml
    from biyu.setup_asset_versions import list_setup_asset_versions
    from biyu.ui.workbench import chapter_snapshot
    from biyu.worldbook import load_worldbook

    readers: dict[str, Callable[[], object]] = {
        "characters": lambda: load_characters_yaml(book),
        "worldbook": lambda: load_worldbook(book),
        "setup_asset_versions": lambda: list_setup_asset_versions(book),
        "chapter_snapshot": lambda: chapter_snapshot(book, 1, "fixture-book"),
    }
    before = _disk_snapshot(snapshot_root)

    readers[reader_name]()

    assert _disk_snapshot(snapshot_root) == before, f"{reader_name} 读取时改变了盘面"


def test_shelf_ui_contracts_are_explicit_and_not_browser_native() -> None:
    app_js = Path("src/biyu/ui/static/app.js").read_text(encoding="utf-8")
    index = Path("src/biyu/ui/static/index.html").read_text(encoding="utf-8")
    styles = Path("src/biyu/ui/static/styles.css").read_text(encoding="utf-8")

    assert 'createElement("details")' not in app_js
    assert 'createElement("summary")' not in app_js
    assert "aria-expanded" in app_js
    assert 'document.addEventListener("click"' in app_js

    assert "settings_ready" in app_js
    assert 'textContent = "去填设定"' in app_js
    assert 'textContent = "开始第 1 章"' in app_js
    assert "/settings.html?book=" in app_js
    assert '"&chapter=1"' in app_js

    nav_links = index.split('<div class="nav-links">', 1)[1].split("</div>", 1)[0]
    nav_badges = index.split('<div class="nav-badges">', 1)[1].split("</div>", 1)[0]
    assert 'id="connection-settings-button"' not in nav_links
    assert 'id="connection-settings-button"' in nav_badges

    assert ".continue-book-btn:visited" in styles
    visited_rule = styles.split(".continue-book-btn:visited", 1)[1].split("}", 1)[0]
    assert "color:var(--paper)" in visited_rule.replace(" ", "")
    more_focus = styles.split(".book-card .book-more-toggle:focus-visible", 1)[1].split("}", 1)[0]
    assert "var(--ink-soft)" in more_focus
    assert "var(--seal)" not in more_focus


def test_shelf_backend_exposes_settings_readiness_without_writing(
    readonly_app: tuple[TestClient, Path, Path, Path],
) -> None:
    client, snapshot_root, _data_root, _book = readonly_app
    before = _disk_snapshot(snapshot_root)

    response = client.get("/api/books")

    assert response.status_code == 200
    item = response.json()["books"][0]
    assert item["settings_filled_count"] == 4
    assert item["settings_required_count"] == 9
    assert item["settings_ready"] is False
    assert _disk_snapshot(snapshot_root) == before


def test_backup_status_has_real_settings_switch() -> None:
    source = Path("src/biyu/ui/static/backup-panel.js").read_text(encoding="utf-8")

    assert "/api/backup/settings" in source
    assert "backup-auto" in source
    assert "备份没有开 · 打开" in source
    assert "上次备份失败" in source
