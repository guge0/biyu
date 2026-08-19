"""在场角色检查 — 正文中出现的有名角色 vs 在场清单。

按 tier 分严格度:
- protagonist 缺席 = BLOCK
- antagonist/major_supporting 缺席 = WARN
- supporting/npc 缺席 = 不报
"""
from __future__ import annotations

import re

from biyu.auditor.base import AuditResult, BaseAuditor, Severity


def _extract_named_characters(chapter_text: str, known_names: list[str]) -> list[str]:
    """从正文中提取出现的已知角色名。"""
    found = []
    for name in known_names:
        if name in chapter_text:
            found.append(name)
    return found


class CharacterPresenceAuditor(BaseAuditor):
    """检查在场角色一致性。"""

    @property
    def name(self) -> str:
        return "character_presence"

    def run(self, chapter_text: str, ctx: dict) -> AuditResult:
        present_characters = ctx.get("present_characters", [])
        characters = ctx.get("characters", [])

        # 构建 name → tier 映射
        name_to_tier: dict[str, str] = {}
        for c in characters:
            if isinstance(c, dict) and c.get("name"):
                name_to_tier[c["name"]] = c.get("tier", "supporting")

        known_names = list(name_to_tier.keys())
        appeared = _extract_named_characters(chapter_text, known_names)

        if not present_characters:
            return AuditResult(
                checker=self.name, severity=Severity.SKIP,
                message=f"无在场角色清单，正文中出现的角色: {', '.join(appeared) if appeared else '未识别'}",
                details={"appeared": appeared, "expected": []},
            )

        unexpected = [n for n in appeared if n not in present_characters]
        missing = [n for n in present_characters if n not in appeared]

        # 按 tier 分级处理 missing 角色
        block_missing: list[str] = []
        warn_missing: list[str] = []
        for n in missing:
            tier = name_to_tier.get(n, "supporting")
            if tier == "protagonist":
                block_missing.append(n)
            elif tier in ("antagonist", "major_supporting"):
                warn_missing.append(n)
            # supporting/npc missing = 不报

        messages = []
        if unexpected:
            messages.append(f"非在场角色出现: {', '.join(unexpected)}")
        if block_missing:
            messages.append(f"核心角色缺席: {', '.join(block_missing)}")
        if warn_missing:
            messages.append(f"重要角色缺席: {', '.join(warn_missing)}")

        if block_missing:
            return AuditResult(
                checker=self.name, severity=Severity.BLOCK,
                message="; ".join(messages),
                details={"appeared": appeared, "expected": present_characters,
                         "unexpected": unexpected, "missing": missing,
                         "block_missing": block_missing},
            )
        if messages:
            return AuditResult(
                checker=self.name, severity=Severity.WARN,
                message="; ".join(messages),
                details={"appeared": appeared, "expected": present_characters,
                         "unexpected": unexpected, "missing": missing,
                         "warn_missing": warn_missing},
            )

        return AuditResult(
            checker=self.name, severity=Severity.PASS,
            message=f"在场角色一致: {', '.join(appeared)}",
            details={"appeared": appeared, "expected": present_characters},
        )
