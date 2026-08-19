from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from biyu.cli.workbench_cmd import _undo_adopt
from biyu.importer import (
    ImportConflict,
    import_manuscripts,
    preview_import,
    preview_memory,
)
from biyu.importer.workbench import chapter_origin, items_from_explicit_text


TRUTH_NAMES = ("current_state.md", "particle_ledger.md", "pending_hooks.md")


def _truth_snapshot(book: Path) -> dict[str, tuple[int, str]]:
    result = {}
    for name in TRUTH_NAMES:
        path = book / "truth_files" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(f"{name} baseline\n", encoding="utf-8")
        result[name] = (path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest())
    return result


def test_import_requires_identity(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="身份"):
        preview_import(tmp_path, [{"chapter": 1, "content": "正文", "identity": ""}])


def test_import_candidate_no_observer(tmp_path: Path) -> None:
    before = _truth_snapshot(tmp_path)
    result = import_manuscripts(
        tmp_path,
        [{"chapter": 1, "content": "候选正文", "identity": "candidate", "source": "paste"}],
    )
    assert (tmp_path / "chapters/_pending/ch1.md").read_text(encoding="utf-8") == "候选正文"
    assert result[0]["identity"] == "candidate"
    assert _truth_snapshot(tmp_path) == before


def test_import_official_no_observer_and_origin_in_meta(tmp_path: Path) -> None:
    before = _truth_snapshot(tmp_path)
    import_manuscripts(
        tmp_path,
        [{"chapter": 2, "content": "正式正文", "identity": "official", "source": "ch02.md"}],
    )
    official = tmp_path / "chapters/ch2.md"
    meta = json.loads((tmp_path / "logs/ch2/meta.json").read_text(encoding="utf-8"))
    assert official.read_text(encoding="utf-8") == "正式正文"
    assert "origin" not in official.read_text(encoding="utf-8")
    assert meta["origin"] == "imported"
    assert meta["imported_from"] == "ch02.md"
    assert _truth_snapshot(tmp_path) == before


def test_import_overwrite_goes_to_trash_and_can_restore(tmp_path: Path) -> None:
    official = tmp_path / "chapters/ch1.md"
    official.parent.mkdir(parents=True)
    official.write_text("旧正文", encoding="utf-8")
    items = [{"chapter": 1, "content": "新正文", "identity": "official", "source": "paste"}]
    with pytest.raises(ImportConflict):
        import_manuscripts(tmp_path, items)
    import_manuscripts(tmp_path, items, confirmed=True)
    trash = list((tmp_path / "logs/ch1/trash").glob("official_import_*.md"))
    assert len(trash) == 1
    assert trash[0].read_text(encoding="utf-8") == "旧正文"


def test_batch_import_zero_llm(tmp_path: Path) -> None:
    result = import_manuscripts(
        tmp_path,
        [
            {"chapter": 1, "content": "第一章", "identity": "candidate", "source": "a.md"},
            {"chapter": 2, "content": "第二章", "identity": "candidate", "source": "b.md"},
        ],
    )
    assert [item["chapter"] for item in result] == [1, 2]
    assert "adapter" not in Path(__import__("biyu.importer", fromlist=["*"]).__file__).read_text(encoding="utf-8").lower()


def test_import_never_calls_activate_chapters(tmp_path: Path, monkeypatch) -> None:
    from biyu.importer import splitter

    monkeypatch.setattr(
        splitter,
        "activate_chapters",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("legacy activation called")),
    )
    import_manuscripts(
        tmp_path,
        [{"chapter": 1, "content": "正文", "identity": "official", "source": "paste"}],
    )
    assert (tmp_path / "chapters/ch1.md").exists()


def test_import_reuses_splitter(monkeypatch) -> None:
    from biyu.importer import workbench
    from biyu.importer.splitter import Chapter, SplitResult

    calls = []
    monkeypatch.setattr(
        workbench,
        "split_text",
        lambda text: calls.append(text) or SplitResult(
            volume=None,
            chapters=[Chapter(7, "标题", "正文\n", 1, 2)],
        ),
    )
    items = items_from_explicit_text("第7章 标题\n正文", identity="candidate")
    assert calls == ["第7章 标题\n正文"]
    assert items == [{
        "chapter": 7,
        "content": "第7章 标题\n正文",
        "identity": "candidate",
        "source": "paste",
    }]


def test_missing_origin_is_unknown(tmp_path: Path) -> None:
    assert chapter_origin(tmp_path, 1) == "unknown"
    meta = tmp_path / "logs/ch1/meta.json"
    meta.parent.mkdir(parents=True)
    meta.write_text('{"origin":"generated"}', encoding="utf-8")
    assert chapter_origin(tmp_path, 1) == "generated"


def test_splitter_module_unmodified() -> None:
    result = subprocess.run(
        ["git", "diff", "--exit-code", "--", "src/biyu/importer/splitter.py"],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_build_memory_previews_first_chapter(tmp_path: Path) -> None:
    for chapter in (1, 2):
        path = tmp_path / "chapters" / f"ch{chapter}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"第{chapter}章", encoding="utf-8")
    calls: list[int] = []

    def build_one(chapter: int, official: Path) -> dict:
        calls.append(chapter)
        return {
            "chapter": chapter,
            "official_sha256": hashlib.sha256(official.read_bytes()).hexdigest(),
            "files": {"current_state.md": {"地点": f"第{chapter}章地点"}},
        }

    result = preview_memory(tmp_path, [1, 2], build_one)
    assert calls == [1]
    assert result["preview_chapter"] == 1
    assert result["remaining"] == [2]
    assert result["calls"] == 2


def test_imported_official_can_be_undone(tmp_path: Path) -> None:
    import_manuscripts(
        tmp_path,
        [{"chapter": 1, "content": "导入正文", "identity": "official", "source": "paste"}],
    )
    result = _undo_adopt(
        tmp_path,
        1,
        commit_fn=lambda *_: "commit",
        rebuild_runner=lambda *_: True,
    )
    assert result.memory_updated is True
    assert (tmp_path / "chapters/_pending/ch1.md").read_text(encoding="utf-8") == "导入正文"
    assert not (tmp_path / "chapters/ch1.md").exists()


def test_import_api_keeps_identity_origin_and_truth_isolated(tmp_path: Path, monkeypatch) -> None:
    from biyu.ui import app as ui_app
    from biyu.ui import workbench

    book = tmp_path / "fixture"
    book.mkdir()
    before = _truth_snapshot(book)
    monkeypatch.setattr(workbench, "get_data_root", lambda: tmp_path)
    client = TestClient(ui_app.app)
    preview = client.post(
        "/api/workbench/books/fixture/imports/preview",
        json={"chapter": 4, "text": "导入候选", "identity": "candidate", "source": "paste"},
    )
    assert preview.status_code == 200
    assert preview.json()["items"][0]["identity"] == "candidate"
    committed = client.post(
        "/api/workbench/books/fixture/imports",
        json={"chapter": 4, "text": "导入候选", "identity": "candidate", "source": "paste"},
    )
    assert committed.status_code == 200
    assert committed.json()["llm_calls"] == 0
    assert (book / "chapters/_pending/ch4.md").read_text(encoding="utf-8") == "导入候选"
    assert chapter_origin(book, 4) == "imported"
    assert _truth_snapshot(book) == before
