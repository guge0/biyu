"""S-7d 工单第 1 条：花费漏记——每个调模型的地方都要落账（全部替身，零真实调用）。

对应修复：
- 工作台生成（force_pending）的编辑审读行从 editor_total 改为 editor：
  read_chapter_costs 跳过聚合行，此前整笔审读费从书内账消失；
- 设定格 AI 起草（cell_draft）写中央台账；
- 保真闸判定的重试/解析失败花费不再丢；
- 责编助手单轮中途失败时，已花掉的部分费用照记账。
"""
from __future__ import annotations

import asyncio
import csv
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


class _Resp:
    def __init__(self, text: str, cost: float = 0.0):
        self.text = text
        self.cost = cost
        self.degraded = False
        self.finish_reason = None
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0
        self.raw = {}
        self.reasoning_content = None
        self.tool_calls = None


def _write_cost_rows(book: Path, rows: list[list[str]]) -> None:
    path = book / "logs" / "cost_log.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestamp", "chapter", "stage", "cost_cny", "latency_s", "status"])
        writer.writerows(rows)


def _read_cost_rows(book: Path) -> list[dict]:
    with (book / "logs" / "cost_log.csv").open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


# ---------------------------------------------------------------------------
# 1) 工作台生成（force_pending）的编辑审读费要进书内账
# ---------------------------------------------------------------------------


def test_chapter_cost_counts_web_editor_row(tmp_path: Path) -> None:
    """单一 editor 行（无 per-round 行）必须被 read_chapter_costs 计入。"""
    from biyu.ui.cost_log import read_chapter_costs

    book = tmp_path / "Book"
    _write_cost_rows(book, [
        ["t1", 1, "architect", "0.1000", "12", "ok"],
        ["t2", 1, "writer", "0.4000", "60", "ok"],
        ["t3", 1, "editor", "0.0600", "30", "ok"],
    ])
    assert read_chapter_costs(book)[1] == pytest.approx(0.56)


def test_generation_estimate_includes_web_editor_rows(tmp_path: Path) -> None:
    """写章预估的历史口径同样要吃得到 editor 行（不再是 editor_total 专属）。"""
    from biyu.ui import action_estimate

    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "cost_log.csv").write_text(
        "timestamp,chapter,stage,cost_cny,latency_s,status\n"
        "t,1,writer,0.10,1,ok\n"
        "t,1,editor,0.10,1,ok\n"
        "t,2,writer,0.10,1,ok\n"
        "t,2,editor,0.10,1,ok\n",
        encoding="utf-8",
    )
    assert action_estimate._history_totals(tmp_path) == [pytest.approx(0.2), pytest.approx(0.2)]


class _EditorResult:
    def __init__(self, cost: float):
        self.cost = cost
        self.issues = []
        self.raw_response = ""
        self.parse_errors = []
        self.queries_used = []


@pytest.mark.asyncio
async def test_web_write_logs_editor_cost_as_counted_row(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """S-7 实跑差账根因：force_pending 审读只写 editor_total（聚合行，读取方跳过）→ 整笔漏记。"""
    import biyu.pipeline as pipeline

    book = tmp_path / "Book"
    book.mkdir()
    (book / "book.json").write_text("{}", encoding="utf-8")
    (book / "outlines").mkdir()
    (book / "outlines" / "ch1.md").write_text("# 第一章\n测试细纲。", encoding="utf-8")
    # 网页真实流程:导演步已批方案,写章时跳过 Architect(账上只剩 writer + editor)
    (book / "logs" / "ch1").mkdir(parents=True)
    (book / "logs" / "ch1" / "planning.md").write_text(
        "status: 已批\n# 第一章 创作者细纲\n测试方案。", encoding="utf-8",
    )

    registry = MagicMock()
    registry.get_feature = lambda name: False
    registry.get_pipeline_config.return_value = {
        "planner": "p", "writer": "w", "editor_enabled": True,
        "polish_enabled": False, "wenyan_enabled": False,
    }

    async def fake_generate(messages, **kwargs):
        return _Resp("这是一段测试正文，完整收尾。" * 120, cost=0.5)

    adapter = MagicMock()
    adapter.generate = fake_generate
    registry.get_adapter_for_stage.return_value = adapter
    registry.get_adapter.return_value = MagicMock()

    async def fake_review(**kwargs):
        return _EditorResult(cost=0.06)

    monkeypatch.setattr("biyu.editor.editor.review_chapter", fake_review)
    monkeypatch.setattr("biyu.git_helper.commit_chapter", lambda *a, **k: "deadbeef")
    monkeypatch.setattr(pipeline, "get_registry", lambda: registry)
    monkeypatch.setattr(pipeline, "load_merged_voiceprint", lambda _: {"text": ""})
    monkeypatch.setattr(pipeline, "sync_characters_from_yaml", lambda _: (0, 0))
    monkeypatch.setattr(pipeline, "load_characters_yaml", lambda _: [])
    monkeypatch.setattr(pipeline, "_build_context_block", lambda *args, **kwargs: ("", None))
    monkeypatch.setattr(pipeline, "read_all_truth_files", lambda _: {})

    result = await pipeline.generate_chapter(book, 1, force_pending=True)
    assert result.cost_cny >= 0.56

    rows = _read_cost_rows(book)
    editor_rows = [r for r in rows if r["stage"] in {"editor", "editor_total"}]
    assert editor_rows, "工作台生成的编辑审读必须落账"
    assert all(r["stage"] == "editor" for r in editor_rows), (
        "force_pending 审读行必须是可聚合的 editor；editor_total 会被 read_chapter_costs 跳过"
    )
    from biyu.ui.cost_log import read_chapter_costs

    assert read_chapter_costs(book)[1] == pytest.approx(0.56)


# ---------------------------------------------------------------------------
# 2) 设定格 AI 起草写中央台账
# ---------------------------------------------------------------------------


def test_cell_draft_writes_central_cost_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from biyu.ui.app import app

    book = tmp_path / "MyBook"
    book.mkdir()
    (book / "book.json").write_text('{"genre":"dushi"}', encoding="utf-8")

    class _Adapter:
        model_name = "fake-model"

        async def generate(self, messages, **kwargs):
            return _Resp("补一句设定。", cost=0.0123)

    monkeypatch.setattr("biyu.config.get_config_path", lambda: "x")
    monkeypatch.setattr("biyu.llm.ModelRegistry", lambda _p: object())
    monkeypatch.setattr("biyu.ui.model_alias.resolve_ui_adapter", lambda _reg: (_Adapter(), "v4_flash"))
    monkeypatch.setattr("biyu.ui.settings._book_dir", lambda _b: book)
    monkeypatch.setattr("biyu.ui.cost_log.get_data_root", lambda: tmp_path)

    resp = TestClient(app).post(
        "/api/settings/books/MyBook/cells/north_star/draft", json={"instruction": ""},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    with (tmp_path / "cost_log.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert any(
        r["task"] == "cell_draft" and float(r["cost"]) == pytest.approx(0.0123)
        for r in rows
    ), "设定格 AI 起草是真实的模型调用，必须写中央台账"


# ---------------------------------------------------------------------------
# 3) 保真闸判定：重试与解析失败的花费也要落账
# ---------------------------------------------------------------------------


class _FlakyJudgeAdapter:
    """按脚本吐 (text, cost)；模拟判定模型的两次调用。"""

    def __init__(self, script: list[tuple[str, float]]):
        self.script = list(script)

    async def generate(self, messages, **kwargs):
        text, cost = self.script.pop(0)
        resp = _Resp(text, cost=cost)
        return resp


def _fidelity_book(tmp_path: Path) -> tuple[Path, object]:
    from biyu.config import BookConfig

    book = tmp_path / "FBook"
    book.mkdir()
    return book, BookConfig(book)


_FIDELITY_OUTLINE = "# 第九章\n1. 姜聆当众复述登记簿结论\n2. 马文把封存刀放上验尸台\n"


@pytest.mark.asyncio
async def test_fidelity_judge_logs_retry_cost(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """第一次输出解析失败（钱已花）、第二次合格 → 两笔都要记进 fidelity_check。"""
    from biyu.ui import workbench

    book, cfg = _fidelity_book(tmp_path)
    adapter = _FlakyJudgeAdapter([
        ("这不是JSON", 0.0100),
        ('{"issues":[{"type":"丢失","detail":"姜聆没有复述"}]}', 0.0200),
    ])
    monkeypatch.setattr("biyu.pipeline._degraded_fallback_adapter", lambda _reg: adapter)

    issues, cost = await workbench._judge_outline_coverage(_FIDELITY_OUTLINE, "方案", MagicMock(), cfg, 9)
    assert any("姜聆" in item for item in issues)
    assert cost == pytest.approx(0.03)

    rows = _read_cost_rows(book)
    fidelity = [r for r in rows if r["stage"] == "fidelity_check"]
    assert fidelity and float(fidelity[0]["cost_cny"]) == pytest.approx(0.03)


@pytest.mark.asyncio
async def test_fidelity_judge_logs_cost_when_all_parse_fail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """两次都解析不了 → 流程 fail-open 放行，但已花的钱必须记账。"""
    from biyu.ui import workbench

    book, cfg = _fidelity_book(tmp_path)
    adapter = _FlakyJudgeAdapter([("坏输出甲", 0.0100), ("坏输出乙", 0.0200)])
    monkeypatch.setattr("biyu.pipeline._degraded_fallback_adapter", lambda _reg: adapter)

    issues, cost = await workbench._judge_outline_coverage(_FIDELITY_OUTLINE, "方案", MagicMock(), cfg, 9)
    assert issues == []

    rows = _read_cost_rows(book)
    fidelity = [r for r in rows if r["stage"] == "fidelity_check"]
    assert fidelity and float(fidelity[0]["cost_cny"]) == pytest.approx(0.03)


# ---------------------------------------------------------------------------
# 4) 责编助手：单轮中途失败时已花的部分费用照记账
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_error_event_carries_partial_cost(tmp_path: Path) -> None:
    from biyu.agent.loop import run_agent_turn
    from biyu.llm.glm import LLMError
    from tests.test_agent_loop import FakeAdapter, resp, tc
    from tests.test_agent_tools import make_book

    make_book(tmp_path)
    adapter = FakeAdapter([
        resp(tool_calls=[tc("list_books", "{}")], cost=0.4),
        LLMError(500, "Server Error"),
    ])
    events = [
        event
        async for event in run_agent_turn(adapter, [], "查一下", book="MyBook", data_root=tmp_path)
    ]
    error = events[-1]
    assert error["type"] == "error"
    assert error["cost"] == pytest.approx(0.4), "中途失败也要把已花费用带出来"


def test_agent_message_logs_partial_cost_on_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from biyu.llm.glm import LLMError
    from biyu.ui.app import app
    from tests.test_agent_routes import parse_sse, use_adapter
    from tests.test_agent_tools import make_book
    from tests.test_agent_loop import resp, tc

    make_book(tmp_path)
    monkeypatch.setattr("biyu.config.get_data_root", lambda: tmp_path)
    monkeypatch.setattr("biyu.ui.agent_routes.get_data_root", lambda: tmp_path)
    monkeypatch.setattr("biyu.ui.agent_routes.feature_enabled", lambda _name: True)
    monkeypatch.setattr("biyu.ui.cost_log.get_data_root", lambda: tmp_path)
    client = TestClient(app)

    use_adapter(client, monkeypatch, [
        resp(tool_calls=[tc("list_books", "{}")], cost=0.3),
        LLMError(500, "Server Error"),
    ])
    sid = client.post("/api/agent/sessions", json={"book": "MyBook"}).json()["id"]
    sse = client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "查一下"})
    assert any(e["type"] == "error" for e in parse_sse(sse.text))

    with (tmp_path / "cost_log.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    agent_rows = [r for r in rows if r["task"] == "agent"]
    assert agent_rows and float(agent_rows[0]["cost"]) == pytest.approx(0.3), (
        "单轮中途失败时已花的模型费也要写中央台账"
    )
