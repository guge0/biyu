"""MD ↔ JSON 双向同步 — 读 MD 中 checkbox → 更新 JSON status。"""
from __future__ import annotations

import re
from pathlib import Path

from .state import AuditReportJSON, AuditIssue


def sync_md_to_json(book_dir: Path, chapter_num: int) -> int:
    """读 MD 报告中的 [x] checkbox → 更新 JSON 对应 issue 为 resolved_by_author。

    Returns:
        更新的 issue 数量。
    """
    report_dir = book_dir / "audit_reports"
    json_path = report_dir / f"ch{chapter_num}.json"
    if not json_path.exists():
        return 0

    report = AuditReportJSON.load(json_path)
    md_path = report_dir / f"ch{chapter_num}.md"
    if not md_path.exists():
        return 0

    md_text = md_path.read_text(encoding="utf-8")

    # 匹配 checkbox 格式: `- [x] ... #<issue-id>` 或 `- [x] ... issue-id`
    # 例: `- [x] 认知边界: ... #ch27-001`
    checked_pattern = re.compile(r'-\s+\[x\]\s+.*?#(\S+)', re.IGNORECASE)
    checked_ids: set[str] = set()
    for m in checked_pattern.finditer(md_text):
        checked_ids.add(m.group(1))

    # 也匹配 issue_id 行内格式: `ch{N}-{NNN}`
    id_pattern = re.compile(r'ch\d+-\d+', re.IGNORECASE)
    for line in md_text.splitlines():
        if '- [x]' in line.lower() or '-[x]' in line.lower():
            for m in id_pattern.finditer(line):
                checked_ids.add(m.group(0))

    updated = 0
    for issue_id in checked_ids:
        issue = report.get_issue(issue_id)
        if issue and issue.status == "open":
            issue.transition("resolved_by_author", note="MD checkbox 勾选")
            updated += 1

    if updated > 0:
        report.save(report_dir)

    return updated
