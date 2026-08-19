"""章末重启检测器。

针对评审发现的 ch1 章末重启 bug:章末写了"赤壁开始了",后续又续了段落讨论怎么躲。
"""
from __future__ import annotations

from biyu.auditor.base import AuditResult, BaseAuditor, Severity
from biyu.auditor.config import get_checker_config


class ChapterEndingAuditor(BaseAuditor):
    """检测章末是否出现场景重启(与前文内容高度重叠)。"""

    @property
    def name(self) -> str:
        return "chapter_ending"

    def run(self, chapter_text: str, ctx: dict) -> AuditResult:
        config = ctx.get("config", {})
        checker_cfg = get_checker_config(config, self.name)
        threshold = checker_cfg.get("jaccard_threshold", 0.4)

        if len(chapter_text) < 5800:
            return AuditResult(
                checker=self.name, severity=Severity.SKIP,
                message="章节过短,跳过末段检查", details={},
            )

        head = chapter_text[:5000]
        tail = chapter_text[-800:]

        def to_grams(text: str, n: int = 2) -> set[str]:
            return set(text[i:i + n] for i in range(len(text) - n + 1))

        head_grams = to_grams(head)
        tail_grams = to_grams(tail)
        if not head_grams or not tail_grams:
            return AuditResult(
                checker=self.name, severity=Severity.SKIP,
                message="无法计算 jaccard", details={},
            )

        jaccard = len(head_grams & tail_grams) / len(head_grams | tail_grams)

        if jaccard > threshold:
            return AuditResult(
                checker=self.name,
                severity=Severity.WARN,
                message=f"章末 800 字与前 5000 字 jaccard={jaccard:.2f},超过 {threshold} 阈值,可能是章末重启",
                details={"jaccard": round(jaccard, 4)},
            )

        return AuditResult(
            checker=self.name,
            severity=Severity.PASS,
            message=f"章末完整性 OK (jaccard={jaccard:.2f})",
            details={"jaccard": round(jaccard, 4)},
        )
