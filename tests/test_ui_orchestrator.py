"""Tests for biyu.ui.orchestrator — UI 编排(P8-M1 T3).

直接调 propose 子模块(scan_all / decide_path_with_cost / build_analysis / build_redblue /
build_craft_hints / build_proposal_markdown / log_propose_cost),聚合结构化数据返给前端。
**propose 内部一行不改**。

覆盖:
- 三路径(SPECIFIC / DIRECTIONAL / EMPTY)聚合字段正确
- 各阶段失败时 orchestrator 不崩,source 标 llm_failed / unavailable(D-70)
- scan_all 全失败仍产出(降级)
- honesty_note == _HONESTY_NOTE 常量(直接 import,断言)
- cost_log 写入 stage 正确(router/tropes/redblue/craft)
- 落盘路径沿 P7-2 约定

所有 LLM / scan 通过 mock,零烧钱。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from biyu.propose.prompts import _HONESTY_NOTE
from biyu.propose.redblue import Quadrant
from biyu.propose.router import PathDecision
from biyu.propose.scanner import BookEntry, PlatformResult
from biyu.ui.orchestrator import ProposeUiResult, run_propose_for_ui


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _make_book(i: int, platform: str) -> BookEntry:
    return BookEntry(
        rank=i, title=f"书{i}", author=f"作者{i}", category="玄幻",
        word_count="100万字", url=f"https://x.com/{platform}/{i}", abstract=f"简介{i}。",
    )


def _mock_scan_all_success(platforms, fetchers=None, limit=20):
    return {
        p: PlatformResult(
            platform=p, success=True,
            books=[_make_book(i + 1, p) for i in range(5)],
            fetched_at="2026-07-03T10:00:00+00:00",
            source_url=f"https://x.com/{p}",
        )
        for p in platforms
    }


def _mock_scan_all_all_fail(platforms, fetchers=None, limit=20):
    return {
        p: PlatformResult(
            platform=p, success=False, error="network down",
            fetched_at="2026-07-03T10:00:00+00:00",
            source_url=f"https://x.com/{p}",
        )
        for p in platforms
    }


class _MockAdapter:
    """Mock LLM adapter —— 根据 prompt 内容返不同响应。"""

    def __init__(self, router_response: str = "specific"):
        self._router_response = router_response
        self.calls: list = []

    async def generate(self, messages, **kwargs):
        self.calls.append(messages)
        blob = "".join(m.get("content", "") or "" for m in messages)
        if "思路分类器" in blob or "specific / directional / empty" in blob:
            text = self._router_response
        elif "套路归纳器" in blob:
            text = (
                '{"hot_genres": [{"genre": "都市异能", "heat_signal": "起点前 10", '
                '"sample_titles": ["书1", "书2", "书3"]}], '
                '"hot_tropes": ["系统流+吐槽"], '
                '"market_summary": "都市异能占主导。"}'
            )
        elif "红蓝海对照分析师" in blob:
            text = (
                '{"supply_crowding": "校车题材拥挤。", '
                '"demand_weak_signal": "同类位次靠前。", '
                '"quadrant": "红海"}'
            )
        elif "创作规律顾问" in blob:
            # 字段需足够长,craft.py 的 _MIN_LEN=200 否则降级 template_fallback
            text = (
                '{"rhythm": "节奏曲线:约 1 万字一个小高潮,三四章一局,章尾铺钩子。", '
                '"goals": "目标体系:开局 1 万字立短期,3 万字立中期,6 万字立长期。", '
                '"cool_points": "爽点六类:暧昧/物品获得/养成/优越感/送菜流/主线追求。", '
                '"opening": "开篇结构:凤头简单精要,主角聚光,双伏笔,写完 3 万字反写 300 字细纲。", '
                '"dimensions": "评书七维:脸面/基础/主角聚光/开头/布局/情节/人物塑造。"}'
            )
        else:
            text = "{}"

        class _R:
            cost = 0.001

        r = _R()
        r.text = text
        return r


@pytest.fixture
def mock_adapter():
    """提供独立 _MockAdapter 实例,允许测试自定义 router_response。"""
    return _MockAdapter(router_response="specific")


# ---------------------------------------------------------------------------
# T3.1 三路径
# ---------------------------------------------------------------------------


class TestThreePaths:
    def test_specific_path_returns_full_result_with_redblue(
        self, tmp_path: Path, monkeypatch
    ):
        adapter = _MockAdapter(router_response="specific")
        result = run_propose_for_ui(
            idea="校车进秘境、轻喜剧爽文",
            name="t3_specific",
            platforms=["qidian"],
            llm_adapter=adapter,
            data_root=tmp_path,
        )
        assert result.status == "ok"
        assert result.path == "specific"
        assert result.redblue is not None
        assert result.redblue["quadrant"] == "红海"

    def test_directional_path_returns_result_without_redblue(
        self, tmp_path: Path, monkeypatch
    ):
        adapter = _MockAdapter(router_response="directional")
        result = run_propose_for_ui(
            idea="想写穿越的",
            name="t3_directional",
            platforms=["qidian"],
            llm_adapter=adapter,
            data_root=tmp_path,
        )
        assert result.status == "ok"
        assert result.path == "directional"
        assert result.redblue is None

    def test_empty_path_returns_result_without_redblue(
        self, tmp_path: Path, monkeypatch
    ):
        adapter = _MockAdapter(router_response="empty")
        result = run_propose_for_ui(
            idea="",
            name="t3_empty",
            platforms=["qidian"],
            llm_adapter=adapter,
            data_root=tmp_path,
        )
        assert result.status == "ok"
        assert result.path == "empty"
        assert result.redblue is None


# ---------------------------------------------------------------------------
# T3.2 聚合字段完整
# ---------------------------------------------------------------------------


def test_aggregated_fields_complete(tmp_path: Path):
    adapter = _MockAdapter(router_response="specific")
    result = run_propose_for_ui(
        idea="校车",
        name="t3_aggregate",
        platforms=["qidian", "fanqie"],
        llm_adapter=adapter,
        data_root=tmp_path,
    )
    # scan/router/analysis/redblue/craft/markdown/total_cost 全部就位
    assert result.router["source"] in ("llm", "llm_heuristic_fallback")
    assert result.router["cost_cny"] >= 0
    assert result.analysis["source"] == "llm"
    assert result.analysis["market_summary"]
    assert len(result.analysis["hot_genres"]) >= 1
    assert result.redblue is not None
    assert result.redblue["supply_crowding"]
    assert result.craft["source"] == "llm"
    assert result.craft["markdown"]
    assert result.markdown  # 完整 markdown
    assert result.total_cost_cny > 0
    assert result.out_path  # 落盘路径
    assert result.elapsed_seconds >= 0


# ---------------------------------------------------------------------------
# T3.3 各阶段失败降级(D-70)
# ---------------------------------------------------------------------------


def test_redblue_exception_does_not_crash_orchestrator(tmp_path: Path, monkeypatch):
    """mock build_redblue 抛异常 → orchestrator 捕获 + 标 source=llm_failed,不崩。"""
    from biyu.propose.redblue import RedBlueResult
    from biyu.ui import orchestrator as orch_mod

    def boom(*args, **kwargs):
        raise RuntimeError("simulated LLM outage")

    monkeypatch.setattr(orch_mod, "build_redblue", boom)

    adapter = _MockAdapter(router_response="specific")
    result = run_propose_for_ui(
        idea="校车",
        name="t3_redblue_boom",
        platforms=["qidian"],
        llm_adapter=adapter,
        data_root=tmp_path,
    )
    # 不崩,status 仍 ok(整个 propose 不报错);redblue 标记失败
    assert result.status == "ok"
    assert result.redblue is not None
    assert result.redblue["source"] == "llm_failed"


def test_scan_all_failures_still_produces_result(tmp_path: Path, monkeypatch):
    """mock scan_all 全失败 → orchestrator 仍调后续(降级,与 propose_command 行为一致)。"""
    from biyu.ui import orchestrator as orch_mod

    # T4.1 起 orchestrator 走 scan_all_cached,包装层 mock 成"全失败 + 空 meta"
    def _scan_all_fail(**kwargs):
        return _mock_scan_all_all_fail(
            platforms=kwargs.get("platforms", []),
            fetchers=kwargs.get("fetchers"),
            limit=kwargs.get("limit", 20),
        )

    def _cached_fail(**kwargs):
        return _scan_all_fail(**kwargs), {
            "cached": False, "cache_date": None, "warning": None, "cache_path": None,
        }

    monkeypatch.setattr(orch_mod, "scan_all_cached", _cached_fail)

    adapter = _MockAdapter(router_response="specific")
    result = run_propose_for_ui(
        idea="校车",
        name="t3_scan_fail",
        platforms=["qidian", "fanqie"],
        llm_adapter=adapter,
        data_root=tmp_path,
    )
    assert result.status == "ok"
    # 仍有创作规律 + 完整 markdown(降级产出)
    assert result.craft["markdown"]
    assert result.markdown


# ---------------------------------------------------------------------------
# T3.4 诚实声明来自常量(D-67)
# ---------------------------------------------------------------------------


def test_honesty_note_equals_constant(tmp_path: Path):
    """result.honesty_note 必须 == propose.prompts._HONESTY_NOTE 常量(无论 source)。"""
    adapter = _MockAdapter(router_response="specific")
    result = run_propose_for_ui(
        idea="x",
        name="t3_honesty",
        platforms=["qidian"],
        llm_adapter=adapter,
        data_root=tmp_path,
    )
    assert result.honesty_note == _HONESTY_NOTE
    # SPECIFIC 路径的 markdown 里也含此声明
    assert _HONESTY_NOTE in result.markdown


# ---------------------------------------------------------------------------
# T3.5 cost_log 写入 + 落盘路径约定
# ---------------------------------------------------------------------------


def test_cost_log_writes_correct_stages_for_specific_path(tmp_path: Path):
    """SPECIFIC 路径 cost_log 含 router/tropes/redblue/craft 四 stage。"""
    adapter = _MockAdapter(router_response="specific")
    run_propose_for_ui(
        idea="校车进秘境",
        name="t3_costlog_specific",
        platforms=["qidian"],
        llm_adapter=adapter,
        data_root=tmp_path,
    )
    cost_log = tmp_path / "t3_costlog_specific" / "logs" / "cost_log.csv"
    assert cost_log.exists()
    content = cost_log.read_text(encoding="utf-8")
    assert "router" in content
    assert "tropes" in content
    assert "redblue" in content
    assert "craft" in content


def test_out_path_follows_p7_2_convention(tmp_path: Path):
    """落盘路径必须是 data/<name>/proposal/proposal_<YYYYMMDD-HHMMSS>.md。"""
    import re

    adapter = _MockAdapter(router_response="specific")
    result = run_propose_for_ui(
        idea="校车",
        name="t3_path",
        platforms=["qidian"],
        llm_adapter=adapter,
        data_root=tmp_path,
    )
    out = Path(result.out_path)
    assert out.exists()
    # 形如 data/t3_path/proposal/proposal_20260703-120000.md
    pattern = re.compile(r"proposal_\d{8}-\d{6}\.md$")
    assert pattern.match(out.name), f"文件名 {out.name} 不符合 P7-2 约定"
    assert out.parent == tmp_path / "t3_path" / "proposal"
