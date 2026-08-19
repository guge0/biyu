"""FastAPI 路由层(P8-M1 T5 + P8-M2.5 T7-3 + T3.2 + T5 + T5 改造 + P8-M3 T5+T6)

- GET  /api/env              → 环境章字典
- GET  /api/session          → 新建 session_id(进程内会话累计用)
- POST /api/propose          → 触发 propose 编排,返 ProposeUiResult(同步)
- POST /api/propose/stream   → T3.2 SSE 版,逐 stage 推送进度事件
- GET  /api/peak-hours       → 峰谷时段状态(T7-3,UI 成本条用)
- GET  /api/prompts/texts    → T5 改造(中枢裁定):主体提示词全文,读 prompt_texts_<date>.md 最新件
- GET  /api/prompts/inventory  → T5 辅:提示词索引(只读,markdown 全文)
- GET  /api/prompts/source     → T5 辅:提示词源码片段(只读)
- POST /api/chat/sessions       → T1 新建会话 | GET /api/chat/sessions → T1 会话列表
- GET  /api/chat/sessions/{id}  → T1 取会话(含消息) | DELETE → T1 软删除
- POST /api/chat/sessions/{id}/messages → T3(editor)/T4(director) SSE 占位 + 真实工具查询结果
- POST /api/chat/sessions/{id}/summarize → T5 收束纪要(生成+落盘)
- GET  /api/summaries?book=X         → T5 纪要列表
- GET  /api/summaries/{book}/{fn}    → T5 纪要查看
- POST /api/preferences → T6 存偏好(本书/通用二选)
- GET  /api/preferences → T6 偏好列表
- DELETE /api/preferences/{scope}/{entry_id} → T6 删除偏好

软顶拦截设计:orchestrator 内部已处理,路由层不重复。软顶触发时返 200 +
status="softcap_reached"(不 4xx —— 前端要拿 body 数据渲染确认弹窗)。
异常时返 500 + 一句人话(detail 字段),不暴露堆栈。

SSE 版本(T3.2):orchestrator 在 worker thread 跑(其内部 propose 函数用
asyncio.run,不能在运行中的 loop 里调)。on_progress 从 thread 触发,经
asyncio.run_coroutine_threadsafe 调度到主 loop 的 queue。

提示词接口(T5):严格只读,无 POST/PUT/DELETE;源码读取走白名单(只 src/biyu/
prompts/ 和 src/biyu/editor/,绝不读 config/ / .env / Key 文件)。
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from biyu.config import get_data_root, get_project_root
from biyu.llm import ModelRegistry
from biyu.ui.chat_tools import run_chat_tools, run_director_tools
from biyu.ui.env import read_env
from biyu.ui.naming import apply_name as _apply_name, generate_names as _generate_names
from biyu.ui.orchestrator import run_propose_for_ui
from biyu.ui.preferences import (
    delete_preference as _delete_pref,
    list_preferences,
    save_preference,
)
from biyu.ui.prompts_editor import PLACEHOLDER_FLAGS, build_director_messages, build_editor_messages
from biyu.ui.session import SessionCosts
from biyu.ui.chat import ChatManager
from biyu.ui.cost_log import write_cost_log
from biyu.ui.summarize import list_summaries, read_summary, save_editor_memo
from biyu.web.sse import sse_generator, make_event

logger = logging.getLogger("biyu.ui.routes")

router = APIRouter()

# 模块级会话成本累计单例(M1 不持久化,进程重启归零)
_costs = SessionCosts(softcap=2.0)


# ---------------------------------------------------------------------------
# T7-3 峰谷时段(D-81):DeepSeek 北京时段 9-12 / 14-18 高峰 2x
# ---------------------------------------------------------------------------

# 7 月 15 日起生效(老板通报,D-81;spec 验收 line 15)
_PEAK_EFFECTIVE_DATE = (7, 15)  # (month, day)
# 高峰时段窗口(小时,左闭右开)
_PEAK_WINDOWS = (
    (9, 12),    # 早高峰
    (14, 18),   # 下午高峰
)


def _get_now() -> datetime:
    """当前时间(包一层方便测试 monkeypatch)。默认 datetime.now()。"""
    return datetime.now()


def _is_peak_time(now: datetime) -> tuple[bool, str]:
    """判断给定时间是否在峰谷时段内,返 (is_peak, label)。

    - 7 月 15 日前:is_peak=False, label="即将生效(7 月 15 日起)"
    - 7 月 15 日后 + 在 9-12 / 14-18:is_peak=True, label="高峰 2x"
    - 其他时段:is_peak=False, label="平峰"
    """
    # 年度生效判断(只看月日,同年循环)
    effective_this_year = datetime(now.year, _PEAK_EFFECTIVE_DATE[0], _PEAK_EFFECTIVE_DATE[1])
    if now < effective_this_year:
        return False, "即将生效(7 月 15 日起,北京 9-12 / 14-18 高峰 2x)"

    hour = now.hour
    for start, end in _PEAK_WINDOWS:
        if start <= hour < end:
            return True, "高峰 2x(北京 9-12 / 14-18)"
    return False, "平峰(成本按标准价)"


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------


class ProposeRequest(BaseModel):
    idea: str = Field("", description="作者设想文本(可空)")
    name: Optional[str] = Field(None, description="书名/临时名")
    session_id: Optional[str] = Field(None, description="会话 ID(从 /api/session 拿)")
    confirm_over_softcap: bool = Field(
        False, description="作者已 confirm 软顶(前端弹框同意后置 True)"
    )
    force_refresh_scan: bool = Field(
        False, description="强制现扫榜单(忽略 ≤7 天缓存,T4 「重新扫榜」按钮触发)"
    )


# ---------------------------------------------------------------------------
# GET /api/env
# ---------------------------------------------------------------------------


@router.get("/api/env")
def get_env() -> dict[str, str]:
    """返回环境章信息(测试=灰 / 真书=红),前端右上渲染用。"""
    return read_env()


# ---------------------------------------------------------------------------
# GET /api/chat/mode — R5 T4.4 返回编辑部占位/真实模式(PLACEHOLDER_FLAGS)
# ---------------------------------------------------------------------------


@router.get("/api/chat/mode")
def get_chat_mode() -> dict[str, Any]:
    """返回责编/导演当前是占位模式(True=占位)还是真 LLM(False)。

    前端 editor.html placeholder-banner 据此显示:
    - 全 False → 绿条 "真实 LLM 模式"
    - 任一 True → 黄条 "占位模式(明细)"
    """
    editor_ph = bool(PLACEHOLDER_FLAGS.get("editor", True))
    director_ph = bool(PLACEHOLDER_FLAGS.get("director", True))
    if not editor_ph and not director_ph:
        level = "real"
        label = "真实 LLM 模式(责编+导演)"
    elif editor_ph and director_ph:
        level = "placeholder"
        label = "占位模式(责编+导演均未接真 LLM)"
    else:
        level = "mixed"
        # 标出哪个还在占位
        ph_roles = []
        if editor_ph: ph_roles.append("责编")
        if director_ph: ph_roles.append("导演")
        label = "混合模式(占位:" + "+".join(ph_roles) + ")"
    return {
        "editor_placeholder": editor_ph,
        "director_placeholder": director_ph,
        "level": level,       # real / placeholder / mixed
        "label": label,
    }


# ---------------------------------------------------------------------------
# GET /api/session
# ---------------------------------------------------------------------------


@router.get("/api/session")
def get_session() -> dict[str, str]:
    """新建一个会话,返 session_id。前端首次访问时调一次,后续 propose 复用。"""
    return {"session_id": _costs.new_session()}


# ---------------------------------------------------------------------------
# POST /api/propose
# ---------------------------------------------------------------------------


@router.post("/api/propose")
def post_propose(req: ProposeRequest) -> dict[str, Any]:
    """触发 propose 编排,返 ProposeUiResult(序列化为 dict)。

    status:
    - "ok":正常产出,前端渲染卡片
    - "softcap_reached":累计到软顶未 confirm,前端弹确认框
    """
    try:
        result = run_propose_for_ui(
            idea=req.idea or "",
            name=req.name,
            session_id=req.session_id,
            costs=_costs,
            confirm_over_softcap=req.confirm_over_softcap,
            force_refresh_scan=req.force_refresh_scan,
        )
    except Exception as e:
        # D-70:不静默崩,日志告警 + 给前端一句人话
        logger.exception("propose 编排异常")
        raise HTTPException(status_code=500, detail=f"本次生成失败,请重试或检查日志。({type(e).__name__})")
    # dataclass → dict(字段都是基本类型,可直接序列化)
    return result.__dict__


# ---------------------------------------------------------------------------
# POST /api/propose/stream — T3.2 SSE 版(spec line 11)
# ---------------------------------------------------------------------------


def _run_orchestrator_sync(
    idea: str,
    name: Optional[str],
    session_id: Optional[str],
    confirm_over_softcap: bool,
    force_refresh_scan: bool,
    on_progress,
):
    """在 worker thread 里同步跑 orchestrator(隔离主 loop)。

    从 async 上下文调度时,主 loop 已在跑;orchestrator 内部用 asyncio.run 调
    async LLM adapter,不能再嵌套进运行中的 loop → 必须放 thread。
    """
    return run_propose_for_ui(
        idea=idea,
        name=name,
        session_id=session_id,
        costs=_costs,
        confirm_over_softcap=confirm_over_softcap,
        on_progress=on_progress,
        force_refresh_scan=force_refresh_scan,
    )


@router.post("/api/propose/stream")
async def post_propose_stream(req: ProposeRequest):
    """SSE 流式 propose。每 stage 推送进度事件,最后一帧 type=result。

    SSE 事件结构:
    - {type: "progress", stage, status, [cost_cny], [error], ...}(stage 帧)
    - {type: "result", status, path, ...}(完成帧,含完整 ProposeUiResult)
    - {type: "error", message}(异常时,人话提示)
    """
    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def _on_progress(event: dict) -> None:
        # 从 worker thread 调度 put 到主 loop
        try:
            asyncio.run_coroutine_threadsafe(queue.put({"type": "progress", **event}), loop)
        except Exception as e:  # noqa: BLE001
            logger.warning("SSE progress 调度失败:%s", e)

    async def _run() -> None:
        try:
            # orchestrator 是 sync 且内部用 asyncio.run → 必须放 thread 跑
            result = await asyncio.to_thread(
                _run_orchestrator_sync,
                req.idea or "",
                req.name,
                req.session_id,
                req.confirm_over_softcap,
                req.force_refresh_scan,
                _on_progress,
            )
            queue.put_nowait({"type": "result", **result.__dict__})
        except Exception as e:
            logger.exception("propose stream 异常")
            queue.put_nowait({
                "type": "error",
                "message": f"生成失败,请重试或检查服务。({type(e).__name__})",
            })
        finally:
            queue.put_nowait(None)

    asyncio.create_task(_run())
    return StreamingResponse(sse_generator(queue), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# GET /api/peak-hours — T7-3 峰谷时段提示(D-81)
# ---------------------------------------------------------------------------


@router.get("/api/peak-hours")
def get_peak_hours() -> dict[str, Any]:
    """返当前峰谷时段状态。前端成本条用此渲染高峰/平峰徽标。

    Returns:
        - is_peak (bool): 当前是否在高峰时段
        - label (str): 显示文案("高峰 2x..." / "平峰..." / "即将生效...")
        - effective_from (str): 生效起始日期描述
        - now (str): 当前时间 ISO(便于前端校对)
    """
    now = _get_now()
    is_peak, label = _is_peak_time(now)
    return {
        "is_peak": is_peak,
        "label": label,
        "effective_from": f"{now.year}-07-15",
        "now": now.isoformat(timespec="minutes"),
    }


# ---------------------------------------------------------------------------
# T5 提示词查看页(只读)— spec line 13
# ---------------------------------------------------------------------------

# 源码读取白名单:只这些目录里的文件可读
_PROMPT_SOURCE_ALLOWED_DIRS = (
    "src/biyu/prompts/",
    "src/biyu/editor/",
)

# inventory 文件位置(本地技术中枢维护)
_INVENTORY_PATH = ".anchor/state/prompt_inventory.md"

# prompt_texts 文件目录(本地技术中枢定期 dump)
_PROMPT_TEXTS_DIR = ".anchor/state"
# 文件名格式:prompt_texts_YYYY-MM-DD.md
_PROMPT_TEXTS_RE = re.compile(r"^prompt_texts_(\d{4}-\d{2}-\d{2})\.md$")


def _resolve_anchor_state_candidates() -> list[Path]:
    """Return developer prompt exports without coupling them to author data."""
    root = get_data_root()
    return [
        get_project_root() / _PROMPT_TEXTS_DIR,
        root / _PROMPT_TEXTS_DIR,
        root.parent / _PROMPT_TEXTS_DIR,
    ]


@router.get("/api/prompts/texts")
def get_prompts_texts() -> dict[str, Any]:
    """读 .anchor/state/prompt_texts_<date>.md 最新导出件全文(主体,中枢裁定)。

    按文件名内嵌日期选最新(不看 mtime,避免文件系统时间漂移影响)。
    无文件时返 200 + 空 markdown + null date(前端显示"暂未导出")。

    Returns:
        - markdown (str): 最新 prompt_texts 全文
        - date (str | None): 最新导出日期 YYYY-MM-DD
        - path (str): 文件名(便于前端展示)
    """
    candidates = _resolve_anchor_state_candidates()
    latest: tuple[str, Path] | None = None  # (date, path)
    for state_dir in candidates:
        if not state_dir.exists():
            continue
        for f in state_dir.iterdir():
            if not f.is_file():
                continue
            m = _PROMPT_TEXTS_RE.match(f.name)
            if not m:
                continue
            date_str = m.group(1)
            if latest is None or date_str > latest[0]:
                latest = (date_str, f)
    if latest is None:
        return {"markdown": "", "date": None, "path": ""}
    try:
        md = latest[1].read_text(encoding="utf-8")
    except OSError as e:
        logger.warning("读 prompt_texts 失败 %s: %s", latest[1], e)
        return {"markdown": "", "date": None, "path": ""}
    return {"markdown": md, "date": latest[0], "path": latest[1].name}


@router.get("/api/prompts/inventory")
def get_prompts_inventory() -> dict[str, str]:
    """读 .anchor/state/prompt_inventory.md 全文返前端,只读渲染用(辅助索引)。

    文件不存在时返 200 + 空字符串(前端显示"暂未生成"),不报错。
    """
    root = get_data_root()
    candidates = [
        get_project_root() / _INVENTORY_PATH,
        root / _INVENTORY_PATH,
        root.parent / _INVENTORY_PATH,
    ]
    for p in candidates:
        if p.exists():
            try:
                return {"markdown": p.read_text(encoding="utf-8")}
            except OSError as e:
                logger.warning("读 inventory 失败 %s: %s", p, e)
                return {"markdown": ""}
    return {"markdown": ""}


@router.get("/api/prompts/source")
def get_prompts_source(
    file: str = Query(..., description="相对仓库根的源码路径"),
    start: int = Query(1, ge=1, description="起始行号(1-based)"),
    end: int = Query(50, ge=1, le=500, description="结束行号(1-based, ≤500)"),
) -> dict[str, Any]:
    """读源码文件指定行段。白名单:src/biyu/prompts/ 和 src/biyu/editor/。

    安全考虑:
    - 拒绝 ../ 路径(防目录穿越)
    - 拒绝 config/、.env、Key 文件
    - 单次最多读 500 行(防整文件 dump 拖性能)
    """
    # 路径安全检查
    if ".." in file or file.startswith("/"):
        raise HTTPException(status_code=400, detail="路径不允许(拒绝绝对/穿越路径)")
    if not any(file.startswith(d) for d in _PROMPT_SOURCE_ALLOWED_DIRS):
        raise HTTPException(
            status_code=400,
            detail=f"路径不在白名单(仅 {' / '.join(_PROMPT_SOURCE_ALLOWED_DIRS)})",
        )

    root = get_data_root()
    candidates = [get_project_root() / file, root / file, root.parent / file]
    path: Path | None = None
    for p in candidates:
        if p.exists() and p.is_file():
            path = p
            break
    if path is None:
        raise HTTPException(status_code=404, detail=f"文件不存在:{file}")

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"读取失败:{e}") from e

    sliced = lines[start - 1: end]
    return {
        "file": file,
        "start": start,
        "end": min(end, len(lines)),
        "total_lines": len(lines),
        "text": "\n".join(sliced),
    }


# ---------------------------------------------------------------------------
# P8-M3 T1:会话基座 — ChatManager 端点
# ---------------------------------------------------------------------------


class CreateChatSessionRequest(BaseModel):
    book: str = Field(..., description="书名(可传 book_id 或目录名)")
    role: str = Field("editor", description="角色: editor / director / naming")
    source: str = Field("production", description="会话来源: production(默认)/ test(自动化/联调)")


class ChatSendRequest(BaseModel):
    content: str = Field(..., description="消息内容")


def _get_chat_mgr() -> ChatManager:
    """创建 ChatManager (不缓存,尊重 monkeypatch 时序)。"""
    return ChatManager(data_root=get_data_root())


def _resolve_book_identity(book: str) -> tuple[str, str]:
    """R1 slug ID:把 book(id 或目录名)解析为 (dir_name, book_id)。

    Lookup:
    1. resolve_book_dir(book) 先按 book.json id 匹配,回退目录名
    2. 读对应 book.json 的 id 字段(无则回退目录名)

    Returns:
        (directory_name, book_id_slug);book_id 无显式 id 时 = dir_name

    Fallback:书不存在时返 (book, book)(兼容旧测试/未建 book.json 的目录)。
    """
    from biyu.config import resolve_book_dir

    try:
        book_dir = resolve_book_dir(book)
    except (FileNotFoundError, ValueError):
        # 书不存在(测试场景或未建 book.json)→ 原样返回
        return book, book
    dir_name = book_dir.name
    try:
        meta = json.loads((book_dir / "book.json").read_text(encoding="utf-8"))
        book_id = meta.get("id") or dir_name
    except (json.JSONDecodeError, OSError):
        book_id = dir_name
    return dir_name, book_id


def _resolve_book_dir_path(book: str, data_root: Path) -> Path:
    """R1 slug ID:把 book(id 或目录名)解析为目录 Path。

    比 _resolve_book_identity 轻:只返 Path,不读 book.json id。
    书不存在时回退 data_root/book(过渡兼容,允许目录尚未建 book.json)。
    """
    dir_name, _ = _resolve_book_identity(book)
    return data_root / dir_name


def _get_chat_adapter() -> Any | None:
    """Get LLM adapter for editorial chat. Returns None if unavailable."""
    try:
        return ModelRegistry().get_adapter("v4_flash")
    except (FileNotFoundError, KeyError, ValueError):
        logger.warning("Chat LLM adapter not available; staying in placeholder mode")
        return None


@router.post("/api/chat/sessions")
def create_chat_session(req: CreateChatSessionRequest) -> dict[str, Any]:
    """新建会话,返 session_id + 元数据。

    P8-M3R R1: req.book 可以是 book_id(slug)或目录名;服务端解析后存
    meta.book=目录名, meta.book_id=slug(无 id 时回退目录名)。
    P8-M3R R6 T6.1: req.source 标记会话来源(production / test),默认 production;
    UI 默认隐 source=test,自动化/联调脚本显式打 source=test。
    """
    dir_name, book_id = _resolve_book_identity(req.book)
    mgr = _get_chat_mgr()
    sid = mgr.new_session(dir_name, req.role, book_id=book_id, source=req.source)
    session = mgr.get_session(sid)
    assert session is not None  # 刚创建应有
    return session


@router.get("/api/chat/sessions")
def list_chat_sessions(
    book: Optional[str] = Query(None, description="按书过滤(可传 book_id 或目录名)"),
    include_test: bool = Query(False, description="是否包含 source=test 会话(默认 False)"),
) -> dict[str, Any]:
    """列出会话(未删除),按创建时间降序。

    P8-M3R R1: book 参数接受 id 或目录名,内部解析为 book_id 过滤。
    P8-M3R R6 T6.1: include_test 默认 False(隐自动化测试会话);?include_test=true 才显。
    """
    mgr = _get_chat_mgr()
    if not book:
        return {"sessions": mgr.list_sessions(include_test=include_test)}
    # 解析 book(id 或目录名)→ book_id,按 book_id 过滤(覆盖跨目录场景)
    try:
        _, book_id = _resolve_book_identity(book)
    except (FileNotFoundError, ValueError):
        # 解析失败(书不存在)时,仍尝试按目录名直查(过渡期不断)
        return {"sessions": mgr.list_sessions(book, include_test=include_test)}
    return {"sessions": mgr.list_sessions(book_id=book_id, include_test=include_test)}


@router.get("/api/chat/sessions/{session_id}")
def get_chat_session(session_id: str) -> dict[str, Any]:
    """取指定会话(含消息历史)。"""
    mgr = _get_chat_mgr()
    session = mgr.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return session


@router.post("/api/chat/sessions/{session_id}/messages")
async def post_chat_message(session_id: str, req: ChatSendRequest):
    """发送消息并流式返回(SSE)。

    T3 占位模式(role=editor):回显固定文案 + 责编工具查询结果。
    T4 占位模式(role=director):回显导演文案 + 会诊工具查询结果。
    """
    mgr = _get_chat_mgr()
    session = mgr.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")

    queue: asyncio.Queue = asyncio.Queue()

    async def _run() -> None:
        try:
            mgr.add_message(session_id, "user", req.content)

            # 解析 book → book_dir
            book = session.get("book", "")
            data_root = get_data_root()  # Path
            book_dir = data_root / book
            role = session.get("role", "editor")

            # 按角色调用工具集(占位与 LLM 模式共用)
            if role == "director":
                tool_results = run_director_tools(
                    book_dir=book_dir,
                    message=req.content,
                )
                placeholder_text = "导演人格待定稿，当前仅代查资料。以下为会诊参考。"
            else:
                tool_results = run_chat_tools(
                    book_dir=book_dir,
                    data_root=data_root,
                    message=req.content,
                )
                placeholder_text = "编辑人格待定稿，当前仅代查资料。以下为工具查询结果。"

            # 占位开关判断
            is_placeholder = PLACEHOLDER_FLAGS.get(role, True) if role in ("editor", "director") else True

            if is_placeholder:
                # === 占位模式:固定文案 + 工具结果(无 LLM) ===
                for i in range(0, len(placeholder_text), 8):
                    chunk = placeholder_text[i:i + 8]
                    await queue.put(make_event("token", content=chunk))
                    await asyncio.sleep(0.01)

                for tr in tool_results:
                    await queue.put(make_event(
                        "tool_call",
                        name=tr["name"],
                        args=tr["args"],
                        result=tr["result"][:500],
                    ))

                mgr.add_message(
                    session_id, "assistant", placeholder_text,
                    tool_call={
                        "tools": [
                            {"name": tr["name"], "args": tr["args"], "result": tr["result"][:500]}
                            for tr in tool_results
                        ],
                    },
                    cost=0.0,
                )
                await queue.put(make_event("cost", amount=0.0))
            else:
                # === 真 LLM 模式:构建 prompt → 调用 adapter → 流式输出 ===
                try:
                    adapter = _get_chat_adapter()
                    if adapter is None:
                        raise RuntimeError("LLM adapter 不可用")

                    # 获取对话历史(不含当前 user message,由 build_* 最后追加)
                    all_msgs = session.get("messages", [])
                    history = [m for m in all_msgs if m.get("role") in ("user", "assistant")][:-1]  # 排除当前 user

                    # 构建消息
                    if role == "director":
                        messages = build_director_messages(history, tool_results, req.content)
                    else:
                        messages = build_editor_messages(history, tool_results, req.content)

                    # 软顶检查:累计成本 < ¥2
                    current_cost = mgr.get_session_cost(session_id)
                    if current_cost >= 2.0:
                        # 软顶已到 → 降级到占位模式告知用户
                        softcap_msg = "会话成本已达软顶(¥2),无法继续生成。请新建会话。"
                        await queue.put(make_event("token", content=softcap_msg))
                        mgr.add_message(session_id, "assistant", softcap_msg, cost=0.0)
                        await queue.put(make_event("cost", amount=0.0))
                        return

                    # 调用 LLM
                    response = await adapter.generate(messages)
                    text = response.text or ""
                    actual_cost = float(getattr(response, "cost", 0.0) or 0.0)

                    # D-93 中央成本台账
                    if actual_cost > 0:
                        try:
                            write_cost_log(
                                task="chat",
                                book=book,
                                session=session_id,
                                cost=actual_cost,
                                model=getattr(adapter, "model_name", ""),
                            )
                        except Exception:
                            logger.warning("写 cost_log 失败", exc_info=True)

                    # 流式输出(逐段)
                    for i in range(0, len(text), 8):
                        chunk = text[i:i + 8]
                        await queue.put(make_event("token", content=chunk))
                        await asyncio.sleep(0.01)

                    # 工具卡(每个工具一张)
                    for tr in tool_results:
                        await queue.put(make_event(
                            "tool_call",
                            name=tr["name"],
                            args=tr["args"],
                            result=tr["result"][:500],
                        ))

                    mgr.add_message(
                        session_id, "assistant", text,
                        tool_call={
                            "tools": [
                                {"name": tr["name"], "args": tr["args"], "result": tr["result"][:500]}
                                for tr in tool_results
                            ],
                        },
                        cost=actual_cost,
                    )
                    await queue.put(make_event("cost", amount=actual_cost))

                except Exception:
                    logger.exception("LLM 调用异常,降级到占位")
                    # LLM 失败 → 降级到占位文本 + 工具结果
                    for i in range(0, len(placeholder_text), 8):
                        chunk = placeholder_text[i:i + 8]
                        await queue.put(make_event("token", content=chunk))
                        await asyncio.sleep(0.01)
                    for tr in tool_results:
                        await queue.put(make_event(
                            "tool_call",
                            name=tr["name"],
                            args=tr["args"],
                            result=tr["result"][:500],
                        ))
                    mgr.add_message(
                        session_id, "assistant", placeholder_text,
                        tool_call={
                            "tools": [
                                {"name": tr["name"], "args": tr["args"], "result": tr["result"][:500]}
                                for tr in tool_results
                            ],
                        },
                        cost=0.0,
                    )
                    await queue.put(make_event("cost", amount=0.0))
        except Exception as e:
            logger.exception("chat SSE 异常")
            await queue.put(make_event("error", message=str(e)))
        finally:
            await queue.put(None)

    asyncio.create_task(_run())
    return StreamingResponse(sse_generator(queue), media_type="text/event-stream")


@router.delete("/api/chat/sessions/{session_id}")
def delete_chat_session(session_id: str) -> dict[str, bool]:
    """软删除会话。"""
    mgr = _get_chat_mgr()
    try:
        mgr.soft_delete(session_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"ok": True}


# ---------------------------------------------------------------------------
# T5 会诊纪要
# ---------------------------------------------------------------------------


class SummarizeRequest(BaseModel):
    rejected: list[str] = Field(default_factory=list, description="被否方向及理由；已落设定集内容须由调用方过滤")
    unresolved: list[str] = Field(default_factory=list, description="还没定的分歧")
    taste_signals: list[str] = Field(default_factory=list, description="作者口味信号")


@router.post("/api/chat/sessions/{session_id}/summarize")
async def post_summarize(session_id: str, req: SummarizeRequest) -> dict[str, Any]:
    """保存责编自己提供的一份滚动工作纪要；本路由不调用第二个 LLM。"""
    mgr = _get_chat_mgr()
    session = mgr.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")

    book = session.get("book", "")
    data_root = get_data_root()
    book_dir = data_root / book

    try:
        notes = {
            "rejected": req.rejected,
            "unresolved": req.unresolved,
            "taste_signals": req.taste_signals,
        }
        filename, char_count = save_editor_memo(book_dir, notes)
    except Exception as e:
        logger.exception("纪要生成异常")
        raise HTTPException(status_code=500, detail=f"纪要生成失败: {type(e).__name__}")

    return {
        "ok": True,
        "filename": filename,
        "book": book,
        "message_count": len(session.get("messages", [])),
        "source": "editor",
        "cost_cny": 0.0,
        "generated_at": datetime.now().date().isoformat(),
        "char_count": char_count,
    }


@router.get("/api/summaries")
def get_summaries(
    book: str = Query(..., description="书名或 book_id"),
) -> list[dict[str, Any]]:
    """列出某书的所有纪要文件。"""
    data_root = get_data_root()
    book_dir = _resolve_book_dir_path(book, data_root)
    return list_summaries(book_dir)


@router.get("/api/summaries/{book}/{filename}")
def get_summary(book: str, filename: str) -> dict[str, Any]:
    """读指定纪要全文。"""
    data_root = get_data_root()
    book_dir = _resolve_book_dir_path(book, data_root)
    try:
        md = read_summary(book_dir, filename)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"纪要不存在:{filename}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取失败:{type(e).__name__}")
    return {"filename": filename, "book": book, "markdown": md}


# ---------------------------------------------------------------------------
# T6 偏好沉淀 v0
# ---------------------------------------------------------------------------


class SavePreferenceRequest(BaseModel):
    content: str = Field(..., description="偏好内容")
    source_session: str = Field(..., description="来源会话 ID")
    scope: str = Field("book", description="book / global")
    book: Optional[str] = Field(None, description="书名(scope=book 时必填)")


@router.post("/api/preferences")
def post_preference(req: SavePreferenceRequest) -> dict[str, Any]:
    """存一条偏好(本书 / 通用二选)。"""
    data_root = get_data_root()
    book_dir = _resolve_book_dir_path(req.book, data_root) if req.book else None

    result = save_preference(
        book_dir=book_dir,
        content=req.content,
        source_session=req.source_session,
        scope=req.scope,
        data_root=data_root,
    )
    return result


@router.get("/api/preferences")
def get_preferences(
    scope: str = Query("book", description="book / global"),
    book: Optional[str] = Query(None, description="书名或 book_id(scope=book 时必填)"),
) -> list[dict[str, Any]]:
    """列出偏好条目。"""
    data_root = get_data_root()
    book_dir = _resolve_book_dir_path(book, data_root) if book else None
    return list_preferences(
        book_dir=book_dir,
        scope=scope,
        data_root=data_root,
    )


@router.delete("/api/preferences/{scope}/{entry_id}")
def delete_preference_route(
    scope: str,
    entry_id: str,
    book: Optional[str] = Query(None, description="书名或 book_id(scope=book 时必填)"),
) -> dict[str, Any]:
    """删除一条偏好。"""
    data_root = get_data_root()
    book_dir = _resolve_book_dir_path(book, data_root) if book else None
    ok = _delete_pref(
        entry_id=entry_id,
        book_dir=book_dir,
        scope=scope,
        data_root=data_root,
    )
    if not ok:
        raise HTTPException(status_code=404, detail=f"偏好条目不存在:{entry_id}")
    return {"ok": True}


# ---------------------------------------------------------------------------
# T7 起名器
# ---------------------------------------------------------------------------


class NamingRequest(BaseModel):
    idea: str = Field("", description="作者设想文本(可空)")
    genre: str = Field("xuanhuan", description="题材代号(xuanhuan/dushi/xianxia/kehuan/lishi/qingxiaoshuo)")
    book: Optional[str] = Field(None, description="书名(用于书架改名入口,读取现有 meta)")


class ApplyNameRequest(BaseModel):
    book: str = Field(..., description="书名/目录名")
    title: str = Field(..., description="选中的书名")


@router.post("/api/naming")
async def post_naming(req: NamingRequest) -> dict[str, Any]:
    """生成候选书名。LLM 模式:调用真 LLM;失败时降级到模板并出声。

    source 字段:
    - "llm": 真 LLM 成功
    - "template_fallback": LLM 失败,降级到模板
    - "template": 占位模式(由 is_naming_placeholder() 控制)
    """
    try:
        # 如果指定了 book,可读取 genre 补全
        genre = req.genre
        if req.book:
            # R1 slug ID:接受 id 或目录名
            dir_name, _ = _resolve_book_identity(req.book)
            data_root = get_data_root()
            book_dir = data_root / dir_name
            book_json = book_dir / "book.json"
            if book_json.exists():
                try:
                    meta = json.loads(book_json.read_text(encoding="utf-8"))
                    genre = meta.get("genre", genre)
                except Exception:
                    pass

        result = await _generate_names(idea=req.idea, genre=genre)
        return result
    except Exception as e:
        logger.exception("起名生成异常")
        raise HTTPException(status_code=500, detail=f"起名生成失败: {type(e).__name__}")


@router.post("/api/naming/apply")
def post_naming_apply(req: ApplyNameRequest) -> dict[str, Any]:
    """应用选中书名到 book.json 的 display_name 字段。

    P8-M3R R1: req.book 可传 id 或目录名;服务端解析为目录后写 display_name。
    """
    # R1 slug ID:解析 book_id 或目录名 → 实际目录
    dir_name, _ = _resolve_book_identity(req.book)
    data_root = get_data_root()
    book_dir = data_root / dir_name
    if not book_dir.exists():
        raise HTTPException(status_code=404, detail=f"书目录不存在:{req.book}")

    try:
        result = _apply_name(book_dir, req.title)
        return result
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("起名应用异常")
        raise HTTPException(status_code=500, detail=f"起名应用失败: {type(e).__name__}")
