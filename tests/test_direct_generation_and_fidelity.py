"""2026-10 三件套:保真闸 / 跳过导演 / 声纹取消。

- 保真闸:机械层抓丢人名丢数字;LLM 剧情层判定;不合格带罪状重试一次,仍败拒收
  (fidelity_issues 随拒收状态落盘);判定调用失败 fail-open 不拦主流程
- 跳过导演:章节级开关→写闸放行→执行器带 --skip-planning→管线细纲直生成
- 声纹取消:selection PUT null 合法,active 归 None
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest


VALID_PLAN = """# 第九章 创作者细纲

## 必检项
- **必须发生**：姜聆当众复述登记簿结论
- **必须不发生**：不揭晓回溯原因
- **结尾状态**：马文把封存刀放上验尸台
- **信息层级**：先公开追问，再私下识刀
"""


def _book(tmp_path: Path, outline: str = "第九章细纲") -> Path:
    book = tmp_path / "Book"
    (book / "outlines").mkdir(parents=True)
    (book / "logs" / "ch9").mkdir(parents=True)
    (book / "book.json").write_text('{"id":"book","title":"Book","genre":"dushi"}', encoding="utf-8")
    (book / "outlines" / "ch9.md").write_text(outline, encoding="utf-8")
    return book


class _FakeResult:
    def __init__(self, text: str) -> None:
        self.text = text
        self.cost = 0.0
        self.status = "ok"


# ---------- 保真闸·机械层 ----------

def test_hard_fact_layer_flags_missing_names_and_numbers() -> None:
    from biyu.ui.workbench import _outline_hard_fact_issues

    outline = "# 第九章\n## 出场人物\n姜聆（法医）、马文（队长）\n1. 当众复述结论,四十三份记录\n"
    plan = "常野夜醒。"
    issues = _outline_hard_fact_issues(outline, plan)
    assert any("姜聆" in item for item in issues)
    assert any("四十三" in item for item in issues)

    full_plan = "姜聆当众复述,四十三份记录,马文在场。"
    assert _outline_hard_fact_issues(outline, full_plan) == []


# ---------- 保真闸·完整流程 ----------

@pytest.fixture
def fidelity_book(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from biyu.ui import workbench

    outline = (
        "# 第九章\n## 出场人物\n姜聆（法医）\n"
        "1. 姜聆当众复述登记簿结论\n2. 马文把封存刀放上验尸台\n"
    )
    book = _book(tmp_path, outline)
    monkeypatch.setattr(workbench, "_book_dir", lambda _b: book)
    monkeypatch.setattr(workbench, "_web_architect_enabled", lambda: True)
    return book


class _Registry:
    def get_feature(self, _name: str) -> bool:
        return False

    def get_adapter_for_stage(self, stage: str):
        class _P:
            max_tokens = 8192

        return _P()


def test_fidelity_gate_retries_with_feedback_then_accepts(
    fidelity_book: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """第一版丢人名→带罪状重试→第二版合格→落盘,流程不拒收。"""
    from biyu.ui import workbench

    good = VALID_PLAN + "\n姜聆当众复述登记簿结论。"
    bad = "马文一个人忙了一整章。"
    calls: list[str] = []

    async def fake_call(book_dir, chapter, feedback=""):
        calls.append(feedback)
        return _FakeResult(bad if len(calls) == 1 else good)

    async def fake_judge(outline, plan, registry, book, chapter):
        return ([], 0.0)

    monkeypatch.setattr(workbench, "_call_web_architect", fake_call)
    monkeypatch.setattr(workbench, "_judge_outline_coverage", fake_judge)
    monkeypatch.setattr(workbench, "get_registry", lambda: _Registry())

    result = asyncio.run(workbench.generate_planning_with_architect("Book", 9))
    assert result["state"] == "draft"
    assert len(calls) == 2
    assert "姜聆" in calls[1]  # 重试反馈带具体罪状
    written = (fidelity_book / "logs" / "ch9" / "planning.md").read_text(encoding="utf-8")
    assert "status: 待批" in written


def test_fidelity_gate_rejects_after_failed_retry(
    fidelity_book: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from biyu.ui import workbench

    bad = "马文一个人忙了一整章。"

    async def fake_call(book_dir, chapter, feedback=""):
        return _FakeResult(bad)

    async def fake_judge(outline, plan, registry, book, chapter):
        return ([], 0.0)

    monkeypatch.setattr(workbench, "_call_web_architect", fake_call)
    monkeypatch.setattr(workbench, "_judge_outline_coverage", fake_judge)
    monkeypatch.setattr(workbench, "get_registry", lambda: _Registry())

    result = asyncio.run(workbench.generate_planning_with_architect("Book", 9))
    assert result["state"] == "rejected"
    assert any("姜聆" in item for item in result["fidelity_issues"])
    # 拒收原文随状态落盘(拒收版可读)
    state = workbench._read_architect_state(fidelity_book, 9)
    assert state["state"] == "rejected"
    assert state["text"] == bad


def test_fidelity_gate_fail_open_on_judge_crash(
    fidelity_book: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """判定模型崩了不能拦死创作:机械层放行即放行。"""
    from biyu.ui import workbench

    text = VALID_PLAN + "\n姜聆当众复述登记簿结论。"

    async def fake_call(book_dir, chapter, feedback=""):
        return _FakeResult(text)

    async def boom(*_args, **_kwargs):
        raise RuntimeError("judge down")

    monkeypatch.setattr(workbench, "_call_web_architect", fake_call)
    monkeypatch.setattr(workbench, "_judge_outline_coverage", boom)
    monkeypatch.setattr(workbench, "get_registry", lambda: _Registry())

    result = asyncio.run(workbench.generate_planning_with_architect("Book", 9))
    assert result["state"] == "draft"


# ---------- 跳过导演 ----------

def test_planning_mode_route_requires_outline(tmp_path, monkeypatch) -> None:
    from fastapi import HTTPException

    from biyu.ui import workbench

    book = _book(tmp_path)
    (book / "outlines" / "ch9.md").unlink()
    monkeypatch.setattr(workbench, "_book_dir", lambda _b: book)
    with pytest.raises(HTTPException) as exc_info:
        workbench.set_planning_mode("Book", 9, {"skipped": True})
    assert exc_info.value.status_code == 400


def test_planning_mode_persists_and_write_gate_opens(tmp_path, monkeypatch) -> None:
    from biyu.ui import workbench
    from biyu.ui.workbench_state import read_planning_skipped, read_workbench_step

    book = _book(tmp_path)
    monkeypatch.setattr(workbench, "_book_dir", lambda _b: book)
    workbench.set_planning_mode("Book", 9, {"skipped": True})
    assert read_planning_skipped(book, 9) is True
    # 2026-10 修复:开跳过要推进阶段,否则卡在写作方案、生成钮不放行
    assert read_workbench_step(book, 9) == "generation"
    workbench.set_planning_mode("Book", 9, {"skipped": False})
    assert read_workbench_step(book, 9) == "planning"

    actions = workbench._state_actions(
        "generation", "idle", stale=False, has_outline=True,
        planning_status="无", planning_skipped=True,
    )
    assert actions["write"]["enabled"] is True
    # 2026-10 自愈:修复前开启的章卡在 planning 阶段,跳过模式下同样放行
    actions_stuck = workbench._state_actions(
        "planning", "idle", stale=False, has_outline=True,
        planning_status="无", planning_skipped=True,
    )
    assert actions_stuck["write"]["enabled"] is True
    actions_no_plan = workbench._state_actions(
        "generation", "idle", stale=False, has_outline=True, planning_status="无",
    )
    assert actions_no_plan["write"]["enabled"] is False


def test_executor_appends_skip_planning_flag(tmp_path, monkeypatch) -> None:
    import asyncio

    import biyu.ui.cli_executor as ex

    book = tmp_path / "Book"
    book.mkdir()
    (book / "book.json").write_text("{}", encoding="utf-8")
    (book / "logs" / "ch1").mkdir(parents=True)
    from biyu.ui.workbench_state import write_planning_skipped

    write_planning_skipped(book, 1, True)
    captured: dict = {}

    class FakeProcess:
        stdout = asyncio.StreamReader()
        stdin = None

        def __init__(self) -> None:
            self.stdout.feed_eof()

        async def wait(self) -> int:
            return 0

    async def fake_create(*args, **kwargs):
        captured["argv"] = [str(a) for a in args]
        return FakeProcess()

    monkeypatch.setattr(ex, "resolve_book_dir", lambda _b: book)
    monkeypatch.setattr(ex.asyncio, "create_subprocess_exec", fake_create)

    async def run() -> list:
        return [event async for event in ex.execute(
            "write", book="Book", chapter=1, confirmed=True, extra={},
        )]

    asyncio.run(run())
    assert "--skip-planning" in captured["argv"]


def test_write_cmd_forwards_skip_planning(tmp_path, monkeypatch) -> None:
    import biyu.config as config_mod
    import biyu.pipeline as pipeline_mod

    captured: dict = {}

    class _FakeResult:
        word_count = 100
        cost_cny = 0.0
        latency_seconds = 0.0
        stage_latencies: dict = {}
        warnings: list = []

    async def fake_generate(book_dir, chapter_num, **kwargs):
        captured.update(kwargs)
        return _FakeResult()

    monkeypatch.setattr(pipeline_mod, "generate_chapter", fake_generate)
    (tmp_path / "book.json").write_text('{"title":"B","genre":"dushi"}', encoding="utf-8")
    monkeypatch.setattr(config_mod, "resolve_book_dir", lambda book: tmp_path)

    from biyu.cli.write_cmd import write_command

    write_command(chapter=1, book=None, skip_planning=True)
    assert captured["use_outline_contract"] is True


# ---------- 声纹取消 ----------

def test_selection_accepts_null_to_cancel(tmp_path, monkeypatch) -> None:
    from biyu.ui import voiceprint as vp

    book = tmp_path / "Book"
    (book / "声纹").mkdir(parents=True)
    (book / "book.json").write_text('{"id":"book","title":"Book"}', encoding="utf-8")
    monkeypatch.setattr(vp, "_book_dir", lambda _b: book)

    class _Body:
        active = None

    vp.update_selection("Book", _Body())
    from biyu.fingerprint.profile_state import load_profile_state

    state = load_profile_state(book)
    assert state["saved"] is True and state["active"] is None


def test_diagnosis_remaps_plan_layer_in_skip_mode(tmp_path, monkeypatch) -> None:
    """跳过导演章被误判方案层 → 归入细纲层(老板要求的回归思考)。"""
    import sys as _sys
    from types import SimpleNamespace

    from biyu.ui.diagnosis import diagnose_chapter
    from biyu.ui.workbench_state import write_planning_skipped

    book = tmp_path / "Book"
    book.mkdir()
    (book / "book.json").write_text('{"id":"b"}', encoding="utf-8")
    rounds = book / "logs" / "ch1" / "revisions"
    for number in (1, 2, 3):
        round_dir = rounds / f"round_{number}"
        round_dir.mkdir(parents=True)
        (round_dir / "manifest.json").write_text('{"status": "complete"}', encoding="utf-8")
        (round_dir / "comments.md").write_text("意见", encoding="utf-8")
        (round_dir / "issues.json").write_text("[]", encoding="utf-8")
        (round_dir / "candidate.md").write_text("正文", encoding="utf-8")
    write_planning_skipped(book, 1, True)

    class Adapter:
        async def generate(self, messages, **kwargs):
            assert any("不存在方案层" in str(message.get("content")) for message in messages)
            return SimpleNamespace(text="方案层：某处要改", cost=0.001)

    result = asyncio.run(diagnose_chapter(book, 1, adapter=Adapter()))
    assert result["layer"] == "细纲层"
    assert "无方案层" in result["reason"]


def test_real_cli_accepts_skip_planning_flag(tmp_path, monkeypatch) -> None:
    """2026-10 事故回归(第二起转发层漏参):真实 CLI 全链必须认 --skip-planning。"""
    import os
    import subprocess
    import sys
    from pathlib import Path as _Path

    book = tmp_path / "Book"
    book.mkdir()
    (book / "book.json").write_text('{"title":"B","genre":"dushi"}', encoding="utf-8")
    # 故意不给细纲:转发验证只需走到管线的干净失败,不真调写手(无 Key 会重试拖死)
    env = {
        **os.environ,
        "PYTHONPATH": "src",
        "BIYU_DATA_ROOT": str(tmp_path),
        "BIYU_DATA_ROOT_SOURCE": "environment",
    }
    result = subprocess.run(
        [sys.executable, "-c", "from biyu.cli.main import app; app()",
         "write", "-c", "1", "-b", "Book", "--force-pending", "--skip-planning"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, cwd=str(_Path(__file__).resolve().parents[1]), timeout=120,
    )
    combined = result.stdout + result.stderr
    assert "No such option" not in combined
    assert result.returncode == 1  # 干净业务失败(缺细纲),不是参数错误(退出码 2)


def test_pipeline_skip_mode_never_invokes_architect_block() -> None:
    """2026-10 事故回归:跳过模式只换 planning_text 不够,Architect 块必须整体跳过——
    否则导演照跑并覆盖细纲契约(实测成本行出现 architect,写手拿回导演方案)。"""
    src = Path("src/biyu/pipeline.py").read_text(encoding="utf-8")
    assert "if not use_existing_planning and not use_outline_contract:" in src


def test_selection_empty_string_means_cancel(tmp_path, monkeypatch) -> None:
    """2026-10 修复:生成步「不使用声纹」保存发空串 → 视为取消,不再 422。"""
    from biyu.ui import voiceprint as vp

    book = tmp_path / "Book"
    book.mkdir()
    (book / "book.json").write_text('{"id":"book","title":"Book"}', encoding="utf-8")
    monkeypatch.setattr(vp, "_book_dir", lambda _b: book)

    class _Body:
        active = ""

    vp.update_selection("Book", _Body())
    from biyu.fingerprint.profile_state import load_profile_state

    state = load_profile_state(book)
    assert state["saved"] is True and state["active"] is None


def test_skip_mode_write_enabled_from_any_stage(tmp_path) -> None:
    """2026-10 老板反馈:换声纹后从读稿阶段直接重复生成,不该被阶段闸打回重走。"""
    from biyu.ui import workbench

    for step in ("planning", "generation", "reading", "review"):
        actions = workbench._state_actions(
            step, "idle", stale=False, has_outline=True,
            planning_status="无", planning_skipped=True,
        )
        assert actions["write"]["enabled"] is True, step
    # 2026-10 终局:导演模式同样不锁阶段——已批方案+细纲即可生成,
    # 改细纲导致的方案变旧由「基于旧方案」徽标警告(死锁案例:已批+改细纲
    # → 阶段回退 → 生成/确认双禁)。reading 阶段也放行。
    actions_normal = workbench._state_actions(
        "reading", "idle", stale=False, has_outline=True,
        planning_status="已批", planning_skipped=False,
    )
    assert actions_normal["write"]["enabled"] is True
    # 未批方案仍然禁(确认闸本身保留)
    actions_unapproved = workbench._state_actions(
        "reading", "idle", stale=False, has_outline=True,
        planning_status="待批", planning_skipped=False,
    )
    assert actions_unapproved["write"]["enabled"] is False


def test_candidate_meta_records_mode_and_voiceprint(tmp_path, monkeypatch) -> None:
    """2026-10 溯源:每版候选记录 细纲直生成/导演方案 + 用的哪份声纹。"""
    from biyu.ui.workbench_versions import snapshot_candidate
    from biyu.fingerprint.profile_state import save_profile_state
    from biyu.fingerprint import library as lib

    book = tmp_path / "Book"
    (book / "chapters" / "_pending").mkdir(parents=True)
    (book / "book.json").write_text('{"id":"book","title":"Book"}', encoding="utf-8")
    (book / "chapters" / "_pending" / "ch1.md").write_text("正文内容测试。", encoding="utf-8")
    hand = book / "声纹" / "手写"
    hand.mkdir(parents=True)
    (hand / "pA.json").write_text(json.dumps({
        "id": "pA", "name": "江南文风", "kind": "manual",
        "lines": [{"dimension": "节奏", "text": "x", "why": "y"}],
    }, ensure_ascii=False), encoding="utf-8")
    save_profile_state(book, "pA")

    version = snapshot_candidate(book, 1, run_id="r1", action="write")
    meta = json.loads(
        (book / "logs" / "ch1" / "candidates" / f"candidate_v{version}.json")
        .read_text(encoding="utf-8")
    )
    assert meta["generation_mode"] == "细纲直生成"  # 无 planning.md
    assert meta["voiceprint_name"] == "江南文风"
    assert meta["voiceprint_id"] == "pA"

    # 导演模式:有已批 planning.md → 导演方案
    (book / "logs" / "ch1" / "planning.md").write_text(
        "status: 已批\n方案内容", encoding="utf-8"
    )
    (book / "chapters" / "_pending" / "ch1.md").write_text("新版正文。", encoding="utf-8")
    save_profile_state(book, None)
    snapshot_candidate(book, 1, run_id="r2", action="regenerate")
    metas = sorted((book / "logs" / "ch1" / "candidates").glob("candidate_v*.json"))
    meta2 = json.loads(metas[-1].read_text(encoding="utf-8"))
    assert meta2["generation_mode"] == "导演方案"
    assert meta2["voiceprint_name"] is None


def test_worldbook_nested_lists_flattened_for_all_consumers(tmp_path) -> None:
    """2026-10 外部用户事故:worldbook.yaml 列表套列表 → 白名单检查器
    TypeError 崩溃。加载时拍平,所有消费者(注入/白名单/Layer1)只见字符串。"""
    from biyu.worldbook import load_worldbook, build_worldbook_prompt
    from biyu.grammar_check.whitelist import load_whitelist

    book = tmp_path / "Book"
    book.mkdir()
    (book / "worldbook.yaml").write_text(
        "facts:\n"
        "  - - 硬设定甲\n"
        "    - 硬设定乙\n"
        "  - 硬设定丙\n"
        "forbidden:\n"
        "  - - 禁止事项一\n"
        "geography:\n"
        "  - - 边地\n"
        "power_system: 无\n",
        encoding="utf-8",
    )
    wb = load_worldbook(book)
    assert wb["facts"] == ["硬设定甲", "硬设定乙", "硬设定丙"]
    prompt = build_worldbook_prompt(wb)
    assert "硬设定甲" in prompt and "禁止事项一" in prompt and "边地" in prompt
    whitelist = load_whitelist(book)
    assert whitelist  # 不崩且提取到词条


def test_nested_worldbook_reaches_whitelist_and_setting_lookup(tmp_path) -> None:
    """2026-10 补漏:白名单与编辑器查询改走拍平加载,嵌套条目不再静默丢失。"""
    from biyu.grammar_check.whitelist import load_whitelist
    from biyu.editor.tools import look_up_setting

    book = tmp_path / "Book"
    book.mkdir()
    (book / "worldbook.yaml").write_text(
        "facts:\n"
        "  - - 盐丁 Seventy\n"
        "    - 桑渡口白役\n"
        "forbidden:\n"
        "  - - 私盐加人货承运\n",
        encoding="utf-8",
    )
    wl = load_whitelist(book)
    assert "桑渡口白役" in wl  # 嵌套条目里的专名进入白名单
    result = look_up_setting("盐丁 Seventy", book)
    assert "盐丁 Seventy" in result  # 嵌套条目可查
