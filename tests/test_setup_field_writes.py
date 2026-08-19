from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _book(tmp_path: Path) -> Path:
    book = tmp_path / "Book"
    book.mkdir()
    (book / "book.json").write_text(
        '{"id":"book-id","title":"Book","genre":"xuanhuan"}',
        encoding="utf-8",
    )
    return book


def test_worldbook_list_section_rejects_mapping_before_any_write(tmp_path: Path) -> None:
    from biyu.setup_asset_versions import SetupAssetYamlError, update_worldbook_section

    book = _book(tmp_path)
    path = book / "worldbook.yaml"
    before = b"# author note\nfacts:\n  - old fact\ngeography:\n  - old place\n"
    path.write_bytes(before)

    with pytest.raises(SetupAssetYamlError, match="设定事实.*逐条"):
        update_worldbook_section(book, "facts", {"wrong": "shape"})

    assert path.read_bytes() == before
    assert not (book / "logs").exists()


def test_worldbook_field_write_changes_target_and_snapshots_exact_bytes(tmp_path: Path) -> None:
    from biyu.setup_asset_versions import update_worldbook_section

    book = _book(tmp_path)
    path = book / "worldbook.yaml"
    before = b"# author note\nfacts:\n  - old fact\ngeography:\n  - old place # keep\n"
    path.write_bytes(before)

    update_worldbook_section(book, "facts", ["new fact"])

    after = path.read_text(encoding="utf-8")
    assert "new fact" in after
    assert "old place # keep" in after
    snapshot = book / "logs" / "setup_assets" / "worldbook" / "worldbook_v1.yaml"
    assert snapshot.read_bytes() == before


def test_characters_web_put_preserves_top_level_keys_and_comments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from biyu import config
    import biyu.db as db
    from biyu.ui.app import app

    book = _book(tmp_path)
    path = book / "characters.yaml"
    path.write_text(
        "# author note\nschema_version: 7 # keep top-level\n"
        "characters:\n  - name: Old\n    status: alive\n"
        "custom_registry:\n  keep: yes\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "get_data_root", lambda: tmp_path)
    monkeypatch.setattr(db, "init_db", lambda _book: None)
    monkeypatch.setattr(db, "sync_characters_from_yaml", lambda _book: (1, 1, 0))

    response = TestClient(app).put(
        "/api/books/Book/characters",
        json={"characters": [{"name": "New", "status": "alive"}]},
    )

    assert response.status_code == 200
    after = path.read_text(encoding="utf-8")
    assert "schema_version: 7 # keep top-level" in after
    assert "custom_registry:" in after and "keep: yes" in after
    assert "name: New" in after


def test_character_card_write_keeps_sibling_card_and_top_level_data(tmp_path: Path) -> None:
    from biyu.setup_asset_versions import update_character_card

    book = _book(tmp_path)
    path = book / "characters.yaml"
    path.write_text(
        "# author note\nschema_version: 7\ncharacters:\n"
        "  - name: Target\n    status: alive\n"
        "  - name: Sibling\n    status: alive # sibling comment\n"
        "custom_registry:\n  keep: yes\n",
        encoding="utf-8",
    )

    update_character_card(book, {"name": "Target", "status": "dead"})

    after = path.read_text(encoding="utf-8")
    assert "name: Target" in after and "status: dead" in after
    assert "name: Sibling" in after and "# sibling comment" in after
    assert "custom_registry:" in after and "keep: yes" in after


def test_character_field_patch_changes_only_target_card_fields(tmp_path: Path) -> None:
    from biyu.setup_asset_versions import update_character_fields

    book = _book(tmp_path)
    path = book / "characters.yaml"
    path.write_text(
        "# author note\nschema_version: 7\ncharacters:\n"
        "  - name: Target\n    status: alive\n    role: old\n"
        "  - name: Sibling\n    status: alive # sibling comment\n    role: keep\n"
        "custom_registry:\n  keep: yes\n",
        encoding="utf-8",
    )

    update_character_fields(book, "Target", {"status": "dead"})

    after = path.read_text(encoding="utf-8")
    assert "name: Target\n  status: dead\n  role: old" in after
    assert "name: Sibling\n  status: alive" in after
    assert "# sibling comment" in after and "role: keep" in after
    assert "custom_registry:" in after and "keep: yes" in after


def test_invalid_character_field_patch_has_zero_disk_effect(tmp_path: Path) -> None:
    from biyu.setup_asset_versions import SetupAssetYamlError, update_character_fields

    book = _book(tmp_path)
    path = book / "characters.yaml"
    before = b"characters:\n  - name: Target\n    aliases: {}\n"
    path.write_bytes(before)

    with pytest.raises(SetupAssetYamlError, match="称谓指引"):
        update_character_fields(book, "Target", {"aliases": []})

    assert path.read_bytes() == before
    assert not (book / "logs").exists()


def test_north_star_write_validates_then_snapshots_exact_bytes(tmp_path: Path) -> None:
    from biyu.setup_asset_versions import update_north_star_text

    book = _book(tmp_path)
    path = book / "北极星.md"
    before = "# 北极星 · 旧稿\n\n## 一句话故事\n旧故事。\n".encode()
    path.write_bytes(before)

    update_north_star_text(book, "# 北极星 · 新稿\n\n## 一句话故事\n新故事。\n")

    assert "新故事" in path.read_text(encoding="utf-8")
    snapshot = book / "logs" / "setup_assets" / "north_star" / "north_star_v1.md"
    assert snapshot.read_bytes() == before


def test_invalid_north_star_has_zero_disk_effect(tmp_path: Path) -> None:
    from biyu.setup_asset_versions import SetupAssetYamlError, update_north_star_text

    book = _book(tmp_path)
    path = book / "北极星.md"
    before = b"# North Star\n\nmissing required Chinese section\n"
    path.write_bytes(before)

    with pytest.raises(SetupAssetYamlError, match="一句话故事"):
        update_north_star_text(book, "# 北极星\n\n只有标题。\n")

    assert path.read_bytes() == before
    assert not (book / "logs").exists()


def test_cli_character_roundtrip_keeps_comments_and_unrelated_top_level_keys(
    tmp_path: Path,
) -> None:
    from biyu.cli.character_add import _load_characters, _save_characters

    book = _book(tmp_path)
    path = book / "characters.yaml"
    path.write_text(
        "# author note\nschema_version: 7\ncharacters:\n"
        "  - name: Old\n    status: alive # keep inline\n"
        "custom_registry:\n  keep: yes\n",
        encoding="utf-8",
    )

    data, characters = _load_characters(book)
    characters.append({"name": "New", "status": "alive"})
    _save_characters(book, data)

    after = path.read_text(encoding="utf-8")
    assert after.startswith("# author note\n")
    assert "# keep inline" in after
    assert "custom_registry:" in after and "keep: yes" in after
    assert "name: New" in after
