"""One-round/one-package persistence for workbench whole-chapter revisions."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4

_LEGACY_LOCAL_MODE = object()
_REVISION_MODES = {"local_revision", "deep_rewrite"}


def text_sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError(f"审读报告无法读取: {path}") from exc


def create_revision_package(
    book_dir: Path,
    chapter: int,
    *,
    selected_issue_ids: list[str],
    issue_comments: dict[str, str],
    general_comment: str,
    candidate_sha: str,
    sample_problem_ids: list[str] | None = None,
    revision_problem_ids: list[str] | None = None,
    revision_problem_lines: list[dict] | None = None,
    mode: object = _LEGACY_LOCAL_MODE,
) -> Path:
    """Persist one immutable revision package and return its final directory."""
    normalized_mode = "local_revision" if mode is _LEGACY_LOCAL_MODE else mode
    if not isinstance(normalized_mode, str) or normalized_mode not in _REVISION_MODES:
        raise ValueError("返修模式无效")
    pending = book_dir / "chapters" / "_pending" / f"ch{chapter}.md"
    planning = book_dir / "logs" / f"ch{chapter}" / "planning.md"
    report_path = book_dir / "audit_reports" / f"ch{chapter}.json"
    if not pending.exists():
        raise ValueError("没有候选稿，不能提交整章修订")
    if not planning.exists():
        raise ValueError("写作方案不存在，不能组装修订任务")
    candidate_text = pending.read_text(encoding="utf-8")
    actual_sha = text_sha(candidate_text)
    if not candidate_sha or candidate_sha != actual_sha:
        raise ValueError("候选稿已有新版本；请刷新后重新选择问题")

    report = _load_json(report_path)
    issue_by_id = {str(item.get("id")): item for item in report.get("issues", []) if item.get("id")}
    for index, result in enumerate(report.get("results", []), 1):
        severity = str(result.get("severity", "")).upper()
        if severity not in {"WARN", "BLOCK"}:
            continue
        issue_id = f"auditor-{result.get('checker', 'check')}-{index}"
        issue_by_id[issue_id] = {
            "id": issue_id,
            "type": result.get("checker", "检查"),
            "severity": severity,
            "description": result.get("message", ""),
            "suggestion": "请结合正文核对并按作者意见修订",
            "source": "auditor",
        }
    selected: list[dict] = []
    missing: list[str] = []
    for issue_id in dict.fromkeys(selected_issue_ids):
        issue = issue_by_id.get(issue_id)
        if issue is None:
            missing.append(issue_id)
            continue
        selected.append({**issue, "author_comment": issue_comments.get(issue_id, "").strip()})
    if missing:
        raise ValueError("这些问题卡已变化，请刷新: " + ", ".join(missing))
    for item in revision_problem_lines or []:
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        selected.append({
            "id": str(item.get("id", "")) or f"manual-{len(selected) + 1}",
            "type": "作者划定问题句",
            "severity": "WARN",
            "description": text,
            "paragraph": int(item.get("anchor", 0) or 0),
            "suggestion": "按作者批注加入本轮返修",
            "author_comment": str(item.get("author_comment", "")).strip(),
            "source": "author_selection",
        })
    if not selected and not general_comment.strip():
        raise ValueError("请至少选择一个问题，或填写整体修改意见")

    revisions = book_dir / "logs" / f"ch{chapter}" / "revisions"
    revisions.mkdir(parents=True, exist_ok=True)
    rounds = [int(path.name.split("_", 1)[1]) for path in revisions.glob("round_[0-9]*") if path.name.split("_", 1)[1].isdigit()]
    round_no = max(rounds, default=0) + 1
    final_dir = revisions / f"round_{round_no}"
    temp_dir = revisions / f".round_{round_no}.{uuid4().hex}.tmp"
    temp_dir.mkdir()
    manifest = {
        "chapter": chapter,
        "round": round_no,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "candidate_sha": actual_sha,
        "selected_issue_ids": [item["id"] for item in selected],
        "sample_problem_ids": list(dict.fromkeys(sample_problem_ids or [])),
        "revision_problem_ids": list(dict.fromkeys(revision_problem_ids or [])),
        "mode": normalized_mode,
        "status": "ready",
    }
    (temp_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (temp_dir / "issues.json").write_text(json.dumps(selected, ensure_ascii=False, indent=2), encoding="utf-8")
    comments = ["# 本轮作者意见", "", general_comment.strip() or "（无整体意见）", "", "## 逐条意见"]
    comments.extend(f"- {item['id']}: {item.get('author_comment') or '（无补充）'}" for item in selected)
    (temp_dir / "comments.md").write_text("\n".join(comments) + "\n", encoding="utf-8")
    (temp_dir / "candidate.md").write_text(candidate_text, encoding="utf-8")
    (temp_dir / "planning.md").write_text(planning.read_text(encoding="utf-8"), encoding="utf-8")
    temp_dir.rename(final_dir)
    return final_dir


def mark_package(package_dir: Path, *, status: str, output_sha: str = "", cost_yuan: float | None = None) -> None:
    manifest_path = package_dir / "manifest.json"
    manifest = _load_json(manifest_path)
    manifest["status"] = status
    manifest["finished_at"] = datetime.now().isoformat(timespec="seconds")
    if output_sha:
        manifest["output_sha"] = output_sha
    if cost_yuan is not None:
        manifest["cost_yuan"] = round(cost_yuan, 4)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
