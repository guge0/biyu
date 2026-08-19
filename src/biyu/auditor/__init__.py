"""Auditor 基础版 — 插件式章节质量检查。

主入口: run_audit(chapter_text, ctx) → list[AuditResult]

新增检查器只需加文件 + 改 config/auditor.yaml，不改本文件。
检查器之间无相互依赖。任一检查器异常 → 输出 WARN、其他继续、不阻塞 pipeline。
"""
from __future__ import annotations

import json
import importlib
import logging
from pathlib import Path

from biyu.auditor.base import AuditResult, BaseAuditor, Severity
from biyu.auditor.config import load_auditor_config, get_checker_config

logger = logging.getLogger(__name__)

# 检查器模块映射: name → module_path.class_name
_CHECKER_REGISTRY: dict[str, str] = {
    "dedup": "biyu.auditor.dedup.DedupAuditor",
    "worldbook_check": "biyu.auditor.worldbook_check.WorldbookCheckAuditor",
    "character_presence": "biyu.auditor.character_presence.CharacterPresenceAuditor",
    "transition": "biyu.auditor.transition.TransitionAuditor",
    "style_repeat": "biyu.auditor.style_repeat.StyleRepeatAuditor",
    "punctuation_density": "biyu.auditor.punctuation_density.PunctuationDensityAuditor",
    "meta_vocab": "biyu.auditor.meta_vocab.MetaVocabAuditor",
    "chapter_ending": "biyu.auditor.chapter_ending.ChapterEndingAuditor",
    "dialogue_ratio": "biyu.auditor.dialogue_ratio.DialogueRatioAuditor",
    "character_naming": "biyu.auditor.character_naming.CharacterNamingAuditor",
    "anchor_check": "biyu.auditor.anchor_check.AnchorCheckAuditor",
    "PLAN_UNAUTHORIZED_MAJOR_EVENT": "biyu.auditor.plan_authorization.PlanAuthorizationAuditor",
}


def _instantiate_checker(class_path: str) -> BaseAuditor:
    """动态加载检查器类。"""
    module_path, class_name = class_path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    return cls()


def run_audit(chapter_text: str, ctx: dict) -> list[AuditResult]:
    """执行所有启用的检查器。

    Args:
        chapter_text: 当前章节正文。
        ctx: 上下文字典，需包含:
            - book_dir: 书目录 Path
            - chapter_num: 章节号 int
            可选:
            - worldbook: worldbook dict
            - characters: 角色列表
            - present_characters: 在场角色列表
            - config: auditor 配置 dict

    Returns:
        所有检查器的 AuditResult 列表。
    """
    # 加载配置
    project_root = ctx.get("project_root")
    config = ctx.get("config") or load_auditor_config(
        project_root if project_root else None
    )
    ctx["config"] = config

    results: list[AuditResult] = []

    for name, class_path in _CHECKER_REGISTRY.items():
        checker_cfg = get_checker_config(config, name)
        if not checker_cfg.get("enabled", True):
            continue

        try:
            checker = _instantiate_checker(class_path)
            result = checker.run(chapter_text, ctx)
            results.append(result)
        except Exception as e:
            logger.exception(f"检查器 {name} 异常")
            results.append(AuditResult(
                checker=name,
                severity=Severity.WARN,
                message=f"检查器异常: {e}",
            ))

    return results


def save_audit_report(book_dir: Path, chapter_num: int, results: list[AuditResult]) -> Path:
    """保存审计报告到 data/<书名>/audit_reports/ch{N}.json。

    Returns:
        报告文件路径。
    """
    report_dir = Path(book_dir) / "audit_reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"ch{chapter_num}.json"

    report_data = {
        "chapter": chapter_num,
        "results": [
            {
                "checker": r.checker,
                "severity": r.severity.value if isinstance(r.severity, Severity) else r.severity,
                "message": r.message,
                "details": r.details,
            }
            for r in results
        ],
        "has_block": any(
            r.severity == Severity.BLOCK for r in results
        ),
    }

    report_path.write_text(
        json.dumps(report_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report_path
