"""Chapter writer prompt v4 - 三层注入架构

替代 v3_opening.py 的罗列式 prompt。三层目的清晰:
- Layer 1: 硬规则(违反必拦)
- Layer 2: 上下文信息(只读不约束)
- Layer 3: 写作约束(数值化,可量化)

设计原则: why > must (来自 Anthropic Skills 设计指南)
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

_PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts" / "writer"


def _read_required_text(filename: str, *, keep_final_newline: bool = False) -> str:
    path = _PROMPTS_DIR / filename
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise RuntimeError(f"Required prompt file could not be read: {path}") from exc
    if not keep_final_newline and text.endswith("\n"):
        text = text[:-1]
    return text


def _read_required_fragments(filename: str) -> dict:
    path = _PROMPTS_DIR / filename
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Required prompt fragments could not be read: {path}") from exc
    if not isinstance(loaded, dict):
        raise RuntimeError(f"Required prompt fragments must be a JSON object: {path}")
    return loaded


WRITER_SYSTEM_V4 = _read_required_text("system.md")
_LAYER3_TEMPLATE = _read_required_text("layer3.md")
_FRAGMENTS = _read_required_fragments("fragments.json")
_MARKERS = _FRAGMENTS["markers"]

# 公共标记名由 pipeline 与既有测试消费，值的唯一文本家在 fragments.json。
LAYER1_BEGIN = _MARKERS["layer1_begin"]
LAYER1_END = _MARKERS["layer1_end"]
LAYER2_BEGIN = _MARKERS["layer2_begin"]
LAYER2_END = _MARKERS["layer2_end"]
LAYER3_BEGIN = _MARKERS["layer3_begin"]
LAYER3_END = _MARKERS["layer3_end"]


def build_layer1_hard_rules(chapter_num: int, worldbook: dict | None) -> str:
    """Layer 1 硬规则,200 字内。

    包含:
    - 主角姓名(从 worldbook 显式 protagonist 字段提取,P7-6;缺失时降级字符串匹配)
    - 已死亡角色禁令
    - worldbook 中标记为 facts 的核心设定
    - 章节号
    """
    layer1_fragments = _FRAGMENTS["layer1"]
    rules = []
    rules.append(layer1_fragments["chapter_rule"].format(chapter_num=chapter_num))

    # 从 worldbook 提取主角姓名和核心设定
    protagonist_name = None
    if worldbook and isinstance(worldbook, dict):
        # P7-6: 优先用显式 protagonist 字段(顶层 YAML key)
        protagonist_name = worldbook.get("protagonist")
        facts = worldbook.get("facts", [])
        # 降级:显式字段缺失时,按旧字符串匹配兜底(别崩)
        if not protagonist_name:
            for fact in facts:
                if isinstance(fact, str):
                    if "主角姓名" in fact or "主角" in fact:
                        protagonist_name = fact
                        break
        # 添加核心设定(非主角声明条目)
        for fact in facts:
            if isinstance(fact, str) and fact != protagonist_name:
                # P7-6: 跳过其他 "主角姓名:X" / "主角:X" 形式的声明条目
                # (它们已被 rule 2 体现,作为独立 rule 会冗余)
                if (fact.startswith("主角姓名")
                        or fact.startswith("主角:")
                        or fact.startswith("主角：")):
                    continue
                idx = len(rules) + 1
                rules.append(f"{idx}. {fact}")

    if protagonist_name:
        # 插入到第 2 条
        rules.insert(
            1,
            layer1_fragments["protagonist_rule"].format(
                protagonist_name=protagonist_name
            ),
        )
        # 重新编号
        for i in range(len(rules)):
            rule_text = rules[i]
            # 去掉旧编号
            if i + 1 > 1 and rule_text.startswith(f"{i + 1}."):
                rule_text = rule_text[len(str(i + 1)) + 2:]
            elif i + 1 > 1 and rule_text[0].isdigit() and "." in rule_text[:3]:
                rule_text = rule_text[rule_text.index(".") + 2:]
            if i == 0:
                rules[i] = layer1_fragments["chapter_rule"].format(
                    chapter_num=chapter_num
                )
            elif i == 1:
                rules[i] = layer1_fragments["protagonist_rule"].format(
                    protagonist_name=protagonist_name
                )
            else:
                rules[i] = f"{i + 1}. {rule_text}"

    # 添加通用硬规则
    idx = len(rules) + 1
    rules.append(layer1_fragments["death_rule"].format(index=idx))

    lines = [LAYER1_BEGIN] + rules + [LAYER1_END]
    return "\n".join(lines)


def build_layer2_context(
    worldbook_prompt: str,
    characters: list[dict],
    truth_files_block: str,
    prev_tail: str,
    context_block: str,
    outline: str,
    planning: str,
    present_characters: list[str] | None = None,
    previous_present_characters: list[str] | None = None,
    voiceprint_block: str = "",
    injection_v2: bool = False,
    original_outline: str = "",
    character_catalog: str = "",
    worldbook_catalog: str = "",
    history_catalog: str = "",
    character_projection: str = "combined",
) -> str:
    """Layer 2 信息上下文,只读不约束。"""
    if character_projection not in {"combined", "quick", "selected_full"}:
        raise ValueError(f"unknown character projection: {character_projection}")
    sections = _FRAGMENTS["sections"]
    parts = [LAYER2_BEGIN, *_FRAGMENTS["layer2_intro"]]

    # Q-1 关闭态必须保持旧装配；开启态的调用方只传预注入子集。
    if worldbook_prompt:
        parts.append(sections["worldbook"])
        parts.append(worldbook_prompt)

    # 角色档案：Q-1 开启时 characters 只含在场卡。
    if characters:
        if injection_v2:
            import yaml

            char_block = yaml.safe_dump(
                characters, allow_unicode=True, sort_keys=False,
            ).strip()
        else:
            full_names = set(present_characters or []) | set(previous_present_characters or [])
            full_names.update(
                str(char.get("name")) for char in characters
                if isinstance(char, dict) and char.get("tier") == "protagonist"
            )
            projected_characters = characters
            if character_projection == "quick":
                full_names = set()
            elif character_projection == "selected_full":
                projected_characters = [
                    char for char in characters
                    if isinstance(char, dict) and str(char.get("name")) in full_names
                ]
            char_block = _build_character_block(
                projected_characters, full_names=full_names,
            )
        if char_block:
            parts.append(sections["characters"])
            parts.append(char_block)

        # 称谓使用指引
        naming_guide = (
            _build_naming_guide(characters)
            if character_projection != "selected_full" else ""
        )
        if naming_guide:
            parts.append(naming_guide)

    # 本章在场角色(从细纲 frontmatter 注入)
    if present_characters and character_projection != "quick":
        present_block = _build_present_characters_block(present_characters, characters)
        parts.append(sections["present_characters"])
        parts.append(present_block)

    # 故事现状
    if truth_files_block:
        parts.append(sections["truth"])
        parts.append(truth_files_block)

    # 上一章末段(衔接锚点)
    if prev_tail and injection_v2:
        parts.append(
            "# 上一章结尾(若本章另起新场景,可不接续)"
            if injection_v2 else sections["prev_tail"]
        )
        parts.append(prev_tail)

    # 历史章节
    if context_block:
        parts.append(sections["history"])
        parts.append(context_block)

    # 创作者细纲
    if outline:
        parts.append(sections["outline"])
        parts.append(outline)

    # Q-1: Writer 同时读作者原始细纲与 Architect 方案。
    if injection_v2 and original_outline:
        parts.append("# 作者原始细纲")
        parts.append(original_outline)

    # 本章规划
    if planning:
        parts.append(sections["planning"])
        parts.append(planning)

    if voiceprint_block:
        parts.append(voiceprint_block)

    if injection_v2:
        catalogs = [
            ("其余人物卡目录", character_catalog),
            ("世界观目录", worldbook_catalog),
            ("历史正文目录", history_catalog),
        ]
        for title, catalog in catalogs:
            if catalog:
                parts.append(f"# {title}\n以下只是清单,要用再查,不必全查")
                parts.append(catalog)

    parts.append(LAYER2_END)
    return "\n\n".join(parts)


def _build_character_block(
    characters: list[dict], *, full_names: set[str] | None = None,
) -> str:
    """构建角色注入块，按 tier 分层排列。

    主角顶部硬注入，NPC 不注入。
    不同 tier 用不同详细度：
    - full: protagonist/antagonist/major_supporting（含全部字段）
    - medium: supporting（不含 voice_examples）
    - skip: npc（不注入 prompt）

    注意:init 模板占位名(主角姓名/配角1/配角2等)自动跳过。
    """
    PLACEHOLDER_PATTERNS = ["主角姓名", "配角1", "配角2", "配角3",
                            "反派姓名", "反派1",
                            "角色姓名", "姓名"]
    TIER_ORDER = ["protagonist", "antagonist", "major_supporting", "supporting"]
    tier_labels = _FRAGMENTS["tier_labels"]
    character_fragments = _FRAGMENTS["character"]

    # 按 tier 分组
    tier_groups: dict[str, list[dict]] = {t: [] for t in TIER_ORDER}
    for char in characters:
        if not isinstance(char, dict):
            continue
        name = char.get("name", "")
        if not name:
            continue
        # 跳过 init 模板占位名,这些不是真实角色数据
        if any(name == p for p in PLACEHOLDER_PATTERNS):
            continue
        tier = char.get("tier", "supporting")
        if tier == "npc":
            continue  # NPC 不进 prompt
        if tier not in tier_groups:
            tier = "supporting"
        tier_groups[tier].append(char)

    full_names = full_names or set()

    # 按 tier 顺序拼接
    sections: list[str] = []
    for tier in TIER_ORDER:
        group = tier_groups[tier]
        if not group:
            continue

        detail = "full" if tier in ("protagonist", "antagonist", "major_supporting") else "medium"
        label = tier_labels.get(tier, tier)
        section_lines = [character_fragments["tier_heading"].format(label=label)]

        for char in group:
            char_block = (
                _format_single_char(char, "full")
                if str(char.get("name")) in full_names
                else _format_character_quick_line(char)
            )
            if char_block:
                section_lines.append(char_block)

        sections.append("\n\n".join(section_lines))

    return "\n\n".join(sections)


def _format_character_quick_line(char: dict) -> str:
    name = str(char.get("name") or "")
    tier = str(char.get("tier") or "supporting")
    locator_text = str(
        char.get("role") or char.get("summary") or char.get("background") or ""
    ).strip()
    locator = locator_text.splitlines()[0].strip() if locator_text else ""
    return f"{name} · {tier} · {locator or '未填写定位'}"


def _format_single_char(char: dict, detail: str = "full") -> str:
    """格式化单个角色卡。

    Args:
        char: 角色数据。
        detail: 'full' 含全部字段, 'medium' 不含 voice_examples。
    """
    name = char.get("name", "")
    character_fragments = _FRAGMENTS["character"]
    lines = [character_fragments["heading"].format(name=name)]
    if char.get("background"):
        lines.append(character_fragments["background"].format(value=char["background"]))
    if detail == "full" and char.get("voice_examples"):
        lines.append(
            character_fragments["voice_examples"].format(value=char["voice_examples"])
        )
    if char.get("personality"):
        lines.append(character_fragments["personality"].format(value=char["personality"]))
    return "\n".join(lines)


def _build_naming_guide(characters: list[dict]) -> str:
    """生成称谓使用指引,放进 Layer 2 末尾。"""
    naming = _FRAGMENTS["naming"]
    lines = [naming["title"]]
    has_content = False
    for char in characters:
        if not isinstance(char, dict):
            continue
        if "aliases" not in char:
            continue
        has_content = True
        name = char["name"]
        aliases = char["aliases"]
        lines.append(naming["character_heading"].format(name=name))
        lines.append(
            naming["narrator_default"].format(
                value=aliases.get("narrator_default", name)
            )
        )
        lines.append(
            naming["self_referent"].format(
                value=aliases.get("self_referent", naming["default_self_referent"])
            )
        )
        if "called_by" in aliases:
            lines.append(naming["called_by_title"])
            for caller, call in aliases["called_by"].items():
                lines.append(naming["called_by_item"].format(caller=caller, call=call))
        if char.get("forbidden_in_narrative"):
            forbidden_list = ", ".join(f'"{x}"' for x in char["forbidden_in_narrative"])
            lines.append(naming["forbidden"].format(values=forbidden_list))
    return "\n".join(lines) if has_content else ""


@dataclass(frozen=True)
class PresentCharacterResolution:
    """Exact present-list resolution; ambiguous aliases are deliberately unresolved."""

    matched_names: list[str]
    unmatched_names: list[str]
    ambiguous_names: list[str]


def _character_match_terms(char: dict) -> list[str]:
    """Return every exact name term declared by the character card."""
    terms: list[str] = []
    name = char.get("name")
    if isinstance(name, str) and name.strip():
        terms.append(name.strip())
    aliases = char.get("aliases") or {}
    if isinstance(aliases, list):
        terms.extend(item.strip() for item in aliases if isinstance(item, str) and item.strip())
    elif isinstance(aliases, dict):
        for key in ("narrator_default", "self_referent"):
            alias = aliases.get(key)
            if isinstance(alias, str) and alias.strip():
                terms.append(alias.strip())
        called_by = aliases.get("called_by") or {}
        if isinstance(called_by, dict):
            terms.extend(
                item.strip()
                for item in called_by.values()
                if isinstance(item, str) and item.strip()
            )
    return list(dict.fromkeys(terms))


def resolve_present_characters(
    present_characters: list[str] | None,
    characters: list[dict],
) -> PresentCharacterResolution:
    """Resolve exact canonical names/aliases and append every protagonist by tier.

    One term belonging to more than one card is ambiguous: none of those cards is
    selected for that term, and the original term remains visible as unmatched.
    """
    term_owners: dict[str, list[str]] = {}
    protagonists: list[str] = []
    for char in characters:
        if not isinstance(char, dict):
            continue
        canonical = str(char.get("name") or "").strip()
        if not canonical:
            continue
        if char.get("tier") == "protagonist":
            protagonists.append(canonical)
        for term in _character_match_terms(char):
            owners = term_owners.setdefault(term, [])
            if canonical not in owners:
                owners.append(canonical)

    matched: list[str] = []
    unmatched: list[str] = []
    ambiguous: list[str] = []
    for raw_name in present_characters or []:
        name = str(raw_name).strip()
        if not name:
            continue
        owners = term_owners.get(name, [])
        if len(owners) == 1:
            if owners[0] not in matched:
                matched.append(owners[0])
        else:
            if name not in unmatched:
                unmatched.append(name)
            if len(owners) > 1 and name not in ambiguous:
                ambiguous.append(name)

    for protagonist in protagonists:
        if protagonist not in matched:
            matched.append(protagonist)
    return PresentCharacterResolution(matched, unmatched, ambiguous)


def _build_present_characters_block(
    present_characters: list[str], characters: list[dict]
) -> str:
    """构建'本章在场角色'注入块。

    从角色档案中提取在场角色的当前状态信息，
    让写手知道本场哪些角色在场、他们当前处于什么状态。
    """
    resolution = resolve_present_characters(present_characters, characters)
    # Exact resolution above has already canonicalised every matched name.
    char_map = {}
    for char in characters:
        if isinstance(char, dict):
            name = char.get("name", "")
            if name:
                char_map[name] = char

    present = _FRAGMENTS["present_characters"]
    lines = [present["rule"]]
    for name in resolution.matched_names:
        char = char_map.get(name, {})
        status = char.get("status", "")
        location = char.get("current_location", "")
        emotional = char.get("current_emotional_state", "")
        power = char.get("current_power_level", "")

        state_parts = []
        if status:
            state_parts.append(present["status"].format(value=status))
        if location:
            state_parts.append(present["location"].format(value=location))
        if emotional:
            state_parts.append(present["emotional"].format(value=emotional))
        if power:
            state_parts.append(present["power"].format(value=power))

        if state_parts:
            state_str = " | ".join(state_parts)
            lines.append(present["with_state"].format(name=name, state=state_str))
        else:
            lines.append(present["without_state"].format(name=name))

    return "\n".join(lines)


def build_layer3_constraints(target_words: int = 5000) -> str:
    """Layer 3 写作约束,数值化。"""
    return _LAYER3_TEMPLATE.format(
        target_words=target_words,
        max_words=target_words + 1500,
    )


def build_writer_prompt_v4(
    chapter_num: int,
    worldbook: dict | None,
    worldbook_prompt: str,
    characters: list[dict],
    truth_files_block: str,
    prev_tail: str,
    context_block: str,
    outline: str,
    planning: str,
    target_words: int = 5000,
    present_characters: list[str] | None = None,
    previous_present_characters: list[str] | None = None,
    voiceprint_block: str = "",
    injection_v2: bool = False,
    original_outline: str = "",
    character_catalog: str = "",
    worldbook_catalog: str = "",
    history_catalog: str = "",
) -> tuple[str, str]:
    """组装完整的 system + user prompt。

    Returns: (system_prompt, user_prompt)

    system_prompt: 简短角色定位
    user_prompt: Layer 1 + Layer 2 + Layer 3 + 收尾指令
    """
    system_prompt = WRITER_SYSTEM_V4

    layer1 = build_layer1_hard_rules(chapter_num, worldbook)
    layer2 = build_layer2_context(
        worldbook_prompt=worldbook_prompt,
        characters=characters,
        truth_files_block=truth_files_block,
        prev_tail=prev_tail,
        context_block=context_block,
        outline=outline,
        planning=planning,
        present_characters=present_characters,
        previous_present_characters=previous_present_characters,
        voiceprint_block=voiceprint_block,
        injection_v2=injection_v2,
        original_outline=original_outline,
        character_catalog=character_catalog,
        worldbook_catalog=worldbook_catalog,
        history_catalog=history_catalog,
    )
    layer3 = build_layer3_constraints(target_words)

    user_prompt = (
        f"{layer1}\n\n"
        f"{layer2}\n\n"
        f"{layer3}\n\n"
        f"{_FRAGMENTS['final_instruction'].format(chapter_num=chapter_num)}"
    )

    return system_prompt, user_prompt
