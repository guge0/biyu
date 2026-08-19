"""lint_rules 基础类定义。

LintRule — 所有 lint 规则的抽象基类
LintIssue — 单条扫描结果
LintContext — 扫描上下文（characters、worldbook 等只读数据）
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


@dataclass
class LintIssue:
    """单条 lint 扫描结果。"""

    rule_name: str
    severity: str  # "info" | "warning" | "error"
    message: str
    location: str  # 文件:行号 或 字段路径
    suggestion: str | None = None


@dataclass
class LintContext:
    """lint 规则共享的只读上下文。"""

    book_dir: Path
    characters: list[dict[str, Any]] = field(default_factory=list)
    worldbook: dict[str, Any] | None = None
    pending_hooks: list[dict[str, str]] = field(default_factory=list)
    outlines_dir: Path | None = None
    chapters_dir: Path | None = None


class LintRule(ABC):
    """所有 lint 规则的抽象基类。

    子类必须实现:
    - name: 规则名称
    - severity: 默认严重级别
    - check(target, context): 执行检查，返回 LintIssue 列表
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """规则唯一名称。"""

    @property
    @abstractmethod
    def severity(self) -> Literal["info", "warning", "error"]:
        """默认严重级别。"""

    @abstractmethod
    def check(self, target: Path, context: LintContext) -> list[LintIssue]:
        """执行检查。

        Args:
            target: 要扫描的 outline / sub-md 文件路径。
            context: 共享上下文。

        Returns:
            检测到的 LintIssue 列表，无问题返回空列表。
        """


def parse_outline_frontmatter(text: str) -> dict[str, Any]:
    """解析 outline 的 YAML frontmatter。"""
    import yaml

    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    try:
        return yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        return {}


def parse_outline_characters(text: str) -> list[str]:
    """从 outline 提取在场角色列表。

    优先读 frontmatter 的 present_characters 字段，
    其次找 "在场角色" 段。
    """
    fm = parse_outline_frontmatter(text)
    if fm and "present_characters" in fm:
        chars = fm["present_characters"]
        if isinstance(chars, list):
            return [str(c).strip() for c in chars if c]

    # 回退：搜索 "在场角色" 段
    lines = text.splitlines()
    in_section = False
    chars: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("在场角色"):
            in_section = True
            continue
        if in_section:
            if stripped.startswith("#") or (not stripped):
                if chars:
                    break
                continue
            # 列表项: "- 角色A" 或 "角色A、角色B"
            if stripped.startswith("- "):
                chars.append(stripped[2:].strip())
            elif stripped.startswith("-"):
                chars.append(stripped[1:].strip())
            elif "、" in stripped or "，" in stripped:
                import re
                chars.extend(re.split(r"[、，,]", stripped))
                chars = [c.strip() for c in chars if c.strip()]
    return chars


def count_events(text: str) -> int:
    """统计 outline 中的事件数量（粗略：数 "关键事件" 下的列表项）。"""
    lines = text.splitlines()
    count = 0
    in_events = False
    for line in lines:
        stripped = line.strip()
        if "关键事件" in stripped and stripped.startswith("#"):
            in_events = True
            continue
        if in_events:
            if stripped.startswith("#") and "关键事件" not in stripped:
                break
            if stripped.startswith("- **") or stripped.startswith("- "):
                count += 1
    return max(count, 1)


def estimate_word_count(text: str) -> int:
    """粗估章节字数：事件数 × 平均事件字数(800)。"""
    events = count_events(text)
    return events * 800
