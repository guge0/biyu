"""扫榜缓存层(P8-M2.5 T4.1)— UI 层 helper,不改 propose/scanner.py。

Spec line 12:
- 扫榜结果按日落盘 data/market_scans/
- propose 默认复用 ≤7 天内最新缓存
- 「重新扫榜」强制现扫
- 缓存缺失/损坏 → 现扫并 WARNING 出声(D-70)

序列化策略:PlatformResult / BookEntry 都是简单 dataclass,用 dict 化 + 关键字段
重建(from_dict),不依赖 dataclasses.asdict(避免字段集变更带来的耦合)。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from biyu.config import get_data_root
from biyu.propose.scanner import BookEntry, PlatformResult, scan_all

logger = logging.getLogger("biyu.ui.scan_cache")

_DEFAULT_MAX_AGE_DAYS = 7
_SCANS_DIRNAME = "market_scans"
_FILE_PREFIX = "scan_"
_FILE_FMT = "%Y-%m-%d"  # 文件名日期格式,例 scan_2026-07-04.json


# ---------------------------------------------------------------------------
# 序列化
# ---------------------------------------------------------------------------


def platform_result_to_dict(result: PlatformResult) -> dict[str, Any]:
    return {
        "platform": result.platform,
        "success": result.success,
        "books": [
            {
                "rank": b.rank, "title": b.title, "author": b.author,
                "category": b.category, "word_count": b.word_count,
                "url": b.url, "abstract": b.abstract,
            }
            for b in result.books
        ],
        "error": result.error,
        "fetched_at": result.fetched_at,
        "source_url": result.source_url,
    }


def platform_result_from_dict(d: dict[str, Any]) -> PlatformResult:
    books = [
        BookEntry(
            rank=int(b.get("rank", 0)),
            title=str(b.get("title", "")),
            author=str(b.get("author", "")),
            category=str(b.get("category", "")),
            word_count=str(b.get("word_count", "")),
            url=str(b.get("url", "")),
            abstract=str(b.get("abstract", "")),
        )
        for b in d.get("books", [])
        if isinstance(b, dict)
    ]
    return PlatformResult(
        platform=str(d.get("platform", "")),
        success=bool(d.get("success", False)),
        books=books,
        error=d.get("error"),
        fetched_at=str(d.get("fetched_at", "")),
        source_url=str(d.get("source_url", "")),
    )


# ---------------------------------------------------------------------------
# 文件 IO
# ---------------------------------------------------------------------------


def _scans_dir(data_root: Path | None) -> Path:
    root = data_root if data_root is not None else get_data_root()
    return root / _SCANS_DIRNAME


def _find_latest_cache(
    scans_dir: Path, *, max_age_days: int = _DEFAULT_MAX_AGE_DAYS
) -> tuple[Path, str] | None:
    """找 ≤max_age_days 内的最新缓存文件。返 (path, date_str) 或 None。"""
    if not scans_dir.exists():
        return None
    candidates: list[tuple[str, Path]] = []
    for f in scans_dir.glob(f"{_FILE_PREFIX}*.json"):
        date_str = f.name[len(_FILE_PREFIX):-len(".json")]
        try:
            d = datetime.strptime(date_str, _FILE_FMT).date()
        except ValueError:
            continue
        candidates.append((d.isoformat(), f))
    if not candidates:
        return None
    # 按日期降序
    candidates.sort(key=lambda x: x[0], reverse=True)
    latest_str, latest_path = candidates[0]
    latest_date = datetime.strptime(latest_str, _FILE_FMT).date()
    cutoff = (datetime.now() - timedelta(days=max_age_days)).date()
    if latest_date < cutoff:
        return None  # 过期
    return latest_path, latest_str


def _write_cache(scans_dir: Path, results: dict[str, PlatformResult]) -> Path:
    """落盘当日扫描结果(覆盖已有当日文件)。"""
    scans_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime(_FILE_FMT)
    out = scans_dir / f"{_FILE_PREFIX}{today}.json"
    payload = {p: platform_result_to_dict(r) for p, r in results.items()}
    out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return out


def _load_cache(path: Path) -> dict[str, PlatformResult]:
    """读缓存文件,失败抛异常(由上层捕获 → 触发 WARNING + 现扫)。"""
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("cache payload is not a dict")
    return {
        p: platform_result_from_dict(d)
        for p, d in data.items()
        if isinstance(d, dict)
    }


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def scan_all_cached(
    platforms: list[str],
    *,
    force_refresh: bool = False,
    max_age_days: int = _DEFAULT_MAX_AGE_DAYS,
    data_root: Path | None = None,
    fetchers: Any | None = None,
    limit: int = 20,
) -> tuple[dict[str, PlatformResult], dict[str, Any]]:
    """扫榜 + 缓存。

    Args:
        platforms: 平台列表(如 ["qidian", "fanqie"])
        force_refresh: 强制现扫(忽略缓存,"重新扫榜"按钮触发)
        max_age_days: 缓存最大年龄(默认 7 天)
        data_root: 数据根目录(None → get_data_root())
        fetchers / limit: 透传给 scan_all

    Returns:
        (results, meta)
        - results: dict[platform -> PlatformResult]
        - meta: {cached, cache_date, warning, cache_path}
    """
    scans_dir = _scans_dir(data_root)
    meta: dict[str, Any] = {
        "cached": False,
        "cache_date": None,
        "warning": None,
        "cache_path": None,
    }

    if not force_refresh:
        hit = _find_latest_cache(scans_dir, max_age_days=max_age_days)
        if hit is not None:
            path, date_str = hit
            try:
                results = _load_cache(path)
                meta["cached"] = True
                meta["cache_date"] = date_str
                meta["cache_path"] = str(path)
                # 校验:请求的平台都在缓存里;缺失则降级到现扫
                if all(p in results for p in platforms):
                    logger.info("扫榜缓存命中:%s (%s)", path, date_str)
                    return results, meta
                logger.warning(
                    "缓存缺平台(%s),降级到现扫",
                    [p for p in platforms if p not in results],
                )
                meta["cached"] = False
                meta["warning"] = "缓存缺部分平台,已现扫补齐"
            except (json.JSONDecodeError, ValueError) as e:
                # D-70:损坏 → 出声 + 现扫
                logger.warning("缓存文件损坏(%s):%s → 现扫", path, e)
                meta["warning"] = f"缓存损坏({date_str}),已现扫"

    # 现扫
    results = scan_all(platforms=platforms, fetchers=fetchers, limit=limit)
    out_path = _write_cache(scans_dir, results)
    meta["cache_path"] = str(out_path)
    meta["cache_date"] = datetime.now().strftime(_FILE_FMT)
    logger.info("扫榜完成 + 落盘:%s", out_path)
    return results, meta
