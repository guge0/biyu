"""quickcheck — S-3 T7 ⚡独立快检台(纯本地,零 API 成本)。

复用 auditor.ai_patterns 的 DENSITY_GROUPS 与去重叠命中(只调用,不改阈值/不改词族本体):
- scan_text(text): 任意文本 → 每千字词族密度 + 命中列表(词/偏移/词族/高亮类) + AI 味指数
- 供 ui/quickcheck_routes.py 暴露 POST /api/quickcheck/scan(限长 20 万字)

口径(整改清单 #3):
- 密度按实际汉字数归一,不足千字不再按一千字算(否则短段落少算最多十倍);
- 不足 MIN_RELIABLE_HAN 字时标 low_sample,前端提示"仅供参考";
- 指数:阈值以内最多 30 分,超出阈值后快速上升,三族都"刚好达标"不会被判成重灾区。
"""
from __future__ import annotations

import math
from typing import Any

from biyu.auditor.ai_patterns import DENSITY_GROUPS, find_hits

# 图纸三色高亮:红波浪=缓冲词 / 琥珀底=明喻 / 紫虚线=套话
_HIGHLIGHT_CLASS = {
    "tic_words": "qc-hl-hedge",
    "simile_markers": "qc-hl-simile",
    "cliche_expressions": "qc-hl-cliche",
}

MAX_SCAN_CHARS = 200_000
MIN_RELIABLE_HAN = 300

# 指数分档(前端同步展示)
SCORE_BANDS = ((30, "自然"), (60, "偏重"), (100, "明显 AI 味"))


def _han_count(text: str) -> int:
    return sum(1 for ch in text if "一" <= ch <= "鿿")


def ai_score(families: list[dict[str, Any]]) -> int:
    """0-100,越高越「AI 味重」。阈值以内最多 30 分;超出部分按指数曲线逼近 100。"""
    ratios = [fam["per_kchar"] / fam["limit"] for fam in families if fam.get("limit", 0) > 0]
    if not ratios:
        return 0
    base = 30 * sum(min(r, 1.0) for r in ratios) / len(ratios)
    excess = sum(max(0.0, r - 1.0) for r in ratios)
    return int(round(base + 70 * (1 - math.exp(-excess))))


def score_band(score: int) -> str:
    for upper, label in SCORE_BANDS:
        if score <= upper:
            return label
    return SCORE_BANDS[-1][1]


def scan_text(text: str) -> dict[str, Any]:
    """扫描任意文本,返回雷达结果与高亮命中。纯字面子串统计,零 LLM。"""
    text = text or ""
    han = _han_count(text)
    per_kilo = han / 1000 if han else 0.0

    per_group_terms: dict[str, dict[str, int]] = {group.key: {} for group in DENSITY_GROUPS}
    hits: list[dict[str, Any]] = []
    for offset, length, term, key in find_hits(text):
        terms = per_group_terms[key]
        terms[term] = terms.get(term, 0) + 1
        hits.append({
            "term": term,
            "offset": offset,
            "length": length,
            "family": key,
            "highlight_class": _HIGHLIGHT_CLASS.get(key, "qc-hl-hedge"),
        })

    families: list[dict[str, Any]] = []
    for group in DENSITY_GROUPS:
        per_term = per_group_terms[group.key]
        total = sum(per_term.values())
        per_k = round(total / per_kilo, 2) if per_kilo else 0.0
        families.append({
            "key": group.key,
            "label": group.label,
            "count": total,
            "per_kchar": per_k,
            "limit": group.limit_per_kchar,
            "exceeded": per_k > group.limit_per_kchar,
            "per_term": per_term,
        })
    score = ai_score(families)
    return {
        "chars": len(text),
        "han_chars": han,
        "low_sample": 0 < han < MIN_RELIABLE_HAN,
        "min_reliable_han": MIN_RELIABLE_HAN,
        "score": score,
        "score_band": score_band(score),
        "families": families,
        "hits": hits,
    }
