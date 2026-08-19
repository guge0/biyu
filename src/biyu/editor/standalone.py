"""P8-M2 T3 · Editor standalone 问题卡渲染 + 失败模式汇总 + 编排。

供 CLI 薄封装 / Web 端点 / 测试共用。

设计:
- 渲染产物是 Markdown,直接落盘或回吐 Web 端点;
- 渲染分层:头部元数据 → 摘要 → 失败模式(若有) → 问题卡逐条 → 元数据尾;
- 每条 issue 三件套(出处/因由/改法)用 blockquote 引,与 spec 验收口径对齐;
- 超长 quote/explanation/改法 截断(防一份 issue 占整页);
- 编排(`run_standalone_review`)只做:加载章文 + 调 `review_chapter` + 渲染;
  adapter 由调用方注入,适配器构造 / 写文件 / asyncio.run 都不在这里。
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

from .editor import review_chapter
from .parser import EditorResult

logger = logging.getLogger(__name__)


_FAILURE_RE = re.compile(r"^failure:(\w+)$")
_QUOTE_MAX = 200     # quote 显示截断
_TEXT_MAX = 600      # explanation / fix_suggestion 显示截断


def summarize_failure_modes(result: EditorResult) -> dict[str, int]:
    """从 parse_errors 中提取 failure:XXX 计数。

    editor.py `_make_failure_result()` 把失败标记写成
    `parse_errors=["failure:BAD_ARGUMENTS"]`,这里反解出来按桶计数。
    其他非 `failure:` 前缀的诊断(幻觉过滤、JSON 解析失败等)不计入失败模式。
    """
    counts: dict[str, int] = {}
    for err in result.parse_errors:
        m = _FAILURE_RE.match(err.strip())
        if m:
            key = m.group(1)
            counts[key] = counts.get(key, 0) + 1
    return counts


def summarize_issues(result: EditorResult) -> dict[str, object]:
    """按 type / severity 汇总 issues。"""
    by_type: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    for issue in result.issues:
        by_type[issue.type] = by_type.get(issue.type, 0) + 1
        sev = issue.severity or "medium"
        by_severity[sev] = by_severity.get(sev, 0) + 1
    return {
        "total": len(result.issues),
        "by_type": by_type,
        "by_severity": by_severity,
    }


def _truncate(text: str, limit: int = _QUOTE_MAX) -> str:
    """超长文本截断 + 省略号;None / 空串安全返回空串。"""
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def render_issues_markdown(
    result: EditorResult,
    chapter_num: int,
    *,
    chapter_words: int | None = None,
    generated_at: datetime | None = None,
) -> str:
    """渲染 EditorResult 为问题卡 Markdown。

    Args:
        result: Editor 审稿结果。
        chapter_num: 章节号(用于报告头)。
        chapter_words: 章节字数(可选,Web 端拼上时显示)。
        generated_at: 生成时间(测试注入;默认 now())。

    Returns:
        Markdown 字符串。
    """
    ts = (generated_at or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
    summary = summarize_issues(result)
    failure_modes = summarize_failure_modes(result)
    cost_str = f"¥{result.cost:.4f}" if result.cost > 0 else "¥0"

    lines: list[str] = []
    lines.append(f"# 第{chapter_num}章 审读报告 · standalone")
    lines.append("")
    lines.append(f"> 生成时间: {ts}")
    if chapter_words is not None:
        lines.append(f"> 章节字数: {chapter_words}")
    lines.append(f"> Issue 数: {summary['total']}")
    lines.append(f"> 信心: {result.confidence}")
    lines.append(f"> 成本: {cost_str}")
    lines.append("")

    # 摘要
    lines.append("## 摘要")
    lines.append("")
    lines.append("按类型:")
    if summary["by_type"]:
        for t, n in sorted(summary["by_type"].items(), key=lambda kv: -kv[1]):
            lines.append(f"- {t}: {n}")
    else:
        lines.append("- (无)")
    lines.append("")
    lines.append("按严重度:")
    if summary["by_severity"]:
        for s, n in sorted(summary["by_severity"].items(), key=lambda kv: -kv[1]):
            lines.append(f"- {s}: {n}")
    else:
        lines.append("- (无)")
    lines.append("")

    # 失败模式(若有)
    if failure_modes:
        lines.append("## 失败模式")
        lines.append("")
        for mode, n in sorted(failure_modes.items()):
            lines.append(f"- {mode}: {n}")
        lines.append("")

    # 问题卡
    lines.append("## 问题卡")
    lines.append("")
    if not result.issues:
        lines.append("(无 issue)")
        lines.append("")
    else:
        for idx, issue in enumerate(result.issues, start=1):
            lines.append(
                f"### #{idx} [{issue.severity}] {issue.type} @ line {issue.line}"
            )
            lines.append("")
            lines.append(f"**出处**(line {issue.line}):")
            lines.append(f"> {_truncate(issue.quote)}")
            lines.append("")
            lines.append("**因由**:")
            lines.append(f"> {_truncate(issue.explanation, _TEXT_MAX)}")
            lines.append("")
            lines.append("**改法**:")
            lines.append(f"> {_truncate(issue.fix_suggestion, _TEXT_MAX)}")
            lines.append("")
            auto_yn = "是" if issue.auto_fixable else "否"
            lines.append(f"**可自动修复**: {auto_yn}")
            lines.append("")
            lines.append("---")
            lines.append("")

    # 元数据尾
    lines.append("## 元数据")
    lines.append("")
    lines.append(f"- queries_used 次数: {len(result.queries_used)}")
    for q in result.queries_used:
        lines.append(f"  - `{q}`")
    lines.append(f"- parse_errors 数: {len(result.parse_errors)}")
    for e in result.parse_errors[:10]:  # 防爆,只显示前 10 条
        lines.append(f"  - {e}")
    if len(result.parse_errors) > 10:
        lines.append(f"  - ...(共 {len(result.parse_errors)} 条,只显示前 10)")
    lines.append(f"- raw_response 长度: {len(result.raw_response)}")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 编排:加载章文 + 调 review_chapter + 渲染
# ---------------------------------------------------------------------------

async def run_standalone_review(
    book_dir: Path,
    chapter_num: int,
    adapter,
    *,
    prev_chapter_tail: str = "",
    max_tool_rounds: int = 5,
) -> tuple[EditorResult, str]:
    """加载指定章,调 Editor review_chapter,渲染问题卡 Markdown。

    适配器由调用方注入(CLI 用 ModelRegistry,测试用 StubAdapter)。
    不写文件、不 asyncio.run — 这些是 CLI 层职责。

    D-70 兜底出声:truth_files 缺失时 log WARNING(B-2 证实 Editor 可降级
    跑单章审查,但 UI/日志要明确告知跨章维置灰)。

    Args:
        book_dir: 书目录(须含 chapters/ch{N}.md)。
        chapter_num: 章节号。
        adapter: LLM 适配器实例。
        prev_chapter_tail: 上一章末尾文本(可选,跨章衔接用)。
        max_tool_rounds: Editor 最大工具调用轮数。

    Returns:
        (EditorResult, Markdown 字符串)。

    Raises:
        FileNotFoundError: 章节文件不存在(不静默、不猜)。
    """
    ch_path = book_dir / "chapters" / f"ch{chapter_num}.md"
    if not ch_path.exists():
        raise FileNotFoundError(f"未找到章节文件: {ch_path}")

    chapter_text = ch_path.read_text(encoding="utf-8")

    # truth_files 检测:B-2 证实 Editor 在无 truth_files 时仍可降级跑章内审查
    # 但跨章维(人物一致 / 跨章衔接)会置灰,必须明确告知(D-70 出声)
    truth_files_dir = book_dir / "truth_files"
    if not (truth_files_dir / "current_state.md").exists():
        logger.warning(
            "truth_files/current_state.md 不存在 — Editor 降级为单章审查,"
            "跨章维(人物一致/跨章衔接)置灰。建议先 biyu refresh 建立记忆。"
            " (book_dir=%s)", book_dir,
        )

    result = await review_chapter(
        chapter_num=chapter_num,
        chapter_text=chapter_text,
        book_dir=book_dir,
        adapter=adapter,
        prev_chapter_tail=prev_chapter_tail,
        max_tool_rounds=max_tool_rounds,
    )

    chapter_words = sum(1 for c in chapter_text if "\u4e00" <= c <= "\u9fff")
    md = render_issues_markdown(result, chapter_num, chapter_words=chapter_words)
    return result, md
