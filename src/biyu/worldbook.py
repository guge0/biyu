"""worldbook 加载与 prompt 注入。

读取 data/<书名>/worldbook.yaml，生成注入 Architect 和 Writer prompt 的字符串。
worldbook 是"宪法"——系统只读不改，每章生成时强制注入，优先级最高。
"""
from __future__ import annotations

from pathlib import Path


def _flatten_str_items(value, _depth: int = 0) -> list[str]:
    """把任意嵌套的列表结构拍平成字符串列表(2026-10 外部用户数据加固)。

    用户手写 worldbook.yaml 时常见"列表套列表"的缩进错误;此函数递归
    拍平(深度上限 5),非字符串标量转字符串,字典原样跳过(由各消费方
    的 dict 分支处理)。保证下游遍历拿到的每一条都是 str。
    """
    out: list[str] = []
    if value is None or _depth > 5:
        return out
    if isinstance(value, str):
        if value.strip():
            out.append(value.strip())
    elif isinstance(value, (list, tuple)):
        for item in value:
            out.extend(_flatten_str_items(item, _depth + 1))
    elif isinstance(value, (int, float)):
        out.append(str(value))
    return out


def load_worldbook(book_dir: Path) -> dict | None:
    """读 data/<书名>/worldbook.yaml，文件不存在返回 None。

    2026-10:列表字段递归拍平——用户 yaml 的"列表套列表"缩进错误
    不再向下游(写手注入/白名单/检查器)泄漏非字符串条目。
    """
    from biyu.setup_asset_versions import load_setup_yaml

    wb_path = book_dir / "worldbook.yaml"
    if not wb_path.exists():
        return None
    wb = load_setup_yaml(wb_path, label="世界观")
    if isinstance(wb, dict):
        list_fields = (
            "facts", "forbidden", "geography", "factions", "timeline",
            "npc_whitelist", "narrative_anchors",
        )
        for field in list_fields:
            if isinstance(wb.get(field), list):
                wb[field] = _flatten_str_items(wb[field])
        power = wb.get("power_system")
        if isinstance(power, dict) and isinstance(power.get("rules"), list):
            power["rules"] = _flatten_str_items(power["rules"])
    return wb


def build_worldbook_prompt(wb: dict | None) -> str:
    """生成注入 prompt 的字符串。None 时返回空串。

    字段语义：
    - narrative_anchors: 主角定位 / 基调 / 爽点偏好
    - power_system: 力量体系规则
    - facts: 硬设定列表，AI 不得违反
    - forbidden: 禁区列表，AI 不得触碰
    - geography: 地理设定
    - factions: 势力设定
    - timeline: 时间线锚点

    缺字段时跳过对应注入段，不阻塞。
    """
    if not wb:
        return ""

    sections: list[str] = []
    sections.append("【世界观锁（worldbook） — 以下信息不可违反，优先级最高】")

    # 创作锚点
    anchors = wb.get("narrative_anchors")
    if anchors:
        lines = ["\n── 创作锚点 ──"]
        for key, val in anchors.items():
            label = {
                "protagonist_archetype": "主角定位",
                "tone": "基调",
                "satisfaction_pattern": "爽点偏好",
                "consistency_rule": "文风一致性",
            }.get(key, key)
            if isinstance(val, str) and val.strip():
                lines.append(f"- {label}: {val}")
            elif isinstance(val, (list, tuple)):
                # S6-4: 真书形态=格下多条(列表),逐条并入,不得静默丢节
                items = [v.strip() for v in val if isinstance(v, str) and v.strip()]
                if items:
                    lines.append(f"- {label}: {'；'.join(items)}")
        if len(lines) > 1:
            sections.append("\n".join(lines))

    # 力量体系
    power = wb.get("power_system")
    if power:
        lines = ["\n── 力量/修炼体系 ──"]
        # S6-6: 兼容三种形态——{"rules":[...]}(旧,输出不加键名)、语义键 dict-of-lists(真书)、纯字符串
        if isinstance(power, dict):
            for key, val in power.items():
                label = str(key)
                items = val if isinstance(val, (list, tuple)) else [val]
                rendered = [v.strip() for v in items if isinstance(v, str) and v.strip()]
                if not rendered:
                    continue
                if label == "rules":
                    lines.extend(f"- {r}" for r in rendered)
                else:
                    lines.append(f"- {label}: {'；'.join(rendered)}")
        elif isinstance(power, str) and power.strip():
            lines.append(f"- {power}")
        if len(lines) > 1:
            sections.append("\n".join(lines))

    # 硬设定
    facts = wb.get("facts")
    if facts:
        lines = ["\n── 不可变硬设定（必须遵守，不得矛盾） ──"]
        for f in facts:
            if isinstance(f, str) and f.strip():
                lines.append(f"- {f}")
        if len(lines) > 1:
            sections.append("\n".join(lines))

    # 绝对禁止
    forbidden = wb.get("forbidden")
    if forbidden:
        lines = ["\n── 绝对禁止（触碰即硬伤） ──"]
        for f in forbidden:
            if isinstance(f, str) and f.strip():
                lines.append(f"- {f}")
        if len(lines) > 1:
            sections.append("\n".join(lines))

    # 地理/势力（短，合并注入）
    geo = wb.get("geography")
    factions = wb.get("factions")
    if geo or factions:
        lines = ["\n── 地理/势力 ──"]
        if geo:
            for g in geo:
                if isinstance(g, str) and g.strip():
                    lines.append(f"- {g}")
        if factions:
            for f in factions:
                if isinstance(f, str) and f.strip():
                    lines.append(f"- {f}")
        if len(lines) > 1:
            sections.append("\n".join(lines))

    # 时间线
    timeline = wb.get("timeline")
    if timeline:
        lines = ["\n── 时间线锚点 ──"]
        for t in timeline:
            if isinstance(t, str) and t.strip():
                lines.append(f"- {t}")
        if len(lines) > 1:
            sections.append("\n".join(lines))

    sections.append("\n【世界观锁结束】\n")

    return "\n\n".join(sections)
