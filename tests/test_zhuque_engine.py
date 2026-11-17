"""S-6 · 降分引擎契约:假 adapter + 假 scorer,全离线。

覆盖:首稿过线即停 / 多轮后过线 / 二次回译后过线 / 始终不过保留原文 /
守卫拦截的稿不测分 / 顺稿回红则放弃 / 顺稿只作用于已过线的窗 / fix_blind 只改 targets /
fix_blind 接受调用方额外锁定词。
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from biyu.zhuque.engine import fix_blind, fix_chapter, split_windows

# 基准窗口:约 36 字叙述、无对白(超过 30 字「几乎全对白」门槛);
# 回译稿只要长度在 0.7–1.7 之间就能过守卫
W = "常野躺在草料堆上一笔一笔数账，把今天的开销和进项都记了三页纸，吹熄了灯。"
FIXED = "常野躺在草料堆上一遍一遍数账，把当天的开销和进项记满了三页纸，然后吹灯。"
DRAFT_A = "常野躺在草料堆上数着账，当天的开销和进项记下三页纸了，他才吹灯。"
DRAFT_B = "常野躺在草料堆上数过账，开销与进项记了三页纸，随后吹熄灯。"
GREEN = {"softmax_confidence": 0.1, "labels_ratio": {"0": 1.0, "1": 0.0, "2": 0.0}}


class FakeAdapter:
    """按序吐正文的假模型;每次 generate 弹一条(回译一稿消耗英/中两条)。"""

    def __init__(self, outputs: list[str]):
        self.outputs = list(outputs)
        self.calls = 0

    async def generate(self, messages: list, **kwargs):
        self.calls += 1
        text = self.outputs.pop(0) if self.outputs else DRAFT_A
        return SimpleNamespace(text=text, cost=0.001)


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


class RecordingAdapter(FakeAdapter):
    """在假模型上加消息记录,断言「哪个窗被送进了哪类提示词」。"""

    def __init__(self, outputs: list[str]):
        super().__init__(outputs)
        self.messages: list[tuple[str, str]] = []

    async def generate(self, messages: list, **kwargs):
        self.messages.append((messages[0]["content"], messages[1]["content"]))
        return await super().generate(messages, **kwargs)


def _run(coro):
    return asyncio.run(coro)


def test_first_round_pass_stops_immediately() -> None:
    """首稿过线即停:不再进第二轮;整章复测两遍后收工。"""
    adapter = FakeAdapter(["e", FIXED, "e", FIXED])  # 第一轮两稿
    scorer = FakeScorer(lambda t: t == W, [
        {"softmax_confidence": 0.2}, {"softmax_confidence": 0.3}, GREEN, GREEN,
    ])
    result = _run(fix_chapter(W, [], adapter=adapter, scorer=scorer, smooth_enabled=False))
    row = result["rows"][0]
    assert row["status"] == "已过线"
    assert row["s1"] == 0.2 and "记满" in row["after"]
    assert adapter.calls == 4          # 一轮两稿 × 每稿两次生成,没有第二轮
    assert scorer.verdict_calls == 3   # 两稿测分 + 终判(本例关掉顺稿,单测轮次逻辑)


def test_passes_after_multiple_rounds() -> None:
    """多轮后过线:第一轮两稿都不过,第二轮才过线。"""
    adapter = FakeAdapter(["e", DRAFT_A, "e", DRAFT_B, "e", FIXED, "e", FIXED])
    scorer = FakeScorer(lambda t: t == W, [
        {"softmax_confidence": 0.8}, {"softmax_confidence": 0.75},   # 第一轮两稿
        {"softmax_confidence": 0.6}, {"softmax_confidence": 0.3},    # 第二轮两稿
        GREEN, GREEN,
    ])
    result = _run(fix_chapter(W, [], adapter=adapter, scorer=scorer, smooth_enabled=False))
    row = result["rows"][0]
    assert row["status"] == "已过线" and row["s1"] == 0.3
    assert len(row["attempts"]) == 4 and adapter.calls == 8


def test_passes_after_second_back_translation() -> None:
    """二次回译后过线:三轮全不过,对最接近的一稿再回译才过线。"""
    outputs = (["e", DRAFT_A, "e", DRAFT_B] * 3) + ["e", DRAFT_A, "e", DRAFT_B]
    adapter = FakeAdapter(outputs)
    scorer = FakeScorer(lambda t: t == W, [
        *([{"softmax_confidence": 0.9}] * 6),        # 三轮两稿全 0.9
        {"softmax_confidence": 0.55},                # 二次回译第 1 次:变好但没过线
        {"softmax_confidence": 0.2},                 # 二次回译第 2 次:过线
        GREEN, GREEN,
    ])
    result = _run(fix_chapter(W, [], adapter=adapter, scorer=scorer))
    row = result["rows"][0]
    assert row["status"] == "已过线(二次回译)" and row["s1"] == 0.2
    assert adapter.calls == 16  # 6 稿 + 2 次二次回译,每档两次生成


def test_never_passes_keeps_original_with_best_try() -> None:
    """始终不过:保留原文标「需手改」,带上最接近的一稿。"""
    outputs = (["e", DRAFT_A, "e", DRAFT_B] * 3) + ["e", DRAFT_A, "e", DRAFT_B]
    outputs += ["e", "顺不动的稿子，他最后还是原样数账，记了整整三页纸才睡下。"]
    adapter = FakeAdapter(outputs)
    scorer = FakeScorer(lambda t: True, [  # 永远红
        *([{"softmax_confidence": 0.9}] * 6),
        {"softmax_confidence": 0.85}, {"softmax_confidence": 0.88},   # 二次回译也不过
        {"softmax_confidence": 0.9},                                  # 顺稿复测不过,不采用
        GREEN, GREEN,
    ])
    result = _run(fix_chapter(W, [], adapter=adapter, scorer=scorer))
    row = result["rows"][0]
    assert row["status"] == "未过线,需手改"
    assert row["after"] == row["before"] == W
    assert row["best_try"]["score"] == 0.85
    assert result["text"] == W


def test_guard_rejected_draft_is_not_scored() -> None:
    """守卫拦截的稿不测分:坏稿只记守卫原因,不消耗朱雀调用。"""
    adapter = FakeAdapter(["e", "“自造了对白。”", "e", FIXED])
    scorer = FakeScorer(lambda t: t == W, [
        {"softmax_confidence": 0.2},   # 只有第二稿被测分
        GREEN, GREEN,
    ])
    result = _run(fix_chapter(W, [], adapter=adapter, scorer=scorer, smooth_enabled=False))
    row = result["rows"][0]
    assert row["attempts"][0]["guard"] == "自造对白"
    assert "score" not in row["attempts"][0]
    assert row["status"] == "已过线"
    assert scorer.verdict_calls == 2  # 1 次测分 + 终判,坏稿没测(本例关掉顺稿)


def test_smooth_reverting_when_chapter_turns_red() -> None:
    """顺稿回红则放弃:顺稿单窗过了线,但整章复测回红 → 整体退回顺稿前。"""
    smoothed = "常野躺在草料堆上顺过的稿子，数账数满三页纸，末了把灯吹了。"
    outputs = (["e", DRAFT_A, "e", DRAFT_B] * 3) + ["e", DRAFT_A, "e", DRAFT_B]
    outputs += [smoothed]  # 顺稿只花一次生成
    adapter = FakeAdapter(outputs)
    scorer = FakeScorer(lambda t: True, [  # 一直红
        *([{"softmax_confidence": 0.9}] * 6),
        {"softmax_confidence": 0.95}, {"softmax_confidence": 0.92},        # 修复全败 → 保留原文
        {"softmax_confidence": 0.3},                                       # 顺稿单窗过线 → 采用
        {"softmax_confidence": 0.6, "labels_ratio": {"0": 0.5, "1": 0.5}},  # 整章复测回红
        GREEN,
    ])
    result = _run(fix_chapter(W, [], adapter=adapter, scorer=scorer))
    assert result["text"] == W                      # 顺稿被整体放弃
    assert result["smooth"] == {"kept": 0, "total": 1, "adopted": False}
    assert result["rows"][0]["status"] == "未过线,需手改"


B_WINDOW = "南城旧武馆的后院静得可怕，张今空把短刀往袖口里又收了一寸，盯着门缝里透进来的那道光。"
B_SMOOTHED = "南城旧武馆后院静得可怕，张今空把短刀又往袖口里收了一寸，盯着门缝里那道光。"


class TwoWindowScorer:
    """两窗恒定:第一行 A 恒红 0.9,第二行起 B 恒绿 0.1;verdict 按队列吐,耗尽回绿。"""

    def __init__(self, verdicts: list[dict]):
        self.verdicts = list(verdicts)

    async def windows(self, text: str) -> list[dict[str, Any]]:
        first, _, rest = text.partition("\n")
        return [
            {"order": 1, "start": 0, "end": len(first), "text": first, "conf": 0.9, "label": 1},
            {"order": 2, "start": len(first) + 1, "end": len(text),
             "text": "\n" + rest, "conf": 0.1, "label": 0},
        ]

    async def verdict(self, text: str) -> dict[str, Any]:
        return self.verdicts.pop(0) if self.verdicts else GREEN


def test_smooth_only_touches_windows_already_past_pass() -> None:
    """顺稿只作用于已过线的窗:红窗 A 三轮救不回、保留原文,只有绿窗 B 被送顺稿。"""
    adapter = RecordingAdapter(["e", DRAFT_A] * 8 + [B_SMOOTHED])
    scorer = TwoWindowScorer(
        [{"softmax_confidence": 0.9}] * 8      # A 的六稿 + 二次回译两次,全不过线
        + [{"softmax_confidence": 0.1}]        # B 的顺稿稿过线
        + [GREEN]                              # 顺稿后整章复测仍绿
    )
    result = _run(fix_chapter(W + "\n" + B_WINDOW, [], adapter=adapter, scorer=scorer))
    assert result["smooth"] == {"kept": 1, "total": 2, "adopted": True}
    assert result["text"] == W + "\n" + B_SMOOTHED
    # 顺稿提示词只喂过绿窗 B;红窗 A 从头到尾没进顺稿
    smooth_calls = [user for system, user in adapter.messages if "顺成通顺" in system]
    assert len(smooth_calls) == 1 and "武馆" in smooth_calls[0]
    row = result["rows"][0]
    assert row["before"] == W and row["after"] == W and row["status"] == "未过线,需手改"


def test_dialogue_heavy_window_left_untouched() -> None:
    """几乎全是对白的窗直接标「未动」,不花生成。"""
    window = "“开门！”“是我。”“快进来。”"
    adapter = FakeAdapter([])
    scorer = FakeScorer(lambda t: True, [GREEN, GREEN])
    result = _run(fix_chapter(window, [], adapter=adapter, scorer=scorer))
    assert result["rows"][0]["status"] == "几乎全是对白,未动"
    assert adapter.calls == 0


def test_engine_emits_progress_events() -> None:
    adapter = FakeAdapter(["e", FIXED, "e", FIXED])
    scorer = FakeScorer(lambda t: t == W, [
        {"softmax_confidence": 0.2}, {"softmax_confidence": 0.3}, GREEN, GREEN,
    ])
    events: list[dict] = []
    _run(fix_chapter(W, [], adapter=adapter, scorer=scorer, on_event=events.append))
    stages = [e["stage"] for e in events]
    assert stages[0] == "outer" and "window" in stages and "smooth" in stages
    done = [e for e in events if e.get("stage") == "window" and e.get("state") == "done"]
    assert done and done[0]["status"] == "已过线"


# ---------- fix_blind ----------

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


def test_fix_blind_only_touches_targets() -> None:
    """fix_blind 只改 targets 指定的窗;其余窗原样保留并标「未动」。"""
    windows = split_windows(BLIND_TEXT)
    target = windows[1]  # 第 2 窗(带尾换行,引擎会原样保留)
    body = target["text"].rstrip("\n")
    draft = body + "他又数了一遍。"
    expected_after = draft + "\n"
    adapter = FakeAdapter(["en", draft])
    result = _run(fix_blind(BLIND_TEXT, [], targets=[2], adapter=adapter))
    rows = {r["order"]: r for r in result["rows"]}
    assert rows[1]["status"] == "未动" and rows[1]["after"] == rows[1]["before"]
    assert rows[3]["status"] == "未动" and rows[3]["after"] == rows[3]["before"]
    assert rows[2]["status"] == "已回译(未测分)"
    assert rows[2]["after"] == expected_after
    assert result["text"] == BLIND_TEXT.replace(target["text"], expected_after, 1)
    assert adapter.calls == 2  # 只有一稿 × 两次生成


def test_fix_blind_all_windows_when_no_targets() -> None:
    windows = split_windows(BLIND_TEXT)
    outputs: list[str] = []
    expected_after: dict[int, str] = {}
    for w in windows:
        body = w["text"].rstrip("\n")
        draft = body + "又一遍。"
        outputs += ["en", draft]
        expected_after[w["order"]] = draft + w["text"][len(body):]
    adapter = FakeAdapter(outputs)
    result = _run(fix_blind(BLIND_TEXT, [], targets=None, adapter=adapter))
    assert all(r["status"] == "已回译(未测分)" for r in result["rows"])
    expected = BLIND_TEXT
    for w in windows:
        expected = expected.replace(w["text"], expected_after[w["order"]], 1)
    assert result["text"] == expected


def test_fix_blind_keeps_window_when_all_drafts_fail_guard() -> None:
    adapter = FakeAdapter(["en", "“全是自造对白。”"] * 3)  # 三稿全被守卫拦
    result = _run(fix_blind(BLIND_TEXT, [], targets=[1], adapter=adapter))
    row = {r["order"]: r for r in result["rows"]}[1]
    assert row["status"] == "未过守卫,需手改"
    assert row["after"] == row["before"]
    assert all("guard" in a for a in row["attempts"])


def test_fix_blind_accepts_extra_locks() -> None:
    """调用方额外锁定词:进 ⟦K⟧ 占位符送翻,回译稿带回复后才还原。"""
    masked_body = P1.replace("常野", "⟦K1⟧")
    adapter = RecordingAdapter(["en", masked_body + "他又数了一遍。"])
    result = _run(fix_blind(BLIND_TEXT, [], targets=[1], adapter=adapter,
                            extra_locks=["常野"]))
    row = {r["order"]: r for r in result["rows"]}[1]
    assert row["status"] == "已回译(未测分)"
    assert row["after"] == P1 + "他又数了一遍。" + "\n"
    en_user = adapter.messages[0][1]  # 第一次 generate 是中→英,吃的应是遮罩文本
    assert "⟦K1⟧" in en_user and "常野" not in en_user
