"""T5 会诊纪要 — 结构化纪要生成/存储/查询 (P8-M3 T5)。

设计:
- `generate_summary(chat_mgr, session_id)` → LLM 结构化提取三段纪要;
  LLM 不可用时降级到占位模板。
- `save_summary(book_dir, summary_data)` → 写 data/<书>/consults/纪要_<date>_<n>.md
- `list_summaries(book_dir)` → 列出某书所有纪要
- `read_summary(book_dir, filename)` → 读指定纪要全文

v0 占位模板(功能类 prompt):摘要 = 消息时间线 + 结构化三段模板,无 LLM。
v1 (D-93):LLM 结构化提取,降级到 v0 模板。
"""
from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path
from typing import Any

from biyu.llm import ModelRegistry
from biyu.ui.chat import ChatManager
from biyu.ui.prompts_summarize import build_summarize_messages

logger = logging.getLogger("biyu.ui.summarize")

_CONSULTS_DIRNAME = "consults"
# F2 (P8-M3R-fix): 新纪要主目录。原 consults/ 同时存 session json 和纪要 md,
# /api/summaries 读 consults/ 易混(B3 §71)。新纪要单独存 summaries/(命名与 API 一致);
# list/read 兼容扫 consults/(fallback,旧纪要 0 迁移)。
_SUMMARIES_DIRNAME = "summaries"
_SUMMARY_PREFIX = "纪要_"
_SUMMARY_RE = re.compile(r"^纪要_(\d{4}-\d{2}-\d{2})_(\d+)\.md$")
_EDITOR_MEMO_FILENAME = "责编纪要.md"
_EDITOR_MEMO_LIMIT = 4000
_EDITOR_MEMO_SECTIONS = (
    ("rejected", "一、被否方向 + 理由"),
    ("unresolved", "二、还没定的分歧"),
    ("taste_signals", "三、作者口味信号"),
)

# F1 (P8-M3R-fix): role 中文化映射。
# B3 发现 director mode 会话生成的纪要头部写 `> 角色: editor`(英文 + 错位);
# 修:头部用中文标签(_role_label),末尾保留英文原值(_ROLE_ORIGINAL_LINE)便于追溯。
_ROLE_LABELS: dict[str, str] = {
    "editor": "责编",
    "director": "导演",
    "naming": "起名",
}


def _role_label(role: str) -> str:
    """会话 role → 中文标签。未知值兜底 '未知'(不直接显英文,防错位)。"""
    return _ROLE_LABELS.get(role, "未知")


def _consults_dir(book_dir: Path) -> Path:
    """Return the consults/ directory for a book.

    注:F2 后 consults/ 仅作 fallback 读旧纪要;新纪要写 summaries/(见 _summaries_dir)。
    """
    d = book_dir / _CONSULTS_DIRNAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def _summaries_dir(book_dir: Path) -> Path:
    """Return the summaries/ directory for a book (F2 主目录)。"""
    d = book_dir / _SUMMARIES_DIRNAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def _summary_dirs(book_dir: Path) -> list[tuple[Path, str]]:
    """F2: 纪要目录候选列表。返回 [(dir, source_dir_name), ...] 顺序即优先级。

    summaries/(主,F2 后新纪要落此)+ consults/(fallback,旧纪要兼容读)。
    目录不存在不强制创建(仅 list/read 用,不写)。
    """
    candidates = [
        (book_dir / _SUMMARIES_DIRNAME, _SUMMARIES_DIRNAME),
        (book_dir / _CONSULTS_DIRNAME, _CONSULTS_DIRNAME),
    ]
    return [(d, name) for d, name in candidates if d.exists() and d.is_dir()]


def _get_llm_adapter() -> Any | None:
    """Get LLM adapter for summarization. Returns None if unavailable."""
    try:
        return ModelRegistry().get_adapter("v4_flash")
    except (FileNotFoundError, KeyError, ValueError):
        logger.warning("Summarize LLM adapter not available")
        return None


def _build_timeline_text(session: dict) -> str:
    """从会话消息构建纯文本时间线。"""
    messages = session.get("messages", [])
    lines: list[str] = []
    for idx, msg in enumerate(messages):
        role_label = msg.get("role", "?")
        content = msg.get("content", "")
        tool_data = msg.get("tool_call")
        ts = msg.get("ts", "")
        lines.append(f"### 第 {idx + 1} 轮 ({role_label}) [{ts}]")
        lines.append(content)
        if tool_data:
            tools = tool_data.get("tools", [])
            for t in tools:
                lines.append(f"> 工具: {t.get('name', '?')}")
        lines.append("")
    return "\n".join(lines)


def _template_summary(session: dict) -> str:
    """占位模板:基于消息时间线 + 结构化三段式。"""
    book = session.get("book", "未知")
    role = session.get("role", "editor")
    today = date.today().isoformat()
    session_id = session.get("id", "?")
    timeline_text = _build_timeline_text(session)

    summary_md = f"""# 会诊纪要

> 来源会话: `{session_id}`
> 角色: {_role_label(role)}
> 书: {book}
> 生成日期: {today}
> 模式: 占位模板(功能类结构化,无 LLM)

---

## 讨论时间线

{timeline_text if timeline_text else "(会话暂无消息)"}

---

## 一、被否方向 + 理由

> (以下为占位模板,待 prompt 过关后由 LLM 结构化提取)

会话中明确被否定的方向及理由:

1. (待提取 — 基于上面对话时间线)

## 二、还没定的分歧

> (以下为占位模板,待 prompt 过关后由 LLM 提取)

会话中仍未拍板的分歧:

1. (待提取)

## 三、作者口味信号

> (以下为占位模板,待 prompt 过关后由 LLM 提取)

从作者取舍中确认的口味信号:

1. (待提取)

---

> 角色标识: {role}
"""
    return summary_md


async def generate_summary(
    chat_mgr: ChatManager,
    session_id: str,
) -> dict[str, Any]:
    """从会话消息生成结构化纪要。

    优先 LLM 结构化提取,失败时降级到占位模板。

    Args:
        chat_mgr: ChatManager 实例
        session_id: 会话 ID

    Returns:
        dict with keys:
            - summary_md (str): 完整 markdown 文本
            - session_id (str): 来源会话 ID
            - book (str): 所属书名
            - message_count (int): 总消息数
            - generated_at (str): 生成时间
            - source: "llm" | "template" | "template_fallback"
            - cost_cny (float): LLM 调用成本
    """
    session = chat_mgr.get_session(session_id)
    if session is None:
        raise ValueError(f"会话不存在:{session_id}")

    messages = session.get("messages", [])
    book = session.get("book", "未知")
    role = session.get("role", "editor")
    today = date.today().isoformat()
    session_id_val = session.get("id", session_id)

    # 尝试 LLM 结构化提取
    adapter = _get_llm_adapter()
    if adapter is not None:
        timeline_text = _build_timeline_text(session)
        llm_messages = build_summarize_messages(timeline_text)
        try:
            resp = await adapter.generate(llm_messages)
            text = resp.text or ""
            cost = float(getattr(resp, "cost", 0.0) or 0.0)

            if text.strip():
                # LLM 成功,构建完整纪要
                summary_md = f"""# 会诊纪要

> 来源会话: `{session_id_val}`
> 角色: {_role_label(role)}
> 书: {book}
> 生成日期: {today}
> 模式: LLM 结构化提取

---

## 讨论时间线

{timeline_text if timeline_text else "(会话暂无消息)"}

---

{text}

---

> 角色标识: {role}
"""
                return {
                    "summary_md": summary_md,
                    "session_id": session_id_val,
                    "book": book,
                    "message_count": len(messages),
                    "generated_at": today,
                    "source": "llm",
                    "cost_cny": cost,
                }
        except Exception:
            logger.exception("LLM 纪要提取异常,降级到模板")

    # 降级到占位模板
    logger.info("Summarize falling back to template (LLM unavailable or failed)")
    return {
        "summary_md": _template_summary(session),
        "session_id": session_id_val,
        "book": book,
        "message_count": len(messages),
        "generated_at": today,
        "source": "template_fallback",
        "cost_cny": 0.0,
    }


def save_summary(book_dir: Path, summary_data: dict[str, Any]) -> str:
    """写纪要到 data/<书>/summaries/ 目录(F2:原 consults/ 改为 summaries/)。

    Args:
        book_dir: 书目录路径
        summary_data: generate_summary() 返回的 dict

    Returns:
        写出的文件名,如 "纪要_2026-07-06_1.md"
    """
    summaries = _summaries_dir(book_dir)
    today = date.today().isoformat()

    # 找今日最大序号(同时扫 summaries/ 主 + consults/ fallback,避免同日重复序号)
    max_n = 0
    for d, _name in _summary_dirs(book_dir):
        for f in d.iterdir():
            if not f.is_file():
                continue
            m = _SUMMARY_RE.match(f.name)
            if m and m.group(1) == today:
                n = int(m.group(2))
                if n > max_n:
                    max_n = n

    filename = f"{_SUMMARY_PREFIX}{today}_{max_n + 1}.md"
    path = summaries / filename
    path.write_text(summary_data["summary_md"], encoding="utf-8")
    logger.info("纪要已落盘: %s", path)
    return filename


def _render_editor_memo(notes: dict[str, list[str]]) -> str:
    """Render the editor-maintained memo; callers must omit settings content."""
    lines = ["# 责编纪要", "", "> 一份滚动工作笔记；已落进设定集的内容请勿重复提交。", ""]
    for key, title in _EDITOR_MEMO_SECTIONS:
        lines.extend([f"## {title}", ""])
        entries = [str(item).strip() for item in notes.get(key, []) if str(item).strip()]
        lines.extend([f"- {item}" for item in entries] or ["- 本次未记录"])
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _compress_editor_memo(notes: dict[str, list[str]]) -> dict[str, list[str]]:
    """Deterministically merge oldest entries until rendered memo is <= 4000 chars."""
    compact = {key: [str(x).strip() for x in notes.get(key, []) if str(x).strip()]
               for key, _title in _EDITOR_MEMO_SECTIONS}
    while len(_render_editor_memo(compact)) > _EDITOR_MEMO_LIMIT:
        candidate = next((key for key, _ in _EDITOR_MEMO_SECTIONS if len(compact[key]) > 1), None)
        if candidate is None:
            # A single pathological entry is clipped; the contract remains a hard limit.
            candidate = next((key for key, _ in _EDITOR_MEMO_SECTIONS if compact[key]), None)
            if candidate is None:
                break
            compact[candidate][0] = compact[candidate][0][: max(0, len(compact[candidate][0]) - 64)]
            continue
        first = compact[candidate].pop(0)
        second = compact[candidate].pop(0)
        if first.startswith("较早记录已合并："):
            first = first.removeprefix("较早记录已合并：").removesuffix("。")
        compact[candidate].insert(0, f"较早记录已合并：{first}；{second}。")
    return compact


def save_editor_memo(book_dir: Path, notes: dict[str, list[str]]) -> tuple[str, int]:
    """Replace the book's single rolling editor memo without invoking an LLM."""
    summaries = _summaries_dir(book_dir)
    content = _render_editor_memo(_compress_editor_memo(notes))
    path = summaries / _EDITOR_MEMO_FILENAME
    path.write_text(content, encoding="utf-8")
    return path.name, len(content)


def list_summaries(book_dir: Path) -> list[dict[str, Any]]:
    """列出某书所有已落盘纪要文件元信息(F2:扫 summaries/ + consults/)。

    Returns:
        list of {filename, date, seq, path, source_dir}
        source_dir: "summaries"(F2 后新纪要)/ "consults"(旧纪要 fallback)
    """
    entries: list[dict[str, Any]] = []
    for d, source_name in _summary_dirs(book_dir):
        for f in sorted(d.iterdir(), key=lambda p: p.name, reverse=True):
            if not f.is_file():
                continue
            m = _SUMMARY_RE.match(f.name)
            if m:
                entries.append({
                    "filename": f.name,
                    "date": m.group(1),
                    "seq": int(m.group(2)),
                    "path": str(f.relative_to(book_dir.parent)),
                    "source_dir": source_name,
                })
            elif f.name == _EDITOR_MEMO_FILENAME:
                entries.append({
                    "filename": f.name,
                    "date": date.fromtimestamp(f.stat().st_mtime).isoformat(),
                    "seq": 0,
                    "path": str(f.relative_to(book_dir.parent)),
                    "source_dir": source_name,
                })
    # 同 filename 在两目录都有时去重(以 summaries/ 优先,因其在候选列表前)
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for e in entries:
        if e["filename"] in seen:
            continue
        seen.add(e["filename"])
        deduped.append(e)
    return deduped


def read_summary(book_dir: Path, filename: str) -> str:
    """读指定纪要文件全文(F2:summaries/ 主 + consults/ fallback)。

    Args:
        book_dir: 书目录路径
        filename: 文件名(如 "纪要_2026-07-06_1.md")

    Returns:
        文件全文

    Raises:
        FileNotFoundError: 文件不存在于 summaries/ 或 consults/
    """
    for d, _name in _summary_dirs(book_dir):
        path = d / filename
        if path.exists():
            return path.read_text(encoding="utf-8")
    raise FileNotFoundError(f"纪要不存在:{filename}")
