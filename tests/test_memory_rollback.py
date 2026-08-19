from __future__ import annotations

import random

import pytest
from tests.support.workbench_assets import assert_workbench_js_src


def _shard(chapter: int, **values: str) -> dict:
    return {"chapter": chapter, "files": {"current_state.md": values}}


def test_merge_is_deterministic_and_chapter_order_overrides() -> None:
    from biyu.memory_projection import merge_machine_projection, serialize_projection

    shards = [_shard(2, hero="alive", place="city"), _shard(1, hero="hurt")]
    first = merge_machine_projection(shards, {1, 2})
    second = merge_machine_projection(shards, {1, 2})

    assert first["current_state.md"]["hero"] == "alive"
    assert first["current_state.md"]["place"] == "city"
    assert serialize_projection(first) == serialize_projection(second)


def test_merge_zero_llm() -> None:
    from biyu.memory_projection import merge_machine_projection

    class ExplodingAdapter:
        def generate(self, *_args, **_kwargs):  # pragma: no cover - must never run
            raise AssertionError("merge must not call an adapter")

    adapter = ExplodingAdapter()
    assert merge_machine_projection([_shard(1, hero="alive")], {1}, adapter=adapter)["current_state.md"]["hero"] == "alive"


def test_pin_survives_rebuild_and_unpin_restores_machine_value() -> None:
    from biyu.memory_projection import rebuild_memory

    shards = [_shard(1, hero="alive")]
    pinned = {"current_state.md:hero": {"value": "injured", "resolution": "keep"}}
    effective = rebuild_memory(shards, {1}, pinned)
    assert effective.values["current_state.md"]["hero"] == "injured"
    assert rebuild_memory(shards, {1}, {}).values["current_state.md"]["hero"] == "alive"


def test_conflict_is_surfaced_not_silent() -> None:
    from biyu.memory_projection import rebuild_memory

    result = rebuild_memory([_shard(1, hero="dead")], {1}, {"current_state.md:hero": {"value": "alive"}})
    assert result.values["current_state.md"]["hero"] == "alive"
    assert result.conflicts == [{"key": "current_state.md:hero", "machine": "dead", "pinned": "alive"}]


def test_memory_is_pure_function_for_random_operation_sequences() -> None:
    from biyu.memory_projection import rebuild_memory

    rng = random.Random(20260723)
    for _ in range(20):
        official: set[int] = set()
        pins: dict[str, dict[str, str]] = {}
        shards = [_shard(chapter, hero=f"state-{chapter}") for chapter in range(1, 6)]
        for _step in range(20):
            action = rng.choice(("adopt", "undo", "pin", "unpin"))
            chapter = rng.randint(1, 5)
            if action == "adopt":
                official.add(chapter)
            elif action == "undo":
                official.discard(chapter)
            elif action == "pin":
                pins["current_state.md:hero"] = {"value": f"manual-{chapter}", "resolution": "keep"}
            else:
                pins.pop("current_state.md:hero", None)
        result = rebuild_memory(shards, official, pins)
        assert result == rebuild_memory(shards, official, pins)


def test_undo_adopt_git_failure_restores_files(tmp_path) -> None:
    from biyu.cli import workbench_cmd as cmd

    book = tmp_path / "Book"
    (book / "chapters").mkdir(parents=True)
    (book / "chapters/ch1.md").write_text("current", encoding="utf-8")
    recycled = book / "logs/ch1/trash/official_old.md"
    recycled.parent.mkdir(parents=True)
    recycled.write_text("old", encoding="utf-8")
    with pytest.raises(RuntimeError, match="commit failed"):
        cmd._undo_adopt(
            book, 1,
            commit_fn=lambda *_: (_ for _ in ()).throw(RuntimeError("commit failed")),
            rebuild_runner=lambda *_: True,
            recycled=recycled,
        )
    assert (book / "chapters/ch1.md").read_text(encoding="utf-8") == "current"
    assert recycled.read_text(encoding="utf-8") == "old"
    assert not (book / "chapters/_pending/ch1.md").exists()


def test_undo_adopt_rebuild_failure_keeps_text_and_marks_dirty(tmp_path) -> None:
    from biyu.cli import workbench_cmd as cmd

    book = tmp_path / "Book"
    (book / "chapters").mkdir(parents=True)
    (book / "chapters/ch1.md").write_text("current", encoding="utf-8")
    trash = book / "logs/ch1/trash"
    trash.mkdir(parents=True)
    old = trash / "official_old.md"
    old.write_text("previous", encoding="utf-8")

    result = cmd._undo_adopt(book, 1, commit_fn=lambda *_: "abc", rebuild_runner=lambda *_: False, recycled=old)
    assert result.memory_updated is False
    assert (book / "chapters/ch1.md").read_text(encoding="utf-8") == "previous"
    assert (book / "chapters/_pending/ch1.md").read_text(encoding="utf-8") == "current"
    assert cmd.read_memory_dirty(book, 1) is True


def test_shard_is_readonly_and_missing_shard_repairs_only_that_chapter(tmp_path) -> None:
    from biyu.projections import read_shard, repair_missing_shards, write_shard

    book = tmp_path / "Book"
    write_shard(book, 1, {"chapter": 1, "files": {"current_state.md": {"hero": "alive"}}})
    before = (book / "truth_files/projections/ch1.yaml").read_bytes()
    with pytest.raises(FileExistsError):
        write_shard(book, 1, {"chapter": 1, "files": {"current_state.md": {"hero": "dead"}}})
    seen: list[int] = []
    repair_missing_shards(book, {1, 2, 3}, lambda chapter: seen.append(chapter) or {"chapter": chapter, "files": {}})
    assert seen == [2, 3]
    assert (book / "truth_files/projections/ch1.yaml").read_bytes() == before
    assert read_shard(book, 2)["chapter"] == 2


def test_pins_are_snapshotted_with_truth_history(tmp_path) -> None:
    from biyu.truth_files import pin_truth_entry, snapshot_truth_files

    book = tmp_path / "Book"
    (book / "truth_files").mkdir(parents=True)
    (book / "truth_files/current_state.md").write_text("state", encoding="utf-8")
    pin_truth_entry(book, "current_state.md", "hero", "alive")
    history = snapshot_truth_files(book, 1)
    assert (history / "pins.yaml").exists()
    assert 'current_state.md:hero' in (history / "pins.yaml").read_text(encoding="utf-8")
    assert list((book / "truth_files/history/pins").glob("pins_*.yaml"))


def test_repeated_adoption_selects_new_immutable_shard(tmp_path) -> None:
    from biyu.projections import read_shard, select_new_shard

    book = tmp_path / "Book"
    first = _shard(1, hero="alive")
    second = _shard(1, hero="hurt")
    original = select_new_shard(book, 1, first)
    original_bytes = original.read_bytes()
    selected = select_new_shard(book, 1, second)
    assert selected != original
    assert original.read_bytes() == original_bytes
    assert read_shard(book, 1)["files"]["current_state.md"]["hero"] == "hurt"


def test_undo_adopt_selects_restored_official_shard(tmp_path) -> None:
    import hashlib
    from biyu.cli import workbench_cmd as cmd
    from biyu.observer import replay_persisted_projections
    from biyu.projections import select_new_shard

    book = tmp_path / "Book"
    (book / "chapters").mkdir(parents=True)
    old_text, current_text = "old official", "current official"
    (book / "chapters/ch1.md").write_text(current_text, encoding="utf-8")
    trash = book / "logs/ch1/trash/official_old.md"
    trash.parent.mkdir(parents=True)
    trash.write_text(old_text, encoding="utf-8")
    select_new_shard(book, 1, {"chapter": 1, "official_sha256": hashlib.sha256(old_text.encode()).hexdigest(), "files": {"current_state.md": {"__whole__": "old memory"}}})
    select_new_shard(book, 1, {"chapter": 1, "official_sha256": hashlib.sha256(current_text.encode()).hexdigest(), "files": {"current_state.md": {"__whole__": "current memory"}}})
    result = cmd._undo_adopt(book, 1, commit_fn=lambda *_: "abc", rebuild_runner=lambda b, _c: replay_persisted_projections(b), recycled=trash)
    assert result.memory_updated is True
    assert (book / "truth_files/current_state.md").read_text(encoding="utf-8") == "old memory"


def test_undo_adopt_missing_matching_shard_is_loud(tmp_path) -> None:
    import hashlib
    import json
    from biyu.cli import workbench_cmd as cmd
    from biyu.observer import replay_persisted_projections
    from biyu.projections import write_shard

    book = tmp_path / "Book"
    (book / "chapters").mkdir(parents=True)
    (book / "chapters/ch1.md").write_text("new official", encoding="utf-8")
    trash = book / "logs/ch1/trash/official_old.md"
    trash.parent.mkdir(parents=True)
    trash.write_text("old official", encoding="utf-8")
    write_shard(
        book,
        1,
        {
            "chapter": 1,
            "official_sha256": hashlib.sha256(b"different official").hexdigest(),
            "files": {"current_state.md": {"state": "new"}},
        },
    )

    result = cmd._undo_adopt(
        book,
        1,
        commit_fn=lambda *_: "abc",
        rebuild_runner=lambda b, _c: replay_persisted_projections(b),
        recycled=trash,
    )

    assert result.memory_updated is False
    state = json.loads((book / "logs/ch1/memory_state.json").read_text(encoding="utf-8"))
    assert state["memory_dirty"] is True
    assert "匹配" in state["error"]


def test_memory_api_exposes_pin_and_conflict_actions(tmp_path, monkeypatch) -> None:
    from fastapi.testclient import TestClient
    import biyu.ui.workbench as wb
    from biyu.projections import write_shard
    from biyu.ui.app import app

    book = tmp_path / "Book"
    (book / "book.json").parent.mkdir(parents=True)
    (book / "book.json").write_text('{"id":"Book"}', encoding="utf-8")
    (book / "chapters").mkdir()
    (book / "chapters/ch1.md").write_text("official", encoding="utf-8")
    write_shard(book, 1, _shard(1, hero="dead"))
    monkeypatch.setattr(wb, "get_data_root", lambda: tmp_path)
    client = TestClient(app)

    pinned = client.put("/api/workbench/books/Book/memory/pins", json={"file": "current_state.md", "key": "hero", "value": "alive"})
    assert pinned.status_code == 200
    assert pinned.json()["entries"][0]["pinned"] is True
    assert pinned.json()["conflicts"][0]["machine"] == "dead"
    heard = client.post("/api/workbench/books/Book/memory/conflicts/resolve", json={"file": "current_state.md", "key": "hero", "choice": "machine"})
    assert heard.status_code == 200
    assert heard.json()["entries"][0]["value"] == "dead"


def test_memory_ui_has_pending_failure_and_conflict_controls() -> None:
    from pathlib import Path

    html = Path("src/biyu/ui/static/memory.html").read_text(encoding="utf-8")
    js = Path("src/biyu/ui/static/memory.js").read_text(encoding="utf-8")
    workbench = Path("src/biyu/ui/static/workbench.html").read_text(encoding="utf-8")
    assert 'id="error-banner"' in html and "error-banner-close" in js
    assert "保留我的" in js and "听正文的" in js and "已锚定" in js
    assert "disabled=true" in js and "finally" in js
    assert 'id="undo-adopt"' in workbench


def test_workbench_r5_script_has_fresh_cache_key() -> None:
    from pathlib import Path

    html = Path("src/biyu/ui/static/workbench.html").read_text(encoding="utf-8")
    js = Path("src/biyu/ui/static/workbench.js").read_text(encoding="utf-8")
    assert_workbench_js_src(html)
    assert "memoryLink.href = `/memory.html?book=${encodeURIComponent(selectedBook)}`" in js


def test_memory_page_recovers_missing_book_query() -> None:
    from pathlib import Path

    html = Path("src/biyu/ui/static/memory.html").read_text(encoding="utf-8")
    js = Path("src/biyu/ui/static/memory.js").read_text(encoding="utf-8")
    assert 'src="/memory.js?v=u1-1"' in html
    assert "setup.selected_book" in js
    assert "history.replaceState" in js
    assert "if(!book)" in js


def test_migration_repairs_only_missing_shards_and_rejects_real_book(tmp_path) -> None:
    import asyncio
    import importlib.util
    from biyu.projections import write_shard

    spec = importlib.util.spec_from_file_location("migrate_projections", "scripts/migrate_projections.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    book = tmp_path / "Isolated"
    (book / "chapters").mkdir(parents=True)
    for chapter in (1, 2):
        (book / f"chapters/ch{chapter}.md").write_text("official", encoding="utf-8")
    write_shard(book, 1, _shard(1, hero="alive"))
    seen = []
    async def repair(chapter, _official):
        seen.append(chapter)
        write_shard(book, chapter, _shard(chapter, hero="later"))
        return True, 0.02
    result = asyncio.run(module.migrate(book, repair))
    assert seen == [2] and result["repaired"] == [2] and result["cost"] == 0.02
    with pytest.raises(PermissionError):
        asyncio.run(module.migrate(tmp_path / "siwanghuisu", repair))
