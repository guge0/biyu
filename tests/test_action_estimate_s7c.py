"""S-7c：生成类动作确认框给出带数字的预估。"""
from __future__ import annotations

from pathlib import Path

from biyu.ui import action_estimate
from biyu.ui.action_estimate import HISTORY_PLACEHOLDER, estimate_text


def test_non_placeholder_passthrough(tmp_path: Path):
    assert estimate_text("adopt", tmp_path, "¥0") == "¥0"


def test_new_book_gets_numeric_range(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(action_estimate, "_price_ratio", lambda: 1.0)
    text = estimate_text("write", tmp_path, HISTORY_PLACEHOLDER)
    assert "¥0.15–0.40" in text and "新书" in text
    assert HISTORY_PLACEHOLDER not in text


def test_history_average_used(tmp_path: Path):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "cost_log.csv").write_text(
        "timestamp,chapter,stage,cost_cny,latency_s,status\n"
        "t,1,architect,0.04,1,ok\n"  # 导演不计入写章预估
        "t,1,writer,0.06,1,ok\n"
        "t,1,editor_total,0.14,1,ok\n"
        "t,2,writer,0.10,1,ok\n"
        "t,2,editor_total,0.10,1,ok\n",
        encoding="utf-8",
    )
    text = estimate_text("write", tmp_path, HISTORY_PLACEHOLDER)
    # 每章 0.20 → 0.14–0.30
    assert "¥0.14–0.30" in text and "2 章" in text


def test_price_ratio_scales(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(action_estimate, "_price_ratio", lambda: 2.0)
    assert "¥0.30–0.80" in estimate_text("write", tmp_path, HISTORY_PLACEHOLDER)
