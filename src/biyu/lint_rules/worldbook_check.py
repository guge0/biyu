"""worldbook_check — 引用校验。

检测 outline 提到的设定/角色/能力是否在 worldbook 或 characters.yaml 中存在。
"""
from __future__ import annotations

import re
from pathlib import Path

from biyu.lint_rules.base import LintContext, LintIssue, LintRule


class WorldbookRefRule(LintRule):
    """引用校验 — outline 提到的设定/角色/能力是否在 worldbook/characters 存在。"""

    @property
    def name(self) -> str:
        return "worldbook_check"

    @property
    def severity(self):
        return "error"

    def check(self, target: Path, context: LintContext) -> list[LintIssue]:
        text = target.read_text(encoding="utf-8")
        issues: list[LintIssue] = []

        wb = context.worldbook
        chars = context.characters

        if not wb:
            return issues

        # 收集 worldbook 中的已知设定名/角色名/能力名
        known_refs = self._build_known_refs(wb, chars)

        # 从 outline 中提取引用
        outline_refs = self._extract_outline_refs(text)

        # 比对
        for ref in outline_refs:
            if ref in known_refs:
                continue

            # 模糊匹配：检查已知引用中是否包含该词
            fuzzy_match = False
            for known in known_refs:
                if ref in known or known in ref:
                    fuzzy_match = True
                    break

            if not fuzzy_match:
                # 检查是否为通用词（不需要在 worldbook 注册的）
                if self._is_generic_term(ref):
                    continue

                issues.append(LintIssue(
                    rule_name=self.name,
                    severity="warning",
                    message=f"引用校验: outline 提到 '{ref}'，但 worldbook/characters 中未找到",
                    location=str(target),
                    suggestion=f"确认 '{ref}' 是否为已有设定的别名，或需要在 worldbook/characters 中补充",
                ))

        return issues

    @staticmethod
    def _build_known_refs(wb: dict, chars: list[dict]) -> set[str]:
        """从 worldbook + characters 构建已知引用集合。"""
        refs: set[str] = set()

        # 角色名
        for char in chars:
            name = char.get("name", "")
            if name:
                refs.add(name)
            # 角色能力
            abilities = char.get("abilities", "")
            if isinstance(abilities, str) and abilities:
                refs.add(abilities)
            # 角色别名
            aliases = char.get("aliases", {})
            if isinstance(aliases, dict):
                called_by = aliases.get("called_by", {})
                if isinstance(called_by, dict):
                    for names in called_by.values():
                        if isinstance(names, str):
                            refs.add(names)
                        elif isinstance(names, list):
                            refs.update(names)

        # worldbook facts 中的关键名
        for fact in wb.get("facts", []):
            if not isinstance(fact, str):
                continue
            # 提取"XX：YY"格式的键
            if "：" in fact or ":" in fact:
                parts = re.split(r"[：:]", fact, 1)
                key = parts[0].strip()
                if key and len(key) <= 20:
                    refs.add(key)
            # 提取"XX"等引号内容
            for quoted in re.findall(r"[『「](.+?)[』」]", fact):
                if quoted and len(quoted) <= 20:
                    refs.add(quoted)

        # 力量体系名称
        power = wb.get("power_system", {})
        if isinstance(power, dict):
            ps_name = power.get("name", "")
            if ps_name:
                refs.add(ps_name)

        # 地理
        for geo in wb.get("geography", []):
            if isinstance(geo, str):
                for name in re.findall(r"^([^：:]+?)[：:]", geo):
                    refs.add(name.strip())

        # 势力
        for faction in wb.get("factions", []):
            if isinstance(faction, str):
                for name in re.findall(r"^([^：:]+?)[：:]", faction):
                    refs.add(name.strip())

        return refs

    @staticmethod
    def _extract_outline_refs(text: str) -> list[str]:
        """从 outline 中提取可能需要校验的引用。

        提取规则:
        - 『XX』 或 「XX」 包围的术语
        - "XX能力" "XX系统" 等能力/系统引用
        - 境界/等级描述
        """
        refs: list[str] = []

        # 书名号/引号包围
        for quoted in re.findall(r"[『「](.+?)[』」]", text):
            if quoted and 2 <= len(quoted) <= 20:
                refs.append(quoted)

        # "XX能力" "XX系统" 模式
        for m in re.finditer(r"([\u4e00-\u9fff]{2,6})(?:能力|系统|体系|功法|技能)", text):
            refs.append(m.group(0))

        # 境界引用: "下三境" "上三境" "X境初期" "X境圆满" 等
        for m in re.finditer(
            r"((?:下三|上三|中三|一|二|三|四|五|六|七|八|九)?"
            r"境(?:初期|中期|高期|圆满|阶段)?)",
            text,
        ):
            refs.append(m.group(0))

        return refs

    @staticmethod
    def _is_generic_term(term: str) -> bool:
        """判断是否为不需要注册的通用术语。"""
        generic = {
            "秘境", "现实世界", "白色空间", "奖励", "结算",
            "金手指", "能力", "战斗", "训练", "修炼", "突破",
            "师傅", "老师", "同学", "队长", "组长",
            "秘境开始结算",
        }
        return term in generic
