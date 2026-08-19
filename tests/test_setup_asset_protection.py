from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


def _book(tmp_path: Path, name: str = "Book") -> Path:
    book = tmp_path / name
    book.mkdir()
    (book / "book.json").write_text(
        '{"id":"book-id","title":"Book","genre":"xuanhuan"}',
        encoding="utf-8",
    )
    return book


def test_setup_assets_save_external_edit_and_restore_roundtrip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from biyu import setup_asset_versions as versions

    project = tmp_path / "project"
    docs = project / "docs"
    docs.mkdir(parents=True)
    book = _book(tmp_path)
    monkeypatch.setattr(versions, "get_project_root", lambda: project)
    originals = {
        "north_star": "# 北极星\n守住方向。\n",
        "book_outline": "# 大纲\n起承转合。\n",
        "worldbook": "# 作者注释\nnarrative_anchors:\n  tone: '冷'\n",
        "characters": "# 角色注释\ncharacters:\n  - name: 阿明\n    status: \"alive\"\n",
    }
    paths = {
        "north_star": book / "北极星.md",
        "book_outline": book / "大纲.md",
        "worldbook": book / "worldbook.yaml",
        "characters": book / "characters.yaml",
    }
    for asset_id, content in originals.items():
        paths[asset_id].write_text(content, encoding="utf-8")
        assert versions.sync_setup_asset_version(book, asset_id, reason="managed_read") == 1

    old = paths["worldbook"].read_bytes()
    paths["worldbook"].write_text("facts:\n  - 外部新版\n", encoding="utf-8")
    assert versions.sync_setup_asset_version(book, "worldbook", reason="managed_read") == 2
    restored = versions.restore_setup_asset_version(book, "worldbook", 1)
    assert restored == old
    assert paths["worldbook"].read_bytes() == old
    listed = versions.list_setup_asset_versions(book)
    worldbook = next(item for item in listed if item["asset_id"] == "worldbook")
    assert [item["version"] for item in worldbook["versions"]] == [2, 1]
    assert worldbook["versions"][1]["content"] == originals["worldbook"]


def test_legacy_north_star_has_separate_version_stream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from biyu import setup_asset_versions as versions

    project = tmp_path / "project"
    (project / "docs").mkdir(parents=True)
    book = _book(tmp_path)
    (book / "北极星.md").write_text("书内\n", encoding="utf-8")
    (project / "docs" / "北极星_Book.md").write_text("旧址\n", encoding="utf-8")
    monkeypatch.setattr(versions, "get_project_root", lambda: project)

    versions.sync_setup_asset_version(book, "north_star", reason="managed_read")
    versions.sync_setup_asset_version(book, "legacy_north_star", reason="managed_read")
    listed = {item["asset_id"]: item for item in versions.list_setup_asset_versions(book)}
    assert listed["north_star"]["versions"][0]["content"] == "书内\n"
    assert listed["legacy_north_star"]["versions"][0]["content"] == "旧址\n"


@pytest.mark.parametrize("sequence_indent", ["", "  "])
@pytest.mark.parametrize("line_ending", ["\n", "\r\n"])
def test_observer_status_roundtrip_changes_only_target_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sequence_indent: str, line_ending: str,
) -> None:
    from biyu import observer
    import biyu.db as db

    book = _book(tmp_path)
    truth = book / "truth_files"
    truth.mkdir()
    (truth / "current_state.md").write_text("李四已死。\n", encoding="utf-8")
    before = (
        "# 作者保留的角色顺序\n"
        "characters:\n"
        f"{sequence_indent}- name: '李四'\n"
        f"{sequence_indent}  role: \"supporting\"\n"
        f"{sequence_indent}  status: \"alive\" # 作者注释\n"
        f"{sequence_indent}  motto: '别动我'\n"
        f"{sequence_indent}- name: '王五'\n"
        f"{sequence_indent}  role: supporting\n"
        f"{sequence_indent}  status: alive\n"
    ).replace("\n", line_ending)
    (book / "characters.yaml").write_bytes(before.encode("utf-8"))
    monkeypatch.setattr(db, "sync_characters_from_yaml", lambda _book: (2, 2, 0))

    assert observer._sync_dead_characters(book) == 1
    after = (book / "characters.yaml").read_bytes().decode("utf-8")
    before_lines = before.splitlines()
    after_lines = after.splitlines()
    assert len(after_lines) == len(before_lines)
    target_index = next(index for index, line in enumerate(before_lines) if 'status: "alive"' in line)
    assert [line for index, line in enumerate(after_lines) if index != target_index] == [
        line for index, line in enumerate(before_lines) if index != target_index
    ]
    assert 'status: "dead"' in after_lines[target_index]
    assert "# 作者注释" in after_lines[target_index]
    assert after.count(line_ending) == before.count(line_ending)


def test_projection_restore_snapshots_author_edit_and_notifies(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    from biyu import observer
    from biyu.setup_asset_versions import list_setup_asset_versions, load_setup_restore_notice

    book = _book(tmp_path)
    (book / "truth_files").mkdir()
    current = "# 作者后改\ncharacters:\n  - name: 阿明\n    status: alive\n"
    base = "characters:\n  - name: 阿明\n    status: dead\n"
    (book / "characters.yaml").write_text(current, encoding="utf-8")
    base_dir = book / "truth_files" / "projection_base" / "ch1"
    base_dir.mkdir(parents=True)
    (base_dir / "characters.yaml").write_text(base, encoding="utf-8")

    observer._restore_or_create_projection_base(book, 1)

    versions = next(
        item["versions"] for item in list_setup_asset_versions(book)
        if item["asset_id"] == "characters"
    )
    assert any(item["content"] == current for item in versions)
    assert (book / "characters.yaml").read_text(encoding="utf-8") == base
    notice = load_setup_restore_notice(book)
    assert notice["active"] is True
    assert "版本" in notice["message"]
    assert "单章重算将恢复角色资料" in capsys.readouterr().out


def test_founding_restore_preserves_author_edit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """Preserve means the author bytes remain a recoverable version, not the current file."""
    from biyu import observer
    from biyu import setup_asset_versions as versions_module
    from biyu.setup_asset_versions import list_setup_asset_versions, load_setup_restore_notice

    if os.environ.get("O2_BREAK_FOUNDING_GUARD") == "1":
        monkeypatch.setattr(versions_module, "save_setup_asset_version", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(versions_module, "record_setup_restore_notice", lambda *_args, **_kwargs: {})

    book = _book(tmp_path)
    truth = book / "truth_files"
    truth.mkdir()
    author = "# 作者后改\ncharacters:\n  - name: 阿明\n    status: alive\n"
    founding = "characters:\n  - name: 阿明\n    status: unknown\n"
    (book / "characters.yaml").write_text(author, encoding="utf-8")
    (truth / "founding_characters.yaml").write_text(founding, encoding="utf-8")

    observer._reset_memory_projection(book)

    versions = next(
        item["versions"] for item in list_setup_asset_versions(book)
        if item["asset_id"] == "characters"
    )
    assert any(item["content"] == author for item in versions)
    assert (book / "characters.yaml").read_text(encoding="utf-8") == founding
    assert load_setup_restore_notice(book)["active"] is True
    assert "全书重建将恢复角色资料" in capsys.readouterr().out


def test_yaml_corruption_fails_before_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from biyu import pipeline
    from biyu.setup_asset_versions import SetupAssetYamlError

    book = _book(tmp_path)
    (book / "outlines").mkdir()
    (book / "outlines" / "ch1.md").write_text("人物: 阿明\n", encoding="utf-8")
    (book / "worldbook.yaml").write_text("facts:\n  - 正常\n  broken: [\n", encoding="utf-8")
    (book / "characters.yaml").write_text("characters: []\n", encoding="utf-8")

    class Registry:
        adapter_calls = 0

        def get_pipeline_config(self):
            return {"planner": "mock"}

        def get_adapter_for_stage(self, *_args, **_kwargs):
            self.adapter_calls += 1
            raise AssertionError("损坏 YAML 后不应取得 adapter")

    registry = Registry()
    monkeypatch.setattr(pipeline, "get_registry", lambda: registry)
    monkeypatch.setattr(pipeline, "load_merged_voiceprint", lambda _book: {"text": ""})
    if os.environ.get("O2_BREAK_YAML_PREFLIGHT") == "1":
        monkeypatch.setattr(pipeline, "load_worldbook", lambda _book: {})

    with pytest.raises(SetupAssetYamlError) as caught:
        asyncio.run(pipeline.generate_chapter(book, 1))
    message = str(caught.value)
    assert "worldbook.yaml" in message
    assert "第 3 行附近" in message
    assert "冒号、缩进或括号" in message
    assert "没有产生费用" in message
    assert registry.adapter_calls == 0


def test_setup_asset_book_api_restore_and_persistent_workbench_notice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import biyu.ui.workbench as workbench
    from biyu.setup_asset_versions import record_setup_restore_notice, update_worldbook_section
    from biyu.ui.app import app

    book = _book(tmp_path)
    (book / "worldbook.yaml").write_text("facts:\n  - v1\n", encoding="utf-8")
    monkeypatch.setattr(workbench, "get_data_root", lambda: tmp_path)
    client = TestClient(app)

    first = client.get("/api/workbench/books/book-id/setup-assets")
    assert first.status_code == 200
    assert next(item for item in first.json()["assets"] if item["asset_id"] == "worldbook")["versions"] == []
    update_worldbook_section(book, "facts", ["v2"], actor="作者")
    second = client.get("/api/workbench/books/book-id/setup-assets").json()
    versions = next(item for item in second["assets"] if item["asset_id"] == "worldbook")["versions"]
    assert [item["version"] for item in versions] == [2, 1]
    restored = client.post("/api/workbench/books/book-id/setup-assets/worldbook/versions/1/restore")
    assert restored.status_code == 200
    assert (book / "worldbook.yaml").read_text(encoding="utf-8") == "facts:\n  - v1\n"

    record_setup_restore_notice(book, version=2, reason="全书重建")
    snapshot = client.get("/api/workbench/books/book-id/chapters/1").json()
    assert snapshot["setup_restore_notice"]["active"] is True
    persisted = TestClient(app).get("/api/workbench/books/book-id/chapters/1").json()
    assert persisted["setup_restore_notice"]["active"] is True
    acknowledged = client.post("/api/workbench/books/book-id/setup-assets/notice/acknowledge")
    assert acknowledged.status_code == 200
    assert acknowledged.json()["active"] is False


def test_setup_asset_history_card_was_replaced_by_settings_page() -> None:
    book_html = Path("src/biyu/ui/static/book.html").read_text(encoding="utf-8")
    workbench_html = Path("src/biyu/ui/static/workbench.html").read_text(encoding="utf-8")
    workbench_js = Path("src/biyu/ui/static/workbench.js").read_text(encoding="utf-8")

    assert 'id="setup-assets-entry"' not in book_html
    assert 'id="setup-assets-panel"' not in book_html
    assert "立项资产历史" not in book_html
    assert "/settings.html?book=" in book_html
    assert "showPersistentError" in book_html
    assert "setup-assets" not in workbench_html
    assert 'id="setup-restore-notice"' in workbench_html
    assert "setup_restore_notice" in workbench_js
    assert "/book.html?book=" in workbench_js


def test_o2_dependency_and_migrated_usage_policy_import() -> None:
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    voice_test = Path("tests/test_voiceprint_workflow.py").read_text(encoding="utf-8")
    assert '"ruamel.yaml>=' in pyproject
    assert "from biyu.fingerprint.merge_policy import SYSTEM_USAGE_POLICY as production_policy" in voice_test
    assert "from biyu.fingerprint.library import SYSTEM_USAGE_POLICY" not in voice_test


def test_version_snapshot_uses_exact_bytes(tmp_path: Path) -> None:
    from biyu.setup_asset_versions import save_setup_asset_version

    book = _book(tmp_path)
    content = b"# comments\r\ncharacters:\r\n  - name: 'A'\r\n"
    (book / "characters.yaml").write_bytes(content)
    version = save_setup_asset_version(book, "characters", reason="before_write")
    snapshot = book / "logs" / "setup_assets" / "characters" / f"characters_v{version}.yaml"
    assert hashlib.sha256(snapshot.read_bytes()).digest() == hashlib.sha256(content).digest()


def test_setup_asset_version_records_actor_and_old_metadata_is_unknown(tmp_path: Path) -> None:
    import json

    from biyu.setup_asset_versions import list_setup_asset_versions, save_setup_asset_version

    book = _book(tmp_path)
    path = book / "characters.yaml"
    path.write_text("characters: []\n", encoding="utf-8")
    version = save_setup_asset_version(
        book, "characters", reason="editor_write", actor="责编",
    )
    assert version == 1
    listed = next(
        item for item in list_setup_asset_versions(book)
        if item["asset_id"] == "characters"
    )
    assert listed["versions"][0]["actor"] == "责编"

    meta_path = (
        book / "logs" / "setup_assets" / "characters" / "characters_v1.json"
    )
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    metadata.pop("actor")
    meta_path.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
    listed = next(
        item for item in list_setup_asset_versions(book)
        if item["asset_id"] == "characters"
    )
    assert listed["versions"][0]["actor"] == "未记录"


def test_cli_init_and_character_save_leave_versions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from biyu import config
    from biyu.cli import character_add, init_cmd
    from biyu.setup_asset_versions import list_setup_asset_versions

    class Stdout:
        def reconfigure(self, **_kwargs) -> None:
            return None

    monkeypatch.setattr(config, "get_data_root", lambda: tmp_path)
    monkeypatch.setattr(init_cmd.sys, "stdout", Stdout())
    monkeypatch.setattr(init_cmd.console, "print", lambda *_args, **_kwargs: None)
    init_cmd.init_command(title="NewBook", genre="xuanhuan")
    book = tmp_path / "NewBook"
    initial = next(
        item["versions"] for item in list_setup_asset_versions(book)
        if item["asset_id"] == "characters"
    )
    assert len(initial) == 1

    character_add._save_characters(book, {"characters": [{"name": "新人", "status": "alive"}]})
    after = next(
        item["versions"] for item in list_setup_asset_versions(book)
        if item["asset_id"] == "characters"
    )
    assert len(after) == 2
    assert any("新人" in item["content"] for item in after)


def test_old_characters_put_snapshots_before_and_after(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from biyu import config
    from biyu.setup_asset_versions import list_setup_asset_versions
    from biyu.ui.app import app

    book = _book(tmp_path)
    old = "# old\ncharacters:\n  - name: 旧人\n    status: alive\n"
    (book / "characters.yaml").write_text(old, encoding="utf-8")
    monkeypatch.setattr(config, "get_data_root", lambda: tmp_path)

    response = TestClient(app).put(
        "/api/books/Book/characters",
        json={"characters": [{"name": "新人", "status": "alive"}]},
    )
    assert response.status_code == 200
    versions = next(
        item["versions"] for item in list_setup_asset_versions(book)
        if item["asset_id"] == "characters"
    )
    assert any(item["content"] == old for item in versions)
    assert any("新人" in item["content"] for item in versions)


def test_characters_corruption_fails_before_pipeline_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from biyu import pipeline
    from biyu.setup_asset_versions import SetupAssetYamlError

    book = _book(tmp_path)
    (book / "outlines").mkdir()
    (book / "outlines" / "ch1.md").write_text("人物: 阿明\n", encoding="utf-8")
    (book / "worldbook.yaml").write_text("facts: []\n", encoding="utf-8")
    (book / "characters.yaml").write_text("characters:\n  - name: [\n", encoding="utf-8")

    class Registry:
        adapter_calls = 0

        def get_pipeline_config(self):
            return {"planner": "mock"}

        def get_adapter_for_stage(self, *_args, **_kwargs):
            self.adapter_calls += 1
            raise AssertionError("损坏 YAML 后不应取得 adapter")

    registry = Registry()
    monkeypatch.setattr(pipeline, "get_registry", lambda: registry)
    monkeypatch.setattr(pipeline, "load_merged_voiceprint", lambda _book: {"text": ""})
    with pytest.raises(SetupAssetYamlError) as caught:
        asyncio.run(pipeline.generate_chapter(book, 1))
    assert "characters.yaml" in str(caught.value)
    assert registry.adapter_calls == 0


def test_observer_validates_characters_before_model(tmp_path: Path) -> None:
    from biyu import observer
    from biyu.setup_asset_versions import SetupAssetYamlError

    book = _book(tmp_path)
    (book / "characters.yaml").write_text("characters:\n  - name: [\n", encoding="utf-8")

    class Adapter:
        calls = 0

        async def generate(self, _messages):
            self.calls += 1
            raise AssertionError("Observer must not call the model")

    adapter = Adapter()
    with pytest.raises(SetupAssetYamlError):
        asyncio.run(observer.update_truth_files(book, 1, "正文", adapter))
    assert adapter.calls == 0


def test_repaired_yaml_reaches_pipeline_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The paired green state: after fixing YAML, generation reaches the mock adapter."""
    from biyu import pipeline

    book = _book(tmp_path)
    (book / "outlines").mkdir()
    (book / "outlines" / "ch1.md").write_text("人物: 阿明\n", encoding="utf-8")
    (book / "worldbook.yaml").write_text("facts: []\n", encoding="utf-8")
    (book / "characters.yaml").write_text(
        "characters:\n  - name: 阿明\n    status: alive\n",
        encoding="utf-8",
    )

    planner = MagicMock()

    class Registry:
        adapter_calls = 0

        def get_pipeline_config(self):
            return {"planner": "mock"}

        def get_feature(self, name):
            return name == "planner_guard"  # 只走旧 planner_guard 挂载点

        def get_adapter_for_stage(self, *_args, **_kwargs):
            self.adapter_calls += 1
            return planner

        def get_adapter(self, *_args, **_kwargs):
            return MagicMock()

    registry = Registry()
    monkeypatch.setattr(pipeline, "get_registry", lambda: registry)
    monkeypatch.setattr(pipeline, "load_merged_voiceprint", lambda _book: {"text": ""})
    monkeypatch.setattr(pipeline, "init_db", lambda _book: None)
    monkeypatch.setattr(pipeline, "sync_characters_from_yaml", lambda _book: (0, 0))
    monkeypatch.setattr(pipeline, "_build_context_block", lambda *_args: ("", None))
    monkeypatch.setattr(pipeline, "read_all_truth_files", lambda _book: {})

    class ReachedAdapter(Exception):
        pass

    async def stop_at_adapter(_messages, **_kwargs):
        raise ReachedAdapter()

    planner.generate_guarded = stop_at_adapter
    with pytest.raises(ReachedAdapter):
        asyncio.run(pipeline.generate_chapter(book, 1))
    assert registry.adapter_calls == 1
