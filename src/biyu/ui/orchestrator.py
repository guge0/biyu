"""UI 编排层(P8-M1 T3 + T4)— 直接调 propose 子模块,聚合结构化数据返给前端。

**propose 内部一行不改**:这里只是把 propose_command 拆出的"编排"那一半,
换成把中间数据(scan/router/analysis/redblue/craft)聚合成 ProposeUiResult 返给前端,
而不是只落盘 Markdown。

落盘 + cost_log 沿用 P7-2 约定:
- data/<name>/proposal/proposal_<YYYYMMDD-HHMMSS>.md
- data/<name>/logs/cost_log.csv(stage: router/tropes/redblue/craft)

软顶(T4):入口先查会话累计 + 估算,到顶未 confirm 时**不调任何 LLM**,直接返
status="softcap_reached"。绝不静默花钱。
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from biyu.config import get_data_root
from biyu.propose.analyzer import AnalysisResult
from biyu.propose.cost import log_propose_cost
from biyu.propose.craft import CraftHints
from biyu.ui.cost_log import write_cost_log
from biyu.propose.proposal import build_proposal_markdown
from biyu.propose.prompts import _HONESTY_NOTE
from biyu.propose.redblue import RedBlueResult
from biyu.propose.router import PathDecision, decide_path_with_cost
from biyu.propose.scanner import PlatformResult
from biyu.ui.scan_cache import scan_all_cached
from biyu.propose.analyzer import build_analysis
from biyu.propose.redblue import build_redblue
from biyu.propose.craft import build_craft_hints

logger = logging.getLogger("biyu.ui.orchestrator")

# 软顶估算:propose 单次历史均值约 ¥0.10(P7-2 实测)
_DEFAULT_PROPOSE_ESTIMATE = 0.10

# 进度回调类型(T3.1):事件结构 {stage, status, [cost_cny], [error], [total_cost_cny]}
ProgressCallback = Callable[[dict], None]


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------


@dataclass
class ProposeUiResult:
    """UI 编排产物。前端按字段渲染分散卡片。

    所有嵌套字段都用 dict(不走 dataclass / Enum),方便 FastAPI 直接 JSON 序列化。
    """

    # 整体状态:"ok" | "softcap_reached"
    status: str = "ok"
    # 路径(specific / directional / empty)
    path: str = ""
    # 结构化数据(供前端卡片渲染)
    router: dict[str, Any] = field(default_factory=dict)
    analysis: dict[str, Any] = field(default_factory=dict)
    redblue: dict[str, Any] | None = None
    craft: dict[str, Any] = field(default_factory=dict)
    honesty_note: str = _HONESTY_NOTE  # 永远 == 常量(D-67)
    # 完整立项书 Markdown(已落盘的内容)
    markdown: str = ""
    out_path: str = ""
    # 成本 / 耗时
    total_cost_cny: float = 0.0
    elapsed_seconds: float = 0.0
    model_alias: str = ""
    # 软顶信息(状态可见性)
    cumulative_cost_cny: float = 0.0
    softcap_cny: float = 0.0
    # T4 扫榜缓存元信息
    scan_cache: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------


def _get_llm_adapter(model_alias: str | None):
    """获取 LLM adapter,失败返 None(降级到模板/不可用模式,不崩)。"""
    from biyu.config import get_registry
    try:
        registry = get_registry()
        return registry.get_adapter_for_stage("writer", override=model_alias or None)
    except Exception as e:
        logger.warning("LLM adapter 获取失败,降级到模板/不可用模式:%s", e)
        return None


def _derive_name(idea: str, name: str | None) -> str:
    """从 idea 派生 slug 或用 name。与 propose_cmd 同逻辑,本地副本避免跨 CLI 耦合。"""
    if name and name.strip():
        return name.strip()
    if idea and idea.strip():
        slug = "".join(c if c.isalnum() else "_" for c in idea.strip()[:10]).strip("_")
        return f"propose_{slug}" or "propose_未命名"
    return "propose_未命名"


def _format_rankings_as_text(scan_results: dict[str, PlatformResult]) -> str:
    """把扫榜结果格式化为给 LLM 的纯文本(无 Markdown 噪音)。与 propose_cmd 同逻辑。"""
    lines: list[str] = []
    for platform, result in scan_results.items():
        if not result.success:
            lines.append(f"## {platform}\n(本次失败:{result.error})\n")
            continue
        lines.append(f"## {platform}(数据时间:{result.fetched_at})")
        for b in result.books[:20]:
            lines.append(
                f"{b.rank}. 《{b.title}》 作者:{b.author} 题材:{b.category} "
                f"字数:{b.word_count} 简介:{b.abstract}"
            )
        lines.append("")
    return "\n".join(lines)


# P8-M3R R7 T7.2:平台代号 → 中文显示名(给前端证据链用)
_PLATFORM_LABELS: dict[str, str] = {
    "qidian": "起点",
    "fanqie": "番茄",
    "chuangshi": "创世",
    "zongheng": "纵横",
    "jinjiang": "晋江",
}


def _build_title_rank_index(scan_results: dict[str, PlatformResult]) -> dict[str, dict[str, int]]:
    """P8-M3R R7 T7.2:从 scan_results 建 {platform: {title: rank}} 索引,供前端证据链查榜位。

    非改 prompt,纯数据规整(把已有数据变成 UI 易查的形状)。
    若 LLM 在 sample_titles 里编了不存在的书名,前端 lookup 会 miss → 显"(榜位未知)",
    正好暴露 LLM 幻觉给用户看(诚实声明,与 T7.5 兜底一致)。
    """
    index: dict[str, dict[str, int]] = {}
    for platform, result in scan_results.items():
        if not result.success:
            continue
        platform_index: dict[str, int] = {}
        for b in result.books[:20]:
            # 标题做 key(去前后空白);若有同名不同 rank,记首次出现
            if b.title and b.title not in platform_index:
                platform_index[b.title] = b.rank
        index[platform] = platform_index
    return index


def _platform_labels_used(scan_results: dict[str, PlatformResult]) -> dict[str, str]:
    """返本次扫描涉及的 {platform_code: 中文显示名}。未知平台回退 code 本身。"""
    return {p: _PLATFORM_LABELS.get(p, p) for p in scan_results.keys()}


def _router_to_dict(r: Any) -> dict[str, Any]:
    return {
        "decision": r.decision.value if hasattr(r.decision, "value") else str(r.decision),
        "source": r.source,
        "cost_cny": r.cost_cny,
        "latency_s": r.latency_s,
    }


def _analysis_to_dict(a: AnalysisResult) -> dict[str, Any]:
    return {
        "hot_genres": [
            {
                "genre": g.genre,
                "heat_signal": g.heat_signal,
                "sample_titles": list(g.sample_titles),
            }
            for g in a.hot_genres
        ],
        "hot_tropes": list(a.hot_tropes),
        "market_summary": a.market_summary,
        "source": a.source,
        "cost_cny": a.cost_cny,
        "latency_s": a.latency_s,
    }


def _redblue_to_dict(rb: RedBlueResult) -> dict[str, Any]:
    return {
        "supply_crowding": rb.supply_crowding,
        "demand_weak_signal": rb.demand_weak_signal,
        "quadrant": rb.quadrant.value if rb.quadrant else None,
        "source": rb.source,
        "cost_cny": rb.cost_cny,
        "latency_s": rb.latency_s,
    }


def _craft_to_dict(c: CraftHints) -> dict[str, Any]:
    return {
        "markdown": c.markdown,
        "source": c.source,
        "cost_cny": c.cost_cny,
        "latency_s": c.latency_s,
    }


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def run_propose_for_ui(
    idea: str,
    name: str | None,
    platforms: list[str] | None = None,
    model_alias: str | None = None,
    *,
    llm_adapter: Any | None = None,
    data_root: Path | None = None,
    session_id: str | None = None,
    costs: Any | None = None,
    confirm_over_softcap: bool = False,
    softcap_estimate: float = _DEFAULT_PROPOSE_ESTIMATE,
    on_progress: ProgressCallback | None = None,
    force_refresh_scan: bool = False,
) -> ProposeUiResult:
    """UI 端 propose 编排。

    Args:
        idea: 作者设想文本(可空 → EMPTY 路径)
        name: 书名/临时名(None → 从 idea 派生)
        platforms: 关注榜单(默认 ["qidian", "fanqie"])
        model_alias: 模型别名(None → 用 pipeline.writer 默认)
        llm_adapter: 测试注入的 adapter;None → 走 registry
        data_root: 数据根目录(None → get_data_root())
        session_id: 会话 ID(用于软顶累计;None → 不查软顶)
        costs: SessionCosts 实例(None → 不查软顶)
        confirm_over_softcap: 作者已 confirm 软顶(放行)
        softcap_estimate: 单次 propose 估算成本(默认 ¥0.10)
        on_progress: T3.1 进度回调,每 stage 触发 {stage, status, ...}。

    Returns:
        ProposeUiResult:status="ok" | "softcap_reached"
    """

    def _notify(stage: str, status: str, **extra: Any) -> None:
        if on_progress is not None:
            on_progress({"stage": stage, "status": status, **extra})

    # 软顶预检(T4):到顶未 confirm → 不调任何 LLM,直接返
    if session_id is not None and costs is not None:
        softcap_check = costs.check_softcap(
            session_id, softcap_estimate, confirm=confirm_over_softcap
        )
        if softcap_check.status == "softcap_reached":
            return ProposeUiResult(
                status="softcap_reached",
                cumulative_cost_cny=softcap_check.cumulative,
                softcap_cny=softcap_check.softcap,
            )

    started = time.time()
    idea_text = (idea or "").strip()
    book_name = _derive_name(idea_text, name)
    platform_list = platforms or ["qidian", "fanqie"]
    alias = (model_alias or "").strip() or None
    root = data_root if data_root is not None else get_data_root()

    # 阶段 1: 扫榜(T4.1:走缓存层)
    _notify("scan", "start")
    scan_results, scan_cache_meta = scan_all_cached(
        platforms=platform_list,
        force_refresh=force_refresh_scan,
        data_root=root,
    )
    _notify(
        "scan", "done",
        cached=scan_cache_meta.get("cached", False),
        cache_date=scan_cache_meta.get("cache_date"),
    )
    if scan_cache_meta.get("warning"):
        # D-70:缓存降级/损坏 → 出声
        logger.warning("扫榜缓存警告:%s", scan_cache_meta["warning"])

    # LLM adapter(测试注入优先,否则走 registry)
    if llm_adapter is None:
        llm_adapter = _get_llm_adapter(alias)

    # 阶段 2: 路径判断
    _notify("router", "start")
    router_decision = decide_path_with_cost(idea_text, llm_adapter)
    path = router_decision.decision
    _notify(
        "router", "done",
        cost_cny=router_decision.cost_cny, decision=path.value,
        source=router_decision.source,
    )
    if llm_adapter is not None and router_decision.source in ("llm", "llm_heuristic_fallback"):
        log_propose_cost(
            data_root=root, name=book_name, stage="router",
            cost_cny=router_decision.cost_cny, latency_s=router_decision.latency_s,
        )

    rankings_text = _format_rankings_as_text(scan_results)

    # 阶段 3: 套路归纳
    _notify("tropes", "start")
    analysis = build_analysis(
        idea=idea_text, rankings_text=rankings_text, llm_adapter=llm_adapter
    )
    _notify(
        "tropes", "done",
        cost_cny=analysis.cost_cny, source=analysis.source,
    )
    if llm_adapter is not None and analysis.source in ("llm", "llm_failed"):
        log_propose_cost(
            data_root=root, name=book_name, stage="tropes",
            cost_cny=analysis.cost_cny, latency_s=analysis.latency_s,
        )

    # 阶段 4: 红蓝海(仅 SPECIFIC 路径,异常时降级 source=llm_failed)
    redblue: RedBlueResult | None = None
    if path == PathDecision.SPECIFIC:
        _notify("redblue", "start")
        try:
            redblue = build_redblue(
                idea=idea_text, rankings_text=rankings_text, llm_adapter=llm_adapter
            )
        except Exception as e:
            # D-70:不静默崩,降级到 llm_failed 并出声
            logger.warning("build_redblue 异常,降级到 llm_failed:%s", e)
            redblue = RedBlueResult(source="llm_failed")
            _notify("redblue", "failed", error=str(e))
        else:
            _notify(
                "redblue", "done",
                cost_cny=redblue.cost_cny, source=redblue.source,
            )
        if llm_adapter is not None and redblue.source in ("llm", "llm_failed"):
            log_propose_cost(
                data_root=root, name=book_name, stage="redblue",
                cost_cny=redblue.cost_cny, latency_s=redblue.latency_s,
            )

    # 阶段 5: 创作规律
    _notify("craft", "start")
    craft = build_craft_hints(idea=idea_text, llm_adapter=llm_adapter)
    _notify(
        "craft", "done",
        cost_cny=craft.cost_cny, source=craft.source,
    )
    if llm_adapter is not None and craft.source in ("llm", "template_fallback"):
        log_propose_cost(
            data_root=root, name=book_name, stage="craft",
            cost_cny=craft.cost_cny, latency_s=craft.latency_s,
        )

    # 阶段 6: 合成 markdown
    elapsed = time.time() - started
    total_cost = (
        router_decision.cost_cny
        + analysis.cost_cny
        + (redblue.cost_cny if redblue is not None else 0.0)
        + craft.cost_cny
    )

    # D-93 中央成本台账
    if total_cost > 0:
        try:
            write_cost_log(task="propose", book=book_name, session=session_id or "", cost=total_cost)
        except Exception:
            logger.warning("写 cost_log 失败", exc_info=True)

    markdown = build_proposal_markdown(
        idea=idea_text,
        path=path,
        scan_results=scan_results,
        analysis=analysis,
        craft=craft,
        redblue=redblue,
        total_cost_cny=total_cost,
        elapsed_seconds=elapsed,
        model_alias=alias or "pipeline.writer",
    )

    # 阶段 7: 落盘
    proposal_dir = root / book_name / "proposal"
    proposal_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_path = proposal_dir / f"proposal_{timestamp}.md"
    out_path.write_text(markdown, encoding="utf-8")

    # 阶段 8: 累计会话成本(T4 配套)
    cumulative = 0.0
    softcap_value = 0.0
    if session_id is not None and costs is not None:
        cumulative = costs.add_cost(session_id, total_cost)
        softcap_value = costs.check_softcap(
            session_id, next_cost_estimate=0.0
        ).softcap

    _notify(
        "done", "done",
        total_cost_cny=total_cost,
        elapsed_seconds=elapsed,
        cumulative_cost_cny=cumulative,
        path=path.value,
    )

    return ProposeUiResult(
        status="ok",
        path=path.value,
        router=_router_to_dict(router_decision),
        analysis=_analysis_to_dict(analysis),
        redblue=_redblue_to_dict(redblue) if redblue is not None else None,
        craft=_craft_to_dict(craft),
        honesty_note=_HONESTY_NOTE,
        markdown=markdown,
        out_path=str(out_path),
        total_cost_cny=total_cost,
        elapsed_seconds=elapsed,
        model_alias=alias or "pipeline.writer",
        cumulative_cost_cny=cumulative,
        softcap_cny=softcap_value,
        scan_cache={
            **scan_cache_meta,
            # P8-M3R R7 T7.2 证据链 plumbing(非改 prompt,只把已有数据规整成 UI 易查形状)
            "title_rank_index": _build_title_rank_index(scan_results),
            "platform_labels": _platform_labels_used(scan_results),
        },
    )
