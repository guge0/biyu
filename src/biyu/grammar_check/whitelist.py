"""白名单加载 — 从 worldbook + characters 提取专有名词，避免误报。"""
from __future__ import annotations

import re
from pathlib import Path

import yaml


def load_whitelist(book_dir: Path) -> set[str]:
    """从 worldbook + characters 提取所有专有名词。

    Returns:
        白名单集合（小写不敏感匹配的话需调用方处理）。
    """
    whitelist: set[str] = set()

    # --- worldbook 设定词 ---
    wb_path = book_dir / "worldbook.yaml"
    if wb_path.exists():
        with open(wb_path, encoding="utf-8") as f:
            wb = yaml.safe_load(f) or {}

        # facts 条目中的专有名词
        for fact in wb.get("facts", []):
            _extract_nouns(fact, whitelist)

        # forbidden 条目
        for item in wb.get("forbidden", []):
            _extract_nouns(item, whitelist)

        # power_system
        for section in ("power_system", "factions", "geography"):
            for item in wb.get(section, []):
                if isinstance(item, str):
                    _extract_nouns(item, whitelist)
                elif isinstance(item, dict):
                    for v in item.values():
                        if isinstance(v, str):
                            _extract_nouns(v, whitelist)

        # narrative_anchors
        for anchor in wb.get("narrative_anchors", []):
            if isinstance(anchor, dict):
                _extract_nouns(anchor.get("name", ""), whitelist)

        # npc_whitelist
        for npc in wb.get("npc_whitelist", []):
            if isinstance(npc, str):
                whitelist.add(npc)
            elif isinstance(npc, dict):
                whitelist.add(npc.get("name", ""))

    # --- characters 角色名 ---
    chars_path = book_dir / "characters.yaml"
    if chars_path.exists():
        with open(chars_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        characters = data.get("characters", [])
        for char in characters:
            name = char.get("name", "")
            if name:
                whitelist.add(name)

            # aliases
            aliases = char.get("aliases", {})
            for key in ("narrator_default", "first_person", "called_by"):
                val = aliases.get(key, {})
                if isinstance(val, dict):
                    whitelist.update(val.values())
                elif isinstance(val, str):
                    whitelist.add(val)

            # voice_examples 口语词
            for example in char.get("voice_examples", []):
                # 提取短词（1-4字的口语/口头禅）
                _extract_oral_words(example, whitelist)

    # --- 常见网文用语 ---
    whitelist.update(_common_xuanhuan_terms())

    # 过滤空串和单字符
    whitelist.discard("")
    whitelist = {w for w in whitelist if len(w) >= 2}

    return whitelist


def _extract_nouns(text: str, out: set[str]) -> None:
    """从文本中提取中文专有名词（2-6字的连续中文字符串中的常见模式）。"""
    if not text:
        return
    # 提取所有 2-8 字连续中文词
    for m in re.finditer(r'[\u4e00-\u9fff]{2,8}', text):
        word = m.group()
        # 过滤常见非专有名词
        if word in _STOP_WORDS:
            continue
        if len(word) <= 6:
            out.add(word)


def _extract_oral_words(text: str, out: set[str]) -> None:
    """从 voice_examples 中提取短口语词。"""
    if not text:
        return
    # 匹配引号内的短句
    for m in re.finditer(r'[\u4e00-\u9fff]{2,4}', text):
        word = m.group()
        out.add(word)


_STOP_WORDS: set[str] = {
    "不是", "而是", "虽然", "但是", "因为", "所以", "如果", "那么",
    "已经", "正在", "可以", "可能", "应该", "必须", "需要", "知道",
    "看到", "听到", "觉得", "认为", "发现", "出现", "开始", "结束",
    "一个", "这个", "那个", "什么", "怎么", "为什么", "哪里", "那里",
    "之后", "之前", "中间", "上面", "下面", "里面", "外面", "旁边",
    "然后", "接着", "最后", "突然", "忽然", "终于", "果然", "竟然",
    "同时", "此时", "这时", "那时", "马上", "立刻", "瞬间", "刹那",
    "非常", "十分", "极其", "特别", "真的", "确实", "居然", "简直",
    "没有", "无法", "不能", "不会", "不要", "不敢", "不想", "不肯",
    "时候", "地方", "东西", "问题", "办法", "关系", "情况", "事情",
    "的话", "似的", "一样", "一般", "这么", "那么", "多么", "怎么",
}

_COMMON_XUANHUAN_TERMS: set[str] = {
    "镇异局", "命甲", "古虚帝国", "古虚遗迹", "外部观察者", "异种共振",
    "补天石", "半阶补天石", "白色空间", "意识体", "本命器",
    "卧槽", "我擦", "靠", "卧擦",
}


def _common_xuanhuan_terms() -> set[str]:
    return _COMMON_XUANHUAN_TERMS
