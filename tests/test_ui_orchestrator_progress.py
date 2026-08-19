"""Tests for biyu.ui.orchestrator on_progress callback (P8-M2.5 T3.1).

Spec line 11 — T3 SSE 进度:propose 按 stage(扫榜→套路→红蓝海→craft)
→ orchestrator 必须接受 on_progress callback,在每个 stage 起点/终点/失败时
触发事件,SSE 层只负责把它转发给前端。

覆盖:
- SPECIFIC 路径:scan / router / tropes / redblue / craft / done 全部触发
- EMPTY/DIRECTIONAL 路径:redblue 不触发(无该 stage)
- 异常降级(D-70):redblue 异常时触发 status=failed,整体仍 done
- 事件结构:{stage, status, [cost_cny], [error], [total_cost_cny]}
"""
from __future__ import annotations

from pathlib import Path

import pytest

from biyu.ui.orchestrator import run_propose_for_ui
from tests.test_ui_orchestrator import _MockAdapter  # 复用 mock


# ---------------------------------------------------------------------------
# SPECIFIC 路径:全 5 stage + done
# ---------------------------------------------------------------------------


def test_specific_path_fires_all_stages(tmp_path: Path):
    adapter = _MockAdapter(router_response="specific")
    events: list[dict] = []
    result = run_propose_for_ui(
        idea="校车进秘境、轻喜剧",
        name="progress_specific",
        platforms=["qidian"],
        llm_adapter=adapter,
        data_root=tmp_path,
        on_progress=events.append,
    )
    assert result.status == "ok"
    stages_seen = {e["stage"] for e in events}
    # scan + router + tropes + redblue + craft + done
    assert "scan" in stages_seen
    assert "router" in stages_seen
    assert "tropes" in stages_seen
    assert "redblue" in stages_seen  # SPECIFIC only
    assert "craft" in stages_seen
    assert "done" in stages_seen


def test_each_stage_has_start_and_done(tmp_path: Path):
    """每个 stage 至少触发 start 和 done 两个事件(done 表示该 stage 完成)。"""
    adapter = _MockAdapter(router_response="specific")
    events: list[dict] = []
    run_propose_for_ui(
        idea="校车",
        name="progress_stage_lifecycle",
        platforms=["qidian"],
        llm_adapter=adapter,
        data_root=tmp_path,
        on_progress=events.append,
    )
    for stage in ("scan", "router", "tropes", "redblue", "craft"):
        statuses = {e["status"] for e in events if e["stage"] == stage}
        assert "start" in statuses, f"stage {stage} 缺 start"
        assert "done" in statuses, f"stage {stage} 缺 done"


def test_done_event_has_total_cost(tmp_path: Path):
    """done 事件必须带 total_cost_cny,前端用于在最后一帧刷新会话成本。"""
    adapter = _MockAdapter(router_response="specific")
    events: list[dict] = []
    result = run_propose_for_ui(
        idea="x",
        name="progress_done_cost",
        platforms=["qidian"],
        llm_adapter=adapter,
        data_root=tmp_path,
        on_progress=events.append,
    )
    done_events = [e for e in events if e["stage"] == "done"]
    assert len(done_events) >= 1
    last_done = done_events[-1]
    assert "total_cost_cny" in last_done
    assert last_done["total_cost_cny"] == pytest.approx(result.total_cost_cny)


# ---------------------------------------------------------------------------
# EMPTY / DIRECTIONAL:无 redblue stage
# ---------------------------------------------------------------------------


def test_empty_path_skips_redblue_stage(tmp_path: Path):
    adapter = _MockAdapter(router_response="empty")
    events: list[dict] = []
    run_propose_for_ui(
        idea="",
        name="progress_empty",
        platforms=["qidian"],
        llm_adapter=adapter,
        data_root=tmp_path,
        on_progress=events.append,
    )
    stages = {e["stage"] for e in events}
    assert "redblue" not in stages
    assert "tropes" in stages
    assert "craft" in stages
    assert "done" in stages


def test_directional_path_skips_redblue_stage(tmp_path: Path):
    adapter = _MockAdapter(router_response="directional")
    events: list[dict] = []
    run_propose_for_ui(
        idea="想写穿越的",
        name="progress_directional",
        platforms=["qidian"],
        llm_adapter=adapter,
        data_root=tmp_path,
        on_progress=events.append,
    )
    stages = {e["stage"] for e in events}
    assert "redblue" not in stages


# ---------------------------------------------------------------------------
# 异常降级(D-70):redblue 异常 → failed 事件 + 整体仍 done
# ---------------------------------------------------------------------------


def test_redblue_failure_fires_failed_status(tmp_path: Path, monkeypatch):
    """build_redblue 异常 → on_progress 收到 status=failed 的 redblue 事件,整体仍 done。"""
    from biyu.ui import orchestrator as orch_mod

    def boom(*args, **kwargs):
        raise RuntimeError("simulated outage")

    monkeypatch.setattr(orch_mod, "build_redblue", boom)

    adapter = _MockAdapter(router_response="specific")
    events: list[dict] = []
    result = run_propose_for_ui(
        idea="x",
        name="progress_boom",
        platforms=["qidian"],
        llm_adapter=adapter,
        data_root=tmp_path,
        on_progress=events.append,
    )
    redblue_events = [e for e in events if e["stage"] == "redblue"]
    assert any(e["status"] == "failed" for e in redblue_events)
    # failed 事件含 error 字段(人话)
    failed = next(e for e in redblue_events if e["status"] == "failed")
    assert "error" in failed and failed["error"]
    # 整体仍完成
    assert result.status == "ok"
    assert any(e["stage"] == "done" for e in events)


# ---------------------------------------------------------------------------
# 事件结构契约:必须有 stage + status 字段
# ---------------------------------------------------------------------------


def test_event_structure_has_stage_and_status_fields(tmp_path: Path):
    adapter = _MockAdapter(router_response="specific")
    events: list[dict] = []
    run_propose_for_ui(
        idea="x",
        name="progress_contract",
        platforms=["qidian"],
        llm_adapter=adapter,
        data_root=tmp_path,
        on_progress=events.append,
    )
    for evt in events:
        assert "stage" in evt
        assert "status" in evt
        assert evt["status"] in ("start", "done", "failed")


def test_on_progress_none_does_not_crash(tmp_path: Path):
    """on_progress 默认 None,应正常工作(等价于不通知)。"""
    adapter = _MockAdapter(router_response="specific")
    result = run_propose_for_ui(
        idea="x",
        name="progress_none",
        platforms=["qidian"],
        llm_adapter=adapter,
        data_root=tmp_path,
        # on_progress 不传
    )
    assert result.status == "ok"
