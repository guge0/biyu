"""T5 会诊纪要单测 (P8-M3 T5)— generate / save / list / read。

零烧钱,纯文件模拟。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from biyu.ui.chat import ChatManager
from biyu.ui.summarize import (
    _compress_editor_memo,
    _get_llm_adapter,
    generate_summary,
    list_summaries,
    read_summary,
    save_summary,
    save_editor_memo,
)


@pytest.fixture(autouse=True)
def _mock_summarize_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit tests 强制降级到模板(零 LLM 调用,零成本)。"""
    monkeypatch.setattr("biyu.ui.summarize._get_llm_adapter", lambda: None)


@pytest.fixture
def chat_mgr(tmp_path: Path) -> ChatManager:
    """ChatManager with tmp data root."""
    return ChatManager(data_root=tmp_path)


@pytest.fixture
def book_dir(tmp_path: Path) -> Path:
    """data/TestBook/ 目录。"""
    d = tmp_path / "TestBook"
    d.mkdir(parents=True)
    return d


def _setup_session_with_messages(chat_mgr: ChatManager) -> str:
    """Create a session with 3 rounds of messages. Return session_id."""
    sid = chat_mgr.new_session("TestBook", "director")
    chat_mgr.add_message(sid, "user", "主角想探索秘境深处")
    chat_mgr.add_message(
        sid, "assistant", "编辑人格待定稿，当前仅代查资料。",
        tool_call={
            "tools": [
                {"name": "read_truth_files", "args": {}, "result": "=== current_state ==="},
            ],
        },
    )
    chat_mgr.add_message(sid, "user", "再加一个女配作为向导")
    chat_mgr.add_message(
        sid, "assistant", "编辑人格待定稿，当前仅代查资料。",
        tool_call={
            "tools": [
                {"name": "read_craft", "args": {}, "result": "# 网文 Craft 蒸馏"},
            ],
        },
    )
    return sid


class TestGenerateSummary:
    @pytest.mark.asyncio
    async def test_generate_basic(self, chat_mgr: ChatManager):
        """从有消息的会话生成纪要 → 三段结构完整。"""
        sid = _setup_session_with_messages(chat_mgr)
        result = await generate_summary(chat_mgr, sid)

        assert result["session_id"] == sid
        assert result["book"] == "TestBook"
        assert result["message_count"] == 4
        assert result["source"] in ("template", "template_fallback")
        assert "被否方向 + 理由" in result["summary_md"]
        assert "还没定的分歧" in result["summary_md"]
        assert "作者口味信号" in result["summary_md"]
        assert "讨论时间线" in result["summary_md"]

    @pytest.mark.asyncio
    async def test_generate_empty_session_does_not_crash(self, chat_mgr: ChatManager):
        """空消息会话 → 不崩,产出含"(会话暂无消息)"。"""
        sid = chat_mgr.new_session("TestBook", "editor")
        result = await generate_summary(chat_mgr, sid)
        assert result["message_count"] == 0
        assert "暂无消息" in result["summary_md"]

    @pytest.mark.asyncio
    async def test_generate_nonexistent_session_raises(self, chat_mgr: ChatManager):
        """不存在的会话 → ValueError。"""
        with pytest.raises(ValueError, match="会话不存在"):
            await generate_summary(chat_mgr, "no-such-session")

    @pytest.mark.asyncio
    async def test_generate_timeline_has_messages(self, chat_mgr: ChatManager):
        """时间线包含每一轮的 role 和内容。"""
        sid = _setup_session_with_messages(chat_mgr)
        result = await generate_summary(chat_mgr, sid)
        assert "user" in result["summary_md"]
        assert "assistant" in result["summary_md"]
        assert "主角想探索秘境深处" in result["summary_md"]


class TestRoleLabelFixup:
    """F1 (P8-M3R-fix):纪要头部 role 字段中文化 + 末尾保留英文原值。

    B3 发现:director mode 创建的会话,纪要头部 `> 角色: editor`(英文 + 错位)。
    修:头部用中文标签(_ROLE_LABELS),末尾加 `> 角色标识: {role}` 保留原值便于追溯。
    """

    @pytest.mark.asyncio
    async def test_director_role_renders_chinese_label(self, chat_mgr: ChatManager):
        """session.role=director → 纪要头部 `> 角色: 导演`。"""
        sid = _setup_session_with_messages(chat_mgr)  # director session
        result = await generate_summary(chat_mgr, sid)
        assert "> 角色: 导演" in result["summary_md"], (
            "director 应显中文'导演',不是英文'editor'或'director'"
        )
        # 末尾保留英文原值便于追溯
        assert "> 角色标识: director" in result["summary_md"], (
            "末尾应保留英文原值'director'用于追溯错位"
        )
        # 头部不应出现英文 director / editor
        assert "> 角色: director" not in result["summary_md"]
        assert "> 角色: editor" not in result["summary_md"]

    @pytest.mark.asyncio
    async def test_editor_role_renders_chinese_label(self, chat_mgr: ChatManager):
        """session.role=editor → 纪要头部 `> 角色: 责编`。"""
        sid = chat_mgr.new_session("TestBook", "editor")
        chat_mgr.add_message(sid, "user", "测试责编路径")
        result = await generate_summary(chat_mgr, sid)
        assert "> 角色: 责编" in result["summary_md"]
        assert "> 角色标识: editor" in result["summary_md"]
        # 不应错位为导演
        assert "> 角色: 导演" not in result["summary_md"]

    @pytest.mark.asyncio
    async def test_unknown_role_falls_back_to_unknown_label(self, chat_mgr: ChatManager):
        """session.role 是未知值(如 'unknown_role')→ 头部显 `> 角色: 未知`,
        末尾原值保留。"""
        # 直接构造非常规 role 的会话
        sid = chat_mgr.new_session("TestBook", "unknown_role")
        chat_mgr.add_message(sid, "user", "测未知 role 兜底")
        result = await generate_summary(chat_mgr, sid)
        assert "> 角色: 未知" in result["summary_md"], (
            "未知 role 应兜底显'未知',不直接显英文值"
        )
        # 末尾保留原值,便于排查
        assert "> 角色标识: unknown_role" in result["summary_md"]


class TestSaveAndList:
    @pytest.mark.asyncio
    async def test_save_creates_file(self, chat_mgr: ChatManager, book_dir: Path):
        """save_summary 在 summaries/ 下创建文件(F2:不再写 consults/)。"""
        sid = _setup_session_with_messages(chat_mgr)
        data = await generate_summary(chat_mgr, sid)
        filename = save_summary(book_dir, data)

        summaries_dir = book_dir / "summaries"
        assert (summaries_dir / filename).exists(), (
            "F2: 新纪要应落到 summaries/ 子目录(命名与 API 一致)"
        )
        # 同时确认 NOT 落到 consults/(避免命名混乱)
        consults_dir = book_dir / "consults"
        assert not (consults_dir / filename).exists(), (
            "F2: 新纪要不该再落到 consults/(与 session json 混)"
        )

    @pytest.mark.asyncio
    async def test_save_increments_seq(self, chat_mgr: ChatManager, book_dir: Path):
        """同一天多次保存 → 序号递增。"""
        sid = _setup_session_with_messages(chat_mgr)
        data = await generate_summary(chat_mgr, sid)

        fn1 = save_summary(book_dir, data)
        fn2 = save_summary(book_dir, data)
        assert fn1 != fn2

    @pytest.mark.asyncio
    async def test_list_returned(self, chat_mgr: ChatManager, book_dir: Path):
        """list_summaries 返回已保存的纪要。"""
        sid = _setup_session_with_messages(chat_mgr)
        data = await generate_summary(chat_mgr, sid)
        save_summary(book_dir, data)

        entries = list_summaries(book_dir)
        assert len(entries) >= 1
        assert "filename" in entries[0]
        assert "date" in entries[0]

    def test_list_empty_book(self, tmp_path: Path):
        """无纪要的书 → 空列表。"""
        empty_dir = tmp_path / "EmptyBook"
        empty_dir.mkdir()
        entries = list_summaries(empty_dir)
        assert entries == []

    @pytest.mark.asyncio
    async def test_read_summary_content(self, chat_mgr: ChatManager, book_dir: Path):
        """read_summary 返回文件全文。"""
        sid = _setup_session_with_messages(chat_mgr)
        data = await generate_summary(chat_mgr, sid)
        filename = save_summary(book_dir, data)

        content = read_summary(book_dir, filename)
        assert "被否方向 + 理由" in content
        assert "讨论时间线" in content

    def test_read_nonexistent_raises(self, book_dir: Path):
        """读不存在的纪要 → FileNotFoundError。"""
        with pytest.raises(FileNotFoundError):
            read_summary(book_dir, "not_exist.md")


class TestSummariesDirFallback:
    """F2 (P8-M3R-fix): summaries/ 子目录隔离 + 兼容旧 consults/。

    B3 发现:API 叫 /api/summaries 但实际读 consults/ 目录(命名混)。
    修:新纪要写 summaries/(命名一致);list/read 扫 summaries/(主)+ consults/(fallback);
    现存纪要不动(避免数据迁移),fallback 兼容读。
    """

    def test_list_reads_both_summaries_and_consults(self, book_dir: Path):
        """list_summaries 同时扫 summaries/ 和 consults/。

        场景:summaries/ 有 1 份新纪要,consults/ 有 1 份旧纪要(手工放入模拟存量)。
        期望:返回 2 条,各带 source_dir 字段("summaries" / "consults")。
        """
        # 新纪要写到 summaries/
        new_dir = book_dir / "summaries"
        new_dir.mkdir(parents=True)
        (new_dir / "纪要_2026-07-09_1.md").write_text("# 新纪要", encoding="utf-8")
        # 旧纪要手工放在 consults/(模拟存量)
        old_dir = book_dir / "consults"
        old_dir.mkdir(parents=True)
        (old_dir / "纪要_2026-07-08_1.md").write_text("# 旧纪要", encoding="utf-8")

        entries = list_summaries(book_dir)
        assert len(entries) == 2, f"应扫到两目录的纪要: {entries}"
        # source_dir 字段标识来源
        sources = {e["source_dir"] for e in entries}
        assert sources == {"summaries", "consults"}, (
            f"source_dir 应区分两目录: {sources}"
        )

    def test_read_summary_finds_in_summaries_first(self, book_dir: Path):
        """read_summary 先在 summaries/ 找,找不到再 fallback consults/。"""
        # 仅在 consults/(模拟旧纪要)
        old_dir = book_dir / "consults"
        old_dir.mkdir(parents=True)
        (old_dir / "纪要_2026-07-08_1.md").write_text("# 旧纪要内容", encoding="utf-8")

        content = read_summary(book_dir, "纪要_2026-07-08_1.md")
        assert "旧纪要内容" in content, "fallback 应能读 consults/ 旧纪要"

    def test_read_summary_prefers_summaries_when_both_exist(self, book_dir: Path):
        """同名文件在两目录都有时,summaries/ 优先(主目录)。

        边角:理论上不应发生(同 filename 不会同时落两目录),但 fallback 路径
        要保证确定性 — summaries/ 主,consults/ 兜底。
        """
        for d in ["summaries", "consults"]:
            sub = book_dir / d
            sub.mkdir(parents=True)
            (sub / "纪要_2026-07-09_1.md").write_text(
                f"# 来自 {d}", encoding="utf-8"
            )

        content = read_summary(book_dir, "纪要_2026-07-09_1.md")
        assert "来自 summaries" in content, (
            "summaries/ 应优先于 consults/(主目录优先)"
        )

    def test_list_entries_have_source_dir_field(self, book_dir: Path):
        """list_summaries 每条 entry 必须带 source_dir 字段(审计性)。"""
        new_dir = book_dir / "summaries"
        new_dir.mkdir(parents=True)
        (new_dir / "纪要_2026-07-09_1.md").write_text("# 新", encoding="utf-8")

        entries = list_summaries(book_dir)
        assert len(entries) == 1
        assert "source_dir" in entries[0]
        assert entries[0]["source_dir"] == "summaries"


class TestEditorRollingMemo:
    def test_repeated_save_replaces_single_memo(self, book_dir: Path):
        first, _ = save_editor_memo(book_dir, {
            "rejected": ["不要倒叙，因为会削弱悬念"],
            "unresolved": ["视角尚未定"],
            "taste_signals": ["偏好短句"],
        })
        second, _ = save_editor_memo(book_dir, {
            "rejected": ["不要梦境开场，因为太常见"],
            "unresolved": [],
            "taste_signals": ["偏好留白"],
        })
        assert first == second == "责编纪要.md"
        content = read_summary(book_dir, second)
        assert "不要梦境开场，因为太常见" in content
        assert "不要倒叙" not in content
        assert len(list_summaries(book_dir)) == 1

    def test_exact_three_sections_and_no_llm(self, monkeypatch, book_dir: Path):
        monkeypatch.setattr("biyu.ui.summarize._get_llm_adapter", lambda: pytest.fail("不得调用 LLM"))
        filename, count = save_editor_memo(book_dir, {
            "rejected": ["方向甲：理由乙"],
            "unresolved": ["甲乙待定"],
            "taste_signals": ["不喜欢解释过满"],
        })
        content = read_summary(book_dir, filename)
        assert content.count("\n## ") == 3
        assert "## 一、被否方向 + 理由" in content
        assert "## 二、还没定的分歧" in content
        assert "## 三、作者口味信号" in content
        assert count == len(content) <= 4000

    def test_over_limit_merges_oldest_deterministically(self, book_dir: Path):
        notes = {
            "rejected": [f"旧项{i}-" + "甲" * 900 for i in range(6)],
            "unresolved": ["未决"],
            "taste_signals": ["口味"],
        }
        compact1 = _compress_editor_memo(notes)
        compact2 = _compress_editor_memo(notes)
        assert compact1 == compact2
        filename, count = save_editor_memo(book_dir, notes)
        content = read_summary(book_dir, filename)
        assert count <= 4000
        assert "较早记录已合并" in content

    def test_legacy_summary_remains_readable(self, book_dir: Path):
        legacy = book_dir / "consults" / "纪要_2026-07-08_1.md"
        legacy.parent.mkdir()
        legacy.write_text("# 旧会诊纪要", encoding="utf-8")
        save_editor_memo(book_dir, {"rejected": [], "unresolved": [], "taste_signals": []})
        assert read_summary(book_dir, legacy.name) == "# 旧会诊纪要"
        assert {item["filename"] for item in list_summaries(book_dir)} == {
            legacy.name, "责编纪要.md"
        }

    @pytest.mark.asyncio
    async def test_route_accepts_editor_notes_without_llm(self, monkeypatch, tmp_path: Path):
        from biyu.ui import routes

        class FakeManager:
            def get_session(self, session_id):
                return {"id": session_id, "book": "TestBook", "messages": [{"role": "user"}]}

        monkeypatch.setattr(routes, "_get_chat_mgr", lambda: FakeManager())
        monkeypatch.setattr(routes, "get_data_root", lambda: tmp_path)
        monkeypatch.setattr("biyu.ui.summarize._get_llm_adapter", lambda: pytest.fail("不得调用 LLM"))
        req = routes.SummarizeRequest(
            rejected=["不用方案甲，因为节奏慢"],
            unresolved=["结局开放或闭合"],
            taste_signals=["喜欢动作先于解释"],
        )
        result = await routes.post_summarize("sid-1", req)
        assert result["source"] == "editor"
        assert result["cost_cny"] == 0.0
        assert result["filename"] == "责编纪要.md"
        assert (tmp_path / "TestBook" / "summaries" / "责编纪要.md").exists()
