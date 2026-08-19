"""forbidden_check — forbidden 条款扫描。

扫描 outline 是否涉及需要特别判定的 forbidden 条款:
- D-24: worldbook.forbidden 第七条白色空间结算豁免
  （意识/物品/能力/信息可跨秘境，需要上下文判定）
- 半阶补天石等一次性物品
- 其他 forbidden 规则的预检
"""
from __future__ import annotations

import re
from pathlib import Path

from biyu.lint_rules.base import LintContext, LintIssue, LintRule


class ForbiddenCheckRule(LintRule):
    """forbidden 条款预检。"""

    @property
    def name(self) -> str:
        return "forbidden_check"

    @property
    def severity(self):
        return "warning"

    def check(self, target: Path, context: LintContext) -> list[LintIssue]:
        text = target.read_text(encoding="utf-8")
        issues: list[LintIssue] = []

        wb = context.worldbook
        if not wb:
            return issues

        forbidden = wb.get("forbidden", [])

        # D-24: 白色空间结算豁免检测
        issues.extend(self._check_white_space_exemption(text, forbidden, target))

        # forbidden 第一条：未注册角色
        issues.extend(self._check_unregistered_characters(text, target))

        # 检查其他 forbidden 关键词
        issues.extend(self._check_general_forbidden(text, forbidden, target))

        return issues

    def _check_white_space_exemption(
        self, text: str, forbidden: list, target: Path
    ) -> list[LintIssue]:
        """D-24: 检测是否涉及白色空间结算相关情节。"""
        issues: list[LintIssue] = []

        # 白色空间关键词
        ws_keywords = ["白色空间", "结算", "奖励"]
        has_ws_context = any(kw in text for kw in ws_keywords)

        if not has_ws_context:
            return issues

        # 检查是否涉及跨秘境内容
        cross_keywords = ["意识", "传送", "带回", "现实世界", "跨秘境"]
        cross_found = [kw for kw in cross_keywords if kw in text]

        if cross_found:
            # 检查 forbidden 中是否有豁免条款
            has_exemption = any(
                "白色空间结算豁免" in str(rule) or
                ("白色空间" in str(rule) and "结算" in str(rule))
                for rule in forbidden
            )
            if has_exemption:
                issues.append(LintIssue(
                    rule_name=self.name,
                    severity="info",
                    message=f"D-24 白色空间结算豁免相关情节，涉及: {', '.join(cross_found)}。"
                            f"worldbook 已有豁免条款，写作时注意引用豁免规则",
                    location=str(target),
                    suggestion="确认具体情节符合 worldbook.forbidden 中白色空间结算豁免条款",
                ))

        return issues

    def _check_unregistered_characters(
        self, text: str, target: Path
    ) -> list[LintIssue]:
        """检查是否有未注册角色的描述（forbidden 第一条的预检）。"""
        issues: list[LintIssue] = []

        # 寻找"新角色"标记（如果有）
        new_char_patterns = [
            r"新角色[：:]\s*(.+)",
            r"新增角色[：:]\s*(.+)",
        ]
        for pattern in new_char_patterns:
            for match in re.finditer(pattern, text):
                char_desc = match.group(1).strip()
                if len(char_desc) > 5:  # 有实质描述
                    issues.append(LintIssue(
                        rule_name=self.name,
                        severity="warning",
                        message=f"outline 标记新角色: '{char_desc[:30]}'，需确认是否已在 characters.yaml 补卡",
                        location=f"{target}:新角色",
                        suggestion="forbidden 第一条：未注册的有名有姓角色不得出现，群众 NPC 除外",
                    ))

        return issues

    def _check_general_forbidden(
        self, text: str, forbidden: list, target: Path
    ) -> list[LintIssue]:
        """检查一般 forbidden 条款。"""
        issues: list[LintIssue] = []

        # 检查破折号密度（forbidden 中的禁令-破折号）
        dash_count = text.count("——")
        if dash_count > 0:
            # 粗估字数（中文约 1.5 字/词）
            char_count = len(text)
            if char_count > 0:
                per_thousand = dash_count / (char_count / 1000)
                if per_thousand > 3:
                    issues.append(LintIssue(
                        rule_name=self.name,
                        severity="warning",
                        message=f"破折号密度过高: {dash_count} 个/千字 ≈ {per_thousand:.1f} 个/千字"
                                f"（限制 ≤3 个/千字）",
                        location=str(target),
                        suggestion="用句号+短句替代破折号，或独立成段",
                    ))

        return issues
