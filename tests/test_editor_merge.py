"""合并算法测试 — Union-Find 聚类 + 投票 + 报告渲染。"""
import pytest

from biyu.editor.schema import (
    AgentIssue, AgentIssueList, AgentSuggestion, MergedIssue, MergeResult,
)
from biyu.editor.merge import (
    _jaccard_similarity,
    _can_cluster,
    merge_issues,
    render_audit_report,
)


def _make_issue(agent_id: str, num: int, type_: str, paragraph: int,
                keyword: str = "test", severity: str = "medium",
                retracted: bool = False) -> AgentIssue:
    return AgentIssue(
        id=f"{agent_id}-{num}",
        type=type_,
        paragraph=paragraph,
        severity=severity,
        keyword=keyword,
        description=f"{agent_id} 发现的 {type_} 问题",
        suggestion=AgentSuggestion(content=f"修复 {type_}", rationale="理由"),
        retracted=retracted,
    )


# ---------------------------------------------------------------------------
# Jaccard similarity
# ---------------------------------------------------------------------------

class TestJaccard:
    def test_identical_sets(self):
        assert _jaccard_similarity({"a", "b"}, {"a", "b"}) == 1.0

    def test_disjoint_sets(self):
        assert _jaccard_similarity({"a"}, {"b"}) == 0.0

    def test_partial_overlap(self):
        sim = _jaccard_similarity({"a", "b", "c"}, {"b", "c", "d"})
        assert 0.0 < sim < 1.0

    def test_empty_sets(self):
        assert _jaccard_similarity(set(), set()) == 1.0

    def test_one_empty(self):
        assert _jaccard_similarity({"a"}, set()) == 0.0


# ---------------------------------------------------------------------------
# Clustering
# ---------------------------------------------------------------------------

class TestClustering:
    def test_same_type_nearby_para_similar_kw_cluster(self):
        a = _make_issue("A", 1, "rhythm", 3, "段落堆砌")
        b = _make_issue("B", 1, "rhythm", 3, "段落堆砌")
        assert _can_cluster(a, b) is True

    def test_different_type_no_cluster(self):
        a = _make_issue("A", 1, "rhythm", 3)
        b = _make_issue("B", 1, "persona", 3)
        assert _can_cluster(a, b) is False

    def test_far_paragraph_no_cluster(self):
        a = _make_issue("A", 1, "rhythm", 3)
        b = _make_issue("B", 1, "rhythm", 10)
        assert _can_cluster(a, b) is False

    def test_adjacent_paragraph_cluster(self):
        a = _make_issue("A", 1, "rhythm", 3, "段落堆砌")
        b = _make_issue("B", 1, "rhythm", 4, "段落堆砌")
        assert _can_cluster(a, b) is True

    def test_dissimilar_keyword_no_cluster(self):
        a = _make_issue("A", 1, "rhythm", 3, "堆砌")
        b = _make_issue("B", 1, "rhythm", 3, "完全不同的关键词内容")
        assert _can_cluster(a, b) is False


# ---------------------------------------------------------------------------
# Voting
# ---------------------------------------------------------------------------

class TestVoting:
    def test_merge_3_votes_high(self):
        """3 个 agent 都报告同一问题 → confidence=high。"""
        lists = {
            "A": AgentIssueList(agent="A", phase=2, chapter=1, issues=[
                _make_issue("A", 1, "rhythm", 3, "段落堆砌"),
            ]),
            "B": AgentIssueList(agent="B", phase=2, chapter=1, issues=[
                _make_issue("B", 1, "rhythm", 3, "段落堆砌"),
            ]),
            "C": AgentIssueList(agent="C", phase=2, chapter=1, issues=[
                _make_issue("C", 1, "rhythm", 3, "段落堆砌"),
            ]),
        }
        result = merge_issues(lists)
        assert len(result.high_issues) == 1
        assert result.high_issues[0].confidence == "high"
        assert sorted(result.high_issues[0].voters) == ["A", "B", "C"]

    def test_merge_2_votes_med(self):
        """2 个 agent 报告 → confidence=medium。"""
        lists = {
            "A": AgentIssueList(agent="A", phase=2, chapter=1, issues=[
                _make_issue("A", 1, "rhythm", 3, "段落堆砌"),
            ]),
            "B": AgentIssueList(agent="B", phase=2, chapter=1, issues=[
                _make_issue("B", 1, "rhythm", 3, "段落堆砌"),
            ]),
            "C": AgentIssueList(agent="C", phase=2, chapter=1, issues=[]),
        }
        result = merge_issues(lists)
        assert len(result.med_issues) == 1
        assert result.med_issues[0].confidence == "medium"

    def test_merge_1_vote_low(self):
        """1 个 agent 独立报告 → confidence=low。"""
        lists = {
            "A": AgentIssueList(agent="A", phase=2, chapter=1, issues=[
                _make_issue("A", 1, "rhythm", 3, "段落堆砌"),
            ]),
            "B": AgentIssueList(agent="B", phase=2, chapter=1, issues=[]),
            "C": AgentIssueList(agent="C", phase=2, chapter=1, issues=[]),
        }
        result = merge_issues(lists)
        assert len(result.low_issues) == 1
        assert result.low_issues[0].confidence == "low"

    def test_retracted_issue_excluded(self):
        """Retracted issue 不参与投票。"""
        lists = {
            "A": AgentIssueList(agent="A", phase=2, chapter=1, issues=[
                _make_issue("A", 1, "rhythm", 3, "段落堆砌", retracted=True),
            ]),
            "B": AgentIssueList(agent="B", phase=2, chapter=1, issues=[]),
            "C": AgentIssueList(agent="C", phase=2, chapter=1, issues=[]),
        }
        result = merge_issues(lists)
        assert result.total_issues == 0

    def test_all_retracted(self):
        """全部 retracted → 空结果。"""
        lists = {
            "A": AgentIssueList(agent="A", phase=2, chapter=1, issues=[
                _make_issue("A", 1, "rhythm", 3, "段落堆砌", retracted=True),
            ]),
            "B": AgentIssueList(agent="B", phase=2, chapter=1, issues=[
                _make_issue("B", 1, "persona", 5, "语气", retracted=True),
            ]),
            "C": AgentIssueList(agent="C", phase=2, chapter=1, issues=[]),
        }
        result = merge_issues(lists)
        assert result.total_issues == 0

    def test_multiple_clusters(self):
        """不同 type 的 issue 不聚类。"""
        lists = {
            "A": AgentIssueList(agent="A", phase=2, chapter=1, issues=[
                _make_issue("A", 1, "rhythm", 3, "段落"),
            ]),
            "B": AgentIssueList(agent="B", phase=2, chapter=1, issues=[
                _make_issue("B", 1, "persona", 5, "语气"),
            ]),
            "C": AgentIssueList(agent="C", phase=2, chapter=1, issues=[]),
        }
        result = merge_issues(lists)
        assert result.total_issues == 2
        assert len(result.low_issues) == 2  # each has 1 vote


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------

class TestRenderAuditReport:
    def test_empty_report(self):
        result = MergeResult()
        report = render_audit_report(1, result)
        assert "未发现问题" in report
        assert "CH" in report or "第 1 章" in report

    def test_report_with_issues(self):
        sug = AgentSuggestion(content="修", rationale="理")
        ai = AgentIssue(id="A-1", type="rhythm", paragraph=3, severity="high",
                        keyword="test", description="d", suggestion=sug)
        mi = MergedIssue(type="rhythm", paragraph=3, confidence="high",
                         voters=["A", "B", "C"], agent_issues=[ai],
                         merged_description="d", merged_suggestion="修")
        result = MergeResult(high_issues=[mi], total_cost=0.01)
        report = render_audit_report(5, result)
        assert "高严重度" in report
        assert "rhythm" in report
        assert "A, B, C" in report

    def test_fallback_report(self):
        result = MergeResult(fallback_used=True)
        report = render_audit_report(1, result)
        assert "回退" in report or "fallback" in report.lower()

    def test_report_with_cost(self):
        mi = MergedIssue(type="rhythm", paragraph=1, confidence="low",
                         voters=["A"], agent_issues=[],
                         merged_description="d", merged_suggestion="s")
        result = MergeResult(low_issues=[mi], total_cost=0.02)
        report = render_audit_report(1, result)
        assert "¥0.0200" in report
