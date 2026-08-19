"""D-54: Unit tests for submit_review tool-bearing output contract.

Tests the new submit_review-based output flow:

1. submit_review tool definition schemas (single + agent)
2. Final round only has submit_review in tools array
3. execute_tool defensive error handling
4. Arguments parse fail → RUN_FAIL
5. No submit_review in final round → RUN_FAIL
6. Token budget: config-driven max_tokens flows through to adapter.generate()
7. Character card wiring (fixture check)

Zero LLM cost: uses stub adapter.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from biyu.editor.parser import (
    parse_editor_response,
    _extract_json,
)
from biyu.editor.tools import (
    SUBMIT_REVIEW_SINGLE,
    SUBMIT_REVIEW_AGENT,
    EditorFailure,
    execute_tool,
    get_submit_review_tool,
)


# ---------------------------------------------------------------------------
# Stub adapter for tool-loop / token-budget tests
# ---------------------------------------------------------------------------

class StubResponse:
    def __init__(self, text="", cost=0.0, reasoning="", raw=None,
                 tool_calls=None, finish_reason="stop"):
        self.text = text
        self.cost = cost
        self.reasoning_content = reasoning
        self.raw = raw or {"choices": [{"message": {"content": text}}]}
        self.finish_reason = finish_reason
        if tool_calls:
            self.raw["choices"][0]["message"]["tool_calls"] = tool_calls


class StubAdapter:
    """Records calls and returns scripted responses."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    async def generate(self, messages, **kwargs):
        self.calls.append({"messages": messages, "kwargs": kwargs})
        if self._responses:
            return self._responses.pop(0)
        return StubResponse(text='{"issues": []}')


def _make_tool_call(name="look_up_character", args='{"char_name": "x"}'):
    return [{
        "id": "call_0",
        "type": "function",
        "function": {"name": name, "arguments": args},
    }]


def _make_submit_review_call(issues, confidence="high"):
    """构造一个 submit_review tool call。"""
    args = json.dumps({"issues": issues, "confidence": confidence}, ensure_ascii=False)
    return [{
        "id": "call_submit",
        "type": "function",
        "function": {"name": "submit_review", "arguments": args},
    }]


# ---------------------------------------------------------------------------
# A6-1: submit_review single schema
# ---------------------------------------------------------------------------

class TestSubmitReviewSingleSchema:
    def test_submit_review_single_structure(self):
        """SUBMIT_REVIEW_SINGLE has correct structure."""
        tool = SUBMIT_REVIEW_SINGLE
        assert tool["type"] == "function"
        assert tool["function"]["name"] == "submit_review"
        params = tool["function"]["parameters"]
        assert "issues" in params["properties"]
        assert "issues" in params["required"]
        # issues is array
        assert params["properties"]["issues"]["type"] == "array"
        # items has EditorIssue fields
        item_props = params["properties"]["issues"]["items"]["properties"]
        for field in ("line", "quote", "type", "explanation", "fix_suggestion",
                      "auto_fixable", "severity"):
            assert field in item_props, f"Missing field: {field}"

    def test_get_submit_review_tool_single(self):
        """get_submit_review_tool('single') returns SUBMIT_REVIEW_SINGLE."""
        tool = get_submit_review_tool("single")
        assert tool["function"]["name"] == "submit_review"


# ---------------------------------------------------------------------------
# A6-2: submit_review agent schema
# ---------------------------------------------------------------------------

class TestSubmitReviewAgentSchema:
    def test_submit_review_agent_structure(self):
        """SUBMIT_REVIEW_AGENT has correct structure."""
        tool = SUBMIT_REVIEW_AGENT
        assert tool["type"] == "function"
        assert tool["function"]["name"] == "submit_review"
        params = tool["function"]["parameters"]
        assert "issues" in params["properties"]
        assert "issues" in params["required"]
        item_props = params["properties"]["issues"]["items"]["properties"]
        for field in ("id", "type", "paragraph", "severity", "keyword",
                      "description", "suggestion"):
            assert field in item_props, f"Missing field: {field}"
        # suggestion has sub-properties
        sug_props = item_props["suggestion"]["properties"]
        assert "content" in sug_props
        assert "rationale" in sug_props

    def test_get_submit_review_tool_agent(self):
        """get_submit_review_tool('agent') returns SUBMIT_REVIEW_AGENT."""
        tool = get_submit_review_tool("agent")
        assert tool["function"]["name"] == "submit_review"

    def test_get_submit_review_tool_invalid(self):
        """get_submit_review_tool with invalid mode raises ValueError."""
        with pytest.raises(ValueError):
            get_submit_review_tool("invalid")


# ---------------------------------------------------------------------------
# A6-3: Final round only submit_review
# ---------------------------------------------------------------------------

class TestFinalRoundOnlySubmitReview:
    def test_single_mode_final_round_only_submit_review(self, tmp_path):
        """In final round, tools array should only contain submit_review."""
        from biyu.editor.editor import review_chapter

        # Round 0: tool call → Round 1: submit_review (with max_tool_rounds=1)
        tool_resp = StubResponse(
            text="checking",
            raw={"choices": [{"message": {
                "content": "checking",
                "tool_calls": _make_tool_call(),
            }}]},
        )
        submit_resp = StubResponse(
            text="done",
            raw={"choices": [{"message": {
                "content": "done",
                "tool_calls": _make_submit_review_call([{
                    "line": 1, "quote": "测试", "type": "字面伪影",
                    "explanation": "test", "fix_suggestion": "delete",
                    "auto_fixable": True, "severity": "high",
                }]),
            }}]},
        )
        adapter = StubAdapter([tool_resp, submit_resp])

        result = asyncio.run(review_chapter(
            chapter_num=1,
            chapter_text="测试正文包含测试",
            book_dir=tmp_path,
            adapter=adapter,
            max_tool_rounds=1,
        ))

        # Round 0 had full tools (lookup + submit_review)
        round0_tools = adapter.calls[0]["kwargs"]["tools"]
        tool_names = [t["function"]["name"] for t in round0_tools]
        assert "submit_review" in tool_names
        assert "look_up_character" in tool_names

        # Round 1 (final) had only submit_review
        round1_tools = adapter.calls[1]["kwargs"]["tools"]
        assert len(round1_tools) == 1
        assert round1_tools[0]["function"]["name"] == "submit_review"

        assert len(result.issues) == 1
        assert result.issues[0].type == "字面伪影"


# ---------------------------------------------------------------------------
# P7-9: max_tool_rounds 默认 3→5 + 收尾轮注入技术指令
# ---------------------------------------------------------------------------

class TestP79FinalRoundDirective:
    """P7-9 T1:Editor 收尾轮强制 submit_review。

    背景:P7-7 实测 ch7 RUN_FAIL(LLM 用满 lookup 轮不调 submit_review);
    P7-8 核查坐实 D-54 tool-loop"设计如此"(非沉默失效),ch7 RUN_FAIL 是
    LLM 决策随机性(重跑成功)。P7-9 按 spec 预答决策点 A-5 第一档:
    ① max_tool_rounds 默认 3→5;② 收尾轮注入技术指令(独立于
    EDITOR_SYSTEM_PROMPT 的协议级提示)强制 LLM 调 submit_review。
    """

    def test_review_chapter_default_max_tool_rounds_is_5(self):
        """review_chapter 签名默认 max_tool_rounds=5(P7-9 从 3 升到 5)。"""
        import inspect
        from biyu.editor.editor import review_chapter
        sig = inspect.signature(review_chapter)
        max_rounds_param = sig.parameters["max_tool_rounds"]
        assert max_rounds_param.default == 5, (
            f"P7-9: max_tool_rounds 默认应为 5(从 3 升到 5),"
            f"当前为 {max_rounds_param.default}"
        )

    def test_final_round_injects_submit_review_directive(self, tmp_path):
        """收尾轮 messages 含 P7-9 注入的技术指令(独有字眼:'最后一轮' + '空审读')。

        独有性:EDITOR_SYSTEM_PROMPT 含 'submit_review' 但不含
        '最后一轮'/'空审读',验证注入是独立技术指令而非 prompt 创作内容。
        """
        from biyu.editor.editor import review_chapter

        # max_tool_rounds=0:只 1 轮即收尾轮;mock LLM 调 submit_review → 成功
        submit_resp = StubResponse(
            text="done",
            raw={"choices": [{"message": {
                "content": "done",
                "tool_calls": _make_submit_review_call([]),  # 空审读
            }}]},
        )
        adapter = StubAdapter([submit_resp])

        asyncio.run(review_chapter(
            chapter_num=1,
            chapter_text="测试正文",
            book_dir=tmp_path,
            adapter=adapter,
            max_tool_rounds=0,
        ))

        # 收尾轮发给 LLM 的 messages
        round0_messages = adapter.calls[0]["messages"]
        all_content = " ".join(
            m.get("content", "") for m in round0_messages
            if isinstance(m.get("content"), str)
        )
        # P7-9 注入指令的独有字眼(EDITOR_SYSTEM_PROMPT 没这些)
        assert "最后一轮" in all_content, (
            "收尾轮必须注入'最后一轮'提示,让 LLM 知道这是最后机会"
        )
        assert "空审读" in all_content, (
            "收尾轮必须注入'无 issue 也提交空审读'的指示"
        )


# ---------------------------------------------------------------------------
# A6-4: execute_tool bad arguments
# ---------------------------------------------------------------------------

class TestExecuteToolBadArguments:
    def test_missing_char_name(self, tmp_path):
        """Missing char_name → BAD_ARGUMENTS JSON."""
        result = execute_tool("look_up_character", {}, tmp_path)
        data = json.loads(result)
        assert data["error"] == "BAD_ARGUMENTS"

    def test_missing_keyword(self, tmp_path):
        """Missing keyword → BAD_ARGUMENTS JSON."""
        result = execute_tool("look_up_setting", {}, tmp_path)
        data = json.loads(result)
        assert data["error"] == "BAD_ARGUMENTS"

    def test_missing_chapter_or_keyword(self, tmp_path):
        """Missing chapter_or_keyword → BAD_ARGUMENTS JSON."""
        result = execute_tool("look_up_history", {}, tmp_path)
        data = json.loads(result)
        assert data["error"] == "BAD_ARGUMENTS"

    def test_missing_symbol(self, tmp_path):
        """Missing symbol → BAD_ARGUMENTS JSON."""
        result = execute_tool("look_up_visual", {}, tmp_path)
        data = json.loads(result)
        assert data["error"] == "BAD_ARGUMENTS"


# ---------------------------------------------------------------------------
# A6-5: execute_tool unknown tool
# ---------------------------------------------------------------------------

class TestExecuteToolUnknownTool:
    def test_unknown_tool(self, tmp_path):
        """Unknown tool name → UNKNOWN_TOOL JSON."""
        result = execute_tool("nonexistent_tool", {"x": "y"}, tmp_path)
        data = json.loads(result)
        assert data["error"] == "UNKNOWN_TOOL"
        assert "nonexistent_tool" in data["message"]


# ---------------------------------------------------------------------------
# A6-6: execute_tool exception → TOOL_EXEC_ERROR
# ---------------------------------------------------------------------------

class TestExecuteToolException:
    def test_exception_returns_tool_exec_error(self, tmp_path):
        """Exception during tool execution → TOOL_EXEC_ERROR JSON."""
        # look_up_character with a corrupted book dir that raises
        # Create a book_dir with a bad characters.yaml
        bad_file = tmp_path / "characters.yaml"
        bad_file.write_text("not: valid\n  yaml: [", encoding="utf-8")
        result = execute_tool("look_up_character", {"char_name": "test"}, tmp_path)
        # yaml.safe_load might still work with this, but if it errors...
        # Actually, let's test with a non-existent book dir to force path error
        # We need a case where the function itself throws
        # look_up_visual with invalid book_dir structure should be fine
        # Let's use a simpler approach: patch the function
        import unittest.mock
        with unittest.mock.patch("biyu.editor.tools.look_up_character", side_effect=RuntimeError("boom")):
            result = execute_tool("look_up_character", {"char_name": "test"}, tmp_path)
            data = json.loads(result)
            assert data["error"] == "TOOL_EXEC_ERROR"
            assert "boom" in data["message"]


# ---------------------------------------------------------------------------
# A6-7: Arguments parse fail → RUN_FAIL
# ---------------------------------------------------------------------------

class TestArgumentsParseFail:
    def test_submit_review_bad_arguments_json(self, tmp_path):
        """submit_review with unparseable arguments → BAD_ARGUMENTS failure."""
        from biyu.editor.editor import review_chapter

        # Return a submit_review call with invalid JSON arguments
        bad_submit_resp = StubResponse(
            text="done",
            raw={"choices": [{"message": {
                "content": "done",
                "tool_calls": [{
                    "id": "call_bad",
                    "type": "function",
                    "function": {"name": "submit_review", "arguments": "not valid json {{{"},
                }],
            }}]},
        )
        adapter = StubAdapter([bad_submit_resp])

        result = asyncio.run(review_chapter(
            chapter_num=1,
            chapter_text="测试正文",
            book_dir=tmp_path,
            adapter=adapter,
            max_tool_rounds=0,
        ))

        # Should have a BAD_ARGUMENTS failure
        assert any("failure:BAD_ARGUMENTS" in e for e in result.parse_errors)


# ---------------------------------------------------------------------------
# A6-8: No submit_review in final round → RUN_FAIL
# ---------------------------------------------------------------------------

class TestNoSubmitReviewInFinalRound:
    def test_single_mode_no_submit_review_in_final_round(self, tmp_path):
        """When LLM doesn't call submit_review in final round → RUN_FAIL."""
        from biyu.editor.editor import review_chapter

        # LLM returns lookup tool calls but no submit_review
        tool_resp = StubResponse(
            text="checking",
            raw={"choices": [{"message": {
                "content": "checking",
                "tool_calls": _make_tool_call(),
            }}]},
        )
        adapter = StubAdapter([tool_resp])

        result = asyncio.run(review_chapter(
            chapter_num=1,
            chapter_text="测试正文",
            book_dir=tmp_path,
            adapter=adapter,
            max_tool_rounds=0,  # Only 1 round (final round immediately)
        ))

        # Should have a RUN_FAIL failure
        assert any("failure:RUN_FAIL" in e for e in result.parse_errors)

    def test_single_mode_submit_review_in_early_round(self, tmp_path):
        """LLM calls submit_review early → success, no more rounds."""
        from biyu.editor.editor import review_chapter

        submit_resp = StubResponse(
            text="done",
            raw={"choices": [{"message": {
                "content": "done",
                "tool_calls": _make_submit_review_call([{
                    "line": 1, "quote": "测试", "type": "字面伪影",
                    "explanation": "test", "fix_suggestion": "delete",
                    "auto_fixable": True, "severity": "high",
                }]),
            }}]},
        )
        adapter = StubAdapter([submit_resp])

        result = asyncio.run(review_chapter(
            chapter_num=1,
            chapter_text="测试正文包含测试",
            book_dir=tmp_path,
            adapter=adapter,
            max_tool_rounds=3,
        ))

        # Should succeed with 1 issue
        assert len(result.issues) == 1
        assert result.issues[0].type == "字面伪影"
        # Only 1 call (submit_review on first round)
        assert len(adapter.calls) == 1


# ---------------------------------------------------------------------------
# Tool-loop with submit_review (replaces old force-final tests)
# ---------------------------------------------------------------------------

class TestToolLoopWithSubmitReview:
    def test_single_mode_tool_then_submit(self, tmp_path):
        """Tool call then submit_review works correctly."""
        from biyu.editor.editor import review_chapter

        tool_resp = StubResponse(
            text="checking",
            raw={"choices": [{"message": {
                "content": "checking",
                "tool_calls": _make_tool_call(),
            }}]},
        )
        submit_resp = StubResponse(
            text="done",
            raw={"choices": [{"message": {
                "content": "done",
                "tool_calls": _make_submit_review_call([{
                    "line": 1, "quote": "测试", "type": "字面伪影",
                    "explanation": "test", "fix_suggestion": "delete",
                    "auto_fixable": True, "severity": "high",
                }]),
            }}]},
        )
        adapter = StubAdapter([tool_resp, submit_resp])

        result = asyncio.run(review_chapter(
            chapter_num=1,
            chapter_text="测试正文包含测试",
            book_dir=tmp_path,
            adapter=adapter,
            max_tool_rounds=3,
        ))

        assert len(result.issues) == 1
        assert result.issues[0].type == "字面伪影"
        assert len(adapter.calls) == 2

    def test_truncation_returns_failure(self, tmp_path):
        """finish_reason=length → TRUNCATION failure."""
        from biyu.editor.editor import review_chapter

        trunc_resp = StubResponse(
            text="truncated...",
            finish_reason="length",
            raw={"choices": [{"message": {"content": "truncated..."}}]},
        )
        adapter = StubAdapter([trunc_resp])

        result = asyncio.run(review_chapter(
            chapter_num=1,
            chapter_text="测试正文",
            book_dir=tmp_path,
            adapter=adapter,
            max_tool_rounds=0,
        ))

        assert any("failure:TRUNCATION" in e for e in result.parse_errors)


# ---------------------------------------------------------------------------
# Token budget control flow
# ---------------------------------------------------------------------------

class TestTokenBudgetConfig:
    """max_tokens is config-driven, not hardcoded 4096."""

    def test_single_mode_reads_max_tokens_from_config(self, tmp_path, monkeypatch):
        """editor.py should read max_completion_tokens from config."""
        from biyu.editor.editor import _load_editor_max_tokens

        val = _load_editor_max_tokens()
        assert val == 16384  # P7-4: 8192 → 16384(治 TRUNCATION);断言镜像配置值

    def test_fallback_to_default_logs_warning(self, caplog, monkeypatch):
        """config 加载失败 → fallback 时必须 log.warning 出声(P7-5)。

        红线:不许静默 fallback。旧版 `except Exception: return 8192` 让一个
        路径 bug(parents[2] 指错位)静默失效 6 个月,P7-4 才发现——配置改了
        但代码读不到,测试一直测 fallback 值不是配置值。出声才能让下次配置
        失效立刻可见。

        本测用 monkeypatch 让 yaml.safe_load 抛错触发 except 路径,断言:
          1. fallback 默认值仍返回(不阻塞生产 —— 安全网保留)
          2. WARNING 日志含 fallback/default/默认 关键词
          3. 日志含 fallback 值本身(8192)便于诊断
        """
        import logging as _logging
        from biyu.editor import editor as editor_mod

        def _boom(*a, **kw):
            raise RuntimeError("simulated config read failure for P7-5 test")

        monkeypatch.setattr(editor_mod.yaml, "safe_load", _boom)

        with caplog.at_level(_logging.WARNING, logger="biyu.editor.editor"):
            val = editor_mod._load_editor_max_tokens()

        # 安全网:fallback 默认值仍返回
        assert val == 8192
        log_text = caplog.text
        # 出声:必须含 fallback/默认/default 任一关键词
        assert (
            "fallback" in log_text.lower()
            or "默认" in log_text
            or "default" in log_text.lower()
        ), "config 失败 fallback 必须在日志里出声(不许静默)"
        # 必须写明 fallback 到什么值,便于诊断
        assert "8192" in log_text, "fallback 默认值必须在日志里写明"

    def test_single_mode_passes_configured_max_tokens(self, tmp_path):
        """adapter.generate() receives max_tokens=16384 (P7-4), not 4096."""
        from biyu.editor.editor import review_chapter

        submit_resp = StubResponse(
            text="done",
            raw={"choices": [{"message": {
                "content": "done",
                "tool_calls": _make_submit_review_call([]),
            }}]},
        )
        adapter = StubAdapter([submit_resp])

        asyncio.run(review_chapter(
            chapter_num=1,
            chapter_text="测试",
            book_dir=tmp_path,
            adapter=adapter,
            max_tool_rounds=0,
        ))

        assert len(adapter.calls) == 1
        assert adapter.calls[0]["kwargs"]["max_tokens"] == 16384  # P7-4

    def test_multi_agent_phase1_passes_configured_max_tokens(self, tmp_path):
        """multi_agent._run_agent_phase1 reads max_completion_tokens from config."""
        from biyu.editor.multi_agent import _run_agent_phase1

        submit_resp = StubResponse(
            text="done",
            raw={"choices": [{"message": {
                "content": "done",
                "tool_calls": _make_submit_review_call([{
                    "id": "A-1", "type": "rhythm", "paragraph": 1,
                    "severity": "medium", "keyword": "k",
                    "description": "d",
                    "suggestion": {"content": "c", "rationale": "r"},
                }]),
            }}]},
        )
        adapter = StubAdapter([submit_resp])

        config = {
            "agents": {"max_tool_calls_per_agent_phase1": 3, "max_issues_per_agent": 8},
            "max_completion_tokens": 8192,
        }

        issue_list, cost = asyncio.run(_run_agent_phase1(
            agent_id="A",
            chapter_num=1,
            chapter_text="测试正文",
            book_dir=tmp_path,
            adapter=adapter,
            config=config,
            prev_chapter_tail="",
        ))

        assert len(adapter.calls) >= 1
        assert adapter.calls[0]["kwargs"]["max_tokens"] == 8192
        assert len(issue_list.issues) == 1


# ---------------------------------------------------------------------------
# Character card wiring (fixture check)
# ---------------------------------------------------------------------------

class TestCharacterCardWiring:
    """Character cards are reachable by look_up_character."""

    def test_main_characters_found(self):
        from biyu.editor.tools import look_up_character

        book_dir = Path(__file__).parents[1] / "eval_set_v0" / "test_book"
        for name in ("江叙白", "何沛", "聂守仁", "苏蔓", "老覃"):
            result = look_up_character(name, book_dir)
            assert "未找到" not in result, f"Character {name} should be found"

    def test_unknown_character_not_found(self):
        from biyu.editor.tools import look_up_character

        book_dir = Path(__file__).parents[1] / "eval_set_v0" / "test_book"
        result = look_up_character("不存在的人", book_dir)
        assert "未找到" in result


# ---------------------------------------------------------------------------
# EditorFailure enum
# ---------------------------------------------------------------------------

class TestEditorFailure:
    def test_all_failure_values(self):
        assert EditorFailure.TRUNCATION.value == "TRUNCATION"
        assert EditorFailure.BAD_ARGUMENTS.value == "BAD_ARGUMENTS"
        assert EditorFailure.UNKNOWN_TOOL.value == "UNKNOWN_TOOL"
        assert EditorFailure.TOOL_EXEC_ERROR.value == "TOOL_EXEC_ERROR"
        assert EditorFailure.RUN_FAIL.value == "RUN_FAIL"


# ---------------------------------------------------------------------------
# P7-4: tool-call parser 容错(BAD_ARGUMENTS verbatim + 重试一次)
# 红线:不许静默猜测/强转参数值;记 verbatim 不截断;submit_review 重试一次。
# 任务来源 data/P7-4/:Editor 37.5% 失败率中 BAD_ARGUMENTS 18.75%。
# ---------------------------------------------------------------------------


class TestToolCallBadArgsVerbatimLogging:
    """工具调用层 args JSON 坏 → 记 verbatim 完整原文(不静默吞、不截断、不猜测)。"""

    def test_tool_call_bad_args_logged_verbatim(self, tmp_path, caplog):
        """args JSON 坏时,完整 verbatim 原文必须进日志(不被静默吞)。"""
        import logging as _logging
        from biyu.editor.editor import review_chapter

        bad_args = "{bad json {{{ not valid"
        bad_tool_resp = StubResponse(
            text="checking",
            raw={"choices": [{"message": {
                "content": "checking",
                "tool_calls": [{
                    "id": "call_bad",
                    "type": "function",
                    "function": {"name": "look_up_character", "arguments": bad_args},
                }],
            }}]},
        )
        submit_resp = StubResponse(
            text="done",
            raw={"choices": [{"message": {
                "content": "done",
                "tool_calls": _make_submit_review_call([]),
            }}]},
        )
        adapter = StubAdapter([bad_tool_resp, submit_resp])

        with caplog.at_level(_logging.WARNING, logger="biyu.editor.editor"):
            asyncio.run(review_chapter(
                chapter_num=1,
                chapter_text="测试正文",
                book_dir=tmp_path,
                adapter=adapter,
                max_tool_rounds=2,
            ))

        # 完整 verbatim 必须在日志里(目前实现静默吞 → 红)
        assert bad_args in caplog.text, "坏 args 的 verbatim 原文必须进日志"

    def test_tool_call_bad_args_verbatim_not_truncated(self, tmp_path, caplog):
        """长 verbatim(>500 字符)也要完整记录,不截断到 200。"""
        import logging as _logging
        from biyu.editor.editor import review_chapter

        long_tail = "x" * 600  # 远超旧的 [:200] 截断点
        long_bad_args = "{" + long_tail
        bad_tool_resp = StubResponse(
            text="checking",
            raw={"choices": [{"message": {
                "content": "checking",
                "tool_calls": [{
                    "id": "call_long",
                    "type": "function",
                    "function": {"name": "look_up_character", "arguments": long_bad_args},
                }],
            }}]},
        )
        submit_resp = StubResponse(
            text="done",
            raw={"choices": [{"message": {
                "content": "done",
                "tool_calls": _make_submit_review_call([]),
            }}]},
        )
        adapter = StubAdapter([bad_tool_resp, submit_resp])

        with caplog.at_level(_logging.WARNING, logger="biyu.editor.editor"):
            asyncio.run(review_chapter(
                chapter_num=1,
                chapter_text="测试正文",
                book_dir=tmp_path,
                adapter=adapter,
                max_tool_rounds=2,
            ))

        # 末尾 600 个 x 也必须在日志里 → 证明没截断
        assert long_tail in caplog.text, "长 verbatim 不能截断"

    def test_tool_call_pure_garbage_not_coerced(self, tmp_path):
        """完全无 JSON 结构的乱码 → tool_args 必须是空 dict。

        P7-4 红线"不许猜测/强转"在 P7-8 部分松绑:json_repair 类型的标准化修复
        (补引号/逗号、转义引号)现在允许。但"完全无结构的乱码"(json_repair 也修不好)
        仍不许被强转成看似合理的参数 → 仍返空 dict,execute_tool 自然返 BAD_ARGUMENTS。
        """
        from biyu.editor.editor import review_chapter

        # 完全无 JSON 结构,json_repair 也修不好
        bad_args = "abc def ghi {{{ not json at all"
        bad_tool_resp = StubResponse(
            text="checking",
            raw={"choices": [{"message": {
                "content": "checking",
                "tool_calls": [{
                    "id": "call_guess",
                    "type": "function",
                    "function": {"name": "look_up_character", "arguments": bad_args},
                }],
            }}]},
        )
        submit_resp = StubResponse(
            text="done",
            raw={"choices": [{"message": {
                "content": "done",
                "tool_calls": _make_submit_review_call([]),
            }}]},
        )
        adapter = StubAdapter([bad_tool_resp, submit_resp])

        result = asyncio.run(review_chapter(
            chapter_num=1,
            chapter_text="测试正文",
            book_dir=tmp_path,
            adapter=adapter,
            max_tool_rounds=2,
        ))

        # queries_used 里记录的 tool_args 必须是空 dict(json_repair 也修不好)
        # 如果是 "look_up_character({\"char_name\": \"foo\"})" → 红线违反(被强转)
        assert any("look_up_character({})" in q for q in result.queries_used), \
            f"完全无结构的乱码不应被强转;queries_used={result.queries_used}"


class TestSubmitReviewBadArgsRetry:
    """submit_review 参数 JSON 坏 → 给 LLM 一次重试机会(目前直接 BAD_ARGUMENTS failure)。"""

    def test_submit_review_bad_args_retries_once_and_succeeds(self, tmp_path):
        """第一次 submit_review args 坏 → 重试一次,LLM 第二次给合法 JSON → 成功(无 failure)。"""
        from biyu.editor.editor import review_chapter

        bad_submit = StubResponse(
            text="done",
            raw={"choices": [{"message": {
                "content": "done",
                "tool_calls": [{
                    "id": "call_bad_submit",
                    "type": "function",
                    "function": {"name": "submit_review", "arguments": "not valid json {{{"},
                }],
            }}]},
        )
        good_submit = StubResponse(
            text="done",
            raw={"choices": [{"message": {
                "content": "done",
                "tool_calls": _make_submit_review_call([]),
            }}]},
        )
        adapter = StubAdapter([bad_submit, good_submit])

        result = asyncio.run(review_chapter(
            chapter_num=1,
            chapter_text="测试正文",
            book_dir=tmp_path,
            adapter=adapter,
            max_tool_rounds=1,
        ))

        # 重试成功 → 无 failure
        assert not any("failure:" in e for e in result.parse_errors), \
            f"重试一次应成功,parse_errors={result.parse_errors}"
        # LLM 被调用 2 次(第一次坏 → 重试 → 第二次成功)
        assert len(adapter.calls) == 2

    def test_submit_review_bad_args_retry_fails_returns_failure(self, tmp_path, caplog):
        """重试一次仍坏 → BAD_ARGUMENTS failure + 两次 verbatim 都进日志。"""
        import logging as _logging
        from biyu.editor.editor import review_chapter

        bad1_args = "bad json attempt 1 {{{"
        bad2_args = "bad json attempt 2 }}}"
        bad1 = StubResponse(
            text="done",
            raw={"choices": [{"message": {
                "content": "done",
                "tool_calls": [{
                    "id": "call_b1",
                    "type": "function",
                    "function": {"name": "submit_review", "arguments": bad1_args},
                }],
            }}]},
        )
        bad2 = StubResponse(
            text="done",
            raw={"choices": [{"message": {
                "content": "done",
                "tool_calls": [{
                    "id": "call_b2",
                    "type": "function",
                    "function": {"name": "submit_review", "arguments": bad2_args},
                }],
            }}]},
        )
        adapter = StubAdapter([bad1, bad2])

        with caplog.at_level(_logging.WARNING, logger="biyu.editor.editor"):
            result = asyncio.run(review_chapter(
                chapter_num=1,
                chapter_text="测试正文",
                book_dir=tmp_path,
                adapter=adapter,
                max_tool_rounds=1,
            ))

        # 最终 BAD_ARGUMENTS failure
        assert any("failure:BAD_ARGUMENTS" in e for e in result.parse_errors)
        # 两次 verbatim 都在日志里(诊断根因用)
        assert bad1_args in caplog.text, "第一次坏 args verbatim 必须在日志"
        assert bad2_args in caplog.text, "重试仍坏的 args verbatim 必须在日志"


# ---------------------------------------------------------------------------
# P7-8: json_repair 兜底修复(治 BAD_ARGUMENTS 50%)
# 红线松绑:P7-4 "不许猜测/强转" 在 P7-8 部分松绑——json_repair 类型的标准化
# 修复(补引号 / 转义 / 补逗号)现在允许,因 P7-7 实测 50% 失败率现实需要治。
# 仍保留:"完全无结构乱码"(json_repair 也修不好)→ 仍 BAD_ARGUMENTS。
# 任务来源 data/P7-8/:P7-7 实测 BAD_ARGUMENTS 50%,根因 LLM 生成不合规 JSON。
# ---------------------------------------------------------------------------


class TestJsonRepairFallbackToolArgs:
    """_safe_parse_tool_args 在 json.loads 失败时用 json_repair 兜底修复主流畸形。"""

    def test_confidence_no_quotes_repaired(self):
        """`{"confidence": high}` (忘加引号) → 修复成 `{"confidence": "high"}`。

        这是 P7-7 乱码日志里观察到的真实根因模式。
        """
        from biyu.editor.editor import _safe_parse_tool_args

        result = _safe_parse_tool_args('{"confidence": high}', "look_up_character")
        assert result == {"confidence": "high"}, \
            f"json_repair 应修复 confidence 忘加引号;got {result}"

    def test_unescaped_quotes_in_value_repaired(self):
        """值字段含未转义 ASCII 引号 → 修复后解析。

        P7-3 / P7-4 report §2.4 描述的根因模式:LLM 在 explanation 字段里用
        未转义双引号包裹中文词。
        """
        from biyu.editor.editor import _safe_parse_tool_args

        bad = '{"line": 1, "explanation": "角色说"你好"打断对话"}'
        result = _safe_parse_tool_args(bad, "submit_review")
        assert isinstance(result, dict), "json_repair 应能修复未转义引号"
        assert result.get("line") == 1

    def test_missing_comma_repaired(self):
        """缺逗号 → 修复后解析。"""
        from biyu.editor.editor import _safe_parse_tool_args

        bad = '{"line": 1 "quote": "x"}'
        result = _safe_parse_tool_args(bad, "submit_review")
        assert isinstance(result, dict), "json_repair 应能修复缺逗号"
        assert result.get("line") == 1

    def test_already_valid_not_repaired(self, caplog):
        """合法 JSON 不需要修复,json_repair 不应触发修复 WARNING。"""
        import logging as _logging
        from biyu.editor.editor import _safe_parse_tool_args

        with caplog.at_level(_logging.WARNING, logger="biyu.editor.editor"):
            result = _safe_parse_tool_args('{"a": "b"}', "look_up_character")
        assert result == {"a": "b"}
        # 合法 JSON 不应触发"repaired"日志(没修就是没修)
        assert "repaired" not in caplog.text.lower(), \
            f"合法 JSON 不应触发修复日志;caplog={caplog.text}"

    def test_pure_garbage_returns_empty(self):
        """完全无 JSON 结构的乱码(json_repair 也修不好)→ 仍返 {}。

        这是 P7-8 保留的安全网:json_repair 不是万能,极端坏 JSON 仍返空。
        """
        from biyu.editor.editor import _safe_parse_tool_args

        result = _safe_parse_tool_args("not even close to json {{{", "look_up_character")
        assert result == {}, \
            f"完全无结构的乱码应返空 dict;got {result}"

    def test_repair_action_logged_warning(self, caplog):
        """修复动作必须进 WARNING 日志(原文 + 修复后,可见不静默)。"""
        import logging as _logging
        from biyu.editor.editor import _safe_parse_tool_args

        bad = '{"confidence": high}'
        with caplog.at_level(_logging.WARNING, logger="biyu.editor.editor"):
            result = _safe_parse_tool_args(bad, "look_up_character")

        assert result == {"confidence": "high"}
        # 原文 + 修复关键词必须在日志
        assert bad in caplog.text, "原文 verbatim 必须进日志"
        assert "repair" in caplog.text.lower(), \
            f"修复动作必须有日志痕迹(repair/json_repair);caplog={caplog.text}"


class TestJsonRepairFallbackSubmitReview:
    """submit_review 解析层在 json.loads 失败时用 json_repair 兜底。

    P7-7 实测 BAD_ARGUMENTS 主导失败,根因是 submit_review args 复杂 JSON
    出格式错(如 "confidence": high 忘加引号)。P7-4 的重试是兜底不是根治。
    P7-8:先 json_repair 修复,修不好再走 P7-4 重试/fail 路径。
    """

    def test_submit_review_confidence_no_quotes_repaired_no_retry(self, tmp_path):
        """submit args 含 confidence 忘加引号 → json_repair 修复 → 成功。

        期望:不触发 P7-4 重试(修复在第 1 次就成功),adapter 只被调 1 次。
        """
        from biyu.editor.editor import review_chapter

        bad_submit = StubResponse(
            text="done",
            raw={"choices": [{"message": {
                "content": "done",
                "tool_calls": [{
                    "id": "call_bad_submit",
                    "type": "function",
                    "function": {
                        "name": "submit_review",
                        "arguments": '{"issues": [], "confidence": high}',
                    },
                }],
            }}]},
        )
        adapter = StubAdapter([bad_submit])

        result = asyncio.run(review_chapter(
            chapter_num=1,
            chapter_text="测试正文",
            book_dir=tmp_path,
            adapter=adapter,
            max_tool_rounds=1,
        ))

        # 修复成功 → 无 BAD_ARGUMENTS
        assert not any("failure:BAD_ARGUMENTS" in e for e in result.parse_errors), \
            f"json_repair 应修复 confidence 无引号,不应 BAD_ARGUMENTS;parse_errors={result.parse_errors}"
        # 没触发重试:adapter 只被调 1 次
        assert len(adapter.calls) == 1, \
            f"json_repair 修复后不应触发重试;adapter.calls={len(adapter.calls)}"

    def test_submit_review_repair_action_logged(self, tmp_path, caplog):
        """submit_review 修复动作必须进日志(可见,不静默)。"""
        import logging as _logging
        from biyu.editor.editor import review_chapter

        bad_submit = StubResponse(
            text="done",
            raw={"choices": [{"message": {
                "content": "done",
                "tool_calls": [{
                    "id": "call_bad_submit",
                    "type": "function",
                    "function": {
                        "name": "submit_review",
                        "arguments": '{"issues": [], "confidence": high}',
                    },
                }],
            }}]},
        )
        adapter = StubAdapter([bad_submit])

        with caplog.at_level(_logging.WARNING, logger="biyu.editor.editor"):
            asyncio.run(review_chapter(
                chapter_num=1,
                chapter_text="测试正文",
                book_dir=tmp_path,
                adapter=adapter,
                max_tool_rounds=1,
            ))

        assert "repair" in caplog.text.lower(), \
            f"submit_review 修复动作应进日志;caplog={caplog.text}"

    def test_submit_review_pure_garbage_still_retries_then_fails(self, tmp_path):
        """json_repair 修不好的纯坏 submit args → 走 P7-4 重试 → 仍坏 → BAD_ARGUMENTS。"""
        from biyu.editor.editor import review_chapter

        bad1 = StubResponse(
            text="done",
            raw={"choices": [{"message": {
                "content": "done",
                "tool_calls": [{
                    "id": "call_b1",
                    "type": "function",
                    "function": {
                        "name": "submit_review",
                        "arguments": "abc def ghi {{{ not json",
                    },
                }],
            }}]},
        )
        bad2 = StubResponse(
            text="done",
            raw={"choices": [{"message": {
                "content": "done",
                "tool_calls": [{
                    "id": "call_b2",
                    "type": "function",
                    "function": {
                        "name": "submit_review",
                        "arguments": "}}} more garbage }}}",
                    },
                }],
            }}]},
        )
        adapter = StubAdapter([bad1, bad2])

        result = asyncio.run(review_chapter(
            chapter_num=1,
            chapter_text="测试正文",
            book_dir=tmp_path,
            adapter=adapter,
            max_tool_rounds=1,
        ))

        # json_repair 修不好 → 触发重试 → 仍坏 → BAD_ARGUMENTS
        assert any("failure:BAD_ARGUMENTS" in e for e in result.parse_errors), \
            f"纯坏 JSON 应最终 BAD_ARGUMENTS;parse_errors={result.parse_errors}"
        assert len(adapter.calls) == 2, "应触发一次重试"


# ---------------------------------------------------------------------------
# P7-8: UTF-8 FileHandler(治 P7-7 终端 GBK 拿不到干净 verbatim 的问题)
# ---------------------------------------------------------------------------

class TestUtf8FileHandler:
    """P7-8: editor logger 加 UTF-8 FileHandler,绕过 Windows 终端 GBK 解码。

    P7-7 probe 发现:logger.warning 输出到 stderr → tee 写文件时被 GBK 解码
    中文乱码,污染 BAD_ARGUMENTS verbatim 诊断。本测试验证:直接以 UTF-8
    编码写文件后,中文消息在落盘文件里完整可读。
    """

    def test_utf8_log_file_preserves_chinese_verbatim(self, tmp_path):
        """_enable_editor_file_logging 写出的日志文件中文不乱码。"""
        import logging as _logging
        from biyu.editor.editor import (
            _enable_editor_file_logging,
            logger as editor_logger,
        )

        log_file = tmp_path / "editor_test.log"

        # 用自定义路径(不动默认 data/.editor_logs/editor.log)
        returned_path = _enable_editor_file_logging(log_file)
        assert returned_path == log_file, \
            f"返回的路径应等于传入路径;got={returned_path}"

        # 取到 handler 引用,try/finally 保证清理(不污染其他测试)
        added_handlers = [h for h in editor_logger.handlers
                          if isinstance(h, _logging.FileHandler)
                          and Path(h.baseFilename) == log_file]
        assert len(added_handlers) >= 1, "FileHandler 应已挂到 editor logger"

        try:
            # 发一条含中文的 WARNING(模拟 BAD_ARGUMENTS verbatim 场景)
            chinese_msg = "BAD_ARGUMENTS verbatim: \"confidence\": 高置信度}"
            editor_logger.warning(chinese_msg)
            # flush 一下确保落盘
            for h in added_handlers:
                h.flush()

            # 读文件验证:必须能以 UTF-8 解码 + 含原文中文
            content = log_file.read_text(encoding="utf-8")
            assert chinese_msg in content, \
                f"中文消息应在日志文件中完整保留;content={content!r}"
            # 关键断言:不能用 GBK 解码出来假装通过
            # (GBK 解 UTF-8 写的中文文件会抛 UnicodeDecodeError 或出乱码)
            raw_bytes = log_file.read_bytes()
            # UTF-8 编码中文"高"是 0xe9 0xab 0x98;GBK 解这串会是乱码
            assert "高置信度".encode("utf-8") in raw_bytes, \
                "文件应是 UTF-8 编码(GBK 不会有这个字节序列)"
        finally:
            # 清理:移除 handler,关闭文件句柄(Windows 下不关会锁文件)
            for h in added_handlers:
                editor_logger.removeHandler(h)
                h.close()

