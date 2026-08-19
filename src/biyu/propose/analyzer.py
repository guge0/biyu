"""市场套路归纳模块(P7-2 T3,重写)。

P7-2 改版:从 P7-1 的"客观罗列 + 契合分析"(situation/hot_topics/fit/risks)
改成"归纳 + 对标"(hot_genres/hot_tropes/market_summary),借 InkOS radar 思路。
新 schema 强制 sample_titles ≤ 3,防"整列书单"。

1 次 LLM 调用(主路径);schema 不全时重试 1 次;LLM 异常直接降级。
红线:LLM 只能基于 prompt 里的真实榜单数据,不得引入训练记忆。

实现:
- LLM 主路径:build_tropes_prompt → 调 adapter → 解析 JSON → schema 校验 → 渲染 Markdown。
- 重试:schema 校验失败 → 再调 1 次(国产模型 JSON 不稳,P7-1 已知)。
- 降级:重试仍失败 / LLM 异常 → source='llm_failed',proposal 据此显示"市场归纳暂不可用"。
- 无 adapter:source='unavailable'(供 CLI 离线模式/纯展示用)。
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from biyu.fingerprint.adapter import _extract_json_object
from biyu.propose.prompts import build_tropes_prompt


@dataclass
class HotGenre:
    """热门题材条目。

    sample_titles 最多 3 本(硬上限,由 _truncate_sample_titles 保证)。
    """

    genre: str = ""
    heat_signal: str = ""  # 热度信号(在哪些榜/排名/数量级)
    sample_titles: list[str] = field(default_factory=list)


@dataclass
class AnalysisResult:
    """市场套路归纳产物。

    source: 'llm' / 'llm_failed' / 'unavailable'
    """

    hot_genres: list[HotGenre] = field(default_factory=list)
    hot_tropes: list[str] = field(default_factory=list)
    market_summary: str = ""
    source: str = "unavailable"
    cost_cny: float = 0.0
    latency_s: float = 0.0


class _LLMAdapterProto(Protocol):
    async def generate(self, messages: list, **kwargs: Any) -> Any: ...


# 最大重试次数(总调用次数 = 1 + MAX_RETRIES)
_MAX_RETRIES = 1
# sample_titles 硬上限(防"整列书单")
_MAX_SAMPLE_TITLES = 3


def build_analysis(
    idea: str,
    rankings_text: str,
    llm_adapter: _LLMAdapterProto | None,
) -> AnalysisResult:
    """合成市场套路归纳。

    Args:
        idea: 作者设想文本(可空)
        rankings_text: 已格式化的榜单 Markdown 文本(真实数据)
        llm_adapter: LLM adapter;None → 直接返回 unavailable

    Returns:
        AnalysisResult
    """
    if llm_adapter is None:
        return AnalysisResult(source="unavailable")

    started = time.time()
    total_cost = 0.0
    last_text = ""

    for attempt in range(_MAX_RETRIES + 1):
        try:
            messages = build_tropes_prompt(idea, rankings_text)
            resp = asyncio.run(llm_adapter.generate(messages))
            cost = float(getattr(resp, "cost", 0.0) or 0.0)
            total_cost += cost
            last_text = getattr(resp, "text", "") or ""
        except Exception:
            # LLM 调用本身异常(网络/鉴权/模型):不重试,直接降级
            elapsed = time.time() - started
            return AnalysisResult(source="llm_failed", cost_cny=total_cost, latency_s=elapsed)

        parsed = _parse_and_validate_analysis(last_text)
        if parsed is not None:
            elapsed = time.time() - started
            return _build_result_from_parsed(parsed, total_cost, elapsed)
        # schema 失败 → 继续下一轮重试

    # 重试用尽仍失败
    elapsed = time.time() - started
    return AnalysisResult(source="llm_failed", cost_cny=total_cost, latency_s=elapsed)


def _parse_and_validate_analysis(text: str) -> dict | None:
    """解析 + schema 校验。

    必填:market_summary(非空字符串)
    选填:hot_genres(list,每条 dict 含 genre/heat_signal/sample_titles)、hot_tropes(list[str])
    """
    try:
        obj = _extract_json_object(text)
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    # market_summary 必须为非空字符串
    summary = obj.get("market_summary")
    if not (isinstance(summary, str) and summary.strip()):
        return None
    # hot_genres / hot_tropes 缺省为空列表,如有则必须是 list
    for k in ("hot_genres", "hot_tropes"):
        if k in obj and not isinstance(obj[k], list):
            return None
    return obj


def _build_result_from_parsed(
    parsed: dict, cost_cny: float, latency_s: float
) -> AnalysisResult:
    """从合法 dict 构造 AnalysisResult,顺便硬截断 sample_titles ≤3。"""
    raw_genres = parsed.get("hot_genres") or []
    hot_genres: list[HotGenre] = []
    if isinstance(raw_genres, list):
        for entry in raw_genres:
            if not isinstance(entry, dict):
                continue
            titles = entry.get("sample_titles") or []
            if not isinstance(titles, list):
                titles = []
            titles = [str(t) for t in titles if t][:_MAX_SAMPLE_TITLES]
            hot_genres.append(
                HotGenre(
                    genre=str(entry.get("genre", "")).strip(),
                    heat_signal=str(entry.get("heat_signal", "")).strip(),
                    sample_titles=titles,
                )
            )

    raw_tropes = parsed.get("hot_tropes") or []
    hot_tropes = (
        [str(t) for t in raw_tropes if str(t).strip()]
        if isinstance(raw_tropes, list)
        else []
    )

    return AnalysisResult(
        hot_genres=hot_genres,
        hot_tropes=hot_tropes,
        market_summary=str(parsed.get("market_summary", "")).strip(),
        source="llm",
        cost_cny=cost_cny,
        latency_s=latency_s,
    )


def render_analysis_as_markdown(result: AnalysisResult) -> str:
    """把 AnalysisResult 渲染成 Markdown。"""
    if result.source == "llm":
        return _render_llm_success(result)
    if result.source == "llm_failed":
        return _render_failed()
    return _render_unavailable()


def _render_llm_success(result: AnalysisResult) -> str:
    """source='llm' 的渲染。"""
    # 题材归纳
    if result.hot_genres:
        genre_lines = []
        for g in result.hot_genres:
            titles_md = (
                "、".join(g.sample_titles) if g.sample_titles else "_(未提取到代表作品)_"
            )
            genre_lines.append(
                f"- **{g.genre or '(未命名题材)'}** — {g.heat_signal or '(无热度信号)'}。"
                f"代表作品:{titles_md}"
            )
        genres_md = "\n".join(genre_lines)
    else:
        genres_md = "_(榜单未归纳出明显题材聚集)_"

    # 套路要素
    if result.hot_tropes:
        tropes_md = "\n".join(f"- {t}" for t in result.hot_tropes)
    else:
        tropes_md = "_(榜单未归纳出横切套路)_"

    return f"""## 市场套路归纳(基于真实榜单数据)

### 热门题材
{genres_md}

### 横切套路要素
{tropes_md}

### 行情概括
{result.market_summary}

> 红线:本节内容由 LLM 基于真实榜单数据归纳。如发现榜单外信息(如未提供数据的题材被点名、不在榜的书名),请视为不可信。
"""


def _render_failed() -> str:
    return """## 市场套路归纳

> ⚠️ 本次 LLM 归纳失败(模型异常或格式错,重试后仍未恢复)。
> 榜单数据已抓到(见上方),但套路归纳未生成。可结合上面的真实榜单自行判断,或重跑命令。

<!-- source: llm_failed -->
"""


def _render_unavailable() -> str:
    return """## 市场套路归纳

> ⚠️ 本次未调用 LLM(离线模式或未配置 adapter)。
> 仅提供上方真实榜单数据供自行判断。

<!-- source: unavailable -->
"""
