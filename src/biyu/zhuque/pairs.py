"""示范对(中文改中文 few-shot)的加载与抽样 — 数据文件与剔除思路照 _s8_ref/r15_zhzh.py。

- load_pairs: 用户数据目录(~/.biyu,可用 BIYU_USER_CONFIG_DIR 指定;在书库根之外)
  里有 zhzh_pairs.json 且 version 比包内新 → 用用户的;坏文件忽略,回落包内版本。
- sample_pairs: 每次调用取至多 12 对;src 或 dst 与当前窗正文重合 12 字以上的
  示范对剔除(防示范泄漏进改稿)。取样按文件顺序取前 12 对,确定性可复现。
"""
from __future__ import annotations

import json
from pathlib import Path

from biyu.secure_config import user_config_dir

from .guards import OVERLAP_CHARS

PAIRS_FILE = "zhzh_pairs.json"
SAMPLE_LIMIT = 12  # 每次改写带的示范对上限(r15 实测用量)
# 包内数据文件路径;模块级常量是为了测试能 monkeypatch 到假文件(S-8-3 解耦)
BUNDLED_PATH = Path(__file__).with_name("data") / PAIRS_FILE


def _version_key(version: str) -> tuple:
    """版本键:「2026.11-3」→可比较元组;数字段按数值、非数字段按字符串,恒可比较。"""

    def _part(p: str) -> tuple:
        return (0, int(p), "") if p.isdigit() else (1, 0, p)

    date, _, suffix = str(version).partition("-")
    return tuple(_part(p) for p in date.split(".")) + (_part(suffix) if suffix else (-1, 0, ""),)


def _load_file(path: Path) -> "tuple[str, list[dict]] | None":
    """读一个示范对文件;打不开/不是合法结构 → None(调用方回落别的来源)。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        pairs = data["pairs"]
        version = str(data.get("version") or "")
        if not isinstance(pairs, list):
            return None
        for p in pairs:
            if not isinstance(p, dict) or not p.get("src") or not p.get("dst"):
                return None
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return version, pairs


def load_pairs() -> "tuple[str, list[dict]]":
    """(version, pairs):用户目录版本更新则用用户的,否则用包内的。"""
    bundled = _load_file(BUNDLED_PATH) or ("", [])
    user = _load_file(user_config_dir() / PAIRS_FILE)
    if user and _version_key(user[0]) > _version_key(bundled[0]):
        return user
    return bundled


def sample_pairs(pairs: list[dict], window_text: str,
                 limit: int = SAMPLE_LIMIT, overlap: int = OVERLAP_CHARS) -> list[dict]:
    """按顺序取至多 limit 对示范,剔除与 window_text 重合 overlap 字以上的对。"""
    if len(window_text) < overlap:
        return pairs[:limit]
    window_hits = {window_text[i:i + overlap] for i in range(len(window_text) - overlap + 1)}

    def _leaks(text: str) -> bool:
        return any(text[i:i + overlap] in window_hits
                   for i in range(len(text) - overlap + 1))

    picked: list[dict] = []
    for pair in pairs:
        if _leaks(str(pair.get("src") or "")) or _leaks(str(pair.get("dst") or "")):
            continue
        picked.append(pair)
        if len(picked) >= limit:
            break
    return picked
