"""守卫与风险标注 — mask/clean/guard 逐条搬自 _s6_ref/jiangfen.py 与 r12_models.py(已验证逻辑)。

- lock_words: 锁定词 = 专名 + 姓氏组合(「常千户」「常家」这类) + 调用方额外词
- mask/unmask: 标题行整行、对白与【】标签 → ⟦D1⟧ 占位符锁死不改;
              锁定词 → ⟦K1⟧ 占位符(长词优先替换)
- clean:      回译稿进守卫前先清洁(中文间多余空白 / 半角 ,;: 换全角 / 占位符后多出的句号)
- dedash:     确定性去破折号(照 r15 的 fix),每层输出 clean 之后、守卫之前过一遍
- guard:      回译稿必须原样带回占位符(个数不变)、不留英文、不自造对白、不并段、
              句末标点不丢、中文后不接半角标点、专名与数字不丢、篇幅 0.7–1.7;
              S-8-1 新增:不添破折号、段中丢句号、示范泄漏(与示范对重合 12 字以上)
- risk_marks: 改后文本里需要作者留意的地方(数字变化/计量单位变化/专名缺失)
"""
from __future__ import annotations

import re

NUM = re.compile(r"\d+(?:\.\d+)?|[零一二三四五六七八九十百千万两]{2,}")
OVERLAP_CHARS = 12  # 「重合 12 字以上」判定长度(示范抽样剔除与示范泄漏守卫共用)
_SLOT = re.compile(r"“[^”]*”|【[^】]*】")
_TOKEN = re.compile(r"⟦[DK]\d+⟧")
# 标题行:井号开头的 markdown 标题,或整行形如「第…章/节/卷/回」且行内无句读
_TITLE = re.compile(
    r"^[ \t]*(?:#{1,6}[ \t]*\S[^\n]*|第[0-9零一二三四五六七八九十百千两]+[章节卷回][^\n。！？!?，,；;]*)$",
    re.MULTILINE,
)
# 姓氏组合:人名首字 + 称谓/排行(「常千户」「常家」「常大少爷」「常二哥」这类),
# 锁死防回译把姓氏改成同音字(实测 GLM-5.2 把「常千户」写成「昌千户」)
_KIN = (
    "大少爷|大姑娘|千户|百户|总旗|大人|老爷|夫人|公子|小姐|姑娘|少爷|当家|掌柜|家"
    "|[一二三四五六七八九十][哥弟妹姐]"
)


def lock_words(text: str, terms: list[str], extra: "list[str] | None" = None) -> list[str]:
    """锁定词:出现在文本里的专名 + 姓氏组合 + 调用方额外传入的词(同样要求出现在文本里)。"""
    words = [k for k in terms if k and k in text]
    for term in terms:
        if not term:
            continue
        for m in re.finditer(re.escape(term[0]) + "(?:%s)" % _KIN, text):
            if m.group(0) not in words:
                words.append(m.group(0))
    for k in extra or []:
        if k and k in text and k not in words:
            words.append(k)
    return words


def mask(text: str, locks: "list[str] | None" = None) -> "tuple[str, list[str], int]":
    """标题行/对白/【】标签 → ⟦D1⟧…;锁定词 → ⟦K1⟧…(长词优先替换)。

    返回 (遮罩文本, 原文片段列表, 对白占位数 nd);items 前 nd 项对应 ⟦D⟧,其余对应 ⟦K⟧。
    """
    items: list[str] = []

    def _rep(m: re.Match) -> str:
        items.append(m.group(0))
        return "⟦D%d⟧" % len(items)

    text = _TITLE.sub(_rep, text)
    text = _SLOT.sub(_rep, text)
    nd = len(items)
    for k in sorted(locks or [], key=len, reverse=True):
        if k in text:
            items.append(k)
            text = text.replace(k, "⟦K%d⟧" % len(items))
    return text, items, nd


def unmask(text: str, items: list[str], nd: int) -> str:
    """把 ⟦Dn⟧/⟦Kn⟧ 换回原文片段(nd = 对白占位数)。"""
    for i, original in enumerate(items, 1):
        text = text.replace("⟦%s%d⟧" % ("D" if i <= nd else "K", i), original)
    return text


def strip_slots(text: str) -> str:
    """剔除占位符与空白后的正文(判「几乎全是对白」用)。"""
    return re.sub(r"⟦[DK]\d+⟧|\s", "", text)


# 中文间多余空白:只看横向空白(空格/制表/全角空格),不动换行——动换行会把并段守卫误伤
_SPACE = re.compile(
    r"(?<=[一-鿿])[ \t　]+(?=[一-鿿“”【⟦])"
    r"|(?<=[一-鿿”】⟧，。；：！？、])[ \t　]+(?=[一-鿿⟦])"
)


def clean(text: str) -> str:
    """回译稿进守卫前的常规清洁(照 r12_models.clean,占位符邻接处一并处理):
    中文后的半角 , ; : 换全角;中文与中文/引号/占位符之间的多余空白;占位符后多出来的句号。
    (先换标点再去空白:「字, ⟦K⟧」里的空格要等逗号变全角后才处在可清的位置)"""
    text = re.sub(r"(?<=[一-鿿”⟧]),", "，", text)
    text = re.sub(r"(?<=[一-鿿”⟧]);", "；", text)
    text = re.sub(r"(?<=[一-鿿”⟧]):", "：", text)
    text = _SPACE.sub("", text)
    return re.sub(r"(⟦[DK]\d+⟧)。", r"\1", text)


def dedash(text: str) -> str:
    """确定性去破折号(照 r15 的 fix):——+ / — / -- → 「，」,再收拾「，，」与「，。」。"""
    text = re.sub(r"——+|--|—", "，", text)
    text = re.sub(r"，{2,}", "，", text)
    return text.replace("，。", "。")


_SENT_END = re.compile(r"[。！？…!?]$")
_LETTER_END = re.compile(r"[一-鿿A-Za-z]$")
# 段中丢句号:句末标点(段内计数)与「80 字以上无句读长串」都用这套字符
_PARA_ENDS = re.compile(r"[。！？…]")
_RUN_BREAK = re.compile(r"[。！？；…]")
_RUN_CHARS = 80


def _shingles(text: str, width: int = OVERLAP_CHARS) -> "set[str]":
    """文本里所有 length=width 的滑窗片段(重合判定用)。"""
    return {text[i:i + width] for i in range(len(text) - width + 1)}


def guard(masked: str, out: str, terms: list[str],
          exemplars: "list[str] | None" = None, *, length: bool = True) -> str:
    """改写稿守卫:返回 ""=通过,否则返回违规原因(给作者看的短词)。

    exemplars: 本次提示词里用到的示范文本(src/dst),出现与之重合 12 字以上
               且不在输入里的片段 = 示范泄漏;
    length=False: 跳过篇幅带(去 AI 味按块改写,合法增删幅度超过 0.7–1.7)。
    """
    if not out:
        return "空"
    for m in _TOKEN.finditer(masked):
        token = m.group(0)
        if out.count(token) != masked.count(token):
            return "对白占位" if token[1] == "D" else "专名占位"
    if set(_TOKEN.findall(out)) - set(_TOKEN.findall(masked)):
        return "占位残留"
    if "“" in out:
        return "自造对白"
    if re.search(r"[A-Za-z]{3,}", out):
        return "英文残留"
    if out.count("—") > masked.count("—") or out.count("--") > masked.count("--"):
        return "破折号"   # 每层输出都过 dedash,改稿里不该多出新破折号
    m_lines = [l for l in masked.splitlines() if l.strip()]
    o_lines = [l for l in out.splitlines() if l.strip()]
    if len(o_lines) < len(m_lines):
        return "并段"
    for a, b in zip(m_lines, o_lines):
        # 原文段末有句末标点而改后段末落在字上 = 句号丢了;
        # 改后段末是占位符/引号时不判(对白自带句读,占位符看不出内容)
        if _SENT_END.search(a) and _LETTER_END.search(b):
            return "句末标点"
    for a, b in zip(m_lines, o_lines):
        # 段中丢句号(逐段):原段句末标点 ≥3 而改后同段不到原来一半
        n_a = len(_PARA_ENDS.findall(a))
        if n_a >= 3 and len(_PARA_ENDS.findall(b)) * 2 < n_a:
            return "段中丢句号"
    out_run = max((len(part) for part in _RUN_BREAK.split(out)), default=0)
    src_run = max((len(part) for part in _RUN_BREAK.split(masked)), default=0)
    if out_run >= _RUN_CHARS and src_run < _RUN_CHARS:
        return "段中丢句号"   # 改后出现 80 字以上无句读长串而原文没有
    if re.search(r"[一-鿿”][,;:]", out):
        return "半角标点"
    if exemplars:
        out_hits = _shingles(out)
        masked_hits = _shingles(masked)
        for ex in exemplars:
            if _shingles(ex) & out_hits - masked_hits:
                return "示范泄漏"
    lost = [k for k in terms if masked.count(k) != out.count(k)]
    if lost:
        return "专名:" + "/".join(lost[:3])
    if set(NUM.findall(masked)) - set(NUM.findall(out)):
        return "数字"
    if length and not 0.7 <= len(out) / max(1, len(masked)) <= 1.7:
        return "篇幅"
    return ""


# 计量单位:改后出现「外文式单位」且改前有对应中文单位 → 提醒(如「尺」变「英尺」)
_FOREIGN_UNITS: dict[str, tuple[str, ...]] = {
    "英尺": ("尺",), "英寸": ("寸",), "英里": ("里",), "海里": ("里",), "公里": ("里",),
    "公斤": ("斤",), "磅": ("斤",), "克": ("钱", "两"), "吨": ("斤",),
    "米": ("丈", "尺"), "厘米": ("寸",), "毫米": ("分",), "码": ("丈", "步"),
    "小时": ("时辰",), "分钟": ("刻",), "秒": ("息",), "英亩": ("亩",), "加仑": ("斗", "桶"),
}
_FOREIGN_UNIT_RE = re.compile("|".join(map(re.escape, sorted(_FOREIGN_UNITS, key=len, reverse=True))))


def risk_marks(before: str, after: str, terms: list[str]) -> list[dict]:
    """改后文本里需要作者留意的地方。

    每项 {kind, before, after, start, end}:
    - kind: "number" 数字变化 / "unit" 计量单位变化 / "term" 专名缺失
    - start/end: 在 after 里的字符区间;-1 表示改后文本里没有对应位置(东西没了)
    """
    risks: list[dict] = []

    # 1) 数字:改后新出现/换值的数字,与改前消失的数字按出现顺序配对
    before_nums = NUM.findall(before)
    after_hits = [(m.group(0), m.start(), m.end()) for m in NUM.finditer(after)]
    before_set = set(before_nums)
    after_set = {value for value, _, _ in after_hits}
    gone = [n for n in dict.fromkeys(before_nums) if n not in after_set]
    appeared = [h for h in after_hits if h[0] not in before_set]
    for i, (value, start, end) in enumerate(appeared):
        risks.append({
            "kind": "number", "before": gone[i] if i < len(gone) else "",
            "after": value, "start": start, "end": end,
        })
    for value in gone[len(appeared):]:
        risks.append({"kind": "number", "before": value, "after": "", "start": -1, "end": -1})

    # 2) 计量单位:外文式单位出现在改后,且改前有对应中文单位
    for m in _FOREIGN_UNIT_RE.finditer(after):
        foreign = m.group(0)
        if foreign in before:
            continue
        natives = [n for n in _FOREIGN_UNITS[foreign] if n in before]
        if natives:
            risks.append({
                "kind": "unit", "before": natives[0], "after": foreign,
                "start": m.start(), "end": m.end(),
            })

    # 3) 专名:出现次数变少(守卫逐稿拦截,这里兜底查最终成稿)
    for term in terms:
        if not term:
            continue
        count_before = before.count(term)
        count_after = after.count(term)
        if count_before > count_after:
            after_label = "" if count_after == 0 else f"还剩 {count_after} 处(原有 {count_before} 处)"
            risks.append({"kind": "term", "before": term, "after": after_label, "start": -1, "end": -1})

    return risks
