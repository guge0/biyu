"""S-4A 责编助手 API — /api/agent/*(引擎无 UI;界面另由 Claude 设计)。

端点:
- POST /api/agent/sessions               → 复用 ChatManager,role="agent"
- POST /api/agent/sessions/{id}/messages → SSE 流出 run_agent_turn 的事件;
                                           会话历史(含工具调用)写回 JSONL
- GET  /api/agent/pending?book=          → 待确认动作列表
- POST /api/agent/pending/{id}/confirm   → 标记 confirmed 并复用 cli_executor
                                            的现有执行路径启动(SSE 日志流)
- POST /api/agent/pending/{id}/cancel    → 标记 cancelled

现有 /api/chat/* 与 chat_tools 关键词路由保持不动。
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from biyu.agent.confirmations import PendingActionError, PendingActionStore
from biyu.agent.loop import run_agent_turn
from biyu.agent.tools import ToolInputError, safe_book_dir
from biyu.config import get_data_root
from biyu.ui.chat import ChatManager
from biyu.ui.cli_executor import execute
from biyu.ui.cost_log import write_cost_log
from biyu.ui.llm_error_copy import humanize_llm_error
from biyu.ui.routes import ChatSendRequest, _get_chat_adapter, _resolve_book_identity
from biyu.web.sse import sse_generator

logger = logging.getLogger("biyu.ui.agent_routes")

router = APIRouter(prefix="/api/agent", tags=["agent"])


class CreateAgentSessionRequest(BaseModel):
    book: str = Field(..., description="书名(可传 book_id 或目录名)")
    source: str = Field("production", description="会话来源:production(默认)/ test")


def _get_store() -> PendingActionStore:
    return PendingActionStore(get_data_root())


def _agent_book_dir_name(book: str) -> str:
    """把 book(id 或目录名)解析成目录名,并做穿越校验;坏名字 400。"""
    dir_name, _book_id = _resolve_book_identity(book)
    try:
        safe_book_dir(dir_name, Path(get_data_root()))
    except ToolInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return dir_name


# ---------------------------------------------------------------------------
# 会话
# ---------------------------------------------------------------------------


@router.post("/sessions")
def create_agent_session(req: CreateAgentSessionRequest) -> dict[str, Any]:
    """新建责编助手会话(复用 ChatManager,role="agent")。"""
    dir_name = _agent_book_dir_name(req.book)
    _, book_id = _resolve_book_identity(req.book)
    mgr = ChatManager(data_root=get_data_root())
    sid = mgr.new_session(dir_name, "agent", book_id=book_id, source=req.source)
    session = mgr.get_session(sid)
    assert session is not None  # 刚创建应有
    return session


# ---------------------------------------------------------------------------
# 历史(JSONL → OpenAI messages)
# ---------------------------------------------------------------------------


def _history_messages(session_messages: list[dict]) -> list[dict]:
    """把会话 JSONL 消息转成可发给模型的 messages(含 assistant.tool_calls / role=tool)。"""
    out: list[dict] = []
    for msg in session_messages:
        role = msg.get("role")
        if role == "user":
            out.append({"role": "user", "content": str(msg.get("content", ""))})
        elif role == "assistant":
            entry = {"role": "assistant", "content": str(msg.get("content", ""))}
            tool_call = msg.get("tool_call")
            raw_calls = tool_call.get("tool_calls") if isinstance(tool_call, dict) else None
            if isinstance(raw_calls, list) and raw_calls:
                # arguments 必须是合法 JSON 字符串;历史里的坏串换 "{}" 再发
                cleaned = []
                for call in raw_calls:
                    if not isinstance(call, dict):
                        continue
                    function = call.get("function") if isinstance(call.get("function"), dict) else {}
                    arguments = function.get("arguments", "{}")
                    if not isinstance(arguments, str):
                        arguments = json.dumps(arguments, ensure_ascii=False)
                    try:
                        json.loads(arguments)
                    except json.JSONDecodeError:
                        arguments = "{}"
                    cleaned.append({
                        "id": call.get("id", ""),
                        "type": call.get("type", "function"),
                        "function": {
                            "name": function.get("name", ""),
                            "arguments": arguments,
                        },
                    })
                if cleaned:
                    entry["tool_calls"] = cleaned
            out.append(entry)
        elif role == "tool":
            tool_call = msg.get("tool_call") if isinstance(msg.get("tool_call"), dict) else {}
            out.append({
                "role": "tool",
                "tool_call_id": str(tool_call.get("tool_call_id", "")),
                "content": str(msg.get("content", "")),
            })
    return out


def _rebuild_raw_call(name: str, args: object, call_id: object) -> dict:
    """从 tool_start 事件字段重建 OpenAI 原始 tool_call(会话历史用)。"""
    arguments = args if isinstance(args, str) else json.dumps(args or {}, ensure_ascii=False)
    return {
        "id": str(call_id or ""),
        "type": "function",
        "function": {"name": str(name), "arguments": arguments},
    }


# ---------------------------------------------------------------------------
# 发消息(SSE)
# ---------------------------------------------------------------------------


@router.post("/sessions/{session_id}/messages")
async def post_agent_message(session_id: str, req: ChatSendRequest) -> StreamingResponse:
    """跑一轮责编助手(模型 ↔ 工具循环),SSE 流出事件并落会话历史。"""
    data_root = get_data_root()
    mgr = ChatManager(data_root=data_root)
    session = mgr.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    if session.get("role") != "agent":
        raise HTTPException(status_code=400, detail="该会话不是责编助手会话")
    book = str(session.get("book", ""))
    history = _history_messages(session.get("messages", []))
    mgr.add_message(session_id, "user", req.content)

    queue: asyncio.Queue = asyncio.Queue()

    async def _run() -> None:
        total_cost = 0.0
        try:
            adapter = _get_chat_adapter()
            if adapter is None:
                raise RuntimeError("没有可用的模型连接:请先在「设置 → 连接」保存 Key")

            turn_rows: list[dict] = []
            current_step: int | None = None
            text_parts: list[str] = []
            raw_calls: list[dict] = []
            tool_rows: list[dict] = []

            def _flush_step() -> None:
                nonlocal current_step, text_parts, raw_calls, tool_rows
                if raw_calls or text_parts:
                    turn_rows.append({
                        "role": "assistant",
                        "content": "".join(text_parts),
                        "tool_call": {"tool_calls": raw_calls} if raw_calls else None,
                    })
                turn_rows.extend(tool_rows)
                text_parts, raw_calls, tool_rows = [], [], []
                current_step = None

            async for event in run_agent_turn(
                adapter, history, req.content,
                book=book, data_root=data_root, session_id=session_id,
            ):
                etype = event.get("type")
                if etype == "text":
                    # 模型在同一步里先说话再调工具:text 归入当前步;
                    # 紧跟前一步工具结果之后的 text 属于新一步:先落前一步。
                    if current_step is not None:
                        _flush_step()
                    text_parts.append(str(event.get("content", "")))
                elif etype == "tool_start":
                    step = int(event.get("step") or 0)
                    if current_step is not None and step != current_step:
                        _flush_step()
                    current_step = step
                    raw_calls.append(_rebuild_raw_call(
                        event.get("name", ""), event.get("args"), event.get("tool_call_id"),
                    ))
                elif etype == "tool_result":
                    tool_rows.append({
                        "role": "tool",
                        "content": str(event.get("content", "")),
                        "tool_call": {
                            "tool_call_id": str(event.get("tool_call_id", "")),
                            "name": str(event.get("name", "")),
                        },
                    })
                elif etype == "done":
                    _flush_step()
                    total_cost = float(event.get("cost") or 0.0)
                if etype == "error":
                    _flush_step()
                    message = humanize_llm_error(
                        None, raw=str(event.get("message", "")),
                        default=str(event.get("message", "")),
                    )
                    await queue.put({"type": "error", "message": message})
                else:
                    await queue.put(event)
            _flush_step()
            # 写会话历史:最后一行 assistant 记成本
            last_assistant_index = max(
                (i for i, row in enumerate(turn_rows) if row["role"] == "assistant"),
                default=None,
            )
            for index, row in enumerate(turn_rows):
                mgr.add_message(
                    session_id, row["role"], row["content"],
                    tool_call=row["tool_call"],
                    cost=total_cost if index == last_assistant_index else None,
                )
            if total_cost > 0:
                try:
                    write_cost_log(
                        task="agent", book=book, session=session_id,
                        cost=total_cost,
                        model=getattr(adapter, "model_name", ""),
                    )
                except Exception:
                    logger.warning("写 cost_log 失败", exc_info=True)
        except Exception as exc:
            logger.exception("agent SSE 异常")
            await queue.put({
                "type": "error",
                "message": humanize_llm_error(exc, default=str(exc)),
            })
        finally:
            await queue.put(None)

    asyncio.create_task(_run())
    return StreamingResponse(sse_generator(queue), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# 待确认动作
# ---------------------------------------------------------------------------


@router.get("/pending")
def list_pending(
    book: str = Query(..., description="书名(可传 book_id 或目录名)"),
    status: Optional[str] = Query(None, description="按状态过滤:pending/confirmed/cancelled"),
) -> dict[str, Any]:
    """列出一本书的待确认动作(默认全部,带各自状态)。"""
    dir_name = _agent_book_dir_name(book)
    store = _get_store()
    return {"pending": store.list_actions(book=dir_name, status=status)}


@router.post("/pending/{action_record_id}/confirm")
async def confirm_pending(action_record_id: str) -> StreamingResponse:
    """作者点了确认:标记 confirmed,并复用 cli_executor 的现有执行路径启动。"""
    store = _get_store()
    try:
        record = store.mark(action_record_id, "confirmed")
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PendingActionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    async def produce(queue: asyncio.Queue) -> None:
        try:
            async for event in execute(
                str(record["action_id"]),
                book=str(record["book"]),
                chapter=int(record["chapter"]),
                confirmed=True,  # 作者已通过确认卡确认
                extra={},
            ):
                await queue.put(event)
        except KeyError:
            await queue.put({"type": "error", "message": f"未知动作: {record['action_id']}"})
        finally:
            await queue.put(None)

    queue: asyncio.Queue = asyncio.Queue()
    asyncio.create_task(produce(queue))
    return StreamingResponse(sse_generator(queue), media_type="text/event-stream")


@router.post("/pending/{action_record_id}/cancel")
def cancel_pending(action_record_id: str) -> dict[str, Any]:
    """作者取消一条待确认动作。"""
    store = _get_store()
    try:
        record = store.mark(action_record_id, "cancelled")
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PendingActionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True, "action": record}
