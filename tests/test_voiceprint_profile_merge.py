from __future__ import annotations

import json
from pathlib import Path


def _line(line_id: str, dimension: str, text: str, *, source: str = "machine") -> dict:
    return {"id": line_id, "dimension": dimension, "text": text, "why": f"{text}的原因", "source": source}


def _profile(profile_id: str, name: str, lines: list[dict], *, kind: str) -> dict:
    return {"id": profile_id, "name": name, "kind": kind, "created_at": "2026-07-31T12:00:00+00:00", "lines": lines}


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_old_selected_order_migrates_deterministically_to_one_active(tmp_path: Path) -> None:
    from biyu.fingerprint.profile_state import load_profile_state, save_profile_state

    _write_json(tmp_path / "声纹/选择.json", {
        "selected": ["builtin:a", "import:b", "book:self"],
        "order": ["import:b", "builtin:a"],
    })
    assert load_profile_state(tmp_path)["active"] == "book:self"
    save_profile_state(tmp_path, "import:b")
    on_disk = json.loads((tmp_path / "声纹/选择.json").read_text(encoding="utf-8"))
    assert on_disk == {"active": "import:b"}


def test_old_state_without_self_uses_first_ordered_selected(tmp_path: Path) -> None:
    from biyu.fingerprint.profile_state import load_profile_state

    _write_json(tmp_path / "声纹/选择.json", {
        "selected": ["builtin:a", "import:b"],
        "order": ["import:b", "builtin:a"],
    })
    state = load_profile_state(tmp_path)
    assert state["active"] == "import:b"
    assert state["migrated_from_legacy"] is True
    assert json.loads((tmp_path / "声纹/选择.json").read_text(encoding="utf-8")) == {"active": "import:b"}


def test_writer_loads_only_active_profile_and_fixed_policy(tmp_path: Path) -> None:
    from biyu.fingerprint.library import load_merged_voiceprint
    from biyu.fingerprint.merge_policy import SYSTEM_USAGE_POLICY
    from biyu.fingerprint.profile_state import save_profile_state

    assets = tmp_path / "assets"
    _write_json(assets / "a.json", _profile("builtin:a", "A", [_line("a", "整体气质", "A规则")], kind="builtin"))
    _write_json(assets / "b.json", _profile("builtin:b", "B", [_line("b", "整体气质", "B规则")], kind="builtin"))
    save_profile_state(tmp_path, "builtin:b")
    loaded = load_merged_voiceprint(tmp_path, builtins_dir=assets)
    assert [item["id"] for item in loaded["profiles"]] == ["builtin:b"]
    assert [item["text"] for item in loaded["lines"]] == ["B规则"]
    assert "A规则" not in loaded["text"]
    assert all(rule in loaded["text"] for rule in SYSTEM_USAGE_POLICY)


def test_explicit_mechanical_combination_keeps_same_dimension_and_sources(tmp_path: Path, monkeypatch) -> None:
    import biyu.fingerprint.adapter as adapter
    from biyu.fingerprint.library import mechanically_combine_profiles, load_merged_voiceprint

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("机械合并不得调用模型")

    monkeypatch.setattr(adapter, "generate_json", forbidden)
    assets = tmp_path / "assets"
    _write_json(assets / "a.json", _profile("builtin:a", "A", [_line("a", "整体气质", "克制")], kind="builtin"))
    _write_json(assets / "b.json", _profile("builtin:b", "B", [_line("b", "整体气质", "热烈")], kind="builtin"))
    combined = mechanically_combine_profiles(tmp_path, ["builtin:a", "builtin:b"], "AB", builtins_dir=assets)
    assert [line["text"] for line in combined["lines"]] == ["克制", "热烈"]
    assert [line["source_profile"]["id"] for line in combined["lines"]] == ["builtin:a", "builtin:b"]
    assert len(combined["source_profiles"]) == 2
    loaded = load_merged_voiceprint(tmp_path, builtins_dir=assets)
    assert loaded["active_profile_id"] == combined["id"]


def test_combined_profile_reports_changed_source(tmp_path: Path) -> None:
    from biyu.fingerprint.library import mechanically_combine_profiles, load_catalog_with_status

    assets = tmp_path / "assets"
    first = _profile("builtin:a", "A", [_line("a", "整体气质", "克制")], kind="builtin")
    second = _profile("builtin:b", "B", [_line("b", "整体气质", "热烈")], kind="builtin")
    _write_json(assets / "a.json", first)
    _write_json(assets / "b.json", second)
    combined = mechanically_combine_profiles(tmp_path, ["builtin:a", "builtin:b"], "AB", builtins_dir=assets)
    assert next(item for item in load_catalog_with_status(tmp_path, assets) if item["id"] == combined["id"])["sources_stale"] is False
    first["lines"][0]["text"] = "已经变化"
    _write_json(assets / "a.json", first)
    assert next(item for item in load_catalog_with_status(tmp_path, assets) if item["id"] == combined["id"])["sources_stale"] is True


def test_manual_profile_is_author_owned_and_active(tmp_path: Path) -> None:
    from biyu.fingerprint.library import create_manual_profile, load_merged_voiceprint

    profile = create_manual_profile(tmp_path, "我的写法", [{"dimension": "对白", "text": "短句", "why": "留白"}])
    assert profile["lines"][0]["source"] == "author"
    assert load_merged_voiceprint(tmp_path, builtins_dir=tmp_path / "none")["active_profile_id"] == profile["id"]


def test_canonical_dimension_still_protects_author_edits(tmp_path: Path) -> None:
    from biyu.fingerprint.library import replace_machine_lines

    _write_json(tmp_path / "声纹/本书自蒸馏.json", _profile(
        "book:self", "本书自蒸馏",
        [_line("author", "句子长短与节奏偏好", "作者改过", source="author")],
        kind="book",
    ))
    profile = replace_machine_lines(tmp_path, [{"dimension": "句子长短与节奏", "text": "机器新稿"}])
    assert [line["text"] for line in profile["lines"]] == ["作者改过"]
