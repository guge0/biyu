"""S-4A — 工具调用循环(loop.py)单测:FakeAdapter 脚本化 tool_calls,零真实调用。

覆盖(工单测试节):单工具→回答;多步;未知工具;坏参数 JSON;max_steps 截止;
run 工具只登记不执行;模型异常 → error 事件;成本累计。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from biyu.agent.loop import run_agent_turn
from biyu.llm.base import LLMResponse
from biyu.llm.glm import LLMError

from tests.test_agent_tools import make_book


class FakeAdapter:
    """按脚本顺序吐响应;记录每次 generate 收到的 messages/kwargs。"""

    def __init__(self, script: list):
        self.script = list(script)
        self.calls: list[tuple[list[dict], dict]] = []
        self.max_tokens = 1000

    async def generate(self, messages, **kwargs):
        self.calls.append(([dict(m) for m in messages], dict(kwargs)))
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def resp(text="", tool_calls=None, cost=0.0):
    return LLMResponse(
        text=text, model="fake", cost=cost,
        finish_reason="tool_calls" if tool_calls else "stop",
        tool_calls=tool_calls,
    )


def tc(name: str, arguments: str, call_id: str = "call_1"):
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": arguments}}


@pytest.fixture
def data_root(tmp_path: Path) -> Path:
    make_book(tmp_path)
    return tmp_path


async def collect(adapter, data_root: Path, message="查一下第 1 章", **kwargs):
    return [
        event
        async for event in run_agent_turn(
            adapter, [], message, book="MyBook", data_root=data_root, **kwargs,
        )
    ]


@pytest.mark.asyncio
async def test_single_tool_then_answer(data_root: Path):
    adapter = FakeAdapter([
        resp(tool_calls=[tc("read_chapter", '{"chapter": 1}', "call_a")]),
        resp(text="第一章讲林砚推门。"),
    ])
    events = await collect(adapter, data_root)
    types = [e["type"] for e in events]
    assert types == ["tool_start", "tool_result", "text", "done"]

    start = events[0]
    assert start["name"] == "read_chapter"
    assert start["tool_call_id"] == "call_a"
    result = events[1]
    assert result["tool_call_id"] == "call_a"
    assert "林砚推门进来" in result["content"]
    assert events[2]["content"] == "第一章讲林砚推门。"

    # 第二次调用时,上下文含 assistant(tool_calls) 与 tool 结果
    second_messages = adapter.calls[1][0]
    assistant = [m for m in second_messages if m["role"] == "assistant"][-1]
    assert assistant["tool_calls"][0]["id"] == "call_a"
    tool_msg = [m for m in second_messages if m["role"] == "tool"][-1]
    assert tool_msg["tool_call_id"] == "call_a"
    assert "林砚推门进来" in tool_msg["content"]
    # tools 参数发给了模型
    assert adapter.calls[0][1]["tools"][0]["function"]["name"] == "list_books"


@pytest.mark.asyncio
async def test_multi_step_chain(data_root: Path):
    adapter = FakeAdapter([
        resp(tool_calls=[tc("chapter_status", '{"chapter": 3}', "c1")]),
        resp(tool_calls=[tc("read_chapter", '{"chapter": 3}', "c2")]),
        resp(text="汇总回答。"),
    ])
    events = await collect(adapter, data_root)
    assert [e["type"] for e in events] == [
        "tool_start", "tool_result",
        "tool_start", "tool_result",
        "text", "done",
    ]
    assert events[-1]["steps"] == 3
    assert len(adapter.calls) == 3


@pytest.mark.asyncio
async def test_unknown_tool_returned_to_model_not_crash(data_root: Path):
    adapter = FakeAdapter([
        resp(tool_calls=[tc("approve_chapter", '{"chapter": 1}')]),  # 禁区动作=未知工具
        resp(text="我没有批准权限。"),
    ])
    events = await collect(adapter, data_root)
    result = next(e for e in events if e["type"] == "tool_result")
    assert "未知工具" in result["content"]
    # 禁区动作只能以「未知工具」名义出现,不得混进可用工具清单
    assert "approve" not in result["content"].split("可用工具")[-1]
    # 错误作为 tool 消息回了模型,第二轮正常收尾
    tool_msg = [m for m in adapter.calls[1][0] if m["role"] == "tool"][-1]
    assert "未知工具" in tool_msg["content"]
    assert events[-1]["type"] == "done"


@pytest.mark.asyncio
async def test_bad_arguments_json_returned_to_model(data_root: Path):
    adapter = FakeAdapter([
        resp(tool_calls=[tc("read_chapter", '{chapter: 1}')]),  # 非 JSON
        resp(text="改用正确参数重试。"),
    ])
    events = await collect(adapter, data_root)
    result = next(e for e in events if e["type"] == "tool_result")
    assert "参数不是合法 JSON" in result["content"]
    assert events[-1]["type"] == "done"


@pytest.mark.asyncio
async def test_max_steps_forces_wrap_up(data_root: Path):
    adapter = FakeAdapter([
        resp(tool_calls=[tc("list_books", "{}", f"c{i}")]) for i in range(10)
    ])
    events = await collect(adapter, data_root, max_steps=3)
    # 3 步模型调用,每步 1 个工具;然后强制收尾文本 + done
    starts = [e for e in events if e["type"] == "tool_start"]
    assert len(starts) == 3
    assert len(adapter.calls) == 3  # 第 4 次不再调模型
    texts = [e for e in events if e["type"] == "text"]
    assert any("步数上限" in e["content"] for e in texts)
    assert events[-1]["type"] == "done" and events[-1]["steps"] == 3


@pytest.mark.asyncio
async def test_run_tool_emits_pending_action_without_execution(data_root: Path):
    adapter = FakeAdapter([
        resp(tool_calls=[tc("request_write", '{"chapter": 4}', "c9")]),
        resp(text="已替你提交写章申请。"),
    ])
    events = await collect(adapter, data_root)
    pending = next(e for e in events if e["type"] == "pending_action")
    assert pending["action_id"] == "write"
    assert pending["chapter"] == 4
    assert pending["status"] == "pending"
    assert "预估" in pending["estimate"]
    # 只登记,没执行
    from biyu.ui.cli_executor import running_action

    assert running_action("MyBook", 4) is None
    assert not (data_root / "MyBook" / "chapters" / "_pending" / "ch4.md").exists()


@pytest.mark.asyncio
async def test_error_event_on_model_failure(data_root: Path):
    adapter = FakeAdapter([LLMError(401, "Authentication Fails")])
    events = await collect(adapter, data_root)
    assert [e["type"] for e in events] == ["error"]
    assert "401" in events[0]["message"]


@pytest.mark.asyncio
async def test_cost_accumulated_in_done(data_root: Path):
    adapter = FakeAdapter([
        resp(tool_calls=[tc("list_books", "{}")], cost=0.5),
        resp(text="好了。", cost=0.25),
    ])
    events = await collect(adapter, data_root)
    assert events[-1] == {"type": "done", "cost": 0.75, "steps": 2}
