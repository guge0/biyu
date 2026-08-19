from __future__ import annotations

from pathlib import Path

import yaml

from biyu.cli.zebian_context import render_zebian_context


def test_zebian_v2_preloads_four_assets_and_catalogs_the_rest(tmp_path: Path) -> None:
    book = tmp_path / "book"
    (book / "truth_files").mkdir(parents=True)
    (book / "chapters").mkdir()
    (book / "outlines").mkdir()
    (book / "北极星.md").write_text("# 北极星\n一句话", encoding="utf-8")
    (book / "大纲.md").write_text("# 大纲\n三幕", encoding="utf-8")
    (book / "worldbook.yaml").write_text(
        yaml.safe_dump(
            {"narrative_anchors": {"tone": "冷峻"}, "geography": ["北岸全文秘密"]},
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    (book / "characters.yaml").write_text(
        yaml.safe_dump({"characters": [{"name": "林舟", "tier": "protagonist", "role": "调查员"}]}, allow_unicode=True),
        encoding="utf-8",
    )
    (book / "truth_files" / "current_state.md").write_text("当前位置：北岸", encoding="utf-8")
    (book / "chapters" / "ch1.md").write_text("正文秘密", encoding="utf-8")
    (book / "outlines" / "ch2.md").write_text("细纲秘密", encoding="utf-8")

    rendered = render_zebian_context(book)

    for expected in ("# 北极星", "# 大纲", "# 创作锚点", "# truth_files", "当前位置：北岸"):
        assert expected in rendered
    assert "地理 ·" in rendered
    assert "北岸全文秘密" not in rendered
    assert "林舟 · protagonist · 调查员" in rendered
    assert "正式正文 ch1.md" in rendered
    assert "章节细纲 ch2.md" in rendered
    assert "正文秘密" not in rendered
    assert "细纲秘密" not in rendered


def test_zebian_skill_keeps_v2_behind_public_feature_probe() -> None:
    skill = Path(".claude/skills/zebian/SKILL.md").read_text(encoding="utf-8")
    assert "python -m biyu.cli.feature_status injection_v2" in skill
    assert "python -m biyu.cli.zebian_context <书目录名>" in skill
    assert "输出 `false`" in skill
    assert "以下只是清单,要用再查,不必全查" in skill
