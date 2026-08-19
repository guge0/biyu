"""Tests for pipeline helpers (_parse_present_characters, _run_anchor_loop)."""
import asyncio
import csv
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from biyu.anchor_check import run_check_text
from biyu.config import BookConfig
from biyu.pipeline import (
    _parse_present_characters,
    _run_anchor_loop,
    _run_checklist_with_cost_log,
)


def test_run_checklist_with_cost_log_writes_six_column_row(tmp_path, monkeypatch):
    """F4 成功调用后必须写入唯一成本账，字段与其余阶段一致。"""
    result = MagicMock(cost_cny=0.0123)

    async def fake_run_and_save_checklist(**kwargs):
        return result, ["核对提醒"]

    monkeypatch.setattr(
        "biyu.checklist.run_and_save_checklist",
        fake_run_and_save_checklist,
    )
    book = BookConfig(tmp_path)
    returned, warnings = asyncio.run(
        _run_checklist_with_cost_log(
            book=book,
            book_dir=tmp_path,
            chapter_num=2,
            planning_text="planning",
            chapter_text="chapter",
            adapter=MagicMock(),
        )
    )

    assert returned is result
    assert warnings == ["核对提醒"]
    with book.cost_log_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["chapter"] == "2"
    assert rows[0]["stage"] == "checklist_f4"
    assert rows[0]["cost_cny"] == "0.0123"
    assert rows[0]["status"] == "ok"


class TestParsePresentCharacters:
    """Tests for _parse_present_characters: frontmatter parsing + fallback."""

    def test_frontmatter_present(self, tmp_path: Path):
        """YAML frontmatter with present_characters should be returned directly."""
        outline = """---
present_characters:
  - 张今空
  - 周大龙
  - 林溪
---

# 第1章
"""
        result = _parse_present_characters(outline, tmp_path)
        assert result == ["张今空", "周大龙", "林溪"]

    def test_no_frontmatter_no_truth_file(self, tmp_path: Path):
        """No frontmatter and no truth file → empty list."""
        outline = "# 第1章\n正文"
        result = _parse_present_characters(outline, tmp_path)
        assert result == []

    def test_fallback_strips_parentheses(self, tmp_path: Path):
        """Fallback should strip content after parentheses."""
        outline = "# 第1章\n正文"
        truth_dir = tmp_path / "truth_files"
        truth_dir.mkdir()
        (truth_dir / "current_state.md").write_text(
            "在场：赵天行（疑似杀母凶手）、张今空\n", encoding="utf-8"
        )
        result = _parse_present_characters(outline, tmp_path)
        assert result == ["赵天行", "张今空"]

    def test_fallback_strips_dash(self, tmp_path: Path):
        """Fallback should strip content after em-dash."""
        outline = "# 第1章\n正文"
        truth_dir = tmp_path / "truth_files"
        truth_dir.mkdir()
        (truth_dir / "current_state.md").write_text(
            "在场：林溪——成绩优异、周大龙\n", encoding="utf-8"
        )
        result = _parse_present_characters(outline, tmp_path)
        assert result == ["林溪", "周大龙"]

    def test_fallback_strips_period_annotation(self, tmp_path: Path):
        """Fallback should strip annotation after period within a name entry."""
        outline = "# 第1章\n正文"
        truth_dir = tmp_path / "truth_files"
        truth_dir.mkdir()
        (truth_dir / "current_state.md").write_text(
            "在场：张今空。、赵小磊。\n", encoding="utf-8"
        )
        result = _parse_present_characters(outline, tmp_path)
        assert result == ["张今空", "赵小磊"]

    def test_fallback_pure_name(self, tmp_path: Path):
        """Pure name without annotations passes through unchanged."""
        outline = "# 第1章\n正文"
        truth_dir = tmp_path / "truth_files"
        truth_dir.mkdir()
        (truth_dir / "current_state.md").write_text(
            "在场：张今空、周大龙、林溪\n", encoding="utf-8"
        )
        result = _parse_present_characters(outline, tmp_path)
        assert result == ["张今空", "周大龙", "林溪"]

    def test_fallback_mixed_annotations(self, tmp_path: Path):
        """Mixed annotations should all be stripped to just names."""
        outline = "# 第1章\n正文"
        truth_dir = tmp_path / "truth_files"
        truth_dir.mkdir()
        (truth_dir / "current_state.md").write_text(
            "在场：赵天行（疑似杀母凶手，左手有暗红色疤痕）,"
            "林溪——成绩优异，本书女主候选,张今空\n",
            encoding="utf-8",
        )
        result = _parse_present_characters(outline, tmp_path)
        assert result == ["赵天行", "林溪", "张今空"]


# ---------------------------------------------------------------------------
# CutA · _run_anchor_loop(P6-A2-CutA 早闸回流闭环,零成本 mock 验证)
# ---------------------------------------------------------------------------
# 接口: _run_anchor_loop(*, skeleton_text, anchors_yaml, chapter_id,
#                       writer_adapter, writer_call_fn, check_fn, book_dir,
#                       chapter_num, max_rounds=2, _log_cost_fn=None) ->
#         tuple[str, dict]
# 设计要点(见 specs/P6-A2-CutA.md):
# - 方案 b 事后修订: Stage 2 已写出 skeleton_text 后才跑回流, 初始 prompt 不污染
# - 2 轮硬上限(for round in range(max_rounds))
# - 不触发分支: miss+vm==0 直接返回 not_triggered, writer_call_fn 调 0 次
# - 不读旧章: 函数体只读 anchors_yaml, 无其他章节文件路径访问
# - 三通道标记: anchor_loop.json 落盘 + state dict 返回 + console print


def _make_anchors_yaml(tmp_path: Path, anchors: list[dict], chapter_id: str = "T1") -> Path:
    """构造最小 anchors.yaml 用于测试。每个 anchor dict 至少含 id/type/canonical。"""
    import yaml
    p = tmp_path / "anchors.yaml"
    data = {chapter_id: {"atomic": anchors}}
    p.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return p


def _resp(text: str, cost: float = 0.1):
    """构造 mock LLM response(鸭子类型,只需 .text 和 .cost)。"""
    m = MagicMock()
    m.text = text
    m.cost = cost
    return m


class TestRunAnchorLoopNoTrigger:
    """CutA-T1: 全 present skeleton → 不触发回流,writer_call_fn 调 0 次。"""

    def test_all_present_no_trigger(self, tmp_path: Path):
        anchors_yaml = _make_anchors_yaml(tmp_path, [
            {"id": "H01", "type": "role", "canonical": "张三"},
        ])
        skeleton = "正文里出现了张三这个角色。"  # canonical 在场

        async def writer_call_fn(messages, **kwargs):
            raise AssertionError("writer_call_fn 不应被调用(无触发)")

        log_calls: list[tuple] = []

        def mock_log_cost(*args, **kwargs):
            log_calls.append(args)

        result_text, state = asyncio.run(_run_anchor_loop(
            skeleton_text=skeleton,
            anchors_yaml=anchors_yaml,
            chapter_id="T1",
            writer_call_fn=writer_call_fn,
            check_fn=run_check_text,
            book_dir=tmp_path,
            chapter_num=1,
            _log_cost_fn=mock_log_cost,
        ))

        assert result_text == skeleton
        assert state["triggered"] is False
        assert state["loops"] == []
        assert state["final_status"] == "not_triggered"
        assert state["unresolved"] == []
        assert state["total_loop_cost"] == 0.0
        assert log_calls == []


class TestRunAnchorLoopOneRoundResolved:
    """CutA-T2: 初始 missing → Writer 修订 1 次 → 复查全 present → resolved。"""

    def test_one_round_resolved(self, tmp_path: Path):
        anchors_yaml = _make_anchors_yaml(tmp_path, [
            {"id": "H01", "type": "role", "canonical": "张三"},
        ])
        skeleton_initial = "正文没出现角色名。"  # canonical 不在场 → missing
        skeleton_fixed = "正文里出现了张三这个角色。"  # canonical 在场 → present

        # writer_call_fn 按顺序返回修订版(只该调 1 次)
        writer_calls: list[list[dict]] = []

        async def writer_call_fn(messages, **kwargs):
            writer_calls.append(messages)
            return _resp(skeleton_fixed, cost=0.12)

        result_text, state = asyncio.run(_run_anchor_loop(
            skeleton_text=skeleton_initial,
            anchors_yaml=anchors_yaml,
            chapter_id="T1",
            writer_call_fn=writer_call_fn,
            check_fn=run_check_text,
            book_dir=tmp_path,
            chapter_num=1,
        ))

        # Writer 调用恰好 1 次
        assert len(writer_calls) == 1
        # 返回的 skeleton 是修订版
        assert result_text == skeleton_fixed
        # state 反映 resolved
        assert state["triggered"] is True
        assert state["final_status"] == "resolved"
        assert state["unresolved"] == []
        assert len(state["loops"]) == 1
        loop = state["loops"][0]
        assert loop["round"] == 1
        assert loop["missing_before"] == 1
        assert loop["value_mismatch_before"] == 0
        assert loop["missing_after"] == 0
        assert loop["value_mismatch_after"] == 0
        assert loop["writer_cost"] == 0.12


class TestRunAnchorLoopTwoRoundHardCap:
    """CutA-T3: Writer 永远修订不到位 → 恰好 2 轮后放行, 不死循环。"""

    def test_two_round_hard_cap_unresolved(self, tmp_path: Path):
        anchors_yaml = _make_anchors_yaml(tmp_path, [
            {"id": "H01", "type": "role", "canonical": "张三"},
        ])
        skeleton_initial = "正文没出现角色名。"  # 触发 missing
        # Writer 永远返回仍有 missing 的 skeleton
        skeleton_bad = "正文仍未出现该角色名。"

        writer_calls: list[list[dict]] = []

        async def writer_call_fn(messages, **kwargs):
            writer_calls.append(messages)
            return _resp(skeleton_bad, cost=0.1)

        result_text, state = asyncio.run(_run_anchor_loop(
            skeleton_text=skeleton_initial,
            anchors_yaml=anchors_yaml,
            chapter_id="T1",
            writer_call_fn=writer_call_fn,
            check_fn=run_check_text,
            book_dir=tmp_path,
            chapter_num=1,
            max_rounds=2,
        ))

        # 关键断言: 恰好 2 次(不是 3 次或更多)
        assert len(writer_calls) == 2, (
            f"应恰好调 2 次(硬上限), 实际 {len(writer_calls)}"
        )
        assert state["triggered"] is True
        assert state["final_status"] == "unresolved"
        # unresolved 列表非空(还剩 H01 missing)
        assert len(state["unresolved"]) == 1
        assert state["unresolved"][0]["id"] == "H01"
        assert state["unresolved"][0]["status"] == "missing"
        # 两轮记录都在
        assert len(state["loops"]) == 2
        assert state["loops"][0]["round"] == 1
        assert state["loops"][1]["round"] == 2
        # 返回的 text 是最后一次修订版(放行, 不阻塞)
        assert result_text == skeleton_bad

    def test_hard_cap_prevents_infinite_loop(self, tmp_path: Path):
        """即使 max_rounds 设很大, 也不会因 Writer 原地踏步死循环。"""
        anchors_yaml = _make_anchors_yaml(tmp_path, [
            {"id": "H01", "type": "role", "canonical": "张三"},
        ])
        skeleton_initial = "正文没出现角色名。"
        skeleton_bad = "正文永不出现该角色名。"

        call_count = [0]

        async def writer_call_fn(messages, **kwargs):
            call_count[0] += 1
            return _resp(skeleton_bad, cost=0.1)

        _, state = asyncio.run(_run_anchor_loop(
            skeleton_text=skeleton_initial,
            anchors_yaml=anchors_yaml,
            chapter_id="T1",
            writer_call_fn=writer_call_fn,
            check_fn=run_check_text,
            book_dir=tmp_path,
            chapter_num=1,
            max_rounds=3,  # 设 3 但断言恰好 3, 不无限循环
        ))

        assert call_count[0] == 3, f"max_rounds=3 应恰好 3 次, 实际 {call_count[0]}"
        assert state["final_status"] == "unresolved"


class TestRunAnchorLoopStage2NotPolluted:
    """CutA-T4: 方案 b — Stage 2 初始 prompt 不被回流信号污染。

    双维度验证:
    1. 签名层面: _run_anchor_loop 不接受任何 Stage 2 prompt 参数
    2. 运行时: writer_call_fn 收到的 messages 只含回流 prompt(独立构造),
       不引用 v3/v4 system_prompt 关键字
    """

    def test_signature_rejects_stage2_prompt_params(self):
        """_run_anchor_loop 签名禁止任何 Stage 2 prompt 入口。"""
        import inspect
        sig = inspect.signature(_run_anchor_loop)
        forbidden = {
            "system_prompt", "stage2_prompt", "writer_system_prompt",
            "planning_messages", "stage2_messages", "initial_prompt",
        }
        actual = set(sig.parameters.keys())
        overlap = actual & forbidden
        assert overlap == set(), (
            f"_run_anchor_loop 不应接受 Stage 2 prompt 参数, "
            f"但签名含: {overlap}"
        )

    def test_loop_prompt_is_independent_from_stage2(self, tmp_path: Path):
        """writer_call_fn 收到的 messages 是独立回流 prompt, 不含 v4 Layer1/v3 system 标志。"""
        anchors_yaml = _make_anchors_yaml(tmp_path, [
            {"id": "H01", "type": "role", "canonical": "张三"},
        ])
        skeleton_initial = "正文没出现角色名。"
        skeleton_fixed = "正文里出现了张三。"

        captured_messages: list[list[dict]] = []

        async def writer_call_fn(messages, **kwargs):
            captured_messages.append(messages)
            return _resp(skeleton_fixed, cost=0.1)

        asyncio.run(_run_anchor_loop(
            skeleton_text=skeleton_initial,
            anchors_yaml=anchors_yaml,
            chapter_id="T1",
            writer_call_fn=writer_call_fn,
            check_fn=run_check_text,
            book_dir=tmp_path,
            chapter_num=1,
        ))

        assert len(captured_messages) == 1, "本轮应只调 1 次"
        messages = captured_messages[0]

        # 回流 prompt 结构: 单条 user message, 无 system role
        assert len(messages) == 1, "回流应只发 user message(无 system)"
        assert messages[0]["role"] == "user"

        content = messages[0]["content"]

        # 必须含回流 prompt 的标志(由 _build_anchor_loop_prompt 产生)
        assert "硬信息" in content, "回流 prompt 必须含 '硬信息' 标志"
        assert "=== 原正文 ===" in content, "回流 prompt 必须含原正文分隔符"
        assert "张三" in content, "回流 prompt 必须列出缺失的 canonical"

        # 必须不含 Stage 2 v4/v3 system_prompt 的标志
        stage2_markers = [
            "Layer 1", "Layer1", "硬规则",  # v4 LAYER1
            "Layer 2", "Layer2",
            "你是一个写作助手",  # v3 system 通用开头
            "现在开始写第",  # v4 dynamic_content 尾巴
        ]
        for marker in stage2_markers:
            assert marker not in content, (
                f"回流 prompt 不应含 Stage 2 标志 '{marker}'(方案 b 不污染)"
            )

    def test_loop_prompt_round_2_marks_repeat(self, tmp_path: Path):
        """第 2 轮 prompt 含 '上一轮已要求' 防重复犯错提示。"""
        anchors_yaml = _make_anchors_yaml(tmp_path, [
            {"id": "H01", "type": "role", "canonical": "张三"},
        ])
        skeleton_initial = "正文没出现角色名。"
        skeleton_bad = "正文仍没出现该角色。"

        captured: list[str] = []

        async def writer_call_fn(messages, **kwargs):
            captured.append(messages[0]["content"])
            return _resp(skeleton_bad, cost=0.1)

        asyncio.run(_run_anchor_loop(
            skeleton_text=skeleton_initial,
            anchors_yaml=anchors_yaml,
            chapter_id="T1",
            writer_call_fn=writer_call_fn,
            check_fn=run_check_text,
            book_dir=tmp_path,
            chapter_num=1,
            max_rounds=2,
        ))

        assert len(captured) == 2
        # 第 1 轮: 不含"上一轮"
        assert "第 1 轮" in captured[0]
        assert "上一轮" not in captured[0]
        # 第 2 轮: 含"上一轮已要求"
        assert "第 2 轮" in captured[1]
        assert "上一轮" in captured[1]


class TestRunAnchorLoopNoReadOtherChapters:
    """CutA-T5: 隔离硬约束 — _run_anchor_loop 绝不读当前章以外的文件。

    监控 _run_anchor_loop 执行期间所有 open() 调用;断言只有 anchors.yaml 被读,
    故意放置的旧章节正文文件 / 其他章 anchors 都没被读。
    """

    def test_does_not_read_chapter_files(self, tmp_path: Path, monkeypatch):
        import builtins

        # 准备: 当前章 anchors + 故意放置的"旧章正文"陷阱
        anchors_yaml = _make_anchors_yaml(tmp_path, [
            {"id": "H01", "type": "role", "canonical": "张三"},
        ])

        # 陷阱 1: 旧章节正文文件(不应被读)
        chapters_dir = tmp_path / "chapters"
        chapters_dir.mkdir()
        old_ch1 = chapters_dir / "ch1.md"
        old_ch1.write_text("# 第1章\n这是旧章节正文, 不应被回流读。", encoding="utf-8")
        old_ch2 = chapters_dir / "ch2.md"
        old_ch2.write_text("# 第2章\n另一旧章。", encoding="utf-8")

        # 陷阱 2: 其他章 anchors(不应被读)
        other_anchors = tmp_path / "anchors_other.yaml"
        other_anchors.write_text("T2:\n  atomic: []", encoding="utf-8")

        skeleton_initial = "正文没出现角色名。"
        skeleton_fixed = "正文里出现了张三。"

        async def writer_call_fn(messages, **kwargs):
            return _resp(skeleton_fixed, cost=0.1)

        # 监控 _run_anchor_loop 执行期间所有 open 调用
        reads_during_loop: list[str] = []
        original_open = builtins.open

        def spy_open(file, *args, **kwargs):
            reads_during_loop.append(str(file))
            return original_open(file, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", spy_open)

        # 清掉 setattr 前的调用, 只计 asyncio.run 期间
        reads_during_loop.clear()

        asyncio.run(_run_anchor_loop(
            skeleton_text=skeleton_initial,
            anchors_yaml=anchors_yaml,
            chapter_id="T1",
            writer_call_fn=writer_call_fn,
            check_fn=run_check_text,
            book_dir=tmp_path,
            chapter_num=1,
        ))

        # 断言 1: 故意放置的陷阱文件没被读
        trap_files = {str(old_ch1), str(old_ch2), str(other_anchors)}
        trap_reads = [r for r in reads_during_loop if r in trap_files]
        assert trap_reads == [], (
            f"_run_anchor_loop 不应读旧章/其他 anchors, 但读了: {trap_reads}"
        )

        # 断言 2: anchors.yaml 被读(check_fn 需要)
        anchors_reads = [r for r in reads_during_loop if str(anchors_yaml) in r]
        assert len(anchors_reads) > 0, (
            f"anchors.yaml 应被读(check_fn 需要), 实际 reads: {reads_during_loop}"
        )


class TestRunAnchorLoopThreeChannelMarker:
    """CutA-T6: 三通道标记 — 落盘 + state + console, 任一通道丢失另两个可互查。"""

    def test_unresolved_three_channels_all_present(self, tmp_path: Path, capsys):
        anchors_yaml = _make_anchors_yaml(tmp_path, [
            {"id": "H01", "type": "role", "canonical": "张三"},
        ])
        skeleton_initial = "正文没出现角色名。"
        skeleton_bad = "正文仍没出现该角色。"

        async def writer_call_fn(messages, **kwargs):
            return _resp(skeleton_bad, cost=0.1)

        _, state = asyncio.run(_run_anchor_loop(
            skeleton_text=skeleton_initial,
            anchors_yaml=anchors_yaml,
            chapter_id="T1",
            writer_call_fn=writer_call_fn,
            check_fn=run_check_text,
            book_dir=tmp_path,
            chapter_num=1,
            max_rounds=2,
        ))

        # 通道 1: state(供 caller 写 meta.json)
        assert state["final_status"] == "unresolved"
        assert len(state["unresolved"]) == 1
        assert state["unresolved"][0]["id"] == "H01"

        # 通道 2: anchor_loop.json 落盘
        loop_json = tmp_path / "logs" / "ch1" / "anchor_loop.json"
        assert loop_json.exists(), f"anchor_loop.json 应落盘于 {loop_json}"
        data = json.loads(loop_json.read_text(encoding="utf-8"))
        assert data["final_status"] == "unresolved"
        assert len(data["unresolved"]) == 1
        assert data["unresolved"][0]["id"] == "H01"
        assert len(data["loops"]) == 2

        # 通道 3: console 报警(capsys 捕获)
        out = capsys.readouterr().out
        assert "硬信息" in out, "console 应含'硬信息'字样"
        assert "2 轮" in out, "console 应含轮数'2 轮'"
        assert "未解决" in out or "人工处理" in out, (
            f"console 应含'未解决/人工处理'报警, 实际: {out!r}"
        )

    def test_resolved_no_alarm_in_console(self, tmp_path: Path, capsys):
        """resolved 场景不打印'未解决'报警。"""
        anchors_yaml = _make_anchors_yaml(tmp_path, [
            {"id": "H01", "type": "role", "canonical": "张三"},
        ])
        skeleton_initial = "正文没出现角色名。"
        skeleton_fixed = "正文里出现了张三。"

        async def writer_call_fn(messages, **kwargs):
            return _resp(skeleton_fixed, cost=0.1)

        asyncio.run(_run_anchor_loop(
            skeleton_text=skeleton_initial,
            anchors_yaml=anchors_yaml,
            chapter_id="T1",
            writer_call_fn=writer_call_fn,
            check_fn=run_check_text,
            book_dir=tmp_path,
            chapter_num=1,
        ))

        out = capsys.readouterr().out
        assert "未解决" not in out, "resolved 不应报警"
        assert "人工处理" not in out

    def test_per_round_reports_dropped(self, tmp_path: Path):
        """每轮复查报告落盘 anchor_loop_round_N.json(便于追溯每轮信号)。"""
        anchors_yaml = _make_anchors_yaml(tmp_path, [
            {"id": "H01", "type": "role", "canonical": "张三"},
        ])
        skeleton_initial = "正文没出现角色名。"
        skeleton_bad = "正文仍没出现该角色。"

        async def writer_call_fn(messages, **kwargs):
            return _resp(skeleton_bad, cost=0.1)

        asyncio.run(_run_anchor_loop(
            skeleton_text=skeleton_initial,
            anchors_yaml=anchors_yaml,
            chapter_id="T1",
            writer_call_fn=writer_call_fn,
            check_fn=run_check_text,
            book_dir=tmp_path,
            chapter_num=1,
            max_rounds=2,
        ))

        log_dir = tmp_path / "logs" / "ch1"
        round1 = log_dir / "anchor_loop_round_1.json"
        round2 = log_dir / "anchor_loop_round_2.json"
        assert round1.exists(), "round 1 报告应落盘"
        assert round2.exists(), "round 2 报告应落盘"

        # 每轮报告是当轮 check_fn 的输出
        r1 = json.loads(round1.read_text(encoding="utf-8"))
        assert r1["chapter"] == "T1"
        assert "atomic_results" in r1


class TestRunAnchorLoopCostLogging:
    """CutA-T7: 每轮 Writer 修订调用成本记入 cost_log 阶段名 'writer_anchor_loop'。"""

    def test_cost_logged_with_correct_stage_name(self, tmp_path: Path):
        anchors_yaml = _make_anchors_yaml(tmp_path, [
            {"id": "H01", "type": "role", "canonical": "张三"},
        ])
        skeleton_initial = "正文没出现角色名。"
        skeleton_bad = "正文仍没出现该角色。"

        async def writer_call_fn(messages, **kwargs):
            return _resp(skeleton_bad, cost=0.15)

        # 注入 mock _log_cost_fn(签名: stage, cost, latency)
        log_calls: list[tuple] = []

        def mock_log_cost(stage, cost, latency):
            log_calls.append((stage, cost, latency))

        _, state = asyncio.run(_run_anchor_loop(
            skeleton_text=skeleton_initial,
            anchors_yaml=anchors_yaml,
            chapter_id="T1",
            writer_call_fn=writer_call_fn,
            check_fn=run_check_text,
            book_dir=tmp_path,
            chapter_num=1,
            max_rounds=2,
            _log_cost_fn=mock_log_cost,
        ))

        # 2 轮 = 2 次 _log_cost 调用
        assert len(log_calls) == 2, f"应有 2 次成本记录, 实际 {len(log_calls)}"

        # 阶段名正确
        for stage, _, _ in log_calls:
            assert stage == "writer_anchor_loop", (
                f"阶段名应为 'writer_anchor_loop', 实际 '{stage}'"
            )

        # 成本累加正确(每次 0.15)
        costs = [c for _, c, _ in log_calls]
        assert costs == [0.15, 0.15]
        assert state["total_loop_cost"] == 0.30

        # latency 是非负数(实测会测)
        for _, _, lat in log_calls:
            assert lat >= 0.0

    def test_no_log_cost_fn_skips_logging(self, tmp_path: Path):
        """_log_cost_fn=None 时不报错(测试默认行为)。"""
        anchors_yaml = _make_anchors_yaml(tmp_path, [
            {"id": "H01", "type": "role", "canonical": "张三"},
        ])
        skeleton_initial = "正文没出现角色名。"
        skeleton_fixed = "正文里出现了张三。"

        async def writer_call_fn(messages, **kwargs):
            return _resp(skeleton_fixed, cost=0.1)

        # 不传 _log_cost_fn, 不应报错
        result_text, state = asyncio.run(_run_anchor_loop(
            skeleton_text=skeleton_initial,
            anchors_yaml=anchors_yaml,
            chapter_id="T1",
            writer_call_fn=writer_call_fn,
            check_fn=run_check_text,
            book_dir=tmp_path,
            chapter_num=1,
        ))
        assert state["final_status"] == "resolved"


class TestCutAApplyPipelineAdapter:
    """CutA-T8: _cut_a_apply 是 _run_anchor_loop 接入 generate_chapter 的辅助函数。

    职责: ① 绑定 writer_adapter 成 writer_call_fn(用 _call_with_retry);
    ② 绑定 book/chapter 成 _log_cost_fn(用 _log_cost); ③ 异常不阻塞
    (放行原 skeleton + state.final_status="error" + warning)。
    """

    def test_no_anchors_yaml_returns_default_state(self, tmp_path: Path):
        """anchors.yaml 不存在 → 不触发, 返回默认 state(不阻塞管线)。"""
        from biyu.pipeline import _cut_a_apply

        # BookConfig 仅需 book_dir(__init__ 不读 book.json)
        from biyu.config import BookConfig
        book = BookConfig(tmp_path)

        async def writer_call(messages, **kwargs):
            raise AssertionError("不应调 Writer")

        result_text, state = asyncio.run(_cut_a_apply(
            skeleton_text="原 skeleton",
            anchors_yaml=tmp_path / "nonexistent.yaml",  # 不存在
            chapter_id="T1",
            writer_adapter=None,
            book=book,
            book_dir=tmp_path,
            chapter_num=1,
        ))

        assert result_text == "原 skeleton"
        assert state["final_status"] == "not_triggered"
        assert state["triggered"] is False

    def test_writer_exception_does_not_block_pipeline(self, tmp_path: Path):
        """Writer adapter 抛异常 → _cut_a_apply 放行原 skeleton, 标 error。"""
        from biyu.pipeline import _cut_a_apply
        from biyu.config import BookConfig

        anchors_yaml = _make_anchors_yaml(tmp_path, [
            {"id": "H01", "type": "role", "canonical": "张三"},
        ])
        book = BookConfig(tmp_path)
        skeleton_initial = "正文没出现角色名。"

        # Writer adapter 抛异常
        writer_adapter = MagicMock()
        writer_adapter.generate = MagicMock(side_effect=RuntimeError("模拟 Writer 故障"))

        result_text, state = asyncio.run(_cut_a_apply(
            skeleton_text=skeleton_initial,
            anchors_yaml=anchors_yaml,
            chapter_id="T1",
            writer_adapter=writer_adapter,
            book=book,
            book_dir=tmp_path,
            chapter_num=1,
        ))

        # 异常不阻塞: 返回原 skeleton + state 标 error
        assert result_text == skeleton_initial
        assert state["final_status"] == "error"
        assert "error" in state
        assert "模拟 Writer 故障" in state["error"]

    def test_normal_path_calls_run_anchor_loop(self, tmp_path: Path):
        """正常路径: 触发回流, 返回修订 skeleton + resolved state。"""
        from biyu.pipeline import _cut_a_apply
        from biyu.config import BookConfig

        anchors_yaml = _make_anchors_yaml(tmp_path, [
            {"id": "H01", "type": "role", "canonical": "张三"},
        ])
        book = BookConfig(tmp_path)
        skeleton_initial = "正文没出现角色名。"
        skeleton_fixed = "正文里出现了张三。"

        # Writer adapter 正常返回修订版(AsyncMock 支持 await)
        writer_adapter = MagicMock()
        writer_adapter.generate = AsyncMock(return_value=_resp(skeleton_fixed, cost=0.1))

        result_text, state = asyncio.run(_cut_a_apply(
            skeleton_text=skeleton_initial,
            anchors_yaml=anchors_yaml,
            chapter_id="T1",
            writer_adapter=writer_adapter,
            book=book,
            book_dir=tmp_path,
            chapter_num=1,
        ))

        assert result_text == skeleton_fixed
        assert state["final_status"] == "resolved"
        # 成本日志写入 cost_log.csv(_cut_a_apply 内部用 _log_cost)
        cost_log = tmp_path / "logs" / "cost_log.csv"
        assert cost_log.exists()
        content = cost_log.read_text(encoding="utf-8")
        assert "writer_anchor_loop" in content
