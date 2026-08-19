"""Issue 合并算法 — Union-Find 聚类 + 投票 + 报告渲染。

纯算法，无 LLM 依赖。
"""
from __future__ import annotations

from .schema import AgentIssue, AgentIssueList, MergedIssue, MergeResult


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _jaccard_similarity(set_a: set[str], set_b: set[str]) -> float:
    """计算两个集合的 Jaccard 相似度。"""
    if not set_a and not set_b:
        return 1.0
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def _keyword_to_set(keyword: str) -> set[str]:
    """将 keyword 字符串转为字符集合（用于 Jaccard 计算）。"""
    # 简单策略：每个非空白字符作为一个 token
    return set(keyword.replace(" ", "")) if keyword else set()


def _can_cluster(a: AgentIssue, b: AgentIssue) -> bool:
    """判断两个 issue 是否可以聚类。

    条件：paragraph 差 ≤ 1 + type 相同 + keyword jaccard ≥ 0.5
    """
    if a.type != b.type:
        return False
    if abs(a.paragraph - b.paragraph) > 1:
        return False
    kw_a = _keyword_to_set(a.keyword)
    kw_b = _keyword_to_set(b.keyword)
    return _jaccard_similarity(kw_a, kw_b) >= 0.5


# ---------------------------------------------------------------------------
# Union-Find
# ---------------------------------------------------------------------------

class _UnionFind:
    """简易 Union-Find，基于 issue 索引。"""

    def __init__(self, n: int) -> None:
        self.parent = list(range(n))
        self.rank = [0] * n

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]  # path compression
            x = self.parent[x]
        return x

    def union(self, x: int, y: int) -> None:
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return
        if self.rank[rx] < self.rank[ry]:
            rx, ry = ry, rx
        self.parent[ry] = rx
        if self.rank[rx] == self.rank[ry]:
            self.rank[rx] += 1


# ---------------------------------------------------------------------------
# 核心合并
# ---------------------------------------------------------------------------

def merge_issues(issue_lists: dict[str, AgentIssueList]) -> MergeResult:
    """合并多个 agent 的 issue 列表。

    Args:
        issue_lists: {"A": AgentIssueList, "B": AgentIssueList, "C": AgentIssueList}

    Returns:
        MergeResult with high/med/low issues
    """
    # 收集所有非 retracted 的 issue
    all_issues: list[AgentIssue] = []
    for agent_id, issue_list in issue_lists.items():
        for issue in issue_list.issues:
            if not issue.retracted:
                all_issues.append(issue)

    if not all_issues:
        return MergeResult()

    # Union-Find 聚类
    n = len(all_issues)
    uf = _UnionFind(n)

    for i in range(n):
        for j in range(i + 1, n):
            if _can_cluster(all_issues[i], all_issues[j]):
                uf.union(i, j)

    # 收集聚类
    clusters: dict[int, list[int]] = {}
    for i in range(n):
        root = uf.find(i)
        clusters.setdefault(root, []).append(i)

    # 每个聚类投票 → MergedIssue
    high_issues: list[MergedIssue] = []
    med_issues: list[MergedIssue] = []
    low_issues: list[MergedIssue] = []

    for root, members in clusters.items():
        cluster_issues = [all_issues[i] for i in members]
        voters = sorted({all_issues[i].id.split("-")[0] for i in members})
        vote_count = len(voters)

        # 聚类中心段落（取中位数）
        paragraphs = [issue.paragraph for issue in cluster_issues]
        paragraphs.sort()
        center_para = paragraphs[len(paragraphs) // 2]

        # 合并描述和建议
        descriptions = [f"[{issue.id}] {issue.description}" for issue in cluster_issues]
        merged_desc = "\n".join(descriptions)

        suggestions = [
            f"[{issue.id}] {issue.suggestion.content}"
            for issue in cluster_issues
            if issue.suggestion.content
        ]
        merged_sug = "\n".join(suggestions) if suggestions else "manual_review"

        # 投票 → confidence
        if vote_count >= 3:
            confidence = "high"
        elif vote_count == 2:
            confidence = "medium"
        else:
            confidence = "low"

        merged = MergedIssue(
            type=cluster_issues[0].type,
            paragraph=center_para,
            confidence=confidence,
            voters=voters,
            agent_issues=cluster_issues,
            merged_description=merged_desc,
            merged_suggestion=merged_sug,
        )

        if confidence == "high":
            high_issues.append(merged)
        elif confidence == "medium":
            med_issues.append(merged)
        else:
            low_issues.append(merged)

    return MergeResult(
        high_issues=high_issues,
        med_issues=med_issues,
        low_issues=low_issues,
    )


# ---------------------------------------------------------------------------
# 报告渲染
# ---------------------------------------------------------------------------

def render_audit_report(chapter_num: int, merge_result: MergeResult) -> str:
    """将 MergeResult 渲染为 markdown 字符串，用于审计报告 section 4。"""
    lines = [
        f"### Editor 多 Agent 审稿（第 {chapter_num} 章）",
        "",
    ]

    if merge_result.fallback_used:
        lines.append("> ⚠️ 因成本超限回退到 single mode")
        lines.append("")

    total = merge_result.total_issues
    if total == 0:
        lines.append("✅ 未发现问题。")
        lines.append("")
        return "\n".join(lines)

    lines.append(f"共 {total} 个合并 issue（高 {len(merge_result.high_issues)} / 中 {len(merge_result.med_issues)} / 低 {len(merge_result.low_issues)}）")
    lines.append("")

    for level, issues, icon in [
        ("高严重度", merge_result.high_issues, "❌"),
        ("中严重度", merge_result.med_issues, "⚠️"),
        ("低严重度", merge_result.low_issues, "ℹ️"),
    ]:
        if not issues:
            continue
        lines.append(f"#### {icon} {level}")
        lines.append("")
        for issue in issues:
            voters_str = ", ".join(issue.voters)
            lines.append(f"**{issue.type}** (¶{issue.paragraph}, 票数: {voters_str})")
            lines.append(f"- {issue.merged_description}")
            if issue.merged_suggestion:
                lines.append(f"- 建议: {issue.merged_suggestion}")
            lines.append("")

    if merge_result.total_cost > 0:
        lines.append(f"> 总成本: ¥{merge_result.total_cost:.4f}")

    return "\n".join(lines)
