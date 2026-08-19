"""Tests for biyu.cli.propose_cmd — P7-2 三路径端到端.

覆盖 T7:
- --idea 不传 → EMPTY 路径(无 redblue)
- --idea "校车..." → SPECIFIC 路径(含 redblue)
- --idea "想写穿越的" → DIRECTIONAL 路径(无 redblue)
- 三路径 cost_log 都正确写入(stage 含 router/tropes/redblue/craft)
- 命令不依赖 book.json
- 命令产出 Markdown 落盘到 data/<name>/proposal/

所有 LLM / scan 通过 mock,零烧钱。
"""
from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from biyu.cli.main import app
from biyu.propose.scanner import BookEntry, PlatformResult


runner = CliRunner()


class TestWriteCliReplanForwarding:
    """R1-1c：main.write → write_command 的 replan 透传契约。"""

    @staticmethod
    def _install_capture(monkeypatch):
        captured = {}

        def fake_write_command(**kwargs):
            captured.update(kwargs)

        monkeypatch.setattr("biyu.cli.write_cmd.write_command", fake_write_command)
        return captured

    def test_write_default_forwards_bool_false(self, monkeypatch):
        captured = self._install_capture(monkeypatch)

        result = runner.invoke(app, ["write", "-c", "99", "-b", "probe-book"])

        assert result.exit_code == 0, result.output
        assert type(captured["replan"]) is bool
        assert captured["replan"] is False

    def test_write_replan_flag_forwards_bool_true(self, monkeypatch):
        captured = self._install_capture(monkeypatch)

        result = runner.invoke(
            app,
            ["write", "-c", "99", "-b", "probe-book", "--replan"],
        )

        assert result.exit_code == 0, result.output
        assert type(captured["replan"]) is bool
        assert captured["replan"] is True

    def test_write_runner_and_direct_call_match(self, monkeypatch):
        from biyu.cli.main import write as write_entry

        captured = self._install_capture(monkeypatch)
        runner_result = runner.invoke(app, ["write", "-c", "99", "-b", "probe-book"])
        runner_replan = captured["replan"]

        captured.clear()
        write_entry(
            chapter=99,
            book="probe-book",
            planner=None,
            writer=None,
            polisher=None,
            prompt_version="v4",
            replan=False,
        )

        assert runner_result.exit_code == 0, runner_result.output
        assert captured["replan"] is runner_replan is False


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _make_book(i: int, platform: str) -> BookEntry:
    return BookEntry(
        rank=i, title=f"书{i}", author=f"作者{i}", category="玄幻",
        word_count="100万字", url=f"https://x.com/{platform}/{i}", abstract=f"简介{i}。",
    )


# 各 prompt 的合法响应
_TROPES_JSON = (
    '{"hot_genres": ['
    '{"genre": "都市异能", "heat_signal": "起点都市榜前 10 占 3 本", '
    '"sample_titles": ["书1", "书2", "书3"]}'
    '], "hot_tropes": ["系统流+吐槽"], '
    '"market_summary": "近期都市异能占主导。"}'
)

_REDBLUE_JSON = (
    '{"supply_crowding": "校车+秘境题材在榜较拥挤。", '
    '"demand_weak_signal": "榜上同类位次靠前。", '
    '"quadrant": "红海"}'
)

_CRAFT_JSON = (
    '{"rhythm": "每章一小高潮。", "goals": "三层目标体系。", '
    '"cool_points": "暧昧/情为主。", "opening": "凤头+双伏笔。", '
    '"dimensions": "脸面/基础/开头。"}'
)


class _MockAdapter:
    """Mock LLM adapter — 根据 prompt 内容返不同响应(router/tropes/redblue/craft)。"""

    def __init__(self, router_response: str = "specific"):
        self._router_response = router_response
        self.calls: list = []

    async def generate(self, messages, **kwargs):
        self.calls.append(messages)
        # 拼 system+user 内容做模式识别
        blob = "".join(m.get("content", "") or "" for m in messages)

        # 注意:顺序很重要 —— redblue prompt 含"红蓝海对照分析师",
        # 别和 craft 的"创作规律顾问"混;router 含"思路分类器"
        if "思路分类器" in blob or "specific / directional / empty" in blob:
            text = self._router_response
        elif "套路归纳器" in blob or "hot_genres" in blob:
            text = _TROPES_JSON
        elif "红蓝海对照分析师" in blob or "supply_crowding" in blob:
            text = _REDBLUE_JSON
        elif "创作规律顾问" in blob or "rhythm" in blob:
            text = _CRAFT_JSON
        else:
            text = "{}"  # fallback

        class _R:
            cost = 0.001

        r = _R()
        r.text = text
        return r


def _mock_scan_all(platforms, fetchers=None, limit=20):
    return {
        p: PlatformResult(
            platform=p, success=True,
            books=[_make_book(i + 1, p) for i in range(5)],
            fetched_at="2026-06-30T10:00:00+00:00",
            source_url=f"https://x.com/{p}",
        )
        for p in platforms
    }


def _apply_common_mocks(monkeypatch, tmp_path: Path, router_response: str = "specific"):
    """重定向 data_root + mock 扫榜 + mock LLM。"""
    monkeypatch.setattr("biyu.cli.propose_cmd.get_data_root", lambda: tmp_path)
    monkeypatch.setattr("biyu.cli.propose_cmd.scan_all", _mock_scan_all)
    monkeypatch.setattr(
        "biyu.cli.propose_cmd.get_llm_adapter",
        lambda model_alias: _MockAdapter(router_response=router_response),
    )


# ---------------------------------------------------------------------------
# T7: 三路径端到端
# ---------------------------------------------------------------------------


def test_propose_command_empty_idea_goes_empty_path(tmp_path: Path, monkeypatch):
    """--idea 不传 → P9-C1 早期拒绝(空输入直接退出,¥0)。"""
    _apply_common_mocks(monkeypatch, tmp_path, router_response="empty")

    result = runner.invoke(app, [
        "propose",
        # 不传 --idea
        "--name", "test_empty_path",
    ])

    assert result.exit_code == 0, f"CLI failed: {result.output}"
    # P9-C1: 空输入被拒绝,不应有任何产出
    proposal_dir = tmp_path / "test_empty_path" / "proposal"
    assert not proposal_dir.exists()


def test_propose_command_specific_idea_goes_specific_path_with_redblue(tmp_path: Path, monkeypatch):
    """--idea "校车..." → SPECIFIC 路径(含红蓝海对照)。"""
    _apply_common_mocks(monkeypatch, tmp_path, router_response="specific")

    result = runner.invoke(app, [
        "propose",
        "--idea", "校车进秘境、轻喜剧爽文",
        "--name", "test_specific_path",
    ])

    assert result.exit_code == 0, f"CLI failed: {result.output}"
    md_files = list((tmp_path / "test_specific_path" / "proposal").glob("proposal_*.md"))
    assert len(md_files) == 1
    md = md_files[0].read_text(encoding="utf-8")
    # SPECIFIC 路径
    assert "红蓝海对照" in md
    assert "象限定性" in md  # 红蓝海象限结论
    # 诚实声明
    assert "需求侧" in md
    assert "不可得" in md


def test_propose_command_directional_idea_goes_directional_path(tmp_path: Path, monkeypatch):
    """--idea "想写穿越的" → DIRECTIONAL 路径(无 redblue)。"""
    _apply_common_mocks(monkeypatch, tmp_path, router_response="directional")

    result = runner.invoke(app, [
        "propose",
        "--idea", "想写穿越的",
        "--name", "test_directional_path",
    ])

    assert result.exit_code == 0, f"CLI failed: {result.output}"
    md_files = list((tmp_path / "test_directional_path" / "proposal").glob("proposal_*.md"))
    assert len(md_files) == 1
    md = md_files[0].read_text(encoding="utf-8")
    # DIRECTIONAL 路径
    assert "方向归纳" in md or "半方向" in md
    # 不出现红蓝海对照节
    assert "核心判断:红蓝海对照" not in md


# ---------------------------------------------------------------------------
# cost_log 验证
# ---------------------------------------------------------------------------


def test_propose_command_cost_log_has_expected_stages_for_specific_path(
    tmp_path: Path, monkeypatch
):
    """SPECIFIC 路径:cost_log 含 router / tropes / redblue / craft 四 stage。"""
    _apply_common_mocks(monkeypatch, tmp_path, router_response="specific")

    result = runner.invoke(app, [
        "propose",
        "--idea", "校车进秘境",
        "--name", "cost_specific",
    ])
    assert result.exit_code == 0

    cost_log = tmp_path / "cost_specific" / "logs" / "cost_log.csv"
    assert cost_log.exists()
    content = cost_log.read_text(encoding="utf-8")
    # 四个 stage 都该出现
    assert "router" in content
    assert "tropes" in content
    assert "redblue" in content
    assert "craft" in content


def test_propose_command_cost_log_no_redblue_for_empty_path(tmp_path: Path, monkeypatch):
    """P9-C1 空输入早期拒绝:cost_log 不存在(因流程被剪断)。"""
    _apply_common_mocks(monkeypatch, tmp_path, router_response="empty")

    result = runner.invoke(app, [
        "propose",
        # 不传 --idea
        "--name", "cost_empty",
    ])
    assert result.exit_code == 0

    # P9-C1: 空输入被早期拒绝,无任何流程,无成本日志
    cost_log = tmp_path / "cost_empty" / "logs" / "cost_log.csv"
    assert not cost_log.exists()


def test_propose_command_cost_log_no_redblue_for_directional_path(tmp_path: Path, monkeypatch):
    """DIRECTIONAL 路径:cost_log 不含 redblue,但含 router(DIRECTIONAL 走 LLM 判断)。"""
    _apply_common_mocks(monkeypatch, tmp_path, router_response="directional")

    result = runner.invoke(app, [
        "propose",
        "--idea", "想写穿越的",
        "--name", "cost_directional",
    ])
    assert result.exit_code == 0

    cost_log = tmp_path / "cost_directional" / "logs" / "cost_log.csv"
    content = cost_log.read_text(encoding="utf-8")
    assert "redblue" not in content
    assert "router" in content  # DIRECTIONAL 用了 LLM 判断
    assert "tropes" in content
    assert "craft" in content


# ---------------------------------------------------------------------------
# 不依赖 book.json
# ---------------------------------------------------------------------------


def test_propose_command_does_not_require_book_json(tmp_path: Path, monkeypatch):
    """propose 在 data/ 下没有 book.json 时也能跑(开书前场景)。"""
    _apply_common_mocks(monkeypatch, tmp_path, router_response="specific")

    # tmp_path 下没有任何 book.json
    assert not list(tmp_path.glob("**/book.json"))

    result = runner.invoke(app, [
        "propose",
        "--idea", "校车",
        "--name", "no_book_json",
    ])

    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# 产出落盘 + 形态
# ---------------------------------------------------------------------------


def test_propose_command_writes_markdown_to_correct_path(tmp_path: Path, monkeypatch):
    """产出 Markdown 落盘到 data/<name>/proposal/proposal_<时间戳>.md。"""
    _apply_common_mocks(monkeypatch, tmp_path, router_response="specific")

    result = runner.invoke(app, [
        "propose",
        "--idea", "校车进秘境",
        "--name", "e2e_path",
    ])

    assert result.exit_code == 0
    proposal_dir = tmp_path / "e2e_path" / "proposal"
    assert proposal_dir.exists()
    md_files = list(proposal_dir.glob("proposal_*.md"))
    assert len(md_files) == 1
    md = md_files[0].read_text(encoding="utf-8")
    # 五节关键词(P7-2 新结构)
    assert "校车进秘境" in md
    assert "核心判断" in md
    assert "市场套路归纳" in md
    assert "创作规律" in md
    assert "诚实边界" in md


def test_propose_command_prints_output_path(tmp_path: Path, monkeypatch):
    """命令结束时把产出路径打给作者。"""
    _apply_common_mocks(monkeypatch, tmp_path, router_response="specific")

    result = runner.invoke(app, [
        "propose", "--idea", "x", "--name", "print_path",
    ])

    assert result.exit_code == 0
    assert "proposal" in result.output
    assert ".md" in result.output


# ---------------------------------------------------------------------------
# 两平台都失败时仍产出
# ---------------------------------------------------------------------------


def test_propose_command_continues_when_all_platforms_fail(tmp_path: Path, monkeypatch):
    """两平台都失败时仍产出立项书(仅创作规律 + 标注数据缺失)。"""
    monkeypatch.setattr("biyu.cli.propose_cmd.get_data_root", lambda: tmp_path)

    def mock_scan_all_fail(platforms, fetchers=None, limit=20):
        return {
            p: PlatformResult(
                platform=p, success=False, error="network down",
                fetched_at="2026-06-30T10:00:00+00:00",
                source_url=f"https://x.com/{p}",
            )
            for p in platforms
        }
    monkeypatch.setattr("biyu.cli.propose_cmd.scan_all", mock_scan_all_fail)
    monkeypatch.setattr(
        "biyu.cli.propose_cmd.get_llm_adapter",
        lambda model_alias: _MockAdapter(router_response="specific"),
    )

    result = runner.invoke(app, [
        "propose", "--idea", "校车", "--name", "all_fail",
    ])

    assert result.exit_code == 0
    md_files = list((tmp_path / "all_fail" / "proposal").glob("proposal_*.md"))
    assert len(md_files) == 1
    md = md_files[0].read_text(encoding="utf-8")
    assert "失败" in md or "缺失" in md
    # 创作规律节仍在
    assert "创作规律" in md
