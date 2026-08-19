"""symbol_collision — 视觉符号撞色检测。

从 worldbook.visual_symbols 读取已注册的视觉符号（颜色/材质/光效等），
扫描 outline 正文是否出现与已分配符号冲突的描述。

worldbook.visual_symbols 格式（可选字段，不存在则跳过）：
  visual_symbols:
    - symbol: "金色光晕"
      assigned_to: "外部观察者"
      chapters: "CH12-15"
    - symbol: "青铜色"
      assigned_to: "命甲"
      chapters: "CH3+"
"""
from __future__ import annotations

import re
from pathlib import Path

from biyu.lint_rules.base import LintContext, LintIssue, LintRule


class SymbolCollisionRule(LintRule):
    """视觉符号撞色检测。"""

    @property
    def name(self) -> str:
        return "symbol_collision"

    @property
    def severity(self):
        return "warning"

    def check(self, target: Path, context: LintContext) -> list[LintIssue]:
        text = target.read_text(encoding="utf-8")
        issues: list[LintIssue] = []

        wb = context.worldbook
        if not wb:
            return issues

        symbols = wb.get("visual_symbols", [])
        if not symbols:
            # 无注册表时不报错，静默跳过
            return issues

        for entry in symbols:
            if not isinstance(entry, dict):
                continue
            symbol = entry.get("symbol", "")
            if not symbol:
                continue

            # 提取核心关键词（如"金色光晕" → ["金色", "光晕"]）
            keywords = self._extract_keywords(symbol)

            # 在 outline 正文中搜索
            for kw in keywords:
                if kw in text:
                    assigned = entry.get("assigned_to", "未知")
                    chapters = entry.get("chapters", "")
                    # 检查是否是同一章节范围内（如果 outline 属于已分配章节则不算冲突）
                    outline_ch = self._extract_chapter_number(target)
                    if outline_ch and self._in_assigned_range(outline_ch, chapters):
                        continue

                    issues.append(LintIssue(
                        rule_name=self.name,
                        severity="warning",
                        message=f"视觉符号撞色: '{kw}'（完整符号 '{symbol}'）在 outline 中出现，"
                                f"但已分配给 '{assigned}'（{chapters}）",
                        location=str(target),
                        suggestion=f"建议改用其他颜色/描述，或加差异化修饰词以区分",
                    ))
                    break  # 一个符号只报一次

        return issues

    @staticmethod
    def _extract_keywords(symbol: str) -> list[str]:
        """从符号描述提取搜索关键词。

        "金色光晕" → ["金色光晕", "金色"]
        "青铜色" → ["青铜色", "青铜"]
        """
        keywords = [symbol]
        # 提取颜色词
        color_suffixes = ["色", "光", "光晕", "光芒"]
        for suffix in color_suffixes:
            if symbol.endswith(suffix):
                base = symbol[:-len(suffix)]
                if base and len(base) >= 2:
                    keywords.append(base)
        return keywords

    @staticmethod
    def _extract_chapter_number(path: Path) -> int | None:
        """从文件名提取章节号（ch20.md → 20）。"""
        match = re.search(r"ch(\d+)", path.stem)
        return int(match.group(1)) if match else None

    @staticmethod
    def _in_assigned_range(chapter: int, range_str: str) -> bool:
        """检查章节号是否在已分配范围内。

        支持格式: "CH12-15", "CH3+", "CH12,CH15"
        """
        if not range_str:
            return False

        # "CH3+" 表示从 CH3 开始
        if range_str.endswith("+"):
            match = re.search(r"(\d+)", range_str)
            if match and chapter >= int(match.group(1)):
                return True

        # "CH12-15" 范围
        range_match = re.search(r"(\d+)\s*[-–]\s*(\d+)", range_str)
        if range_match:
            start, end = int(range_match.group(1)), int(range_match.group(2))
            if start <= chapter <= end:
                return True

        # "CH12,CH15" 逗号分隔
        nums = re.findall(r"(\d+)", range_str)
        if nums and str(chapter) in nums:
            return True

        return False
