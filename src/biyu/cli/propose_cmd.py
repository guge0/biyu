"""biyu propose 命令实现(P7-2 重构)。

开书前命令:扫榜 + 路径判断 + 套路归纳 + (条件性)红蓝海对照 + 创作规律,合成 Markdown 立项书。
独立运行,不依赖任何已有书的 truth_files / book.json。

三路径编排(P7-2):
- SPECIFIC(具体想法):套路归纳 + 红蓝海 + 创作规律
- DIRECTIONAL(半方向):套路归纳 + 创作规律
- EMPTY(空 idea):套路归纳 + 创作规律

流程:
1. 扫榜(scan_all)。
2. 路径判断(decide_path):LLM 主 + 启发式降级,空 idea 直接 EMPTY。
3. 套路归纳(build_analysis):1 次 LLM(可重试 1 次)。
4. 红蓝海(build_redblue):仅 SPECIFIC 路径,1 次 LLM(可重试 1 次)。
5. 创作规律(build_craft_hints):1 次 LLM,失败降级模板。
6. 合成(build_proposal_markdown):判断在前、证据在后、不整列书单。
7. 落盘到 data/<name>/proposal/proposal_<YYYYMMDD-HHMMSS>.md
8. 各 LLM 调用分别写入 data/<name>/logs/cost_log.csv(stage: router/tropes/redblue/craft)
"""
from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path

from rich.console import Console

from biyu.config import get_data_root
from biyu.propose.analyzer import build_analysis
from biyu.propose.cost import log_propose_cost
from biyu.propose.craft import build_craft_hints
from biyu.propose.proposal import build_proposal_markdown
from biyu.propose.redblue import build_redblue
from biyu.propose.router import PathDecision, decide_path_with_cost
from biyu.propose.scanner import PlatformResult, scan_all


_console = Console()


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------


def get_llm_adapter(model_alias: str):
    """获取 LLM adapter,延迟 import 以便测试 monkeypatch。

    生产路径走 ModelRegistry.get_adapter_for_stage('writer', override=model_alias)。
    """
    from biyu.config import get_registry
    registry = get_registry()
    return registry.get_adapter_for_stage("writer", override=model_alias or None)


def _format_rankings_as_text(scan_results: dict[str, PlatformResult]) -> str:
    """把扫榜结果格式化为给 LLM 的纯文本(无 Markdown 噪音)。"""
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


def _derive_name(idea: str, name: str | None) -> str:
    """从 idea 派生 slug 或用 name。"""
    if name and name.strip():
        return name.strip()
    if idea and idea.strip():
        # 取前 10 个非空白字符做 slug,空格换 _
        slug = "".join(c if c.isalnum() else "_" for c in idea.strip()[:10]).strip("_")
        return f"propose_{slug}" or "propose_未命名"
    return "propose_未命名"


def _parse_platforms(platforms: str) -> list[str]:
    """解析 --platforms 字符串为列表。"""
    return [p.strip() for p in platforms.split(",") if p.strip()]


# ---------------------------------------------------------------------------
# 主命令
# ---------------------------------------------------------------------------


def propose_command(
    idea: str = "",
    name: str | None = None,
    platforms: str = "qidian,fanqie",
    model: str | None = None,
) -> Path:
    """biyu propose 主入口(P7-2 三路径版)。

    Args:
        idea: 作者设想文本(可空,空 → 走纯市场归纳路径)
        name: 书名或临时名
        platforms: 关注哪些榜单,逗号分隔
        model: 覆盖 LLM 模型别名

    Returns:
        产出的 Markdown 文件路径
    """
    started = time.time()
    data_root = get_data_root()
    idea_text = (idea or "").strip()
    if not idea_text:
        _console.print("[red]✗ 拒绝空输入: propose 需要填写创作设想(idea)。[/red]")
        _console.print("[yellow]提示: 输入你的创作想法,哪怕只有一句话。¥0.00[/yellow]")
        sys.exit(0)
    book_name = _derive_name(idea_text, name)
    platform_list = _parse_platforms(platforms)
    model_alias = (model or "").strip() or None

    _console.print(f"[cyan]▶ 扫榜平台:[/cyan] {', '.join(platform_list)}")

    # 阶段 1: 扫榜
    scan_results = scan_all(platforms=platform_list, limit=20)
    success_n = sum(1 for r in scan_results.values() if r.success)
    fail_n = len(scan_results) - success_n
    _console.print(
        f"[cyan]▶ 扫榜结果:[/cyan] {success_n} 平台成功"
        + (f", {fail_n} 失败" if fail_n else "")
    )

    # LLM adapter
    llm_adapter = None
    try:
        llm_adapter = get_llm_adapter(model_alias or "")
    except Exception as e:
        _console.print(f"[yellow]⚠ LLM adapter 获取失败,降级到模板/不可用模式:{e}[/yellow]")

    # 阶段 2: 路径判断
    router_decision = decide_path_with_cost(idea_text, llm_adapter)
    path = router_decision.decision
    _console.print(
        f"[cyan]▶ 路径判断:[/cyan] {path.value} (source: {router_decision.source})"
    )
    # 路径判断若走了 LLM(非空 idea + adapter 在线),记 cost_log
    if llm_adapter is not None and router_decision.source in ("llm", "llm_heuristic_fallback"):
        log_propose_cost(
            data_root=data_root, name=book_name, stage="router",
            cost_cny=router_decision.cost_cny, latency_s=router_decision.latency_s,
        )

    rankings_text = _format_rankings_as_text(scan_results)

    # 阶段 3: 套路归纳(所有路径都跑)
    analysis = build_analysis(
        idea=idea_text, rankings_text=rankings_text, llm_adapter=llm_adapter
    )
    if llm_adapter is not None and analysis.source in ("llm", "llm_failed"):
        log_propose_cost(
            data_root=data_root, name=book_name, stage="tropes",
            cost_cny=analysis.cost_cny, latency_s=analysis.latency_s,
        )

    # 阶段 4: 红蓝海(仅 SPECIFIC 路径)
    redblue = None
    if path == PathDecision.SPECIFIC:
        redblue = build_redblue(
            idea=idea_text, rankings_text=rankings_text, llm_adapter=llm_adapter
        )
        if llm_adapter is not None and redblue.source in ("llm", "llm_failed"):
            log_propose_cost(
                data_root=data_root, name=book_name, stage="redblue",
                cost_cny=redblue.cost_cny, latency_s=redblue.latency_s,
            )

    # 阶段 5: 创作规律
    craft = build_craft_hints(idea=idea_text, llm_adapter=llm_adapter)
    if llm_adapter is not None and craft.source in ("llm", "template_fallback"):
        log_propose_cost(
            data_root=data_root, name=book_name, stage="craft",
            cost_cny=craft.cost_cny, latency_s=craft.latency_s,
        )

    # 阶段 6: 合成
    elapsed = time.time() - started
    total_cost = (
        router_decision.cost_cny
        + analysis.cost_cny
        + (redblue.cost_cny if redblue is not None else 0.0)
        + craft.cost_cny
    )
    markdown = build_proposal_markdown(
        idea=idea_text,
        path=path,
        scan_results=scan_results,
        analysis=analysis,
        craft=craft,
        redblue=redblue,
        total_cost_cny=total_cost,
        elapsed_seconds=elapsed,
        model_alias=model_alias or "pipeline.writer",
    )

    # 阶段 7: 落盘
    proposal_dir = data_root / book_name / "proposal"
    proposal_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_path = proposal_dir / f"proposal_{timestamp}.md"
    out_path.write_text(markdown, encoding="utf-8")

    _console.print(f"[green]✓ 立项书已写入:[/green] {out_path}")
    return out_path
