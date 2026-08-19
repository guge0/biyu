"""biyu lint_rules — outline / sub-md 工程冲突扫描规则库。

每条规则继承 LintRule，实现 check() 方法。
入口: run_lint(target, context) → list[LintIssue]
"""
from __future__ import annotations

import importlib
import logging
from pathlib import Path

from biyu.lint_rules.base import LintContext, LintIssue, LintRule

logger = logging.getLogger(__name__)

# 规则注册表: name → module_path.class_name
_RULE_REGISTRY: dict[str, str] = {
    "character_check": "biyu.lint_rules.character_check.CharacterCheckRule",
    "symbol_collision": "biyu.lint_rules.symbol_collision.SymbolCollisionRule",
    "forbidden_check": "biyu.lint_rules.forbidden_check.ForbiddenCheckRule",
    "hook_tracking": "biyu.lint_rules.hook_tracking.HookTrackingRule",
    "worldbook_check": "biyu.lint_rules.worldbook_check.WorldbookRefRule",
    "wb_impact_scan": "biyu.lint_rules.wb_impact_scan.WbImpactRule",
}


def _instantiate_rule(class_path: str) -> LintRule:
    """动态加载规则类。"""
    module_path, class_name = class_path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    return cls()


def run_lint(
    target: Path,
    context: LintContext,
    rules: list[str] | None = None,
) -> list[LintIssue]:
    """执行 lint 规则扫描。

    Args:
        target: 要扫描的 outline / sub-md 文件路径。
        context: lint 上下文，包含 book_dir、characters 等。
        rules: 要运行的规则名列表，None 表示全部。

    Returns:
        所有规则的 LintIssue 列表。
    """
    issues: list[LintIssue] = []

    for name, class_path in _RULE_REGISTRY.items():
        if name == "wb_impact_scan":
            # wb-impact 有自己的入口，不参与普通 lint
            continue
        if rules and name not in rules:
            continue

        try:
            rule = _instantiate_rule(class_path)
            rule_issues = rule.check(target, context)
            issues.extend(rule_issues)
        except Exception as e:
            logger.exception(f"规则 {name} 异常")
            issues.append(LintIssue(
                rule_name=name,
                severity="error",
                message=f"规则执行异常: {e}",
                location=str(target),
            ))

    return issues
