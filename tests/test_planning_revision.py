"""2026-10 按作者意见修订:网页导演的反馈回路。

契约:POST /architect 带 {feedback} → 基于已有方案修订;无方案时明确拒绝;
落盘 source 标「按作者意见修订」;不带 feedback 行为不变。
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest


VALID_PLAN = """# 第九章 创作者细纲

## 必检项
- **必须发生**：姜聆当众复述登记簿结论
- **必须不发生**：不揭晓回溯原因
- **结尾状态**：马文把封存刀放上验尸台
- **信息层级**：先公开追问，再私下识刀
"""


@pytest.fixture
def plan_book(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from biyu.ui import workbench

    book = tmp_path / "Book"
    (book / "outlines").mkdir(parents=True)
    (book / "logs" / "ch9").mkdir(parents=True)
    (book / "book.json").write_text(
        '{"id":"book","title":"Book","genre":"dushi"}', encoding="utf-8"
    )
    (book / "outlines" / "ch9.md").write_text("第九章细纲", encoding="utf-8")
    monkeypatch.setattr(workbench, "_book_dir", lambda _book: book)
    monkeypatch.setattr(workbench, "_web_architect_enabled", lambda: True)
    return book


class _FakeResult:
    def __init__(self, text: str) -> None:
        self.text = text
        self.cost = 0.0
        self.status = "ok"


def test_revision_requires_existing_plan(plan_book: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from biyu.ui import workbench
    from fastapi import HTTPException

    # 不 mock _call_web_architect:无方案拦截发生在它内部的修订前言构建处
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            workbench.generate_planning_with_architect("Book", 9, feedback="戏核改成当众立威")
        )
    assert exc_info.value.status_code == 400
    assert "还没有可修订的方案" in exc_info.value.detail


def test_revision_passes_feedback_and_marks_source(plan_book: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from biyu.ui import workbench

    (plan_book / "logs" / "ch9" / "planning.md").write_text(
        "status: 待批\nsource: 导演产出\n" + VALID_PLAN, encoding="utf-8"
    )
    captured: dict = {}

    async def fake_call(book_dir, chapter, feedback=""):
        captured["feedback"] = feedback
        return _FakeResult(VALID_PLAN)

    monkeypatch.setattr(workbench, "_call_web_architect", fake_call)
    result = asyncio.run(
        workbench.generate_planning_with_architect("Book", 9, feedback="戏核改成当众立威")
    )
    assert result["state"] == "draft"
    assert captured["feedback"] == "戏核改成当众立威"
    written = (plan_book / "logs" / "ch9" / "planning.md").read_text(encoding="utf-8")
    assert "source: 按作者意见修订" in written


def test_call_web_architect_builds_revision_preamble(plan_book: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """带 feedback 时,发给模型的 prompt 含作者意见/原方案/修订规则三段。"""
    from biyu.ui import workbench

    (plan_book / "logs" / "ch9" / "planning.md").write_text(
        "status: 待批\nsource: 导演产出\n" + VALID_PLAN, encoding="utf-8"
    )
    prompts: list[str] = []

    class _Guarded:
        text = VALID_PLAN
        cost = 0.0
        degraded = False

    async def fake_guarded(self, messages, fallback_adapter=None, **kwargs):
        prompts.append(messages[0]["content"])
        return _Guarded()

    class _Registry:
        def get_feature(self, _name: str) -> bool:
            return False

        def get_adapter_for_stage(self, stage: str):
            class _Primary:
                max_tokens = 8192

            return _Primary()

    monkeypatch.setattr(workbench, "get_registry", lambda: _Registry())
    monkeypatch.setattr(
        "biyu.pipeline._degraded_fallback_adapter", lambda registry: None
    )
    monkeypatch.setattr(
        "biyu.llm.base.LLMAdapter.generate_guarded", fake_guarded
    )
    asyncio.run(
        workbench._call_web_architect(plan_book, 9, feedback="结尾钩子换成威胁信号")
    )
    assert prompts, "模型未被调用"
    prompt = prompts[0]
    assert "【修订任务】" in prompt
    assert "## 作者意见(逐条落实)" in prompt and "结尾钩子换成威胁信号" in prompt
    assert "## 原方案(修订基础)" in prompt and "姜聆当众复述登记簿结论" in prompt
    assert "修订规则" in prompt
    # 原方案头两行(status/source)不应进入修订基础
    assert "status: 待批" not in prompt.split("修订规则")[0].split("原方案(修订基础)")[1]


def test_no_feedback_keeps_original_source(plan_book: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from biyu.ui import workbench

    async def fake_call(book_dir, chapter, feedback=""):
        assert feedback == ""
        return _FakeResult(VALID_PLAN)

    monkeypatch.setattr(workbench, "_call_web_architect", fake_call)
    asyncio.run(workbench.generate_planning_with_architect("Book", 9))
    written = (plan_book / "logs" / "ch9" / "planning.md").read_text(encoding="utf-8")
    assert "source: 导演产出" in written


def test_rejected_plan_keeps_text_readable(plan_book: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """2026-10 拒收版可读:必检项不全被拒时,原文随状态落盘供页面只读展示。"""
    from biyu.ui import workbench

    nl = chr(10)
    incomplete = nl.join(
        line for line in VALID_PLAN.splitlines() if "必须不发生" not in line
    )

    async def fake_call(book_dir, chapter, feedback=""):
        return _FakeResult(incomplete)

    monkeypatch.setattr(workbench, "_call_web_architect", fake_call)
    result = asyncio.run(workbench.generate_planning_with_architect("Book", 9))
    assert result["state"] == "rejected"
    assert "必须不发生" in result["missing_labels"]
    assert "姜聆当众复述登记簿结论" in result["text"]
    state = workbench._read_architect_state(plan_book, 9)
    assert state["state"] == "rejected"
    assert "姜聆当众复述登记簿结论" in state["text"]
