from __future__ import annotations

import asyncio

from biyu.wordguard import enforce_floor


def test_short_complete_chapter_is_warning_only_and_never_continued() -> None:
    calls = 0

    async def continuation(_text: str, _remaining: int) -> str:
        nonlocal calls
        calls += 1
        return "不应出现的续写"

    result = asyncio.run(enforce_floor("故事在这里自然收束。", 5000, 4250, continuation))

    assert result.text == "故事在这里自然收束。"
    assert result.continued is False
    assert calls == 0
    assert "本章下限" in result.warning


def test_writer_prompt_uses_floor_only_length_contract() -> None:
    """2026-10 老板裁定:篇幅只设下限、不设上限,档位即本章下限。"""
    text = open("prompts/writer/layer3.md", encoding="utf-8").read()

    assert "本章至少 {min_words}" in text
    assert "上不设限" in text
    assert "不得为凑字数" in text
    assert "max_words" not in text
    assert "不超过" not in text


def test_v3_prompt_no_longer_orders_padding_to_hit_a_number() -> None:
    from biyu.prompts.writer_v3_legacy import V3_OPENING_SYSTEM, build_writer_user_prompt

    combined = V3_OPENING_SYSTEM + build_writer_user_prompt(
        planning="方案", outline="细纲", target_words=5000, genre="奇幻",
        characters=[], context_block="", info_boundary="", worldbook_prompt="",
        prev_tail="", present_characters=[],
    )

    for forbidden in ("宁多勿少", "不要写到 3000-4000 字就收尾", "目标再写", "总字数 5000 ± 200"):
        assert forbidden not in combined
    assert "不必扩写" in combined
    assert "不为贴近数字硬扩写" in combined
