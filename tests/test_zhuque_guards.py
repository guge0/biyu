"""S-6 · 守卫与风险标注契约:mask/unmask 往返;clean;guard 每条规则一正一反;
r12 真实坏例子(英文残留/半角逗号/昌千户/并段)做反例;risk_marks 三类。
S-8-1 追加:dedash;破折号/段中丢句号/示范泄漏三条新守卫。"""
from __future__ import annotations

from biyu.zhuque.guards import (
    clean,
    dedash,
    guard,
    lock_words,
    mask,
    risk_marks,
    strip_slots,
    unmask,
)

TEXT = "常野躺在草料堆上。“已攒：三钱二分。”蓝光透出【守成】两个楷字。"


# ---------- mask / unmask 往返 ----------

def test_mask_unmask_roundtrip() -> None:
    masked, items, nd = mask(TEXT)
    assert items == ["“已攒：三钱二分。”", "【守成】"]
    assert masked == "常野躺在草料堆上。⟦D1⟧蓝光透出⟦D2⟧两个楷字。"
    assert nd == 2
    assert unmask(masked, items, nd) == TEXT


def test_mask_plain_text_no_dialogue() -> None:
    masked, items, nd = mask("干草垛扎得后背发痒。")
    assert masked == "干草垛扎得后背发痒。" and items == [] and nd == 0


def test_strip_slots_leaves_body() -> None:
    masked, _items, _nd = mask(TEXT)
    assert "⟦" not in strip_slots(masked)
    assert "已攒" not in strip_slots(masked)  # 对白被占位符替掉,不剩正文


# ---------- 标题行整行锁定 ----------

def test_mask_locks_title_lines() -> None:
    text = "# 第一章 大风\n常野躺在草料堆上。\n第十二章\n他数着账。"
    masked, items, nd = mask(text)
    assert masked == "⟦D1⟧\n常野躺在草料堆上。\n⟦D2⟧\n他数着账。"
    assert items == ["# 第一章 大风", "第十二章"] and nd == 2
    assert unmask(masked, items, nd) == text


def test_mask_title_form_ignores_narration_lines() -> None:
    # 带句读的整行不是标题;行中的「第…章」不算(必须整行)
    masked, items, _nd = mask("第三章里的人都散了。\n他想起第三章的旧事。")
    assert "⟦" not in masked and items == []


# ---------- 专名 ⟦K⟧ 锁定(长词优先) ----------

def test_mask_locks_terms_long_first() -> None:
    text = "常野氏和常野都在场，常野先开口。"
    masked, items, nd = mask(text, ["常野", "常野氏"])
    assert masked == "⟦K1⟧和⟦K2⟧都在场，⟦K2⟧先开口。"
    assert items == ["常野氏", "常野"] and nd == 0
    assert unmask(masked, items, nd) == text


def test_mask_dialogue_slots_numbered_before_terms() -> None:
    masked, items, nd = mask("常野说：“开门。”", ["常野"])
    assert masked == "⟦K2⟧说：⟦D1⟧"
    assert items == ["“开门。”", "常野"] and nd == 1
    assert unmask(masked, items, nd) == "常野说：“开门。”"


def test_lock_words_surname_combos() -> None:
    # 姓氏保护:人名首字以「X千户」「X家」「X大少爷」「X二哥」形式出现也锁定
    text = "常千户把刀放下。常家二房到了。常大少爷拱手。常二哥让开。张今空没来。"
    locks = lock_words(text, ["常野", "张今空"])
    assert "常千户" in locks and "常家" in locks and "常大少爷" in locks and "常二哥" in locks
    assert "张今空" in locks
    assert "常野" not in locks  # 本窗没出现全名,只锁组合


def test_lock_words_extra_from_caller() -> None:
    locks = lock_words("他把玄铁重剑扛在肩上。", [], ["玄铁重剑", "没出现的词"])
    assert locks == ["玄铁重剑"]


# ---------- clean:回译稿进守卫前的清洁 ----------

def test_clean_removes_spaces_around_cjk_and_marks() -> None:
    # r12 真实坏例子:设定词两边多空格
    assert clean("蓝光透出 【守成】 两个楷字。") == "蓝光透出【守成】两个楷字。"
    assert clean("常野 躺在 草料堆上。") == "常野躺在草料堆上。"


def test_clean_keeps_line_breaks() -> None:
    text = "他数完账。\n又去挑水。"
    assert clean(text) == text  # 只清横向空白,不吃换行(否则并段守卫误伤)


def test_clean_halfwidth_punct_to_fullwidth() -> None:
    # r12 真实坏例子:中文后接半角逗号
    assert clean("他挠了挠背,又躺下;片刻后:鼾声起。") == "他挠了挠背，又躺下；片刻后：鼾声起。"


def test_clean_dot_after_placeholder() -> None:
    assert clean("他说。⟦D1⟧。然后走了。") == "他说。⟦D1⟧然后走了。"
    assert clean("⟦K1⟧。把刀放下。") == "⟦K1⟧把刀放下。"


def test_clean_space_around_placeholder() -> None:
    assert clean("⟦K1⟧ 躺在草料堆上") == "⟦K1⟧躺在草料堆上"
    assert clean("草料堆上 ⟦D1⟧ 翻了个身") == "草料堆上⟦D1⟧翻了个身"


# ---------- guard:每条规则一正一反 ----------

MASKED = "常野躺在草料堆上数账。"  # 11 字,无对白
DIALOGUE_MASKED, DIALOGUE_ITEMS, DIALOGUE_ND = mask("他喊了一声。“开门！”然后走了。")


def test_guard_ok_draft_passes() -> None:
    assert guard(MASKED, "常野躺在草料堆上一笔一笔数账。", []) == ""


def test_guard_empty_draft_rejected() -> None:
    assert guard(MASKED, "", []) == "空"


def test_guard_placeholder_once() -> None:
    # 正:占位符各出现一次
    assert guard(DIALOGUE_MASKED, "他喊了一声⟦D1⟧然后走了。", []) == ""
    # 反:丢了占位符
    assert guard(DIALOGUE_MASKED, "他喊了一声然后走了。", []) == "对白占位"
    # 反:占位符出现两次
    assert guard(DIALOGUE_MASKED, "他喊⟦D1⟧了⟦D1⟧声然后走了。", []) == "对白占位"


def test_guard_term_placeholder_count_preserved() -> None:
    # 正:锁定词占位符按原次数带回;反:锁定词没带回复(被写成同音字)
    masked, items, nd = mask("常野数账，常野又核了一遍。", ["常野"])
    assert guard(masked, "⟦K1⟧数账，⟦K1⟧又核了一遍。", []) == ""
    # r12 真实坏例子:「常千户」被写成「昌千户」——占位符没带回来
    qianhu, q_items, q_nd = mask("常千户把刀收了。", ["常千户"])
    assert qianhu == "⟦K1⟧把刀收了。"
    assert guard(qianhu, "昌千户把刀收了。", []) == "专名占位"
    assert guard(qianhu, "⟦K1⟧把刀收好了。", []) == ""
    assert unmask("⟦K1⟧把刀收好了。", q_items, q_nd) == "常千户把刀收好了。"


def test_guard_stray_placeholder_rejected() -> None:
    # 反:多出自造占位符(unmask 后会残留 ⟦⟧)
    assert guard("他走了。", "他走了。⟦D9⟧", []) == "占位残留"
    assert guard(DIALOGUE_MASKED, "他喊了一声⟦D1⟧⟦D2⟧然后走了。", []) == "占位残留"


def test_guard_invented_dialogue_rejected() -> None:
    # 反:自造弯引号对白(此规则在篇幅之前,先命中)
    assert guard(MASKED, "常野躺在草料堆上数账。“又多了一笔。”", []) == "自造对白"


def test_guard_english_residue_rejected() -> None:
    # r12 真实坏例子:残留英文(连续 3 个以上拉丁字母即拦)
    assert guard("常野挠了挠背。", "常野 scratched his back 数账。", []) == "英文残留"
    # 正:全中文过;零星单双字母(如量词缩写)不拦
    assert guard("常野挠了挠背。", "常野挠了挠后背。", []) == ""


def test_guard_paragraph_merge_rejected() -> None:
    two_lines = "常野躺在草料堆上。\n他数着账。"
    assert guard(two_lines, "常野躺在草料堆上。他数着账。", []) == "并段"
    assert guard(two_lines, "常野躺在草料堆上。\n他数着账册。", []) == ""


def test_guard_final_punct_preserved() -> None:
    two_lines = "常野数完了三页账。\n他去挑水。"
    # 反:原文段末有句末标点,改后段末落在字上(句号丢了)
    assert guard(two_lines, "常野数完了三页账\n他去挑水了。", []) == "句末标点"
    assert guard(two_lines, "常野把三页账数完。\n他去挑水了。", []) == ""


def test_guard_final_punct_skipped_when_line_ends_with_slot() -> None:
    # 原段末是占位符(对白自带句读)时不做句末标点检查
    masked, _items, _nd = mask("他喊了一声。“开门！”")
    assert masked == "他喊了一声。⟦D1⟧"
    assert guard(masked, "⟦D1⟧他喊了一声。", []) == ""


def test_guard_halfwidth_punct_rejected() -> None:
    # r12 真实坏例子:中文后接半角逗号(clean 之前的手稿)
    assert guard("他挠了挠背又躺下。", "他挠了挠背,又躺下。", []) == "半角标点"
    assert guard("他挠了挠背又躺下。", "他挠了挠背，又躺下。", []) == ""


def test_guard_term_count_unchanged() -> None:
    terms = ["常野"]
    assert guard(MASKED, "常野躺在草料堆上一笔一笔数账。", terms) == ""
    assert guard(MASKED, "他躺在草料堆上数账。", terms) == "专名:常野"
    assert guard(MASKED, "常野常野躺在草料堆上数账。", terms) == "专名:常野"


def test_guard_number_set_not_lost() -> None:
    masked = "南城小院要二百两银子。"  # NUM 命中「二百两」
    assert guard(masked, "南城小院要二百两的银子。", []) == ""
    assert guard(masked, "南城小院要一笔银子。", []) == "数字"
    # 新增数字不算丢
    assert guard(masked, "南城小院要二百两银子，分三回付。", []) == ""


def test_guard_length_band() -> None:
    masked = "巷口的灯笼一盏接一盏地灭了。"  # 14 字,无数字无对白
    assert guard(masked, "巷口的灯笼一盏接一盏地全灭了。", []) == ""
    assert guard(masked, "巷口的灯笼全灭了。", []) == "篇幅"    # 9/14 ≈ 0.64 < 0.7
    assert guard(masked, "嗯。" * 14, []) == "篇幅"             # 28/14 = 2.0 > 1.7


def test_guard_truncated_draft_reports_final_punct_first() -> None:
    # 截断稿同时丢句号又超篇幅:报更具体的「句末标点」
    assert guard("巷口的灯笼一盏接一盏地灭了。", "巷口的灯笼一盏接一", []) == "句末标点"


# ---------- dedash:确定性去破折号(r15 的 fix) ----------

def test_dedash_variants() -> None:
    assert dedash("他走了——又回来。") == "他走了，又回来。"
    assert dedash("灯灭了—屋里黑了。") == "灯灭了，屋里黑了。"
    assert dedash("门开了--风灌进来。") == "门开了，风灌进来。"
    assert dedash("三连———一起换。") == "三连，一起换。"       # ——+ 整段一起换
    assert dedash("他走了，，又回来。") == "他走了，又回来。"   # 收拾 ，，
    assert dedash("他走了，。又回来。") == "他走了。又回来。"   # 收拾 ，。


def test_dedash_keeps_plain_text() -> None:
    assert dedash("常野数了三遍账。") == "常野数了三遍账。"


# ---------- S-8-1 新守卫:每条一正一反 ----------

def test_guard_no_new_dashes() -> None:
    masked = "他走了——又回来。"
    # 反:改后比原文多出破折号(dedash 后正常应为 0)
    assert guard(masked, "他走了——回来——又走了。", []) == "破折号"
    # 正:改后一个破折号都没有
    assert guard(masked, "他走了，又回来。", []) == ""


def test_guard_dash_not_flagged_when_fewer_than_source() -> None:
    # 原文有破折号、改后减半:不拦(只拦「多于原文」)
    assert guard("门开——风进来——灯灭了。", "门开，风就灌进来，灯也灭了。", []) == ""


def test_guard_sentence_ends_lost_mid_paragraph() -> None:
    masked = "他数账。他挑水。他喂马。天黑了才歇。"
    # 反:原段 4 个句末标点,改后只剩 1 个(不到一半);段末句号还在,
    # 先过「句末标点」规则,才轮到逐段计数的「段中丢句号」
    assert guard(masked, "他数账，他挑水，他喂马，天黑了才歇。", []) == "段中丢句号"
    # 正:4 → 2 个,正好一半(「不到一半」才拦),放行
    assert guard(masked, "他数账。他挑水，他喂马，天黑了才歇。", []) == ""


def test_guard_long_punctuation_free_run() -> None:
    # 段末句号在、段内计数也不足 3,只有「80 字以上无句读长串」能拦:
    # 逗号不算句读,整段只有句尾一个句号 = 一条 100 字长串
    masked = "他数账，他挑水，他喂马。"
    run = "他数账，" * 25  # 100 字,零句读,结尾落在逗号上
    assert guard(masked, run, []) == "段中丢句号"
    # 正:原文也有同量级长串时不拦
    assert guard(run, run, []) == ""


def test_guard_exemplar_leak() -> None:
    exemplar = "他猫着腰钻进柴房，把半袋糙米挪到墙角，又用干草盖住了麻袋口。"
    masked = "常野推开柴房的门，里面堆着喂马的草料。"
    # 反:输出里搬了示范的片段(12 字以上),且这段不在输入里
    leaked = "常野推开柴房的门，他猫着腰钻进柴房，把半袋糙米挪到墙角，又用干草盖住了麻袋口。"
    assert guard(masked, leaked, [], exemplars=[exemplar]) == "示范泄漏"
    # 正:输出与示范的重合片段同样出现在输入里(改写自输入,不是抄示范)
    assert guard(masked, "常野推开柴房的门，里头堆着喂马的草料。", [], exemplars=[exemplar]) == ""


def test_guard_short_exemplar_overlap_not_flagged() -> None:
    # 重合不足 12 字(「草料的门口」5 字)不算泄漏
    exemplar = "他把草料的门口堵上了。"
    assert guard("常野看看草料的门口。", "常野看了看草料的门口。", [], exemplars=[exemplar]) == ""


def test_guard_length_switch_for_deai() -> None:
    """length=False 跳过篇幅带(去 AI 味按块改写,合法增删超过 0.7–1.7)。"""
    masked = "他挑水，喂马，数账，天黑才歇。"
    assert guard(masked, "他挑水，喂马。" * 8, []) == "篇幅"
    assert guard(masked, "他挑水，喂马。" * 8, [], length=False) == ""


# ---------- 回译全链:clean → guard → unmask ----------

def test_clean_guard_unmask_pipeline_on_bad_draft() -> None:
    """带占位符的真实坏手稿:多余空格 + 半角逗号 → clean 后过守卫,unmask 还原。"""
    masked, items, nd = mask("蓝光透出【守成】两个楷字。常野翻了个身。", ["常野"])
    assert masked == "蓝光透出⟦D1⟧两个楷字。⟦K2⟧翻了个身。"
    raw = "蓝光透出 ⟦D1⟧ 两个楷字, ⟦K2⟧翻了个身。"
    out = clean(raw)
    assert out == "蓝光透出⟦D1⟧两个楷字，⟦K2⟧翻了个身。"
    assert guard(masked, out, ["常野"]) == ""
    assert unmask(out, items, nd) == "蓝光透出【守成】两个楷字，常野翻了个身。"


# ---------- risk_marks:数字 / 单位 / 专名 ----------

def test_risk_marks_number_change() -> None:
    risks = risk_marks("南城小院要二百两银子。", "南城小院要 100 两银子。", [])
    nums = [r for r in risks if r["kind"] == "number"]
    assert nums and nums[0]["before"] == "二百两" and nums[0]["after"] == "100"
    assert nums[0]["start"] >= 0 and nums[0]["end"] > nums[0]["start"]


def test_risk_marks_number_vanished() -> None:
    risks = risk_marks("他攒了二百两。", "他攒了一点钱。", [])
    vanished = [r for r in risks if r["kind"] == "number" and r["after"] == ""]
    assert vanished and vanished[0]["before"] == "二百两" and vanished[0]["start"] == -1


def test_risk_marks_unit_change() -> None:
    risks = risk_marks("他解下三尺白绫。", "他解下三英尺白绫。", [])
    units = [r for r in risks if r["kind"] == "unit"]
    assert units and units[0]["before"] == "尺" and units[0]["after"] == "英尺"
    assert "他解下三英尺白绫。"[units[0]["start"]:units[0]["end"]] == "英尺"


def test_risk_marks_unit_unchanged_not_flagged() -> None:
    assert [r for r in risk_marks("他解下三尺白绫。", "他解下三尺白绫子。", []) if r["kind"] == "unit"] == []


def test_risk_marks_missing_term() -> None:
    risks = risk_marks("常野抬起头。", "他抬起头。", ["常野"])
    terms = [r for r in risks if r["kind"] == "term"]
    assert terms and terms[0]["before"] == "常野" and terms[0]["start"] == -1


def test_risk_marks_no_change_clean() -> None:
    assert risk_marks(TEXT, TEXT, ["常野"]) == []
