"""Editor 单测 — 12+ 用例。"""
import json
import pytest
from pathlib import Path
from biyu.editor.parser import parse_editor_response, EditorIssue, EditorResult
from biyu.editor.auto_fix import auto_fix_issues
from biyu.editor.prompts import EDITOR_SYSTEM_PROMPT, build_editor_user_prompt
from biyu.editor.tools import (
    look_up_character, look_up_setting, look_up_history, look_up_visual,
    execute_tool, TOOL_DEFINITIONS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_book_dir(tmp_path):
    """Create a minimal book dir for tool testing."""
    (tmp_path / "characters.yaml").write_text(
        "characters:\n"
        "  - name: 张今空\n"
        "    aliases:\n"
        "      narrator_default: '他'\n"
        "    voice_examples:\n"
        "      - '卧槽，这也太猛了'\n"
        "    personality: '热血少年'\n"
        "  - name: 周大龙\n"
        "    voice_examples:\n"
        "      - '我擦'\n",
        encoding="utf-8",
    )
    (tmp_path / "worldbook.yaml").write_text(
        "facts:\n"
        "  - 金色是外部观察者的标志色\n"
        "  - 命甲是核心装备\n"
        "forbidden:\n"
        "  - 秘境内不得出现手机互联网\n"
        "power_system:\n"
        "  - 命甲等级：白/绿/蓝/紫/金\n",
        encoding="utf-8",
    )
    # Create chapter files for history/visual lookup
    ch_dir = tmp_path / "chapters"
    ch_dir.mkdir()
    (ch_dir / "ch1.md").write_text(
        "张今空走进了镇异局。金色的光芒在他手中闪烁。"
        "老樵看着他说：'来了。'",
        encoding="utf-8",
    )
    (ch_dir / "ch2.md").write_text(
        "周大龙一拳打在墙上。青铜色的命甲发出嗡鸣。"
        "曹操冷笑道：'后人编的。'",
        encoding="utf-8",
    )
    return tmp_path


SAMPLE_CHAPTER = (
    "老樵看着张今空，忽然说了句：[NAME]你来了。"
    "金色的光芒笼罩了短刀第七字。"
    "曹操冷笑道：后人编的都是假的。"
    "张今空在水中用布画了一张图。"
    "红糖糍粑红糖糍粑红糖糍粑，他一直在吃红糖糍粑。"
)


# ---------------------------------------------------------------------------
# Test 1: 字面伪影识别
# ---------------------------------------------------------------------------
def test_literal_artifact_detection():
    """CH10 章末句模拟数据 → 应识别。"""
    response = json.dumps({
        "issues": [{
            "line": 1, "quote": "[NAME]", "type": "字面伪影",
            "subtype": None, "explanation": "占位符",
            "fix_suggestion": "delete", "auto_fixable": True,
        }],
        "queries_used": [], "confidence": "high",
    })
    result = parse_editor_response(response, SAMPLE_CHAPTER)
    assert len(result.issues) == 1
    assert result.issues[0].type == "字面伪影"
    assert result.issues[0].auto_fixable is True


# ---------------------------------------------------------------------------
# Test 2: 认知边界识别
# ---------------------------------------------------------------------------
def test_perspective_violation():
    """曹操"后人编的"模拟 → 应识别。"""
    response = json.dumps({
        "issues": [{
            "line": 3, "quote": "后人编的都是假的", "type": "认知边界",
            "subtype": None, "explanation": "三国时代角色不应知道后人编的",
            "fix_suggestion": "manual_review", "auto_fixable": False,
        }],
        "queries_used": [], "confidence": "high",
    })
    result = parse_editor_response(response, SAMPLE_CHAPTER)
    assert len(result.issues) == 1
    assert result.issues[0].type == "认知边界"


# ---------------------------------------------------------------------------
# Test 3: 跨章衔接（含工具调用）
# ---------------------------------------------------------------------------
def test_cross_chapter_consistency():
    """金色撞色模拟 → 应识别。"""
    response = json.dumps({
        "issues": [{
            "line": 2, "quote": "金色的光芒笼罩了短刀第七字", "type": "跨章衔接",
            "subtype": None, "explanation": "金色已分配给外部观察者",
            "fix_suggestion": "manual_review", "auto_fixable": False,
        }],
        "queries_used": ["look_up_visual('金色')"], "confidence": "high",
    })
    result = parse_editor_response(response, SAMPLE_CHAPTER)
    assert len(result.issues) == 1
    assert result.issues[0].type == "跨章衔接"
    assert "look_up_visual" in result.queries_used[0]


# ---------------------------------------------------------------------------
# Test 4: 逻辑常识识别
# ---------------------------------------------------------------------------
def test_logic_hole():
    """水中布上画图模拟 → 应识别。"""
    response = json.dumps({
        "issues": [{
            "line": 4, "quote": "张今空在水中用布画了一张图", "type": "逻辑常识",
            "subtype": None, "explanation": "布在水里会散",
            "fix_suggestion": "manual_review", "auto_fixable": False,
        }],
        "queries_used": [], "confidence": "medium",
    })
    result = parse_editor_response(response, SAMPLE_CHAPTER)
    assert len(result.issues) == 1
    assert result.issues[0].type == "逻辑常识"


# ---------------------------------------------------------------------------
# Test 5: 人物一致 — 符号过度
# ---------------------------------------------------------------------------
def test_character_conservation_symbol_overuse():
    """红糖糍粑频次模拟 → 应识别。"""
    response = json.dumps({
        "issues": [{
            "line": 5, "quote": "红糖糍粑红糖糍粑红糖糍粑", "type": "人物一致",
            "subtype": "符号过度", "explanation": "红糖糍粑频繁出现",
            "fix_suggestion": "manual_review", "auto_fixable": False,
        }],
        "queries_used": [], "confidence": "high",
    })
    result = parse_editor_response(response, SAMPLE_CHAPTER)
    assert len(result.issues) == 1
    assert result.issues[0].type == "人物一致"
    assert result.issues[0].subtype == "符号过度"


# ---------------------------------------------------------------------------
# Test 6: 幻觉防御（quote 不在原文中）
# ---------------------------------------------------------------------------
def test_hallucination_filter():
    """quote 不在原文中 → 应过滤。"""
    response = json.dumps({
        "issues": [{
            "line": 99, "quote": "这段文字根本不存在于原文中", "type": "逻辑常识",
            "subtype": None, "explanation": "幻觉测试",
            "fix_suggestion": "manual_review", "auto_fixable": False,
        }],
        "queries_used": [], "confidence": "low",
    })
    result = parse_editor_response(response, SAMPLE_CHAPTER)
    assert len(result.issues) == 0
    assert len(result.parse_errors) > 0
    assert "幻觉" in result.parse_errors[0]


# ---------------------------------------------------------------------------
# Test 7: auto_fixable 校验（只有字面伪影可以为 true）
# ---------------------------------------------------------------------------
def test_auto_fixable_enforcement():
    """非字面伪影类不应 auto_fixable=true。"""
    response = json.dumps({
        "issues": [{
            "line": 3, "quote": "后人编的都是假的", "type": "认知边界",
            "subtype": None, "explanation": "穿帮",
            "fix_suggestion": "manual_review", "auto_fixable": True,  # 应被强制改为 False
        }],
        "queries_used": [], "confidence": "high",
    })
    result = parse_editor_response(response, SAMPLE_CHAPTER)
    assert len(result.issues) == 1
    assert result.issues[0].auto_fixable is False  # 被强制修正


# ---------------------------------------------------------------------------
# Test 8: issue 上限 8 个
# ---------------------------------------------------------------------------
def test_issue_limit():
    """超过 8 个 issue 应截断。"""
    issues = []
    for i in range(10):
        issues.append({
            "line": 1, "quote": "张今空", "type": "字面伪影",
            "subtype": None, "explanation": f"test {i}",
            "fix_suggestion": "manual_review", "auto_fixable": False,
        })
    response = json.dumps({"issues": issues, "queries_used": [], "confidence": "high"})
    result = parse_editor_response(response, SAMPLE_CHAPTER)
    assert len(result.issues) <= 8


# ---------------------------------------------------------------------------
# Test 9: look_up_character 工具
# ---------------------------------------------------------------------------
def test_tool_look_up_character(mock_book_dir):
    result = look_up_character("张今空", mock_book_dir)
    assert "张今空" in result
    assert "aliases" in result


# ---------------------------------------------------------------------------
# Test 10: look_up_setting 工具
# ---------------------------------------------------------------------------
def test_tool_look_up_setting(mock_book_dir):
    result = look_up_setting("命甲", mock_book_dir)
    assert "命甲" in result


# ---------------------------------------------------------------------------
# Test 11: look_up_visual 工具
# ---------------------------------------------------------------------------
def test_tool_look_up_visual(mock_book_dir):
    result = look_up_visual("金色", mock_book_dir)
    assert "金色" in result
    assert "chapter" in result


# ---------------------------------------------------------------------------
# Test 12: look_up_history 工具
# ---------------------------------------------------------------------------
def test_tool_look_up_history(mock_book_dir):
    result = look_up_history("金色", mock_book_dir)
    assert "金色" in result


# ---------------------------------------------------------------------------
# Test 13: auto_fix 字面伪影
# ---------------------------------------------------------------------------
def test_auto_fix_literal_artifact():
    """字面伪影 [NAME] 应被自动删除。"""
    chapter = "老樵看着张今空，[NAME]忽然说了句话。"
    issues = [EditorIssue(
        line=1, quote="[NAME]", type="字面伪影", subtype=None,
        explanation="占位符", fix_suggestion="delete", auto_fixable=True,
    )]
    fixed, count = auto_fix_issues(chapter, issues)
    assert count == 1
    assert "[NAME]" not in fixed
    assert "老樵看着张今空" in fixed


# ---------------------------------------------------------------------------
# Test 14: prompt 不为空
# ---------------------------------------------------------------------------
def test_prompts_not_empty():
    assert len(EDITOR_SYSTEM_PROMPT) > 100
    prompt = build_editor_user_prompt(chapter_num=1, chapter_text="测试正文")
    assert "第 1 章" in prompt
    assert "测试正文" in prompt


# ---------------------------------------------------------------------------
# Test 14b: 战力等级边界句逐字断言 (P7-10)
#   防漂移:老板拍板的边界措辞必须逐字落在 EDITOR_SYSTEM_PROMPT 战力等级段末尾。
#   改 prompt 同步测试(防漂移清单第 1 条)。
# ---------------------------------------------------------------------------
def test_editor_prompt_contains_boundary_clause():
    boundary_clause = (
        "边界:同一对象的境界、等级或战力强弱在前后文不一致时,报「战力等级」,不报「章内自洽」;"
        "角色使用了其身份不该掌握的境界术语或体系知识时,报「认知边界」,不报「战力等级」;"
        "两种问题同时成立时分别报,不合并成一条。"
    )
    assert boundary_clause in EDITOR_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Test 15: TOOL_DEFINITIONS 格式正确
# ---------------------------------------------------------------------------
def test_tool_definitions_format():
    assert len(TOOL_DEFINITIONS) == 4
    names = {td["function"]["name"] for td in TOOL_DEFINITIONS}
    assert names == {"look_up_character", "look_up_setting", "look_up_history", "look_up_visual"}


# ---------------------------------------------------------------------------
# Test 16: execute_tool 路由
# ---------------------------------------------------------------------------
def test_execute_tool_routing(mock_book_dir):
    result = execute_tool("look_up_character", {"char_name": "张今空"}, mock_book_dir)
    assert "张今空" in result
    result = execute_tool("unknown_tool", {}, mock_book_dir)
    # Returns structured JSON error with UNKNOWN_TOOL code
    assert "UNKNOWN_TOOL" in result


# ---------------------------------------------------------------------------
# Test 17: multi_agent tool_call_id in tool messages (D-39 regression)
# ---------------------------------------------------------------------------
def test_multi_agent_tool_call_id_in_tool_messages(mock_book_dir):
    """Verify that tool messages include tool_call_id (DeepSeek API requirement).

    Regression test for T-P3-D-2 bug: tool responses were missing tool_call_id
    and assistant messages were missing reasoning_content, causing DeepSeek API
    to reject requests with 400 errors.
    """
    import asyncio
    from unittest.mock import AsyncMock, MagicMock
    from biyu.editor.multi_agent import _run_agent_phase1

    # Build a mock adapter that returns a tool_call with reasoning, then submit_review
    tool_call_resp = MagicMock()
    tool_call_resp.text = "calling tool"
    tool_call_resp.cost = 0.001
    tool_call_resp.reasoning_content = "Let me look up the character..."
    tool_call_resp.raw = {
        "choices": [{
            "message": {
                "content": "calling tool",
                "tool_calls": [{
                    "id": "call_abc123",
                    "function": {"name": "look_up_character", "arguments": '{"char_name": "张今空"}'},
                    "type": "function",
                }],
            }
        }]
    }

    submit_resp = MagicMock()
    submit_resp.text = "done"
    submit_resp.cost = 0.001
    submit_resp.reasoning_content = None
    submit_resp.raw = {
        "choices": [{
            "message": {
                "content": "done",
                "tool_calls": [{
                    "id": "call_submit",
                    "function": {
                        "name": "submit_review",
                        "arguments": json.dumps({"issues": [{"id": "A-1", "type": "rhythm", "paragraph": 1, "severity": "medium", "keyword": "k", "description": "d", "suggestion": {"content": "c", "rationale": "r"}}]}),
                    },
                    "type": "function",
                }],
            }
        }]
    }

    adapter = AsyncMock()
    adapter.generate = AsyncMock(side_effect=[tool_call_resp, submit_resp])
    config = {"agents": {"max_tool_calls_per_agent_phase1": 3, "max_issues_per_agent": 8}}

    result = asyncio.run(
        _run_agent_phase1("A", 1, "测试正文", mock_book_dir, adapter, config, "")
    )

    # Check the second call's messages (after tool call round)
    second_call_messages = adapter.generate.call_args_list[1][0][0]

    # Verify assistant message has tool_calls
    assistant_msgs = [m for m in second_call_messages if m["role"] == "assistant"]
    assert len(assistant_msgs) >= 1
    assert "tool_calls" in assistant_msgs[-1], "assistant message must include tool_calls"

    # Verify assistant message includes reasoning_content (DeepSeek R1 requirement)
    assert "reasoning_content" in assistant_msgs[-1], "assistant message must include reasoning_content"
    assert assistant_msgs[-1]["reasoning_content"] == "Let me look up the character..."

    # Verify tool message has tool_call_id
    tool_msgs = [m for m in second_call_messages if m["role"] == "tool"]
    assert len(tool_msgs) >= 1
    assert "tool_call_id" in tool_msgs[0], "tool message must include tool_call_id"
    assert tool_msgs[0]["tool_call_id"] == "call_abc123"


# ---------------------------------------------------------------------------
# Test 18: editor.py tool_call_id in tool messages (parallel to D-40)
# ---------------------------------------------------------------------------
def test_editor_tool_call_id_in_tool_messages(mock_book_dir):
    """Verify that tool messages in editor.py include tool_call_id (DeepSeek API requirement).

    Parallel to test_multi_agent_tool_call_id_in_tool_messages (D-40 fix).
    Regression test for T-P3-D-2.2: editor.py had the same missing fields.
    """
    import asyncio
    from unittest.mock import AsyncMock, MagicMock
    from biyu.editor.editor import review_chapter

    # Build a mock adapter that returns a tool_call with reasoning, then submit_review
    tool_call_resp = MagicMock()
    tool_call_resp.text = "calling tool"
    tool_call_resp.reasoning_content = "Let me look up the character..."
    tool_call_resp.raw = {
        "choices": [{
            "message": {
                "content": "calling tool",
                "tool_calls": [{
                    "id": "call_editor_xyz789",
                    "function": {"name": "look_up_character", "arguments": '{"char_name": "张今空"}'},
                    "type": "function",
                }],
            }
        }]
    }

    submit_resp = MagicMock()
    submit_resp.text = "done"
    submit_resp.reasoning_content = None
    submit_resp.raw = {
        "choices": [{
            "message": {
                "content": "done",
                "tool_calls": [{
                    "id": "call_submit",
                    "function": {
                        "name": "submit_review",
                        "arguments": json.dumps({
                            "issues": [],
                            "confidence": "high",
                        }),
                    },
                    "type": "function",
                }],
            }
        }]
    }

    adapter = AsyncMock()
    adapter.generate = AsyncMock(side_effect=[tool_call_resp, submit_resp])

    result = asyncio.run(
        review_chapter(
            chapter_num=1,
            chapter_text="测试正文",
            book_dir=mock_book_dir,
            adapter=adapter,
        )
    )

    # Check the second call's messages (after tool call round)
    second_call_messages = adapter.generate.call_args_list[1][0][0]

    # Verify assistant message has tool_calls
    assistant_msgs = [m for m in second_call_messages if m["role"] == "assistant"]
    assert len(assistant_msgs) >= 1
    assert "tool_calls" in assistant_msgs[-1], "assistant message must include tool_calls"

    # Verify assistant message includes reasoning_content (DeepSeek R1 requirement)
    assert "reasoning_content" in assistant_msgs[-1], "assistant message must include reasoning_content"
    assert assistant_msgs[-1]["reasoning_content"] == "Let me look up the character..."

    # Verify tool message has tool_call_id
    tool_msgs = [m for m in second_call_messages if m["role"] == "tool"]
    assert len(tool_msgs) >= 1
    assert "tool_call_id" in tool_msgs[0], "tool message must include tool_call_id"
    assert tool_msgs[0]["tool_call_id"] == "call_editor_xyz789"


# ---------------------------------------------------------------------------
# Test 19: suggestion field quality check (T-P3-D-3 Part A)
# ---------------------------------------------------------------------------
def test_suggestion_field_quality():
    """Non-artifact issues with vague fix_suggestion should trigger parse_error."""
    # "manual_review" should be flagged
    response = json.dumps({
        "issues": [{
            "line": 3, "quote": "后人编的都是假的", "type": "认知边界",
            "subtype": None, "explanation": "穿帮",
            "fix_suggestion": "manual_review", "auto_fixable": False,
            "severity": "high",
        }],
        "queries_used": [], "confidence": "high",
    })
    result = parse_editor_response(response, SAMPLE_CHAPTER)
    assert len(result.issues) == 1
    assert any("suggestion 质量不足" in e for e in result.parse_errors)

    # Short suggestion should also be flagged
    response2 = json.dumps({
        "issues": [{
            "line": 4, "quote": "张今空在水中用布画了一张图", "type": "逻辑常识",
            "subtype": None, "explanation": "布会散",
            "fix_suggestion": "请检查", "auto_fixable": False,
            "severity": "medium",
        }],
        "queries_used": [], "confidence": "high",
    })
    result2 = parse_editor_response(response2, SAMPLE_CHAPTER)
    assert any("suggestion 质量不足" in e for e in result2.parse_errors)

    # Good suggestion should NOT be flagged
    response3 = json.dumps({
        "issues": [{
            "line": 3, "quote": "后人编的都是假的", "type": "认知边界",
            "subtype": None, "explanation": "穿帮",
            "fix_suggestion": "曹操是三国人物，不应使用'后人编的'这类元叙事表达，改为符合时代的措辞",
            "auto_fixable": False, "severity": "high",
        }],
        "queries_used": [], "confidence": "high",
    })
    result3 = parse_editor_response(response3, SAMPLE_CHAPTER)
    assert not any("suggestion 质量不足" in e for e in result3.parse_errors)

    # 字面伪影类 "manual_review" should NOT be flagged (allowed for artifacts)
    response4 = json.dumps({
        "issues": [{
            "line": 1, "quote": "[NAME]", "type": "字面伪影",
            "subtype": None, "explanation": "占位符",
            "fix_suggestion": "delete", "auto_fixable": True,
            "severity": "high",
        }],
        "queries_used": [], "confidence": "high",
    })
    result4 = parse_editor_response(response4, SAMPLE_CHAPTER)
    assert not any("suggestion 质量不足" in e for e in result4.parse_errors)


# ---------------------------------------------------------------------------
# Test 20: severity field parsing (T-P3-D-3 Part A)
# ---------------------------------------------------------------------------
def test_severity_field():
    """severity field should be parsed correctly."""
    response = json.dumps({
        "issues": [{
            "line": 3, "quote": "后人编的都是假的", "type": "认知边界",
            "subtype": None, "explanation": "穿帮",
            "fix_suggestion": "改为符合时代的措辞，如'都是后人杜撰'",
            "auto_fixable": False, "severity": "high",
        }, {
            "line": 4, "quote": "张今空在水中用布画了一张图", "type": "逻辑常识",
            "subtype": None, "explanation": "布会散",
            "fix_suggestion": "将场景改为在岸边用石头在地上画图",
            "auto_fixable": False, "severity": "medium",
        }],
        "queries_used": [], "confidence": "high",
    })
    result = parse_editor_response(response, SAMPLE_CHAPTER)
    assert len(result.issues) == 2
    assert result.issues[0].severity == "high"
    assert result.issues[1].severity == "medium"

    # Invalid severity should default to "medium"
    response2 = json.dumps({
        "issues": [{
            "line": 3, "quote": "后人编的都是假的", "type": "认知边界",
            "subtype": None, "explanation": "穿帮",
            "fix_suggestion": "改为符合时代背景的表达方式",
            "auto_fixable": False, "severity": "critical",
        }],
        "queries_used": [], "confidence": "high",
    })
    result2 = parse_editor_response(response2, SAMPLE_CHAPTER)
    assert result2.issues[0].severity == "medium"

    # Missing severity should default to "medium"
    response3 = json.dumps({
        "issues": [{
            "line": 1, "quote": "[NAME]", "type": "字面伪影",
            "subtype": None, "explanation": "占位符",
            "fix_suggestion": "delete", "auto_fixable": True,
        }],
        "queries_used": [], "confidence": "high",
    })
    result3 = parse_editor_response(response3, SAMPLE_CHAPTER)
    assert result3.issues[0].severity == "medium"


# ---------------------------------------------------------------------------
# Test 21: 章内自洽 type 透传 (P6-QC-S1)
# ---------------------------------------------------------------------------
def test_intra_chapter_consistency_type():
    """type='章内自洽' 应被 parser 通过 (P6-QC-S1 新增 type)."""
    response = json.dumps({
        "issues": [{
            "line": 2,
            "quote": "金色的光芒笼罩了短刀第七字",
            "quoted_text": "金色的光芒笼罩了短刀第七字",
            "type": "章内自洽",
            "subtype": None,
            "explanation": "韩旭境界前后矛盾：前文二品，后文一品巅峰",
            "fix_suggestion": "统一韩旭境界，二处选其一并据此调整另一处。",
            "auto_fixable": False,
            "severity": "high",
        }],
        "queries_used": [], "confidence": "high",
    })
    result = parse_editor_response(response, SAMPLE_CHAPTER)
    assert len(result.issues) == 1
    assert result.issues[0].type == "章内自洽"
    assert result.issues[0].severity == "high"


# ---------------------------------------------------------------------------
# Test 22: 战力等级 type 透传 (P6-QC-S1)
# ---------------------------------------------------------------------------
def test_power_level_type():
    """type='战力等级' 应被 parser 通过 (P6-QC-S1 新增 type)."""
    response = json.dumps({
        "issues": [{
            "line": 4,
            "quote": "张今空在水中用布画了一张图",
            "quoted_text": "张今空在水中用布画了一张图",
            "type": "战力等级",
            "subtype": None,
            "explanation": "地位与实力倒挂：韩旭作为最强对手却是一品巅峰，低于二品杂鱼",
            "fix_suggestion": "调整韩旭境界，使其高于二品，符合最强设定。",
            "auto_fixable": False,
            "severity": "high",
        }],
        "queries_used": [], "confidence": "high",
    })
    result = parse_editor_response(response, SAMPLE_CHAPTER)
    assert len(result.issues) == 1
    assert result.issues[0].type == "战力等级"
    assert result.issues[0].severity == "high"
