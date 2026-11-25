"""降分引擎 — 流程逐段搬自已验证原型,改为 async + 可注入。

- fix_chapter(text, terms, *, adapter, scorer, on_event, polish_enabled): 自动模式,每红窗三层:
  1. zhzh 中文改中文(r15 写法,示范对来自 pairs.load_pairs,pairs 为空则跳过):
     第 1 轮 3 稿并发;都不过线就拿分最低那稿再改一轮 2 稿;过守卫才测分,任一稿 < PASS 即停。
  2. 回译兜底(r12/jiangfen 写法):只对第一层仍未过线的窗,输入用原窗(不用第一层的稿),
     每窗最多 3 轮、每轮 2 稿,仍不过则对最接近的一稿再回译(最多 2 次)。
  3. polish 小手术:对本次改采用后的每一窗做一次(过守卫且复测仍 < PASS 才替换)。
  拼回整章复测(最多 4 遍)。不过线的窗保留原文,标「需手改」。
- fix_blind(text, terms, targets=None, *, layer, adapter, on_event): 网页复核模式,不调朱雀。
  layer="zhzh":每窗取第一稿过守卫的中文改中文(最多 3 稿;示范对为空自动回落回译);
  layer="bt":现有回译。两种模式采用后都再 polish 一次(过守卫即用,不测分)。
- deai_text(text, terms, *, adapter, on_event): 独立去 AI 味(r13 写法),不进降分流程。
  按 chunks(limit=700) 分块,锁定同降分,每块 deai 一次,守卫不过(篇幅除外)保留原块。

改写前先锁定:标题行/对白/【】标签进 ⟦D⟧,词表专名 + 姓氏组合(X千户/X家这类)
+ 调用方 extra_locks 进 ⟦K⟧;每层输出 clean(去多余空白/半角标点/占位符句号)
再 dedash(去破折号)后再进守卫。

adapter: 任何有 async generate(messages, **kwargs) 的对象(仓内 LLMAdapter 或测试假件);
scorer:  有 async windows(text) 与 async verdict(text) 的对象(朱雀客户端或测试假件);
on_event:同步回调,收引擎进度事件(逐窗 start/layer/done、outer、polish、终态)。
"""
from __future__ import annotations

import asyncio
import re
import time
from typing import Any, Callable

from .guards import NUM, clean, dedash, guard, lock_words, mask, risk_marks, strip_slots, unmask
from .pairs import load_pairs, sample_pairs
from .rewrite import back_translate, deai, polish, zhzh

PASS = 0.45            # 单窗分数低于此值算过线(朱雀 0.5 算人工,留缓冲)
ROUNDS = 3             # 每窗最多 3 轮(回译兜底层与盲改取稿共用)
DRAFTS_PER_ROUND = 2   # 回译每轮 2 稿
ZHZH_DRAFTS_1 = 3      # 中文改中文第 1 轮 3 稿并发(r15)
ZHZH_DRAFTS_2 = 2      # 中文改中文第 2 轮 2 稿(r15:拿最低分那稿再改一轮)
OUTER_PASSES = 4       # 整章拼回复测最多 4 遍
SECOND_PASSES = 2      # 仍不过时对最接近的一稿再回译,最多 2 次
MIN_BODY = 30          # 剔除占位与空白后不足此长度 = 几乎全是对白,不动
WINDOW_CHARS = 260     # 盲改模式的本地分窗目标长度
DEAI_CHUNK_CHARS = 700 # 去.AI 味的分块目标长度(r13)

OnEvent = Callable[[dict], None]

_SENTENCE_END = re.compile(r"(?<=[。！？!?…])")


class _CountingAdapter:
    """包住注入的 adapter:统计生成次数与累计成本;引擎在进每层前设 tag,用量按层回报。"""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.generates = 0
        self.cost = 0.0
        self.tag = ""
        self.by_tag: dict[str, int] = {}

    async def generate(self, messages: list, **kwargs):
        resp = await self._inner.generate(messages, **kwargs)
        self.generates += 1
        self.cost += float(getattr(resp, "cost", 0.0) or 0.0)
        self.by_tag[self.tag] = self.by_tag.get(self.tag, 0) + 1
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
         attempts: list[dict], best_try: dict | None, terms: list[str],
         layer: str = "", polished: bool = False) -> dict[str, Any]:
    return {
        "before": before,
        "after": after,
        "s0": s0,
        "s1": s1,
        "status": status,
        "layer": layer,          # 采用的层:"zhzh" / "bt" / ""(未改)
        "polished": polished,    # 第三层小手术是否被采用
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


def _prepare(body: str, allterms: list[str],
             extra_locks: "list[str] | None" = None) -> "tuple[str, str, str, str, list[str], int, list[str], list[str]]":
    """一段原文的完整预处理(各层共用)。

    返回 (原文本体, 前导空白, 尾随空白, 遮罩文本, 占位原文, 对白占位数,
    本窗专名[守卫与风险标注用], 回译时要求原样保留的中文数字)。
    """
    stripped, lead, tail = _lead_tail(body)
    locks = lock_words(stripped, allterms, extra_locks)
    masked, items, nd = mask(stripped, locks)
    terms = [k for k in allterms if k and k in stripped]
    keep = [x for x in dict.fromkeys(NUM.findall(masked)) if not x.isdigit()]
    return stripped, lead, tail, masked, items, nd, terms, keep


def _judge(masked: str, raw: str, terms: list[str],
           exemplars: "list[str] | None" = None, *, length: bool = True) -> "tuple[str, str]":
    """一层输出的常规处理:clean → dedash → 守卫。返回 (违规原因, 清洁后的占位稿)。"""
    out = dedash(clean(raw))
    return guard(masked, out, terms, exemplars, length=length), out


async def _score(scorer: Any, text: str) -> float:
    verdict = await scorer.verdict(text)
    return float(verdict.get("softmax_confidence", 1.0))


def _exemplars_of(sampled: list[dict]) -> list[str]:
    """示范泄漏守卫用的文本集:本次提示词里带过的全部 src/dst。"""
    return [x for p in sampled for x in (p["src"], p["dst"])]


async def _zhzh_layer(counter: _CountingAdapter, scorer: Any, attempts: list[dict],
                      body: str, allterms: list[str], extra_locks: "list[str] | None",
                      sampled: list[dict]) -> "tuple[float, str] | None":
    """第一层:中文改中文(r15 写法)。第 1 轮 3 稿;都不过线就拿最低分那稿再改一轮 2 稿。

    返回 (最低分, 稿),没有可用稿返回 None。
    """
    exemplars = _exemplars_of(sampled)
    best: "tuple[float, str] | None" = None
    for rnd, n_drafts in ((1, ZHZH_DRAFTS_1), (2, ZHZH_DRAFTS_2)):
        if rnd == 2:
            if best is None or best[0] < PASS:
                break   # 过线不再改;没有可用稿也没得改
            body = best[1]   # 第 2 轮喂第 1 轮分最低那稿(重遮罩,同 r15)
        _stripped, _lead, _tail, masked, items, nd, terms, _keep = _prepare(body, allterms, extra_locks)
        raws = await asyncio.gather(*[zhzh(counter, masked, sampled) for _ in range(n_drafts)])
        for j, raw in enumerate(raws, 1):
            tag = f"中文改写第{rnd}轮第{j}稿"
            violation, out = _judge(masked, raw, terms, exemplars)
            if violation:
                attempts.append({"tag": tag, "guard": violation})
                continue
            draft = unmask(out, items, nd)
            score = await _score(scorer, draft)
            attempts.append({"tag": tag, "score": round(score, 4)})
            if best is None or score < best[0]:
                best = (score, draft)
        if best is not None and best[0] < PASS:
            break
    return best


async def _bt_layer(counter: _CountingAdapter, scorer: Any, attempts: list[dict],
                    masked: str, items: list[str], nd: int,
                    terms: list[str], keep: list[str]) -> "tuple[float, str, bool] | None":
    """第二层:直译式回译(jiangfen 写法,含二次回译)。返回 (最低分, 稿, 是否二次回译稿)。"""
    best: "tuple[float, str] | None" = None
    best_masked: str | None = None

    for rnd in range(ROUNDS):
        drafts = await asyncio.gather(
            *[back_translate(counter, masked, keep) for _ in range(DRAFTS_PER_ROUND)]
        )
        for j, raw in enumerate(drafts, 1):
            tag = f"回译第{rnd + 1}轮第{j}稿"
            violation, out = _judge(masked, raw, terms)
            if violation:
                attempts.append({"tag": tag, "guard": violation})
                continue
            draft = unmask(out, items, nd)
            score = await _score(scorer, draft)
            attempts.append({"tag": tag, "score": round(score, 4)})
            if best is None or score < best[0]:
                best = (score, draft)
                best_masked = out
        if best is not None and best[0] < PASS:
            return (*best, False)

    # 升级手段:对最接近的一稿再回译,最多两次
    current = best_masked
    for _ in range(SECOND_PASSES if current else 0):
        violation, out = _judge(masked, await back_translate(counter, current, keep), terms)
        if violation:
            attempts.append({"tag": "二次回译", "guard": violation})
            continue
        draft = unmask(out, items, nd)
        score = await _score(scorer, draft)
        attempts.append({"tag": "二次回译", "score": round(score, 4)})
        if best is None or score < best[0]:
            best = (score, draft)
            current = out
        if score < PASS:
            return (*best, True)
    return (*best, False) if best else None


async def _polish_body(counter: _CountingAdapter, body: str, allterms: list[str],
                       extra_locks: "list[str] | None") -> "tuple[str | None, str]":
    """小手术一次:clean/dedash/守卫。返回 (改后稿, 违规原因);守卫不过时改后稿为 None。"""
    _stripped, _lead, _tail, masked, items, nd, terms, _keep = _prepare(body, allterms, extra_locks)
    violation, out = _judge(masked, await polish(counter, masked), terms)
    if violation:
        return None, violation
    return unmask(out, items, nd), ""


async def _fix_window(counter: _CountingAdapter, scorer: Any, window: dict,
                      allterms: list[str], extra_locks: "list[str] | None", pairs: list[dict],
                      polish_enabled: bool, polish_stat: dict[str, int],
                      idx: int, total: int, emit: Callable[[dict], None]) -> dict[str, Any]:
    """改一个红窗:三层接力。采用哪层记进 row.layer;采用后再做一次小手术。"""
    before = window["text"]
    s0 = window.get("conf", 0.0)
    stripped, lead, tail, masked, items, nd, terms, keep = _prepare(before, allterms, extra_locks)
    attempts: list[dict] = []

    if len(strip_slots(masked)) < MIN_BODY:
        return _row(before, before, s0, s0, "几乎全是对白,未动", attempts, None, allterms)

    adopted: "tuple[float, str] | None" = None   # 采用的 (分数, 稿)
    closest: "tuple[float, str] | None" = None   # 全层最接近的一稿(未过线时的 best_try)
    layer_used = ""
    status = "已过线"

    # 第一层:中文改中文(示范对为空,或本窗剔除后没有可用示范 → 跳过)
    sampled = sample_pairs(pairs, stripped)
    if sampled:
        emit({"stage": "window", "state": "layer", "layer": "zhzh", "index": idx, "total": total})
        counter.tag = "zhzh"
        zbest = await _zhzh_layer(counter, scorer, attempts, stripped, allterms, extra_locks, sampled)
        if zbest is not None:
            if closest is None or zbest[0] < closest[0]:
                closest = zbest
            if zbest[0] < PASS:
                adopted, layer_used, status = zbest, "zhzh", "已过线(中文改写)"

    # 第二层:回译兜底,只对第一层仍未过线的窗;输入用原窗,不用第一层的稿
    if adopted is None:
        emit({"stage": "window", "state": "layer", "layer": "bt", "index": idx, "total": total})
        counter.tag = "bt"
        bbest = await _bt_layer(counter, scorer, attempts, masked, items, nd, terms, keep)
        if bbest is not None:
            if closest is None or bbest[0] < closest[0]:
                closest = (bbest[0], bbest[1])
            if bbest[0] < PASS:
                adopted = (bbest[0], bbest[1])
                layer_used = "bt"
                status = "已过线(二次回译)" if bbest[2] else "已过线"

    if adopted is None:
        best_try = {"score": round(closest[0], 4), "text": lead + closest[1] + tail} if closest else None
        return _row(before, before, s0, s0, "未过线,需手改", attempts, best_try, allterms)

    # 第三层:小手术(过守卫且复测仍 < PASS 才替换)
    s1 = round(adopted[0], 4)
    after_body = adopted[1]
    polished = False
    if polish_enabled:
        emit({"stage": "window", "state": "layer", "layer": "polish", "index": idx, "total": total})
        counter.tag = "polish"
        polish_stat["tried"] += 1
        cand, violation = await _polish_body(counter, after_body, allterms, extra_locks)
        if cand is None:
            attempts.append({"tag": "小手术", "guard": violation})
        else:
            score = await _score(scorer, cand)
            if score < PASS:
                attempts.append({"tag": "小手术", "score": round(score, 4)})
                after_body, polished, s1 = cand, True, round(score, 4)
                polish_stat["kept"] += 1
            else:
                attempts.append({"tag": "小手术", "score": round(score, 4), "kept": False})

    return _row(before, lead + after_body + tail, s0, s1, status, attempts, None,
                allterms, layer_used, polished)


async def fix_chapter(text: str, terms: list[str], *, adapter: Any, scorer: Any,
                      on_event: OnEvent | None = None, polish_enabled: bool = True,
                      extra_locks: "list[str] | None" = None) -> dict[str, Any]:
    """自动模式:整章降分。polish_enabled=False 时跳过第三层小手术。

    extra_locks:调用方额外传入的锁定词(与词表专名一起进 ⟦K⟧ 占位符)。
    """
    started = time.time()
    counter = _CountingAdapter(adapter)
    _version, pairs = load_pairs()
    polish_stat = {"kept": 0, "tried": 0}

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
            row = await _fix_window(counter, scorer, w, terms, extra_locks, pairs,
                                    polish_enabled, polish_stat, i, len(red), emit)
            rows.append(row)
            if row["after"] != w["text"]:
                text = text.replace(w["text"], row["after"], 1)
            emit({"stage": "window", "state": "done", "index": i, "total": len(red),
                  "status": row["status"], "s1": row["s1"]})

    if polish_stat["tried"]:
        emit({"stage": "polish", **polish_stat})

    verdict = await scorer.verdict(text)
    final_windows = await scorer.windows(text)
    return {
        "text": text,
        "rows": rows,
        "windows": final_windows,
        "verdict": verdict,
        "polish": dict(polish_stat),
        "usage": {
            "zhzh": counter.by_tag.get("zhzh", 0),
            "bt": counter.by_tag.get("bt", 0),
            "polish": counter.by_tag.get("polish", 0),
            "generates": counter.generates,
            "cost_cny": round(counter.cost, 6),
            "zhuque_tokens": int(getattr(scorer, "used_tokens", 0) or 0),
        },
        "elapsed_seconds": round(time.time() - started, 1),
    }


async def _blind_window(counter: _CountingAdapter, window: dict,
                        allterms: list[str], extra_locks: "list[str] | None",
                        layer: str, pairs: list[dict],
                        idx: int, total: int, emit: Callable[[dict], None]) -> dict[str, Any]:
    """盲改一个窗:不测分,取第一稿过守卫的改写(最多试 3 稿),采用后再 polish 一次。"""
    before = window["text"]
    stripped, lead, tail, masked, items, nd, terms, keep = _prepare(before, allterms, extra_locks)
    attempts: list[dict] = []

    if len(strip_slots(masked)) < MIN_BODY:
        return _row(before, before, None, None, "几乎全是对白,未动", attempts, None, allterms)

    mode = layer
    sampled: list[dict] = []
    if layer == "zhzh":
        sampled = sample_pairs(pairs, stripped)
        if not sampled:
            mode = "bt"   # 本窗示范全被剔除,这一窗回落回译
    emit({"stage": "window", "state": "layer", "layer": mode, "index": idx, "total": total})

    adopted: str | None = None
    status = ""
    last_draft = ""
    exemplars = _exemplars_of(sampled) if mode == "zhzh" else None
    for attempt in range(1, ROUNDS + 1):
        counter.tag = "zhzh" if mode == "zhzh" else "bt"
        raw = (await zhzh(counter, masked, sampled) if mode == "zhzh"
               else await back_translate(counter, masked, keep))
        tag = f"中文改写第{attempt}稿" if mode == "zhzh" else f"回译第{attempt}稿"
        violation, out = _judge(masked, raw, terms, exemplars)
        if violation:
            attempts.append({"tag": tag, "guard": violation})
            last_draft = unmask(out, items, nd)
            continue
        attempts.append({"tag": tag, "ok": True})
        adopted = unmask(out, items, nd)
        status = "已改写(未测分)" if mode == "zhzh" else "已回译(未测分)"
        break

    if adopted is None:
        best_try = {"score": None, "text": lead + last_draft + tail} if last_draft else None
        return _row(before, before, None, None, "未过守卫,需手改", attempts, best_try,
                    allterms, mode, False)

    # 采用后再 polish 一次:过守卫即用,不测分
    emit({"stage": "window", "state": "layer", "layer": "polish", "index": idx, "total": total})
    counter.tag = "polish"
    polished = False
    cand, violation = await _polish_body(counter, adopted, allterms, extra_locks)
    if cand is not None:
        adopted, polished = cand, True
    else:
        attempts.append({"tag": "小手术", "guard": violation})
    return _row(before, lead + adopted + tail, None, None, status, attempts, None,
                allterms, mode, polished)


async def fix_blind(text: str, terms: list[str], targets: list[int] | None = None, *,
                    layer: str = "zhzh", adapter: Any, on_event: OnEvent | None = None,
                    extra_locks: "list[str] | None" = None) -> dict[str, Any]:
    """网页复核模式:按本地分窗逐窗改写,不调朱雀。targets(1 起窗号)给定时只改这些窗。

    layer="zhzh" 用中文改中文(示范对为空自动回落回译);layer="bt" 用直译式回译。
    作者网页复核后,对仍红的窗可用 targets + layer="bt" 再跑一遍。
    """
    started = time.time()
    counter = _CountingAdapter(adapter)
    _version, pairs = load_pairs()
    if layer == "zhzh" and not pairs:
        layer = "bt"
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
        row = await _blind_window(counter, w, terms, extra_locks, layer, pairs, i, len(todo), emit)
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
            "zhzh": counter.by_tag.get("zhzh", 0),
            "bt": counter.by_tag.get("bt", 0),
            "polish": counter.by_tag.get("polish", 0),
            "generates": counter.generates,
            "cost_cny": round(counter.cost, 6),
            "zhuque_tokens": 0,
        },
        "elapsed_seconds": round(time.time() - started, 1),
    }


# ---------------------------------------------------------------------------
# 独立去 AI 味(不进降分流程;付费功能,路由层过 _license_block 闸)
# ---------------------------------------------------------------------------

def _deai_sep(text: str) -> str:
    """段落分隔符:优先空行(r13 口径);全文没有空行时退到单换行,免得整章挤成一块。"""
    return "\n\n" if "\n\n" in text else "\n"


def _deai_chunks(text: str, limit: int = DEAI_CHUNK_CHARS) -> list[str]:
    """按 r13 的 chunks 分块:段落贪心合并到约 limit 字;单段超长自成一块。"""
    sep = _deai_sep(text)
    groups: list[list[str]] = []
    cur: list[str] = []
    cur_len = 0
    for para in text.split(sep):
        if cur and cur_len + len(para) > limit:
            groups.append(cur)
            cur, cur_len = [], 0
        cur.append(para)
        cur_len += len(para)
    if cur:
        groups.append(cur)
    return [sep.join(group) for group in groups]


async def _deai_chunk(counter: _CountingAdapter, chunk: str, allterms: list[str]) -> dict[str, Any]:
    """去一块 AI 味:锁定同降分;守卫(篇幅除外)不过保留原块。"""
    before = chunk
    _stripped, lead, tail, masked, items, nd, terms, _keep = _prepare(chunk, allterms, None)
    if len(strip_slots(masked)) < MIN_BODY:
        return _row(before, before, None, None, "未动", [], None, allterms)
    violation, out = _judge(masked, await deai(counter, masked), terms, length=False)
    if violation:
        return _row(before, before, None, None, "未过守卫,保留原文",
                    [{"tag": "去AI味", "guard": violation}], None, allterms)
    return _row(before, lead + unmask(out, items, nd) + tail, None, None, "已去AI味",
                [{"tag": "去AI味", "ok": True}], None, allterms)


async def deai_text(text: str, terms: list[str], *, adapter: Any,
                    on_event: OnEvent | None = None) -> dict[str, Any]:
    """独立去 AI 味(r13 写法):分块 → 锁定 → 每块 deai 一次 → 守卫不过保留原块。"""
    started = time.time()
    counter = _CountingAdapter(adapter)
    counter.tag = "deai"

    def emit(event: dict) -> None:
        if on_event is not None:
            on_event(event)

    chunks = _deai_chunks(text)
    rows: list[dict[str, Any]] = []
    parts: list[str] = []
    for i, chunk in enumerate(chunks, 1):
        emit({"stage": "window", "state": "start", "index": i, "total": len(chunks), "s0": None})
        row = await _deai_chunk(counter, chunk, terms)
        rows.append({"order": i, **row})
        parts.append(row["after"])
        emit({"stage": "window", "state": "done", "index": i, "total": len(chunks),
              "status": row["status"]})

    emit({"stage": "done", "windows": len(rows)})
    return {
        "text": _deai_sep(text).join(parts),
        "rows": rows,
        "usage": {
            "generates": counter.generates,
            "cost_cny": round(counter.cost, 6),
            "zhuque_tokens": 0,
        },
        "elapsed_seconds": round(time.time() - started, 1),
    }
