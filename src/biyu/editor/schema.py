"""Multi-agent Editor issue 数据结构 — 独立于旧 EditorIssue/EditorResult。

旧 parser.py 的 EditorIssue / EditorResult 完全不动，single mode 继续用。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Type 枚举 — 每个 agent 限定集合
# ---------------------------------------------------------------------------

EDITOR_A_TYPES = frozenset({
    "rhythm",        # 节奏/呼吸感
    "hook",          # 开头/结尾钩子
    "ai_smell",      # AI 味/元叙事词
    "meta_vocab",    # 说明书式词汇
    "dialogue_ratio",  # 对话/叙述比例
})

EDITOR_B_TYPES = frozenset({
    "persona",            # 角色言行与角色卡不符
    "symbol_overuse",     # 符号/口头禅过度
    "dialogue_id",        # 对话角色辨识度
    "personality_anchor", # 性格锚点缺失
    "tier_rigor",         # 战力等级严谨性
})

EDITOR_C_TYPES = frozenset({
    "facts",             # 设定事实冲突
    "forbidden",         # 触碰禁忌设定
    "naming",            # 命名不一致
    "hooks_audit",       # 伏笔/回收审计
    "appearance_audit",  # 外貌描写一致性
    "visual_clash",      # 视觉符号撞色
    "cross_chapter",     # 跨章 continuity
})

AGENT_VALID_TYPES = {
    "A": EDITOR_A_TYPES,
    "B": EDITOR_B_TYPES,
    "C": EDITOR_C_TYPES,
}

# ---------------------------------------------------------------------------
# Agent → 工具权限映射
# ---------------------------------------------------------------------------

AGENT_TOOL_MAP: dict[str, list[str]] = {
    "A": ["look_up_history"],
    "B": ["look_up_character", "look_up_history"],
    "C": ["look_up_character", "look_up_setting", "look_up_history", "look_up_visual"],
}


# ---------------------------------------------------------------------------
# 数据类
# ---------------------------------------------------------------------------

@dataclass
class AgentSuggestion:
    """建议子结构。"""
    content: str          # 建议内容
    rationale: str        # 为什么这样建议

    def to_dict(self) -> dict[str, Any]:
        return {"content": self.content, "rationale": self.rationale}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AgentSuggestion:
        return cls(
            content=str(d.get("content", "")),
            rationale=str(d.get("rationale", "")),
        )


@dataclass
class AgentIssue:
    """单个 agent 产出的 issue。"""
    id: str                     # agent 内部编号，如 "A-1"
    type: str                   # issue type，必须在对应 agent 的 TYPE 集合内
    paragraph: int              # 段落号（从 1 开始）
    severity: str               # high / medium / low
    keyword: str                # 关键词/引用片段
    description: str            # 问题描述
    suggestion: AgentSuggestion # 建议
    retracted: bool = False     # Phase 2 是否撤回
    retracted_reason: str = ""  # 撤回原因

    def validate(self, agent_id: str) -> list[str]:
        """校验 issue 是否合法，返回错误列表（空=合法）。"""
        errors: list[str] = []
        valid_types = AGENT_VALID_TYPES.get(agent_id, frozenset())
        if self.type not in valid_types:
            errors.append(
                f"Agent-{agent_id} issue '{self.id}' has invalid type '{self.type}', "
                f"allowed: {sorted(valid_types)}"
            )
        if self.severity not in ("high", "medium", "low"):
            errors.append(f"Invalid severity '{self.severity}' on issue '{self.id}'")
        if self.paragraph < 0:
            errors.append(f"Invalid paragraph {self.paragraph} on issue '{self.id}'")
        return errors

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "type": self.type,
            "paragraph": self.paragraph,
            "severity": self.severity,
            "keyword": self.keyword,
            "description": self.description,
            "suggestion": self.suggestion.to_dict(),
            "retracted": self.retracted,
        }
        if self.retracted_reason:
            d["retracted_reason"] = self.retracted_reason
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AgentIssue:
        sug_data = d.get("suggestion", {})
        suggestion = AgentSuggestion.from_dict(sug_data) if isinstance(sug_data, dict) else AgentSuggestion("", "")
        return cls(
            id=str(d.get("id", "")),
            type=str(d.get("type", "")),
            paragraph=int(d.get("paragraph", 0)),
            severity=str(d.get("severity", "medium")),
            keyword=str(d.get("keyword", "")),
            description=str(d.get("description", "")),
            suggestion=suggestion,
            retracted=bool(d.get("retracted", False)),
            retracted_reason=str(d.get("retracted_reason", "")),
        )


@dataclass
class AgentIssueList:
    """一个 agent 一轮产出的 issue 列表。"""
    agent: str                      # "A" / "B" / "C"
    phase: int                      # 1 或 2
    chapter: int                    # 章节号
    issues: list[AgentIssue] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "phase": self.phase,
            "chapter": self.chapter,
            "issues": [i.to_dict() for i in self.issues],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AgentIssueList:
        issues = [AgentIssue.from_dict(i) for i in d.get("issues", [])]
        return cls(
            agent=str(d.get("agent", "")),
            phase=int(d.get("phase", 1)),
            chapter=int(d.get("chapter", 0)),
            issues=issues,
        )

    @classmethod
    def from_json(cls, json_str: str) -> AgentIssueList:
        return cls.from_dict(json.loads(json_str))


@dataclass
class MergedIssue:
    """合并后的 issue（多 agent 投票结果）。"""
    type: str                        # issue type
    paragraph: int                   # 聚类中心段落
    confidence: str                  # high(3票) / medium(2票) / low(1票)
    voters: list[str]                # ["A", "B", "C"] 投票 agent 列表
    agent_issues: list[AgentIssue]   # 原始 agent issues
    merged_description: str          # 合并后的描述
    merged_suggestion: str           # 合并后的建议

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "paragraph": self.paragraph,
            "confidence": self.confidence,
            "voters": self.voters,
            "merged_description": self.merged_description,
            "merged_suggestion": self.merged_suggestion,
            "agent_issues": [i.to_dict() for i in self.agent_issues],
        }


@dataclass
class MergeResult:
    """整个 merge 阶段的输出。"""
    high_issues: list[MergedIssue] = field(default_factory=list)
    med_issues: list[MergedIssue] = field(default_factory=list)
    low_issues: list[MergedIssue] = field(default_factory=list)
    total_cost: float = 0.0
    fallback_used: bool = False

    @property
    def all_issues(self) -> list[MergedIssue]:
        return self.high_issues + self.med_issues + self.low_issues

    @property
    def total_issues(self) -> int:
        return len(self.high_issues) + len(self.med_issues) + len(self.low_issues)

    def to_dict(self) -> dict[str, Any]:
        return {
            "high_issues": [i.to_dict() for i in self.high_issues],
            "med_issues": [i.to_dict() for i in self.med_issues],
            "low_issues": [i.to_dict() for i in self.low_issues],
            "total_cost": self.total_cost,
            "fallback_used": self.fallback_used,
            "total_issues": self.total_issues,
        }
