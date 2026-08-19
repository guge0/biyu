"""audit_reports 双层格式核心数据模型 — 状态机 + JSON 持久化。"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# 状态转换规则
# ---------------------------------------------------------------------------

VALID_TRANSITIONS: dict[str, set[str]] = {
    "open": {"resolved_by_author", "resolved_by_biyu", "dismissed"},
    "resolved_by_author": set(),   # terminal
    "resolved_by_biyu": set(),     # terminal
    "dismissed": set(),            # terminal
}

TERMINAL_STATES = {"resolved_by_author", "resolved_by_biyu", "dismissed"}


# ---------------------------------------------------------------------------
# 辅助结构
# ---------------------------------------------------------------------------

@dataclass
class SuggestionVersion:
    """一次 suggestion 版本（regen 时追加）。"""
    suggestion: str
    source: str  # "editor" | "reviser"
    timestamp: str = ""
    cost_yuan: float = 0.0

    def to_dict(self) -> dict:
        return {
            "suggestion": self.suggestion,
            "source": self.source,
            "timestamp": self.timestamp,
            "cost_yuan": self.cost_yuan,
        }

    @classmethod
    def from_dict(cls, d: dict) -> SuggestionVersion:
        return cls(
            suggestion=d.get("suggestion", ""),
            source=d.get("source", "editor"),
            timestamp=d.get("timestamp", ""),
            cost_yuan=d.get("cost_yuan", 0.0),
        )


@dataclass
class StatusTransition:
    """一次状态转换记录。"""
    from_status: str
    to_status: str
    timestamp: str
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "from_status": self.from_status,
            "to_status": self.to_status,
            "timestamp": self.timestamp,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, d: dict) -> StatusTransition:
        return cls(
            from_status=d.get("from_status", ""),
            to_status=d.get("to_status", ""),
            timestamp=d.get("timestamp", ""),
            note=d.get("note", ""),
        )


# ---------------------------------------------------------------------------
# AuditIssue
# ---------------------------------------------------------------------------

@dataclass
class AuditIssue:
    """一条可追踪的审稿 issue。"""
    id: str
    type: str
    paragraph: int
    description: str
    suggestion: str
    severity: str  # high / medium / low
    status: str = "open"
    voters: list[str] = field(default_factory=list)
    suggestions_history: list[SuggestionVersion] = field(default_factory=list)
    status_history: list[StatusTransition] = field(default_factory=list)
    resolved_at: str | None = None
    resolution_note: str = ""
    quoted_text: str = ""  # 问题段落原文片段，用于 Reviser 引文优先定位

    def can_transition(self, new_status: str) -> bool:
        """检查是否可以转换到 new_status。"""
        allowed = VALID_TRANSITIONS.get(self.status, set())
        return new_status in allowed

    def transition(self, new_status: str, note: str = "") -> bool:
        """执行状态转换。成功返回 True，非法返回 False。"""
        if not self.can_transition(new_status):
            return False
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.status_history.append(StatusTransition(
            from_status=self.status,
            to_status=new_status,
            timestamp=now,
            note=note,
        ))
        self.status = new_status
        if new_status in TERMINAL_STATES:
            self.resolved_at = now
            self.resolution_note = note
        return True

    def add_suggestion(self, suggestion: str, source: str = "reviser",
                       cost_yuan: float = 0.0) -> None:
        """追加一条 suggestion 版本。"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.suggestions_history.append(SuggestionVersion(
            suggestion=suggestion,
            source=source,
            timestamp=now,
            cost_yuan=cost_yuan,
        ))
        # 更新当前 suggestion 为最新
        self.suggestion = suggestion

    @property
    def reviser_call_count(self) -> int:
        """该 issue 的 Reviser 调用次数。"""
        return sum(1 for s in self.suggestions_history if s.source == "reviser")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "paragraph": self.paragraph,
            "description": self.description,
            "suggestion": self.suggestion,
            "severity": self.severity,
            "status": self.status,
            "voters": self.voters,
            "suggestions_history": [s.to_dict() for s in self.suggestions_history],
            "status_history": [t.to_dict() for t in self.status_history],
            "resolved_at": self.resolved_at,
            "resolution_note": self.resolution_note,
            "quoted_text": self.quoted_text,
        }

    @classmethod
    def from_dict(cls, d: dict) -> AuditIssue:
        history = [SuggestionVersion.from_dict(s) for s in d.get("suggestions_history", [])]
        status_hist = [StatusTransition.from_dict(t) for t in d.get("status_history", [])]
        return cls(
            id=d.get("id", ""),
            type=d.get("type", ""),
            paragraph=d.get("paragraph", 0),
            description=d.get("description", ""),
            suggestion=d.get("suggestion", ""),
            severity=d.get("severity", "medium"),
            status=d.get("status", "open"),
            voters=d.get("voters", []),
            suggestions_history=history,
            status_history=status_hist,
            resolved_at=d.get("resolved_at"),
            resolution_note=d.get("resolution_note", ""),
            quoted_text=d.get("quoted_text", ""),
        )


# ---------------------------------------------------------------------------
# AuditReportJSON — 章级报告
# ---------------------------------------------------------------------------

@dataclass
class AuditReportJSON:
    """一章的审稿报告（JSON 持久化）。"""
    chapter: int
    generated_at: str
    editor_mode: str = "single"
    editor_cost_yuan: float = 0.0
    reviser_total_cost_yuan: float = 0.0
    reviser_call_count: int = 0
    issues: list[AuditIssue] = field(default_factory=list)
    # 兼容旧格式: results 字段
    results: list[dict] = field(default_factory=list)

    def get_issue(self, issue_id: str) -> AuditIssue | None:
        """按 id 获取 issue。"""
        for iss in self.issues:
            if iss.id == issue_id:
                return iss
        return None

    def open_issues(self) -> list[AuditIssue]:
        """返回所有 open 状态的 issue。"""
        return [i for i in self.issues if i.status == "open"]

    def is_chapter_finalized(self) -> bool:
        """所有 issue 都已解决/忽略。"""
        return all(i.status in TERMINAL_STATES for i in self.issues)

    def save(self, report_dir: Path) -> Path:
        """保存 JSON 到 report_dir/ch{chapter}.json。"""
        report_dir.mkdir(parents=True, exist_ok=True)
        path = report_dir / f"ch{self.chapter}.json"
        data = self.to_dict()
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path

    @classmethod
    def load(cls, path: Path) -> AuditReportJSON:
        """从 JSON 文件加载。兼容新旧两种格式。"""
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        issues = [AuditIssue.from_dict(i) for i in data.get("issues", [])]
        return cls(
            chapter=data.get("chapter", 0),
            generated_at=data.get("generated_at", ""),
            editor_mode=data.get("editor_mode", "single"),
            editor_cost_yuan=data.get("editor_cost_yuan", 0.0),
            reviser_total_cost_yuan=data.get("reviser_total_cost_yuan", 0.0),
            reviser_call_count=data.get("reviser_call_count", 0),
            issues=issues,
            results=data.get("results", []),
        )

    def to_dict(self) -> dict:
        return {
            "chapter": self.chapter,
            "generated_at": self.generated_at,
            "editor_mode": self.editor_mode,
            "editor_cost_yuan": self.editor_cost_yuan,
            "reviser_total_cost_yuan": self.reviser_total_cost_yuan,
            "reviser_call_count": self.reviser_call_count,
            "issues": [i.to_dict() for i in self.issues],
            "results": self.results,
        }


# ---------------------------------------------------------------------------
# 构造函数: EditorResult → AuditReportJSON
# ---------------------------------------------------------------------------

def build_report_from_editor_result(
    chapter_num: int,
    editor_result: Any,  # EditorResult from parser.py
    editor_cost_yuan: float = 0.0,
    editor_mode: str = "single",
) -> AuditReportJSON:
    """从 EditorResult 构造 AuditReportJSON。"""
    issues: list[AuditIssue] = []
    for idx, ei in enumerate(editor_result.issues):
        issue_id = f"ch{chapter_num}-{idx + 1:03d}"
        initial_suggestion = SuggestionVersion(
            suggestion=ei.fix_suggestion,
            source="editor",
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
        issues.append(AuditIssue(
            id=issue_id,
            type=ei.type,
            paragraph=ei.line,
            description=ei.explanation,
            suggestion=ei.fix_suggestion,
            severity=ei.severity,
            status="open",
            suggestions_history=[initial_suggestion],
            quoted_text=ei.quoted_text,
        ))

    return AuditReportJSON(
        chapter=chapter_num,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        editor_mode=editor_mode,
        editor_cost_yuan=editor_cost_yuan,
        issues=issues,
    )
