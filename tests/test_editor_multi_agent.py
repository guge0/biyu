"""多 Agent 编排测试 — Phase 1/2 隔离 / 无 tools / 成本回退 / single fallback。"""
from __future__ import annotations

import asyncio
import json
import pytest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from biyu.editor.schema import AgentIssue, AgentIssueList, AgentSuggestion
from biyu.editor.multi_agent import (
    load_editor_config,
    clear_config_cache,
    review_chapter_multi_agent,
    _parse_agent_response,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_response(text: str, cost: float = 0.001, has_tool_calls: bool = False,
                    submit_review_issues: Any = None):
    """构造 mock LLMResponse。

    If submit_review_issues is provided, the response will contain a submit_review
    tool call with those issues. Otherwise returns plain text.
    """
    resp = MagicMock()
    resp.text = text
    resp.cost = cost
    resp.raw = None
    if submit_review_issues is not None:
        resp.raw = {
            "choices": [{
                "message": {
                    "content": text,
                    "tool_calls": [{
                        "id": "call_submit",
                        "type": "function",
                        "function": {
                            "name": "submit_review",
                            "arguments": json.dumps({"issues": submit_review_issues}),
                        },
                    }],
                }
            }]
        }
    elif has_tool_calls:
        resp.raw = {
            "choices": [{
                "message": {
                    "tool_calls": [{
                        "function": {
                            "name": "look_up_history",
                            "arguments": json.dumps({"chapter_or_keyword": "test"}),
                        }
                    }]
                }
            }]
        }
    return resp


def _make_agent_json(agent_id: str, issues: list[dict]) -> str:
    """构造 agent JSON 响应。"""
    return json.dumps({
        "issues": [
            {
                "id": f"{agent_id}-{i+1}",
                "type": issue["type"],
                "paragraph": issue.get("paragraph", i+1),
                "severity": issue.get("severity", "medium"),
                "keyword": issue.get("keyword", "test"),
                "description": issue.get("description", "test desc"),
                "suggestion": {"content": "fix", "rationale": "reason"},
            }
            for i, issue in enumerate(issues)
        ]
    }, ensure_ascii=False)


def _mock_config():
    return {
        "mode": "multi_agent",
        "fallback_on_budget_exceed": False,
        "fallback_threshold_yuan_per_chapter": 999,
        "agents": {"max_tool_calls_per_agent_phase1": 0, "max_issues_per_agent": 8},
    }


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

class TestConfig:
    def setup_method(self):
        clear_config_cache()

    def test_load_config_caching(self):
        """配置应被缓存。"""
        config = load_editor_config()
        config2 = load_editor_config()
        assert config is config2

    def test_clear_cache(self):
        load_editor_config()
        clear_config_cache()
        from biyu.editor import multi_agent
        assert multi_agent._EDITOR_CONFIG_CACHE is None


# ---------------------------------------------------------------------------
# JSON parsing
# ---------------------------------------------------------------------------

class TestParseAgentResponse:
    def test_valid_json(self):
        text = _make_agent_json("A", [{"type": "rhythm"}])
        result = _parse_agent_response(text, "A", 1, 5, 8)
        assert result.agent == "A"
        assert len(result.issues) == 1
        assert result.issues[0].type == "rhythm"

    def test_invalid_type_rejected(self):
        """越界 type 应被拒绝。"""
        text = _make_agent_json("A", [{"type": "persona"}])  # persona is B's type
        result = _parse_agent_response(text, "A", 1, 5, 8)
        assert len(result.issues) == 0

    def test_max_issues_enforced(self):
        """超出 max_issues 应截断。"""
        issues = [{"type": "rhythm"} for _ in range(10)]
        text = _make_agent_json("A", issues)
        result = _parse_agent_response(text, "A", 1, 5, 3)
        assert len(result.issues) <= 3

    def test_invalid_json_returns_empty(self):
        result = _parse_agent_response("not json at all", "A", 1, 5, 8)
        assert len(result.issues) == 0

    def test_json_in_code_block(self):
        text = f"```json\n{_make_agent_json('A', [{'type': 'hook'}])}\n```"
        result = _parse_agent_response(text, "A", 1, 5, 8)
        assert len(result.issues) == 1


# ---------------------------------------------------------------------------
# Phase 2 isolation tests (sync wrappers around async)
# ---------------------------------------------------------------------------

class TestPhase2Isolation:
    """验证 Phase 2 的信息隔离和工具禁用。"""

    def test_phase2_information_isolation(self):
        """Phase 2 的每个 agent 输入只含 v1 不含 v2。"""
        asyncio.run(self._test_isolation())

    async def _test_isolation(self):
        call_log = []

        async def mock_generate(messages, **kwargs):
            call_log.append({
                "messages": [m["content"][:100] for m in messages],
                "tools": kwargs.get("tools"),
                "phase": "p2" if "反思" in messages[0]["content"] else "p1",
            })
            if "反思" not in messages[0]["content"]:
                aid = "A" if "Editor-A" in messages[0]["content"] else \
                      "B" if "Editor-B" in messages[0]["content"] else "C"
                types = {"A": "rhythm", "B": "persona", "C": "visual_clash"}
                issues = [{"id": f"{aid}-1", "type": types[aid], "paragraph": 1,
                           "severity": "medium", "keyword": "k", "description": "d",
                           "suggestion": {"content": "c", "rationale": "r"}}]
                return _make_response(_make_agent_json(aid, [{"type": types[aid]}]),
                                       submit_review_issues=issues)
            # Phase 2 — return submit_review for reflection
            issues = [{"id": "A-1", "type": "rhythm", "paragraph": 1,
                       "severity": "medium", "keyword": "k", "description": "d",
                       "suggestion": {"content": "c", "rationale": "r"}}]
            return _make_response("", submit_review_issues=issues)

        adapter = MagicMock()
        adapter.generate = mock_generate

        with patch("biyu.editor.multi_agent.load_editor_config", return_value=_mock_config()):
            await review_chapter_multi_agent(
                chapter_num=1,
                chapter_text="测试正文",
                book_dir=Path("/tmp/test_book"),
                adapter=adapter,
            )

        p2_calls = [c for c in call_log if c["phase"] == "p2"]
        assert len(p2_calls) == 3
        for call in p2_calls:
            for msg_content in call["messages"]:
                # Phase 2 input should not reference v2 data
                assert "v2" not in msg_content.lower() or "v1" in msg_content

    def test_phase2_only_submit_review_tool(self):
        """Phase 2 的 adapter.generate() 调用只传 submit_review 工具。"""
        asyncio.run(self._test_submit_review_only())

    async def _test_submit_review_only(self):
        tool_args = []

        async def mock_generate(messages, **kwargs):
            if "反思" not in messages[0]["content"]:
                aid = "A" if "Editor-A" in messages[0]["content"] else \
                      "B" if "Editor-B" in messages[0]["content"] else "C"
                types = {"A": "rhythm", "B": "persona", "C": "visual_clash"}
                issues = [{"id": f"{aid}-1", "type": types[aid], "paragraph": 1,
                           "severity": "medium", "keyword": "k", "description": "d",
                           "suggestion": {"content": "c", "rationale": "r"}}]
                return _make_response(_make_agent_json(aid, [{"type": types[aid]}]),
                                       submit_review_issues=issues)
            tool_args.append(kwargs.get("tools"))
            # Phase 2 returns submit_review
            issues = [{"id": "A-1", "type": "rhythm", "paragraph": 1,
                       "severity": "medium", "keyword": "k", "description": "d",
                       "suggestion": {"content": "c", "rationale": "r"}}]
            return _make_response("", submit_review_issues=issues)

        adapter = MagicMock()
        adapter.generate = mock_generate

        with patch("biyu.editor.multi_agent.load_editor_config", return_value=_mock_config()):
            await review_chapter_multi_agent(
                chapter_num=1,
                chapter_text="测试正文",
                book_dir=Path("/tmp/test_book"),
                adapter=adapter,
            )

        for tools_val in tool_args:
            # Phase 2 should only have submit_review in tools
            assert tools_val is not None
            assert len(tools_val) == 1
            assert tools_val[0]["function"]["name"] == "submit_review"


# ---------------------------------------------------------------------------
# Budget fallback
# ---------------------------------------------------------------------------

class TestBudgetFallback:
    def test_budget_fallback(self):
        """超限触发 fallback。"""
        asyncio.run(self._test_fallback())

    async def _test_fallback(self):
        high_cost = 0.1  # 超过 threshold 0.05

        async def mock_generate(messages, **kwargs):
            if "Editor-A" in messages[0]["content"]:
                return _make_response(_make_agent_json("A", [{"type": "rhythm"}]), cost=high_cost)
            elif "Editor-B" in messages[0]["content"]:
                return _make_response(_make_agent_json("B", [{"type": "persona"}]), cost=0.001)
            elif "Editor-C" in messages[0]["content"]:
                return _make_response(_make_agent_json("C", [{"type": "visual_clash"}]), cost=0.001)
            return _make_response("{}", cost=0.001)

        adapter = MagicMock()
        adapter.generate = mock_generate

        cfg = _mock_config()
        cfg["fallback_on_budget_exceed"] = True
        cfg["fallback_threshold_yuan_per_chapter"] = 0.05

        with patch("biyu.editor.multi_agent.load_editor_config", return_value=cfg):
            result = await review_chapter_multi_agent(
                chapter_num=1,
                chapter_text="测试正文",
                book_dir=Path("/tmp/test_book"),
                adapter=adapter,
            )

        assert result.fallback_used is True
        assert result.total_cost > 0.05


# ---------------------------------------------------------------------------
# Prompt char limit
# ---------------------------------------------------------------------------

class TestPromptLimits:
    def test_prompt_within_char_limit(self):
        """每个 agent prompt ≤ 800 字。"""
        from biyu.editor.agent_prompts.editor_a import EDITOR_A_SYSTEM_PROMPT
        from biyu.editor.agent_prompts.editor_b import EDITOR_B_SYSTEM_PROMPT
        from biyu.editor.agent_prompts.editor_c import EDITOR_C_SYSTEM_PROMPT

        for name, prompt in [
            ("A", EDITOR_A_SYSTEM_PROMPT),
            ("B", EDITOR_B_SYSTEM_PROMPT),
            ("C", EDITOR_C_SYSTEM_PROMPT),
        ]:
            assert len(prompt) <= 800, f"Editor-{name} prompt exceeds 800 chars: {len(prompt)}"
            assert len(prompt) > 100, f"Editor-{name} prompt seems too short"


# ---------------------------------------------------------------------------
# Single mode fallback
# ---------------------------------------------------------------------------

class TestSingleModeFallback:
    def test_single_mode_returns_default_config(self):
        """当 editor.yaml 不存在时应返回 single 模式。"""
        clear_config_cache()
        with patch("biyu.editor.multi_agent.Path") as mock_path:
            mock_config = MagicMock()
            mock_config.exists.return_value = False
            mock_path.return_value.parents.__getitem__.return_value.__truediv__.return_value = mock_config
