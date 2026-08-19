from __future__ import annotations

from pathlib import Path


RULE = "PLAN_UNAUTHORIZED_MAJOR_EVENT"


def _ctx(planning: str | None) -> dict:
    ctx = {"book_dir": Path("unused"), "chapter_num": 1}
    if planning is not None:
        ctx["planning"] = planning
    return ctx


def _result(chapter: str, planning: str | None):
    from biyu.auditor.plan_authorization import PlanAuthorizationAuditor

    return PlanAuthorizationAuditor().run(chapter, _ctx(planning))


def test_unauthorized_death_blocks() -> None:
    result = _result(
        "角色甲拔刀杀死了角色乙。",
        "status: 已批\n角色甲与角色乙在北坊争执，随后各自离开。",
    )
    assert result.checker == RULE
    assert result.severity.value == "BLOCK"
    assert result.details
    assert result.details["chapter_evidence"] == "角色甲拔刀杀死了角色乙。"
    assert "未找到授权" in result.details["planning_check"]


def test_authorized_death_passes() -> None:
    result = _result(
        "角色甲拔刀杀死了角色乙。",
        "status: 已批\n本章结尾，角色甲在北坊杀死角色乙。",
    )
    assert result.severity.value == "PASS"


def test_no_keyword_only_match() -> None:
    result = _result(
        "角色甲与角色乙谈论死亡的意义。",
        "status: 已批\n角色甲与角色乙讨论生死观。",
    )
    assert result.severity.value != "BLOCK"


def test_negated_or_hypothetical_death_does_not_block() -> None:
    planning = "status: 已批\n角色甲警告角色乙不要冒险。"
    assert _result("角色甲没有杀死角色乙。", planning).severity.value != "BLOCK"
    assert _result("如果角色甲杀死角色乙，北坊必乱。", planning).severity.value != "BLOCK"


def test_no_evidence_no_block() -> None:
    assert _result("角色甲杀死了角色乙。", None).severity.value == "SKIP"
    assert _result("角色甲杀死了角色乙。", "status: 待确认\n方案").severity.value == "SKIP"


def test_two_state_registry_tripwire() -> None:
    import biyu.auditor as auditor

    class_path = auditor._CHECKER_REGISTRY.pop(RULE, None)
    try:
        disconnected = auditor.run_audit(
            "角色甲杀死了角色乙。",
            _ctx("status: 已批\n角色甲与角色乙谈判后各自离开。"),
        )
        assert not any(item.checker == RULE and item.severity.value == "BLOCK" for item in disconnected)
    finally:
        if class_path is not None:
            auditor._CHECKER_REGISTRY[RULE] = class_path

    restored_unauthorized = auditor.run_audit(
        "角色甲杀死了角色乙。",
        _ctx("status: 已批\n角色甲与角色乙谈判后各自离开。"),
    )
    restored_authorized = auditor.run_audit(
        "角色甲杀死了角色乙。",
        _ctx("status: 已批\n角色甲在北坊杀死角色乙。"),
    )
    assert any(item.checker == RULE and item.severity.value == "BLOCK" for item in restored_unauthorized)
    assert any(item.checker == RULE and item.severity.value == "PASS" for item in restored_authorized)


def test_signed_editor_text_installed_verbatim() -> None:
    text = Path("prompts/editor/system.md").read_text(encoding="utf-8")
    assert "最高优先级：先检查正文是否新增了规划件未授权的重大事件" in text
    assert "**重大事件授权**" in text
    assert "不是创作自由，必须按最高优先级报 high" in text
