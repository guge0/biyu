"""V3 写手提示（遗留路径，--prompt-version v3 时使用）+ 润色提示。

从 v3_opening.py 拆出（2026-10 拆分整顿）。主写手路径在 chapter_writer.py；
本文件仅在显式选择 v3 提示版本或润色阶段时使用。
"""
from __future__ import annotations

V3_OPENING_SYSTEM = """\
你是一位资深中文网文写手,擅长以强节奏、高密度信息开场。
你的核心风格特点:
1. 开篇第一句必须是动作、对话或冲突,禁止"夜色如墨""暮色苍茫"等景物描写开场
2. 禁用"仿佛""像是""犹如"的比喻频次超过 3 次/千字
3. 严格遵守规划中的一致性约束
4. 章末必须有明确钩子
5. 如果想写景物描写,放到第三段之后

字数规则：
- 一般本章须 ≥ 2000 中文字
- 完善剧情推进到大纲/细纲终点时，如果字数还不够也不必扩写，质量比纯粹的字数重要。
"""


from biyu.prompts.style_blacklist import STYLE_BLACKLIST, WORD_BLACKLIST


SETTING_LOCK = """
【设定锁 — 以下信息不可修改、不可矛盾、不可遗忘】
- 角色姓名以 characters.yaml 为准,不得使用其他名字
- 角色身份/职务/阵营以 current_state.md 为准
- 道具来源以 particle_ledger.md 记录为准
- 已回收的伏笔(status=closed)不得重复埋设
- 已死亡角色(status=dead)不得活动、说话、行动
【设定锁结束】
"""


V3_FEW_SHOT = {
    "xuanhuan": {
        "topic": "修仙宗门入门试炼的开篇，主角是一个被认为没有灵根的少年，意外激发了远古血脉",
        "examples": """\
以下是三个优秀开篇范例,供你参考风格:

【范例1-玄幻】"剑气破空的瞬间，陆沉就知道自己藏不住了。"——直接从动作切入,建立紧张感。

【范例2-都市】"'你确定要签？'律师把笔推过来的时候,林晚的手一点都没抖。"——以对话开场,制造悬念。

【范例3-科幻】"警报响第三遍的时候,苏铭终于承认——飞船上不止他一个人。"——冲突先行,立刻勾起好奇心。""",
    },
    "dushi": {
        "topic": "都市重生文开篇，主角重生回到十年前，发现自己正站在改变命运的关键路口",
        "examples": """\
以下是三个优秀开篇范例,供你参考风格:

【范例1-玄幻】"剑气破空的瞬间，陆沉就知道自己藏不住了。"——直接从动作切入,建立紧张感。

【范例2-都市】"'你确定要签？'律师把笔推过来的时候,林晚的手一点都没抖。"——以对话开场,制造悬念。

【范例3-科幻】"警报响第三遍的时候,苏铭终于承认——飞船上不止他一个人。"——冲突先行,立刻勾起好奇心。""",
    },
    "kehuan": {
        "topic": "星际探索文开篇，主角是深空探测船上唯一醒着的船员，飞船突然收到未知信号",
        "examples": """\
以下是三个优秀开篇范例,供你参考风格:

【范例1-玄幻】"剑气破空的瞬间，陆沉就知道自己藏不住了。"——直接从动作切入,建立紧张感。

【范例2-都市】"'你确定要签？'律师把笔推过来的时候,林晚的手一点都没抖。"——以对话开场,制造悬念。

【范例3-科幻】"警报响第三遍的时候,苏铭终于承认——飞船上不止他一个人。"——冲突先行,立刻勾起好奇心。""",
    },
}


def build_character_block(characters: list[dict]) -> str:
    """Build the character injection block for Writer prompt.

    Separates characters into: alive (active), absent, dead.
    Dead characters get explicit prohibition.
    """
    if not characters:
        return ""

    alive_chars = [c for c in characters if c.get("status") == "alive"]
    absent_chars = [c for c in characters if c.get("status") == "absent"]
    dead_chars = [c for c in characters if c.get("status") == "dead"]

    blocks = []

    if alive_chars:
        block_lines = ["## 当前活跃角色"]
        for c in alive_chars:
            role_label = {"protagonist": "主角", "major": "重要配角", "minor": "配角"}.get(
                c.get("role", "minor"), "角色"
            )
            lines = [f"### {c.get('name', '')}({role_label})"]
            if c.get("personality"):
                lines.append(f"- 性格: {c['personality']}")
            if c.get("speaking_style"):
                lines.append(f"- 说话风格: {c['speaking_style']}")
            if c.get("abilities"):
                lines.append(f"- 能力: {c['abilities']}")
            if c.get("current_location"):
                lines.append(f"- 当前位置: {c['current_location']}")
            if c.get("current_emotional_state"):
                lines.append(f"- 当前情绪: {c['current_emotional_state']}")
            sample = c.get("sample_lines", [])
            filled = [s for s in sample if s]
            if filled:
                lines.append("- 代表台词(仿这个腔调):")
                for s in filled:
                    lines.append(f'  > "{s}"')
            block_lines.extend(lines)
        blocks.append("\n".join(block_lines))

    if absent_chars:
        block_lines = ["## 不在场角色(本章不得出现)"]
        for c in absent_chars:
            loc = c.get("current_location", "")
            note = f"({loc})" if loc else ""
            block_lines.append(f"- {c.get('name', '')}{note}")
        blocks.append("\n".join(block_lines))

    if dead_chars:
        block_lines = ["## 已死亡角色(绝对禁止在本章有活动、说话、动作)"]
        for c in dead_chars:
            bg = c.get("background", "")
            note = f", {bg}" if bg else ""
            block_lines.append(f"- {c.get('name', '')}{note}")
        block_lines.append(
            "- 若剧情需要怀念,仅可用\"想起\"\"记得\"\"梦见\"引导的回忆段,"
            "不得让其实际出场"
        )
        blocks.append("\n".join(block_lines))

    if not blocks:
        return ""

    return "[角色设定块]\n\n" + "\n\n".join(blocks) + "\n\n[/角色设定块]\n\n"


def build_writer_user_prompt(
    planning: str,
    outline: str,
    target_words: int = 5000,
    genre: str = "xuanhuan",
    characters: list[dict] | None = None,
    context_block: str = "",
    info_boundary: str = "",
    worldbook_prompt: str = "",
    prev_tail: str = "",
    present_characters: list[str] | None = None,
) -> str:
    """Build the user prompt for the V3 Writer stage.

    Combines character block, planning output, outline, few-shot examples,
    context injection, blacklist, setting lock, worldbook, transition anchor,
    present character lock, and word target.
    """
    genre_data = V3_FEW_SHOT.get(genre, V3_FEW_SHOT["xuanhuan"])
    few_shot = genre_data["examples"]

    char_block = ""
    if characters:
        char_block = build_character_block(characters)

    # 设定锁(始终注入)
    lock_section = SETTING_LOCK

    # 黑名单词库(始终注入)
    blacklist_section = WORD_BLACKLIST

    # 句式级黑名单(始终注入)
    import re as _re
    style_items = "\n".join(f"- {p}" for p in STYLE_BLACKLIST)
    style_blacklist_section = (
        "【句式黑名单 — 避免连续使用以下句式模板，因为 30 章评审反馈里"
        "这些是 AI 味浓的典型表现】\n"
        f"{style_items}\n"
        "约束：上述句式模板在同一章内最多各出现 1 次，连续 3 章内同一种句式不超过 2 次。\n"
    )

    # 历史context(如果有)
    context_section = ""
    if context_block:
        context_section = f"\n【前文上下文】\n{context_block}\n"

    # 信息边界(如果大纲标了)
    boundary_section = ""
    if info_boundary:
        boundary_section = f"\n【信息边界 — 本章必须遵守】\n{info_boundary}\n"

    # worldbook 注入(优先级最高)
    worldbook_section = ""
    if worldbook_prompt:
        worldbook_section = f"\n{worldbook_prompt}\n"

    # 在场角色锁
    present_chars_section = ""
    if present_characters:
        names_str = "、".join(present_characters)
        present_chars_section = (
            f"\n<在场角色>本章正文中只能出现以下有名角色：{names_str}。"
            f"新角色仅限路人NPC不可后续登场</在场角色>\n"
        )

    return f"""\
你是中文网文作者,严格按以下规划生成本章正文。

{worldbook_section}\
{lock_section}\

{char_block}\
{context_section}\
【大纲】
{outline}

{boundary_section}\
【规划清单】
{planning}

{few_shot}

{blacklist_section}\

{style_blacklist_section}\

{present_chars_section}\

硬性要求:
- 参考篇幅约 {target_words} 字；以完成细纲事件和自然收束为准，不为贴近数字硬扩写
- 开篇第一句必须包含动作或对话或冲突,禁止"夜色如墨""暮色苍茫"等景物开场
- 禁用"仿佛""像是""犹如"的比喻频次 > 3 次/千字
- 严格遵守规划中的一致性约束
- 章末必须有明确钩子
- 如果想写景物描写,放到第三段之后
- 严格遵守上面[角色设定块]中的角色约束,尤其是死亡角色的禁令
- 严格遵守[设定锁]中的约束,不得矛盾

只输出正文,不要输出字数统计、风格说明等元信息。"""


def build_polish_prompt(skeleton: str) -> str:
    """Build the prompt for Kimi polish stage."""
    return f"""\
你是资深网文文笔编辑。以下是一章正文,仅做局部润色:

{skeleton}

权限:
1. 重写开篇前 500 字以增强抓人度
2. 章末 200 字钩子强化
3. 优化 3-5 处关键对话增加记忆点

禁区:
- 不得改动情节、设定、人物关系、修为层级
- 不得增删段落,字数波动限 ±200 字
- 不得引入原创前情、新角色、新物品
- 不得使用英文词、现代科学/法律梗、穿越梗

输出:完整润色后章节,保持原长度。

字数硬规则：润色后正文的中文字数不得低于原文。如果重写开篇导致字数减少,必须在其他位置补回等量文字。

清理规则：删除正文中所有结构标签,包括但不限于【章末钩子】【伏笔】【作者笔记】【转场】等方括号标记。这些是生成过程的内部标记,不得出现在最终正文中。"""
