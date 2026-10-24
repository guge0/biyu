"""quickcheck — S-3 T7 ⚡独立快检台(纯本地,零 API 成本)。

复用 auditor.ai_patterns 的 DENSITY_GROUPS(只调用,不改阈值/不改词族本体):
- scan_text(text): 任意文本 → 每千字词族密度 + 命中列表(词/偏移/词族/高亮类)
- 供 ui/quickcheck_routes.py 暴露 POST /api/quickcheck/scan(限长 20 万字)
"""
from __future__ import annotations

from typing import Any

from biyu.auditor.ai_patterns import DENSITY_GROUPS, count_group

# 图纸三色高亮:红波浪=缓冲词 / 琥珀底=明喻 / 紫虚线=套话
_HIGHLIGHT_CLASS = {
    "tic_words": "qc-hl-hedge",
    "simile_markers": "qc-hl-simile",
    "cliche_expressions": "qc-hl-cliche",
}

MAX_SCAN_CHARS = 200_000


def _han_count(text: str) -> int:
    return sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")


def scan_text(text: str) -> dict[str, Any]:
    """扫描任意文本,返回雷达结果与高亮命中。纯字面子串统计,零 LLM。"""
    text = text or ""
    han = _han_count(text)
    per_kilo = max(han / 1000, 1.0) if han else 0.0

    families: list[dict[str, Any]] = []
    hits: list[dict[str, Any]] = []
    for group in DENSITY_GROUPS:
        per_term_count: dict[str, int] = {}
        for term in group.terms:
            start = 0
            while True:
                idx = text.find(term, start)
                if idx == -1:
                    break
                per_term_count[term] = per_term_count.get(term, 0) + 1
                hits.append({
                    "term": term,
                    "offset": idx,
                    "length": len(term),
                    "family": group.key,
                    "highlight_class": _HIGHLIGHT_CLASS.get(group.key, "qc-hl-hedge"),
                })
                start = idx + len(term)
        total = sum(per_term_count.values())
        per_k = round(total / per_kilo, 2) if per_kilo else 0.0
        families.append({
            "key": group.key,
            "label": group.label,
            "count": total,
            "per_kchar": per_k,
            "limit": group.limit_per_kchar,
            "exceeded": per_k > group.limit_per_kchar,
            "per_term": per_term_count,
        })
    hits.sort(key=lambda h: h["offset"])
    # 简单评分:各词族按超标倍率加权(0-100,越高越「AI 味重」),纯本地口径
    score = 0
    for fam in families:
        if fam["limit"] > 0:
            score += int(min(100, max(0.0, fam["per_kchar"] / fam["limit"]) * 34))
    return {
        "chars": len(text),
        "han_chars": han,
        "score": min(100, score),
        "families": families,
        "hits": hits,
    }
