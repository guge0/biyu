"""立项书 Markdown 合成模块(P7-2 重写)。

P7-2 核心变化:**判断在前、证据在后、不整列书单**。
- 砍掉 P7-1 的"top 20 表格"(原 §2),改成"核心判断"在最前。
- 三路径(specific/directional/empty)差异化渲染 §2。
- hot_genres 每条题材的 sample_titles ≤3 本(由 analyzer 已硬截断)。
- 诚实声明(_HONESTY_NOTE)在 SPECIFIC 路径产出里"不可省"。

新五节结构(spec §5):
1. 作者输入回显
2. 核心判断(SPECIFIC→红蓝海 + 诚实声明;DIRECTIONAL→方向归纳;EMPTY→热门归纳)
3. 市场套路归纳(完整底座)
4. 创作规律提示(蒸馏)
5. 诚实边界 + 一句话
+ 元数据(末尾,含数据源 URL / 时间戳 / 成本 / 模型 / 来源标签)
"""
from __future__ import annotations

from datetime import datetime, timezone

from biyu.propose.analyzer import AnalysisResult, render_analysis_as_markdown
from biyu.propose.craft import CraftHints
from biyu.propose.redblue import Quadrant, RedBlueResult
from biyu.propose.router import PathDecision
from biyu.propose.scanner import PlatformResult


_QUADRANT_LABEL = {
    Quadrant.RED_SEA: "红海(多人写多人看)",
    Quadrant.BLUE_SEA: "蓝海(少人写多人看)",
    Quadrant.DEAD_SEA: "死海(多人写少人看)",
    Quadrant.WASTELAND: "荒漠(少人写少人看,警示'没人写可能因为没人看')",
}


def build_proposal_markdown(
    idea: str,
    path: PathDecision,
    scan_results: dict[str, PlatformResult],
    analysis: AnalysisResult,
    craft: CraftHints,
    redblue: RedBlueResult | None = None,
    total_cost_cny: float = 0.0,
    elapsed_seconds: float = 0.0,
    model_alias: str = "",
) -> str:
    """合成完整立项书 Markdown(P7-2 重构版)。

    Args:
        idea: 作者设想文本(可空)
        path: 路径判断结果(SPECIFIC/DIRECTIONAL/EMPTY)
        scan_results: 各平台的扫榜结果
        analysis: 市场套路归纳结果
        craft: 创作规律提示
        redblue: 红蓝海结果(仅 SPECIFIC 路径传,其他路径 None)
        total_cost_cny: 本次运行总成本
        elapsed_seconds: 本次运行总耗时
        model_alias: 使用的 LLM 模型别名

    Returns:
        完整 Markdown 字符串
    """
    now = datetime.now(timezone.utc).isoformat()
    idea_display = idea.strip() if idea and idea.strip() else "_(未填写)_"

    sections: list[str] = []
    sections.append(f"# 立项建议书\n\n> 生成时间(UTC):{now}\n")

    # 节 1: 设想回显
    sections.append(_render_idea_section(idea_display, path))

    # 节 2: 核心判断(最前,最重要)
    sections.append(_render_core_judgment_section(path=path, analysis=analysis, redblue=redblue))

    # 节 3: 市场套路归纳(完整底座)
    sections.append(_render_analysis_section(analysis))

    # 节 4: 创作规律
    sections.append(_render_craft_section(craft))

    # 节 5: 诚实边界 + 一句话
    sections.append(_render_honesty_closing_section(path=path, redblue=redblue))

    # 元数据(末尾)
    sections.append(_render_metadata(
        scan_results=scan_results,
        total_cost_cny=total_cost_cny,
        elapsed_seconds=elapsed_seconds,
        model_alias=model_alias,
        craft_source=craft.source,
        analysis_source=analysis.source,
        redblue_source=redblue.source if redblue else None,
        path=path,
    ))

    return "\n".join(sections)


# ---------------------------------------------------------------------------
# 节 1: 设想回显
# ---------------------------------------------------------------------------


def _render_idea_section(idea_display: str, path: PathDecision) -> str:
    """节 1:作者输入回显 + 路径标签。"""
    path_label = {
        PathDecision.SPECIFIC: "具体想法(走红蓝海对照)",
        PathDecision.DIRECTIONAL: "半方向(走方向归纳)",
        PathDecision.EMPTY: "未提供想法(走纯市场归纳)",
    }[path]
    return (
        "## 1. 作者设想\n\n"
        f"{idea_display}\n\n"
        f"> 路径判断:`{path_label}`\n"
    )


# ---------------------------------------------------------------------------
# 节 2: 核心判断(最前)
# ---------------------------------------------------------------------------


def _render_core_judgment_section(
    path: PathDecision,
    analysis: AnalysisResult,
    redblue: RedBlueResult | None,
) -> str:
    """节 2:核心判断。三路径差异化。"""
    if path == PathDecision.SPECIFIC:
        return _render_core_judgment_specific(redblue)
    if path == PathDecision.DIRECTIONAL:
        return _render_core_judgment_directional(analysis)
    return _render_core_judgment_empty(analysis)


def _render_core_judgment_specific(redblue: RedBlueResult | None) -> str:
    """SPECIFIC:红蓝海结论 + 诚实声明。"""
    parts: list[str] = ["## 2. 核心判断:红蓝海对照\n"]

    if redblue is None or redblue.source == "unavailable":
        parts.append(
            "> ⚠️ 本次未做红蓝海对照(未配置 LLM 或路径异常)。\n"
            "> 可参考下方市场套路归纳自行判断。\n"
        )
        return "\n".join(parts) + "\n"

    if redblue.source == "llm_failed":
        parts.append(
            "> ⚠️ 本次红蓝海对照未生成(LLM 失败或格式错,重试后仍未恢复)。\n"
            "> 可参考下方市场套路归纳,或重跑命令。\n"
        )
        return "\n".join(parts) + "\n"

    # source == 'llm':正常输出
    quadrant_label = _QUADRANT_LABEL.get(redblue.quadrant, "(未归类)")
    parts.append(f"**象限定性**:{quadrant_label}\n")
    parts.append(f"**供给拥挤度**:{redblue.supply_crowding}\n")
    parts.append(f"**同类在榜弱信号**:{redblue.demand_weak_signal}\n")
    parts.append(f"\n> **诚实声明**:{redblue.honesty_note}\n")
    return "\n".join(parts) + "\n"


def _render_core_judgment_directional(analysis: AnalysisResult) -> str:
    """DIRECTIONAL:该方向的套路归纳摘要(完整在 §3)。"""
    parts: list[str] = ["## 2. 核心判断:方向归纳\n"]
    if analysis.source == "llm":
        # 用 market_summary 作判断摘要;完整题材/套路在 §3
        parts.append(
            f"基于当前榜单,该方向的市场行情:{analysis.market_summary}\n"
        )
        if analysis.hot_tropes:
            tropes_preview = "、".join(analysis.hot_tropes[:3])
            parts.append(f"高频套路要素:{tropes_preview}\n")
        parts.append("\n> 完整题材分布与套路归纳见 §3。\n")
    else:
        parts.append(
            "> ⚠️ 市场套路归纳未生成(LLM 失败或离线)。"
            "> 可参考下方扫榜元数据自行判断。\n"
        )
    return "\n".join(parts) + "\n"


def _render_core_judgment_empty(analysis: AnalysisResult) -> str:
    """EMPTY:当前热门题材/套路归纳摘要(完整在 §3)。"""
    parts: list[str] = ["## 2. 核心判断:当前市场热门\n"]
    if analysis.source == "llm":
        parts.append(f"基于当前榜单的整体行情:{analysis.market_summary}\n")
        if analysis.hot_genres:
            genres_preview = "、".join(
                g.genre for g in analysis.hot_genres[:3] if g.genre
            )
            parts.append(f"近期热门题材:{genres_preview}\n")
        parts.append("\n> 完整题材分布与套路归纳见 §3。\n")
    else:
        parts.append(
            "> ⚠️ 市场套路归纳未生成(LLM 失败或离线)。"
            "> 可参考下方扫榜元数据自行判断。\n"
        )
    return "\n".join(parts) + "\n"


# ---------------------------------------------------------------------------
# 节 3: 市场套路归纳(完整)
# ---------------------------------------------------------------------------


def _render_analysis_section(analysis: AnalysisResult) -> str:
    """节 3:市场套路归纳(底座产出,完整)。"""
    return "## 3. 市场套路归纳\n\n" + render_analysis_as_markdown(analysis) + "\n"


# ---------------------------------------------------------------------------
# 节 4: 创作规律
# ---------------------------------------------------------------------------


def _render_craft_section(craft: CraftHints) -> str:
    """节 4:创作规律。"""
    body = craft.markdown
    # 去掉 markdown 里可能有的 H1/H2 标题(避免节中节),改成粗体
    for h in ("## 创作规律参考提示", "## 创作规律参考提示(LLM)"):
        if body.startswith(h):
            body = body[len(h):].lstrip()
            break
    body = body.replace("\n## ", "\n**")  # 粗略:内部小节降级
    source_tag = {
        "llm": "LLM 生成",
        "template": "蒸馏模板(未调 LLM)",
        "template_fallback": "蒸馏模板(LLM 失败降级)",
    }.get(craft.source, craft.source)
    return (
        "## 4. 创作规律提示\n\n"
        f"> 来源标签:`{source_tag}`\n\n"
        f"{body}\n"
    )


# ---------------------------------------------------------------------------
# 节 5: 诚实边界 + 一句话
# ---------------------------------------------------------------------------


def _render_honesty_closing_section(
    path: PathDecision, redblue: RedBlueResult | None
) -> str:
    """节 5:诚实边界 + 一句话免责。"""
    parts: list[str] = ["## 5. 诚实边界\n"]
    parts.append(
        "本建议书基于真实榜单数据归纳。"
        "**读者总量、阅读/付费等需求侧完整数据不可得**,本工具不编造。"
        "最终方向由作者结合行业经验判断。\n"
    )
    parts.append(
        "> 本建议书仅供参考,不命令作者、不替代创作判断。\n"
    )
    return "\n".join(parts) + "\n"


# ---------------------------------------------------------------------------
# 元数据(末尾)
# ---------------------------------------------------------------------------


def _render_metadata(
    scan_results: dict[str, PlatformResult],
    total_cost_cny: float,
    elapsed_seconds: float,
    model_alias: str,
    craft_source: str,
    analysis_source: str,
    redblue_source: str | None,
    path: PathDecision,
) -> str:
    """末尾元数据,含数据源 URL/时间戳/平台成败。"""
    success_count = sum(1 for r in scan_results.values() if r.success)
    fail_count = len(scan_results) - success_count

    platform_lines: list[str] = []
    for r in scan_results.values():
        status = "✓ 成功" if r.success else f"✗ 失败({r.error or '未记录'})"
        book_count = f",抓到 {len(r.books)} 本" if r.success else ""
        platform_lines.append(
            f"- `{r.platform}`: {status}{book_count} | URL:`{r.source_url or '(未记录)'}` "
            f"| 数据时间戳:`{r.fetched_at or '(未记录)'}`"
        )
    platforms_md = "\n".join(platform_lines) or "- (无平台)"

    return (
        "---\n\n"
        "## 元数据(供参考)\n\n"
        f"- 路径:`{path.value}`\n"
        f"- 平台成败:{success_count} 成功 / {fail_count} 失败\n"
        f"- 总成本(CNY):`{total_cost_cny:.4f}`\n"
        f"- 总耗时(秒):`{elapsed_seconds:.2f}`\n"
        f"- LLM 模型:`{model_alias or '(未记录)'}`\n"
        f"- 套路归纳来源:`{analysis_source}`\n"
        f"- 红蓝海来源:`{redblue_source or '(未走该路径)'}`\n"
        f"- 创作规律来源:`{craft_source}`\n"
        "\n数据源:\n"
        f"{platforms_md}\n"
    )
