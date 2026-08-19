"""Tests for chapter_writer.py v4 prompt."""
from biyu.prompts.chapter_writer import (
    build_layer1_hard_rules,
    build_layer2_context,
    build_layer3_constraints,
    build_writer_prompt_v4,
    LAYER1_BEGIN,
    LAYER2_BEGIN,
    LAYER3_BEGIN,
)


def test_layer1_hard_rules_extracts_protagonist_name():
    """Layer 1 包含从 worldbook.facts 提取的主角姓名。"""
    worldbook = {
        "facts": [
            "主角姓名:张今空",
            "秘境名称:试炼之塔",
            "等级体系:LV1-LV100",
        ]
    }
    result = build_layer1_hard_rules(chapter_num=3, worldbook=worldbook)
    assert "张今空" in result
    assert "第 3 章" in result


# ---------------------------------------------------------------------------
# P7-6: 显式 protagonist 字段(优先于 facts 字符串匹配)
# ---------------------------------------------------------------------------

def test_layer1_uses_explicit_protagonist_field():
    """P7-6: worldbook 显式 protagonist 字段优先于 facts 字符串匹配。

    背景:旧版靠 facts 里"主角"字符串匹配,产物是"2. 主角姓名: 主角姓名:X"
    (双前缀);方平试点被整段设定污染。P7-6 加显式字段,直接用 worldbook.get。
    """
    worldbook = {
        "protagonist": "李测试",
        "facts": ["主角姓名:旧主角", "金手指:测试"],
    }
    result = build_layer1_hard_rules(chapter_num=1, worldbook=worldbook)
    # 显式字段取到的名字必须出现
    assert "李测试" in result, "显式 protagonist 字段必须生效"
    # 不能出现旧字符串匹配的产物(整条 "主角姓名:旧主角" 不能作为 rule 2 内容)
    assert "主角姓名:旧主角" not in result, (
        "显式字段下,旧格式 fact 不能作为 rule 内容出现"
    )
    # 也不能有双前缀
    assert "主角姓名: 主角姓名" not in result, "双前缀必须消失"


def test_layer1_no_double_prefix_with_explicit_field():
    """P7-6: 显式字段下,Layer1 输出干净的 "2. 主角姓名: 张今空",无双前缀。"""
    worldbook = {
        "protagonist": "张今空",
        "facts": ["主角姓名:张今空", "主角所在城市:南城"],
    }
    result = build_layer1_hard_rules(chapter_num=1, worldbook=worldbook)
    # 必须是干净的 "2. 主角姓名: 张今空",不是 "2. 主角姓名: 主角姓名:张今空"
    assert "2. 主角姓名: 张今空\n" in result, (
        "显式字段下 rule 2 必须是 '主角姓名: 张今空'(无重复前缀)"
    )
    assert "主角姓名: 主角姓名" not in result, "双前缀必须消失"


def test_layer1_skips_other_protagonist_declaration_facts():
    """P7-6: 显式字段下,其他 '主角姓名:X' 形式的 fact 不进 rule 列表(防冗余)。

    facts 里"主角姓名:张今空" 旧条目保留(向后兼容),但不能作为独立 rule 出现
    (否则会与 rule 2 重复)。真设定 fact(主角所在城市/主角金手指)应保留。
    """
    worldbook = {
        "protagonist": "张今空",
        "facts": [
            "主角姓名:张今空",  # 旧格式声明 fact,应跳过(已在 rule 2 体现)
            "主角所在城市:南城",  # 真设定 fact,应保留
            "主角金手指:测试",   # 真设定 fact,应保留
        ],
    }
    result = build_layer1_hard_rules(chapter_num=1, worldbook=worldbook)
    # 主角姓名:X 形式的 fact 不能作为单独 rule 出现(避免重复)
    assert "\n3. 主角姓名:张今空" not in result, (
        "其他 '主角姓名:X' fact 不能作为独立 rule"
    )
    # 但真设定 fact 应保留
    assert "主角所在城市:南城" in result, "真设定 fact 必须保留"
    assert "主角金手指:测试" in result, "真设定 fact 必须保留"


def test_layer1_fallback_when_no_explicit_field():
    """P7-6: 无显式 protagonist 字段时,降级到旧字符串匹配(向后兼容,别崩)。"""
    worldbook = {
        "facts": ["主角姓名:张今空", "金手指:测试"],
    }
    result = build_layer1_hard_rules(chapter_num=1, worldbook=worldbook)
    # 旧路径仍能找到主角
    assert "张今空" in result, "无显式字段时,降级路径必须仍能取到主角名"


def test_layer1_under_300_chars():
    """Layer 1 字符数不超过 300(包含格式标记)。"""
    worldbook = {
        "facts": [
            "主角姓名:张今空",
            "秘境名称:试炼之塔",
        ]
    }
    result = build_layer1_hard_rules(chapter_num=1, worldbook=worldbook)
    assert len(result) <= 300


def test_layer2_no_constraint_keywords():
    """Layer 2 内容不出现约束词(只在各子段原文中允许)。

    检查 Layer 2 的结构标记和分隔行是否不含约束词。
    Layer 2 传入的内容本身(worldbook 原文)可能包含,所以只检查非内容行。
    """
    layer2 = build_layer2_context(
        worldbook_prompt="世界观内容",
        characters=[{"name": "张三", "background": "普通背景"}],
        truth_files_block="当前状态",
        prev_tail="上一章末段",
        context_block="历史章节",
        outline="本章大纲",
        planning="本章规划",
    )
    # 提取结构行(以 # 或 【 开头的行)
    constraint_words = ["必须", "禁止", "不得", "禁止使用"]
    for line in layer2.split("\n"):
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith("【"):
            for word in constraint_words:
                assert word not in stripped, f"Layer 2 结构行含约束词 '{word}': {stripped}"


def test_layer3_contains_punctuation_rule():
    """Layer 3 必须包含破折号约束。"""
    result = build_layer3_constraints(target_words=5000)
    assert "破折号" in result
    assert "2 次/章" in result


def test_present_characters_injected_into_layer2():
    """现场角色锁必须真实注入 Layer 2,且带角色当前状态。"""
    characters = [
        {"name": "江叙白", "tier": "protagonist", "status": "alive",
         "current_location": "回声巷", "current_emotional_state": "警惕"},
        {"name": "苏蔓", "tier": "major_supporting", "status": "alive",
         "current_location": "医院", "current_emotional_state": "焦虑"},
    ]
    present = ["江叙白", "苏蔓"]

    layer2 = build_layer2_context(
        worldbook_prompt="都市悬疑世界观",
        characters=characters,
        truth_files_block="故事现状",
        prev_tail="上一章尾",
        context_block="历史章节",
        outline="大纲",
        planning="规划",
        present_characters=present,
    )

    # Layer 2 中必须出现本章在场角色节
    assert "# 本章在场角色" in layer2
    # 角色名和当前状态必须出现
    assert "江叙白" in layer2
    assert "苏蔓" in layer2
    assert "alive" in layer2
    assert "回声巷" in layer2 or "医院" in layer2

    # 约束性语句必须出现
    assert "本章正文中只能出现以下有名角色" in layer2

    # Layer 2 仍不应含约束词(结构行检查)
    constraint_words = ["必须", "禁止", "不得", "禁止使用"]
    for line in layer2.split("\n"):
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith("【"):
            for word in constraint_words:
                assert word not in stripped, (
                    f"Layer 2 结构行含约束词 '{word}': {stripped}"
                )


def test_present_characters_flows_via_build_writer_prompt_v4():
    """build_writer_prompt_v4 必须把 present_characters 透传到最终 user_prompt。"""
    _, user_prompt = build_writer_prompt_v4(
        chapter_num=2,
        worldbook={"facts": ["主角姓名:江叙白"]},
        worldbook_prompt="都市悬疑",
        characters=[{"name": "江叙白", "tier": "protagonist", "status": "alive"}],
        truth_files_block="",
        prev_tail="",
        context_block="",
        outline="大纲",
        planning="",
        target_words=5000,
        present_characters=["江叙白"],
    )

    assert "# 本章在场角色" in user_prompt
    assert "江叙白" in user_prompt


def test_no_present_characters_does_not_add_section():
    """未传 present_characters 时不添加'本章在场角色'节。"""
    layer2 = build_layer2_context(
        worldbook_prompt="世界观",
        characters=[{"name": "张三", "tier": "protagonist"}],
        truth_files_block="",
        prev_tail="",
        context_block="",
        outline="",
        planning="",
    )
    assert "# 本章在场角色" not in layer2


def test_full_prompt_layers_in_order():
    """完整 prompt 顺序为 Layer 1 → Layer 2 → Layer 3。"""
    system_prompt, user_prompt = build_writer_prompt_v4(
        chapter_num=1,
        worldbook={"facts": ["主角姓名:张今空"]},
        worldbook_prompt="世界观",
        characters=[],
        truth_files_block="",
        prev_tail="",
        context_block="",
        outline="大纲",
        planning="规划",
        target_words=5000,
    )

    # system prompt 是独立的
    assert "中文网文作者" in system_prompt

    # user prompt 中 Layer 顺序
    l1_pos = user_prompt.find(LAYER1_BEGIN)
    l2_pos = user_prompt.find(LAYER2_BEGIN)
    l3_pos = user_prompt.find(LAYER3_BEGIN)

    assert l1_pos < l2_pos < l3_pos, (
        f"Layer 顺序错误: L1={l1_pos}, L2={l2_pos}, L3={l3_pos}"
    )

    # 收尾指令
    assert "现在开始写第 1 章正文" in user_prompt
