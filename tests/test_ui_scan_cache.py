"""Tests for biyu.ui.scan_cache — T4.1 扫榜缓存层(P8-M2.5).

Spec line 12:
- 扫榜结果按日落盘 data/market_scans/
- propose 默认复用 ≤7 天内最新缓存
- 「重新扫榜」强制现扫
- 缓存缺失/损坏 → 现扫并 WARNING 出声(D-70)

cache 层属 UI 层,不改 propose/scanner.py(租约外)。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from biyu.propose.scanner import BookEntry, PlatformResult
from biyu.ui.scan_cache import scan_all_cached


def _make_book(i: int) -> BookEntry:
    return BookEntry(
        rank=i, title=f"书{i}", author=f"作者{i}", category="玄幻",
        word_count="100万字", url=f"https://x.com/{i}", abstract=f"简介{i}",
    )


def _platform_result(platform: str = "qidian", n: int = 3) -> PlatformResult:
    return PlatformResult(
        platform=platform, success=True,
        books=[_make_book(i + 1) for i in range(n)],
        fetched_at="2026-07-04T10:00:00+00:00",
        source_url=f"https://x.com/{platform}",
    )


def _fake_scan(**kwargs):
    """假扫(替 scan_all):返固定结果。"""
    platforms = kwargs.get("platforms") or ["qidian"]
    return {p: _platform_result(p) for p in platforms}


# ---------------------------------------------------------------------------
# 缓存缺失 → 现扫 + 落盘
# ---------------------------------------------------------------------------


def test_cache_miss_triggers_scan_and_writes_file(tmp_path: Path, monkeypatch):
    """空目录 → 触发扫榜,落盘 scan_<YYYY-MM-DD>.json。"""
    scans_dir = tmp_path / "market_scans"
    # 目录不存在 → 应自动创建

    calls = []
    monkeypatch.setattr(
        "biyu.ui.scan_cache.scan_all",
        lambda **kw: (calls.append(kw) or _fake_scan(**kw)),
    )

    results, meta = scan_all_cached(
        platforms=["qidian"], data_root=tmp_path,
    )
    assert len(results) == 1
    assert "qidian" in results
    assert meta["cached"] is False
    assert meta["warning"] is None
    # 文件落盘
    assert scans_dir.exists()
    files = list(scans_dir.glob("scan_*.json"))
    assert len(files) == 1
    # scan_all 被调一次
    assert len(calls) == 1


def test_cache_hit_reuses_file(tmp_path: Path, monkeypatch):
    """已有当日缓存 → 不再调 scan_all。"""
    scans_dir = tmp_path / "market_scans"
    scans_dir.mkdir(parents=True)
    today = datetime.now().strftime("%Y-%m-%d")
    cache_file = scans_dir / f"scan_{today}.json"
    cache_file.write_text(
        json.dumps({
            "qidian": {
                "platform": "qidian", "success": True,
                "books": [
                    {"rank": 1, "title": "缓存书", "author": "X", "category": "Y",
                     "word_count": "1万字", "url": "http://x", "abstract": "Z"}
                ],
                "fetched_at": "2026-07-04T10:00:00+00:00",
                "source_url": "https://x.com/qidian",
            }
        }),
        encoding="utf-8",
    )

    called = []
    monkeypatch.setattr(
        "biyu.ui.scan_cache.scan_all",
        lambda **kw: (called.append(kw) or _fake_scan(**kw)),
    )

    results, meta = scan_all_cached(
        platforms=["qidian"], data_root=tmp_path,
    )
    assert meta["cached"] is True
    assert meta["cache_date"] == today
    assert len(called) == 0, "缓存命中,不应调 scan_all"
    assert results["qidian"].books[0].title == "缓存书"


# ---------------------------------------------------------------------------
# ≤7 天:用最近缓存(即便不是今天)
# ---------------------------------------------------------------------------


def test_cache_within_7_days_is_reused(tmp_path: Path, monkeypatch):
    """3 天前的缓存 → 应被复用(默认 max_age_days=7)。"""
    scans_dir = tmp_path / "market_scans"
    scans_dir.mkdir(parents=True)
    three_days_ago = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
    cache_file = scans_dir / f"scan_{three_days_ago}.json"
    cache_file.write_text(
        json.dumps({
            "qidian": {
                "platform": "qidian", "success": True,
                "books": [], "fetched_at": "2026-07-01T10:00:00+00:00",
                "source_url": "https://x.com/qidian",
            }
        }),
        encoding="utf-8",
    )

    called = []
    monkeypatch.setattr(
        "biyu.ui.scan_cache.scan_all",
        lambda **kw: (called.append(kw) or _fake_scan(**kw)),
    )

    results, meta = scan_all_cached(
        platforms=["qidian"], data_root=tmp_path,
    )
    assert meta["cached"] is True
    assert meta["cache_date"] == three_days_ago
    assert len(called) == 0


def test_cache_older_than_7_days_triggers_refresh(tmp_path: Path, monkeypatch):
    """10 天前的缓存 → 视为过期,现扫。"""
    scans_dir = tmp_path / "market_scans"
    scans_dir.mkdir(parents=True)
    ten_days_ago = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
    cache_file = scans_dir / f"scan_{ten_days_ago}.json"
    cache_file.write_text(
        json.dumps({
            "qidian": {
                "platform": "qidian", "success": True,
                "books": [], "fetched_at": "2026-06-24T10:00:00+00:00",
                "source_url": "https://x.com/qidian",
            }
        }),
        encoding="utf-8",
    )

    called = []
    monkeypatch.setattr(
        "biyu.ui.scan_cache.scan_all",
        lambda **kw: (called.append(kw) or _fake_scan(**kw)),
    )

    results, meta = scan_all_cached(
        platforms=["qidian"], data_root=tmp_path,
    )
    assert meta["cached"] is False
    assert len(called) == 1


# ---------------------------------------------------------------------------
# 缓存损坏 → 现扫 + WARNING
# ---------------------------------------------------------------------------


def test_corrupt_cache_triggers_refresh_with_warning(tmp_path: Path, monkeypatch):
    """缓存文件 JSON 坏 → 现扫,meta.warning 含人话提示(D-70)。"""
    scans_dir = tmp_path / "market_scans"
    scans_dir.mkdir(parents=True)
    today = datetime.now().strftime("%Y-%m-%d")
    cache_file = scans_dir / f"scan_{today}.json"
    cache_file.write_text("{not valid json", encoding="utf-8")

    monkeypatch.setattr("biyu.ui.scan_cache.scan_all", _fake_scan)

    results, meta = scan_all_cached(
        platforms=["qidian"], data_root=tmp_path,
    )
    assert meta["cached"] is False
    assert meta["warning"] is not None
    assert "损坏" in meta["warning"] or "corrupt" in meta["warning"].lower()


# ---------------------------------------------------------------------------
# force_refresh:忽略缓存,强制现扫
# ---------------------------------------------------------------------------


def test_force_refresh_ignores_valid_cache(tmp_path: Path, monkeypatch):
    """有效的当日缓存 + force_refresh=True → 应强制现扫。"""
    scans_dir = tmp_path / "market_scans"
    scans_dir.mkdir(parents=True)
    today = datetime.now().strftime("%Y-%m-%d")
    cache_file = scans_dir / f"scan_{today}.json"
    cache_file.write_text(
        json.dumps({
            "qidian": {
                "platform": "qidian", "success": True,
                "books": [], "fetched_at": "2026-07-04T10:00:00+00:00",
                "source_url": "https://x.com/qidian",
            }
        }),
        encoding="utf-8",
    )

    called = []
    monkeypatch.setattr(
        "biyu.ui.scan_cache.scan_all",
        lambda **kw: (called.append(kw) or _fake_scan(**kw)),
    )

    results, meta = scan_all_cached(
        platforms=["qidian"], data_root=tmp_path, force_refresh=True,
    )
    assert meta["cached"] is False
    assert len(called) == 1
    # 强制现扫后,新文件落盘(覆盖当日)
    assert cache_file.exists()


# ---------------------------------------------------------------------------
# 选择最新缓存(多文件场景)
# ---------------------------------------------------------------------------


def test_picks_most_recent_cache(tmp_path: Path, monkeypatch):
    """多份缓存:选最新的(按文件名日期)。"""
    scans_dir = tmp_path / "market_scans"
    scans_dir.mkdir(parents=True)
    # 5 天前 + 2 天前,应选 2 天前
    five_days = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
    two_days = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
    for date_str in (five_days, two_days):
        (scans_dir / f"scan_{date_str}.json").write_text(
            json.dumps({
                "qidian": {
                    "platform": "qidian", "success": True,
                    "books": [], "fetched_at": f"{date_str}T10:00:00+00:00",
                    "source_url": "https://x.com/qidian",
                }
            }),
            encoding="utf-8",
        )

    monkeypatch.setattr("biyu.ui.scan_cache.scan_all", _fake_scan)
    results, meta = scan_all_cached(
        platforms=["qidian"], data_root=tmp_path,
    )
    assert meta["cached"] is True
    assert meta["cache_date"] == two_days
