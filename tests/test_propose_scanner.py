"""Tests for biyu.propose.scanner — 扫榜模块.

覆盖:起点 mobile SSR 解析、番茄 API 解析、sanity check、单平台/全平台降级。
所有 HTTP 调用通过构造 mock HTML/JSON 测试,零网络依赖。
"""
from __future__ import annotations

import json

from biyu.propose.scanner import (
    BookEntry,
    PlatformResult,
    parse_fanqie_json,
    parse_qidian_html,
    scan_all,
    scan_fanqie,
    scan_qidian,
)


# ---------------------------------------------------------------------------
# T1: 起点移动端 SSR 解析
# ---------------------------------------------------------------------------


def _make_qidian_html(records: list[dict]) -> str:
    """构造一份带 SSR pageContext 的起点 HTML mock。

    真实页面结构(基于 P7-Probe 验证):
      <script id="vite-plugin-ssr_pageContext">{...}</script>
    JSON 路径:pageContext.pageContext.pageProps.pageData.records
    """
    page_context = {
        "pageContext": {
            "pageProps": {
                "pageData": {
                    "total": len(records),
                    "records": records,
                }
            }
        }
    }
    return (
        "<html><head>"
        f'<script id="vite-plugin-ssr_pageContext">'
        f"{json.dumps(page_context, ensure_ascii=False)}"
        "</script>"
        "</head><body>...略...</body></html>"
    )


def test_parse_qidian_html_extracts_records_from_ssr_page_context():
    """能从 SSR pageContext 抠出书籍列表,字段映射正确。

    真实字段名(已验证):bName/bAuth/cat/subCat/cnt/bid/desc/rankNum。
    """
    records = [
        {
            "bName": "玄鉴仙族",
            "bAuth": "季越人",
            "cat": "仙侠",
            "subCat": "修真文明",
            "cnt": "593.54万字",
            "bid": "1035420986",
            "desc": "陆江仙熬夜猝死,残魂附在了铜镜上...",
            "rankNum": 1,
            "catId": 22,
            "subCatId": 18,
            "_index": 0,
        },
        {
            "bName": "青山",
            "bAuth": "会说话的肘子",
            "cat": "玄幻",
            "subCat": "东方玄幻",
            "cnt": "239.7万字",
            "bid": "1033014772",
            "desc": "当今名利已斩天下九分侠气...",
            "rankNum": 2,
            "catId": 21,
            "subCatId": 8,
            "_index": 1,
        },
    ]
    html = _make_qidian_html(records)

    books = parse_qidian_html(html)

    assert len(books) == 2
    assert all(isinstance(b, BookEntry) for b in books)

    first = books[0]
    assert first.rank == 1
    assert first.title == "玄鉴仙族"
    assert first.author == "季越人"
    assert first.category == "仙侠·修真文明"
    assert first.word_count == "593.54万字"
    assert first.url == "https://m.qidian.com/book/1035420986/"
    assert first.abstract.startswith("陆江仙熬夜猝死")


def test_parse_qidian_html_returns_empty_when_no_ssr_script():
    """SSR script 不在 HTML 里时,返回空列表,不抛异常。"""
    html = "<html><body>没有 SSR 注水</body></html>"
    books = parse_qidian_html(html)
    assert books == []


def test_parse_qidian_html_returns_empty_when_records_missing():
    """SSR JSON 在但路径里没 records 时,返回空列表。"""
    page_context = {"pageContext": {"pageProps": {"pageData": {"total": 0}}}}
    html = (
        '<html><head><script id="vite-plugin-ssr_pageContext">'
        f"{json.dumps(page_context)}</script></head></html>"
    )
    books = parse_qidian_html(html)
    assert books == []


def test_parse_qidian_html_skips_records_without_title():
    """record 缺 bName(空字符串/缺字段)时跳过,不进结果。"""
    records = [
        {"bName": "正常书", "bAuth": "作者", "bid": "1", "rankNum": 1},
        {"bName": "", "bAuth": "无名氏", "bid": "2", "rankNum": 2},
        {"bAuth": "缺书名", "bid": "3", "rankNum": 3},
    ]
    html = _make_qidian_html(records)
    books = parse_qidian_html(html)
    assert len(books) == 1
    assert books[0].title == "正常书"


# ---------------------------------------------------------------------------
# T3: scan_qidian / scan_fanqie / scan_all — HTTP 抓取 + sanity check + 降级
# ---------------------------------------------------------------------------


def test_scan_qidian_success_via_injected_fetcher():
    """注入 fetcher 返回合法 HTML → PlatformResult.success=True + books。"""
    html = _make_qidian_html([
        {"bName": "书A", "bAuth": "作者A", "cat": "玄幻", "subCat": "东方",
         "cnt": "100万字", "bid": "1", "desc": "x", "rankNum": 1},
        {"bName": "书B", "bAuth": "作者B", "cat": "都市", "subCat": "",
         "cnt": "50万字", "bid": "2", "desc": "y", "rankNum": 2},
    ])

    result = scan_qidian(fetcher=lambda url: html)

    assert result.platform == "qidian"
    assert result.success is True
    assert len(result.books) == 2
    assert result.error is None
    assert result.source_url.startswith("https://m.qidian.com/rank/")
    assert result.fetched_at  # 非空 ISO 时间戳


def test_scan_qidian_failure_when_fetcher_raises():
    """fetcher 抛异常 → PlatformResult.success=False,不向上抛。"""
    def boom(_url: str) -> str:
        raise ConnectionError("network down")

    result = scan_qidian(fetcher=boom)

    assert result.platform == "qidian"
    assert result.success is False
    assert result.books == []
    assert "network down" in (result.error or "")


def test_scan_qidian_failure_when_zero_books():
    """fetcher 返回合法 HTML 但 0 本书 → sanity 失败,success=False。"""
    html = _make_qidian_html([])

    result = scan_qidian(fetcher=lambda url: html)

    assert result.success is False
    assert result.books == []
    assert "sanity" in (result.error or "").lower() or "0" in (result.error or "")


def test_scan_qidian_failure_when_category_mostly_empty():
    """有书但题材大面积缺失(>20% 缺)→ sanity 失败。

    题材是非空比例阈值 80%:5 本里 3 本题材空 → 非 empty 比例 5/10=0.5 不达标。
    """
    records = [
        {"bName": f"书{i}", "bAuth": "x", "cat": "", "subCat": "",
         "cnt": "1万字", "bid": str(i), "desc": "d", "rankNum": i}
        for i in range(1, 4)  # 3 本无题材
    ] + [
        {"bName": f"书{i}", "bAuth": "x", "cat": "玄幻", "subCat": "东方",
         "cnt": "1万字", "bid": str(i), "desc": "d", "rankNum": i}
        for i in range(4, 6)  # 2 本有题材
    ]
    html = _make_qidian_html(records)

    result = scan_qidian(fetcher=lambda url: html)

    assert result.success is False
    assert "sanity" in (result.error or "").lower()


def test_scan_fanqie_success_via_injected_fetcher():
    """注入 fetcher 返回合法 JSON 字符串 → PlatformResult.success=True。"""
    payload = json.dumps({
        "code": 0,
        "data": {"result": [
            {"book_name": "番茄书A", "author": "A", "category": "都市",
             "abstract": "x", "book_id": "1"},
            {"book_name": "番茄书B", "author": "B", "category": "玄幻",
             "abstract": "y", "book_id": "2"},
        ]},
    })

    result = scan_fanqie(fetcher=lambda url: payload)

    assert result.platform == "fanqie"
    assert result.success is True
    assert len(result.books) == 2
    assert result.source_url.startswith("https://api-lf.fanqiesdk.com/")


def test_scan_all_continues_when_one_platform_fails():
    """scan_all 里某平台失败不中断,继续跑其他平台,两平台都在结果里。"""
    qidian_html = _make_qidian_html([
        {"bName": "起点书", "cat": "玄幻", "subCat": "东方", "bid": "1",
         "bAuth": "x", "desc": "d", "rankNum": 1}
    ])
    fanqie_payload = "not valid json"  # 让 fanqie 失败

    results = scan_all(
        platforms=["qidian", "fanqie"],
        fetchers={
            "qidian": lambda url: qidian_html,
            "fanqie": lambda url: fanqie_payload,
        },
    )

    assert set(results.keys()) == {"qidian", "fanqie"}
    assert results["qidian"].success is True
    assert results["fanqie"].success is False


def test_scan_all_all_fail_returns_all_failed_dict():
    """两平台都失败 → scan_all 仍返回 dict,每平台 success=False。"""
    def boom(_url): raise RuntimeError("oops")

    results = scan_all(
        platforms=["qidian", "fanqie"],
        fetchers={"qidian": boom, "fanqie": boom},
    )

    assert all(r.success is False for r in results.values())
    assert set(results.keys()) == {"qidian", "fanqie"}


# ---------------------------------------------------------------------------
# T2: 番茄 API 解析
# ---------------------------------------------------------------------------


def test_parse_fanqie_json_extracts_records_from_data_result():
    """番茄 API 返回 {code, data: {result: [...]}},正确解析。"""
    payload = {
        "code": 0,
        "data": {
            "result": [
                {
                    "book_name": "重生之极品太子爷",
                    "author": "某作者",
                    "category": "都市",
                    "abstract": "重生回到大学时代...",
                    "book_id": "12345",
                },
                {
                    "book_name": "修仙从沙漠开始",
                    "author": "另一作者",
                    "category": "玄幻",
                    "abstract": "大漠孤烟直...",
                    "book_id": "67890",
                },
            ]
        },
    }

    books = parse_fanqie_json(payload)

    assert len(books) == 2
    assert all(isinstance(b, BookEntry) for b in books)

    first = books[0]
    assert first.rank == 1
    assert first.title == "重生之极品太子爷"
    assert first.author == "某作者"
    assert first.category == "都市"
    assert first.abstract.startswith("重生回到大学")
    assert "12345" in first.url


def test_parse_fanqie_json_returns_empty_when_no_result_field():
    """API 返回缺 data.result 时,返回空列表。"""
    books = parse_fanqie_json({"code": 0, "data": {}})
    assert books == []


def test_parse_fanqie_json_skips_records_without_book_name():
    """缺 book_name 的记录跳过。"""
    payload = {
        "data": {
            "result": [
                {"book_name": "正常", "author": "A"},
                {"book_name": "", "author": "B"},
                {"author": "C"},
            ]
        }
    }
    books = parse_fanqie_json(payload)
    assert len(books) == 1
    assert books[0].title == "正常"
