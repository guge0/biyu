from __future__ import annotations

import hashlib
import json
from pathlib import Path

from fastapi.testclient import TestClient


def _file(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _report(*, issues: list[dict] | None = None) -> str:
    return json.dumps(
        {"chapter": 1, "issues": issues or [], "results": []},
        ensure_ascii=False,
    )


def _checklist(*, candidate_sha: str | None, items: list[dict]) -> str:
    payload = {
        "chapter": 1,
        "version": "fixture",
        "engine_version": "f4",
        "items": items,
        "summary": {"total": len(items)},
    }
    if candidate_sha is not None:
        payload["candidate_sha"] = candidate_sha
    return json.dumps(payload, ensure_ascii=False)


def test_snapshot_exposes_manuscript_and_honest_check_states(tmp_path: Path, monkeypatch) -> None:
    import biyu.ui.workbench as wb

    monkeypatch.setattr(wb, "_checklist_feature_enabled", lambda: False)

    book = tmp_path / "Book"
    missing = wb.chapter_snapshot(book, 1)
    assert missing["manuscript_state"] == "missing"
    assert missing["check_state"] == "unchecked"
    assert missing["check_sources"] == {
        "editor": "unchecked",
        "checklist": "feature_off",
    }

    _file(book / "chapters/ch1.md", "正式正文")
    official = wb.chapter_snapshot(book, 1)
    assert official["manuscript_state"] == "official"
    assert official["check_state"] == "unchecked"

    _file(book / "chapters/_pending/ch1.md", "候选正文")
    _file(book / "audit_reports/ch1.json", _report())
    checked_clean = wb.chapter_snapshot(book, 1)
    assert checked_clean["manuscript_state"] == "candidate"
    assert checked_clean["check_state"] == "checked_clean"
    assert checked_clean["check_sources"]["editor"] == "checked_clean"

    _file(
        book / "audit_reports/ch1.json",
        _report(
            issues=[
                {
                    "id": "ch1-001",
                    "status": "open",
                    "severity": "medium",
                    "description": "前后不一致",
                    "quoted_text": "原句",
                }
            ]
        ),
    )
    checked_with_issues = wb.chapter_snapshot(book, 1)
    assert checked_with_issues["check_state"] == "checked_with_issues"
    assert checked_with_issues["check_sources"]["editor"] == "checked_with_issues"


def test_ignored_issue_stays_visible_and_can_be_unignored(tmp_path: Path, monkeypatch) -> None:
    import biyu.ui.workbench as wb
    from biyu.ui.app import app

    book = tmp_path / "Book"
    pending_text = "候选正文"
    _file(book / "book.json", "{}")
    _file(book / "chapters/_pending/ch1.md", pending_text)
    _file(
        book / "audit_reports/ch1.json",
        json.dumps(
            {
                "chapter": 1,
                "issues": [
                    {
                        "id": "ch1-001",
                        "status": "open",
                        "severity": "medium",
                        "description": "问题",
                        "quoted_text": "候选",
                    }
                ],
                "workbench_annotations": {
                    "ch1-001": {"ignored": True, "selected": False}
                },
            },
            ensure_ascii=False,
        ),
    )
    monkeypatch.setattr(wb, "get_data_root", lambda: tmp_path)
    client = TestClient(app)

    before = client.get("/api/workbench/books/Book/chapters/1").json()
    assert len(before["issue_cards"]) == 1
    assert before["issue_cards"][0]["ignored"] is True
    assert before["unhandled_issue_count"] == 0

    restored = client.delete(
        "/api/workbench/books/Book/chapters/1/issues/ch1-001/ignore",
        params={"candidate_sha": _sha(pending_text)},
    )

    assert restored.status_code == 200
    card = restored.json()["issue_cards"][0]
    assert card["ignored"] is False
    assert card["selected"] is False
    assert restored.json()["unhandled_issue_count"] == 1


def test_saving_candidate_keeps_editor_feedback_bound_to_old_version(
    tmp_path: Path, monkeypatch
) -> None:
    import biyu.ui.workbench as wb
    from biyu.ui.app import app

    book = tmp_path / "Book"
    _file(book / "book.json", "{}")
    _file(book / "chapters/_pending/ch1.md", "旧候选正文")
    _file(
        book / "audit_reports/ch1.json",
        _report(
            issues=[
                {
                    "id": "ch1-001",
                    "status": "open",
                    "severity": "medium",
                    "description": "问题",
                    "quoted_text": "旧候选",
                }
            ]
        ),
    )
    monkeypatch.setattr(wb, "get_data_root", lambda: tmp_path)
    client = TestClient(app)
    before = client.get("/api/workbench/books/Book/chapters/1").json()

    saved = client.put(
        "/api/workbench/books/Book/chapters/1/chapter",
        json={
            "content": "新候选正文",
            "base_sha": before["chapter_sha"],
            "target": "pending",
        },
    )

    assert saved.status_code == 200
    assert saved.json()["review_stale"] is True
    sidecar = json.loads(
        (book / "logs/ch1/workbench_review_state.json").read_text(encoding="utf-8")
    )
    assert sidecar["candidate_sha"] == _sha("新候选正文")
    assert sidecar["editor_base_sha"] == _sha("旧候选正文")
    reloaded = client.get("/api/workbench/books/Book/chapters/1").json()
    assert reloaded["review_stale"] is True

    _file(book / "chapters/_pending/ch1.md", "旧候选正文")
    switched_back = client.get("/api/workbench/books/Book/chapters/1").json()
    assert switched_back["review_stale"] is False

    _file(book / "chapters/_pending/ch1.md", "另一份候选正文")
    switched_elsewhere = client.get("/api/workbench/books/Book/chapters/1").json()
    assert switched_elsewhere["review_stale"] is True


def test_corrupt_review_sidecar_degrades_loudly_to_unchecked(
    tmp_path: Path, monkeypatch
) -> None:
    import biyu.ui.workbench as wb

    book = tmp_path / "Book"
    _file(book / "chapters/_pending/ch1.md", "候选正文")
    _file(book / "audit_reports/ch1.json", _report())
    _file(book / "logs/ch1/workbench_review_state.json", "{broken")
    monkeypatch.setattr(wb, "_checklist_feature_enabled", lambda: False)

    snapshot = wb.chapter_snapshot(book, 1)

    assert snapshot["check_state"] == "unchecked"
    assert snapshot["review_state_error"]


def test_unhandled_count_excludes_selected_and_ignored(tmp_path: Path, monkeypatch) -> None:
    import biyu.ui.workbench as wb

    book = tmp_path / "Book"
    _file(book / "chapters/_pending/ch1.md", "候选正文")
    report = json.loads(
        _report(
            issues=[
                {"id": "open", "status": "open", "description": "未处理"},
                {"id": "selected", "status": "open", "description": "已勾选"},
                {"id": "ignored", "status": "open", "description": "已忽略"},
            ]
        )
    )
    report["workbench_annotations"] = {
        "selected": {"selected": True},
        "ignored": {"ignored": True},
    }
    _file(book / "audit_reports/ch1.json", json.dumps(report, ensure_ascii=False))
    monkeypatch.setattr(wb, "_checklist_feature_enabled", lambda: False)

    snapshot = wb.chapter_snapshot(book, 1)

    assert len(snapshot["issue_cards"]) == 3
    assert snapshot["unhandled_issue_count"] == 1


def test_checklist_exact_sha_only_maps_unmet_to_warn(tmp_path: Path, monkeypatch) -> None:
    import biyu.ui.workbench as wb

    book = tmp_path / "Book"
    chapter_text = "候选正文里有可精确定位的原句。"
    _file(book / "chapters/_pending/ch1.md", chapter_text)
    _file(book / "audit_reports/ch1.json", _report())
    _file(
        book / "logs/ch1/candidates/fixture_checklist.json",
        _checklist(
            candidate_sha=_sha(chapter_text),
            items=[
                {
                    "category": "must_happen",
                    "index": 0,
                    "text": "关键事件必须发生",
                    "verdict": "unmet",
                    "quotes": ["可精确定位的原句"],
                    "reason": "正文没有兑现关键事件",
                },
                {
                    "category": "must_not_happen",
                    "index": 1,
                    "text": "禁项不得出现",
                    "verdict": "met",
                    "quotes": [],
                    "reason": "禁项没有出现",
                },
                {
                    "category": "ending_state",
                    "index": 2,
                    "text": "结尾状态",
                    "verdict": "unclear",
                    "quotes": [],
                    "reason": "必检项不可核对",
                },
                {
                    "category": "info_layers",
                    "index": 3,
                    "text": "信息层级",
                    "verdict": "invalid",
                    "quotes": ["对不上正文的引证"],
                    "reason": "引证无效",
                },
            ],
        ),
    )
    monkeypatch.setattr(wb, "_checklist_feature_enabled", lambda: True)

    snapshot = wb.chapter_snapshot(book, 1)

    checklist_cards = [
        card for card in snapshot["issue_cards"] if card["source"] == "checklist"
    ]
    assert snapshot["check_sources"]["checklist"] == "checked_with_issues"
    assert snapshot["check_state"] == "checked_with_issues"
    assert snapshot["check_source_meta"]["checklist"] == {
        "total": 4,
        "unresolved": 2,
    }
    assert len(checklist_cards) == 1
    assert checklist_cards[0]["severity"] == "WARN"
    assert checklist_cards[0]["quote"] == "可精确定位的原句"
    assert checklist_cards[0]["quotes"] == ["可精确定位的原句"]
    assert all(card["severity"] != "BLOCK" for card in checklist_cards)


def test_checklist_met_must_not_happen_is_checked_clean(tmp_path: Path, monkeypatch) -> None:
    import biyu.ui.workbench as wb

    book = tmp_path / "Book"
    chapter_text = "候选正文"
    _file(book / "chapters/_pending/ch1.md", chapter_text)
    _file(
        book / "logs/ch1/candidates/fixture_checklist.json",
        _checklist(
            candidate_sha=_sha(chapter_text),
            items=[
                {
                    "category": "must_not_happen",
                    "index": 0,
                    "text": "禁项不得出现",
                    "verdict": "met",
                    "quotes": [],
                    "reason": "禁项没有出现",
                }
            ],
        ),
    )
    monkeypatch.setattr(wb, "_checklist_feature_enabled", lambda: True)

    snapshot = wb.chapter_snapshot(book, 1)

    assert snapshot["check_sources"]["checklist"] == "checked_clean"
    assert snapshot["check_state"] == "checked_clean"
    assert snapshot["issue_cards"] == []


def test_checklist_refuses_mismatched_and_unversioned_results(
    tmp_path: Path, monkeypatch
) -> None:
    import biyu.ui.workbench as wb

    monkeypatch.setattr(wb, "_checklist_feature_enabled", lambda: True)
    item = {
        "category": "must_happen",
        "index": 0,
        "text": "必须发生",
        "verdict": "unmet",
        "quotes": ["原句"],
        "reason": "未发生",
    }

    mismatched = tmp_path / "Mismatch"
    _file(mismatched / "chapters/_pending/ch1.md", "当前正文")
    _file(
        mismatched / "logs/ch1/candidates/other_checklist.json",
        _checklist(candidate_sha=_sha("另一版正文"), items=[item]),
    )
    mismatch_snapshot = wb.chapter_snapshot(mismatched, 1)
    assert mismatch_snapshot["check_sources"]["checklist"] == "version_mismatch"
    assert mismatch_snapshot["check_state"] == "unchecked"
    assert mismatch_snapshot["issue_cards"] == []

    unversioned = tmp_path / "Unversioned"
    _file(unversioned / "chapters/_pending/ch1.md", "当前正文")
    _file(
        unversioned / "logs/ch1/candidates/legacy_checklist.json",
        _checklist(candidate_sha=None, items=[item]),
    )
    unversioned_snapshot = wb.chapter_snapshot(unversioned, 1)
    assert unversioned_snapshot["check_sources"]["checklist"] == "unversioned"
    assert unversioned_snapshot["check_state"] == "unchecked"
    assert unversioned_snapshot["issue_cards"] == []
