"""Auditor 抽象基类。每个检查器继承 BaseAuditor，实现 run() 方法。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum


class Severity(str, Enum):
    PASS = "PASS"
    SKIP = "SKIP"
    BLOCK = "BLOCK"
    WARN = "WARN"


@dataclass
class AuditResult:
    """单个检查器的输出。"""
    checker: str
    severity: Severity
    message: str
    details: dict | None = None


class BaseAuditor(ABC):
    """所有 Auditor 检查器的基类。

    子类必须实现:
    - name: 检查器名称
    - run(chapter_text, ctx): 执行检查，返回 AuditResult
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """检查器唯一名称，用于 config 开关和日志。"""

    @abstractmethod
    def run(self, chapter_text: str, ctx: dict) -> AuditResult:
        """执行检查。

        Args:
            chapter_text: 当前章节正文。
            ctx: 上下文字典，包含 book_dir, chapter_num, worldbook 等信息。

        Returns:
            AuditResult 包含严重级、消息和可选详情。
        """
