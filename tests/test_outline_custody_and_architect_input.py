"""Zero-cost guards for outline custody and Architect North Star input."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


def _book(root: Path, name: str = "N1Book") -> Path:
    book = root / name
    book.mkdir()
    (book / "book.json").write_text("{}", encoding="utf-8")
    return book


def _workbench_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from biyu.ui.app import app
    import biyu.ui.workbench as workbench

    monkeypatch.setattr(workbench, "get_data_root", lambda: tmp_path)
    return TestClient(app)


def test_outline_version_saved_on_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    book = _book(tmp_path)
    client = _workbench_client(tmp_path, monkeypatch)
    snapshot = client.get("/api/workbench/books/N1Book/chapters/1").json()

    response = client.put(
        "/api/workbench/books/N1Book/chapters/1/outline",
        json={"content": "作者第一版细纲", "base_sha": snapshot["outline_sha"]},
    )

    assert response.status_code == 200
    assert [item["content"] for item in response.json()["outline_versions"]] == ["作者第一版细纲"]
    assert (book / "logs/ch1/outlines/outline_v1.md").exists()


def test_outline_legacy_api_write_is_versioned(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from biyu.web.app import app
    import biyu.config as config
    import biyu.web.routes as routes
    from biyu.ui.workbench_versions import list_outline_versions

    book = _book(tmp_path)
    (book / "outlines").mkdir()
    (book / "outlines/ch1.md").write_text("旧接口前一版", encoding="utf-8")
    monkeypatch.setattr(config, "get_data_root", lambda: tmp_path)
    monkeypatch.setattr(routes, "get_data_root", lambda: tmp_path)

    response = TestClient(app).put(
        "/api/books/N1Book/chapters/1/outline", json={"content": "旧接口新一版"}
    )

    assert response.status_code == 200
    assert {item["content"] for item in list_outline_versions(book, 1)} == {"旧接口前一版", "旧接口新一版"}


def test_outline_external_write_waits_for_next_author_save(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    book = _book(tmp_path)
    client = _workbench_client(tmp_path, monkeypatch)
    first = client.get("/api/workbench/books/N1Book/chapters/1").json()
    client.put(
        "/api/workbench/books/N1Book/chapters/1/outline",
        json={"content": "作者原版", "base_sha": first["outline_sha"]},
    )

    # Simulates Claude Code or any other process that bypasses the HTTP API.
    outline = book / "outlines/ch1.md"
    outline.write_text("外部改写版", encoding="utf-8")
    after_external = client.get("/api/workbench/books/N1Book/chapters/1").json()
    assert {item["content"] for item in after_external["outline_versions"]} == {"作者原版"}

    saved = client.put(
        "/api/workbench/books/N1Book/chapters/1/outline",
        json={"content": "作者保存版", "base_sha": after_external["outline_sha"]},
    ).json()
    assert {"作者原版", "外部改写版", "作者保存版"} <= {
        item["content"] for item in saved["outline_versions"]
    }


def test_outline_restore_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    book = _book(tmp_path)
    client = _workbench_client(tmp_path, monkeypatch)
    first = client.get("/api/workbench/books/N1Book/chapters/1").json()
    saved = client.put(
        "/api/workbench/books/N1Book/chapters/1/outline",
        json={"content": "可恢复的原版", "base_sha": first["outline_sha"]},
    ).json()
    old_version = saved["outline_versions"][0]["version"]
    (book / "outlines/ch1.md").write_text("外部新版", encoding="utf-8")
    client.get("/api/workbench/books/N1Book/chapters/1")

    restored = client.post(
        f"/api/workbench/books/N1Book/chapters/1/outlines/{old_version}/select"
    )

    assert restored.status_code == 200
    assert (book / "outlines/ch1.md").read_text(encoding="utf-8") == "可恢复的原版"


class _ArchitectBoundary(Exception):
    pass


async def _capture_architect(messages, expected: str | None) -> None:
    combined = "\n".join(str(message.get("content", "")) for message in messages)
    if expected is not None:
        assert expected in combined
    raise _ArchitectBoundary()


async def _run_to_architect(book: Path, monkeypatch: pytest.MonkeyPatch, expected: str | None) -> None:
    import biyu.pipeline as pipeline

    (book / "outlines").mkdir(exist_ok=True)
    (book / "outlines/ch1.md").write_text("# 第一章\n测试细纲", encoding="utf-8")
    planner = MagicMock()
    registry = MagicMock()
    registry.get_pipeline_config.return_value = {"planner": "mock-planner"}
    registry.get_adapter_for_stage.return_value = planner
    registry.get_adapter.return_value = MagicMock()

    monkeypatch.setattr(pipeline, "get_registry", lambda: registry)
    monkeypatch.setattr(pipeline, "load_merged_voiceprint", lambda _: {"text": ""})
    monkeypatch.setattr(pipeline, "init_db", lambda _: None)
    monkeypatch.setattr(pipeline, "sync_characters_from_yaml", lambda _: (0, 0))
    monkeypatch.setattr(pipeline, "load_characters_yaml", lambda _: [])
    monkeypatch.setattr(pipeline, "_build_context_block", lambda *args: ("", None))
    monkeypatch.setattr(pipeline, "read_all_truth_files", lambda _: {})

    async def capture(messages, **kwargs):
        await _capture_architect(messages, expected)

    planner.generate_guarded = capture
    with pytest.raises(_ArchitectBoundary):
        await pipeline.generate_chapter(book, 1)


@pytest.mark.asyncio
async def test_north_star_reaches_architect_input(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    book = _book(tmp_path)
    (book / "北极星.md").write_text("北极星约束：结尾必须反转", encoding="utf-8")

    await _run_to_architect(book, monkeypatch, "北极星约束：结尾必须反转")


def test_north_star_prefers_book_local_then_legacy_docs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import biyu.pipeline as pipeline

    book = _book(tmp_path, "NorthStarBook")
    project = tmp_path / "project"
    legacy = project / "docs/北极星_NorthStarBook.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("旧稿北极星", encoding="utf-8")
    monkeypatch.setattr(pipeline, "get_project_root", lambda: project)

    assert pipeline._read_north_star(book) == ("旧稿北极星", "legacy_docs")
    (book / "北极星.md").write_text("书内北极星", encoding="utf-8")
    assert pipeline._read_north_star(book) == ("书内北极星", "book_local")


@pytest.mark.asyncio
async def test_missing_north_star_behavior(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    book = _book(tmp_path)

    await _run_to_architect(book, monkeypatch, None)

    output = capsys.readouterr().out
    assert "本书方向说明暂未找到；本次方案仍按其余资料生成。" in output
    assert "北极星.md" not in output


def test_skill_has_no_generation_command() -> None:
    canonical = Path(".claude/skills/daoyan/SKILL.md").read_text(encoding="utf-8")
    assert "biyu write" not in canonical
    assert "biyu auto" not in canonical
    for required in ("当前章细纲", "logs/chN/planning.md", "不写任何文件", "网页管线 architect"):
        assert required in canonical

    # 产品随附的 .claude skill 是唯一事实源。
    assert "`.claude/` 是本 skill 的唯一事实源" in canonical
