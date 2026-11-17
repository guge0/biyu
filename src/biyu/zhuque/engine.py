"""降分引擎 — 流程逐段搬自 _s6_ref/jiangfen.py(已验证原型),改为 async + 可注入。

- fix_chapter(text, terms, *, adapter, scorer, on_event): 自动模式。
  定位红窗 → 每窗最多 3 轮、每轮 2 稿 → 过守卫才测分,低于 0.45 即停 →
  仍不过则对最接近的一稿再回译(最多 2 次) → 拼回整章复测(最多 4 遍) →
  顺稿(复测仍过线才采用,整章回红则整体放弃)。不过线的窗保留原文,标「需手改」。
- fix_blind(text, terms, targets=None, *, adapter, on_event): 网页复核模式,不调朱雀。
  按段落边界切成约 260 字的窗,targets 给定时只改这些窗;每窗取第一稿过守卫的回译。

改写前先锁定:标题行/对白/【】标签进 ⟦D⟧,词表专名 + 姓氏组合(X千户/X家这类)
+ 调用方 extra_locks 进 ⟦K⟧;回译稿 clean(去多余空白/半角标点/占位符句号)后再进守卫。

adapter: 任何有 async generate(messages, **kwargs) 的对象(仓内 LLMAdapter 或测试假件);
scorer:  有 async windows(text) 与 async verdict(text) 的对象(朱雀客户端或测试假件);
on_event:同步回调,收引擎进度事件(逐窗 start/done、outer、smooth、终态)。
"""
from __future__ import annotations

import asyncio
import re
import time
from typing import Any, Callable

from .guards import NUM, clean, guard, lock_words, mask, risk_marks, strip_slots, unmask
from .rewrite import back_translate, smooth

PASS = 0.45            # 单窗分数低于此值算过线(朱雀 0.5 算人工,留缓冲)
ROUNDS = 3             # 每窗最多 3 轮
DRAFTS_PER_ROUND = 2   # 每轮 2 稿
OUTER_PASSES = 4       # 整章拼回复测最多 4 遍
SECOND_PASSES = 2      # 仍不过时对最接近的一稿再回译,最多 2 次
CHAPTER_GREEN = 0.999  # 整章复测「人工」占比达到此值才算绿
MIN_BODY = 30          # 剔除占位与空白后不足此长度 = 几乎全是对白,不动
WINDOW_CHARS = 260     # 盲改模式的本地分窗目标长度

OnEvent = Callable[[dict], None]

_SENTENCE_END = re.compile(r"(?<=[。！？!?…])")


class _CountingAdapter:
    """包住注入的 adapter:统计生成次数与累计成本,结果里回报。"""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.generates = 0
        self.cost = 0.0

    async def generate(self, messages: list, **kwargs):
        resp = await self._inner.generate(messages, **kwargs)
        self.generates += 1
        self.cost += float(getattr(resp, "cost", 0.0) or 0.0)
        return resp


def split_windows(text: str, size: int = WINDOW_CHARS) -> list[dict[str, Any]]:
    """按段落边界切成约 size 字的窗(盲改与报告映射共用;确定性,顺序稳定)。

    段落贪心合并到 size;超长段再按句子边界拆。窗口拼接(含换行)与原文完全一致。
    """
    if not text:
        return []
    chunks: list[str] = []
    buf = ""
    for para in text.splitlines(keepends=True):
        if not buf:
            buf = para
        elif len(buf) + len(para) <= size:
            buf += para
        else:
            chunks.append(buf)
            buf = para
    if buf:
        chunks.append(buf)

    pieces: list[str] = []
    for chunk in chunks:
        if len(chunk) <= int(size * 1.6):
            pieces.append(chunk)
            continue
        piece = ""
        for sentence in _SENTENCE_END.split(chunk):
            if piece and len(piece) + len(sentence) > size:
                pieces.append(piece)
                piece = sentence
            else:
                piece += sentence
        if piece:
            pieces.append(piece)

    windows: list[dict[str, Any]] = []
    cursor = 0
    for order, piece in enumerate(pieces, 1):
        start = text.find(piece, cursor)
        if start < 0:
            start = cursor
        cursor = start + len(piece)
        windows.append({"order": order, "start": start, "end": start + len(piece), "text": piece})
    return windows


def _row(before: str, after: str, s0: Any, s1: Any, status: str,
         attempts: list[dict], best_try: dict | None, terms: list[str]) -> dict[str, Any]:
    return {
        "before": before,
        "after": after,
        "s0": s0,
        "s1": s1,
        "status": status,
        "attempts": attempts,
        "best_try": best_try,
        "risks": risk_marks(before, after, terms),
    }


def _lead_tail(text: str) -> "tuple[str, str, str]":
    """(原文本体, 前导空白, 尾随空白)。"""
    stripped = text.strip()
    lead = text[:len(text) - len(text.lstrip())]
    tail = text[len(text.rstrip()):]
    return stripped, lead, tail


def _window_scope(stripped: str, masked: str, allterms: list[str]) -> "tuple[list[str], list[str]]":
    """(本窗专名[守卫与风险标注用,正文里的已被 ⟦K⟧ 锁定], 回译时要求原样保留的中文数字)。"""
    terms = [k for k in allterms if k and k in stripped]
    keep = [x for x in dict.fromkeys(NUM.findall(masked)) if not x.isdigit()]
    return terms, keep


async def _score(scorer: Any, text: str) -> float:
    verdict = await scorer.verdict(text)
    return float(verdict.get("softmax_confidence", 1.0))


async def _fix_window(adapter: _CountingAdapter, scorer: Any, window: dict,
                      allterms: list[str], extra_locks: "list[str] | None" = None) -> dict[str, Any]:
    """改一个红窗(照 jiangfen.fix_window):多稿 → 清洁 → 守卫 → 测分 → 挑最低分。"""
    before = window["text"]
    s0 = window.get("conf", 0.0)
    stripped, lead, tail = _lead_tail(before)
    locks = lock_words(stripped, allterms, extra_locks)
    masked, items, nd = mask(stripped, locks)
    terms, keep = _window_scope(stripped, masked, allterms)
    attempts: list[dict] = []

    if len(strip_slots(masked)) < MIN_BODY:
        return _row(before, before, s0, s0, "几乎全是对白,未动", attempts, None, allterms)

    best: "tuple[float, str] | None" = None   # (分数, 带首尾空白的成稿)
    best_masked: str | None = None            # 最接近的一稿(占位形态)

    for rnd in range(ROUNDS):
        drafts = await asyncio.gather(
            *[back_translate(adapter, masked, keep) for _ in range(DRAFTS_PER_ROUND)]
        )
        for j, raw in enumerate(drafts, 1):
            tag = f"第{rnd + 1}轮第{j}稿"
            out = clean(raw)
            violation = guard(masked, out, terms)
            if violation:
                attempts.append({"tag": tag, "guard": violation})
                continue
            draft = unmask(out, items, nd)
            score = await _score(scorer, draft)
            attempts.append({"tag": tag, "score": round(score, 4)})
            if best is None or score < best[0]:
                best = (score, lead + draft + tail)
                best_masked = out
        if best is not None and best[0] < PASS:
            return _row(before, best[1], s0, round(best[0], 4), "已过线", attempts, None, allterms)

    # 升级手段:对最接近的一稿再回译,最多两次
    current = best_masked
    for _ in range(SECOND_PASSES if current else 0):
        out = clean(await back_translate(adapter, current, keep))
        violation = guard(masked, out, terms)
        if violation:
            attempts.append({"tag": "二次回译", "guard": violation})
            continue
        draft = unmask(out, items, nd)
        score = await _score(scorer, draft)
        attempts.append({"tag": "二次回译", "score": round(score, 4)})
        if best is None or score < best[0]:
            best = (score, lead + draft + tail)
            current = out
        if score < PASS:
            return _row(before, best[1], s0, round(best[0], 4), "已过线(二次回译)", attempts, None, allterms)

    best_try = {"score": round(best[0], 4), "text": best[1]} if best else None
    return _row(before, before, s0, s0, "未过线,需手改", attempts, best_try, allterms)


async def _smooth_pass(adapter: _CountingAdapter, scorer: Any, text: str,
                       allterms: list[str], extra_locks: "list[str] | None" = None
                       ) -> "tuple[str, int, int]":
    """顺稿:逐窗最小改动去翻译腔,复测仍过线才采用。返回 (新文本, 采用数, 总窗数)。"""
    segs = await scorer.windows(text)
    kept = 0
    for w in segs:
        body = w["text"]
        if w.get("conf", 0.0) >= PASS:   # 只顺已过线的窗;红窗留给作者手改(TL 验收修正:原判断写反)
            continue
        stripped, lead, tail = _lead_tail(body)
        locks = lock_words(stripped, allterms, extra_locks)
        masked, items, nd = mask(stripped, locks)
        if len(strip_slots(masked)) < MIN_BODY:
            continue
        out = clean(await smooth(adapter, masked))
        terms, _keep = _window_scope(stripped, masked, allterms)
        if guard(masked, out, terms):
            continue
        draft = unmask(out, items, nd)
        if await _score(scorer, draft) < PASS:
            text = text.replace(body, lead + draft + tail, 1)
            kept += 1
    return text, kept, len(segs)


async def fix_chapter(text: str, terms: list[str], *, adapter: Any, scorer: Any,
                      on_event: OnEvent | None = None, smooth_enabled: bool = True,
                      extra_locks: "list[str] | None" = None) -> dict[str, Any]:
    """自动模式:整章降分。流程与 jiangfen.main 一致。smooth_enabled=False 时跳过顺稿。

    extra_locks:调用方额外传入的锁定词(与词表专名一起进 ⟦K⟧ 占位符)。"""
    started = time.time()
    counter = _CountingAdapter(adapter)

    def emit(event: dict) -> None:
        if on_event is not None:
            on_event(event)

    rows: list[dict[str, Any]] = []
    for outer in range(OUTER_PASSES):
        segs = await scorer.windows(text)
        red = [
            w for w in segs
            if w.get("conf", 0.0) >= PASS
            and not any(r["after"] == w["text"] and r["status"].startswith("未过线") for r in rows)
        ]
        emit({"stage": "outer", "pass_no": outer + 1, "windows": len(segs), "red": len(red)})
        if not red:
            break
        for i, w in enumerate(red, 1):
            emit({"stage": "window", "state": "start", "index": i, "total": len(red), "s0": w.get("conf")})
            row = await _fix_window(counter, scorer, w, terms, extra_locks)
            rows.append(row)
            if row["after"] != w["text"]:
                text = text.replace(w["text"], row["after"], 1)
            emit({"stage": "window", "state": "done", "index": i, "total": len(red),
                  "status": row["status"], "s1": row["s1"]})

    # 顺稿:整章复测仍过线才采用;回红则整体放弃
    pre_smooth = text
    kept, total = 0, 0
    if smooth_enabled:
        text, kept, total = await _smooth_pass(counter, scorer, text, terms, extra_locks)
    smooth_info: dict[str, Any] = {"kept": kept, "total": total, "adopted": bool(smooth_enabled)}
    if total:
        check = await scorer.verdict(text)
        if (check.get("labels_ratio") or {}).get("0", 0.0) < CHAPTER_GREEN:
            text = pre_smooth
            smooth_info = {"kept": 0, "total": total, "adopted": False}
        emit({"stage": "smooth", **smooth_info})

    verdict = await scorer.verdict(text)
    final_windows = await scorer.windows(text)
    return {
        "text": text,
        "rows": rows,
        "windows": final_windows,
        "verdict": verdict,
        "smooth": smooth_info,
        "usage": {
            "generates": counter.generates,
            "cost_cny": round(counter.cost, 6),
            "zhuque_tokens": int(getattr(scorer, "used_tokens", 0) or 0),
        },
        "elapsed_seconds": round(time.time() - started, 1),
    }


async def _blind_window(adapter: _CountingAdapter, window: dict,
                        allterms: list[str], extra_locks: "list[str] | None" = None) -> dict[str, Any]:
    """盲改一个窗:不测分,取第一稿过守卫的回译(最多试 3 稿)。"""
    before = window["text"]
    stripped, lead, tail = _lead_tail(before)
    locks = lock_words(stripped, allterms, extra_locks)
    masked, items, nd = mask(stripped, locks)
    terms, keep = _window_scope(stripped, masked, allterms)
    attempts: list[dict] = []

    if len(strip_slots(masked)) < MIN_BODY:
        return _row(before, before, None, None, "几乎全是对白,未动", attempts, None, allterms)

    last_draft = ""
    for attempt in range(1, ROUNDS + 1):
        out = clean(await back_translate(adapter, masked, keep))
        tag = f"第{attempt}稿"
        violation = guard(masked, out, terms)
        if violation:
            attempts.append({"tag": tag, "guard": violation})
            last_draft = lead + unmask(out, items, nd) + tail
            continue
        attempts.append({"tag": tag, "ok": True})
        return _row(before, lead + unmask(out, items, nd) + tail, None, None,
                    "已回译(未测分)", attempts, None, allterms)
    best_try = {"score": None, "text": last_draft} if last_draft else None
    return _row(before, before, None, None, "未过守卫,需手改", attempts, best_try, allterms)


async def fix_blind(text: str, terms: list[str], targets: list[int] | None = None, *,
                    adapter: Any, on_event: OnEvent | None = None,
                    extra_locks: "list[str] | None" = None) -> dict[str, Any]:
    """网页复核模式:按本地分窗逐窗回译,不调朱雀。targets(1 起窗号)给定时只改这些窗。"""
    started = time.time()
    counter = _CountingAdapter(adapter)
    windows = split_windows(text)
    want = {int(t) for t in targets} if targets else None

    def emit(event: dict) -> None:
        if on_event is not None:
            on_event(event)

    emit({"stage": "outer", "pass": 1, "windows": len(windows), "red": len(want or windows)})
    rows_by_order: dict[int, dict[str, Any]] = {}
    todo = [w for w in windows if want is None or w["order"] in want]
    for i, w in enumerate(todo, 1):
        emit({"stage": "window", "state": "start", "index": i, "total": len(todo), "s0": None})
        row = await _blind_window(counter, w, terms, extra_locks)
        rows_by_order[w["order"]] = {"order": w["order"], **row}
        if row["after"] != w["text"]:
            text = text.replace(w["text"], row["after"], 1)
        emit({"stage": "window", "state": "done", "index": i, "total": len(todo), "status": row["status"]})

    # 没动的窗也进结果(标「未动」),前端才能按窗口渲染整章
    for w in windows:
        if w["order"] not in rows_by_order:
            rows_by_order[w["order"]] = {
                "order": w["order"],
                **_row(w["text"], w["text"], None, None, "未动", [], None, terms),
            }
    rows = [rows_by_order[k] for k in sorted(rows_by_order)]

    emit({"stage": "done", "windows": len(rows)})
    return {
        "text": text,
        "rows": rows,
        "windows": split_windows(text),
        "usage": {
            "generates": counter.generates,
            "cost_cny": round(counter.cost, 6),
            "zhuque_tokens": 0,
        },
        "elapsed_seconds": round(time.time() - started, 1),
    }
