"""P8-M3 三 prompt 文本断言测试(防漂移) + 消息构造器测试。

零烧钱,纯文本断言。

设计:
- 3 条 anti-drift 测试:每条 prompt 文本与设计稿 2026-07-04 定稿逐字对比
  (改 prompt 需同时更新本测试,确保故意变更而非意外损坏)
- 消息构造器测试:build_editor_messages / build_director_messages /
  build_naming_messages 产出正确结构
"""
from __future__ import annotations

from pathlib import Path

import pytest

from biyu.ui.prompts_editor import (
    DIRECTOR_SYSTEM_PROMPT,
    EDITOR_SYSTEM_PROMPT,
    PLACEHOLDER_FLAGS,
    build_director_messages,
    build_editor_messages,
)
from biyu.ui.prompts_naming import (
    NAMING_SYSTEM_PROMPT,
    build_naming_messages,
    is_naming_placeholder,
    read_paradigm_ref,
    set_naming_placeholder,
)


# ---------------------------------------------------------------------------
# Anti-drift: 三条 prompt 文本与设计稿 2026-07-04 定稿逐字对照
# ---------------------------------------------------------------------------


class TestEditorPromptAntiDrift:
    """责编 system prompt 防漂移:只含"查了再说话"同行责编人格。"""

    def test_editor_prompt_contains_key_principles(self):
        """责编 prompt 包含五条规矩 + 语气要求。"""
        assert "先查后说" in EDITOR_SYSTEM_PROMPT
        assert "像编辑,不像检查器" in EDITOR_SYSTEM_PROMPT
        assert "不空夸,不空贬" in EDITOR_SYSTEM_PROMPT
        assert "决定权在作者" in EDITOR_SYSTEM_PROMPT
        assert "不代写正文" in EDITOR_SYSTEM_PROMPT
        assert "直接、省字、同行之间不客套" in EDITOR_SYSTEM_PROMPT

    def test_editor_prompt_no_extra_text(self):
        """责编 prompt 不由其他文本侵入。"""
        # 不应含"导演"或"起名"相关内容
        assert "导演" not in EDITOR_SYSTEM_PROMPT
        assert "起名" not in EDITOR_SYSTEM_PROMPT
        # 应以语气要求结尾
        assert EDITOR_SYSTEM_PROMPT.strip().endswith("同行之间不客套。")


class TestDirectorPromptAntiDrift:
    """导演 system prompt 防漂移:三步顺序(冲突→节奏→方案)+ 红线。"""

    def test_director_prompt_contains_three_steps(self):
        """导演 prompt 包含三步:冲突预警/节奏判断/给方案。"""
        assert "冲突预警" in DIRECTOR_SYSTEM_PROMPT
        assert "节奏与市场判断" in DIRECTOR_SYSTEM_PROMPT
        assert "给方案不做主" in DIRECTOR_SYSTEM_PROMPT

    def test_director_prompt_contains_redlines(self):
        """导演 prompt 包含红线:不写正文、不出细纲。"""
        assert "不写正文" in DIRECTOR_SYSTEM_PROMPT
        assert "不出细纲" in DIRECTOR_SYSTEM_PROMPT

    def test_director_prompt_no_extra_text(self):
        """导演 prompt 不由其他文本侵入。"""
        assert "责编" not in DIRECTOR_SYSTEM_PROMPT
        assert "榜样" not in DIRECTOR_SYSTEM_PROMPT


class TestNamingPromptAntiDrift:
    """起名 system prompt 防漂移:8-10 候选 + 三条标准 + 范式引用。"""

    def test_naming_prompt_contains_candidate_rule(self):
        """起名 prompt 包含 8-10 个候选要求。"""
        assert "8-10 个候选" in NAMING_SYSTEM_PROMPT

    def test_naming_prompt_contains_three_criteria(self):
        """起名 prompt 包含三条评判标准:信息量/口语可读/搜索友好。"""
        assert "信息量" in NAMING_SYSTEM_PROMPT
        assert "口语可读" in NAMING_SYSTEM_PROMPT
        assert "搜索友好" in NAMING_SYSTEM_PROMPT

    def test_naming_prompt_contains_paradigm_ref(self):
        """起名 prompt 包含命名范式参考注入(派发单附加句)。"""
        assert "命名范式" in NAMING_SYSTEM_PROMPT

    def test_naming_paradigm_uses_prompts_assets_single_home(self):
        root = Path(__file__).resolve().parents[1]
        content = read_paradigm_ref()

        assert "全文消费者" in content
        assert (root / "prompts" / "assets" / "命名范式_v0.md").is_file()
        assert not (root / "docs" / "craft" / "命名范式_v0.md").exists()

    def test_missing_naming_paradigm_fails_loudly(self, monkeypatch, tmp_path):
        monkeypatch.setattr("biyu.ui.prompts_naming.get_project_root", lambda: tmp_path)
        expected = tmp_path / "prompts" / "assets" / "命名范式_v0.md"
        with pytest.raises(RuntimeError, match="Required prompt asset could not be read") as exc:
            read_paradigm_ref()
        assert str(expected) in str(exc.value)


# ---------------------------------------------------------------------------
# 占位开关
# ---------------------------------------------------------------------------


class TestPlaceholderFlags:
    def test_placeholder_flipped_off_after_b_review(self):
        """B 核通过后占位模式已翻转为 False(所有角色)。"""
        assert PLACEHOLDER_FLAGS["editor"] is False
        assert PLACEHOLDER_FLAGS["director"] is False

    def test_naming_placeholder_flipped_off_after_b_review(self):
        """B 核通过后起名占位已翻转为 False。"""
        assert is_naming_placeholder() is False

    def test_set_naming_placeholder(self):
        """set_naming_placeholder 生效。"""
        set_naming_placeholder(False)
        assert is_naming_placeholder() is False
        set_naming_placeholder(True)
        assert is_naming_placeholder() is True


# ---------------------------------------------------------------------------
# 消息构造器结构测试
# ---------------------------------------------------------------------------


class TestBuildEditorMessages:
    def test_returns_list_of_dicts(self):
        """build_editor_messages 返回 dict 列表。"""
        messages = build_editor_messages([], [], "你好")
        assert isinstance(messages, list)
        assert all(isinstance(m, dict) for m in messages)

    def test_first_message_is_system(self):
        """首条消息 role=system,content=EDITOR_SYSTEM_PROMPT。"""
        messages = build_editor_messages([], [], "你好")
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == EDITOR_SYSTEM_PROMPT

    def test_last_message_is_user(self):
        """末条消息 role=user,content=用户输入。"""
        messages = build_editor_messages([], [], "查角色陈凡")
        assert messages[-1]["role"] == "user"
        assert messages[-1]["content"] == "查角色陈凡"

    def test_history_included(self):
        """历史消息包含在 system 与 user 之间。"""
        history = [
            {"role": "user", "content": "之前的问题"},
            {"role": "assistant", "content": "之前的回复"},
        ]
        messages = build_editor_messages(history, [], "新问题")
        # R2 后:system(0:人格) + system(1:工具说明) + history(2,3) + user(4)
        assert len(messages) == 5
        assert messages[2] == history[0]
        assert messages[3] == history[1]

    def test_tool_results_included(self):
        """工具结果作为 system 消息注入。"""
        tools = [{"name": "read_truth_files", "args": {}, "result": "current_state", "cost": 0.0}]
        messages = build_editor_messages([], tools, "看看真相")
        # R2 后:system(0:人格) + system(1:工具说明) + tool_context(2) + user(3)
        assert len(messages) == 4
        # tool_context 在 messages[2]
        assert messages[2]["role"] == "system"
        assert "read_truth_files" in messages[2]["content"]

    def test_empty_conversation_history(self):
        """空历史消息列表仍正常工作。"""
        messages = build_editor_messages([], [], "查角色陈凡")
        assert len(messages) >= 2  # system + user


class TestBuildDirectorMessages:
    def test_first_message_is_system(self):
        """首条消息 role=system,content=DIRECTOR_SYSTEM_PROMPT。"""
        messages = build_director_messages([], [], "主角想探索秘境")
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == DIRECTOR_SYSTEM_PROMPT

    def test_last_message_is_user(self):
        """末条消息 role=user。"""
        messages = build_director_messages([], [], "主角想探索秘境")
        assert messages[-1]["role"] == "user"
        assert messages[-1]["content"] == "主角想探索秘境"

    def test_tool_results_included(self):
        """工具结果作为 system 消息注入,前缀为"会诊资料"。"""
        tools = [{"name": "read_craft", "args": {}, "result": "节奏参考", "cost": 0.0}]
        messages = build_director_messages([], tools, "主角想探索秘境")
        # R2 后:system(0:人格) + system(1:工具说明) + tool_context(2) + user(3)
        # 会诊资料在 messages[2](工具说明段占 messages[1])
        assert "会诊资料" in messages[2]["content"]


class TestBuildNamingMessages:
    def test_returns_system_user_pair(self):
        """build_naming_messages 返 [system, user]。"""
        messages = build_naming_messages("修仙", "xianxia", "扫榜数据", "范式参考")
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == NAMING_SYSTEM_PROMPT
        assert messages[1]["role"] == "user"

    def test_user_content_contains_idea(self):
        """user 消息含作品设想与题材。"""
        messages = build_naming_messages("主角穿越修仙", "xianxia", "凡人修仙传", "范式参考")
        user_content = messages[1]["content"]
        assert "主角穿越修仙" in user_content
        assert "xianxia" in user_content
        assert "凡人修仙传" in user_content
        assert "范式参考" in user_content

    def test_handles_empty_idea(self):
        """空设想可处理。"""
        messages = build_naming_messages("", "dushi", "数据", "范式")
        assert messages[1]["role"] == "user"
        assert "(空)" in messages[1]["content"]
