"""真相文件读写工具 — current_state, particle_ledger, pending_hooks 三件套。

初始化模板 + 读写 + Observer 输出解析。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

TRUTH_DIR_NAME = "truth_files"

TRUTH_FILE_NAMES = (
    "current_state.md",
    "particle_ledger.md",
    "pending_hooks.md",
)

# ── 模板 ────────────────────────────────────────────────────────────────

CURRENT_STATE_TEMPLATE = """\
| 字段 | 值 |
|------|-----|
| 当前章节 | 0 |
| 主角状态 | （待第一章生成后填写） |
| 当前位置 | （待填写） |
| 当前目标 | 短期：（待填写）；中期：（待填写） |
| 当前限制 | （待填写） |
| 当前敌我 | 敌：（待填写）；友：（待填写）；中立：（待填写） |
| 当前冲突 | （待填写） |
"""

PARTICLE_LEDGER_TEMPLATE = """\
| 章节 | 角色 | 属性 | 期初值 | 变化 | 期末值 | 依据 |
|------|------|------|--------|------|--------|------|
"""

PENDING_HOOKS_TEMPLATE = """\
| hook_id | 起始章节 | 类型 | 状态 | 最近推进 | 预期回收 | 回收节奏 | 备注 |
|---------|---------|------|------|---------|---------|---------|------|
"""

_TEMPLATES = {
    "current_state.md": CURRENT_STATE_TEMPLATE,
    "particle_ledger.md": PARTICLE_LEDGER_TEMPLATE,
    "pending_hooks.md": PENDING_HOOKS_TEMPLATE,
}

# ── 目录 / 文件操作 ─────────────────────────────────────────────────────


def truth_dir(book_dir: Path) -> Path:
    """Return the truth_files directory for a book."""
    return book_dir / TRUTH_DIR_NAME


def init_truth_files(book_dir: Path) -> None:
    """Create truth_files/ directory and write empty templates."""
    tdir = truth_dir(book_dir)
    tdir.mkdir(parents=True, exist_ok=True)
    for name, template in _TEMPLATES.items():
        path = tdir / name
        if not path.exists():
            path.write_text(template, encoding="utf-8")


def reset_truth_files(book_dir: Path) -> None:
    """Reset the three derived truth files to their empty projection."""
    tdir = truth_dir(book_dir)
    tdir.mkdir(parents=True, exist_ok=True)
    for name, template in _TEMPLATES.items():
        (tdir / name).write_text(template, encoding="utf-8")


def read_truth_file(book_dir: Path, name: str) -> str:
    """Read a single truth file. Returns empty string if missing."""
    path = truth_dir(book_dir) / name
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def write_truth_file(book_dir: Path, name: str, content: str) -> None:
    """Overwrite a single truth file."""
    tdir = truth_dir(book_dir)
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / name).write_text(content, encoding="utf-8")


def read_all_truth_files(book_dir: Path) -> dict[str, str]:
    """Read all three truth files into a dict."""
    return {name: read_truth_file(book_dir, name) for name in TRUTH_FILE_NAMES}


def _pins_path(book_dir: Path) -> Path:
    return truth_dir(book_dir) / "pins.yaml"


def read_pins(book_dir: Path) -> dict[str, dict[str, str]]:
    path = _pins_path(book_dir)
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("pinned 元数据损坏") from exc
    return value if isinstance(value, dict) else {}


def write_pins(book_dir: Path, pins: dict[str, dict[str, str]]) -> None:
    path = _pins_path(book_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(pins, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    path.write_text(content, encoding="utf-8")
    history = truth_dir(book_dir) / "history" / "pins"
    history.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    (history / f"pins_{stamp}.yaml").write_text(content, encoding="utf-8")


def pin_truth_entry(book_dir: Path, filename: str, entry_key: str, value: str) -> dict[str, str]:
    if filename not in TRUTH_FILE_NAMES or entry_key.startswith("__") or not entry_key.strip():
        raise ValueError("只能锚定真相文件中的单条条目")
    pins = read_pins(book_dir)
    compound = f"{filename}:{entry_key}"
    pins[compound] = {
        "value": value,
        "pinned_at": datetime.now(timezone.utc).isoformat(),
        "resolution": "",
    }
    write_pins(book_dir, pins)
    return pins[compound]


def unpin_truth_entry(book_dir: Path, filename: str, entry_key: str) -> None:
    pins = read_pins(book_dir)
    pins.pop(f"{filename}:{entry_key}", None)
    write_pins(book_dir, pins)


def resolve_pin_conflict(book_dir: Path, filename: str, entry_key: str, choice: str) -> None:
    if choice == "machine":
        unpin_truth_entry(book_dir, filename, entry_key)
        return
    if choice != "mine":
        raise ValueError("裁决只能选择保留我的或听正文的")
    pins = read_pins(book_dir)
    compound = f"{filename}:{entry_key}"
    if compound not in pins:
        raise KeyError("锚定条目不存在")
    pins[compound]["resolution"] = "keep"
    write_pins(book_dir, pins)


# ── 历史版本快照 ─────────────────────────────────────────────────────────


def snapshot_truth_files(book_dir: Path, chapter_num: int) -> Path:
    """Snapshot current truth_files to history/chN/ before overwriting.

    Args:
        book_dir: Book directory.
        chapter_num: The chapter number that is about to update truth files.

    Returns:
        Path to the snapshot directory.
    """
    import shutil

    tdir = truth_dir(book_dir)
    history_dir = tdir / "history" / f"ch{chapter_num}"
    history_dir.mkdir(parents=True, exist_ok=True)

    for name in TRUTH_FILE_NAMES:
        src = tdir / name
        if src.exists():
            shutil.copy2(src, history_dir / name)
    pins = _pins_path(book_dir)
    if pins.exists():
        shutil.copy2(pins, history_dir / "pins.yaml")

    return history_dir


# ── Observer 输出解析 ───────────────────────────────────────────────────

_SEPARATORS = {
    "current_state.md": "=== current_state ===",
    "particle_ledger.md": "=== particle_ledger ===",
    "pending_hooks.md": "=== pending_hooks ===",
}


def parse_observer_output(raw: str) -> dict[str, str]:
    """Parse the Observer's triple-segment output into three file contents.

    Expected format (see observer.py prompt):
        === current_state ===
        (markdown table)
        === particle_ledger ===
        (markdown table)
        === pending_hooks ===
        (markdown table)
    """
    result: dict[str, str] = {}
    keys = list(_SEPARATORS.keys())
    seps = list(_SEPARATORS.values())
    pos = 0

    for i, sep in enumerate(seps):
        start = raw.find(sep, pos)
        if start == -1:
            result[keys[i]] = ""
            continue
        # skip the separator line itself
        content_start = start + len(sep)
        # find the next separator (if any)
        next_sep_pos = len(raw)
        for j in range(i + 1, len(seps)):
            candidate = raw.find(seps[j], content_start)
            if candidate != -1:
                next_sep_pos = candidate
                break
        result[keys[i]] = raw[content_start:next_sep_pos].strip()
        pos = next_sep_pos

    return result
