"""Schema 校验测试 — type 枚举 / AgentIssue 验证 / 序列化。"""
import json
import pytest

from biyu.editor.schema import (
    AgentIssue,
    AgentIssueList,
    AgentSuggestion,
    MergedIssue,
    MergeResult,
    EDITOR_A_TYPES,
    EDITOR_B_TYPES,
    EDITOR_C_TYPES,
    AGENT_VALID_TYPES,
    AGENT_TOOL_MAP,
)


# ---------------------------------------------------------------------------
# AgentSuggestion
# ---------------------------------------------------------------------------

class TestAgentSuggestion:
    def test_to_dict_and_from_dict(self):
        sug = AgentSuggestion(content="删掉这段", rationale="节奏拖沓")
        d = sug.to_dict()
        assert d["content"] == "删掉这段"
        sug2 = AgentSuggestion.from_dict(d)
        assert sug2.content == "删掉这段"
        assert sug2.rationale == "节奏拖沓"


# ---------------------------------------------------------------------------
# AgentIssue validation
# ---------------------------------------------------------------------------

class TestAgentIssueValidation:
    def _make_issue(self, **overrides) -> AgentIssue:
        defaults = dict(
            id="A-1", type="rhythm", paragraph=3,
            severity="medium", keyword="段落堆砌",
            description="节奏问题",
            suggestion=AgentSuggestion(content="分段", rationale="太长"),
        )
        defaults.update(overrides)
        return AgentIssue(**defaults)

    def test_valid_agent_a_issue(self):
        issue = self._make_issue(type="rhythm")
        assert issue.validate("A") == []

    def test_valid_agent_b_issue(self):
        issue = self._make_issue(id="B-1", type="persona")
        assert issue.validate("B") == []

    def test_valid_agent_c_issue(self):
        issue = self._make_issue(id="C-1", type="visual_clash")
        assert issue.validate("C") == []

    def test_schema_type_enforcement_agent_a_rejects_b_type(self):
        """Agent-A issue 越界使用 B 的 type → 被拒绝。"""
        issue = self._make_issue(type="persona")  # persona is B's type
        errors = issue.validate("A")
        assert len(errors) > 0
        assert "invalid type" in errors[0]

    def test_schema_type_enforcement_agent_b_rejects_c_type(self):
        issue = self._make_issue(id="B-1", type="facts")
        errors = issue.validate("B")
        assert len(errors) > 0

    def test_schema_type_enforcement_agent_c_rejects_a_type(self):
        issue = self._make_issue(id="C-1", type="rhythm")
        errors = issue.validate("C")
        assert len(errors) > 0

    def test_invalid_severity(self):
        issue = self._make_issue(severity="critical")
        errors = issue.validate("A")
        assert any("severity" in e for e in errors)

    def test_invalid_paragraph(self):
        issue = self._make_issue(paragraph=-1)
        errors = issue.validate("A")
        assert any("paragraph" in e for e in errors)

    def test_retracted_issue(self):
        issue = self._make_issue(retracted=True, retracted_reason="站不住脚")
        assert issue.retracted is True
        d = issue.to_dict()
        assert d["retracted"] is True
        assert d["retracted_reason"] == "站不住脚"


# ---------------------------------------------------------------------------
# Serialization roundtrip
# ---------------------------------------------------------------------------

class TestSerialization:
    def test_agent_issue_roundtrip(self):
        sug = AgentSuggestion(content="分段", rationale="太长")
        issue = AgentIssue(
            id="A-1", type="rhythm", paragraph=3,
            severity="high", keyword="堆砌",
            description="节奏问题", suggestion=sug,
        )
        d = issue.to_dict()
        issue2 = AgentIssue.from_dict(d)
        assert issue2.id == "A-1"
        assert issue2.type == "rhythm"
        assert issue2.suggestion.content == "分段"

    def test_agent_issue_list_json(self):
        sug = AgentSuggestion(content="修", rationale="理")
        issue = AgentIssue(
            id="A-1", type="hook", paragraph=1,
            severity="low", keyword="开头",
            description="钩子不够", suggestion=sug,
        )
        il = AgentIssueList(agent="A", phase=1, chapter=5, issues=[issue])
        json_str = il.to_json()
        data = json.loads(json_str)
        assert data["agent"] == "A"
        assert len(data["issues"]) == 1

        il2 = AgentIssueList.from_json(json_str)
        assert il2.agent == "A"
        assert il2.chapter == 5
        assert len(il2.issues) == 1
        assert il2.issues[0].type == "hook"


# ---------------------------------------------------------------------------
# Type enums
# ---------------------------------------------------------------------------

class TestTypeEnums:
    def test_editor_a_types(self):
        assert "rhythm" in EDITOR_A_TYPES
        assert "persona" not in EDITOR_A_TYPES

    def test_editor_b_types(self):
        assert "persona" in EDITOR_B_TYPES
        assert "visual_clash" not in EDITOR_B_TYPES

    def test_editor_c_types(self):
        assert "visual_clash" in EDITOR_C_TYPES
        assert "rhythm" not in EDITOR_C_TYPES

    def test_no_type_overlap(self):
        """三个 agent 的 type 集合不应有交集。"""
        assert EDITOR_A_TYPES & EDITOR_B_TYPES == set()
        assert EDITOR_A_TYPES & EDITOR_C_TYPES == set()
        assert EDITOR_B_TYPES & EDITOR_C_TYPES == set()

    def test_agent_valid_types_keys(self):
        assert set(AGENT_VALID_TYPES.keys()) == {"A", "B", "C"}

    def test_agent_tool_map_keys(self):
        assert set(AGENT_TOOL_MAP.keys()) == {"A", "B", "C"}


# ---------------------------------------------------------------------------
# MergeResult
# ---------------------------------------------------------------------------

class TestMergeResult:
    def test_empty_merge_result(self):
        mr = MergeResult()
        assert mr.total_issues == 0
        assert mr.all_issues == []

    def test_merge_result_with_issues(self):
        sug = AgentSuggestion(content="修", rationale="理")
        ai = AgentIssue(id="A-1", type="rhythm", paragraph=1, severity="high",
                        keyword="x", description="d", suggestion=sug)
        mi = MergedIssue(type="rhythm", paragraph=1, confidence="high",
                         voters=["A", "B", "C"], agent_issues=[ai],
                         merged_description="d", merged_suggestion="修")
        mr = MergeResult(high_issues=[mi], total_cost=0.01)
        assert mr.total_issues == 1
        assert mr.all_issues == [mi]
        d = mr.to_dict()
        assert d["total_issues"] == 1
