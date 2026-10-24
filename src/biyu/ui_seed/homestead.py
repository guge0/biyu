"""书斋耕读历统计与朱批钤印里程碑 — S-3 T3 最小实现(T8 完善降级与重算测试)。

数据源(design.md):纯本地、可重算——
- 每日字数:各书 chapters/*.md(含 _pending)按文件修改日聚合的汉字数;
- 连续耕读:有产出的日子向前连续计数(今天/昨天断尾即止);
- 累计拦截:各书 audit_reports/ch*.json 中 WARN/BLOCK 检查项合计(Auditor 词族超标等);
- 批准章数:各书已定稿章数合计。
删除示例书后全部字段随现存文件重算,书架为空时返回零值(空态不报错)。
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

_HEATMAP_DAYS = 14


def _han_count(text: str) -> int:
    return sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")


def _book_dirs(data_root: Path) -> list[Path]:
    if not data_root.is_dir():
        return []
    return [p for p in sorted(data_root.iterdir()) if p.is_dir() and (p / "book.json").is_file()]


def _daily_words(books: list[Path]) -> dict[date, int]:
    by_day: dict[date, int] = {}
    for book in books:
        chapters = book / "chapters"
        if not chapters.is_dir():
            continue
        for md in list(chapters.glob("ch*.md")) + list((chapters / "_pending").glob("ch*.md")):
            try:
                text = md.read_text(encoding="utf-8")
            except OSError:
                continue
            day = datetime.fromtimestamp(md.stat().st_mtime).date()
            by_day[day] = by_day.get(day, 0) + _han_count(text)
    return by_day


def _intercepted_count(books: list[Path]) -> int:
    total = 0
    for book in books:
        reports = book / "audit_reports"
        if not reports.is_dir():
            continue
        for rp in reports.glob("ch*.json"):
            try:
                data = json.loads(rp.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            for item in data.get("results", []):
                if str(item.get("severity", "")).upper() in ("WARN", "BLOCK"):
                    total += 1
    return total


def _finalized_total(books: list[Path]) -> int:
    total = 0
    for book in books:
        chapters = book / "chapters"
        if chapters.is_dir():
            total += len([p for p in chapters.glob("ch*.md") if p.parent.name != "_pending"])
    return total


def _contract_confirmed(books: list[Path]) -> bool:
    for book in books:
        plans = book / "logs"
        if not plans.is_dir():
            continue
        for planning in plans.glob("ch*/planning.md"):
            try:
                text = planning.read_text(encoding="utf-8")
            except OSError:
                continue
            if re.search(r"(?mi)^#{0,3}\s*(状态|status).{0,40}(已批|确认|approved)", text):
                return True
    return False


def _streak(by_day: dict[date, int]) -> int:
    streak = 0
    cursor = date.today()
    if cursor not in by_day:
        cursor -= timedelta(days=1)  # 今天还没写不算断
    while cursor in by_day:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def homestead_stats(data_root: Path) -> dict[str, Any]:
    books = _book_dirs(Path(data_root))
    by_day = _daily_words(books)
    today = date.today()
    heatmap = []
    for offset in range(_HEATMAP_DAYS - 1, -1, -1):
        day = today - timedelta(days=offset)
        words = by_day.get(day, 0)
        level = 0 if words == 0 else (1 if words < 2000 else (2 if words < 3500 else 3))
        heatmap.append({
            "date": day.isoformat(),
            "label": day.strftime("%m/%d"),
            "words": words,
            "level": level,
        })
    week_words = sum(
        words for day, words in by_day.items()
        if today - timedelta(days=6) <= day <= today
    )
    total_words = sum(by_day.values())
    return {
        "streak_days": _streak(by_day),
        "week_words": week_words,
        "total_words": total_words,
        "heatmap": heatmap,
        "intercepted_count": _intercepted_count(books),
        "approved_chapters": _finalized_total(books),
    }


_SEAL_DEFS: tuple[tuple[str, str, str, int], ...] = (
    # key, 标题(图纸三枚), 达成条件说明, 门槛字数/章数
    ("first_chapter", "初啼 · 首章定稿", "第一份正文采用为正式稿", 1),
    ("ten_k", "落纸 · 万言起步", "累计定稿字数突破一万字", 10_000),
    ("hundred_k", "云烟 · 十万言达成", "累计定稿字数突破十万字", 100_000),
    ("first_contract", "法随 · 首份契约", "与导演签下第一份写作契约", 0),
)


def seals_state(data_root: Path) -> dict[str, Any]:
    books = _book_dirs(Path(data_root))
    finalized_words = 0
    finalized_chapters = 0
    for book in books:
        chapters = book / "chapters"
        if not chapters.is_dir():
            continue
        for md in chapters.glob("ch*.md"):
            try:
                finalized_words += _han_count(md.read_text(encoding="utf-8"))
                finalized_chapters += 1
            except OSError:
                continue
    contract = _contract_confirmed(books)
    seals = []
    for key, title, detail, threshold in _SEAL_DEFS:
        if key == "first_chapter":
            achieved = finalized_chapters >= threshold
        elif key == "first_contract":
            achieved = contract
        else:
            achieved = finalized_words >= threshold
        seals.append({"key": key, "title": title, "detail": detail, "achieved": achieved})
    return {
        "seals": seals,
        "achieved_count": sum(1 for s in seals if s["achieved"]),
        "finalized_words": finalized_words,
    }
