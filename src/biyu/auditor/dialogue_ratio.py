"""对话占比检测器。

针对评审发现的 ch4-5 全章坐着说话问题。
"""
from __future__ import annotations

import re

from biyu.auditor.base import AuditResult, BaseAuditor, Severity
from biyu.auditor.config import get_checker_config


class DialogueRatioAuditor(BaseAuditor):
    """检测章节中对话占比是否过高。"""

    @property
    def name(self) -> str:
        return "dialogue_ratio"

    def run(self, chapter_text: str, ctx: dict) -> AuditResult:
        config = ctx.get("config", {})
        checker_cfg = get_checker_config(config, self.name)
        ratio_threshold = checker_cfg.get("ratio_threshold", 0.6)

        dialogue_pattern = r'[\u201c\u201d「」"][^\u201c\u201d「」"]*?[\u201c\u201d「」"]'
        matches = re.findall(dialogue_pattern, chapter_text)
        dialogue_chars = sum(len(m) for m in matches)
        total_chars = len([c for c in chapter_text if '\u4e00' <= c <= '\u9fff'])
        if total_chars == 0:
            return AuditResult(
                checker=self.name, severity=Severity.SKIP,
                message="无中文字符", details={},
            )

        ratio = dialogue_chars / total_chars

        if ratio > ratio_threshold:
            return AuditResult(
                checker=self.name,
                severity=Severity.WARN,
                message=f"对话占比 {ratio:.1%},超过 {ratio_threshold:.0%} 阈值,可能是对话过密",
                details={"ratio": round(ratio, 4)},
            )

        return AuditResult(
            checker=self.name,
            severity=Severity.PASS,
            message=f"对话占比 {ratio:.1%},正常",
            details={"ratio": round(ratio, 4)},
        )
