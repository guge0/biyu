"""T3/T4 工具分发 — 责编/导演会话的工具查询后端 (P8-M3 T3+T4)。

设计:
- `run_chat_tools(book_dir, data_root, message)` → T3 责编工具集
- `run_director_tools(book_dir, message)` → T4 导演工具集
  每个工具结果 = {"name": str, "args": dict, "result": str, "cost": float}
- 简单关键词匹配路由意图(非 LLM),严格占位模式,无 LLM 调用。
- 所有工具纯文件读取,成本 = 0。

P8-M3R R2(D-96 分层读书 L2):
- `_tool_read_chapter(book_dir, n)` 读单章正文(≤4000 字截断)
- `_tool_read_chapters(book_dir, nums)` 多章(≤3 上限 + 采样声明)
- `_parse_chapter_numbers(message)` 从消息解析章号
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from biyu.editor.tools import look_up_character, look_up_setting
from biyu.propose.craft import read_craft_file
from biyu.truth_files import read_all_truth_files
from biyu.ui.scan_cache import scan_all_cached

logger = logging.getLogger("biyu.ui.chat_tools")

# 固定占位提示(编辑人格未定稿)
_PLACEHOLDER_NOTE = "编辑人格待定稿，当前仅代查资料。"

# D-96:每轮 ≤3 章上限
_MAX_CHAPTERS_PER_TURN = 3

# 单章正文截断上限(D-96:超长截断仍守 ≤4000 字/章)
_CHAPTER_MAX_CHARS = 4000


def run_chat_tools(
    book_dir: Path,
    data_root: Path,
    message: str,
) -> list[dict]:
    """根据用户消息选配工具,执行并返回结果列表。

    每个工具结果 dict:
        - name: 工具名
        - args: 调用参数
        - result: 文本结果(≥1 行)
        - cost: 成本(纯文件读取 = 0.0)
    """
    intents = _route_intent(message)
    results: list[dict] = []

    # R2(D-96 L2):消息含章号 → 触发 read_chapter
    chapter_nums = _parse_chapter_numbers(message)
    if chapter_nums:
        results.extend(_tool_read_chapters(book_dir, chapter_nums))

    for intent in intents:
        if intent == "truth_files":
            r = _tool_truth_files(book_dir)
        elif intent == "character":
            r = _tool_lookup_character(book_dir, message)
        elif intent == "setting":
            r = _tool_lookup_setting(book_dir, message)
        elif intent == "review":
            r = _tool_review(book_dir)
        elif intent == "craft":
            r = _tool_craft()
        elif intent == "scan":
            r = _tool_scan(data_root)
        else:
            continue
        results.append(r)

    if not results:
        # 保底:返回默认工具集
        results = [
            _tool_truth_files(book_dir),
            _tool_craft(),
            _tool_scan(data_root),
        ]

    return results


# ---------------------------------------------------------------------------
# 意图路由
# ---------------------------------------------------------------------------

# 关键词 → 意图映射(简单关键词匹配,非 LLM)
_INTENT_KEYWORDS: list[tuple[list[str], str]] = [
    (["人物", "角色", "人设", "性格"], "character"),
    (["设定", "世界观", "背景", "力量体系"], "setting"),
    (["审读", "review", "审稿", "审阅", "读一下", "看看章节"], "review"),
    (["创作", "规律", "craft", "节奏", "爽点", "开篇", "目标体系"], "craft"),
    (["市场", "扫榜", "行情", "榜单", "排行", "热门", "番茄", "起点"], "scan"),
    (["真相", "truth", "状态", "当前状态", "粒子账", "钩子", "hook"], "truth_files"),
]


def _route_intent(message: str) -> list[str]:
    """关键词匹配 → 命中的意图列表(去重,保持优先级顺序)。"""
    seen: set[str] = set()
    results: list[str] = []
    msg_lower = message.lower()
    for keywords, intent in _INTENT_KEYWORDS:
        if any(kw in msg_lower for kw in keywords):
            if intent not in seen:
                seen.add(intent)
                results.append(intent)

    # 如果没有命中任何意图，返回空列表，由调用方补默认
    return results


# ---------------------------------------------------------------------------
# 工具实现
# ---------------------------------------------------------------------------


def _tool_truth_files(book_dir: Path) -> dict:
    """读取三份真相文件并格式化摘要。"""
    name = "read_truth_files"
    args: dict = {}
    try:
        data = read_all_truth_files(book_dir)
        lines: list[str] = []
        for fname in ("current_state.md", "particle_ledger.md", "pending_hooks.md"):
            content = data.get(fname, "").strip()
            if content:
                lines.append(f"=== {fname} ===")
                lines.append(content[:1000])  # 截断,单文件 ≤1000 字
                lines.append("")
        result = "\n".join(lines) if lines else "(真相文件为空或不存在)"
    except Exception as e:
        logger.warning("真相文件读取失败:%s", e)
        result = f"(读取失败:{e})"
    return {"name": name, "args": args, "result": result, "cost": 0.0}


def _tool_lookup_character(book_dir: Path, message: str) -> dict:
    """从消息中提取角色名并查询。"""
    name = "look_up_character"
    char_name = _extract_name(message)
    args = {"char_name": char_name}
    try:
        result = look_up_character(char_name, book_dir)
    except Exception as e:
        logger.warning("角色查询失败:%s", e)
        result = f"(查询失败:{e})"
    return {"name": name, "args": args, "result": result, "cost": 0.0}


def _tool_lookup_setting(book_dir: Path, message: str) -> dict:
    """从消息中提取关键词并查询 worldbook。"""
    name = "look_up_setting"
    keyword = _extract_keyword(message)
    args = {"keyword": keyword}
    try:
        result = look_up_setting(keyword, book_dir)
    except Exception as e:
        logger.warning("设定查询失败:%s", e)
        result = f"(查询失败:{e})"
    return {"name": name, "args": args, "result": result, "cost": 0.0}


def _tool_review(book_dir: Path) -> dict:
    """读取最新 standalone 审读结果文件。

    文件路径模式: <book>/reviews/standalone/ch{N}.md
    取编号最大的文件。
    """
    name = "read_review"
    args: dict = {}
    try:
        reviews_dir = book_dir / "reviews" / "standalone"
        if not reviews_dir.exists():
            result = "(暂无审读结果)"
        else:
            ch_files = sorted(
                [f for f in reviews_dir.iterdir() if f.suffix == ".md" and f.stem.startswith("ch")],
                key=lambda f: int(f.stem[2:]) if f.stem[2:].isdigit() else 0,
                reverse=True,
            )
            if not ch_files:
                result = "(暂无审读结果)"
            else:
                latest = ch_files[0]
                content = latest.read_text(encoding="utf-8")
                result = f"最新审读: {latest.name}\n\n{content[:2000]}"
    except Exception as e:
        logger.warning("审读读取失败:%s", e)
        result = f"(读取失败:{e})"
    return {"name": name, "args": args, "result": result, "cost": 0.0}


def _tool_craft() -> dict:
    """读取 craft 蒸馏文件,返回各节内容。"""
    name = "read_craft"
    args: dict = {}
    try:
        content = read_craft_file()
        if not content:
            result = "(Craft 参考文件暂未就绪)"
        else:
            result = content[:3000]  # 截断 ≤3000 字
    except Exception as e:
        logger.warning("Craft 读取失败:%s", e)
        result = f"(读取失败:{e})"
    return {"name": name, "args": args, "result": result, "cost": 0.0}


def _tool_scan(data_root: Path) -> dict:
    """读取最新扫榜缓存。

    使用 scan_all_cached 读取已缓存的扫榜数据(不从网络抓取),
    仅当缓存可用时返回;无缓存则注明。
    """
    name = "read_scan_cache"
    args: dict = {}
    try:
        results, meta = scan_all_cached(
            platforms=["qidian", "fanqie"],
            force_refresh=False,
            data_root=data_root,
        )
        if meta.get("cached"):
            cache_date = meta.get("cache_date", "未知")
            lines: list[str] = [f"扫榜缓存日期: {cache_date}"]
            for platform, pr in results.items():
                lines.append(f"\n--- {platform} ---")
                if pr.success:
                    for b in pr.books[:5]:  # 每平台最多 5 本
                        lines.append(f"  #{b.rank} {b.title}({b.author}) [{b.category}]")
                else:
                    lines.append(f"  (平台不可用:{pr.error})")
            result = "\n".join(lines)
        else:
            result = "(暂无扫榜缓存)"
    except Exception as e:
        logger.warning("扫榜缓存读取失败:%s", e)
        result = f"(读取失败:{e})"
    return {"name": name, "args": args, "result": result, "cost": 0.0}


# ---------------------------------------------------------------------------
# R2 read_chapter(D-96 L2 点读)
# ---------------------------------------------------------------------------


def _tool_read_chapter(book_dir: Path, n: int) -> dict:
    """读单章正文,≤4000 字截断(D-96 L2 点读)。

    文件路径: <book>/chapters/ch{n}.md
    """
    name = "read_chapter"
    args = {"chapter": n}
    try:
        chapter_path = book_dir / "chapters" / f"ch{n}.md"
        if not chapter_path.exists():
            result = f"(第 {n} 章正文不存在)"
        else:
            content = chapter_path.read_text(encoding="utf-8")
            if len(content) > _CHAPTER_MAX_CHARS:
                result = content[:_CHAPTER_MAX_CHARS] + "\n\n[已截断]"
            else:
                result = content
    except Exception as e:
        logger.warning("章节读取失败(ch%d):%s", n, e)
        result = f"(读取失败:{e})"
    return {"name": name, "args": args, "result": result, "cost": 0.0}


def _tool_read_chapters(book_dir: Path, nums: list[int]) -> list[dict]:
    """多章点读,D-96 ≤3 章上限;超限只取前 3 + 采样声明。

    返回:list[dict],每章一个工具结果;超限时末尾追加采样声明条目。
    """
    results: list[dict] = []
    capped = nums[:_MAX_CHAPTERS_PER_TURN]
    overflow = len(nums) - len(capped)

    for n in capped:
        results.append(_tool_read_chapter(book_dir, n))

    if overflow > 0:
        results.append({
            "name": "read_chapter_sample_notice",
            "args": {"requested": len(nums), "returned": len(capped)},
            "result": (
                f"[D-96 采样声明] 已采样前 {len(capped)} 章正文,"
                f"另有 {overflow} 章未读。如需更多请明示(每轮 ≤3 章)。"
            ),
            "cost": 0.0,
        })
    return results


# 中文数字映射(用于 _parse_chapter_numbers)
_CN_NUMS = {
    "零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
    "十一": 11, "十二": 12, "十三": 13, "十四": 14, "十五": 15,
    "十六": 16, "十七": 17, "十八": 18, "十九": 19, "二十": 20,
    "二十一": 21, "二十二": 22, "二十三": 23, "二十四": 24, "二十五": 25,
    "二十六": 26, "二十七": 27, "二十八": 28, "二十九": 29, "三十": 30,
}


def _parse_chapter_numbers(message: str) -> list[int]:
    """从消息解析章号(支持阿拉伯数字与中文数字)。

    匹配 "第 3 章"、"第三章"、"第3章" 等形式。
    无匹配 → 空列表(调用方默认最新章)。
    """
    nums: list[int] = []
    seen: set[int] = set()

    # 阿拉伯数字:第 N 章(N 可前后含空格)
    for m in re.finditer(r"第\s*(\d+)\s*章", message):
        n = int(m.group(1))
        if n not in seen:
            seen.add(n)
            nums.append(n)

    # 中文数字:第X章(X ∈ _CN_NUMS keys)
    for m in re.finditer(r"第([\u4e00-\u9fff]+)章", message):
        cn = m.group(1)
        if cn in _CN_NUMS:
            n = _CN_NUMS[cn]
            if n not in seen:
                seen.add(n)
                nums.append(n)

    return nums


# ---------------------------------------------------------------------------
# T4 导演会诊工具集
# ---------------------------------------------------------------------------


def run_director_tools(book_dir: Path, message: str) -> list[dict]:
    """T4 导演会诊:运行 truth_files + craft + 细纲历史。

    输入 = 作者剧情想法 + 特殊要求(透在 message 中)。
    无细纲时自动降级(truth_files + craft),结果中注明。

    每个工具结果 dict:
        - name, args, result, cost
    """
    results: list[dict] = []

    # R2(D-96 L2):消息含章号 → 触发 read_chapter
    chapter_nums = _parse_chapter_numbers(message)
    if chapter_nums:
        results.extend(_tool_read_chapters(book_dir, chapter_nums))

    # 始终跑 truth_files + craft
    results.append(_tool_truth_files(book_dir))
    results.append(_tool_craft())

    # 细纲历史(有则追加,无则注降级)
    outline_result = _tool_outline_history(book_dir)
    results.append(outline_result)

    return results


def _tool_outline_history(book_dir: Path) -> dict:
    """读取细纲目录,返回已有细纲摘要。

    文件路径模式: <book>/outlines/ch{N}.md
    无细纲时降级说明。
    """
    name = "read_outlines"
    args: dict = {}
    try:
        outlines_dir = book_dir / "outlines"
        if not outlines_dir.exists():
            return {
                "name": name,
                "args": args,
                "result": "(本书暂无细纲;当前仅基于 truth_files + craft 给出参考)",
                "cost": 0.0,
            }
        ch_files = sorted(
            [f for f in outlines_dir.iterdir()
             if f.suffix == ".md" and f.stem.startswith("ch")],
            key=lambda f: int(f.stem[2:]) if f.stem[2:].isdigit() else 0,
        )
        if not ch_files:
            return {
                "name": name,
                "args": args,
                "result": "(本书暂无细纲;当前仅基于 truth_files + craft 给出参考)",
                "cost": 0.0,
            }
        lines: list[str] = [f"细纲数: {len(ch_files)}"]
        for cf in ch_files[-5:]:  # 最多 5 份
            content = cf.read_text(encoding="utf-8")
            # 取标题行 + 前 200 字摘要
            title_line = content.split("\n")[0] if content else cf.stem
            preview = content[:200].replace("\n", " ")
            lines.append(f"  {cf.name}: {title_line}")
            lines.append(f"    → {preview}...")
        result = "\n".join(lines)
    except Exception as e:
        logger.warning("细纲读取失败:%s", e)
        result = f"(读取失败:{e})"
    return {"name": name, "args": args, "result": result, "cost": 0.0}


# ---------------------------------------------------------------------------
# 消息解析工具
# ---------------------------------------------------------------------------


def _extract_name(message: str) -> str:
    """从消息中提取可能的角色名。

    先用"角色"/"人物"后面的第一个词;不行则返回消息前 10 字。
    """
    for sep in ("角色", "人物", "角色名"):
        if sep in message:
            after = message.split(sep, 1)[1].strip()
            if after:
                # 取第一个词(忽略标点、"的"、"是"等连接词)
                for ch in ("的", "是", ":", "：", "，", ",", "?", "？", "。"):
                    after = after.replace(ch, " ")
                parts = after.split()
                if parts and parts[0].strip():
                    return parts[0].strip()
    # fallback: 取消息前 10 字
    return message[:10].strip() or "未指定"


def _extract_keyword(message: str) -> str:
    """从消息中提取可能的设定关键词。

    类似 _extract_name 逻辑,但目标词是"设定"/"世界观"/"背景"。
    """
    for sep in ("设定", "世界观", "背景", "力量体系"):
        if sep in message:
            after = message.split(sep, 1)[1].strip()
            if after:
                for ch in ("的", "是", ":", "：", "，", ",", "?", "？", "。"):
                    after = after.replace(ch, " ")
                parts = after.split()
                if parts and parts[0].strip():
                    return parts[0].strip()
    return message[:10].strip() or "未指定"
