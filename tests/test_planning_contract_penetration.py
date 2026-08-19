"""规划合同：Writer 与 Editor 真实消息穿透测试。

验证已批规划件的埋词能穿透到 LLM 调用边界：
- Writer 穿透：埋词在 _call_with_retry 收到的 messages 中（精确截断 writer 边界）
- Editor 穿透：埋词在 adapter.generate 收到的 messages 中

全 mock，零烧钱。
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from biyu.pipeline import generate_chapter, _call_with_retry
from biyu.editor.editor import review_chapter


# ---------------------------------------------------------------------------
# 专用异常：精确截断 Writer 边界
# ---------------------------------------------------------------------------

class _WriterBoundaryCaptured(Exception):
    """Writer 边界捕获后主动截断流水线的专用异常。"""
    pass


# ---------------------------------------------------------------------------
# Stub Adapter for Editor test
# ---------------------------------------------------------------------------

class StubResponse:
    def __init__(self, text="", cost=0.0, reasoning="", raw=None,
                 tool_calls=None, finish_reason="stop"):
        self.text = text
        self.cost = cost
        self.reasoning_content = reasoning
        self.raw = raw or {"choices": [{"message": {"content": text}}]}
        self.finish_reason = finish_reason
        if tool_calls:
            self.raw["choices"][0]["message"]["tool_calls"] = tool_calls


class StubAdapter:
    """Records calls and returns scripted responses."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    async def generate(self, messages, **kwargs):
        self.calls.append({"messages": messages, "kwargs": kwargs})
        if self._responses:
            return self._responses.pop(0)
        return StubResponse(text='{"issues": []}')


def _make_submit_review_call(issues, confidence="high"):
    """构造一个 submit_review tool call。"""
    import json
    args = json.dumps({"issues": issues, "confidence": confidence}, ensure_ascii=False)
    return [{
        "id": "call_submit",
        "type": "function",
        "function": {"name": "submit_review", "arguments": args},
    }]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def siwanghuisu_book_with_approved_planning(tmp_path):
    """创建含已批规划件的 siwanghuisu 书目录（复用真实夹具）。"""
    # 书级配置
    (tmp_path / "book.json").write_text(
        '{"title": "死亡回复", "genre": "xuanhuan", "chapter_target_words": 5000}',
        encoding="utf-8",
    )
    (tmp_path / "outline.md").write_text("# 第99章 测试章\n", encoding="utf-8")
    (tmp_path / "characters.yaml").write_text(
        "characters:\n  - name: 张今空\n",
        encoding="utf-8",
    )
    (tmp_path / "worldbook.yaml").write_text(
        "facts:\n  - 测试设定\n",
        encoding="utf-8",
    )

    # 复用真实夹具作为已批规划件
    fixtures_dir = Path(__file__).parent.parent / "tests" / "fixtures"
    planning_fixture = fixtures_dir / "planning_ch99.md"
    planning_content = planning_fixture.read_text(encoding="utf-8")

    # 已批规划件（含埋词 规划埋词唯一词ABC987）
    logs_dir = tmp_path / "logs" / "ch99"
    logs_dir.mkdir(parents=True, exist_ok=True)
    (logs_dir / "planning.md").write_text(planning_content, encoding="utf-8")

    # 章节 outline 文件（必需）
    outlines_dir = tmp_path / "outlines"
    outlines_dir.mkdir(parents=True, exist_ok=True)
    (outlines_dir / "ch99.md").write_text(
        "# 第99章 测试章\n\n测试章细纲。\n",
        encoding="utf-8",
    )

    # 章节
    ch_dir = tmp_path / "chapters" / "_pending"
    ch_dir.mkdir(parents=True, exist_ok=True)
    (ch_dir / "ch99.md").write_text(
        "第99章测试内容\n张今空走进了镇异局。\n",
        encoding="utf-8",
    )

    return tmp_path


# ---------------------------------------------------------------------------
# Writer 穿透测试：精确截断 Writer 边界
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_writer_real_call_with_approved_planning(siwanghuisu_book_with_approved_planning):
    """Writer 穿透：实际调用 generate_chapter，以 adapter identity 精确截断 Writer 边界。

    此测试走真实生产路径：
    1. 调用 generate_chapter（非 mock）
    2. 已批 planning 经现役 build_writer_prompt_v4 进入生产代码
    3. registry 返回独立的 writer_adapter（identity 可识别）
    4. monkeypatch _call_with_retry 以 adapter identity 确认是 writer
    5. 在真实 messages 内断言埋词后抛 _WriterBoundaryCaptured 主动截断
    6. 测试外围用 pytest.raises 精确接住

    不是复刻拼接逻辑：未调用 build_writer_prompt_v4，未解析 prompt 字符串，
    而是捕获生产代码真实调用 _call_with_retry 时的 messages 参数（按 adapter identity 识别）。
    """
    book_dir = siwanghuisu_book_with_approved_planning

    # registry 返回独立的 writer_adapter（identity 可识别）
    writer_adapter = MagicMock()  # 独立实例，用于 identity 确认
    editor_adapter = MagicMock()  # 另一实例，避免误捕获

    async def mock_call_with_retry(adapter, messages, **kwargs):
        """以 adapter identity 确认是 writer 后，断言埋词并主动截断。"""
        # 精确识别：只处理 writer_adapter
        if adapter is not writer_adapter:
            # 不是 writer，让原始逻辑处理（会调用 adapter.generate）
            class R:
                text = "mock response"
                cost = 0.001
            return R()

        # 确认是 writer_adapter：断言埋词在 messages 中
        messages_str = " ".join(m.get("content", "") for m in messages)
        assert "规划埋词唯一词ABC987" in messages_str, (
            "埋词 '规划埋词唯一词ABC987' 应在 Writer 的 messages 中。"
            "这证明已批规划件经 build_writer_prompt_v4 真实穿透到了 LLM 调用边界。"
        )

        # 埋词验证通过：主动截断流水线
        raise _WriterBoundaryCaptured("Writer 边界已捕获，埋词验证通过")

    # Monkeypatch _call_with_retry（真实 seam）
    with patch("biyu.pipeline._call_with_retry", side_effect=mock_call_with_retry):
        # Mock adapter 返回假响应（避免真实 LLM 调用）
        writer_adapter.generate = AsyncMock()
        writer_adapter.generate.return_value = MagicMock(
            text="第99章测试正文",
            cost=0.001,
        )
        editor_adapter.generate = AsyncMock()
        editor_adapter.generate.return_value = MagicMock(
            text="{}",
            cost=0.001,
        )

        # Mock registry 让 generate_chapter 能获取 adapter
        with patch("biyu.pipeline.get_registry") as mock_registry:
            registry_instance = MagicMock()

            def get_adapter_for_stage(stage, override=None):
                """返回独立 adapter 实例（identity 可识别）。"""
                if stage == "writer":
                    return writer_adapter
                elif stage == "planner":
                    planner_mock = MagicMock()
                    planner_mock.generate = AsyncMock()
                    planner_mock.generate.return_value = MagicMock(
                        text="planning response",
                        cost=0.001,
                    )
                    return planner_mock
                else:
                    return editor_adapter

            registry_instance.get_adapter_for_stage = get_adapter_for_stage
            registry_instance.get_pipeline_config.return_value = {
                "writer": "v3",
                "planner": "r1",
            }
            mock_registry.return_value = registry_instance

            # Mock 其他依赖（避免写入文件等副作用）
            with patch("biyu.pipeline._log_cost"), \
                 patch("biyu.pipeline._write_long_run_csv"), \
                 patch("biyu.pipeline._run_anchor_loop") as mock_anchor:

                mock_anchor.return_value = ("skeleton", {"stats": {"total": 0}})

                # 实际调用 generate_chapter（走真实生产路径）
                # 预期会抛出 _WriterBoundaryCaptured
                with pytest.raises(_WriterBoundaryCaptured) as exc_info:
                    await generate_chapter(
                        book_dir=book_dir,
                        chapter_num=99,
                        prompt_version="v4",
                    )

                # 验证异常消息
                assert "Writer 边界已捕获，埋词验证通过" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Editor 穿透测试：实际调用 review_chapter
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_editor_real_call_with_approved_planning(siwanghuisu_book_with_approved_planning):
    """Editor 穿透：实际调用 review_chapter，埋词应在 adapter.generate 收到的 messages 中。

    此测试走真实生产路径：
    1. 调用 review_chapter(planning=埋词夹具)（非 mock）
    2. planning 经 build_editor_user_prompt 进入生产代码
    3. StubAdapter 捕获 adapter.generate 的 messages
    4. 断言埋词在 messages 中

    不是复刻拼接逻辑：未调用 build_editor_user_prompt，未解析 prompt 字符串，
    而是捕获生产代码真实调用 adapter.generate 时的 messages 参数。
    """
    book_dir = siwanghuisu_book_with_approved_planning

    # 读取含埋词的规划件
    fixtures_dir = Path(__file__).parent.parent / "tests" / "fixtures"
    planning_fixture = fixtures_dir / "planning_ch99.md"
    planning_content = planning_fixture.read_text(encoding="utf-8")

    # 构造含埋词的 planning 参数
    planning_with_baici = planning_content  # 含 规划埋词唯一词ABC987

    # 构造 Editor 返回（含 submit_review tool call）
    submit_resp = StubResponse(
        text="done",
        raw={"choices": [{"message": {
            "content": "done",
            "tool_calls": _make_submit_review_call([]),  # 空审读
        }}]},
    )

    # StubAdapter 记录调用
    adapter = StubAdapter([submit_resp])

    # 实际调用 review_chapter（走真实生产路径）
    result = await review_chapter(
        chapter_num=99,
        chapter_text="第99章测试内容\n张今空走进了镇异局。\n",
        book_dir=book_dir,
        adapter=adapter,
        planning=planning_with_baici,  # 含埋词的规划件
        max_tool_rounds=0,  # 只一轮，简化测试
    )

    # 断言：adapter.generate 被调用
    assert len(adapter.calls) > 0, "adapter.generate 应被调用至少一次"

    # 断言：埋词在 Editor 的 messages 中
    found_baici = False
    for call in adapter.calls:
        messages = call["messages"]
        messages_str = " ".join(m.get("content", "") for m in messages)
        if "规划埋词唯一词ABC987" in messages_str:
            found_baici = True
            break

    assert found_baici, (
        "埋词 '规划埋词唯一词ABC987' 应在 Editor 的 messages 中。"
        "这证明已批规划件经 build_editor_user_prompt 真实穿透到了 LLM 调用边界。"
    )

    # 验证 result 结构正常
    assert result is not None
