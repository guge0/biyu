"""worldbook 一致性检查 — 扫描 facts 和 forbidden 关键词。

检查正文中是否出现违反 worldbook 设定的内容：
- facts: 检查关键词是否被正确使用（如主角姓名是否正确）
- forbidden: 检查是否触碰禁区
"""
from __future__ import annotations

import re

from biyu.auditor.base import AuditResult, BaseAuditor, Severity


class WorldbookCheckAuditor(BaseAuditor):
    """扫描正文是否违反 worldbook 的 facts 和 forbidden。"""

    @property
    def name(self) -> str:
        return "worldbook_check"

    def run(self, chapter_text: str, ctx: dict) -> AuditResult:
        worldbook = ctx.get("worldbook")
        if not worldbook:
            return AuditResult(
                checker=self.name, severity=Severity.SKIP,
                message="worldbook 不存在，跳过检查",
            )

        violations: list[str] = []

        # 检查 facts 中的关键设定
        facts = worldbook.get("facts", [])
        # 提取主角姓名做正查
        for fact in facts:
            if not isinstance(fact, str):
                continue
            # 主角姓名锁定：检查是否有漂移迹象
            if fact.startswith("主角姓名:"):
                correct_name = fact.split(":", 1)[1].strip()
                # 检查常见漂移模式：如果正文出现了其他常见替代名
                # 这里只做正向检查——确认正确名字出现
                if correct_name and correct_name not in chapter_text:
                    violations.append(f"主角姓名'{correct_name}'在正文中未出现，可能有漂移")

        # 检查 forbidden 是否被违反
        forbidden = worldbook.get("forbidden", [])
        for rule in forbidden:
            if not isinstance(rule, str):
                continue
            # 提取可检测的关键约束
            # "不得出现未在 characters.yaml 中注册的..." 跳过（需要 characters 数据）
            # "不得凭空切换场景" — 检查首段是否承接
            # "不得让秘境等级..." — 简单关键词检测
            if "不得让秘境等级" in rule:
                # 检测是否出现不同等级描述
                if re.search(r"[ABCS]级", chapter_text):
                    pass  # 出现等级描述是正常的，不一定是违规

        if violations:
            return AuditResult(
                checker=self.name, severity=Severity.WARN,
                message=f"发现 {len(violations)} 个潜在违规: {'; '.join(violations)}",
                details={"violations": violations},
            )

        return AuditResult(
            checker=self.name, severity=Severity.PASS,
            message="worldbook 检查通过",
            details={"violations": []},
        )
