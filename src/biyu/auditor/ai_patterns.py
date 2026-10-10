"""反AI句式密度分组 — 词族合计按每千字归一的八股密度检查。

来源: 2026-10 融合外部写作提示词包《反AI与质量标准》§一/§六(老板授权导入)。
与 style_repeat 的逐模板阈值并存,分工:
- 逐模板阈值(STYLE_BLACKLIST): 单个句式模板一章内重复 → 惯性复读
- 密度分组(本表): 词族合计按每千字归一 → 八股密度,章长变化阈值不变形

阈值默认值来自提示词包§六的"原创默认上限",可用 config/auditor.yaml 的
checkers.style_repeat.density_limits.<key> 覆盖(书籍声纹分覆盖属后续设计,见交接)。
明喻引导词按字面计数,单字"像"不计(误报高),用"像是/像一"等双字标记。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DensityGroup:
    """一个密度检查组: label 面向作者展示, terms 为纯字面量子串。"""

    key: str
    label: str
    terms: tuple[str, ...]
    limit_per_kchar: float


DENSITY_GROUPS: tuple[DensityGroup, ...] = (
    DensityGroup(
        key="simile_markers",
        label="明喻引导词(像是/仿佛/如同/宛如/犹如/好似)",
        terms=("像是", "像一", "仿佛", "如同", "宛如", "犹如", "好似"),
        limit_per_kchar=3.0,
    ),
    DensityGroup(
        key="tic_words",
        label="缓冲词(缓缓/微微/轻轻/淡淡/嘴角)",
        terms=("缓缓", "微微", "轻轻", "淡淡", "嘴角"),
        limit_per_kchar=5.0,
    ),
    DensityGroup(
        key="cliche_expressions",
        label="套话表情(瞳孔一缩/嘴角上扬/心中暗道/倒吸一口凉气等)",
        terms=(
            "瞳孔一缩",
            "瞳孔猛缩",
            "瞳孔骤缩",
            "嘴角上扬",
            "嘴角微微上扬",
            "嘴角勾起",
            "心中暗道",
            "倒吸一口凉气",
            "喉结滚动",
            "眼眸中闪过",
        ),
        limit_per_kchar=1.0,
    ),
)


def count_group(text: str, group: DensityGroup) -> int:
    """统计词族在文本中的合计出现次数(按字面子串,各词独立计数)。"""
    return sum(text.count(term) for term in group.terms)
