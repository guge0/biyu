"""Tests for biyu.propose.prompts — P7-2 新增 prompt 模板.

覆盖:
- T2 套路归纳 prompt:build_tropes_prompt 形态 + 红线 + schema 说明
- T4 红蓝海 prompt:build_redblue_prompt 形态 + 四象限 + 禁编数字红线 + 诚实声明常量

prompt 是纯文本构造,无 LLM 调用,零烧钱。
"""
from __future__ import annotations

from biyu.propose.prompts import (
    _HONESTY_NOTE,
    build_redblue_prompt,
    build_tropes_prompt,
)


# ---------------------------------------------------------------------------
# T2: 套路归纳 prompt
# ---------------------------------------------------------------------------


def test_build_tropes_prompt_returns_system_user_messages():
    """build_tropes_prompt 返回 [{"role":"system",...}, {"role":"user",...}] 两段。"""
    messages = build_tropes_prompt(idea="校车进秘境", rankings_text="榜单数据...")

    assert isinstance(messages, list)
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"


def test_build_tropes_prompt_user_echoes_idea_and_rankings():
    """user 段回显作者 idea 与榜单数据,让 LLM 知道在分析什么。"""
    messages = build_tropes_prompt(idea="校车进秘境", rankings_text="QD热门:书A,书B")

    user_text = messages[1]["content"]
    assert "校车进秘境" in user_text
    assert "QD热门" in user_text


def test_build_tropes_prompt_system_has_no_outside_rankings_redline():
    """system 段含'不得引入榜单之外'红线(沿用 P7-1 analyzer 的硬约束)。"""
    messages = build_tropes_prompt(idea="某设想", rankings_text="某榜")

    system_text = messages[0]["content"]
    assert "不得引入榜单之外" in system_text


def test_build_tropes_prompt_system_describes_full_schema():
    """system 段说清输出 schema:hot_genres / sample_titles / hot_tropes / market_summary。

    防止 LLM 自由发挥结构,导致下游解析崩。
    """
    messages = build_tropes_prompt(idea="某设想", rankings_text="某榜")

    system_text = messages[0]["content"]
    assert "hot_genres" in system_text
    assert "sample_titles" in system_text
    assert "hot_tropes" in system_text
    assert "market_summary" in system_text


def test_build_tropes_prompt_system_caps_sample_titles_at_three():
    """system 段明示 sample_titles ≤ 3(防 LLM 塞 10 本,违背'不整列书单')。"""
    messages = build_tropes_prompt(idea="某设想", rankings_text="某榜")

    system_text = messages[0]["content"]
    # 必须出现"3"或"三"作为上限明示
    assert "3" in system_text or "三" in system_text
    # 而且 sample_titles 附近要有上限语义(简单检查 sample_titles 出现)
    assert "sample_titles" in system_text


# ---------------------------------------------------------------------------
# T4: 红蓝海 prompt + 诚实声明常量
# ---------------------------------------------------------------------------


def test_honesty_note_constant_matches_spec_wording():
    """模块级常量 _HONESTY_NOTE 文本对齐 spec §3 那句诚实声明(不可由 LLM 改)。

    spec 原话:"以上基于榜单的供给侧 + 同类在榜表现判断;读者总量、阅读/付费等
    需求侧完整数据不可得,最终需作者结合行业经验判断。"
    """
    assert isinstance(_HONESTY_NOTE, str)
    assert len(_HONESTY_NOTE) > 30  # 有实质内容
    # 关键不可省的语义片段
    assert "供给侧" in _HONESTY_NOTE
    assert "需求侧" in _HONESTY_NOTE
    assert "不可得" in _HONESTY_NOTE or "不可获" in _HONESTY_NOTE
    assert "作者" in _HONESTY_NOTE  # "作者自行判断"语义


def test_build_redblue_prompt_returns_system_user_messages():
    """build_redblue_prompt 返回 [{"role":"system",...}, {"role":"user",...}] 两段。"""
    messages = build_redblue_prompt(idea="校车进秘境", rankings_text="榜单数据...")

    assert isinstance(messages, list)
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"


def test_build_redblue_prompt_user_echoes_idea_and_rankings():
    """user 段回显作者 idea 与榜单数据。"""
    messages = build_redblue_prompt(
        idea="校车进秘境、轻喜剧爽文",
        rankings_text="QD热门:书A,书B",
    )

    user_text = messages[1]["content"]
    assert "校车进秘境" in user_text
    assert "QD热门" in user_text


def test_build_redblue_prompt_system_defines_four_quadrants():
    """system 段含四象限定义:红海 / 蓝海 / 死海 / 荒漠。

    防止 LLM 自由发挥象限归类。
    """
    messages = build_redblue_prompt(idea="x", rankings_text="x")

    system_text = messages[0]["content"]
    assert "红海" in system_text
    assert "蓝海" in system_text
    assert "死海" in system_text
    assert "荒漠" in system_text


def test_build_redblue_prompt_system_has_no_fabricated_demand_numbers_redline():
    """system 段含'禁止编造需求侧数字'红线(spec §3 硬要求)。

    防止 LLM 编"该题材有X万读者"这类假确定性。
    """
    messages = build_redblue_prompt(idea="x", rankings_text="x")

    system_text = messages[0]["content"]
    assert "需求侧" in system_text
    assert "编" in system_text or "捏造" in system_text or "虚构" in system_text


def test_build_redblue_prompt_system_describes_schema():
    """system 段说清输出 schema:supply_crowding / demand_weak_signal / quadrant。

    honesty_note 由代码常量注入,不要求 LLM 产。
    """
    messages = build_redblue_prompt(idea="x", rankings_text="x")

    system_text = messages[0]["content"]
    assert "supply_crowding" in system_text
    assert "demand_weak_signal" in system_text
    assert "quadrant" in system_text
