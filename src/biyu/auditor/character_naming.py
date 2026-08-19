"""角色称谓审查器。

检查正文是否出现 characters.yaml 中标记为
forbidden_in_narrative 的字符串(如"张父""张母")。

按 tier 分严格度:
- protagonist/antagonist/major_supporting: BLOCK
- supporting: WARN
- npc: 不报
"""
from __future__ import annotations

from biyu.auditor.base import AuditResult, BaseAuditor, Severity


# tier → severity 映射
_TIER_SEVERITY = {
    "protagonist": Severity.BLOCK,
    "antagonist": Severity.BLOCK,
    "major_supporting": Severity.BLOCK,
    "supporting": Severity.WARN,
    "npc": None,  # 不报
}


class CharacterNamingAuditor(BaseAuditor):
    """检查正文中是否出现了工程层代号(如'张父''张母')。"""

    @property
    def name(self) -> str:
        return "character_naming"

    def run(self, chapter_text: str, ctx: dict) -> AuditResult:
        characters = ctx.get("characters", [])
        block_violations: list[str] = []
        warn_violations: list[str] = []

        for char in characters:
            if not isinstance(char, dict):
                continue

            tier = char.get("tier", "supporting")
            severity = _TIER_SEVERITY.get(tier)

            # NPC 不检查
            if severity is None:
                continue

            forbidden_list = char.get("forbidden_in_narrative", [])
            for forbidden in forbidden_list:
                count = chapter_text.count(forbidden)
                if count > 0:
                    idx = chapter_text.find(forbidden)
                    context = chapter_text[max(0, idx - 20):idx + len(forbidden) + 20]
                    msg = (
                        f"角色'{char['name']}'的禁用称谓'{forbidden}'"
                        f"出现{count}次,上下文:'...{context}...'"
                    )
                    if severity == Severity.BLOCK:
                        block_violations.append(msg)
                    else:
                        warn_violations.append(msg)

        if block_violations:
            return AuditResult(
                checker=self.name,
                severity=Severity.BLOCK,
                message=f"发现 {len(block_violations)} 处称谓穿帮(BLOCK 级)",
                details={"violations": block_violations + warn_violations},
            )
        if warn_violations:
            return AuditResult(
                checker=self.name,
                severity=Severity.WARN,
                message=f"发现 {len(warn_violations)} 处称谓穿帮(WARN 级)",
                details={"violations": warn_violations},
            )
        return AuditResult(
            checker=self.name,
            severity=Severity.PASS,
            message="角色称谓检查通过",
            details={},
        )
