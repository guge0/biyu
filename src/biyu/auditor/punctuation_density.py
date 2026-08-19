"""破折号/省略号/感叹号密度检查器。

针对评审发现的 AI 文风顽疾:破折号成灾(165 个/5 章,平均每 446 字一个)。
"""
from __future__ import annotations

from biyu.auditor.base import AuditResult, BaseAuditor, Severity
from biyu.auditor.config import get_checker_config


class PunctuationDensityAuditor(BaseAuditor):
    """检查破折号、省略号、感叹号的千字密度。"""

    @property
    def name(self) -> str:
        return "punctuation_density"

    def run(self, chapter_text: str, ctx: dict) -> AuditResult:
        config = ctx.get("config", {})
        checker_cfg = get_checker_config(config, self.name)

        em_dash_threshold = checker_cfg.get("em_dash_threshold", 3.0)
        ellipsis_threshold = checker_cfg.get("ellipsis_threshold", 2.0)
        exclamation_threshold = checker_cfg.get("exclamation_threshold", 8.0)

        word_count = len([c for c in chapter_text if '\u4e00' <= c <= '\u9fff'])
        thousand_count = max(word_count / 1000, 1)

        em_dash_count = chapter_text.count('——')
        ellipsis_count = chapter_text.count('……')
        exclamation_count = chapter_text.count('!') + chapter_text.count('！')

        em_dash_per_k = em_dash_count / thousand_count
        ellipsis_per_k = ellipsis_count / thousand_count
        exclamation_per_k = exclamation_count / thousand_count

        em_dash_violation = em_dash_per_k > em_dash_threshold
        ellipsis_violation = ellipsis_per_k > ellipsis_threshold
        exclamation_violation = exclamation_per_k > exclamation_threshold

        violations = []
        if em_dash_violation:
            violations.append(f"破折号 {em_dash_count} 个 ({em_dash_per_k:.1f}/千字),超过 {em_dash_threshold}/千字阈值")
        if ellipsis_violation:
            violations.append(f"省略号 {ellipsis_count} 个 ({ellipsis_per_k:.1f}/千字),超过 {ellipsis_threshold}/千字阈值")
        if exclamation_violation:
            violations.append(f"感叹号 {exclamation_count} 个 ({exclamation_per_k:.1f}/千字),超过 {exclamation_threshold}/千字阈值")

        # 破折号超标 → BLOCK;其他超标 → WARN
        if em_dash_violation:
            severity = Severity.BLOCK
        elif violations:
            severity = Severity.WARN
        else:
            severity = Severity.PASS

        if violations:
            return AuditResult(
                checker=self.name,
                severity=severity,
                message="; ".join(violations),
                details={
                    "em_dash_per_k": round(em_dash_per_k, 2),
                    "ellipsis_per_k": round(ellipsis_per_k, 2),
                    "exclamation_per_k": round(exclamation_per_k, 2),
                },
            )

        return AuditResult(
            checker=self.name,
            severity=Severity.PASS,
            message=f"标点密度正常 (—— {em_dash_per_k:.1f}/k, …… {ellipsis_per_k:.1f}/k, ! {exclamation_per_k:.1f}/k)",
            details={
                "em_dash_per_k": round(em_dash_per_k, 2),
                "ellipsis_per_k": round(ellipsis_per_k, 2),
                "exclamation_per_k": round(exclamation_per_k, 2),
            },
        )
