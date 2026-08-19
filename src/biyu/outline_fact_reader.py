"""Conservative, model-free fact checks for author-written chapter outlines."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml


_DEATH_WORDS = ("已死", "死亡", "身亡", "战死", "被杀", "殒命", "陨落")
_EXCEPTION_WORDS = ("回忆", "幻觉", "梦境", "做梦", "往事")


def _history_record(book_dir: Path, needle: str, words: tuple[str, ...]) -> tuple[int, str] | None:
    history = book_dir / "truth_files" / "history"
    if not history.exists():
        return None
    for path in sorted(history.glob("ch*/current_state.md"), reverse=True):
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            if needle in line and any(word in line for word in words):
                number = int(path.parent.name[2:])
                return number, line.strip()
    return None


def _category(key: str, label: str, *, checked: bool, reason: str = "") -> dict[str, Any]:
    return {"key": key, "label": label, "checked": checked, "reason": reason}


def _dead_character_issues(book_dir: Path, outline: str) -> tuple[list[dict[str, str]], dict[str, Any]]:
    path = book_dir / "characters.yaml"
    if not path.exists():
        return [], _category("character", "角色状态", checked=False, reason="这本书目前还没有角色状态记录；有死亡记录后会自动检查")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return [], _category("character", "角色状态", checked=False, reason="角色状态记录无法读取")
    characters = data.get("characters", []) if isinstance(data, dict) else []
    issues: list[dict[str, str]] = []
    readable = False
    for character in characters:
        if not isinstance(character, dict) or character.get("status") != "dead":
            continue
        name = str(character.get("name", "")).strip()
        if not name:
            continue
        record = _history_record(book_dir, name, _DEATH_WORDS)
        if not record:
            continue
        readable = True
        if name not in outline:
            continue
        sentence = next((item for item in re.split(r"[。！？\n]", outline) if name in item), "")
        if any(marker in sentence for marker in _EXCEPTION_WORDS):
            continue
        chapter, evidence = record
        issues.append({
            "category": "角色状态",
            "message": f"{name} 已被记录为死亡，细纲仍安排其直接出场。",
            "evidence": f"第 {chapter} 章 · {evidence}",
        })
    if readable:
        return issues, _category("character", "角色状态", checked=True)
    return [], _category("character", "角色状态", checked=False, reason="这本书目前还没有带章节依据的死亡记录；有死亡记录后会自动检查")


def _hook_issues(book_dir: Path, outline: str) -> tuple[list[dict[str, str]], dict[str, Any]]:
    history = book_dir / "truth_files" / "history"
    if not history.exists():
        return [], _category("hooks", "未回收伏笔", checked=False, reason="这类记录还不是机器能读准的格式")
    closed: dict[str, tuple[int, str]] = {}
    for path in sorted(history.glob("ch*/pending_hooks.md")):
        chapter = int(path.parent.name[2:])
        for line in path.read_text(encoding="utf-8").splitlines():
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(cells) >= 2 and any(value in {"closed", "已回收"} for value in cells):
                hook = cells[0]
                if hook and hook not in {"伏笔", "ID"}:
                    closed[hook] = (chapter, line.strip())
    if not closed:
        return [], _category("hooks", "未回收伏笔", checked=False, reason="这类记录还不是机器能读准的格式")
    issues = []
    for hook, (chapter, evidence) in closed.items():
        if re.search(rf"(?:回收|揭开|解开).{{0,12}}{re.escape(hook)}|{re.escape(hook)}.{{0,12}}(?:回收|揭开|解开)", outline):
            issues.append({
                "category": "未回收伏笔",
                "message": f"{hook} 已被记录为回收，细纲又声明回收它。",
                "evidence": f"第 {chapter} 章 · {evidence}",
            })
    return issues, _category("hooks", "未回收伏笔", checked=True)


def check_outline_facts(book_dir: Path, outline: str) -> dict[str, Any]:
    """Return only evidenced contradictions; unknown source formats stay explicit."""
    character_issues, character = _dead_character_issues(book_dir, outline)
    hook_issues, hooks = _hook_issues(book_dir, outline)
    categories = [
        character,
        _category("timeline", "时间线", checked=False, reason="这类记录还不是机器能读准的格式"),
        _category("events", "已发生事件", checked=False, reason="这类记录还不是机器能读准的格式"),
        hooks,
    ]
    return {"issues": character_issues + hook_issues, "categories": categories}
