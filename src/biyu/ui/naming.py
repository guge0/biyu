"""T7 起名器 v0 (P8-M3 T7)— 占位模式下基于规则生成候选名。

设计:
- 占位模式:读 prompts/assets/命名范式_v0.md → 按题材匹配范式模板 → 生成候选
- apply_name:将选中书名写入 book.json 的 display_name 字段
- 零 LLM 调用,成本 = ¥0

起名 prompt 过关后替换为 LLM 生成(本模块保持接口不变)。
"""
from __future__ import annotations

import json
import logging
import random
from pathlib import Path
from typing import Any

from biyu.config import get_data_root
from biyu.fingerprint.adapter import _extract_json_object
from biyu.llm import ModelRegistry
from biyu.ui.cost_log import write_cost_log
from biyu.ui.prompts_naming import build_naming_messages, is_naming_placeholder, read_paradigm_ref
from biyu.ui.scan_cache import scan_all_cached

logger = logging.getLogger("biyu.ui.naming")

# 各题材的范式候选名(占位模式,从命名范式文档提炼)
_PARADIGM_NAMES: dict[str, list[tuple[str, str]]] = {
    "xianxia": [
        ("玄鉴仙诀", "四字凝练型:二字意象+仙族/场景"),
        ("赤心问道", "四字凝练型:信念+行动"),
        ("青云剑宗", "四字凝练型:意象+门派"),
        ("紫府修仙传", "五字叙事型:场景+题材"),
        ("苟在仙门成圣", "叙事感长句型:苟字系流行句式"),
        ("剑破九霄", "四字凝练型:武器+场景"),
        ("灵虚渡劫录", "五字叙事型:场景+主题"),
        ("青云之上", "四字凝练型:场景+方位词"),
    ],
    "xuanhuan": [
        ("星穹之主", "三字主语谓型:概念+之主"),
        ("天荒问道", "四字凝练型:场景+行动"),
        ("神渊之纪", "四字凝练型:意象+纪元"),
        ("万道争锋", "四字凝练型:体系+冲突"),
        ("九幽炼神", "四字凝练型:地点+行动"),
        ("太初有道", "四字凝练型:时间+存在"),
        ("我在大荒修神", "叙事感长句型:我在+地点+动作"),
        ("鸿蒙之主", "三字主语谓型:意象+之主"),
    ],
    "dushi": [
        ("我在都市修行", "叙事感长句型:我在+地点+动作"),
        ("我的群里全是大佬", "叙事感长句型:第一人称+设定反转"),
        ("都市天机", "四字凝练型:场景+悬疑"),
        ("龙城风云", "四字凝练型:地点+事件"),
        ("烟火人间", "四字凝练型:意象+场景"),
        ("1984：从今天开始", "冒号分隔型:年代+冒号+起点"),
    ],
    "kehuan": [
        ("异度旅社", "四字凝练型:异度+场景"),
        ("星门穿梭", "四字凝练型:场景+动作"),
        ("深空纪元", "四字凝练型:场景+时间"),
        ("光年之外", "四字凝练型:距离+方位"),
        ("星际开拓者", "五字身份型:场景+身份"),
        ("超维入侵", "四字凝练型:概念+冲突"),
    ],
    "lishi": [
        ("大周风云", "四字凝练型:朝代+场景"),
        ("盛唐无双", "四字凝练型:朝代+气势"),
        ("大宋江湖", "四字凝练型:朝代+题材"),
        ("春秋问道", "四字凝练型:时代+行动"),
        ("青史留名", "四字凝练型:概念+结果"),
        ("天下为棋", "四字凝练型:格局+比喻"),
    ],
    "qingxiaoshuo": [
        ("我绑定了系统", "叙事感长句型:第一人称+设定"),
        ("我的日常不正常", "叙事感长句型:第一人称+反差"),
        ("幻界奇缘", "四字凝练型:场景+事件"),
        ("怪异日常", "四字凝练型:题材+风格"),
        ("我有一间秘境", "叙事感长句型:第一人称+设定"),
        ("奇妙冒险录", "五字叙事型:风格+主题"),
    ],
}

# 通用候选(题材无关,经典范例)
_FALLBACK_NAMES: list[tuple[str, str]] = [
    ("星辰变", "经典四字格范例"),
    ("无名诀", "通用四字格"),
    ("天启纪元", "通用四字格"),
    ("万象更新", "通用四字格"),
    ("一念永恒", "经典网文书名"),
]

# 题材关键词映射
_GENRE_KEYWORDS: dict[str, list[str]] = {
    "xianxia": ["仙", "玄", "剑", "修仙", "道"],
    "xuanhuan": ["夜", "荒", "神", "主", "界", "武", "天"],
    "dushi": ["我", "都", "市", "群"],
    "kehuan": ["异度", "星", "旅", "穿梭"],
    "lishi": ["晋", "唐", "宋", "明", "朝"],
    "qingxiaoshuo": ["我", "反差", "魔", "怪"],
}

_TARGET_PLATFORM = "起点"


def _get_naming_adapter() -> Any | None:
    """Get LLM adapter for naming. Returns None if unavailable."""
    try:
        return ModelRegistry().get_adapter("v4_flash")
    except (FileNotFoundError, KeyError, ValueError):
        logger.warning("Naming LLM adapter not available")
        return None


def _parse_llm_candidates(text: str) -> list[dict[str, Any]] | None:
    """Parse LLM response into candidate list.

    Expects JSON with "candidates" array, each with "name", "paradigm", "reason".
    Falls back to extracting JSON object from arbitrary text.
    """
    try:
        obj = _extract_json_object(text)
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    raw_candidates = obj.get("candidates", [])
    if not isinstance(raw_candidates, list) or not raw_candidates:
        return None
    parsed: list[dict[str, Any]] = []
    for c in raw_candidates:
        if isinstance(c, dict) and "name" in c:
            parsed.append({
                "name": str(c["name"]),
                "paradigm": str(c.get("paradigm", c.get("style", ""))),
                "reason": str(c.get("reason", c.get("why", ""))),
            })
    return parsed if parsed else None


def _read_scan_data(data_root: Path | None = None) -> str:
    """读取扫榜缓存文本,作为起名参照语料。"""
    if data_root is None:
        data_root = get_data_root()
    try:
        results, meta = scan_all_cached(
            platforms=["qidian", "fanqie"],
            force_refresh=False,
            data_root=data_root,
        )
        if not meta.get("cached"):
            return ""
        lines: list[str] = []
        for platform, pr in results.items():
            if pr.success and pr.books:
                lines.append(f"--- {platform} ---")
                for b in pr.books[:10]:
                    lines.append(f"  {b.title} ({b.author}) [{b.category}]")
        return "\n".join(lines)
    except Exception as e:
        logger.warning("扫榜缓存读取失败: %s", e)
        return ""


async def generate_names(idea: str, genre: str) -> dict[str, Any]:
    """生成候选书名列表。

    Args:
        idea: 作者设想文本(可空)
        genre: 题材代号(如 xuanhuan / dushi)

    Returns:
        dict {
            "candidates": list[{"name", "paradigm", "reason"}],
            "source": "template" | "llm",
            "target_platform": str,
            "paradigm_ref": str,
            "cost_cny": float,
        }
    """
    # 空输入直接拒绝(¥0)
    if not idea or not idea.strip():
        return {
            "candidates": [],
            "source": "empty_rejected",
            "target_platform": "qidian",
            "paradigm_ref": "",
            "cost_cny": 0.0,
            "error": "起名需要填写创作设想(idea)",
            "hint": "输入你的创作想法,哪怕只有一句话。¥0.00",
        }

    # 读范式文档(作为背景参考)
    paradigm_ref = read_paradigm_ref()

    if is_naming_placeholder():
        # === 占位模式:模板候选 ===
        candidates: list[dict[str, Any]] = []

        pool = _PARADIGM_NAMES.get(genre, _PARADIGM_NAMES.get("xuanhuan", []))
        shuffled = list(pool)
        random.shuffle(shuffled)

        keywords = _GENRE_KEYWORDS.get(genre, ["通用"])
        kw_hint = "、".join(keywords[:3])

        for name, paradigm in shuffled:
            reason = f"基于{paradigm},适合{genre}题材(关键词:{kw_hint})"
            candidates.append({
                "name": name,
                "paradigm": paradigm,
                "reason": reason,
            })
            if len(candidates) >= 6:
                break

        random.shuffle(_FALLBACK_NAMES)
        for name, paradigm in _FALLBACK_NAMES:
            if len(candidates) >= 8:
                break
            if not any(c["name"] == name for c in candidates):
                candidates.append({
                    "name": name,
                    "paradigm": paradigm,
                    "reason": "经典网文命名风格,通用适配",
                })

        return {
            "candidates": candidates[:8],
            "source": "template",
            "target_platform": _TARGET_PLATFORM,
            "paradigm_ref": paradigm_ref,
            "cost_cny": 0.0,
        }

    # === 真 LLM 模式 ===
    adapter = _get_naming_adapter()
    if adapter is None:
        # adapter 不可用 → 降级到模板
        logger.warning("Naming adapter unavailable, falling back to template")
        return _fallback_template(idea, genre, paradigm_ref)

    # 获取扫榜数据作为参照语料
    scan_data = _read_scan_data()

    # 构建 prompt
    messages = build_naming_messages(
        idea=idea,
        genre=genre,
        scan_data=scan_data,
        paradigm_ref=paradigm_ref,
    )

    try:
        resp = await adapter.generate(messages)
        text = resp.text or ""
        cost = float(getattr(resp, "cost", 0.0) or 0.0)

        # D-93 中央成本台账
        if cost > 0:
            try:
                write_cost_log(
                    task="naming",
                    book=genre,
                    session="naming",
                    cost=cost,
                    model=getattr(adapter, "model_name", ""),
                )
            except Exception:
                logger.warning("写 cost_log 失败", exc_info=True)

        candidates = _parse_llm_candidates(text)
        if candidates is None:
            logger.warning("LLM 起名候选解析失败,降级到模板")
            return _fallback_template(idea, genre, paradigm_ref)

        return {
            "candidates": candidates[:10],
            "source": "llm",
            "target_platform": _TARGET_PLATFORM,
            "paradigm_ref": paradigm_ref,
            "cost_cny": cost,
        }
    except Exception as e:
        logger.warning("LLM 起名调用异常: %s, 降级到模板", e)
        return _fallback_template(idea, genre, paradigm_ref)


def _fallback_template(idea: str, genre: str, paradigm_ref: str) -> dict[str, Any]:
    """LLM 不可用/失败时的纯模板降级。"""
    candidates: list[dict[str, Any]] = []
    pool = _PARADIGM_NAMES.get(genre, _PARADIGM_NAMES.get("xuanhuan", []))
    shuffled = list(pool)
    random.shuffle(shuffled)
    keywords = _GENRE_KEYWORDS.get(genre, ["通用"])
    kw_hint = "、".join(keywords[:3])
    for name, paradigm in shuffled:
        candidates.append({
            "name": name,
            "paradigm": paradigm,
            "reason": f"基于{paradigm},适合{genre}题材(关键词:{kw_hint})",
        })
        if len(candidates) >= 6:
            break
    random.shuffle(_FALLBACK_NAMES)
    for name, paradigm in _FALLBACK_NAMES:
        if len(candidates) >= 8:
            break
        if not any(c["name"] == name for c in candidates):
            candidates.append({
                "name": name,
                "paradigm": paradigm,
                "reason": "经典网文命名风格,通用适配",
            })
    return {
        "candidates": candidates[:8],
        "source": "template_fallback",
        "target_platform": _TARGET_PLATFORM,
        "paradigm_ref": paradigm_ref,
        "cost_cny": 0.0,
    }


def apply_name(book_dir: Path, new_title: str) -> dict[str, Any]:
    """将选中书名应用到 book.json 的 display_name 字段。

    Args:
        book_dir: data/<book>/ 目录
        new_title: 选中的书名

    Returns:
        dict {ok: bool, title: str, display_name: str}
    """
    book_json = book_dir / "book.json"
    if not book_json.exists():
        raise FileNotFoundError(f"book.json 不存在:{book_json}")

    try:
        meta = json.loads(book_json.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        raise ValueError(f"读 book.json 失败:{e}") from e

    meta["display_name"] = new_title
    book_json.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("书名已应用: %s → display_name=%s", book_dir.name, new_title)

    return {
        "ok": True,
        "title": meta.get("title", ""),
        "display_name": new_title,
    }
