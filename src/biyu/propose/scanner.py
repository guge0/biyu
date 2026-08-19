"""扫榜模块:起点 mobile SSR + 番茄公开 API,纯 httpx。

设计:
- parse_*  : 纯函数,输入是已抓到的 HTML/JSON,输出 BookEntry 列表。便于单测零网络。
- scan_*   : HTTP 抓取 + parse + sanity check + 降级,返回 PlatformResult。
- scan_all : 编排多个平台,失败不中断,返回 dict[platform -> PlatformResult]。

参考实现(已在 P7-Probe 验证):
- 起点 mobile SSR:oh-story qidian-rank-scraper.js:287-298
- 番茄 API:inkos radar-source.ts:53-86
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

import httpx


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------


@dataclass
class BookEntry:
    """单本榜单书的标准化记录。"""

    rank: int
    title: str
    author: str
    category: str  # 题材,合并主+子,如 "仙侠·修真文明"
    word_count: str  # 字数,保留原字符串,如 "593.54万字"
    url: str
    abstract: str


@dataclass
class PlatformResult:
    """单平台扫榜结果(含成功/失败状态)。"""

    platform: str  # "qidian" / "fanqie"
    success: bool
    books: list[BookEntry] = field(default_factory=list)
    error: str | None = None  # 失败原因(success=False 时填)
    fetched_at: str = ""  # ISO8601 UTC 时间戳
    source_url: str = ""  # 数据来源 URL,便于溯源


# ---------------------------------------------------------------------------
# 起点移动端 SSR 解析(纯函数)
# ---------------------------------------------------------------------------


_SSR_SCRIPT_RE = re.compile(
    r'<script[^>]+id=["\']vite-plugin-ssr_pageContext["\'][^>]*>([\s\S]*?)</script>',
    re.IGNORECASE,
)


def parse_qidian_html(html: str) -> list[BookEntry]:
    """从起点移动端 SSR HTML 抠出榜单书籍。

    SSR JSON 路径(已验证):pageContext.pageContext.pageProps.pageData.records
    字段映射:bName/bAuth/cat/subCat/cnt/bid/desc/rankNum
    """
    m = _SSR_SCRIPT_RE.search(html)
    if not m:
        return []
    try:
        ctx = json.loads(m.group(1))
    except json.JSONDecodeError:
        return []

    records = (
        ctx.get("pageContext", {})
        .get("pageProps", {})
        .get("pageData", {})
        .get("records", [])
    )
    if not isinstance(records, list):
        return []

    books: list[BookEntry] = []
    for idx, rec in enumerate(records):
        if not isinstance(rec, dict):
            continue
        title = rec.get("bName") or rec.get("bookName") or ""
        if not title:
            continue  # 跳过缺书名的记录
        bid = str(rec.get("bid") or rec.get("bookId") or "")
        cat = rec.get("cat") or ""
        sub_cat = rec.get("subCat") or ""
        category = "·".join([p for p in [cat, sub_cat] if p])
        books.append(
            BookEntry(
                rank=rec.get("rankNum") or idx + 1,
                title=title,
                author=rec.get("bAuth") or rec.get("author") or "",
                category=category,
                word_count=rec.get("cnt") or "",
                url=f"https://m.qidian.com/book/{bid}/" if bid else "",
                abstract=rec.get("desc") or "",
            )
        )
    return books


# ---------------------------------------------------------------------------
# Sanity check(健壮性兜底)
# ---------------------------------------------------------------------------


def _passes_sanity_check(books: list[BookEntry]) -> bool:
    """检查抓到的数据是否可用:本数 > 0 且关键字段非空比例 ≥ 80%。

    关键字段 = 书名 + 题材。每个 book 这两字段非空各算 1 分,总分 / (2 * 本数) >= 0.8 才过。
    触发场景:平台改版导致 SSR 字段名 / API 路径变了,大面积字段抠空 → 标失败降级。
    """
    if not books:
        return False
    non_empty = sum(1 for b in books if b.title) + sum(1 for b in books if b.category)
    return non_empty / (2 * len(books)) >= 0.8


# ---------------------------------------------------------------------------
# 默认 HTTP fetcher(生产用),测试可注入 fetcher 绕过
# ---------------------------------------------------------------------------


_QIDIAN_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "identity",
}

_FANQIE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; biyu-propose/0.1)",
}


def _http_get_text(url: str, headers: dict | None = None, timeout: float = 10.0) -> str:
    """默认 HTTP fetcher,用 httpx.Client 同步抓。失败抛异常让上层 catch。"""
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        resp = client.get(url, headers=headers or {})
        resp.raise_for_status()
        return resp.text


def _default_qidian_fetcher(url: str) -> str:
    return _http_get_text(url, headers=_QIDIAN_HEADERS)


def _default_fanqie_fetcher(url: str) -> str:
    return _http_get_text(url, headers=_FANQIE_HEADERS)


# ---------------------------------------------------------------------------
# 扫榜编排:scan_qidian / scan_fanqie / scan_all
# ---------------------------------------------------------------------------


QIDIAN_MOBILE_BASE = "https://m.qidian.com"
# 起点榜单类型 → 移动端路径(参考 oh-story qidian-rank-scraper.js:53-89)
QIDIAN_RANK_TYPES: dict[str, str] = {
    "hotsales": "/rank/hotsales/",
    "yuepiao": "/rank/yuepiao/",
    "newbook": "/rank/newbook/",
    "recom": "/rank/rec/",
    "readindex": "/rank/readindex/",
}

FANQIE_API = (
    "https://api-lf.fanqiesdk.com/api/novel/channel/homepage/rank/rank_list/v2/"
)
# 番茄 side_type → 标签(参考 inkos radar-source.ts:48-51)
FANQIE_SIDE_TYPES: dict[str, int] = {
    "hot": 10,
    "darkhorse": 13,
}


Fetcher = Callable[[str], str]


def scan_qidian(
    rank_type: str = "hotsales",
    limit: int = 20,
    fetcher: Fetcher | None = None,
) -> PlatformResult:
    """扫起点移动端 SSR 榜单。

    Args:
        rank_type: 榜单类型,见 QIDIAN_RANK_TYPES
        limit: 取前 N 本
        fetcher: 可选 URL→text fetcher(测试注入用);默认走 httpx
    """
    f = fetcher or _default_qidian_fetcher
    path = QIDIAN_RANK_TYPES.get(rank_type, QIDIAN_RANK_TYPES["hotsales"])
    url = f"{QIDIAN_MOBILE_BASE}{path}"
    fetched_at = datetime.now(timezone.utc).isoformat()

    try:
        html = f(url)
    except Exception as e:
        return PlatformResult(
            platform="qidian", success=False,
            error=f"fetch failed: {e}", fetched_at=fetched_at, source_url=url,
        )

    books = parse_qidian_html(html)[:limit]
    if not _passes_sanity_check(books):
        return PlatformResult(
            platform="qidian", success=False,
            error=f"sanity check failed (books={len(books)}, fields too sparse)",
            fetched_at=fetched_at, source_url=url,
        )

    return PlatformResult(
        platform="qidian", success=True, books=books,
        fetched_at=fetched_at, source_url=url,
    )


def scan_fanqie(
    side_type: int | str = "hot",
    limit: int = 20,
    fetcher: Fetcher | None = None,
) -> PlatformResult:
    """扫番茄公开 API 榜单。

    Args:
        side_type: 'hot'(热门榜 10) / 'darkhorse'(黑马榜 13) / 直接传 int
        limit: API limit 参数(也是返回上限)
        fetcher: 可选 URL→text fetcher(测试注入用)
    """
    f = fetcher or _default_fanqie_fetcher
    st = FANQIE_SIDE_TYPES.get(str(side_type), 10) if not isinstance(side_type, int) else side_type
    url = f"{FANQIE_API}?aid=13&limit={limit}&offset=0&side_type={st}"
    fetched_at = datetime.now(timezone.utc).isoformat()

    try:
        body = f(url)
        data = json.loads(body)
    except Exception as e:
        return PlatformResult(
            platform="fanqie", success=False,
            error=f"fetch/parse failed: {e}", fetched_at=fetched_at, source_url=url,
        )

    books = parse_fanqie_json(data)[:limit]
    if not _passes_sanity_check(books):
        return PlatformResult(
            platform="fanqie", success=False,
            error=f"sanity check failed (books={len(books)}, fields too sparse)",
            fetched_at=fetched_at, source_url=url,
        )

    return PlatformResult(
        platform="fanqie", success=True, books=books,
        fetched_at=fetched_at, source_url=url,
    )


def scan_all(
    platforms: list[str],
    fetchers: dict[str, Fetcher] | None = None,
    limit: int = 20,
) -> dict[str, PlatformResult]:
    """扫多平台,某平台失败不中断,继续其他平台。

    Returns:
        dict[platform -> PlatformResult],每个平台都有 entry(success 可能 False)
    """
    fetchers = fetchers or {}
    results: dict[str, PlatformResult] = {}
    for p in platforms:
        if p == "qidian":
            results[p] = scan_qidian(limit=limit, fetcher=fetchers.get("qidian"))
        elif p == "fanqie":
            results[p] = scan_fanqie(limit=limit, fetcher=fetchers.get("fanqie"))
        else:
            results[p] = PlatformResult(
                platform=p, success=False,
                error=f"unknown platform: {p}",
                fetched_at=datetime.now(timezone.utc).isoformat(),
            )
    return results


# ---------------------------------------------------------------------------
# 番茄公开 API 解析(纯函数)
# ---------------------------------------------------------------------------


def parse_fanqie_json(data: dict[str, Any]) -> list[BookEntry]:
    """从番茄 API 返回的 JSON 解析榜单书籍。

    API 路径(已验证):api-lf.fanqiesdk.com/...?side_type=10
    字段映射:book_name/author/category/abstract/book_id
    """
    result = (
        data.get("data", {})
        .get("result", [])
        if isinstance(data, dict)
        else []
    )
    if not isinstance(result, list):
        return []

    books: list[BookEntry] = []
    for idx, rec in enumerate(result):
        if not isinstance(rec, dict):
            continue
        title = rec.get("book_name") or ""
        if not title:
            continue
        book_id = str(rec.get("book_id") or "")
        books.append(
            BookEntry(
                rank=idx + 1,  # 番茄 API 不带 rank,按返回顺序
                title=title,
                author=rec.get("author") or "",
                category=rec.get("category") or "",
                word_count=str(rec.get("word_number") or rec.get("word_count") or ""),
                url=f"https://fanqienovel.com/page/{book_id}" if book_id else "",
                abstract=rec.get("abstract") or "",
            )
        )
    return books
