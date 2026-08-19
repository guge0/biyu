"""T6 偏好沉淀 v0 — preferences 文件 CRUD (P8-M3 T6)。

设计:
- 本书偏好: data/<书>/preferences.md
- 通用偏好: data/preferences_global.md
- 每条记录带: 来源会话链接 + 日期 + 内容
- 纯文件操作,无 LLM 调用,成本 = 0。

**注入 prompt 不做**(M4),本模块只做存储和查询。

文件格式:
```markdown
# 偏好 - <书名> / 通用偏好

## <YYYY-MM-DD> — <会话链接>
<内容>

## <YYYY-MM-DD> — <会话链接>
<内容>
```
"""
from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path
from typing import Any

from biyu.config import get_data_root

logger = logging.getLogger("biyu.ui.preferences")

_SUMMARY_PREFIX = "## "

# 偏好条目正则: "## <YYYY-MM-DD> — <session_link>"
_ENTRY_HEADER_RE = re.compile(r"^## (\d{4}-\d{2}-\d{2}) — (.+)$")


def _book_pref_path(book_dir: Path) -> Path:
    """Return data/<书>/preferences.md."""
    return book_dir / "preferences.md"


def _global_pref_path(data_root: Path | None = None) -> Path:
    """Return data/preferences_global.md."""
    root = data_root if data_root is not None else get_data_root()
    return root / "preferences_global.md"


def _ensure_file(path: Path) -> None:
    """Create file with header if not exists."""
    if not path.exists():
        # 根据路径推断标题
        if "global" in path.name:
            header = "# 通用偏好\n\n"
        else:
            header = f"# 偏好 - {path.parent.name}\n\n"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(header, encoding="utf-8")


def save_preference(
    book_dir: Path,
    *,
    content: str,
    source_session: str,
    scope: str = "book",
    data_root: Path | None = None,
) -> dict[str, Any]:
    """存一条偏好。

    Args:
        book_dir: 书目录路径(仅 scope=book 时用)
        content: 偏好内容
        source_session: 来源会话 ID
        scope: "book" → 本书 preferences.md / "global" → 全局
        data_root: 数据根(scope=global 时用)

    Returns:
        dict {entry_id, path, scope, date, source_session}
    """
    today = date.today().isoformat()

    if scope == "global":
        path = _global_pref_path(data_root)
    else:
        path = _book_pref_path(book_dir)

    _ensure_file(path)

    # 生成 entry_id: 日期 + 短哈希(基于内容)
    entry_id = f"{today}_{hash(content) & 0xFFFF:04x}"

    entry_block = (
        f"## {today} — 会话:{source_session} (id:{entry_id})\n\n"
        f"{content}\n\n"
    )

    # 追加到文件末尾
    with open(path, "a", encoding="utf-8") as f:
        f.write(entry_block)

    logger.info("偏好已存储: %s (scope=%s, id=%s)", path, scope, entry_id)

    return {
        "entry_id": entry_id,
        "path": str(path),
        "scope": scope,
        "date": today,
        "source_session": source_session,
    }


def list_preferences(
    book_dir: Path | None = None,
    *,
    scope: str = "book",
    data_root: Path | None = None,
) -> list[dict[str, Any]]:
    """列出偏好条目。

    Args:
        book_dir: 书目录路径(scope=book 时必填)
        scope: "book" 或 "global"
        data_root: 数据根(scope=global 时用)

    Returns:
        list of {entry_id, date, source, content, raw_text}
    """
    if scope == "global":
        path = _global_pref_path(data_root)
    elif book_dir is not None:
        path = _book_pref_path(book_dir)
    else:
        return []

    if not path.exists():
        return []

    raw = path.read_text(encoding="utf-8")
    return _parse_entries(raw)


def delete_preference(
    entry_id: str,
    *,
    book_dir: Path | None = None,
    scope: str = "book",
    data_root: Path | None = None,
) -> bool:
    """按 entry_id 删除一条偏好。

    策略:解析条目 → 重建文件(header + 除目标外的所有条目 block)。

    Args:
        entry_id: 条目 ID
        book_dir: 书目录路径(scope=book 时必填)
        scope: "book" 或 "global"
        data_root: 数据根(scope=global 时用)

    Returns:
        True if deleted, False if not found
    """
    if scope == "global":
        path = _global_pref_path(data_root)
    elif book_dir is not None:
        path = _book_pref_path(book_dir)
    else:
        return False

    if not path.exists():
        return False

    raw = path.read_text(encoding="utf-8")
    entries = _parse_entries(raw)

    # 找目标索引 + 获取文件 header
    target_idx = None
    for idx, entry in enumerate(entries):
        if entry.get("entry_id") == entry_id:
            target_idx = idx
            break

    if target_idx is None:
        return False

    # 取 header(第一个 # 行)
    header_lines: list[str] = []
    for line in raw.split("\n"):
        header_lines.append(line)
        if line.startswith("# "):
            break
    header = "\n".join(header_lines)

    # 重建内容:header + 除目标外的条目
    remaining = [e for i, e in enumerate(entries) if i != target_idx]
    blocks = [header]
    for e in remaining:
        raw_text = e.get("raw_text", "")
        if raw_text:
            blocks.append(raw_text)
    new_content = "\n\n".join(blocks).strip() + "\n"
    path.write_text(new_content, encoding="utf-8")
    logger.info("偏好已删除: id=%s (scope=%s)", entry_id, scope)
    return True


# ---------------------------------------------------------------------------
# 内部解析/分割
# ---------------------------------------------------------------------------


def _parse_entries(raw: str) -> list[dict[str, Any]]:
    """解析偏好 markdown 文件,返回条目列表。"""
    entries: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    current_lines: list[str] = []

    def _finalize_current() -> None:
        """从 current_lines 提取完整条目信息并追加到 entries。"""
        if current is None:
            return
        current["raw_text"] = "\n".join(current_lines).strip()
        # content = body lines not counting header
        body_lines = current_lines[1:] if len(current_lines) > 1 else []
        body = "\n".join(body_lines).strip()
        if body and not current.get("content"):
            current["content"] = body
        entries.append(current)

    for line in raw.split("\n"):
        m = _ENTRY_HEADER_RE.match(line)
        if m:
            _finalize_current()
            current = {
                "date": m.group(1),
                "source": m.group(2),
                "entry_id": _extract_entry_id(m.group(2)),
                "content": "",
            }
            current_lines = [line]
        elif current is not None:
            current_lines.append(line)

    _finalize_current()
    return entries


def _extract_entry_id(source_str: str) -> str:
    """从 '会话:xxx (id:xxx)' 中提取 entry_id。"""
    m = re.search(r"id:([^\s)]+)", source_str)
    return m.group(1) if m else ""


