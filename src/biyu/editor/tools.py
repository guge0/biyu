"""Editor 查询工具 — 供 LLM function calling 使用。"""
from __future__ import annotations

import json
import re
from enum import Enum
from pathlib import Path
from typing import Any

import yaml


# ---------------------------------------------------------------------------
# EditorFailure — 具名失败桶
# ---------------------------------------------------------------------------

class EditorFailure(Enum):
    TRUNCATION = "TRUNCATION"           # finish_reason=length
    BAD_ARGUMENTS = "BAD_ARGUMENTS"     # tool args parse fail
    UNKNOWN_TOOL = "UNKNOWN_TOOL"       # 不在白名单
    TOOL_EXEC_ERROR = "TOOL_EXEC_ERROR"  # 工具执行异常
    RUN_FAIL = "RUN_FAIL"               # 收尾轮未调 submit_review / arguments 重试失败


def look_up_character(char_name: str, book_dir: Path) -> str:
    """查角色卡完整内容。"""
    chars_path = book_dir / "characters.yaml"
    if not chars_path.exists():
        return f"角色数据不存在: {chars_path}"

    with open(chars_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    characters = data.get("characters", [])
    for char in characters:
        if char.get("name") == char_name:
            # 返回关键信息（不全量返回，控制 token）
            info = {"name": char.get("name")}
            if "aliases" in char:
                info["aliases"] = char["aliases"]
            if "voice_examples" in char:
                info["voice_examples"] = char["voice_examples"]
            if "personality" in char:
                info["personality"] = char["personality"]
            if "state" in char:
                info["state"] = char["state"]
            if "forbidden_in_narrative" in char:
                info["forbidden_in_narrative"] = char["forbidden_in_narrative"]
            return str(info)

    return f"未找到角色: {char_name}"


def look_up_setting(keyword: str, book_dir: Path) -> str:
    """查 worldbook 中包含 keyword 的条目。"""
    wb_path = book_dir / "worldbook.yaml"
    if not wb_path.exists():
        return f"worldbook 不存在: {wb_path}"

    with open(wb_path, encoding="utf-8") as f:
        wb = yaml.safe_load(f) or {}

    matches: list[dict] = []
    for section in ("facts", "forbidden", "power_system", "factions", "geography"):
        items = wb.get(section, [])
        if isinstance(items, list):
            for item in items:
                if isinstance(item, str) and keyword in item:
                    matches.append({"section": section, "content": item})
                elif isinstance(item, dict):
                    text = str(item)
                    if keyword in text:
                        matches.append({"section": section, "content": item})

    if not matches:
        return f"worldbook 中未找到包含 '{keyword}' 的条目"

    return str(matches[:5])  # 最多 5 条


def look_up_history(chapter_or_keyword: str, book_dir: Path) -> str:
    """查历史章节中的相关段落 / truth_files 状态。"""
    # 先尝试按章节号查
    try:
        ch_num = int(chapter_or_keyword)
        ch_file = book_dir / "chapters" / f"ch{ch_num}.md"
        if ch_file.exists():
            text = ch_file.read_text(encoding="utf-8")
            # 只返回最后 500 字（避免 token 爆炸）
            return f"CH{ch_num} 末 500 字:\n{text[-500:]}"
    except ValueError:
        pass

    # 按关键词搜索最近 5 章
    results: list[str] = []
    chapters_dir = book_dir / "chapters"
    if not chapters_dir.exists():
        return "无历史章节"

    ch_files = sorted(
        [f for f in chapters_dir.iterdir() if f.name.startswith("ch") and f.suffix == ".md"],
        key=lambda f: int(f.stem[2:]),
    )

    for ch_file in ch_files[-10:]:  # 最近 10 章
        text = ch_file.read_text(encoding="utf-8")
        # 找关键词附近 100 字
        for m in re.finditer(keyword_or_chapter_escaped(chapter_or_keyword), text):
            start = max(0, m.start() - 50)
            end = min(len(text), m.end() + 50)
            context = text[start:end]
            ch_name = ch_file.stem
            results.append(f"[{ch_name}] ...{context}...")
            if len(results) >= 5:
                break
        if len(results) >= 5:
            break

    if not results:
        return f"历史章节中未找到 '{chapter_or_keyword}'"

    return "\n".join(results)


def look_up_visual(symbol: str, book_dir: Path) -> str:
    """查视觉符号（颜色/意象）在前文的使用记录。"""
    results: list[dict] = []
    chapters_dir = book_dir / "chapters"
    if not chapters_dir.exists():
        return "无历史章节"

    ch_files = sorted(
        [f for f in chapters_dir.iterdir() if f.name.startswith("ch") and f.suffix == ".md"],
        key=lambda f: int(f.stem[2:]),
    )

    for ch_file in ch_files:
        text = ch_file.read_text(encoding="utf-8")
        for m in re.finditer(re.escape(symbol), text):
            start = max(0, m.start() - 30)
            end = min(len(text), m.end() + 30)
            context = text[start:end]
            try:
                ch_num = int(ch_file.stem[2:])
            except ValueError:
                ch_num = 0
            results.append({"chapter": ch_num, "context": f"...{context}..."})
            if len(results) >= 10:
                break
        if len(results) >= 10:
            break

    if not results:
        return f"视觉符号 '{symbol}' 在前文中未出现"

    return str(results)


def keyword_or_chapter_escaped(kw: str) -> str:
    """Escape keyword for regex."""
    return re.escape(kw)


# ---------------------------------------------------------------------------
# Tool definitions for function calling (OpenAI format)
# ---------------------------------------------------------------------------
TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "look_up_character",
            "description": "查询角色卡：获取角色的 aliases/voice_examples/personality/state 等信息",
            "parameters": {
                "type": "object",
                "properties": {
                    "char_name": {
                        "type": "string",
                        "description": "角色名（如'角色A'、'角色B'）",
                    },
                },
                "required": ["char_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "look_up_setting",
            "description": "查询 worldbook：搜索设定中包含某关键词的条目",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "搜索关键词（如'金色'、'命甲'、'外部观察者'）",
                    },
                },
                "required": ["keyword"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "look_up_history",
            "description": "查询历史章节：搜索前文中包含某关键词的段落",
            "parameters": {
                "type": "object",
                "properties": {
                    "chapter_or_keyword": {
                        "type": "string",
                        "description": "章节号（如'15'）或搜索关键词",
                    },
                },
                "required": ["chapter_or_keyword"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "look_up_visual",
            "description": "查询视觉符号：搜索某颜色/意象在前文中的使用记录",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "视觉符号（如'金色'、'青铜色'、'红糖糍粑'）",
                    },
                },
                "required": ["symbol"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# submit_review tool definitions — single mode & multi-agent mode
# ---------------------------------------------------------------------------

SUBMIT_REVIEW_SINGLE = {
    "type": "function",
    "function": {
        "name": "submit_review",
        "description": "提交审稿结果。这是提交最终 issues 的唯一方式。审稿完成后必须调用此工具。",
        "parameters": {
            "type": "object",
            "properties": {
                "issues": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "line": {"type": "integer", "description": "大致行号（从 1 开始）"},
                            "quote": {"type": "string", "description": "原文中的句子（必须逐字引用）"},
                            "quoted_text": {"type": "string", "description": "问题段落中心连续 30-50 字原文片段"},
                            "type": {"type": "string", "description": "章内自洽 | 战力等级 | 认知边界 | 逻辑常识 | 人物一致 | 文风与AI味 | 跨章衔接 | 规划履约 | 字面伪影"},
                            "subtype": {"type": ["string", "null"], "description": "主角戏份 | 维基百科化 | 符号过度 | 语气漂移 | null"},
                            "explanation": {"type": "string", "description": "为什么这是问题"},
                            "fix_suggestion": {"type": "string", "description": "具体修改建议"},
                            "auto_fixable": {"type": "boolean", "description": "只有字面伪影类可为 true"},
                            "severity": {"type": "string", "description": "high | medium | low"},
                        },
                        "required": ["line", "quote", "type", "explanation", "fix_suggestion", "auto_fixable", "severity"],
                    },
                    "description": "审稿发现的问题列表",
                },
                "confidence": {"type": "string", "description": "high | medium | low"},
            },
            "required": ["issues"],
        },
    },
}

SUBMIT_REVIEW_AGENT = {
    "type": "function",
    "function": {
        "name": "submit_review",
        "description": "提交审稿结果。这是提交最终 issues 的唯一方式。审稿完成后必须调用此工具。",
        "parameters": {
            "type": "object",
            "properties": {
                "issues": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "description": "agent 内部编号，如 A-1"},
                            "type": {"type": "string", "description": "issue type（必须在你负责的 type 集合内）"},
                            "paragraph": {"type": "integer", "description": "段落号（从 1 开始）"},
                            "severity": {"type": "string", "description": "high | medium | low"},
                            "keyword": {"type": "string", "description": "关键词/引用片段"},
                            "description": {"type": "string", "description": "问题描述"},
                            "suggestion": {
                                "type": "object",
                                "properties": {
                                    "content": {"type": "string"},
                                    "rationale": {"type": "string"},
                                },
                                "required": ["content", "rationale"],
                            },
                            "retracted": {"type": "boolean", "description": "Phase 2 是否撤回"},
                            "retracted_reason": {"type": "string", "description": "撤回原因"},
                        },
                        "required": ["id", "type", "paragraph", "severity", "keyword", "description", "suggestion"],
                    },
                    "description": "审稿发现的问题列表",
                },
            },
            "required": ["issues"],
        },
    },
}


def get_submit_review_tool(mode: str) -> dict:
    """返回对应模式的 submit_review 工具定义。

    Args:
        mode: "single" 或 "agent"

    Returns:
        工具定义 dict
    """
    if mode == "single":
        return SUBMIT_REVIEW_SINGLE
    elif mode == "agent":
        return SUBMIT_REVIEW_AGENT
    else:
        raise ValueError(f"Unknown mode: {mode!r}, expected 'single' or 'agent'")


# ---------------------------------------------------------------------------
# Tool execution — 防御化
# ---------------------------------------------------------------------------

def _error(code: str, msg: str) -> str:
    """构造结构化 JSON 错误消息。"""
    return json.dumps({"error": code, "message": msg}, ensure_ascii=False)


def execute_tool(name: str, arguments: dict, book_dir: Path) -> str:
    """Execute a named tool with arguments. Returns structured JSON error on failure."""
    try:
        if name == "look_up_character":
            char_name = arguments.get("char_name")
            if not char_name:
                return _error("BAD_ARGUMENTS", "missing char_name")
            return look_up_character(char_name, book_dir)
        elif name == "look_up_setting":
            keyword = arguments.get("keyword")
            if not keyword:
                return _error("BAD_ARGUMENTS", "missing keyword")
            return look_up_setting(keyword, book_dir)
        elif name == "look_up_history":
            val = arguments.get("chapter_or_keyword")
            if not val:
                return _error("BAD_ARGUMENTS", "missing chapter_or_keyword")
            return look_up_history(val, book_dir)
        elif name == "look_up_visual":
            symbol = arguments.get("symbol")
            if not symbol:
                return _error("BAD_ARGUMENTS", "missing symbol")
            return look_up_visual(symbol, book_dir)
        else:
            return _error("UNKNOWN_TOOL", f"unknown tool: {name}")
    except Exception as e:
        return _error("TOOL_EXEC_ERROR", str(e))


def get_tools_for_agent(agent_id: str) -> list[dict]:
    """按 AGENT_TOOL_MAP 过滤 TOOL_DEFINITIONS，返回该 agent 有权使用的工具子集。"""
    from .schema import AGENT_TOOL_MAP

    allowed = set(AGENT_TOOL_MAP.get(agent_id, []))
    return [td for td in TOOL_DEFINITIONS if td["function"]["name"] in allowed]
