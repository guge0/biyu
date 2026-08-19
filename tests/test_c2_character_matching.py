from __future__ import annotations

from pathlib import Path
import json

import yaml

from biyu.prompts.chapter_writer import resolve_present_characters


def _character(
    name: str,
    *,
    tier: str = "supporting",
    narrator_default: str = "",
    called_by: dict[str, str] | None = None,
) -> dict:
    aliases: dict[str, object] = {"self_referent": "我"}
    if narrator_default:
        aliases["narrator_default"] = narrator_default
    if called_by:
        aliases["called_by"] = called_by
    return {
        "name": name,
        "tier": tier,
        "status": f"{name}当前状态",
        "aliases": aliases,
    }


def test_alias_exact_match_resolves_to_character_card() -> None:
    characters = [_character("林舟", narrator_default="小舟")]

    result = resolve_present_characters(["小舟"], characters)

    assert result.matched_names == ["林舟"]
    assert result.unmatched_names == []


def test_colliding_alias_matches_neither_character() -> None:
    characters = [
        _character("林舟", called_by={"母亲": "孩子"}),
        _character("周望", called_by={"父亲": "孩子"}),
    ]

    result = resolve_present_characters(["孩子"], characters)

    assert result.matched_names == []
    assert result.unmatched_names == ["孩子"]
    assert result.ambiguous_names == ["孩子"]


def test_protagonist_is_always_present_by_tier() -> None:
    characters = [
        _character("林舟", tier="protagonist"),
        _character("周望"),
    ]

    result = resolve_present_characters(["周望"], characters)

    assert result.matched_names == ["周望", "林舟"]
    assert result.unmatched_names == []


def test_outline_save_returns_nonblocking_unmatched_character_notice(
    tmp_path: Path, monkeypatch,
) -> None:
    from biyu.ui import workbench

    book = tmp_path / "book"
    book.mkdir()
    (book / "characters.yaml").write_text(
        yaml.safe_dump(
            {"characters": [_character("林舟", tier="protagonist")]},
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(workbench, "_book_dir", lambda _book: book)
    content = "---\npresent_characters:\n  - 外婆\n  - 那个陪母亲来的女孩\n---\n\n本章细纲"

    snapshot = workbench.save_outline(
        "book", 1, {"content": content, "base_sha": ""},
    )

    assert (book / "outlines" / "ch1.md").read_text(encoding="utf-8") == content
    assert snapshot["outline_character_notice"] == {
        "count": 2,
        "names": ["外婆", "那个陪母亲来的女孩"],
        "message": (
            "这一章点到 2 个名字没有人物卡：外婆、那个陪母亲来的女孩。"
            "写手查不到他们的设定，可以去设定集补，也可以就这么写。"
        ),
        "blocking": False,
    }


def test_outline_save_has_no_notice_when_every_name_has_card(tmp_path: Path, monkeypatch) -> None:
    from biyu.ui import workbench

    book = tmp_path / "book"
    book.mkdir()
    (book / "characters.yaml").write_text(
        yaml.safe_dump({"characters": [_character("林舟")]}, allow_unicode=True),
        encoding="utf-8",
    )
    monkeypatch.setattr(workbench, "_book_dir", lambda _book: book)

    snapshot = workbench.save_outline(
        "book", 1,
        {"content": "---\npresent_characters:\n  - 林舟\n---\n\n本章细纲", "base_sha": ""},
    )

    assert snapshot["outline_character_notice"]["count"] == 0
    assert snapshot["outline_character_notice"]["message"] == ""


def test_workbench_renders_unmatched_character_notice_without_blocking_save() -> None:
    script = Path("src/biyu/ui/static/workbench.js").read_text(encoding="utf-8")

    assert "outline_character_notice" in script
    assert "characterNotice.message" in script
    assert ".disabled" not in script.split("outline_character_notice", 1)[1][:300]


def test_generation_captures_exact_setup_versions_before_writing(tmp_path: Path) -> None:
    from biyu.pipeline import _capture_generation_setup_versions

    book = tmp_path / "book"
    book.mkdir()
    (book / "worldbook.yaml").write_text("facts:\n  - 第一版\n", encoding="utf-8")
    (book / "characters.yaml").write_text("characters: []\n", encoding="utf-8")
    (book / "北极星.md").write_text("一句话故事", encoding="utf-8")

    first = _capture_generation_setup_versions(book)
    (book / "worldbook.yaml").write_text("facts:\n  - 第二版\n", encoding="utf-8")
    second = _capture_generation_setup_versions(book)

    assert first == {"worldbook": 1, "characters": 1, "north_star": 1}
    assert second == {"worldbook": 2, "characters": 1, "north_star": 1}
    records = [
        json.loads(line)
        for line in (book / "logs" / "generation_setup_versions.jsonl")
        .read_text(encoding="utf-8").splitlines()
    ]
    assert [item["setup_versions"] for item in records] == [first, second]


def test_generation_metadata_includes_setup_version_snapshot() -> None:
    source = Path("src/biyu/pipeline.py").read_text(encoding="utf-8")

    assert '"setup_versions": generation_setup_versions' in source
