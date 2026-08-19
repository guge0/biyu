"""truth_inject — A3 实体过滤结构 + A1 实体识别/注入(P6-A1)。

A3: 把 YAML truth 按"关键词/字符串过滤"整理(纯 dict/字符串,不建库)。
A1: 用 alias 预注册识别本章出场实体,只把相关真值注入 agent prompt。

边界(钉死 D-43):关键词/字符串级匹配,不做语义检索/向量/同义归一化。
复用 biyu.anchor_check.normalize 处理全角→半角。
"""
from __future__ import annotations

import yaml

from biyu.anchor_check import normalize

# 顶层 dict 段:键即实体名,按 key ∈ appearing 过滤
_DICT_ENTITY_SECTIONS = frozenset({"characters", "locations"})

# 顶层 list 段:每条有文本字段,按"文本含 appearing 关键词"过滤
_LIST_TEXT_FIELDS = {"clues": "name", "hooks": "desc"}


# ---------------------------------------------------------------------------
# A1: 实体识别(alias 预注册)
# ---------------------------------------------------------------------------
def build_alias_registry(
    raw_characters: dict,
    truth: dict | None = None,
) -> dict[str, list[str]]:
    """从 characters.yaml 原始结构构建 {canonical: [识别别名...]}。

    收集的识别别名(用于本章出场判定):
    - 角色名本身(top-level key)
    - narrator_default(叙述默认称谓)
    - called_by 的全部 values(他人称呼)

    排除(不用于识别):
    - self_referent(如"我",所有第一人称 narrator 共用,太泛)
    - forbidden_in_narrative(禁用标签,非称谓)

    Args:
        raw_characters: characters.yaml 解析后的原始 dict
            {name: {aliases: {narrator_default, self_referent, called_by}, ...}}
        truth: 可选, 解析后的 truth dict; 提供 → 把 locations 段的键补进 registry
            (地点无 alias 预注册, 以 truth 自身键做关键词)

    Returns:
        {canonical_name: [alias1, alias2, ...]} 去重保序。
    """
    registry: dict[str, list[str]] = {}
    # 兼容管线 list[{name, aliases}] 与 yaml dict{name: {...}} 两种格式
    if isinstance(raw_characters, list):
        raw_characters = {
            item["name"]: item
            for item in raw_characters
            if isinstance(item, dict) and "name" in item
        }
    for name, info in raw_characters.items():
        aliases: list[str] = [name]
        sub = info.get("aliases", {}) if isinstance(info, dict) else {}
        if isinstance(sub, dict):
            nd = sub.get("narrator_default")
            if isinstance(nd, str) and nd:
                aliases.append(nd)
            called_by = sub.get("called_by", {})
            if isinstance(called_by, dict):
                for v in called_by.values():
                    if isinstance(v, str) and v:
                        aliases.append(v)
        # 去重保序
        seen: set[str] = set()
        deduped = []
        for a in aliases:
            if a not in seen:
                seen.add(a)
                deduped.append(a)
        registry[name] = deduped

    # 地点: truth 自身键做关键词(地点无 alias 预注册)
    if truth:
        for loc in (truth.get("locations") or {}):
            registry.setdefault(loc, [loc])

    return registry


def identify_appearing_entities(
    text: str,
    alias_registry: dict[str, list[str]],
) -> set[str]:
    """识别本章出场实体(canonical 名集合)。

    Args:
        text: 本章细纲/正文
        alias_registry: {canonical: [alias1, alias2, ...]}
            从 characters.yaml / anchors.yaml 的 aliases 预注册派生

    Returns:
        出场实体的 canonical 名集合(任一 alias 子串命中即算出场)。
    """
    norm_text = normalize(text)
    appearing: set[str] = set()
    for canonical, aliases in alias_registry.items():
        for alias in aliases:
            if normalize(alias) in norm_text:
                appearing.add(canonical)
                break
    return appearing


# ---------------------------------------------------------------------------
# A3: 实体过滤结构
# ---------------------------------------------------------------------------
def filter_truth_by_entities(
    truth: dict,
    appearing: set[str],
) -> dict:
    """按出场实体过滤 YAML truth(关键词/字符串级)。

    段处理:
    - characters / locations(dict, 键=实体名): 键 ∈ appearing 才保留
    - clues / hooks(list, 文本字段): 文本含任一 appearing 关键词才保留
    - 其它顶层键(如 meta): 原样透传(无实体概念)

    Args:
        truth: 解析后的 truth dict
        appearing: 出场实体 canonical 名集合(identify_appearing_entities 产出)

    Returns:
        同结构 filtered dict,只含相关条目。
    """
    out: dict = {}
    for key, val in truth.items():
        if key in _DICT_ENTITY_SECTIONS and isinstance(val, dict):
            out[key] = {k: v for k, v in val.items() if k in appearing}
        elif key in _LIST_TEXT_FIELDS and isinstance(val, list):
            text_field = _LIST_TEXT_FIELDS[key]
            out[key] = [
                item for item in val
                if any(
                    e in str(item.get(text_field, "")) for e in appearing
                )
            ]
        else:
            # 未知顶层键: 原样透传(meta 等无实体概念)
            out[key] = val
    return out


# ---------------------------------------------------------------------------
# A1: 过滤后的注入文本
# ---------------------------------------------------------------------------
def build_filtered_truth_block(
    truth: dict,
    text: str,
    alias_registry: dict[str, list[str]],
) -> str:
    """生成"仅含本章出场实体真值"的 prompt 注入块。

    流程: identify → filter → 渲染为可读文本块。
    无出场实体 → 空块(不注入任何 truth)。

    Args:
        truth: 解析后的 truth dict
        text: 本章细纲/正文
        alias_registry: 实体 alias 预注册

    Returns:
        注入文本(段标题 + 条目; 空条目段省略)。
    """
    appearing = identify_appearing_entities(text, alias_registry)
    filtered = filter_truth_by_entities(truth, appearing)

    lines: list[str] = []
    for section, val in filtered.items():
        if section in _DICT_ENTITY_SECTIONS and val:
            lines.append(f"=== {section} ===")
            for k, v in val.items():
                lines.append(f"- {k}: {v}")
        elif section in _LIST_TEXT_FIELDS and val:
            text_field = _LIST_TEXT_FIELDS[section]
            lines.append(f"=== {section} ===")
            for item in val:
                lines.append(f"- {item.get(text_field, '')}")
        # 未知段(meta 等)不进 prompt 块
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 管线桥接: 读 truth_files/*.md(eval 把 YAML 写进 .md) + 控制变量开关
# ---------------------------------------------------------------------------
def build_truth_injection_block(
    truth_md: dict[str, str],
    raw_characters: dict,
    filter_text: str,
    filter_enabled: bool,
) -> str:
    """管线注入块构建(承载 D-45 控制变量)。

    - filter_enabled=False(默认/改造前): 原样拼接全部 truth, 与现有 pipeline
      逐字等价 → 基线可复现。
    - filter_enabled=True(改造后): 解析 YAML → 实体过滤 → 只注入本章相关真值。

    Args:
        truth_md: read_all_truth_files 产出 {filename: content_str}
            (eval 桥接时 content 是 YAML 文本写在 .md 里)
        raw_characters: characters.yaml 原始 dict {name: {aliases: {...}}}
        filter_text: 过滤基准文本(细纲/正文); enabled=False 时不用
        filter_enabled: 实体过滤开关
    """
    if not filter_enabled:
        # D-45 钉死: 与 pipeline.py 原拼接逐字一致
        parts: list[str] = []
        for name, content in truth_md.items():
            if content.strip():
                parts.append(f"=== {name} ===\n{content}\n\n")
        return "".join(parts)

    # enabled: 解析 YAML → 合并 → 过滤
    # A4-V0 Part 2 容错: Observer 写入的 markdown 表格等非 YAML 内容
    # 会让 yaml.safe_load 抛 ScannerError; 跳过不可解析条目而非崩溃。
    truth: dict = {}
    for name, content in truth_md.items():
        if not content.strip():
            continue
        try:
            parsed = yaml.safe_load(content)
        except yaml.YAMLError:
            # 非合法 YAML(如 Observer 写入的 markdown 表格)→ 跳过
            continue
        if isinstance(parsed, dict):
            truth.update(parsed)

    registry = build_alias_registry(raw_characters, truth=truth)
    return build_filtered_truth_block(truth, filter_text, registry)
