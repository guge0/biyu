from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _book(root: Path) -> Path:
    book = root / "Book"
    book.mkdir()
    (book / "book.json").write_text('{"id":"book-id","title":"长篇测试书"}', encoding="utf-8")
    (book / "北极星.md").write_text("# 北极星\n\n## 一句话故事\n旧故事。\n", encoding="utf-8")
    (book / "大纲.md").write_text("# 大纲\n\n## 第一幕\n旧内容。\n", encoding="utf-8")
    (book / "worldbook.yaml").write_text(
        "narrative_anchors:\n  基调: 克制\nfacts:\n  - 旧事实\npower_system: {}\n"
        "forbidden: []\ngeography: []\nfactions: []\ntimeline: []\n",
        encoding="utf-8",
    )
    (book / "characters.yaml").write_text(
        "characters:\n  - name: 林舟\n    tier: protagonist\n    role: 保管人\n    voice_examples:\n      - 你先坐。\n",
        encoding="utf-8",
    )
    return book


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, Path]:
    import biyu.ui.settings as settings
    import biyu.ui.workbench as workbench
    from biyu.ui.app import app

    book = _book(tmp_path)
    monkeypatch.setattr(workbench, "get_data_root", lambda: tmp_path)
    monkeypatch.setattr(settings, "feature_enabled", lambda _name: True)
    return TestClient(app), book


def test_feature_defaults_closed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import biyu.ui.settings as settings
    import biyu.ui.workbench as workbench
    from biyu.ui.app import app

    _book(tmp_path)
    monkeypatch.setattr(workbench, "get_data_root", lambda: tmp_path)
    monkeypatch.setattr(settings, "feature_enabled", lambda _name: False)
    response = TestClient(app).get("/api/settings/books/book-id")
    assert response.status_code == 404
    example = Path("config/models.yaml.example").read_text(encoding="utf-8")
    assert "  settings_page: true" in example


def test_zero_file_new_book_opens_as_nine_empty_cells_and_first_save_creates_asset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import biyu.ui.settings as settings
    import biyu.ui.workbench as workbench
    from biyu.ui.app import app

    book = tmp_path / "Fresh"
    book.mkdir()
    (book / "book.json").write_text('{"id":"fresh","title":"新书"}', encoding="utf-8")
    monkeypatch.setattr(workbench, "get_data_root", lambda: tmp_path)
    monkeypatch.setattr(settings, "feature_enabled", lambda _name: True)
    http = TestClient(app)

    opened = http.get("/api/settings/books/fresh")
    assert opened.status_code == 200, opened.text
    cells = opened.json()["cells"]
    assert len(cells) == 9
    assert all(cell["content"] == "" for cell in cells)
    assert not (book / "北极星.md").exists()

    north_star = next(cell for cell in cells if cell["id"] == "north_star")
    saved = http.put(
        "/api/settings/books/fresh/cells/north_star",
        json={
            "version": north_star["version"],
            "content": "# 北极星\n\n## 一句话故事\n从零开始。\n",
        },
    )
    assert saved.status_code == 200, saved.text
    assert (book / "北极星.md").read_text(encoding="utf-8").endswith("从零开始。\n")


def test_unparseable_paste_is_rejected_without_disk_write(client: tuple[TestClient, Path]) -> None:
    http, book = client
    before = (book / "北极星.md").read_bytes()
    response = http.post("/api/settings/books/book-id/preview", json={"content": "没有二级标题"})
    assert response.status_code == 405
    assert (book / "北极星.md").read_bytes() == before


def test_settings_history_displays_actor_with_legacy_fallback() -> None:
    script = Path("src/biyu/ui/static/settings.js").read_text(encoding="utf-8")
    assert "item.actor||'未记录'" in script


def test_worldbook_cell_save_changes_only_target_section(client: tuple[TestClient, Path]) -> None:
    http, book = client
    path = book / "worldbook.yaml"
    before = path.read_text(encoding="utf-8")
    snapshot = http.get("/api/settings/books/book-id").json()
    cell = next(item for item in snapshot["cells"] if item["id"] == "world_narrative_anchors")
    response = http.put(
        "/api/settings/books/book-id/cells/world_narrative_anchors",
        json={"version": cell["version"], "content": "## 基调\n新的克制基调。\n## 爽点\n迟到告别。\n"},
    )
    assert response.status_code == 200, response.text
    after = path.read_text(encoding="utf-8")
    assert "新的克制基调" in after
    assert "facts:\n  - 旧事实" in before and "facts:\n  - 旧事实" in after


def test_single_cell_save_rejects_stale_version_and_keeps_current_bytes(
    client: tuple[TestClient, Path],
) -> None:
    http, book = client
    snapshot = http.get("/api/settings/books/book-id").json()
    cell = next(item for item in snapshot["cells"] if item["id"] == "north_star")
    payload = {
        "version": cell["version"],
        "content": "# 北极星\n\n## 一句话故事\n第一位作者保存。\n",
    }
    assert http.put("/api/settings/books/book-id/cells/north_star", json=payload).status_code == 200
    current = (book / "北极星.md").read_bytes()
    stale = http.put(
        "/api/settings/books/book-id/cells/north_star",
        json={"version": cell["version"], "content": "# 北极星\n\n## 一句话故事\n过期覆盖。\n"},
    )
    assert stale.status_code == 409
    assert (book / "北极星.md").read_bytes() == current


def test_same_cell_saves_within_two_minutes_coalesce_one_history_version(
    client: tuple[TestClient, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    import biyu.ui.settings as settings

    http, _book_dir = client
    moments = iter([1000.0, 1050.0])
    monkeypatch.setattr(settings, "_now_seconds", lambda: next(moments))
    first = http.get("/api/settings/books/book-id").json()
    cell = next(item for item in first["cells"] if item["id"] == "book_outline")
    one = http.put(
        "/api/settings/books/book-id/cells/book_outline",
        json={"version": cell["version"], "content": "# 大纲\n\n## 第一幕\n一。\n"},
    ).json()
    two = http.put(
        "/api/settings/books/book-id/cells/book_outline",
        json={"version": one["cell"]["version"], "content": "# 大纲\n\n## 第一幕\n二。\n"},
    ).json()
    assert len(two["cell"]["history"]) == 1
    assert "旧内容。" in two["cell"]["history"][0]["content"]


def test_restore_cell_history_uses_current_version_guard(client: tuple[TestClient, Path]) -> None:
    http, book = client
    first = http.get("/api/settings/books/book-id").json()
    cell = next(item for item in first["cells"] if item["id"] == "book_outline")
    saved = http.put(
        "/api/settings/books/book-id/cells/book_outline",
        json={"version": cell["version"], "content": "# 大纲\n\n## 第一幕\n新内容。\n"},
    ).json()["cell"]
    stale = http.post(
        "/api/settings/books/book-id/cells/book_outline/history/0/restore",
        json={"version": cell["version"]},
    )
    assert stale.status_code == 409
    restored = http.post(
        "/api/settings/books/book-id/cells/book_outline/history/0/restore",
        json={"version": saved["version"]},
    )
    assert restored.status_code == 200, restored.text
    assert "旧内容。" in (book / "大纲.md").read_text(encoding="utf-8")


def test_character_archive_keeps_card_and_marks_it_archived(client: tuple[TestClient, Path]) -> None:
    http, book = client
    snapshot = http.get("/api/settings/books/book-id").json()
    card = next(item for item in snapshot["characters"] if item["name"] == "林舟")
    response = http.post(
        "/api/settings/books/book-id/characters/%E6%9E%97%E8%88%9F/archive",
        json={"version": card["version"]},
    )
    assert response.status_code == 200
    text = (book / "characters.yaml").read_text(encoding="utf-8")
    assert "name: 林舟" in text
    assert "archived: true" in text
    assert "archived: true" not in response.json()["character"]["history"][0]["content"]


def test_character_whole_card_save_removes_deleted_field_but_keeps_sibling(
    client: tuple[TestClient, Path],
) -> None:
    http, book = client
    path = book / "characters.yaml"
    path.write_text(
        "characters:\n  - name: 林舟\n    tier: protagonist\n    role: 旧定位\n"
        "    personality: 这段要删除\n  - name: 苏遥\n    tier: major_supporting\n    role: 保留\n",
        encoding="utf-8",
    )
    snapshot = http.get("/api/settings/books/book-id").json()
    card = next(item for item in snapshot["characters"] if item["name"] == "林舟")
    response = http.put(
        "/api/settings/books/book-id/characters/%E6%9E%97%E8%88%9F",
        json={
            "version": card["version"],
            "content": "## 人物卡\nname: 林舟\ntier: protagonist\nrole: 新定位\n",
        },
    )
    assert response.status_code == 200, response.text
    text = path.read_text(encoding="utf-8")
    assert "新定位" in text and "这段要删除" not in text
    assert "name: 苏遥" in text and "role: 保留" in text


def test_character_history_can_restore_without_deleting_sibling(
    client: tuple[TestClient, Path],
) -> None:
    http, book = client
    snapshot = http.get("/api/settings/books/book-id").json()
    card = next(item for item in snapshot["characters"] if item["name"] == "林舟")
    changed = http.put(
        "/api/settings/books/book-id/characters/%E6%9E%97%E8%88%9F",
        json={
            "version": card["version"],
            "content": "## 人物卡\nname: 林舟\ntier: protagonist\nrole: 新定位\n",
        },
    ).json()["character"]
    restored = http.post(
        "/api/settings/books/book-id/characters/%E6%9E%97%E8%88%9F/history/0/restore",
        json={"version": changed["version"]},
    )
    assert restored.status_code == 200, restored.text
    text = (book / "characters.yaml").read_text(encoding="utf-8")
    assert "role: 保管人" in text and "新定位" not in text


def test_worldbook_mapping_value_shape_roundtrips(client: tuple[TestClient, Path]) -> None:
    http, book = client
    path = book / "worldbook.yaml"
    path.write_text(
        "narrative_anchors:\n  复杂格:\n    要点:\n      - 一\n      - 二\nfacts:\n  - 保留\n",
        encoding="utf-8",
    )
    snapshot = http.get("/api/settings/books/book-id").json()
    cell = next(item for item in snapshot["cells"] if item["id"] == "world_narrative_anchors")
    assert "要点:" in cell["content"]
    saved = http.put(
        "/api/settings/books/book-id/cells/world_narrative_anchors",
        json={"version": cell["version"], "content": cell["content"]},
    )
    assert saved.status_code == 200, saved.text
    parsed = __import__("yaml").safe_load(path.read_text(encoding="utf-8"))
    assert parsed["narrative_anchors"]["复杂格"]["要点"] == ["一", "二"]


def test_settings_write_to_secondary_root_is_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import biyu.ui.settings as settings
    from biyu.ui.app import app

    prod = tmp_path / "prod"
    dev = tmp_path / "dev"
    prod.mkdir()
    dev.mkdir()
    _book(dev)
    monkeypatch.setenv("BIYU_DATA_ROOT", str(prod))
    monkeypatch.setenv("BIYU_DATA_ROOT_2", str(dev))
    monkeypatch.setattr(settings, "feature_enabled", lambda _name: True)
    response = TestClient(app).put(
        "/api/settings/books/book-id/cells/north_star",
        json={"version": "stale", "content": "# 北极星\n\n## 一句话故事\n不能写。\n"},
    )
    assert response.status_code == 403


def test_settings_static_page_has_required_floor_and_tier_copy() -> None:
    html = Path("src/biyu/ui/static/settings.html").read_text(encoding="utf-8")
    js = Path("src/biyu/ui/static/settings.js").read_text(encoding="utf-8")
    book = Path("src/biyu/ui/static/book.html").read_text(encoding="utf-8")
    main_start = book.index('class="entry-grid entry-grid-main"')
    sub_start = book.index('class="entry-grid entry-grid-sub"')
    main = book[main_start:sub_start]
    sub = book[sub_start:book.index("      // 组装", sub_start)]
    assert "设定集" in main and "/settings.html?book=" in main
    assert "整书概览" not in main and "整书概览" in sub
    assert "立项资产历史" not in book
    assert 'id="setup-assets-panel"' not in book
    assert "9 格 · 一格没填" in book and "9 格 · 已填 " in book
    assert "正在保存" in js and "button.disabled=true" in js
    assert "直接写这一格的内容" in html
    assert "修改已有内容时，旧版会自动进入历史" in html
    assert "切成了这" not in html and "previewSave" not in js
    assert "$('save-button').onclick=confirmSave" in js
    assert "每一章都整张读，包括说话的例句" in js
    assert "本章或上一章出场时整张读，不含说话的例句" in js
    assert "不进写手手里，只在这里留档" in js
    assert "正在读取本书设定" not in html
    assert "写手和导演每一章都会读这里" in html
    assert "设定没有读取成功" in js
    assert "服务还是旧版本" in js
    assert 'src="/settings.js?v=u2-1"' in html


def test_character_projection_has_five_human_sections_and_preserves_unmapped_fields(
    client: tuple[TestClient, Path],
) -> None:
    http, book = client
    path = book / "characters.yaml"
    path.write_text(
        "characters:\n  - name: 林舟\n    tier: protagonist\n    role: 保管人\n"
        "    background: 河边长大\n    personality: 克制\n"
        "    aliases:\n      narrator_default: 小舟\n      self_referent: 我\n"
        "      called_by:\n        母亲: 孩子\n"
        "    forbidden_in_narrative: [林先生]\n    voice_examples: [你先坐。]\n"
        "    status: alive\n    current_location: 旧桥\n"
        "    speaking_style: 短句\n    sample_lines: [旧台词]\n"
        "    tier_history:\n      - from_chapter: 1\n        reason: Q-5\n",
        encoding="utf-8",
    )
    card = next(item for item in http.get("/api/settings/books/book-id").json()["characters"] if item["name"] == "林舟")
    assert card["sections"]["基础"]["role"] == "保管人"
    assert card["sections"]["称谓"]["别人怎么叫他"] == {"母亲": "孩子"}
    assert card["state"]["current_location"] == "旧桥"
    assert card["other"]["speaking_style"] == "短句"
    assert "tier_history" not in card["other"]

    before = path.read_bytes()
    saved = http.put(
        "/api/settings/books/book-id/characters/%E6%9E%97%E8%88%9F",
        json={"version": card["version"], "fields": card["sections"]},
    )
    assert saved.status_code == 200, saved.text
    assert path.read_bytes() == before


def test_character_new_ui_round_trip_preserves_legacy_voice_string_bytes(
    client: tuple[TestClient, Path],
) -> None:
    http, book = client
    path = book / "characters.yaml"
    path.write_text(
        "characters:\n  - name: 林舟\n    tier: protagonist\n    role: 保管人\n"
        "    voice_examples: 你先坐。\n    speaking_style: 短句\n",
        encoding="utf-8",
    )
    before = path.read_bytes()
    card = next(
        item
        for item in http.get("/api/settings/books/book-id").json()["characters"]
        if item["name"] == "林舟"
    )

    assert card["sections"]["语声样本"] == ["你先坐。"]
    saved = http.put(
        "/api/settings/books/book-id/characters/%E6%9E%97%E8%88%9F",
        json={"version": card["version"], "fields": card["sections"]},
    )

    assert saved.status_code == 200, saved.text
    assert path.read_bytes() == before
    text = path.read_text(encoding="utf-8")
    for projection_key in ("sections:", "state:", "other:", "display_length:", "last_saved_at:"):
        assert projection_key not in text


def test_character_fields_reject_ui_projection_keys_without_writing(
    client: tuple[TestClient, Path],
) -> None:
    http, book = client
    path = book / "characters.yaml"
    before = path.read_bytes()
    card = next(
        item
        for item in http.get("/api/settings/books/book-id").json()["characters"]
        if item["name"] == "林舟"
    )
    fields = dict(card["sections"])
    fields["display_length"] = card["display_length"]

    saved = http.put(
        "/api/settings/books/book-id/characters/%E6%9E%97%E8%88%9F",
        json={"version": card["version"], "fields": fields},
    )

    assert saved.status_code == 400
    assert "只能保存五段中文内容" in saved.text
    assert path.read_bytes() == before


def test_character_fields_save_changes_only_mapped_fields_and_keeps_legacy_fields(
    client: tuple[TestClient, Path],
) -> None:
    http, book = client
    card = next(item for item in http.get("/api/settings/books/book-id").json()["characters"] if item["name"] == "林舟")
    saved = http.put(
        "/api/settings/books/book-id/characters/%E6%9E%97%E8%88%9F",
        json={
            "version": card["version"],
            "fields": {
                "基础": {"name": "林舟", "tier": "protagonist", "role": "新的定位"},
                "背景": "新的来历",
                "性格": "新的性格",
                "称谓": {"叙述者怎么称呼他": "小舟", "他怎么自称": "我", "别人怎么叫他": {}, "正文里不许用的称呼": []},
                "语声样本": ["新的台词"],
            },
        },
    )
    assert saved.status_code == 200, saved.text
    text = (book / "characters.yaml").read_text(encoding="utf-8")
    assert "role: 新的定位" in text and "background: 新的来历" in text
    assert "speaking_style" not in text


def test_character_fields_save_keeps_unmapped_alias_keys(client: tuple[TestClient, Path]) -> None:
    http, book = client
    path = book / "characters.yaml"
    path.write_text(
        "characters:\n  - name: 林舟\n    tier: protagonist\n    aliases:\n"
        "      narrator_default: 小舟\n      self_referent: 我\n"
        "      called_by: {}\n      private_alias: 内部检索名\n",
        encoding="utf-8",
    )
    card = next(item for item in http.get("/api/settings/books/book-id").json()["characters"] if item["name"] == "林舟")
    response = http.put(
        "/api/settings/books/book-id/characters/%E6%9E%97%E8%88%9F",
        json={"version": card["version"], "fields": card["sections"]},
    )
    assert response.status_code == 200, response.text
    assert "private_alias: 内部检索名" in path.read_text(encoding="utf-8")


def test_character_delete_has_recoverable_restore_route(client: tuple[TestClient, Path]) -> None:
    http, book = client
    card = next(item for item in http.get("/api/settings/books/book-id").json()["characters"] if item["name"] == "林舟")
    deleted = http.post(
        "/api/settings/books/book-id/characters/%E6%9E%97%E8%88%9F/archive",
        json={"version": card["version"]},
    )
    assert deleted.status_code == 200
    current = deleted.json()["character"]
    restored = http.post(
        "/api/settings/books/book-id/characters/%E6%9E%97%E8%88%9F/restore",
        json={"version": current["version"]},
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["character"]["archived"] is False
    assert "archived: true" not in book.joinpath("characters.yaml").read_text(encoding="utf-8")


def test_settings_static_page_uses_human_character_copy_without_native_dialogs() -> None:
    html = Path("src/biyu/ui/static/settings.html").read_text(encoding="utf-8")
    js = Path("src/biyu/ui/static/settings.js").read_text(encoding="utf-8")
    assert "这一章没出场的人，写手只看到一行：姓名、档位、一句话定位。" in html
    assert "return{'基础':{name:get('姓名'),tier:" in js
    assert "'背景':get('背景'),'性格':get('性格'),'称谓':" in js
    assert "'语声样本':voice}" in js
    assert "input('正文里不许用的称呼',forbidden,'textarea')" in js
    assert "每一章都整张读，包括说话的例句" in js
    assert "这一格现有" not in js
    assert "每章全量进写手上下文" not in html + js
    assert "confirm(" not in js
    assert "归档人物卡" not in html + js
    assert "删掉这张卡" in html + js
    assert "还没有人物卡。" in js
    assert "写手和导演每章都会读这里——先建一张主角的卡。" in js
    assert "setRosterChrome(true)" in js
    assert "startCreateCharacter" in js
    assert "renderCharacterEditor(current.data,{isNew:true})" in js
    assert "method:'POST'" in js
    assert "data-name-error" in js
    assert "showNameError(exc.message" in js
    assert "!Object.keys(value).length" in js
    assert "creatingCharacter?showRoster():showEdit()" in js
    assert "new-character.js" not in html
    assert "new-character.css" not in html
    assert "showModal" not in html + js
    assert "<dialog" not in html


def test_author_character_create_is_explicit_and_rejects_duplicates(
    client: tuple[TestClient, Path],
) -> None:
    http, book = client
    fields = {
        "基础": {"name": "新人物", "tier": "protagonist", "role": ""},
        "背景": "",
        "性格": "",
        "称谓": {},
        "语声样本": [],
    }

    created = http.post(
        "/api/settings/books/book-id/characters",
        json={"fields": fields},
    )
    assert created.status_code == 200, created.text
    assert created.json()["character"]["name"] == "新人物"

    duplicate = http.post(
        "/api/settings/books/book-id/characters",
        json={"fields": fields},
    )
    assert duplicate.status_code == 409
    assert "同名人物卡" in duplicate.json()["detail"]

    before = (book / "characters.yaml").read_bytes()
    missing_update = http.put(
        "/api/settings/books/book-id/characters/打错的名字",
        json={"version": "missing", "fields": fields},
    )
    assert missing_update.status_code == 404
    assert (book / "characters.yaml").read_bytes() == before
