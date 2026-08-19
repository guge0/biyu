"""audit_report 生成逻辑 — 整合所有 Auditor 输出到一个 md/章。"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader


def _get_template_env() -> Environment:
    """Get Jinja2 template environment."""
    template_dir = Path(__file__).parent / "templates"
    return Environment(
        loader=FileSystemLoader(str(template_dir)),
        keep_trailing_newline=True,
    )


def _classify_severity(severity: str) -> tuple[str, str]:
    """Classify severity into icon and label."""
    s = severity.upper()
    if s == "BLOCK":
        return "❌", "BLOCK"
    elif s == "WARN":
        return "⚠️", "WARN"
    elif s == "PASS":
        return "✅", "PASS"
    elif s == "SKIP":
        return "⏭", "SKIP"
    else:
        return "•", s


def _classify_issue_severity(severity: str) -> tuple[str, str]:
    """Classify issue severity for reviser template."""
    s = severity.lower()
    if s == "high":
        return "🔴", "HIGH"
    elif s == "medium":
        return "🟡", "MEDIUM"
    elif s == "low":
        return "🟢", "LOW"
    else:
        return "•", s.upper()


def _status_label(status: str) -> str:
    """Human-readable status label."""
    labels = {
        "open": "待处理",
        "resolved_by_author": "作者已修",
        "resolved_by_biyu": "已自动修",
        "dismissed": "已忽略",
    }
    return labels.get(status, status)


def build_audit_report(
    book_dir: Path,
    chapter_num: int,
    *,
    audit_results: list[dict] | None = None,
    word_count: int = 0,
    postproc_summary: str = "",
    pending: bool = False,
    editor_section: str = "",
) -> Path:
    """Build an audit report markdown file for a chapter.

    If audit_results is None, tries to load from existing JSON.

    Returns the path to the generated report.
    """
    report_dir = book_dir / "audit_reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"ch{chapter_num}.md"

    # Load from JSON if not provided
    if audit_results is None:
        audit_json = report_dir / f"ch{chapter_num}.json"
        if audit_json.exists():
            with open(audit_json, encoding="utf-8") as f:
                data = json.load(f)
            audit_results = data.get("results", [])
        else:
            audit_results = []

    # Get word count from chapter file if not provided
    if word_count == 0:
        ch_file = book_dir / "chapters" / f"ch{chapter_num}.md"
        if not ch_file.exists():
            ch_file = book_dir / "chapters" / "_pending" / f"ch{chapter_num}.md"
        if ch_file.exists():
            text = ch_file.read_text(encoding="utf-8")
            word_count = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')

    # Get git history
    git_history: list[dict] = []
    try:
        from biyu.git_helper import get_chapter_history
        raw_history = get_chapter_history(book_dir, chapter_num, max_entries=20)
        for entry in raw_history:
            msg = entry["message"]
            if msg.startswith("auto:"):
                entry_type = "auto"
            elif msg.startswith("manual:"):
                entry_type = "manual"
            elif msg.startswith("regen:"):
                entry_type = "regen"
            else:
                entry_type = "other"
            git_history.append({
                "type": entry_type,
                "date": entry["date"][:19],
                "message": msg,
            })
    except Exception:
        pass

    # PASS/SKIP are completion facts, not author problems.
    completed_results = []
    problem_cards = []
    for r in audit_results:
        severity = r.get("severity", "?")
        icon, label = _classify_severity(severity)
        item = {
            "checker": r.get("checker", "?"),
            "severity": label,
            "icon": icon,
            "message": r.get("message", ""),
        }
        if label in {"PASS", "SKIP"}:
            completed_results.append(item)
        else:
            problem_cards.append(item)

    # Determine statuses
    has_block = any(
        r.get("severity", "").upper() == "BLOCK"
        for r in audit_results
    )
    overall_status = "❌ 进 _pending/" if (pending or has_block) else "✅ 进 chapters/"

    # Operation suggestion
    if pending or has_block:
        operation_suggestion = (
            f"⚠️ 此章有问题待处理。可用 `biyu review ch{chapter_num}` 查看详情，"
            f"`biyu accept ch{chapter_num}` 接受修改，或 `biyu rewrite ch{chapter_num}` 重生成。"
        )
    else:
        operation_suggestion = (
            f"✅ 已自动接受。可用 `biyu rollback ch{chapter_num}` 查看历史版本。"
        )

    # Render template
    env = _get_template_env()
    template = env.get_template("chapter.md.j2")
    content = template.render(
        chapter_num=chapter_num,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        word_count=word_count,
        overall_status=overall_status,
        completed_results=completed_results,
        completed_count=len(completed_results),
        problem_cards=problem_cards,
        postproc_summary=postproc_summary,
        git_history=git_history,
        operation_suggestion=operation_suggestion,
        editor_section=editor_section,
    )

    report_path.write_text(content, encoding="utf-8")
    return report_path


def backfill_all_reports(book_dir: Path) -> list[tuple[int, Path]]:
    """Backfill audit reports for all chapters that have data.

    Returns list of (chapter_num, report_path) tuples.
    """
    results: list[tuple[int, Path]] = []

    # Find all chapters with data
    chapters_dir = book_dir / "chapters"
    if not chapters_dir.exists():
        return results

    chapter_nums: list[int] = []
    for f in chapters_dir.iterdir():
        if f.is_file() and f.name.startswith("ch") and f.suffix == ".md":
            try:
                num = int(f.stem[2:])
                chapter_nums.append(num)
            except ValueError:
                pass

    # Also check _pending
    pending_dir = chapters_dir / "_pending"
    if pending_dir.exists():
        for f in pending_dir.iterdir():
            if f.is_file() and f.name.startswith("ch") and f.suffix == ".md":
                try:
                    num = int(f.stem[2:])
                    if num not in chapter_nums:
                        chapter_nums.append(num)
                except ValueError:
                    pass

    for num in sorted(chapter_nums):
        # Check if audit JSON exists
        audit_json = book_dir / "audit_reports" / f"ch{num}.json"

        # Build postproc summary from dash_fixer log
        postproc_summary = ""
        meta_json = book_dir / "logs" / f"ch{num}" / "meta.json"
        if meta_json.exists():
            with open(meta_json, encoding="utf-8") as f:
                meta = json.load(f)
            # Check for dash_fixer info in long_run_metrics
            metrics_csv = book_dir / "logs" / "long_run_metrics.csv"
            if metrics_csv.exists():
                import csv
                with open(metrics_csv, encoding="utf-8") as cf:
                    reader = csv.DictReader(cf)
                    for row in reader:
                        if row.get("chapter") == str(num):
                            dash_count = row.get("dash_fixer_count", "0")
                            if dash_count and dash_count != "0":
                                postproc_summary = f"- dash_fixer: {dash_count} 个破折号修复"
                            break

        path = build_audit_report(
            book_dir,
            num,
            postproc_summary=postproc_summary,
        )
        results.append((num, path))

    return results


# ---------------------------------------------------------------------------
# T-P3-D-3: 从 AuditReportJSON 渲染 MD 视图
# ---------------------------------------------------------------------------

def build_audit_md_from_json(report: Any, book_dir: Path) -> Path:
    """从 AuditReportJSON 渲染 MD 视图（checkbox 形式 + CLI 操作提示）。

    Args:
        report: AuditReportJSON 实例。
        book_dir: 书籍目录。

    Returns:
        生成的 MD 文件路径。
    """
    from .state import AuditReportJSON

    report_dir = book_dir / "audit_reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"ch{report.chapter}.md"

    # 准备 issue 数据
    formatted_issues = []
    for issue in report.issues:
        severity_icon, severity_label = _classify_issue_severity(issue.severity)
        status_lbl = _status_label(issue.status)

        # checkbox: open 用 [ ], 其他用 [x]
        checked = "[x]" if issue.status != "open" else "[ ]"

        formatted_issues.append({
            "id": issue.id,
            "type": issue.type,
            "paragraph": issue.paragraph,
            "description": issue.description,
            "suggestion": issue.suggestion,
            "severity": issue.severity,
            "severity_icon": severity_icon,
            "severity_label": severity_label,
            "status": issue.status,
            "status_label": status_lbl,
            "checked": checked,
            "voters": issue.voters,
            "suggestions_history": issue.suggestions_history,
            "quoted_text": issue.quoted_text,
        })

    completed_results = []
    problem_cards = []
    for result in report.results:
        icon, label = _classify_severity(str(result.get("severity", "?")))
        item = {"icon": icon, "severity": label, "checker": result.get("checker", "?"), "message": result.get("message", "")}
        (completed_results if label in {"PASS", "SKIP"} else problem_cards).append(item)

    env = _get_template_env()
    template = env.get_template("chapter_reviser.md.j2")
    content = template.render(
        chapter_num=report.chapter,
        generated_at=report.generated_at,
        editor_mode=report.editor_mode,
        editor_cost_yuan=report.editor_cost_yuan,
        reviser_total_cost_yuan=report.reviser_total_cost_yuan,
        reviser_call_count=report.reviser_call_count,
        issues=formatted_issues,
        completed_results=completed_results,
        completed_count=len(completed_results),
        problem_cards=problem_cards,
        is_finalized=report.is_chapter_finalized(),
    )

    report_path.write_text(content, encoding="utf-8")
    return report_path
