"""Anchor check 引擎 — 纯确定性 value-match,零 LLM。

P6-A2: 从 tools/anchor_checker.py 抽出引擎核心入包, 供 auditor 和 CLI 共用。
包内 import 不依赖 repo 根的 tools/ 目录(装包后也可用)。

判定(value-match 三态, 纯子串字符比对, 不造归一化引擎):
1. canonical 或 alias 命中 → status="present"
2. 否则若 mismatch_aliases(错值 distractor)命中 → status="value_mismatch"
3. 否则 → status="missing"

归一化: 全角→半角(字母/数字/标点), 连续空白压缩为单空格, strip。
不做数字自动转换(确定性优先)。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml


# ---------------------------------------------------------------------------
# 归一化
# ---------------------------------------------------------------------------
_FULLWIDTH_MAP = str.maketrans(
    "ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ"
    "ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ"
    "０１２３４５６７８９"
    "！＠＃＄％＾＆＊（）－＝＋［］｛｝；＇：＂，．／＜＞？",
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "abcdefghijklmnopqrstuvwxyz"
    "0123456789"
    "!@#$%^&*()-=+[]{};':\",./<>?",
)


def normalize(text: str) -> str:
    """归一化: 全角→半角, 连续空白压缩为单空格, strip 首尾。"""
    text = text.translate(_FULLWIDTH_MAP)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


# ---------------------------------------------------------------------------
# slot-pattern 原语(P6-A2/B1)— 确定性结构化抽取,不破 D-43 精神
# ---------------------------------------------------------------------------
_CN_DIGITS = {
    "零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}
_CN_UNITS = {"十": 10, "百": 100, "千": 1000}
_CN_NUM_CHARS = "零一二三四五六七八九十百千两"  # 中文数字字符集(正则用)
_TIME_PERIODS_PM = ("下午", "晚上", "夜里", "午后", "傍晚", "夜间")


def cn2num(s: str) -> int | None:
    """中文数字 → 阿拉伯(0-9999)。无法解析返回 None。

    支持两种形式:
    - 位值连写(无单位,如年份"一九九八"):逐位拼接 → 1998
    - 带单位(十/百/千):"三十七"→37、"十一"→11、"二十"→20

    确定性规则,不做模糊语义。非法字符或空串 → None。
    """
    if not s:
        return None
    if any(c not in _CN_DIGITS and c not in _CN_UNITS for c in s):
        return None
    # 位值连写:纯数字字符(无单位)
    if all(c in _CN_DIGITS for c in s):
        if len(s) == 1:
            return _CN_DIGITS[s]
        return int("".join(str(_CN_DIGITS[c]) for c in s))
    # 带单位解析
    total = 0
    current = 0
    for c in s:
        if c in _CN_DIGITS:
            current = _CN_DIGITS[c]
        else:  # 单位
            if current == 0:
                current = 1  # "十"开头 = 一十
            total += current * _CN_UNITS[c]
            current = 0
    total += current  # 尾巴(如"三十七"的七)
    return total


def _apply_time_period(hour: int, text: str, start: int) -> int:
    """根据 start 位置前 6 字符窗口的时段修饰词调整小时(PM → +12)。"""
    window = text[max(0, start - 6):start]
    if any(p in window for p in _TIME_PERIODS_PM) and hour <= 12:
        return hour + 12
    return hour


def normalize_time_hm(text: str) -> list[str]:
    """抽取文本中的时分表达,归一化为 24h "HH:MM" 列表。

    支持形式(中阿混用):
    - 阿拉伯:HH:MM、HH点MM分、HH点MM、HH点
    - 中文:CN点CN分、CN点CN、CN点

    时段修饰(向前看 6 字符窗口):上午/凌晨/早上 不变;
    下午/晚上/夜里/傍晚 +12(仅当小时 ≤ 12)。

    确定性规则,不做语义推断。无匹配返回空列表。
    """
    if not text:
        return []
    norm = normalize(text)
    results: list[str] = []
    seen: set[str] = set()

    def _add(h: int, mi: int) -> None:
        if 0 <= h <= 23 and 0 <= mi <= 59:
            v = f"{h:02d}:{mi:02d}"
            if v not in seen:
                seen.add(v)
                results.append(v)

    # 模式1:阿拉伯 HH:MM(冒号)
    for m in re.finditer(r"(\d{1,2}):(\d{2})", norm):
        h = _apply_time_period(int(m.group(1)), norm, m.start())
        _add(h, int(m.group(2)))

    # 模式2:阿拉伯 HH点[MM]分?
    for m in re.finditer(r"(\d{1,2})点(\d{1,2})?分?", norm):
        h = _apply_time_period(int(m.group(1)), norm, m.start())
        mi = int(m.group(2)) if m.group(2) else 0
        _add(h, mi)

    # 模式3:中文 CN点[CN]分?
    for m in re.finditer(rf"([{_CN_NUM_CHARS}]+)点([{_CN_NUM_CHARS}]+)?分?", norm):
        h = cn2num(m.group(1))
        if h is None:
            continue
        h = _apply_time_period(h, norm, m.start())
        mi = cn2num(m.group(2)) if m.group(2) else 0
        if mi is None:
            mi = 0
        _add(h, mi)

    return results


def normalize_number_unit(text: str, unit: str) -> list[str]:
    """抽取文本中"数字+指定单位"的表达,归一化为数字串列表。

    支持阿拉伯和中文数字。单位必须精确匹配(单位不符不命中)。
    用于 slot-pattern:"三十七页"/"37页" + unit="页" → ["37"]。
    """
    if not text or not unit:
        return []
    norm = normalize(text)
    results: list[str] = []
    seen: set[str] = set()
    esc_unit = re.escape(unit)

    # 阿拉伯数字 + unit
    for m in re.finditer(r"(\d+)\s*" + esc_unit, norm):
        v = m.group(1)
        if v not in seen:
            seen.add(v)
            results.append(v)

    # 中文数字 + unit
    for m in re.finditer(rf"([{_CN_NUM_CHARS}]+)" + esc_unit, norm):
        n = cn2num(m.group(1))
        if n is not None:
            v = str(n)
            if v not in seen:
                seen.add(v)
                results.append(v)

    return results


def _check_slot_match(slot: dict, norm_text: str) -> str | None:
    """检查已归一化文本是否命中 anchor 声明的 slot(P6-A2/B1)。

    slot schema: {kind: time_hm|number_unit, value: str, unit?: str}
    命中返回 hit_by 标记(如 "[slot:11:20]"、"[slot:37|页]"),未命中返回 None。

    被 check_atomic 在 canonical/alias 未中时调用,优先于 mismatch_aliases。
    输入 norm_text 应为 normalize() 产物(函数内 normalize 幂等,重复无害)。
    """
    kind = slot.get("kind")
    value = slot.get("value")
    if not kind or value is None:
        return None
    if kind == "time_hm":
        if value in normalize_time_hm(norm_text):
            return f"[slot:{value}]"
    elif kind == "number_unit":
        unit = slot.get("unit", "")
        if unit and value in normalize_number_unit(norm_text, unit):
            return f"[slot:{value}|{unit}]"
    return None


def _check_slot_form_mismatch(slot: dict, norm_text: str) -> str | None:
    """B2:slot 模式抽到同形异值 → mismatch 信号(opt-in)。

    slot schema 扩展(B2):加可选 `mismatch_enabled: bool`(默认 false)。
    仅当 mismatch_enabled=true 时启用本检查;否则返回 None(B1 行为不变)。

    判定(仅当启用):
    - time_hm:normalize_time_hm(text) → 列表 L。slot.value not in L 且 L 非空
      → 取首个 ≠ slot.value 的 w,返回 f"[slot-mismatch:{w}]"。
    - number_unit:normalize_number_unit(text, unit) → 列表 L。slot.value not in L
      且 L 非空 → 取首个 ≠ slot.value 的 w,返回 f"[slot-mismatch:{w}|{unit}]"。
    - 其况(slot.value 在 L / L 空 / 缺 kind/value/unit)→ None。

    被 check_atomic 在 slot.value 未命中(_check_slot_match 返回 None)时调用,
    优先于 mismatch_aliases。返回非 None 即把 status 提为 value_mismatch。

    D-43 边界:本检查仍确定性(无语义),但需要作者显式 opt-in(承认"无语义下不能
    自动区分'作者没写'vs'作者写错值'",per-anchor 让作者控)。详见 specs/P6-A2-B2.md。
    """
    if not slot.get("mismatch_enabled"):
        return None
    kind = slot.get("kind")
    value = slot.get("value")
    if not kind or value is None:
        return None
    if kind == "time_hm":
        extracted = normalize_time_hm(norm_text)
        if value not in extracted and extracted:
            diff = next((v for v in extracted if v != value), None)
            if diff is not None:
                return f"[slot-mismatch:{diff}]"
    elif kind == "number_unit":
        unit = slot.get("unit", "")
        if not unit:
            return None
        extracted = normalize_number_unit(norm_text, unit)
        if value not in extracted and extracted:
            diff = next((v for v in extracted if v != value), None)
            if diff is not None:
                return f"[slot-mismatch:{diff}|{unit}]"
    return None


# ---------------------------------------------------------------------------
# P6-A3 · 异名检测(未预声明的错名,相似但字面不一致)
# 纯确定性,无 NER:从 canonical 字面特征出发扫文本。
# ---------------------------------------------------------------------------
def _edit_distance_same_len(a: str, b: str) -> int:
    """等长串的 Hamming 距离(对应位置不同字符数)。

    等长 Levenshtein = Hamming(只有替换,无插入/删除)。本引擎只对等长候选
    比对(字数必须相同),用 Hamming 更直接、零歧义。
    """
    return sum(1 for x, y in zip(a, b) if x != y)


def _find_alias_similar(
    canonical: str,
    registered_names: set[str],
    norm_text: str,
    max_distance: int = 2,
) -> str | None:
    """在 norm_text 中扫"与 canonical 相似但未在任何 anchor 登记过"的候选。

    P6-A3 异名检测的核心 helper。纯确定性,无 NER:用 canonical[0](姓)
    作锚点定位候选起点,避免对全文所有位置跑距离比对。

    候选条件(全满足才命中):
    1. 长度 == len(canonical)
    2. 首字 == canonical[0](姓相同)
    3. 候选 != canonical 自身
    4. 候选 ∉ registered_names(本锚 alias、同册他锚 canonical/alias 都在内)
    5. _edit_distance_same_len(候选, canonical) ≤ max_distance

    Args:
        canonical: 该 anchor 的规范名(已 normalize 之前的原形,函数内 normalize)
        registered_names: 已登记名字集合(每元素应为 normalize() 产物)
        norm_text: 已归一化的待检文本
        max_distance: 最大允许编辑距离(默认 2,反推自早期秘境章实测的"异名"典型案例)

    Returns:
        首个命中的候选字符串,或 None。

    设计取舍见 specs/P6-A3.md "决策 1/2/3"。报告语义为"疑似异名,提请人工确认",
    不自动改名——相似名也可能是两个真不同角色(都未登记时,本引擎无法区分,
    由人工确认兜底)。
    """
    norm_canonical = normalize(canonical)
    L = len(norm_canonical)
    if L < 2:
        return None  # 单字名易误报,不检
    first = norm_canonical[0]
    for m in re.finditer(re.escape(first), norm_text):
        start = m.start()
        candidate = norm_text[start:start + L]
        if len(candidate) < L:
            continue  # 文本尾不足 L 字
        if candidate == norm_canonical:
            continue  # 自身
        if candidate in registered_names:
            continue  # 已登记(本锚 alias / 同册他锚)
        if _edit_distance_same_len(candidate, norm_canonical) <= max_distance:
            return candidate
    return None


# ---------------------------------------------------------------------------
# 数据加载
# ---------------------------------------------------------------------------
def load_anchors(yaml_path: str | Path) -> dict[str, Any]:
    """加载 anchors.yaml, 返回原始字典。"""
    with open(yaml_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_text(file_path: str | Path) -> str:
    """加载待检测文本文件。"""
    p = Path(file_path)
    return p.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 检测逻辑
# ---------------------------------------------------------------------------
def check_atomic(
    anchors_list: list[dict], text: str
) -> list[dict]:
    """检查 atomic 锚点命中情况(value-match 三态 + slot-pattern + 异名检测)。

    判定优先级(P6-A3 最终态):
    1. canonical 或任一 alias 子串命中 → status="present"
    2. 否则若 anchor 声明了 slot 且 slot value 命中 → status="present"(hit_by=[slot:...])
    3. 否则若 slot.mismatch_enabled=true 且 slot 模式抽到同形异值
       → status="value_mismatch"(mismatch_by=[slot-mismatch:...])(P6-A2/B2)
    4. 否则若任一 mismatch_aliases(错值 distractor)命中 → status="value_mismatch"
    5. 否则 → status="missing"
    6. **alias-similar override(仅 alias_check_enabled=true,P6-A3 新增)**:
       若 _find_alias_similar 在 norm_text 中扫到"与 canonical 相似但未登记"
       的候选 → **无论 1-5 得 present 还是 missing,都覆盖为** status="value_mismatch",
       mismatch_by="[alias-similar:<候选>~<canonical>]"。同时把 hit 降为 False
       (守护不变量 hit=True ↔ status=present;canonical 在场信息保留在 mismatch_by
       的字符串里)。

    向后兼容:alias_check_enabled 默认 false。无此字段的锚走 1-5 原链,行为逐字不变。
    registered_names 集合(供 _find_alias_similar 排除同册已登记角色)= 本章所有
    atomic anchor 的 normalize(canonical + aliases)。mismatch_aliases 是显式
    错值,不计入 registered_names(它们本就是"错的",不该自我排除)。
    """
    norm_text = normalize(text)
    # 预计算注册名集合(同章 atomic 的 canonical+aliases,normalize 后入集合)。
    # 用 anchors_list(本章全体)而非单锚,是为了让"两真不同角色名相近"互不撞。
    registered_names: set[str] = set()
    for a in anchors_list:
        registered_names.add(normalize(a["canonical"]))
        for al in a.get("aliases", []):
            registered_names.add(normalize(al))

    results = []
    for a in anchors_list:
        anchor_id = a["id"]
        anchor_type = a["type"]
        canonical = a["canonical"]
        aliases = a.get("aliases", [])
        mismatch_aliases = a.get("mismatch_aliases", [])
        cross_chapter = a.get("cross_chapter_of")

        norm_canonical = normalize(canonical)
        status = "missing"
        hit = False
        hit_by = None
        mismatch_by = None

        # 1. present: canonical 或 alias
        if norm_canonical in norm_text:
            status = "present"
            hit = True
            hit_by = canonical
        else:
            for alias in aliases:
                if normalize(alias) in norm_text:
                    status = "present"
                    hit = True
                    hit_by = alias
                    break

        # 1.5 slot-pattern: canonical/alias 未中 → 结构化槽位比对(P6-A2/B1)
        if not hit:
            slot = a.get("slot")
            if slot:
                slot_by = _check_slot_match(slot, norm_text)
                if slot_by:
                    status = "present"
                    hit = True
                    hit_by = slot_by
                else:
                    # 1.6 B2: slot form mismatch(opt-in)。
                    # 仅 mismatch_enabled=true 时启用;slot.value 未中、
                    # 但 slot 模式抽到同形异值 → value_mismatch。
                    slot_mm = _check_slot_form_mismatch(slot, norm_text)
                    if slot_mm:
                        status = "value_mismatch"
                        mismatch_by = slot_mm

        # 2. value_mismatch: canonical/slot 未命中才查 distractor(canonical 优先)。
        # B2:status 已被 slot form mismatch 提为 value_mismatch 时,跳过(信号不被覆盖)。
        if not hit and status != "value_mismatch":
            for distractor in mismatch_aliases:
                if normalize(distractor) in norm_text:
                    status = "value_mismatch"
                    mismatch_by = distractor
                    break

        # 3. P6-A3 · alias-similar override(opt-in)。
        # alias_check_enabled=true 时扫文本找"与 canonical 相似但未登记"的候选。
        # 找到则强制 value_mismatch(无论前序步骤得 present/missing/mismatch)。
        # 注:即便前序 mismatch_aliases 已触发 value_mismatch,override 仍以
        # alias-similar 信号覆盖(异名是更具体的诊断,优先于"显式错值"信号)。
        #
        # 不变量守护:hit=True ↔ status=present(被 compute_stats 等下游依赖)。
        # override 触发时若 hit=True(canonical 也在场),把 hit 降回 False。
        # canonical 在场的诊断信息不丢:mismatch_by 字符串 `[alias-similar:X~canonical]`
        # 含 canonical 原形,人工 review 时仍能看到"哪个规范名被写错"。
        if a.get("alias_check_enabled"):
            variant = _find_alias_similar(canonical, registered_names, norm_text)
            if variant is not None:
                status = "value_mismatch"
                hit = False
                hit_by = None
                mismatch_by = f"[alias-similar:{variant}~{canonical}]"

        results.append({
            "id": anchor_id,
            "type": anchor_type,
            "canonical": canonical,
            "hit": hit,
            "hit_by": hit_by,
            "status": status,
            "mismatch_by": mismatch_by,
            "cross_chapter_of": cross_chapter,
        })
    return results


def check_composite(
    composite_list: list[dict], atomic_results: list[dict]
) -> list[dict]:
    """检查 composite 锚点命中情况。

    命中条件: 所有 members 对应的 atomic 全部命中(AND)。
    """
    hit_map = {r["id"]: r["hit"] for r in atomic_results}
    results = []
    for c in composite_list:
        members = c["members"]
        all_hit = all(hit_map.get(m, False) for m in members)
        member_details = [
            {"id": m, "hit": hit_map.get(m, False)} for m in members
        ]
        results.append({
            "id": c["id"],
            "name": c["name"],
            "all_hit": all_hit,
            "members": member_details,
        })
    return results


# ---------------------------------------------------------------------------
# 统计汇总
# ---------------------------------------------------------------------------
def compute_stats(
    chapter_id: str,
    atomic_results: list[dict],
    composite_results: list[dict] | None = None,
) -> dict[str, Any]:
    """按类型汇总命中统计(present / value_mismatch / missing 三态分桶)。"""
    total = len(atomic_results)
    hits = sum(1 for r in atomic_results if r["hit"])
    value_mismatch = sum(
        1 for r in atomic_results if r.get("status") == "value_mismatch"
    )

    # 按类型分组
    type_stats: dict[str, dict[str, int]] = {}
    for r in atomic_results:
        t = r["type"]
        if t not in type_stats:
            type_stats[t] = {"total": 0, "hit": 0, "value_mismatch": 0}
        type_stats[t]["total"] += 1
        if r["hit"]:
            type_stats[t]["hit"] += 1
        elif r.get("status") == "value_mismatch":
            type_stats[t]["value_mismatch"] += 1

    # 跨章锚子集(T3 等)
    cross_chapter = [r for r in atomic_results if r.get("cross_chapter_of")]
    cross_total = len(cross_chapter)
    cross_hits = sum(1 for r in cross_chapter if r["hit"])

    stats = {
        "chapter": chapter_id,
        "atomic": {
            "total": total,
            "hit": hits,
            "value_mismatch": value_mismatch,
            "miss": total - hits - value_mismatch,
            "ratio": hits / total if total > 0 else 0.0,
        },
        "by_type": {},
        "cross_chapter": {
            "total": cross_total,
            "hit": cross_hits,
            "ratio": cross_hits / cross_total if cross_total > 0 else None,
        },
    }

    for t, s in type_stats.items():
        stats["by_type"][t] = {
            "total": s["total"],
            "hit": s["hit"],
            "value_mismatch": s["value_mismatch"],
            "miss": s["total"] - s["hit"] - s["value_mismatch"],
            "ratio": s["hit"] / s["total"] if s["total"] > 0 else 0.0,
        }

    # composite
    if composite_results is not None:
        comp_total = len(composite_results)
        comp_hits = sum(1 for r in composite_results if r["all_hit"])
        stats["composite"] = {
            "total": comp_total,
            "hit": comp_hits,
            "ratio": comp_hits / comp_total if comp_total > 0 else None,
        }

    return stats


# ---------------------------------------------------------------------------
# 完整检测流程
# ---------------------------------------------------------------------------
def run_check_text(
    yaml_path: str | Path,
    text: str,
    chapter_id: str,
) -> dict[str, Any]:
    """对内存文本执行完整锚点检测(细纲层 planning_text 等不落盘场景)。

    Args:
        yaml_path: anchors.yaml 路径
        text: 待检测文本(细纲或正文)
        chapter_id: 章节标识(如 T1/T2/T3), 必填
    """
    anchors_data = load_anchors(yaml_path)

    chapter_data = anchors_data.get(chapter_id, {})
    atomic_list = chapter_data.get("atomic", [])
    composite_list = chapter_data.get("composite", [])

    atomic_results = check_atomic(atomic_list, text)
    composite_results = check_composite(composite_list, atomic_results) if composite_list else []
    stats = compute_stats(chapter_id, atomic_results, composite_results)

    return {
        "chapter": chapter_id,
        "atomic_results": atomic_results,
        "composite_results": composite_results,
        "stats": stats,
    }


def run_check(
    yaml_path: str | Path,
    text_path: str | Path,
    chapter_id: str | None = None,
) -> dict[str, Any]:
    """对单个文本文件执行完整锚点检测。

    Args:
        yaml_path: anchors.yaml 路径
        text_path: 待检测文本路径
        chapter_id: 章节标识(如 T1/T2/T3), 若 None 则从文件名推断

    Returns:
        完整检测报告字典
    """
    text = load_text(text_path)
    if chapter_id is None:
        chapter_id = Path(text_path).stem.split("_")[0].upper()

    report = run_check_text(yaml_path, text, chapter_id)
    report["source_file"] = str(text_path)
    return report


def run_two_layer_check(
    yaml_path: str | Path,
    chapter_id: str,
    skeleton_text: str,
    body_text: str,
) -> dict[str, Any]:
    """细纲层 + 正文层 便利函数(同一 anchors / chapter_id 跑两次)。

    用于 P6-A2 转正: Architect 出细纲后跑 skeleton(非阻塞早闸),
    Writer 出正文后跑 body(正文层 QC, 已由 AnchorCheckAuditor 承载)。

    Args:
        yaml_path: anchors.yaml 路径
        chapter_id: 章节标识(如 T1)
        skeleton_text: 细纲文本(Stage 1 planning_text)
        body_text: 正文文本(Writer final_text)

    Returns:
        {"skeleton": <report>, "body": <report>}
    """
    return {
        "skeleton": run_check_text(yaml_path, skeleton_text, chapter_id),
        "body": run_check_text(yaml_path, body_text, chapter_id),
    }
