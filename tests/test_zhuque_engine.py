"""S-8-1 · 降分引擎契约:假 adapter(按 system 提示词分层)+ 假 scorer,全离线。

覆盖:第一层过线不走第二层 / 第一层不过走第二层且输入用原窗 / pairs 为空跳过第一层 /
zhzh 第 2 轮喂最低分稿 / polish 复测回红不采用 / polish 守卫失败保留原稿 /
polish 只作用于本次采用的窗 / 回译层既有行为(过线即停、多轮、二次回译、始终不过) /
fix_blind 的 zhzh 与 bt 两种模式(含示范对为空回落)/ deai_text 分块与守卫失败保留。
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from biyu.zhuque import engine, rewrite
from biyu.zhuque.engine import deai_text, fix_blind, fix_chapter, split_windows

# 基准窗口:约 38 字叙述、无对白(超过 30 字「几乎全对白」门槛);
# 改写稿只要长度在 0.7–1.7 之间、句读齐全就能过守卫
W = "常野躺在草料堆上一笔一笔数账，把今天的开销和进项都记了三页纸，吹熄了灯。"
FIXED = "常野躺在草料堆上一遍一遍数账，把当天的开销和进项记满了三页纸，然后吹灯。"
FIXED_POLISHED = "常野躺在草料堆上一遍一遍数账，当天的开销和进项记满三页纸，然后吹灯。"
DRAFT_A = "常野躺在草料堆上数着账，当天的开销和进项记下三页纸了，他才吹灯。"
DRAFT_B = "常野躺在草料堆上数过账，开销与进项记了三页纸，随后吹熄灯。"
GREEN = {"softmax_confidence": 0.1, "labels_ratio": {"0": 1.0, "1": 0.0, "2": 0.0}}

# 示范对(与各测试窗无 12 字以上重合,抽样不会被剔除)
PAIR_SRC = "他猫着腰钻进柴房，把半袋糙米挪到了墙角。"
PAIR_DST = "他弯腰进了柴房，把半袋糙米挪到墙角那里。"
PAIRS = [{"src": PAIR_SRC, "dst": PAIR_DST, "note": ""}]


def _classify(system: str) -> str:
    if system.startswith("Translate this Chinese"):
        return "bt_en"
    if system.startswith("把下面的英文直译成中文"):
        return "bt_zh"
    if system.startswith(rewrite.SYS_ZHZH_HEAD[:12]):
        return "zhzh"
    if system == rewrite.SYS_POLISH:
        return "polish"
    if system.endswith(rewrite.DEAI_WRAP):
        return "deai"
    raise AssertionError("认不出的 system 提示词: " + system[:40])


class LayerAdapter:
    """按 system 提示词分层的假模型:每层一条输出队列(耗尽返 ""),记录全部调用。"""

    def __init__(self) -> None:
        self.queues: dict[str, list[str]] = {k: [] for k in
                                             ("zhzh", "bt_en", "bt_zh", "polish", "deai")}
        self.calls: list[tuple[str, str]] = []   # (层, user 正文)

    def feed(self, kind: str, *outputs: str) -> "LayerAdapter":
        self.queues[kind].extend(outputs)
        return self

    async def generate(self, messages: list, **kwargs):
        kind = _classify(messages[0]["content"])
        self.calls.append((kind, messages[1]["content"]))
        text = self.queues[kind].pop(0) if self.queues[kind] else ""
        return SimpleNamespace(text=text, cost=0.001)

    def users(self, kind: str) -> list[str]:
        return [user for k, user in self.calls if k == kind]

    def count(self, kind: str) -> int:
        return sum(1 for k, _ in self.calls if k == kind)


class FakeScorer:
    """windows(text) 按 red_when 判红;verdict(text) 按队列吐分(耗尽回绿)。"""

    def __init__(self, red_when, verdicts: list[dict]):
        self.red_when = red_when
        self.verdicts = list(verdicts)
        self.verdict_calls = 0
        self.windows_calls = 0

    async def windows(self, text: str) -> list[dict[str, Any]]:
        self.windows_calls += 1
        conf = 0.8 if self.red_when(text) else 0.1
        return [{"order": 1, "start": 0, "end": len(text), "text": text, "conf": conf, "label": 1}]

    async def verdict(self, text: str) -> dict[str, Any]:
        self.verdict_calls += 1
        value = self.verdicts.pop(0) if self.verdicts else GREEN
        return value(text) if callable(value) else value


def _run(coro):
    return asyncio.run(coro)


def _use_pairs(monkeypatch, pairs) -> None:
    monkeypatch.setattr(engine, "load_pairs", lambda: ("test-0", list(pairs)))


# ---------- 第一层:中文改中文 ----------

def test_zhzh_first_layer_pass_skips_bt(monkeypatch) -> None:
    """第一层就过线:第 1 轮 3 稿全部测完取最低,不再走第二层。"""
    _use_pairs(monkeypatch, PAIRS)
    adapter = LayerAdapter().feed("zhzh", FIXED, DRAFT_A, DRAFT_B)
    scorer = FakeScorer(lambda t: t == W, [
        {"softmax_confidence": 0.2}, {"softmax_confidence": 0.3}, {"softmax_confidence": 0.4},
        GREEN,
    ])
    result = _run(fix_chapter(W, [], adapter=adapter, scorer=scorer, polish_enabled=False))
    row = result["rows"][0]
    assert row["status"] == "已过线(中文改写)" and row["layer"] == "zhzh"
    assert row["s1"] == 0.2 and row["after"] == FIXED
    assert adapter.count("zhzh") == 3                       # 第 1 轮 3 稿,没有第 2 轮
    assert adapter.count("bt_en") == 0 and adapter.count("bt_zh") == 0
    assert result["usage"]["zhzh"] == 3 and result["usage"]["bt"] == 0
    assert [a["tag"] for a in row["attempts"]] == ["中文改写第1轮第1稿", "中文改写第1轮第2稿", "中文改写第1轮第3稿"]


def test_zhzh_second_round_feeds_lowest_draft(monkeypatch) -> None:
    """第 1 轮都不过线:拿分最低那稿(0.6 的 DRAFT_A)再改一轮 2 稿。"""
    _use_pairs(monkeypatch, PAIRS)
    adapter = LayerAdapter().feed("zhzh", DRAFT_A, FIXED, DRAFT_B, DRAFT_B, FIXED)
    scorer = FakeScorer(lambda t: t == W, [
        {"softmax_confidence": 0.6}, {"softmax_confidence": 0.8}, {"softmax_confidence": 0.7},  # 第 1 轮
        {"softmax_confidence": 0.5}, {"softmax_confidence": 0.3},                                # 第 2 轮
        GREEN,
    ])
    result = _run(fix_chapter(W, [], adapter=adapter, scorer=scorer, polish_enabled=False))
    row = result["rows"][0]
    assert row["status"] == "已过线(中文改写)" and row["s1"] == 0.3
    assert adapter.count("zhzh") == 5
    users = adapter.users("zhzh")
    assert users[0] == W                    # 第 1 轮吃原窗
    assert users[3] == DRAFT_A              # 第 2 轮吃分最低那稿(重遮罩)


def test_zhzh_fail_falls_to_bt_with_original_window(monkeypatch) -> None:
    """第一层 5 稿全不过线 → 第二层回译,输入用原窗(不是第一层的稿)。"""
    _use_pairs(monkeypatch, PAIRS)
    adapter = (LayerAdapter()
               .feed("zhzh", DRAFT_A, DRAFT_B, FIXED, DRAFT_A, FIXED)   # 全部 ≥ PASS
               .feed("bt_en", "en1", "en2")
               .feed("bt_zh", DRAFT_A, FIXED))
    scorer = FakeScorer(lambda t: t == W, [
        *[{"softmax_confidence": s} for s in (0.8, 0.7, 0.75, 0.72, 0.74)],   # zhzh 5 稿
        {"softmax_confidence": 0.5}, {"softmax_confidence": 0.2},             # 回译第 1 轮 2 稿
        GREEN,
    ])
    result = _run(fix_chapter(W, [], adapter=adapter, scorer=scorer, polish_enabled=False))
    row = result["rows"][0]
    assert row["status"] == "已过线" and row["layer"] == "bt" and row["s1"] == 0.2
    assert adapter.users("bt_en")[0] == W    # 回译吃的是原窗遮罩,不是第一层的稿
    assert adapter.count("zhzh") == 5 and adapter.count("bt_en") == 2


def test_empty_pairs_skips_zhzh_layer(monkeypatch) -> None:
    """pairs 为空:第一层整层跳过,第一口就是回译的中→英。"""
    _use_pairs(monkeypatch, [])
    adapter = LayerAdapter().feed("bt_en", "en").feed("bt_zh", FIXED)
    scorer = FakeScorer(lambda t: t == W, [{"softmax_confidence": 0.2}, GREEN])
    result = _run(fix_chapter(W, [], adapter=adapter, scorer=scorer, polish_enabled=False))
    assert result["rows"][0]["layer"] == "bt"
    assert adapter.calls[0][0] == "bt_en" and adapter.count("zhzh") == 0


# ---------- 第三层:polish 小手术 ----------

def test_polish_adopted_when_retest_still_passes(monkeypatch) -> None:
    """polish 过守卫且复测仍 < PASS:替换采用,polished=True,用量按层计。"""
    _use_pairs(monkeypatch, PAIRS)
    adapter = (LayerAdapter()
               .feed("zhzh", FIXED, DRAFT_A, DRAFT_B)
               .feed("polish", FIXED_POLISHED))
    scorer = FakeScorer(lambda t: t == W, [
        {"softmax_confidence": 0.2}, {"softmax_confidence": 0.3}, {"softmax_confidence": 0.4},
        {"softmax_confidence": 0.15},   # 小手术复测仍过线 → 采用
        GREEN,
    ])
    result = _run(fix_chapter(W, [], adapter=adapter, scorer=scorer))
    row = result["rows"][0]
    assert row["polished"] is True and row["after"] == FIXED_POLISHED and row["s1"] == 0.15
    assert result["polish"] == {"kept": 1, "tried": 1}
    assert result["usage"]["polish"] == 1
    assert adapter.users("polish") == [FIXED]   # 小手术吃采用后的稿(重遮罩)


def test_polish_reverted_when_retest_red(monkeypatch) -> None:
    """polish 复测回红(≥ PASS):不采用,保留 polish 前的稿。"""
    _use_pairs(monkeypatch, PAIRS)
    adapter = (LayerAdapter()
               .feed("zhzh", FIXED, DRAFT_A, DRAFT_B)
               .feed("polish", FIXED_POLISHED))
    scorer = FakeScorer(lambda t: t == W, [
        {"softmax_confidence": 0.2}, {"softmax_confidence": 0.3}, {"softmax_confidence": 0.4},
        {"softmax_confidence": 0.6},    # 小手术复测回红 → 不采用
        GREEN,
    ])
    result = _run(fix_chapter(W, [], adapter=adapter, scorer=scorer))
    row = result["rows"][0]
    assert row["polished"] is False and row["after"] == FIXED and row["s1"] == 0.2
    assert result["polish"] == {"kept": 0, "tried": 1}
    assert row["attempts"][-1] == {"tag": "小手术", "score": 0.6, "kept": False}


def test_polish_guard_fail_keeps_draft(monkeypatch) -> None:
    """polish 稿被守卫拦下:保留 polish 前的稿,attempts 记守卫原因。"""
    _use_pairs(monkeypatch, PAIRS)
    adapter = (LayerAdapter()
               .feed("zhzh", FIXED, DRAFT_A, DRAFT_B)
               .feed("polish", "“顺手编了一句对白。”"))
    scorer = FakeScorer(lambda t: t == W, [
        {"softmax_confidence": 0.2}, {"softmax_confidence": 0.3}, {"softmax_confidence": 0.4},
        GREEN,
    ])
    result = _run(fix_chapter(W, [], adapter=adapter, scorer=scorer))
    row = result["rows"][0]
    assert row["polished"] is False and row["after"] == FIXED
    assert row["attempts"][-1] == {"tag": "小手术", "guard": "自造对白"}
    assert scorer.verdict_calls == 4   # 3 稿测分 + 终判,守卫拦下的稿不测分


def test_polish_only_touches_changed_windows(monkeypatch) -> None:
    """polish 只作用于本次改采用后的窗:未过线的窗与没进改写的绿窗都不 polish。"""
    _use_pairs(monkeypatch, [])
    adapter = LayerAdapter().feed("bt_en", *["e"] * 8).feed("bt_zh", *[DRAFT_A, DRAFT_B] * 4)
    scorer = FakeScorer(lambda t: True, [*({"softmax_confidence": 0.9} for _ in range(8)), GREEN])
    result = _run(fix_chapter(W, [], adapter=adapter, scorer=scorer))
    row = result["rows"][0]
    assert row["status"] == "未过线,需手改" and row["polished"] is False
    assert adapter.count("polish") == 0          # 没采用过任何稿,一次小手术都不做
    assert result["polish"] == {"kept": 0, "tried": 0}
    assert result["text"] == W


# ---------- 第二层:回译兜底(pairs 为空时的既有行为) ----------

def test_bt_first_round_pass_stops_immediately(monkeypatch) -> None:
    """首稿过线即停:不再进第二轮。"""
    _use_pairs(monkeypatch, [])
    adapter = LayerAdapter().feed("bt_en", "e", "e").feed("bt_zh", FIXED, DRAFT_A)
    scorer = FakeScorer(lambda t: t == W, [
        {"softmax_confidence": 0.2}, {"softmax_confidence": 0.3}, GREEN,
    ])
    result = _run(fix_chapter(W, [], adapter=adapter, scorer=scorer, polish_enabled=False))
    row = result["rows"][0]
    assert row["status"] == "已过线" and row["s1"] == 0.2 and "记满" in row["after"]
    assert adapter.count("bt_en") == 2          # 一轮两稿,没有第二轮
    assert scorer.verdict_calls == 3            # 两稿测分 + 终判


def test_bt_passes_after_multiple_rounds(monkeypatch) -> None:
    """第一轮两稿都不过,第二轮才过线。"""
    _use_pairs(monkeypatch, [])
    adapter = (LayerAdapter()
               .feed("bt_en", "e1", "e2", "e3", "e4")
               .feed("bt_zh", DRAFT_A, DRAFT_B, DRAFT_A, FIXED))
    scorer = FakeScorer(lambda t: t == W, [
        {"softmax_confidence": 0.8}, {"softmax_confidence": 0.75},   # 第一轮两稿
        {"softmax_confidence": 0.6}, {"softmax_confidence": 0.3},    # 第二轮两稿
        GREEN,
    ])
    result = _run(fix_chapter(W, [], adapter=adapter, scorer=scorer, polish_enabled=False))
    row = result["rows"][0]
    assert row["status"] == "已过线" and row["s1"] == 0.3
    assert len(row["attempts"]) == 4 and adapter.count("bt_en") == 4
    assert [a["tag"] for a in row["attempts"]][:2] == ["回译第1轮第1稿", "回译第1轮第2稿"]


def test_bt_passes_after_second_back_translation(monkeypatch) -> None:
    """三轮全不过,对最接近的一稿再回译才过线。"""
    _use_pairs(monkeypatch, [])
    adapter = (LayerAdapter()
               .feed("bt_en", *["e"] * 8).feed("bt_zh", *[DRAFT_A, DRAFT_B] * 4))
    scorer = FakeScorer(lambda t: t == W, [
        *({"softmax_confidence": 0.9} for _ in range(6)),            # 三轮两稿全 0.9
        {"softmax_confidence": 0.55},                                # 二次回译 1:变好没过线
        {"softmax_confidence": 0.2},                                 # 二次回译 2:过线
        GREEN,
    ])
    result = _run(fix_chapter(W, [], adapter=adapter, scorer=scorer, polish_enabled=False))
    row = result["rows"][0]
    assert row["status"] == "已过线(二次回译)" and row["s1"] == 0.2
    assert adapter.count("bt_en") == 8   # 6 稿 + 2 次二次回译


def test_bt_never_passes_keeps_original_with_best_try(monkeypatch) -> None:
    """始终不过:保留原文标「需手改」,带上全层最接近的一稿。"""
    _use_pairs(monkeypatch, PAIRS)
    adapter = (LayerAdapter()
               .feed("zhzh", DRAFT_A, DRAFT_B, FIXED, DRAFT_A, FIXED)
               .feed("bt_en", *["e"] * 8).feed("bt_zh", *[DRAFT_A, DRAFT_B] * 4))
    scorer = FakeScorer(lambda t: True, [
        *({"softmax_confidence": 0.95} for _ in range(5)),           # zhzh 5 稿全不过
        *({"softmax_confidence": 0.9} for _ in range(6)),            # 回译三轮全不过
        {"softmax_confidence": 0.85}, {"softmax_confidence": 0.88},  # 二次回译也不过
        GREEN,
    ])
    result = _run(fix_chapter(W, [], adapter=adapter, scorer=scorer))
    row = result["rows"][0]
    assert row["status"] == "未过线,需手改"
    assert row["after"] == row["before"] == W
    assert row["best_try"]["score"] == 0.85       # 回译二次 0.85 比 zhzh 全稿都低
    assert result["text"] == W and adapter.count("polish") == 0


def test_bt_guard_rejected_draft_is_not_scored(monkeypatch) -> None:
    """守卫拦截的稿不测分:坏稿只记守卫原因,不消耗朱雀调用。"""
    _use_pairs(monkeypatch, [])
    adapter = LayerAdapter().feed("bt_en", "e1", "e2").feed("bt_zh", "“自造了对白。”", FIXED)
    scorer = FakeScorer(lambda t: t == W, [
        {"softmax_confidence": 0.2},   # 只有第二稿被测分
        GREEN,
    ])
    result = _run(fix_chapter(W, [], adapter=adapter, scorer=scorer, polish_enabled=False))
    row = result["rows"][0]
    assert row["attempts"][0]["guard"] == "自造对白"
    assert "score" not in row["attempts"][0]
    assert row["status"] == "已过线"
    assert scorer.verdict_calls == 2


def test_dialogue_heavy_window_left_untouched(monkeypatch) -> None:
    """几乎全是对白的窗直接标「未动」,不花生成。"""
    _use_pairs(monkeypatch, PAIRS)
    window = "“开门！”“是我。”“快进来。”"
    adapter = LayerAdapter()
    scorer = FakeScorer(lambda t: True, [GREEN])
    result = _run(fix_chapter(window, [], adapter=adapter, scorer=scorer))
    row = result["rows"][0]
    assert row["status"] == "几乎全是对白,未动" and row["layer"] == "" and row["polished"] is False
    assert adapter.calls == []


def test_engine_emits_progress_events(monkeypatch) -> None:
    """进度事件:outer / window start / window layer / window done / polish。"""
    _use_pairs(monkeypatch, PAIRS)
    adapter = (LayerAdapter()
               .feed("zhzh", FIXED, DRAFT_A, DRAFT_B)
               .feed("polish", FIXED_POLISHED))
    scorer = FakeScorer(lambda t: t == W, [
        {"softmax_confidence": 0.2}, {"softmax_confidence": 0.3}, {"softmax_confidence": 0.4},
        {"softmax_confidence": 0.15},
        GREEN,
    ])
    events: list[dict] = []
    _run(fix_chapter(W, [], adapter=adapter, scorer=scorer, on_event=events.append))
    stages = [e["stage"] for e in events]
    assert stages[0] == "outer" and "window" in stages and "polish" in stages
    layers = [e.get("layer") for e in events if e.get("state") == "layer"]
    assert layers == ["zhzh", "polish"]
    done = [e for e in events if e.get("stage") == "window" and e.get("state") == "done"]
    assert done and done[0]["status"] == "已过线(中文改写)"


# ---------- fix_blind:zhzh / bt 两种模式 ----------

# 三段各 190 字上下:相邻两段相加超过 260 字上限,必成独立窗
_BASE1 = "干草垛扎得后背发痒。常野挠了挠背，仰面躺在草料堆顶上，左手举着半截账册，右手捏着根烧剩的柳木炭条，在泛黄的麻纸背面一笔一划地描账。"
_BASE2 = "南城旧武馆后院静得可怕。院墙外脚步声越来越近，张今空屏住呼吸，把短刀往袖口里又收了一寸，盯着门缝里透进来的那道光。"
_BASE3 = "方圆端着茶碗走过来，脚步放得很轻。她在离他三步远的地方站定，看了一眼那半本账册，又看了一眼他手背上的墨痕，什么也没说。"
P1, P2, P3 = _BASE1 * 3, _BASE2 * 4, _BASE3 * 4
BLIND_TEXT = P1 + "\n" + P2 + "\n" + P3


def test_split_windows_covers_text_in_order() -> None:
    windows = split_windows(BLIND_TEXT)
    assert "".join(w["text"] for w in windows) == BLIND_TEXT
    assert [w["order"] for w in windows] == list(range(1, len(windows) + 1))
    assert all(w["end"] - w["start"] == len(w["text"]) for w in windows)
    assert len(windows) == 3  # 三段互不相并


def test_fix_blind_zhzh_mode(monkeypatch) -> None:
    """zhzh 模式:第一稿过守卫的中文改中文,再 polish 一次(过守卫即用,不测分)。"""
    _use_pairs(monkeypatch, PAIRS)
    body = P2
    draft = body + "他又数了一遍。"
    polished = body + "他又数了一遍，又核了一遍。"
    adapter = LayerAdapter().feed("zhzh", draft).feed("polish", polished)
    result = _run(fix_blind(BLIND_TEXT, [], targets=[2], layer="zhzh", adapter=adapter))
    rows = {r["order"]: r for r in result["rows"]}
    assert rows[2]["status"] == "已改写(未测分)"
    assert rows[2]["layer"] == "zhzh" and rows[2]["polished"] is True
    assert rows[2]["after"] == polished + "\n"
    assert rows[1]["status"] == "未动" and rows[3]["status"] == "未动"
    assert adapter.count("zhzh") == 1 and adapter.count("polish") == 1
    assert adapter.count("bt_en") == 0
    assert result["usage"]["zhzh"] == 1 and result["usage"]["polish"] == 1


def test_fix_blind_zhzh_mode_tries_up_to_three_drafts(monkeypatch) -> None:
    """zhzh 模式最多 3 稿:前两稿被守卫拦,第三稿采用;拦截不测分、失败不 polish。"""
    _use_pairs(monkeypatch, PAIRS)
    draft = P1 + "他又数了一遍。"
    adapter = LayerAdapter().feed("zhzh", "“自造对白。”", "⟦D9⟧乱写。", draft)
    result = _run(fix_blind(BLIND_TEXT, [], targets=[1], layer="zhzh", adapter=adapter))
    row = {r["order"]: r for r in result["rows"]}[1]
    assert row["status"] == "已改写(未测分)"
    assert [a["tag"] for a in row["attempts"]][:2] == ["中文改写第1稿", "中文改写第2稿"]
    assert all("guard" in a for a in row["attempts"][:2])


def test_fix_blind_zhzh_all_drafts_fail_guard(monkeypatch) -> None:
    """zhzh 模式 3 稿全被守卫拦:保留原文标「需手改」,不 polish。"""
    _use_pairs(monkeypatch, PAIRS)
    adapter = LayerAdapter().feed("zhzh", *["“自造对白。”"] * 3)
    result = _run(fix_blind(BLIND_TEXT, [], targets=[1], layer="zhzh", adapter=adapter))
    row = {r["order"]: r for r in result["rows"]}[1]
    assert row["status"] == "未过守卫,需手改" and row["after"] == row["before"]
    assert adapter.count("polish") == 0


def test_fix_blind_bt_mode(monkeypatch) -> None:
    """bt 模式:现有回译 + polish。"""
    _use_pairs(monkeypatch, PAIRS)
    body = P2.rstrip("\n")
    draft = body + "他又数了一遍。"
    polished = body + "他又数了一遍，又核了一遍。"
    adapter = (LayerAdapter()
               .feed("bt_en", "en").feed("bt_zh", draft).feed("polish", polished))
    result = _run(fix_blind(BLIND_TEXT, [], targets=[2], layer="bt", adapter=adapter))
    row = {r["order"]: r for r in result["rows"]}[2]
    assert row["status"] == "已回译(未测分)" and row["layer"] == "bt" and row["polished"] is True
    assert row["after"] == polished + "\n"
    assert adapter.count("bt_en") == 1 and adapter.count("zhzh") == 0


def test_fix_blind_zhzh_falls_back_to_bt_without_pairs(monkeypatch) -> None:
    """pairs 为空:zhzh 模式自动回落回译。"""
    _use_pairs(monkeypatch, [])
    draft = P1 + "他又数了一遍。"
    adapter = LayerAdapter().feed("bt_en", "en").feed("bt_zh", draft).feed("polish", draft)
    result = _run(fix_blind(BLIND_TEXT, [], targets=[1], layer="zhzh", adapter=adapter))
    row = {r["order"]: r for r in result["rows"]}[1]
    assert row["status"] == "已回译(未测分)" and row["layer"] == "bt"
    assert adapter.count("zhzh") == 0 and adapter.count("bt_en") == 1


def test_fix_blind_only_touches_targets(monkeypatch) -> None:
    """fix_blind 只改 targets 指定的窗;其余窗原样保留并标「未动」。"""
    _use_pairs(monkeypatch, [])
    windows = split_windows(BLIND_TEXT)
    target = windows[1]
    body = target["text"].rstrip("\n")
    polished = body + "他又数了一遍，又核了一遍。"
    adapter = (LayerAdapter()
               .feed("bt_en", "en").feed("bt_zh", body + "他又数了一遍。")
               .feed("polish", polished))
    result = _run(fix_blind(BLIND_TEXT, [], targets=[2], layer="bt", adapter=adapter))
    rows = {r["order"]: r for r in result["rows"]}
    assert rows[1]["status"] == "未动" and rows[1]["after"] == rows[1]["before"]
    assert rows[3]["status"] == "未动" and rows[3]["after"] == rows[3]["before"]
    assert rows[2]["status"] == "已回译(未测分)"
    assert result["text"] == BLIND_TEXT.replace(target["text"], polished + "\n", 1)
    assert len(adapter.calls) == 3   # 一稿回译(英/中)+ 一次 polish


def test_fix_blind_all_windows_when_no_targets(monkeypatch) -> None:
    _use_pairs(monkeypatch, [])
    windows = split_windows(BLIND_TEXT)
    adapter = LayerAdapter()
    expected = BLIND_TEXT
    for w in windows:
        body = w["text"].rstrip("\n")
        draft, polished = body + "又一遍。", body + "又一遍，再一遍。"
        adapter.feed("bt_en", "en").feed("bt_zh", draft).feed("polish", polished)
        expected = expected.replace(w["text"], polished + w["text"][len(body):], 1)
    result = _run(fix_blind(BLIND_TEXT, [], targets=None, layer="bt", adapter=adapter))
    assert all(r["status"] == "已回译(未测分)" for r in result["rows"])
    assert result["text"] == expected


def test_fix_blind_keeps_window_when_all_drafts_fail_guard(monkeypatch) -> None:
    _use_pairs(monkeypatch, [])
    adapter = LayerAdapter().feed("bt_en", *["en"] * 3).feed("bt_zh", *["“全是自造对白。”"] * 3)
    result = _run(fix_blind(BLIND_TEXT, [], targets=[1], layer="bt", adapter=adapter))
    row = {r["order"]: r for r in result["rows"]}[1]
    assert row["status"] == "未过守卫,需手改"
    assert row["after"] == row["before"]
    assert all("guard" in a for a in row["attempts"])
    assert adapter.count("polish") == 0


def test_fix_blind_accepts_extra_locks(monkeypatch) -> None:
    """调用方额外锁定词:进 ⟦K⟧ 占位符送改,回译稿带回复后才还原;polish 同样锁定。"""
    _use_pairs(monkeypatch, [])
    masked_body = P1.replace("常野", "⟦K1⟧")
    polished = masked_body + "他又数了一遍，又核了一遍。"
    adapter = (LayerAdapter()
               .feed("bt_en", "en").feed("bt_zh", masked_body + "他又数了一遍。")
               .feed("polish", polished))
    result = _run(fix_blind(BLIND_TEXT, [], targets=[1], layer="bt", adapter=adapter,
                            extra_locks=["常野"]))
    row = {r["order"]: r for r in result["rows"]}[1]
    assert row["status"] == "已回译(未测分)"
    assert row["after"] == P1 + "他又数了一遍，又核了一遍。" + "\n"
    en_user = adapter.users("bt_en")[0]      # 中→英吃的应是遮罩文本
    assert "⟦K1⟧" in en_user and "常野" not in en_user


# ---------- deai_text:独立去 AI 味 ----------

# 两段各 ~760 字:加标题行后必超 700 字上限,必成三块(标题块 + 两个正文块)
DEAI_PARA1 = "常野推开柴房的门，里面堆着喂马的草料，他挨着草料堆坐下，一笔一笔数今天的账。" * 20
DEAI_PARA2 = "半夜里马嘶了一声，他惊醒过来，摸黑去添草料，又坐下守了半个时辰才重新睡下。" * 20
DEAI_TEXT = "# 第一章 草料房\n\n" + DEAI_PARA1 + "\n\n" + DEAI_PARA2
DEAI_OUT1 = "他推开柴房的门，草料堆得满满当当，挨着坐下慢慢把当天的账数完。" * 20
DEAI_OUT2 = "半夜马叫了一声，他惊醒过来，摸黑添了草料，又坐了半个时辰才重新睡着。" * 20


def test_deai_chunks_split_by_blank_line() -> None:
    chunks = engine._deai_chunks(DEAI_TEXT)
    assert chunks == ["# 第一章 草料房", DEAI_PARA1, DEAI_PARA2]   # 贪心到 700 字必分三块
    assert max(len(c) for c in chunks) > 700   # 单段超长自成一块(r13 口径)


def test_deai_chunks_single_newline_text() -> None:
    """全文没有空行时按单换行分块,免得整章挤成一块(对 r13 的健壮性补充)。"""
    text = "第一段。" * 300 + "\n" + "第二段。" * 300
    chunks = engine._deai_chunks(text)
    assert len(chunks) > 1 and "".join(chunks) == text.replace("\n", "")  # 单换行作分隔


def test_deai_text_rewrites_body_keeps_headings(monkeypatch) -> None:
    _use_pairs(monkeypatch, [])
    adapter = LayerAdapter().feed("deai", DEAI_OUT1, DEAI_OUT2)
    result = _run(deai_text(DEAI_TEXT, [], adapter=adapter))
    rows = result["rows"]
    assert [r["status"] for r in rows] == ["未动", "已去AI味", "已去AI味"]   # 标题块不动
    assert rows[0]["after"] == "# 第一章 草料房"
    assert rows[1]["after"] == DEAI_OUT1 and rows[2]["after"] == DEAI_OUT2
    assert result["text"] == "# 第一章 草料房\n\n" + DEAI_OUT1 + "\n\n" + DEAI_OUT2
    assert result["usage"]["generates"] == 2
    assert adapter.count("deai") == 2


def test_deai_text_guard_fail_keeps_chunk(monkeypatch) -> None:
    """守卫不过的块保留原文:这里喂一稿丢了占位符的输出。"""
    _use_pairs(monkeypatch, [])
    text = "他喊了一声。“开门！”然后进去添草料，把马槽填满才回屋睡下，一夜无事到天明。"
    adapter = LayerAdapter().feed("deai", "他喊了一声然后进去添草料。")   # ⟦D1⟧ 丢了
    result = _run(deai_text(text, [], adapter=adapter))
    row = result["rows"][0]
    assert row["status"] == "未过守卫,保留原文" and row["after"] == row["before"]
    assert row["attempts"] == [{"tag": "去AI味", "guard": "对白占位"}]
    assert result["text"] == text


def test_deai_text_length_guard_excluded(monkeypatch) -> None:
    """去 AI 味不做篇幅限制:合法的大幅增删(篇幅带 0.7–1.7 之外)照样采用。"""
    _use_pairs(monkeypatch, [])
    text = "他数完账，吹了灯，靠着草料堆睡下，半夜又被马嘶惊醒，起来添了一把草。"
    long_out = ("他推开了柴房的门，草料堆得满满当当，他挨着坐下慢慢数账，数完了当天的账，"
                "又把明天的草料提前添好，检查了一遍马槽，才靠着草料堆睡下，一夜安稳到天亮。")
    assert len(long_out) / len(text) > 1.7        # 篇幅带之外,守卫只剩 length=False 一条路
    adapter = LayerAdapter().feed("deai", long_out)
    result = _run(deai_text(text, [], adapter=adapter))
    assert result["rows"][0]["status"] == "已去AI味"
    assert result["rows"][0]["after"] == long_out
