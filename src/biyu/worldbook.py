"""worldbook 加载与 prompt 注入。

读取 data/<书名>/worldbook.yaml，生成注入 Architect 和 Writer prompt 的字符串。
worldbook 是"宪法"——系统只读不改，每章生成时强制注入，优先级最高。
"""
from __future__ import annotations

from pathlib import Path


def load_worldbook(book_dir: Path) -> dict | None:
    """读 data/<书名>/worldbook.yaml，文件不存在返回 None。"""
    from biyu.setup_asset_versions import load_setup_yaml

    wb_path = book_dir / "worldbook.yaml"
    if not wb_path.exists():
        return None
    return load_setup_yaml(wb_path, label="世界观")


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
            if isinstance(val, str) and val.strip():
                label = {
                    "protagonist_archetype": "主角定位",
                    "tone": "基调",
                    "satisfaction_pattern": "爽点偏好",
                    "consistency_rule": "文风一致性",
                }.get(key, key)
                lines.append(f"- {label}: {val}")
        if len(lines) > 1:
            sections.append("\n".join(lines))

    # 力量体系
    power = wb.get("power_system")
    if power:
        lines = ["\n── 力量/修炼体系 ──"]
        # power_system 可以是 dict(含 rules)或纯字符串(如"无")
        if isinstance(power, dict):
            rules = power.get("rules", [])
        else:
            rules = []
        for r in rules:
            if isinstance(r, str) and r.strip():
                lines.append(f"- {r}")
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
