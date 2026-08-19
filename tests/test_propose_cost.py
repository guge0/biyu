"""Tests for biyu.propose.cost — propose 命令的成本日志.

覆盖:
- CSV 格式与 _log_cost 一致(timestamp/chapter/stage/cost_cny/latency_s)
- chapter 字段写 'propose'(propose 无章节概念)
- 文件不存在时建表头,存在时 append
- 路径在 data/<name>/logs/cost_log.csv
- 单口径写入(无双写,P9-C1)
"""
from __future__ import annotations

import csv
from pathlib import Path

from biyu.propose.cost import log_propose_cost


# ---------------------------------------------------------------------------
# CSV 写入
# ---------------------------------------------------------------------------


def test_log_propose_cost_creates_file_with_header(tmp_path: Path):
    """文件不存在时,首次写入建表头 + 一行数据。"""
    name = "test_book"
    log_path = tmp_path / "data" / name / "logs" / "cost_log.csv"

    log_propose_cost(
        data_root=tmp_path,
        name=name,
        stage="analyzer",
        cost_cny=0.012,
        latency_s=3.4,
        log_path=log_path,
    )

    assert log_path.exists()
    with open(log_path, encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert len(rows) == 2  # 表头 + 1 行
    assert rows[0] == ["timestamp", "chapter", "stage", "cost_cny", "latency_s"]
    assert rows[1][1] == "propose"  # chapter 字段写 'propose'
    assert rows[1][2] == "analyzer"
    assert rows[1][3] == "0.0120"
    assert rows[1][4] == "3.4"


def test_log_propose_cost_appends_when_file_exists(tmp_path: Path):
    """文件已存在时,只 append 数据行,不重复表头。"""
    log_path = tmp_path / "data" / "x" / "logs" / "cost_log.csv"
    log_path.parent.mkdir(parents=True)

    log_propose_cost(
        data_root=tmp_path, name="x", stage="analyzer",
        cost_cny=0.01, latency_s=1.0, log_path=log_path,
    )
    log_propose_cost(
        data_root=tmp_path, name="x", stage="craft",
        cost_cny=0.02, latency_s=2.0, log_path=log_path,
    )

    with open(log_path, encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert len(rows) == 3  # 表头 + 2 数据行
    assert rows[1][2] == "analyzer"
    assert rows[2][2] == "craft"


def test_log_propose_cost_writes_chapter_field_as_propose(tmp_path: Path):
    """chapter 字段固定写 'propose'(spec 要求,propose 无章节)。"""
    log_path = tmp_path / "data" / "x" / "logs" / "cost_log.csv"
    log_propose_cost(
        data_root=tmp_path, name="x", stage="any",
        cost_cny=0.0, latency_s=0.0, log_path=log_path,
    )
    with open(log_path, encoding="utf-8") as f:
        rows = list(csv.reader(f))
    # 每行的 chapter 字段都是 'propose'
    for row in rows[1:]:
        assert row[1] == "propose"


def test_log_propose_cost_uses_default_path_when_log_path_none(tmp_path: Path):
    """log_path=None 时,默认写到 data_root/<name>/logs/cost_log.csv。"""
    name = "default_path_test"
    log_propose_cost(
        data_root=tmp_path, name=name, stage="analyzer",
        cost_cny=0.01, latency_s=1.0,
        # log_path 不传
    )

    expected = tmp_path / name / "logs" / "cost_log.csv"
    assert expected.exists()


def test_log_propose_cost_format_matches_pipeline_log_cost(tmp_path: Path):
    """与 _log_cost 的 CSV 列顺序完全一致(timestamp/chapter/stage/cost_cny/latency_s)。"""
    log_path = tmp_path / "data" / "x" / "logs" / "cost_log.csv"
    log_propose_cost(
        data_root=tmp_path, name="x", stage="analyzer",
        cost_cny=0.0123, latency_s=3.45, log_path=log_path,
    )
    with open(log_path, encoding="utf-8") as f:
        rows = list(csv.reader(f))
    header = rows[0]
    assert header == ["timestamp", "chapter", "stage", "cost_cny", "latency_s"]
    data = rows[1]
    # 列数一致
    assert len(data) == 5
    # timestamp 不为空
    assert data[0]


# D-93 双写已移除(P9-C1 单口径),不再写入根 csv。

