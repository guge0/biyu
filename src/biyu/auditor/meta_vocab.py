"""元词汇黑名单检查器。

针对评审发现的"曹操说后人编的"跨时空穿帮问题。
仅在秘境内场景检查(通过 outline 或 planning 中是否有"秘境"判断)。
"""
from __future__ import annotations

from biyu.auditor.base import AuditResult, BaseAuditor, Severity
from biyu.auditor.config import get_checker_config

META_VOCAB_BLACKLIST = ["后人", "后世", "史书", "未来", "先人", "流传", "记载", "典籍", "传记"]


class MetaVocabAuditor(BaseAuditor):
    """检查秘境场景中的元词汇使用。"""

    @property
    def name(self) -> str:
        return "meta_vocab"

    def run(self, chapter_text: str, ctx: dict) -> AuditResult:
        config = ctx.get("config", {})
        checker_cfg = get_checker_config(config, self.name)
        if not checker_cfg.get("enabled", True):
            return AuditResult(
                checker=self.name, severity=Severity.SKIP,
                message="检查器已禁用", details={},
            )

        # 检测是否秘境内场景(简单启发式)
        outline = ctx.get("outline", "")
        planning = ctx.get("planning", "")
        check_source = outline + planning
        in_secret_realm = any(kw in check_source for kw in ["秘境内", "白色空间", "三国", "铠甲勇士", "斗破"])
        if not in_secret_realm:
            return AuditResult(
                checker=self.name, severity=Severity.SKIP,
                message="非秘境场景,跳过元词汇检查", details={},
            )

        violations = []
        for vocab in META_VOCAB_BLACKLIST:
            count = chapter_text.count(vocab)
            if count > 0:
                idx = chapter_text.find(vocab)
                context = chapter_text[max(0, idx - 30):idx + len(vocab) + 30]
                violations.append(f"'{vocab}' 出现 {count} 次,上下文:'...{context}...'")

        if violations:
            return AuditResult(
                checker=self.name,
                severity=Severity.WARN,
                message=f"发现 {len(violations)} 个元词汇",
                details={"violations": violations},
            )

        return AuditResult(
            checker=self.name,
            severity=Severity.PASS,
            message="元词汇检查通过",
            details={},
        )
