"""导演（architect）提示词——从 v3_opening.py 拆出（2026-10 拆分整顿）。

输入：本章细纲/世界观/角色卡/记忆/上一章结尾；输出：结构化创作者细纲
（戏核/承载/笔墨/锚点/必检项）。产出写进 logs/chN/planning.md，
写手照图施工、必检项核对器照图验收、保真闸照图比对细纲。
"""
from __future__ import annotations


def build_planning_prompt(
    outline: str,
    characters: list[dict] | None = None,
    truth_files_block: str = "",
    worldbook_prompt: str = "",
    chapter_num: int = 0,
    anchor_block: str = "",
    prev_tail: str = "",
    present_characters: list[str] | None = None,
    previous_present_characters: list[str] | None = None,
    character_catalog: str = "",
    worldbook_catalog: str = "",
    injection_v2: bool = False,
    author_details_locked: bool = False,
) -> str:
    """Build the prompt for Creator Outline Generator (创作者细纲生成器).

    Architect 的职责是做创作判断,不是复述事件清单:
    戏核是什么、笔墨怎么分配、什么该删减。
    """
    # ---- sub-md 放最前面,锚定章节号 ----
    top_block = f"你现在要规划的是第 {chapter_num} 章。本章的剧情简介(sub-md)如下:\n\n{outline}"

    # ---- 背景材料放在 sub-md 之后 ----
    background_sections = []

    if worldbook_prompt.strip():
        background_sections.append("# 世界观\n" + worldbook_prompt.strip())

    if characters:
        from biyu.prompts.chapter_writer import _build_character_block

        full_names = set(present_characters or []) | set(previous_present_characters or [])
        full_names.update(
            str(char.get("name")) for char in characters
            if isinstance(char, dict) and char.get("tier") == "protagonist"
        )
        char_block = _build_character_block(characters, full_names=full_names)
        if char_block:
            background_sections.append("# 角色卡\n" + char_block)

    if truth_files_block.strip():
        background_sections.append(
            "# 前文摘要(truth_files)\n"
            "以下 truth_files 是已发生的故事状态,供你理解前文上下文,\n"
            "不是让你规划 truth_files 之后的章节。你要规划的章节,以上面的 sub-md 为准。\n\n"
            + truth_files_block.strip()
        )

    if prev_tail:
        background_sections.append(
            "# 上一章结尾(若本章另起新场景,可不接续)\n" + prev_tail
        )

    if injection_v2:
        catalogs = [
            ("人物名单", character_catalog),
            ("世界观目录", worldbook_catalog),
        ]
        for title, catalog in catalogs:
            if catalog:
                background_sections.append(
                    f"# {title}\n以下只是清单,要用再查,不必全查\n{catalog}"
                )

    background_block = "\n\n".join(background_sections)

    details_rule = ""
    if author_details_locked:
        from biyu.prompts.chapter_writer import _FRAGMENTS

        details_rule = "\n" + _FRAGMENTS["author_details"]["director"]

    return f"""\
你是中文网文的导演,为下一章写一张简短的场景表,给写手参考。
作者的细纲是路线:上面的事要发生、顺序不变、事实不能错。你不改剧情,不复述路线,也不替写手定细节。

{top_block}

{background_block}

## 创作引导

1. 先想这一章为了什么。作者写了「本章看点」就以它为准,不另起。
2. 按作者路线分场,路线几条大致就几场,可以合并,不能新增事件。
3. 每场只写它的作用、情绪从哪到哪、该重写还是一笔带过。作者标了「本章最重的一场」,照标。
4. 不发明细节:道具、数字、台词、人物的小动作、天气、钱数,作者没写的不要写进来。细节是写手和作者的事。
5. 你觉得路线有问题,写进「给作者的话」,不要自己改,也不要悄悄略过。{details_rule}

## 输出格式

# 第 N 章 导演方案

## 戏核
一句话:这一章为了什么。
一句话:读者最该被抓住的是哪一下。

## 场景表
- 场名|作用(铺垫 / 试探 / 升温 / 爆发 / 钩子)|情绪从哪到哪|重写 / 中 / 一笔带过|本场不能提前发生的事(没有写「无」)
(标出全章最重的一场;最后一行写「停在:」,照抄作者原话。)

## 不能违背
照抄作者细纲的「不能违背」,以及路线里出现的数字、人名、原样台词。逐字照抄,不改写、不合并。
{anchor_block}
## 出场人物
照抄作者细纲的「出场人物」。

## 必检项
- 必须发生:最多 5 条,只写删掉了这章就不成立的事;作者标的最重一场必须在内。
- 必须不发生:作者明说不能出现、或要留到后面的事;没有写「无」。
- 结尾状态:最后一段结束时人在哪、处在什么状态。

## 给作者的话
(可空)

整体 400-900 字。只输出方案,不输出正文。"""
