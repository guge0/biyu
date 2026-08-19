"""character_check — 在场角色清单提取 + characters.yaml 比对 + NPC 标记 + 字数密度。

检测项:
- #1: 在场角色清单提取（从 frontmatter present_characters 字段）
- #2: 与 characters.yaml 比对，标记新角色（必补 / 可豁免 / Phase 5 推迟）
- #3: 与 NPC 比对，标记疑似 NPC（不补卡）
- #7: 字数密度估算
"""
from __future__ import annotations

from pathlib import Path

from biyu.lint_rules.base import (
    LintContext,
    LintIssue,
    LintRule,
    estimate_word_count,
    parse_outline_characters,
)


class CharacterCheckRule(LintRule):
    """在场角色比对 + 字数密度估算。"""

    @property
    def name(self) -> str:
        return "character_check"

    @property
    def severity(self):
        return "warning"

    def check(self, target: Path, context: LintContext) -> list[LintIssue]:
        text = target.read_text(encoding="utf-8")
        issues: list[LintIssue] = []

        # 提取在场角色
        present = parse_outline_characters(text)
        if not present:
            issues.append(LintIssue(
                rule_name=self.name,
                severity="warning",
                message="未找到在场角色清单（frontmatter present_characters 或 '在场角色' 段）",
                location=str(target),
                suggestion="在 outline 的 YAML frontmatter 中添加 present_characters 字段",
            ))
            return issues

        # 构建已知角色名集合
        known_names = set()
        npc_names = set()
        for char in context.characters:
            name = char.get("name", "")
            if name:
                known_names.add(name)
            tier = char.get("tier", "")
            if tier == "npc":
                npc_names.add(name)
            # 也收集 aliases 中的称谓
            aliases = char.get("aliases", {})
            if isinstance(aliases, dict):
                called_by = aliases.get("called_by", {})
                if isinstance(called_by, dict):
                    for alias_names in called_by.values():
                        if isinstance(alias_names, str):
                            known_names.add(alias_names)
                        elif isinstance(alias_names, list):
                            known_names.update(alias_names)

        # 与 characters.yaml 比对
        for char_name in present:
            if char_name in known_names:
                continue

            # 检查是否在 NPC 列表中
            if char_name in npc_names:
                issues.append(LintIssue(
                    rule_name=self.name,
                    severity="info",
                    message=f"角色 '{char_name}' 为 NPC 级别，不补卡",
                    location=str(target),
                    suggestion="NPC 角色不需要补卡，确认其出场符合 forbidden 第一条（不超过50字台词、不推动剧情）",
                ))
                continue

            # 判断是否为已知原作角色（NPC 豁免）
            if self._is_original_character(char_name, context):
                issues.append(LintIssue(
                    rule_name=self.name,
                    severity="info",
                    message=f"角色 '{char_name}' 为原作角色，worldbook NPC 豁免",
                    location=str(target),
                    suggestion="原作角色不需要在 characters.yaml 补卡",
                ))
                continue

            # 未知角色：需要补卡
            issues.append(self._classify_new_character(char_name, target, text))

        # 字数密度估算
        word_est = estimate_word_count(text)
        min_words = 3500  # 默认最低字数
        if word_est < min_words:
            issues.append(LintIssue(
                rule_name=self.name,
                severity="warning",
                message=f"字数密度估算: {word_est} 字（目标 ≥{min_words}）",
                location=str(target),
                suggestion=f"当前事件数可能不足以达到 {min_words} 字，考虑增加事件或扩展场景",
            ))

        return issues

    def _is_original_character(self, char_name: str, context: LintContext) -> bool:
        """判断是否为原作角色（萧炎/药老/曹操/刘备等来自源世界的角色）。"""
        wb = context.worldbook
        if not wb:
            return False

        # 从 worldbook timeline 提取源世界角色名
        timeline = wb.get("timeline", [])
        timeline_text = " ".join(timeline) if timeline else ""

        # 从 narrative_anchors 中提取元词汇禁令里提到的角色
        anchors = wb.get("narrative_anchors", {})
        constraints = anchors.get("writing_constraints", {})
        pov = constraints.get("pov_consistency", [])
        pov_text = " ".join(pov) if pov else ""

        # 常见原作角色关键词（来自 worldbook 已提及的）
        original_markers = ["曹操", "关羽", "刘备", "诸葛亮", "孙权", "周瑜",
                            "萧炎", "药老", "纳兰", "帝皇侠"]
        # 在 worldbook 文本中被提及但不在 characters.yaml 中的名字
        for marker in original_markers:
            if char_name == marker:
                return True
            if marker in char_name or char_name in marker:
                return True

        # 检查是否在 timeline 的源世界描述中出现
        if char_name in timeline_text:
            # 但如果这个角色已经在 characters.yaml 中有卡，则不算原作豁免
            for char in context.characters:
                if char.get("name") == char_name:
                    return False
            return True

        return False

    def _classify_new_character(self, char_name: str, target: Path, text: str) -> LintIssue:
        """对未知角色分类: 必补 / 可豁免 / Phase 5 推迟。"""
        # 检查这个角色在 outline 中是否有连续台词或推动剧情
        has_dialogue = False
        has_plot_role = False

        for line in text.splitlines():
            if char_name in line:
                # 有引号包围的台词
                if f"{char_name}：" in line or f"{char_name}:" in line:
                    has_dialogue = True
                # 在关键事件中出现
                if line.strip().startswith("- **") and char_name in line:
                    has_plot_role = True

        if has_plot_role or has_dialogue:
            return LintIssue(
                rule_name=self.name,
                severity="error",
                message=f"新角色 '{char_name}' 有台词/推动剧情，**必补卡**",
                location=str(target),
                suggestion=f"在 characters.yaml 中为 '{char_name}' 添加角色卡（tier 根据戏份选择）",
            )

        return LintIssue(
            rule_name=self.name,
            severity="warning",
            message=f"新角色 '{char_name}' 未在 characters.yaml 注册，建议确认是否需要补卡",
            location=str(target),
            suggestion="如果角色仅作路人/群众出场且不推动剧情，可标记为可豁免；否则需补卡",
        )
