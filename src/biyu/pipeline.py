"""主管线: Architect(R1) → Writer(V4) → WordGuard → postproc → Editor → Auditor"""
from __future__ import annotations

import asyncio
import csv
import json
import re
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Coroutine

from biyu.auditor import run_audit, save_audit_report
from biyu.auditor.base import AuditResult, Severity
from biyu.anchor_check import run_check_text
from biyu.truth_inject import build_truth_injection_block
from biyu.config import BookConfig, get_project_root, get_registry, load_characters_yaml
from biyu.context_retriever import get_retriever
from biyu.db import init_db, record_chapter, sync_characters_from_yaml
from biyu.llm.base import GenerationError
from biyu.polish import PolishResult, polish_chapter
from biyu.prompts.v3_opening import build_planning_prompt, build_writer_user_prompt
from biyu.truth_files import read_all_truth_files, read_truth_file
from biyu.wordguard import WordGuardResult, count_cjk_chars, enforce_floor
from biyu.worldbook import load_worldbook, build_worldbook_prompt
from biyu.fingerprint.library import load_merged_voiceprint
from biyu.llm import LLMResponse


_Q1_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "look_up_character",
            "description": "按姓名或别名查询一张完整人物卡",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "姓名或别名"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "look_up_worldbook",
            "description": "按关键词查询完整世界观条目",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "设定关键词"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "look_up_history",
            "description": "按章号或关键词查询完整历史正文",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "章号或关键词"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "look_up_truth",
            "description": "按关键词查询完整 truth file",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "状态或伏笔关键词"}},
                "required": ["query"],
            },
        },
    },
]


def _response_tool_calls(response) -> list[dict]:
    """Read OpenAI-compatible function calls without inventing adapter fields."""
    raw = response.raw if isinstance(response.raw, dict) else {}
    choices = raw.get("choices") or []
    if not choices or not isinstance(choices[0], dict):
        return []
    message = choices[0].get("message") or {}
    calls = message.get("tool_calls") or []
    return calls if isinstance(calls, list) else []


class _ToolAwareAdapter:
    """Keep Architect's guarded ladder while accepting empty tool-call turns."""

    supports_tools = True

    def __init__(self, adapter, responses: list):
        self._adapter = adapter
        self._responses = responses
        self.max_tokens = adapter.max_tokens

    async def generate(self, messages, **kwargs):
        response = await self._adapter.generate(messages, **kwargs)
        self._responses.append(response)
        return response

    async def generate_guarded(self, messages, **kwargs):
        from biyu.llm.base import LLMAdapter

        return await LLMAdapter.generate_guarded(self, messages, **kwargs)

    @staticmethod
    def detect_failure(response) -> str | None:
        if _response_tool_calls(response):
            return None
        if not response.text or not response.text.strip():
            return "empty"
        if response.finish_reason == "length":
            return "truncated"
        return None


def _adapter_supports_tools(adapter) -> bool:
    if getattr(adapter, "supports_tools", False):
        return True
    return adapter.__class__.__module__ in {"biyu.llm.deepseek", "biyu.llm.glm"}


def _catalog_without_lines(catalog: str, excluded: set[str]) -> str:
    """Filter static catalog lines without changing the catalog generator."""
    return "\n".join(
        line for line in catalog.splitlines()
        if not any(name and name in line for name in excluded)
    )


def _q1_worldbook_prompt(wb: dict | None) -> str:
    """Render only the signed Q-1 preload fields; power_system is excluded."""
    if not wb:
        return ""
    import yaml

    parts: list[str] = []
    for key, title in (
        ("narrative_anchors", "创作锚点"),
        ("facts", "不可变硬设定"),
        ("forbidden", "绝对禁止"),
    ):
        value = wb.get(key)
        if value:
            rendered = yaml.safe_dump(value, allow_unicode=True, sort_keys=False).strip()
            parts.append(f"【{title}】\n{rendered}")
    return "\n\n".join(parts)


def _q1_history_catalog(book_dir: Path, chapter_num: int) -> str:
    lines = ["以下只是清单,要用再查,不必全查"]
    for number in range(1, chapter_num):
        if (book_dir / "chapters" / f"ch{number}.md").exists():
            lines.append(f"- 第 {number} 章 · 要用再查,不必全查")
    return "\n".join(lines)


def _q1_editor_inputs(book_dir: Path, wb: dict | None, chapter_num: int):
    """Build Editor v2 preload/catalog and its common telemetry sink."""
    from biyu.injection_tools import (
        build_character_catalog,
        build_history_catalog,
        build_worldbook_catalog,
        editor_observation_sink,
    )

    import yaml

    anchors = (wb or {}).get("narrative_anchors")
    creative_anchor = (
        yaml.safe_dump(anchors, allow_unicode=True, sort_keys=False).strip()
        if anchors else ""
    )
    lookup_catalog = "\n\n".join((
        "# 人物目录\n" + build_character_catalog(book_dir),
        "# 世界观目录\n" + build_worldbook_catalog(
            book_dir, exclude_fields={"narrative_anchors"}
        ),
        "# 历史目录\n" + build_history_catalog(book_dir),
    ))
    return creative_anchor, lookup_catalog, editor_observation_sink(
        book_dir, chapter=chapter_num
    )


async def _run_q1_tool_loop(
    *, adapter, fallback_adapter, messages: list[dict], book_dir: Path,
    chapter_num: int, role: str, guarded: bool, generate_kwargs: dict,
):
    """Run Q-1 lookups; Writer has five lookup rounds plus one tool-free final."""
    from biyu.call_evidence import record_call_evidence
    from biyu.injection_tools import (
        append_tool_call, query_character, query_history, query_truth, query_worldbook,
    )

    if not _adapter_supports_tools(adapter):
        error = RuntimeError(
            f"{role} 的当前适配器 {adapter.__class__.__name__} 不支持 tools；"
            "injection_v2 已停止，未静默降级。"
        )
        error.q1_cost = 0.0
        error.q1_cost_logged = False
        raise error
    responses: list = []
    primary = _ToolAwareAdapter(adapter, responses)
    fallback = None
    if fallback_adapter is not None:
        if not _adapter_supports_tools(fallback_adapter):
            error = RuntimeError(
                f"{role} 的降级适配器 {fallback_adapter.__class__.__name__} 不支持 tools。"
            )
            error.q1_cost = 0.0
            error.q1_cost_logged = False
            raise error
        fallback = _ToolAwareAdapter(fallback_adapter, responses)
    round_num = 0
    any_degraded = False

    def _billed_failure(message: str, *, status: str, cause: Exception | None = None):
        spent = sum(item.cost for item in responses)
        if spent:
            _log_cost(
                BookConfig(book_dir), chapter_num, role, spent, 0.0, status=status
            )
        error = RuntimeError(message)
        error.q1_cost = spent
        error.q1_cost_logged = bool(spent)
        if cause is not None:
            raise error from cause
        raise error

    writer_max_lookup_rounds = 5
    while True:
        round_num += 1
        final_round = role == "writer" and round_num == writer_max_lookup_rounds + 1
        if final_round:
            messages.append({
                "role": "user",
                "content": (
                    "【系统提示·最后一轮】这是最后一轮，不再允许查询工具。"
                    "请立即输出完整章节正文，只输出正文，不要解释或附加元信息。"
                ),
            })
        response_start = len(responses)
        try:
            if guarded:
                from biyu.llm.base import LLMAdapter

                response = await LLMAdapter.generate_guarded(
                    primary,
                    messages, fallback_adapter=fallback, tools=_Q1_TOOL_DEFINITIONS,
                    tool_choice="auto", **generate_kwargs,
                )
            elif final_round:
                response = await primary.generate(messages, **generate_kwargs)
            else:
                response = await _call_with_retry(
                    primary, messages, tools=_Q1_TOOL_DEFINITIONS,
                    tool_choice="auto", **generate_kwargs,
                )
        except Exception as exc:
            for recorded in responses[response_start:]:
                record_call_evidence(
                    role=role, chapter_num=chapter_num, round_num=round_num,
                    messages=messages, response=recorded, final_round=final_round,
                )
            _billed_failure(
                f"{role} 工具轮模型调用失败；已发生费用已记账。",
                status="error",
                cause=exc,
            )
        for recorded in responses[response_start:]:
            record_call_evidence(
                role=role, chapter_num=chapter_num, round_num=round_num,
                messages=messages, response=recorded, final_round=final_round,
            )
        any_degraded = any_degraded or response.degraded
        tool_calls = _response_tool_calls(response)
        if final_round and (tool_calls or not response.text or not response.text.strip()):
            _billed_failure(
                f"{role} 收尾轮返回了空内容或工具调用，已停止且不执行工具。",
                status="empty",
            )
        if sum(item.cost for item in responses) > 0.60:
            _billed_failure(
                f"{role} 本章费用已超过 ¥0.60，工具轮已停止。",
                status="cost_stop",
            )
        if not tool_calls:
            if not response.text or not response.text.strip():
                _billed_failure(
                    f"{role} 返回了空内容，已停止且不落盘。", status="empty"
                )
            if response.finish_reason == "length":
                _billed_failure(
                    f"{role} 输出被截断，已停止且不落盘。", status="truncated"
                )
            break
        messages.append({"role": "assistant", "content": response.text or "", "tool_calls": tool_calls})
        group = f"{role}:{round_num}"
        lookup = {
            "look_up_character": ("character", query_character),
            "look_up_worldbook": ("worldbook", query_worldbook),
            "look_up_history": ("history", query_history),
            "look_up_truth": ("truth_files", query_truth),
        }
        for call in tool_calls:
            function = call.get("function") or {}
            name = str(function.get("name") or "")
            try:
                arguments = json.loads(function.get("arguments") or "{}")
            except json.JSONDecodeError as exc:
                _billed_failure(
                    f"{role} 工具参数不是合法 JSON: {name}", status="error", cause=exc
                )
            query = str(arguments.get("query") or "")
            if name not in lookup:
                _billed_failure(
                    f"{role} 请求了未允许的工具: {name}", status="error"
                )
            item, function_call = lookup[name]
            result = function_call(book_dir, query)
            append_tool_call(
                book_dir, role=role, chapter=chapter_num, item=item, query=query,
                result=result, tokens=response.total_tokens, cost=response.cost,
                response_group=group, usage_scope="triggering_response_shared",
                response_tool_call_count=len(tool_calls),
                prompt_tokens=response.prompt_tokens,
                completion_tokens=response.completion_tokens,
                total_tokens=response.total_tokens,
            )
            messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": result.content})

    # Preserve downstream accounting while charging every response exactly once.
    response.cost = sum(item.cost for item in responses)
    response.prompt_tokens = sum(item.prompt_tokens for item in responses)
    response.completion_tokens = sum(item.completion_tokens for item in responses)
    response.total_tokens = sum(item.total_tokens for item in responses)
    response.degraded = any_degraded
    return response


def _read_planning_status(planning_path: Path) -> tuple[str | None, str | None]:
    """读取规划件并返回 (status, content).

    检查 planning.md 首部是否含 status 字段,返回 status 值(小写)和全文内容.
    如果文件不存在或无 status 字段,返回 (None, content) 或 (None, None).

    Args:
        planning_path: 规划件路径

    Returns:
        (status, content) 元组,status 为 "已批"/"未批"/None
    """
    if not planning_path.exists():
        return None, None

    try:
        content = planning_path.read_text(encoding="utf-8")
        # 检查前 10 行是否有 status 字段
        for line in content.split("\n")[:10]:
            if line.strip().startswith("status:"):
                status_value = line.split(":", 1)[1].strip().lower()
                return status_value, content
        return None, content
    except Exception as e:
        print(f"  读取规划件失败: {e}")
        return None, None


@dataclass
class ChapterResult:
    chapter_num: int
    final_text: str
    word_count: int          # CJK 字数
    cost_cny: float
    latency_seconds: float
    stage_latencies: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)
    planning_text: str = ""
    skeleton_text: str = ""
    polished_text: str = ""
    audit_warnings: list = field(default_factory=list)


async def _call_with_retry(adapter, messages: list[dict], max_retries: int = 2, **kwargs):
    """Call adapter.generate with retry."""
    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            return await adapter.generate(messages, **kwargs)
        except Exception as e:
            last_err = e
            if attempt < max_retries:
                await asyncio.sleep(5.0)
    raise last_err


def _log_cost(
    book: BookConfig,
    chapter_num: int,
    stage: str,
    cost_cny: float,
    latency_s: float,
    status: str = "ok",
) -> None:
    """Append a cost row to the book's cost_log.csv.

    status: ok / empty / truncated / degraded。旧 5 列文件首次写入时升级表头为 6 列;
    读取方缺 status 时视为 ok(DictReader 按列名取)。
    """
    book.logs_dir.mkdir(parents=True, exist_ok=True)
    cost_path = book.cost_log_path
    is_new = not cost_path.exists()
    if not is_new:
        with open(cost_path, encoding="utf-8") as f:
            first_line = f.readline().strip()
        if first_line == "timestamp,chapter,stage,cost_cny,latency_s":
            with open(cost_path, encoding="utf-8") as f:
                lines = f.readlines()
            with open(cost_path, "w", encoding="utf-8", newline="") as f:
                f.write("timestamp,chapter,stage,cost_cny,latency_s,status\n")
                f.writelines(lines[1:])
    with open(cost_path, "a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(["timestamp", "chapter", "stage", "cost_cny", "latency_s", "status"])
        writer.writerow([
            datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            chapter_num,
            stage,
            f"{cost_cny:.4f}",
            f"{latency_s:.1f}",
            status,
        ])


async def _run_checklist_with_cost_log(
    *,
    book: BookConfig,
    book_dir: Path,
    chapter_num: int,
    planning_text: str,
    chapter_text: str,
    adapter,
):
    """Run the existing F4 mount and append its successful cost to cost_log.csv."""
    from biyu.checklist import run_and_save_checklist

    started = time.time()
    tracked_costs: list[float] = []

    class _ChecklistCostAdapter:
        def __init__(self, wrapped):
            self._wrapped = wrapped

        def __getattr__(self, name):
            return getattr(self._wrapped, name)

        async def generate(self, messages, **kwargs):
            response = await self._wrapped.generate(messages, **kwargs)
            tracked_costs.append(float(response.cost))
            return response

    tracking_adapter = _ChecklistCostAdapter(adapter)
    result, warnings = await run_and_save_checklist(
        book_dir=book_dir,
        chapter_num=chapter_num,
        planning_text=planning_text,
        chapter_text=chapter_text,
        adapter=tracking_adapter,
        engine_version="f4",
    )
    if tracked_costs or result is not None:
        cost = sum(tracked_costs) if tracked_costs else float(result.cost_cny)
        status = "ok" if result is not None else ("empty" if any("空" in str(w) for w in warnings) else "error")
        _log_cost(
            book,
            chapter_num,
            "checklist_f4",
            cost,
            time.time() - started,
            status=status,
        )
    return result, warnings


def _write_long_run_csv(
    book_dir: Path,
    chapter_num: int,
    model: str,
    planning_resp,
    writer_resp,
    total_cost: float,
    audit_results: list,
    dash_result,
    final_count: int,
    context_block: str,
    final_text: str,
) -> None:
    """Append a row to the book's long_run_metrics.csv (Phase 4 轻量统计)."""
    csv_path = book_dir / "logs" / "long_run_metrics.csv"
    if not csv_path.exists():
        return

    # Token accumulation
    input_tokens = planning_resp.prompt_tokens + writer_resp.prompt_tokens
    output_tokens = planning_resp.completion_tokens + writer_resp.completion_tokens

    # Cache data (DeepSeek prompt caching)
    cached_tokens = 0
    cache_hit_ratio = 0.0
    raw_usage = (writer_resp.raw or {}).get("usage", {})
    if "prompt_cache_hit_tokens" in raw_usage:
        cached_tokens = raw_usage["prompt_cache_hit_tokens"]
        cache_hit_ratio = cached_tokens / input_tokens if input_tokens > 0 else 0.0

    # Auditor results: map checker name → severity string
    audit_map: dict[str, str] = {}
    for ar in audit_results:
        audit_map[ar.checker] = (
            ar.severity.value if isinstance(ar.severity, Severity) else str(ar.severity)
        )

    # Dash fixer
    dash_count = dash_result.original_count if dash_result else 0
    dash_density = dash_count / (final_count / 1000) if final_count > 0 else 0.0

    # Dialogue ratio (CJK quotation marks)
    dialogue_chars = sum(1 for c in final_text if c in "\u300c\u300d\u300e\u300f\u201c\u201d")
    dialogue_ratio = dialogue_chars / len(final_text) if final_text else 0.0

    # Context block info
    ctx_chars = len(context_block) if context_block else 0
    ctx_chapters = context_block.count("=== \u7b2c") if context_block else 0  # === 第

    # Truth files
    truth_data = read_all_truth_files(book_dir)
    truth_lines = sum(len(v.split("\n")) for v in truth_data.values())
    pending_hooks = sum(
        1 for v in truth_data.values()
        for line in v.split("\n")
        if "pending" in line.lower() or "\u4f0f\u7b14" in line  # 伏笔
    )

    row = [
        chapter_num,
        datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        model,
        input_tokens,
        cached_tokens,
        f"{cache_hit_ratio:.3f}",
        output_tokens,
        f"{total_cost:.4f}",
        audit_map.get("dedup", ""),
        audit_map.get("worldbook_check", ""),
        audit_map.get("character_presence", ""),
        audit_map.get("transition", ""),
        audit_map.get("style_repeat", ""),
        audit_map.get("punctuation_density", ""),
        audit_map.get("meta_vocab", ""),
        audit_map.get("chapter_ending", ""),
        audit_map.get("dialogue_ratio", ""),
        audit_map.get("character_naming", ""),
        dash_count,
        f"{dash_density:.2f}",
        final_count,
        f"{dialogue_ratio:.3f}",
        ctx_chars,
        ctx_chapters,
        truth_lines,
        pending_hooks,
    ]

    with open(csv_path, "a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(row)

    print(f"  [long_run_csv] \u5df2\u5199\u5165\u7b2c {chapter_num} \u7ae0\u6307\u6807")


def _build_context_block(
    book_dir: Path, chapter_num: int, context_mode: str = "long_context",
) -> str:
    """构造历史 context 块: 真相文件 + 历史章节。"""
    parts: list[str] = []

    # 1. 真相文件(设定锁,最重要)
    truth_data = read_all_truth_files(book_dir)
    for name, content in truth_data.items():
        if content.strip():
            parts.append(f"=== {name} ===\n{content}")

    # 2. 历史章节(通过 retriever 获取)
    retriever = get_retriever(book_dir, context_mode)
    history = retriever.retrieve(chapter_num)
    for i, ch_text in enumerate(history, start=1):
        parts.append(f"=== 第{i}章 ===\n{ch_text}")

    return "\n\n".join(parts), retriever


def _extract_info_boundary(outline: str) -> str:
    """从大纲中提取'信息边界'段落(如果有)。

    大纲格式:
    ## 信息边界（可选）
    本章可揭示：
    - ...
    本章不可揭示：
    - ...
    """
    # 查找 "信息边界" 段落
    marker = "信息边界"
    idx = outline.find(marker)
    if idx == -1:
        return ""

    # 从标记位置开始,截取到下一个 ## 标题或文件末尾
    start = idx
    # 找到包含标记的那一行的开头
    while start > 0 and outline[start - 1] != "\n":
        start -= 1

    rest = outline[start:]
    # 找到下一个 ## 标题
    import re as _re
    next_heading = _re.search(r"\n##\s+", rest[1:])  # skip first char to avoid matching current
    if next_heading:
        return rest[:next_heading.start() + 1].strip()
    return rest.strip()


def _load_prev_chapter_tail(book_dir: Path, chapter_num: int) -> str:
    """从 ch{N-1}.md 取末尾 500 字（按字符算），用于衔接锚点。

    ch1 不注入。文件不存在不报错，跳过。
    """
    if chapter_num <= 1:
        return ""
    prev_path = book_dir / "chapters" / f"ch{chapter_num - 1}.md"
    if not prev_path.exists():
        return ""
    prev_text = prev_path.read_text(encoding="utf-8")
    return prev_text[-500:] if len(prev_text) > 500 else prev_text


def _detect_secret_realm(outline: str) -> bool:
    """启发式检测大纲是否涉及秘境内场景。

    简单实现:检查大纲中是否包含常见秘境关键词。
    """
    keywords = ["秘境", "白色空间", "异能兽", "铠甲勇士", "曹操", "关羽", "赤壁"]
    lower_outline = outline.lower()
    return any(kw in lower_outline for kw in keywords)


def _parse_present_characters(
    outline: str, book_dir: Path, *, allow_truth_fallback: bool = True,
) -> list[str]:
    """从大纲 yaml frontmatter 解析 present_characters 字段。

    解析失败或字段缺失时，用 truth_files/current_state.md 里的"当前在场"兜底。
    """
    # 尝试解析 yaml frontmatter
    if outline.startswith("---"):
        end = outline.find("---", 3)
        if end != -1:
            frontmatter = outline[3:end].strip()
            try:
                import yaml
                fm = yaml.safe_load(frontmatter)
                if isinstance(fm, dict) and "present_characters" in fm:
                    chars = fm["present_characters"]
                    if isinstance(chars, list):
                        return [str(c) for c in chars]
            except Exception:
                pass

    if not allow_truth_fallback:
        return []

    # 兜底: 从 truth_files/current_state.md 读取"当前在场"
    truth_path = book_dir / "truth_files" / "current_state.md"
    if truth_path.exists():
        content = truth_path.read_text(encoding="utf-8")
        # 查找"在场"或"友"行
        for line in content.split("\n"):
            if "在场" in line or "友：" in line or "友:" in line:
                # 提取冒号后的内容
                parts = line.split("：", 1) if "：" in line else line.split(":", 1)
                if len(parts) > 1:
                    raw_names = [n.strip() for n in parts[1].replace("、", ",").split(",") if n.strip()]
                    if raw_names:
                        # 只取角色名: 遇到括号、破折号、句号、逗号或空格立即停止
                        cleaned = []
                        for name in raw_names:
                            clean = re.split(r'[（(——\-。，,、\s]', name)[0].strip()
                            if clean:
                                cleaned.append(clean)
                        if cleaned:
                            return cleaned
    return []


def _fix_chapter_number(text: str, chapter_num: int) -> str:
    """扫描正文首行，如果章节号与 chapter_num 不符则修正。

    无章节号则不动。
    """
    lines = text.split("\n")
    if not lines:
        return text

    first_line = lines[0]
    # 匹配 "第N章" 或 "Chapter N" 等模式
    pattern = re.compile(r"(第\s*)(\d+)(\s*章|章)")
    match = pattern.search(first_line)
    if match:
        found_num = int(match.group(2))
        if found_num != chapter_num:
            lines[0] = pattern.sub(rf"第{chapter_num}章", first_line)
            return "\n".join(lines)

    # 匹配英文 "Chapter N"
    pattern_en = re.compile(r"(Chapter\s*)(\d+)", re.IGNORECASE)
    match_en = pattern_en.search(first_line)
    if match_en:
        found_num = int(match_en.group(2))
        if found_num != chapter_num:
            lines[0] = pattern_en.sub(f"Chapter {chapter_num}", first_line)
            return "\n".join(lines)

    return text


# ---------------------------------------------------------------------------
# CutA · 早闸回流闭环(P6-A2-CutA)
# ---------------------------------------------------------------------------
# 设计(详见 specs/P6-A2-CutA.md):
# - 方案 b 事后修订: Stage 2 Writer 跑完产 skeleton_text 后才调本函数,
#   Stage 2 初始 prompt 逐字不被回流信号污染。
# - 2 轮硬上限(max_rounds=2): 2 轮后无论是否达标都放行, 只标记。
# - 隔离硬约束: 函数体只读 anchors_yaml, 绝不读/写其他章节文件。
# - 依赖注入 writer_call_fn / check_fn / _log_cost_fn, 便于零成本 mock 测试。


def _extract_unresolved(report: dict) -> list[dict]:
    """从 run_check_text 报告里抽出 missing / value_mismatch 的 atomic 条目。

    返回 [{id, type, canonical, status, mismatch_by}] 列表(供 state.unresolved
    以及组织 Writer 回流 prompt 使用)。
    """
    out = []
    for r in report.get("atomic_results", []):
        status = r.get("status")
        if status in ("missing", "value_mismatch"):
            out.append({
                "id": r["id"],
                "type": r["type"],
                "canonical": r["canonical"],
                "status": status,
                "mismatch_by": r.get("mismatch_by"),
            })
    return out


async def _run_anchor_loop(
    *,
    skeleton_text: str,
    anchors_yaml: Path,
    chapter_id: str,
    writer_call_fn,
    check_fn,
    book_dir: Path,
    chapter_num: int,
    max_rounds: int = 2,
    _log_cost_fn=None,
) -> tuple[str, dict]:
    """CutA 早闸回流闭环。详见 specs/P6-A2-CutA.md。

    Stage 2 Writer 产 skeleton_text 之后调用; 对 skeleton_text 跑 anchor 检查,
    若 miss+vm > 0, 把缺/错硬信息喂回 Writer 修订, 最多 max_rounds 轮, 仍不达标
    放行 + 在 state 里标记 unresolved(供 caller 写 meta + 报警)。

    绝不回溯改动其他章节: 函数体只读 anchors_yaml, 无章节正文文件访问。

    Args:
        skeleton_text: Stage 2 Writer 初始产物(方案 b: 初始 prompt 未被污染)
        anchors_yaml: 当前章 anchors.yaml 路径
        chapter_id: 章节标识, 如 "T1"
        writer_call_fn: async callable(messages, **kwargs) -> resp(鸭子类型:
            resp.text / resp.cost 可读)。caller 负责绑定 adapter;
            _run_anchor_loop 内部不直接接触 adapter。
        check_fn: anchor 检查入口(yaml_path, text, chapter_id) -> report。
            默认 run_check_text, 测试可注入 mock。
        book_dir: 当前书 book_dir, 用于落盘 logs/ch<N>/
        chapter_num: 章节号(用于落盘 + _log_cost)
        max_rounds: 回流硬上限, 默认 2
        _log_cost_fn: 成本日志函数(book, chapter_num, stage, cost, latency),
            DI 注入。默认 None 时跳过日志(测试用); 生产传 _log_cost。

    Returns:
        (final_skeleton_text, state) 其中 state 含:
        - triggered: bool
        - loops: [{round, missing_before, value_mismatch_before,
                   missing_after, value_mismatch_after, writer_cost}]
        - final_status: "not_triggered" | "resolved" | "unresolved"
        - unresolved: [{id, type, canonical, status, mismatch_by}]
        - total_loop_cost: float
    """
    state: dict = {
        "triggered": False,
        "loops": [],
        "final_status": "not_triggered",
        "unresolved": [],
        "total_loop_cost": 0.0,
    }

    # 落盘目录(logs/ch<N>/, 复用 BookConfig.get_log_dir_for_chapter 同结构)
    loop_log_dir = book_dir / "logs" / f"ch{chapter_num}"
    loop_log_dir.mkdir(parents=True, exist_ok=True)

    # 初始检查: 对 Stage 2 产物跑 anchor 检查(零 LLM)
    initial_report = check_fn(anchors_yaml, skeleton_text, chapter_id)
    sk0 = initial_report["stats"]["atomic"]
    miss0 = sk0["miss"]
    vm0 = sk0["value_mismatch"]

    # 不触发分支: 全 present 直接返回
    if miss0 + vm0 == 0:
        return skeleton_text, state

    # 触发分支(T2-T8): for-round 循环 + 修订 + 复查 + 标记
    state["triggered"] = True
    current_text = skeleton_text
    miss_before = miss0
    vm_before = vm0
    total_cost = 0.0
    last_report = initial_report  # 上一轮复查报告(用于 unresolved 提取)

    for round_num in range(1, max_rounds + 1):
        # 组织回流 prompt(T4 扩展防重复犯错提示)
        unresolved = _extract_unresolved(last_report)
        prompt = _build_anchor_loop_prompt(current_text, unresolved, round_num)
        messages = [{"role": "user", "content": prompt}]

        # Writer 修订调用(带 latency 测量)
        t_loop = time.time()
        resp = await writer_call_fn(messages)
        loop_latency = time.time() - t_loop
        new_text = resp.text
        cost = resp.cost
        total_cost += cost

        # 成本日志: 独立阶段名 writer_anchor_loop(便于审计回流开销)
        # _log_cost_fn 签名 (stage, cost, latency); caller 用闭包绑定 book + chapter_num
        if _log_cost_fn is not None:
            _log_cost_fn("writer_anchor_loop", cost, loop_latency)

        # 复查(零 LLM)
        loop_report = check_fn(anchors_yaml, new_text, chapter_id)
        sk = loop_report["stats"]["atomic"]
        miss_after = sk["miss"]
        vm_after = sk["value_mismatch"]

        # 通道 2a: 每轮复查报告落盘(便于追溯每轮信号)
        _write_json(
            loop_log_dir / f"anchor_loop_round_{round_num}.json",
            loop_report,
        )

        state["loops"].append({
            "round": round_num,
            "missing_before": miss_before,
            "value_mismatch_before": vm_before,
            "missing_after": miss_after,
            "value_mismatch_after": vm_after,
            "writer_cost": cost,
        })
        state["total_loop_cost"] = total_cost
        # 通道 2b: 每轮覆盖写 anchor_loop.json(磁盘始终有最新状态)
        _write_json(loop_log_dir / "anchor_loop.json", state)

        current_text = new_text
        miss_before = miss_after
        vm_before = vm_after
        last_report = loop_report

        # 达标退出
        if miss_after + vm_after == 0:
            state["final_status"] = "resolved"
            state["unresolved"] = []
            _write_json(loop_log_dir / "anchor_loop.json", state)
            print(
                f"  [anchor-loop] 第 {round_num} 轮解决 "
                f"(初始缺/错 {miss0 + vm0} → 0)"
            )
            return current_text, state

    # max_rounds 用完仍未解决 → 放行 + 标记
    state["final_status"] = "unresolved"
    state["unresolved"] = _extract_unresolved(last_report)
    _write_json(loop_log_dir / "anchor_loop.json", state)

    # 通道 3: console 报警(操作者肉眼可见)
    unresolved_count = len(state["unresolved"])
    print(
        f"  [anchor-loop] ⚠ 本章 {unresolved_count} 条硬信息 "
        f"{max_rounds} 轮未解决, 需作者人工处理"
    )
    return current_text, state


def _write_json(path: Path, data) -> None:
    """JSON 落盘辅助(ensure_ascii=False, 缩进 2)。CutA 内部用。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


async def _cut_a_apply(
    *,
    skeleton_text: str,
    anchors_yaml: Path | None,
    chapter_id: str,
    writer_adapter,
    book,  # BookConfig
    book_dir: Path,
    chapter_num: int,
    max_rounds: int = 2,
) -> tuple[str, dict]:
    """CutA 接入 generate_chapter 的辅助函数。

    职责:
    1. 绑定 writer_adapter 成 writer_call_fn(经 _call_with_retry);
    2. 绑定 book/chapter_num 成 _log_cost_fn(经 _log_cost, 阶段名 writer_anchor_loop);
    3. anchors_yaml 不存在 → 直接返回默认 state(不触发);
    4. 异常不阻塞管线: 放行原 skeleton + state.final_status="error" + console warning。

    Args 见 _run_anchor_loop;额外:
        book: BookConfig(用于 _log_cost 的 logs_dir / cost_log_path)
        writer_adapter: Writer LLM adapter(直接调,内部经 _call_with_retry)

    Returns:
        (final_skeleton_text, state) — state 字段同 _run_anchor_loop;
        异常时 state.final_status="error", state["error"] 含异常信息。
    """
    default_state: dict = {
        "triggered": False,
        "loops": [],
        "final_status": "not_triggered",
        "unresolved": [],
        "total_loop_cost": 0.0,
    }

    # 无 anchors.yaml → 不触发(管线在无 anchors.yaml 时 CutA 自动跳过)
    if anchors_yaml is None or not anchors_yaml.exists():
        return skeleton_text, default_state

    try:
        async def _loop_writer_call(messages, **kwargs):
            return await _call_with_retry(writer_adapter, messages, **kwargs)

        def _loop_log_cost(stage: str, cost: float, latency: float) -> None:
            _log_cost(book, chapter_num, stage, cost, latency)

        return await _run_anchor_loop(
            skeleton_text=skeleton_text,
            anchors_yaml=anchors_yaml,
            chapter_id=chapter_id,
            writer_call_fn=_loop_writer_call,
            check_fn=run_check_text,
            book_dir=book_dir,
            chapter_num=chapter_num,
            max_rounds=max_rounds,
            _log_cost_fn=_loop_log_cost,
        )
    except Exception as e:
        # CutA 回流异常绝不阻塞写作管线
        print(f"  [anchor-loop] 回流异常跳过(warning, 不阻塞): {e}")
        err_state = dict(default_state)
        err_state["final_status"] = "error"
        err_state["error"] = str(e)
        return skeleton_text, err_state


def _build_anchor_loop_prompt(
    skeleton_text: str,
    unresolved: list[dict],
    round_num: int,
) -> str:
    """组织 Writer 回流修订 prompt。详见 specs/P6-A2-CutA.md。

    Stage 2 初始 prompt 不污染(方案 b):本函数独立 prompt, 不引用 v3/v4
    system_prompt。第 2 轮起加"上一轮已要求"防重复犯错提示。

    Args:
        skeleton_text: 上一轮 skeleton(初始 / 上轮修订版)
        unresolved: _extract_unresolved 输出(missing + value_mismatch 条目)
        round_num: 1 起

    Returns:
        Writer 修订 prompt 字符串。
    """
    missing = [u for u in unresolved if u["status"] == "missing"]
    mismatch = [u for u in unresolved if u["status"] == "value_mismatch"]

    parts: list[str] = []
    if round_num == 1:
        parts.append("你刚才写的正文有以下硬信息问题(第 1 轮检查):\n\n")
    else:
        parts.append(
            f"你刚才写的正文仍有以下硬信息未解决(第 {round_num} 轮检查,"
            "上一轮已要求, 仍缺/错, 请重点检查):\n\n"
        )

    if missing:
        parts.append("【缺失】(必须在正文出现, 当前未提):\n")
        for m in missing:
            parts.append(f"  - {m['id']} ({m['type']}): {m['canonical']}\n")
    if mismatch:
        parts.append("【错值】(正文写错, 必须纠正):\n")
        for mm in mismatch:
            parts.append(
                f"  - {mm['id']} ({mm['type']}): 应为 \"{mm['canonical']}\","
                f" 当前含 \"{mm['mismatch_by']}\"\n"
            )

    parts.append(
        "\n请修订正文, 优先解决上述硬信息。不要新引入其他改动。"
        "只输出修订后的完整正文。\n\n=== 原正文 ===\n"
    )
    parts.append(skeleton_text)
    return "".join(parts)


# ---------------------------------------------------------------------------
# P9-C3: Editor 审稿→修稿回路
# ---------------------------------------------------------------------------

def _build_editor_revision_prompt(
    text: str,
    issues: list,
) -> str:
    """组织 Writer 修订 prompt, 根据 Editor 发现的 issue 修正正文。

    与 CutA 锚点回流同模式:事后修订, 不污染 Writer 初始 prompt。
    """
    parts = [
        "你刚才写的这一章被编辑审稿后发现了以下问题, 需要你修改:\n\n",
    ]
    for i, issue in enumerate(issues, 1):
        severity_label = {"high": "【严重】", "medium": "【中等】", "low": "【轻微】"}.get(issue.severity, "")
        parts.append(
            f"{i}. {severity_label} {issue.type}\n"
            f"   问题: {issue.explanation}\n"
            f"   建议: {issue.fix_suggestion}\n"
        )
        if issue.quoted_text:
            parts.append(f"   原文: \"{issue.quoted_text}\"\n")
        parts.append("\n")

    parts.append(
        "请按照以上每一条编辑意见逐一修改正文。"
        "只修改有问题的地方, 其他保持原样。"
        "只输出修改后的完整正文, 不做任何其他解释。\n\n"
        "=== 需要修改的正文 ===\n"
    )
    parts.append(text)
    return "".join(parts)


async def _editor_revision_loop(
    chapter_num: int,
    text: str,
    book_dir: Path,
    editor_adapter,
    writer_adapter,
    book,
    _log_cost_fn,
    *,
    prev_chapter_tail: str = "",
    planning: str = "",
    has_approved_planning: bool = False,
    max_revisions: int = 1,
    result_sink: list | None = None,
    injection_v2: bool = False,
    creative_anchor: str = "",
    lookup_catalog: str = "",
    tool_observer=None,
) -> tuple[str, str, float]:
    """Editor 审稿→修稿闭环。

    流程:
    1. Editor 审稿(首次, 已在外层完成)
    2. 提取手动 review 的 issue → 构建修订 prompt → Writer 修
    3. Editor 再审修订后的文本
    4. 两轮结果合并进 editor_section

    Args:
        text: 需要审稿的原文
        planning: 规划件全文(已批的 planning.md 内容),用于规划履约检查
        has_approved_planning: `_read_planning_status` 结果对应的确定性批准状态
    Returns:
        (最终文本, editor_section Markdown 字符串, 额外成本)
    """
    from biyu.editor.editor import review_chapter as editor_review

    extra_cost = 0.0
    editor_sections: list[str] = []

    # ---- 第 1 轮：Editor 审稿(已完成) ----
    round1_result = await editor_review(
        chapter_num=chapter_num,
        chapter_text=text,
        book_dir=book_dir,
        adapter=editor_adapter,
        prev_chapter_tail=prev_chapter_tail,
        planning=planning,
        has_approved_planning=has_approved_planning,
        injection_v2=injection_v2,
        creative_anchor=creative_anchor,
        lookup_catalog=lookup_catalog,
        tool_observer=tool_observer,
    )
    extra_cost += round1_result.cost
    _log_cost_fn(book, chapter_num, "editor_r1", round1_result.cost, 0)

    # 构建第 1 轮表格
    section_lines = [
        "### 第 1 轮审稿",
        "",
        "| # | 类型 | 严重度 | 行号 | 问题描述 | 建议 |",
        "|---|------|--------|------|----------|------|",
    ]
    if has_approved_planning:
        planning_issue_count = sum(
            issue.type == "规划履约" for issue in round1_result.issues
        )
        section_lines[0:0] = [f"规划履约:偏离 {planning_issue_count}", ""]
    else:
        section_lines[0:0] = ["规划履约:无合同,跳过", ""]
    for idx, issue in enumerate(round1_result.issues, 1):
        severity_icon = "🔴" if issue.severity == "high" else ("🟡" if issue.severity == "medium" else "🟢")
        section_lines.append(
            f"| {idx} | {issue.type} | {severity_icon} {issue.severity} | "
            f"L{issue.line} | {issue.explanation} | {issue.fix_suggestion or '-'} |"
        )
    editor_sections.append("\n".join(section_lines))

    # ---- 需要修的吗? ----
    manual_issues = [i for i in round1_result.issues if not i.auto_fixable]
    if not manual_issues:
        # 没问题或只有字面伪影(已自动修), 直接返回
        if result_sink is not None:
            result_sink.append(round1_result)
        return text, editor_sections[0], extra_cost

    # ---- 修：Writer 按 Editor 意见修改 ----
    n_manual = len(manual_issues)
    print(f"  [Editor→Writer] 发现 {n_manual} 个需人工修的问题, 回传 Writer 修订...")
    revision_prompt = _build_editor_revision_prompt(text, manual_issues)
    t0 = time.time()
    try:
        writer_resp = await writer_adapter.generate(
            messages=[{"role": "user", "content": revision_prompt}],
            temperature=0.1,  # 偏保守, 只改该改的
            max_tokens=16384,
        )
        revised_text = writer_resp.text
        rev_cost = writer_resp.cost
        extra_cost += rev_cost
        _log_cost_fn(book, chapter_num, "writer_editor_fix", rev_cost, time.time() - t0)
        print(f"  [Editor→Writer] 修订完成, ¥{rev_cost:.4f}")
    except Exception as e:
        print(f"  [Editor→Writer] 修订失败(warning): {e}")
        # 修订失败 → 返回原文 + 第 1 轮意见, 不阻塞
        if result_sink is not None:
            result_sink.append(round1_result)
        return text, editor_sections[0], extra_cost

    # ---- 第 2 轮：Editor 再审修订后文本 ----
    if max_revisions >= 2:
        print(f"  [Editor] 第 2 轮审稿(修订后)...")
        round2_result = await editor_review(
            chapter_num=chapter_num,
            chapter_text=revised_text,
            book_dir=book_dir,
            adapter=editor_adapter,
            prev_chapter_tail=prev_chapter_tail,
            planning=planning,
            has_approved_planning=has_approved_planning,
            injection_v2=injection_v2,
            creative_anchor=creative_anchor,
            lookup_catalog=lookup_catalog,
            tool_observer=tool_observer,
        )
        extra_cost += round2_result.cost
        _log_cost_fn(book, chapter_num, "editor_r2", round2_result.cost, 0)

        section_lines = [
            "### 第 2 轮审稿(修订后)",
            "",
            "| # | 类型 | 严重度 | 行号 | 问题描述 | 建议 |",
            "|---|------|--------|------|----------|------|",
        ]
        for idx, issue in enumerate(round2_result.issues, 1):
            severity_icon = "🔴" if issue.severity == "high" else ("🟡" if issue.severity == "medium" else "🟢")
            section_lines.append(
                f"| {idx} | {issue.type} | {severity_icon} {issue.severity} | "
                f"L{issue.line} | {issue.explanation} | {issue.fix_suggestion or '-'} |"
            )
        if not round2_result.issues:
            section_lines.append("| - | ✅ 无 | - | - | 修订后通过 | - |")
        editor_sections.append("\n".join(section_lines))

        # 修订后仍有高严重度 issue → 标记在 editor_section 里
        high_types = {"认知边界", "逻辑常识", "跨章衔接", "章内自洽", "战力等级"}
        round2_high = [i for i in round2_result.issues if i.type in high_types]
        if round2_high:
            remaining = ", ".join(f"{i.type}({i.severity})" for i in round2_high)
            print(f"  [Editor] 第 2 轮后仍有问题: {remaining}")
        else:
            print(f"  [Editor] 第 2 轮通过 ✓")

        editor_section = "\n\n".join(editor_sections)
        if result_sink is not None:
            result_sink.append(round2_result)
        return revised_text, editor_section, extra_cost
    else:
        # 只修不看(省钱模式)
        print(f"  [Editor] 修稿完成(未再审, max_revisions<2)")
        revised_section = (
            "### 修订(Writer 按第 1 轮意见修改)\n\n"
            "_已回传 Writer 修改, 未执行二次审稿。如需验证请手动检查。_"
        )
        editor_sections.append(revised_section)
        editor_section = "\n\n".join(editor_sections)
        if result_sink is not None:
            result_sink.append(round1_result)
        return revised_text, editor_section, extra_cost


def build_whole_revision_messages(package_dir: Path, prompt_path: Path | None = None) -> list[dict[str, str]]:
    """Assemble the signed prompt asset and one persisted revision package."""
    if prompt_path is None:
        prompt_path = Path(__file__).resolve().parents[2] / "prompts" / "writer" / "revision.md"
    if not prompt_path.exists():
        raise RuntimeError(f"整章修订提示词尚未签署安装: {prompt_path}")
    required = ("manifest.json", "issues.json", "comments.md", "candidate.md", "planning.md")
    missing = [name for name in required if not (package_dir / name).exists()]
    if missing:
        raise ValueError("修订包不完整: " + ", ".join(missing))
    manifest = json.loads((package_dir / "manifest.json").read_text(encoding="utf-8"))
    mode = manifest.get("mode")
    if mode is None and "status" not in manifest:
        mode = "local_revision"
    mode_labels = {
        "local_revision": "【局部返修】",
        "deep_rewrite": "【深度重写】",
    }
    if not isinstance(mode, str) or mode not in mode_labels:
        raise ValueError("返修模式无效")
    blocks = [f"## 返修模式\n\n{mode_labels[mode]}"]
    for heading, name in (
        ("本轮问题卡", "issues.json"),
        ("作者意见", "comments.md"),
        ("已批写作方案", "planning.md"),
        ("当前候选稿", "candidate.md"),
    ):
        blocks.append(f"## {heading}\n\n{(package_dir / name).read_text(encoding='utf-8')}")
    return [
        {"role": "system", "content": prompt_path.read_text(encoding="utf-8")},
        {"role": "user", "content": "\n\n".join(blocks)},
    ]


async def revise_chapter_from_package(
    book_dir: Path,
    chapter_num: int,
    package_dir: Path,
    *,
    writer_adapter=None,
    editor_adapter=None,
    prompt_path: Path | None = None,
) -> dict[str, object]:
    """Run exactly one whole-chapter revision call, then one Editor rereview."""
    from biyu.audit_reports.builder import build_audit_md_from_json
    from biyu.audit_reports.revisions import mark_package, text_sha
    from biyu.audit_reports.state import build_report_from_editor_result
    from biyu.editor.editor import review_chapter

    book_dir = book_dir.resolve()
    expected_root = (book_dir / "logs" / f"ch{chapter_num}" / "revisions").resolve()
    package_dir = package_dir.resolve()
    if package_dir.parent != expected_root or not package_dir.name.startswith("round_"):
        raise ValueError("修订包不属于当前书章")
    manifest = json.loads((package_dir / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("status") != "ready":
        raise ValueError("这一轮修订已经提交过，不能重复调用")
    pending = book_dir / "chapters" / "_pending" / f"ch{chapter_num}.md"
    official = book_dir / "chapters" / f"ch{chapter_num}.md"
    if not pending.exists():
        raise ValueError("候选稿已不存在，请刷新工作台")
    before = pending.read_text(encoding="utf-8")
    if text_sha(before) != manifest.get("candidate_sha"):
        raise ValueError("候选稿已有新版本；本轮修订包未调用")
    official_before = official.read_bytes() if official.exists() else None
    registry = get_registry()
    writer_adapter = writer_adapter or registry.get_adapter_for_stage("writer")
    editor_adapter = editor_adapter or registry.get_adapter_for_stage("writer")
    messages = build_whole_revision_messages(package_dir, prompt_path=prompt_path)
    voiceprint_block = load_merged_voiceprint(book_dir)["text"]
    if voiceprint_block:
        messages[-1]["content"] += "\n\n" + voiceprint_block
    started = time.time()
    try:
        response = await writer_adapter.generate(messages=messages, temperature=0.2, max_tokens=16384)
        revised = response.text.strip()
        if not revised:
            raise RuntimeError("写手没有返回修订正文")
        if official_before is not None and official.read_bytes() != official_before:
            raise RuntimeError("正式正文在修订期间发生变化；候选稿未覆盖")
        pending.write_text(revised, encoding="utf-8")
        book = BookConfig(book_dir)
        _log_cost(book, chapter_num, "workbench_revision", response.cost, time.time() - started)
        planning = (package_dir / "planning.md").read_text(encoding="utf-8")
        rereview = await review_chapter(
            chapter_num=chapter_num,
            chapter_text=revised,
            book_dir=book_dir,
            adapter=editor_adapter,
            prev_chapter_tail=_load_prev_chapter_tail(book_dir, chapter_num),
            planning=planning,
            has_approved_planning=planning.splitlines()[0].strip() == "status: 已批",
        )
        _log_cost(book, chapter_num, "workbench_rereview", rereview.cost, 0)
        report = build_report_from_editor_result(chapter_num, rereview, rereview.cost)
        audit_ctx = {
            "book_dir": book_dir,
            "chapter_num": chapter_num,
            "planning": planning,
        }
        audit_results = run_audit(revised, audit_ctx)
        report.results = [
            {"checker": item.checker, "severity": item.severity.value, "message": item.message, "details": item.details}
            for item in audit_results
        ]
        report_dir = book_dir / "audit_reports"
        report.save(report_dir)
        build_audit_md_from_json(report, book_dir)
        output_sha = text_sha(revised)
        mark_package(package_dir, status="complete", output_sha=output_sha, cost_yuan=response.cost + rereview.cost)
        _commit_workbench_revision(book_dir, chapter_num)
        if official_before is not None and official.read_bytes() != official_before:
            raise RuntimeError("正式正文被意外修改")
        return {"candidate_sha": output_sha, "writer_cost": response.cost, "editor_cost": rereview.cost}
    except Exception:
        mark_package(package_dir, status="failed")
        raise


def _commit_workbench_revision(book_dir: Path, chapter_num: int) -> str:
    """Commit only the revised candidate and its reports; preserve unrelated staging."""
    from biyu.git_helper import repo_root_for_book

    try:
        root = repo_root_for_book(book_dir)
    except RuntimeError:
        # Normal product entrypoints resolve books through BIYU_DATA_ROOT, whose
        # repository is initialized before the pipeline runs. Direct library
        # callers may supply an unmanaged temporary directory; the revision is
        # still valid, but there is no local history repository to commit into.
        return ""
    relative_book = book_dir.resolve().relative_to(root)
    paths = [
        relative_book / "chapters" / "_pending" / f"ch{chapter_num}.md",
        relative_book / "audit_reports" / f"ch{chapter_num}.json",
        relative_book / "audit_reports" / f"ch{chapter_num}.md",
    ]
    existing = [str(path) for path in paths if (root / path).exists()]
    if not existing:
        return ""
    added = subprocess.run(["git", "add", "--", *existing], cwd=root, capture_output=True, text=True, encoding="utf-8")
    if added.returncode:
        raise RuntimeError(added.stderr.strip() or "修订版本暂存失败")
    committed = subprocess.run(
        ["git", "commit", "--only", "-m", f"auto: CH{chapter_num} 工作台整章修订", "--", *existing],
        cwd=root, capture_output=True, text=True, encoding="utf-8",
    )
    if committed.returncode:
        raise RuntimeError(committed.stderr.strip() or "修订版本提交失败")
    return committed.stdout.strip()


def _chapter_output_path(chapters_dir: Path, chapter_num: int, *, pending: bool) -> Path:
    """Select the draft destination without touching the official chapter."""
    return chapters_dir / "_pending" / f"ch{chapter_num}.md" if pending else chapters_dir / f"ch{chapter_num}.md"


def _read_north_star(book_dir: Path) -> tuple[str, str]:
    """Return the book-local North Star first, then the legacy project document."""
    from biyu.setup_asset_versions import sync_setup_asset_version

    candidates = (
        (book_dir / "北极星.md", "book_local", "north_star"),
        (get_project_root() / "docs" / f"北极星_{book_dir.name}.md", "legacy_docs", "legacy_north_star"),
    )
    for path, source, asset_id in candidates:
        if path.exists():
            sync_setup_asset_version(book_dir, asset_id, reason="managed_read")
            return path.read_text(encoding="utf-8"), source
    return "", "missing"


def _capture_generation_setup_versions(book_dir: Path) -> dict[str, int | None]:
    """Freeze and durably record the three setting versions for this attempt."""
    from biyu.setup_asset_versions import save_setup_asset_version

    versions = {
        asset_id: save_setup_asset_version(
            book_dir, asset_id, reason="generation_reference",
        )
        for asset_id in ("worldbook", "characters", "north_star")
    }
    record = {
        "captured_at": datetime.now().isoformat(),
        "setup_versions": versions,
    }
    log_path = book_dir / "logs" / "generation_setup_versions.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return versions


async def generate_chapter(
    book_dir: Path,
    chapter_num: int,
    chapter_outline_path: Path | None = None,
    model_overrides: dict[str, str] | None = None,
    prompt_version: str = "v4",
    truth_filter_enabled: bool = False,
    replan: bool = False,
    force_pending: bool = False,
) -> ChapterResult:
    """Generate a single chapter through the three-stage pipeline.

    Args:
        book_dir: Path to the book directory (containing book.json).
        chapter_num: Chapter number to generate.
        chapter_outline_path: Path to outline file. Defaults to outlines/ch{N}.md.
        model_overrides: Optional dict of pipeline stage → model alias overrides.
                         e.g. {"writer": "r1", "polisher": "v3"}.
                         Only affects this call, does not modify yaml.
        prompt_version: "v4" for new 3-layer prompt, "v3" for legacy prompt.
        truth_filter_enabled: P6-A1 实体过滤注入开关。False(默认)= 全量 truth
                         拼接(改造前基线, D-45 钉死); True = 按 outline 出场实体
                         只注入相关真值(改造后)。
        replan: If True, force rerun Architect even if planning.md exists.
               If False, use existing planning.md when status: 已批.
        force_pending: If True, always stage the generated draft in _pending/.
                       Defaults to False so ordinary write behavior is unchanged.

    Returns:
        ChapterResult with all outputs and metadata.
    """
    generation_setup_versions = _capture_generation_setup_versions(book_dir)
    book = BookConfig(book_dir)
    meta = book.load_meta()
    registry = get_registry()
    # Strict bool prevents generic MagicMock registries from accidentally enabling Q-1.
    get_feature = getattr(registry, "get_feature", None)
    injection_v2 = get_feature("injection_v2") is True if callable(get_feature) else False

    overrides = model_overrides or {}

    genre = meta.get("genre", "xuanhuan")
    target_words = meta.get("chapter_target_words", 5000)
    min_words = meta.get("chapter_min_words", 4250)
    context_mode = meta.get("context_mode", "long_context")

    # Voiceprint is a stable Layer 2 input. The loader also normalizes the
    # legacy fingerprint_path contract without mutating its source asset.
    try:
        fingerprint_block = load_merged_voiceprint(book_dir)["text"]
    except Exception as exc:
        fingerprint_block = ""
        print(f"  [WARN] 声纹文件格式错误，跳过注入: {exc}")

    # Resolve outline
    if chapter_outline_path is None:
        chapter_outline_path = book.outline_path(chapter_num)
    if not chapter_outline_path.exists():
        raise FileNotFoundError(f"Outline not found: {chapter_outline_path}")
    outline = chapter_outline_path.read_text(encoding="utf-8")

    # ---- Extract info boundary from outline ----
    info_boundary = _extract_info_boundary(outline)

    # ---- Load worldbook (T-P3-A) ----
    wb = load_worldbook(book_dir)
    worldbook_prompt = build_worldbook_prompt(wb)
    if worldbook_prompt:
        print(f"  worldbook 已加载，注入 prompt")
    else:
        print(f"  worldbook 未找到，跳过注入(warning)")

    # ---- Load prev chapter tail for transition anchor (T-P3-A) ----
    prev_tail = _load_prev_chapter_tail(book_dir, chapter_num)
    if prev_tail:
        print(f"  衔接锚点: 上一章末尾 {len(prev_tail)} 字")

    # ---- Parse present characters from outline (T-P3-A) ----
    present_characters = _parse_present_characters(outline, book_dir)
    if present_characters:
        print(f"  在场角色锁: {', '.join(present_characters)}")
    else:
        print(f"  在场角色锁: 无(无 frontmatter 且兜底为空)")

    # ---- Sync characters to SQLite ----
    init_db(book_dir)
    sync_result = sync_characters_from_yaml(book_dir)
    print(f"  角色同步: yaml {sync_result[0]} 条 → SQLite {sync_result[1]} 条")
    characters = load_characters_yaml(book_dir)
    from biyu.prompts.chapter_writer import resolve_present_characters
    present_resolution = resolve_present_characters(present_characters, characters)
    present_characters = present_resolution.matched_names
    if present_resolution.unmatched_names:
        print(f"  在场名单未匹配人物卡: {', '.join(present_resolution.unmatched_names)}")
    previous_present_characters: list[str] = []
    if chapter_num > 1:
        previous_outline_path = book.outline_path(chapter_num - 1)
        if previous_outline_path.exists():
            previous_names = _parse_present_characters(
                previous_outline_path.read_text(encoding="utf-8"),
                book_dir,
                allow_truth_fallback=False,
            )
            previous_present_characters = resolve_present_characters(
                previous_names, characters,
            ).matched_names

    # ---- Build context block (truth files + history chapters) ----
    print(f"  构建上下文 (模式: {context_mode})...")
    context_block, retriever = _build_context_block(book_dir, chapter_num, context_mode)
    if injection_v2:
        # Q-1 已将 truth 预注入，历史改为目录查询；不再与 prev500 重复。
        context_block = ""
    if context_block:
        ctx_chars = len(context_block)
        print(f"  上下文: {ctx_chars} 字符")
    else:
        print(f"  上下文: 无(第一章或无历史数据)")

    total_cost = 0.0
    total_start = time.time()
    stage_latencies: dict[str, float] = {}
    warnings: list[str] = []
    write_to_pending = force_pending
    north_star_source = "not_needed"

    # ---- 读取 truth_files (Architect + Writer 共用) ----
    truth_files_block = ""
    truth_data = read_all_truth_files(book_dir)
    if truth_filter_enabled:
        # P6-A1: 按 outline 出场实体过滤(改造后); 复用 alias 预注册
        truth_files_block = build_truth_injection_block(
            truth_data, characters, outline, filter_enabled=True,
        )
    else:
        # D-45 钉死: 改造前基线 = 全量拼接(逐字不变)
        for name, content in truth_data.items():
            if content.strip():
                truth_files_block += f"=== {name} ===\n{content}\n\n"

    q1_character_catalog = ""
    q1_worldbook_catalog = ""
    q1_history_catalog = ""
    q1_worldbook_preload = ""
    q1_present_cards: list[dict] = []
    if injection_v2:
        from biyu.injection_tools import build_character_catalog, build_worldbook_catalog

        q1_character_catalog = build_character_catalog(book_dir)
        q1_worldbook_catalog = _catalog_without_lines(
            build_worldbook_catalog(book_dir),
            {"创作锚点", "不可变硬设定", "绝对禁止", "力量·修炼体系"},
        )
        q1_history_catalog = _q1_history_catalog(book_dir, chapter_num)
        q1_worldbook_preload = _q1_worldbook_prompt(wb)
        present_set = set(present_characters)
        q1_present_cards = [
            char for char in characters
            if isinstance(char, dict) and str(char.get("name") or "") in present_set
        ]
        q1_character_catalog = _catalog_without_lines(q1_character_catalog, present_set)

    # ---- Stage 1: Architect (planner) ----
    planning_text = ""

    # R1-1: 检测已批规划件
    log_dir = book_dir / "logs" / f"ch{chapter_num}"
    planning_path = log_dir / "planning.md"
    use_existing_planning = False
    planner_alias = overrides.get("planner") or registry.get_pipeline_config().get("planner", "r1")
    planning_resp = LLMResponse(text="", model=planner_alias)

    if not replan:
        status, content = _read_planning_status(planning_path)
        if status == "已批" and content:
            planning_text = content
            use_existing_planning = True
            log_path_str = str(planning_path.relative_to(book_dir))
            print(f"  检测到已批规划件,跳过 Architect: {log_path_str}")

    if not use_existing_planning:
        console_output = f"  [1/4] Architect ({planner_alias} 规划)..."
        print(console_output)
        t0 = time.time()
        planner_adapter = registry.get_adapter_for_stage("planner", override=overrides.get("planner"))
        north_star, north_star_source = _read_north_star(book_dir)
        if north_star.strip():
            if not injection_v2:
                # Keep the signed static prompt text unchanged: this is background material,
                # carried through the existing worldbook input seam.
                worldbook_prompt = "\n\n".join(part for part in (worldbook_prompt, north_star) if part.strip())
                print(f"  北极星已载入（来源：{'书内' if north_star_source == 'book_local' else '兼容旧稿'}）")
        else:
            notice = "本书方向说明暂未找到；本次方案仍按其余资料生成。"
            warnings.append(notice)
            print(f"  {notice}")
        planning_content = build_planning_prompt(
            outline=outline,
            characters=[] if injection_v2 else characters,
            truth_files_block=truth_files_block,
            worldbook_prompt=q1_worldbook_preload if injection_v2 else worldbook_prompt,
            chapter_num=chapter_num,
            prev_tail=prev_tail,
            present_characters=present_characters,
            previous_present_characters=previous_present_characters,
            character_catalog=q1_character_catalog,
            worldbook_catalog=q1_worldbook_catalog,
            injection_v2=injection_v2,
        )
        planning_messages = [{"role": "user", "content": planning_content}]
        if injection_v2:
            planning_resp = await _run_q1_tool_loop(
                adapter=planner_adapter,
                fallback_adapter=registry.get_adapter("v3") if registry.get_feature("planner_guard") else None,
                messages=planning_messages,
                book_dir=book_dir,
                chapter_num=chapter_num,
                role="architect",
                guarded=registry.get_feature("planner_guard"),
                generate_kwargs={},
            )
            planning_text = planning_resp.text
            planning_status = "degraded" if planning_resp.degraded else "ok"
            stage_latencies["architect"] = time.time() - t0
            total_cost += planning_resp.cost
            _log_cost(
                book, chapter_num, "architect", planning_resp.cost,
                stage_latencies["architect"], status=planning_status,
            )
            print(
                f"  [1/4] OK - {stage_latencies['architect']:.1f}s, "
                f"¥{planning_resp.cost:.4f}, status={planning_status}"
            )
            if planning_resp.degraded:
                planning_text = (
                    "> ⚠️ 本次戏核由降级模型生成, 未经主模型确认。\n"
                    "> 管线已停下, 未进入 Writer。请作者审阅后决定用否。\n\n"
                    + planning_text
                )
                log_dir = book.chapter_log_dir(chapter_num)
                log_dir.mkdir(parents=True, exist_ok=True)
                (log_dir / "planning.md").write_text(planning_text, encoding="utf-8")
                notice = "戏核由降级模型生成, 已停下待作者定夺(不进 Writer)。"
                warnings.append(notice)
                return ChapterResult(
                    chapter_num=chapter_num, final_text="", word_count=0,
                    cost_cny=total_cost, latency_seconds=stage_latencies["architect"],
                    stage_latencies=stage_latencies, warnings=warnings,
                    planning_text=planning_text,
                )
        elif registry.get_feature("planner_guard"):
            # E-1 兜底:空/截断戏核拦截 + 降级停机制(H-1 后默认关,走配置开关)
            try:
                planning_resp = await planner_adapter.generate_guarded(
                    planning_messages,
                    fallback_adapter=registry.get_adapter("v3"),
                )
                planning_text = planning_resp.text
                planning_status = "degraded" if planning_resp.degraded else "ok"
                stage_latencies["architect"] = time.time() - t0
                total_cost += planning_resp.cost
                _log_cost(book, chapter_num, "architect", planning_resp.cost, stage_latencies["architect"], status=planning_status)
                print(f"  [1/4] OK - {stage_latencies['architect']:.1f}s, ¥{planning_resp.cost:.4f}, status={planning_status}")
                if planning_resp.degraded:
                    # E-1 2c: 降级产出不自动往下传。落盘带标记, 管线在此停下, 交作者定夺。
                    planning_text = (
                        "> ⚠️ 本次戏核由降级模型(deepseek-chat)生成, 未经主模型(r1)确认。\n"
                        "> 管线已停下, 未进入 Writer。请作者审阅后决定用否。\n\n"
                        + planning_text
                    )
                    log_dir = book.chapter_log_dir(chapter_num)
                    log_dir.mkdir(parents=True, exist_ok=True)
                    (log_dir / "planning.md").write_text(planning_text, encoding="utf-8")
                    notice = "戏核由降级模型生成, 已停下待作者定夺(不进 Writer)。"
                    warnings.append(notice)
                    print(f"  {notice}")
                    return ChapterResult(
                        chapter_num=chapter_num,
                        final_text="",
                        word_count=0,
                        cost_cny=total_cost,
                        latency_seconds=stage_latencies["architect"],
                        stage_latencies=stage_latencies,
                        warnings=warnings,
                        planning_text=planning_text,
                    )
            except GenerationError as e:
                # E-1 2d: 上层不静默 + 不写空文件 + planning 为空禁走 Writer。
                stage_latencies["architect"] = time.time() - t0
                total_cost += e.total_cost
                _log_cost(book, chapter_num, "architect", e.total_cost, stage_latencies["architect"], status=e.failure_type)
                notice = (
                    f"Architect 生成失败({e.failure_type}), 已重试 {e.attempts} 次"
                    f" (¥{e.total_cost:.4f})。未写 planning.md, 管线停止。"
                )
                warnings.append(notice)
                print(f"  {notice}")
                return ChapterResult(
                    chapter_num=chapter_num,
                    final_text="",
                    word_count=0,
                    cost_cny=total_cost,
                    latency_seconds=stage_latencies["architect"],
                    stage_latencies=stage_latencies,
                    warnings=warnings,
                    planning_text="",
                )
        else:
            # H-1:planner_guard 默认关,回退原逻辑(空/截断不拦截,保持历史行为)
            planning_resp = await _call_with_retry(planner_adapter, planning_messages)
            planning_text = planning_resp.text
            stage_latencies["architect"] = time.time() - t0
            total_cost += planning_resp.cost
            _log_cost(book, chapter_num, "architect", planning_resp.cost, stage_latencies["architect"])
            print(f"  [1/4] OK - {stage_latencies['architect']:.1f}s, ¥{planning_resp.cost:.4f}")

    # ---- 细纲层 anchor 早闸(非阻塞, P6-A2)----
    # 零 LLM: 纯子串 value-match。anchors.yaml 不存在则静默跳过。
    skeleton_anchor_report = None
    try:
        anchors_yaml = book_dir / "anchors.yaml"
        if anchors_yaml.exists():
            skel_report = run_check_text(str(anchors_yaml), planning_text, f"T{chapter_num}")
            sk = skel_report["stats"]["atomic"]
            print(
                f"  [1/4] 细纲锚点: 在 {sk['hit']} / 值错 {sk['value_mismatch']} "
                f"/ 缺 {sk['miss']} (共 {sk['total']})"
            )
            skeleton_anchor_report = skel_report
            # CutA: 早闸报告落盘(为回流提供磁盘载体, B1 收尾发现的工程债)
            _write_json(
                book_dir / "logs" / f"ch{chapter_num}" / "anchor_skeleton.json",
                skel_report,
            )
    except Exception as e:
        print(f"  [1/4] 细纲锚点检查跳过: {e}")

    # ---- Stage 2: Writer ----
    skeleton_text = ""
    writer_alias = overrides.get("writer") or registry.get_pipeline_config().get("writer", "v3")
    print(f"  [2/4] Writer ({writer_alias}, prompt={prompt_version})...")
    t0 = time.time()
    writer_adapter = registry.get_adapter_for_stage("writer", override=overrides.get("writer"))

    if prompt_version == "v4":
        from biyu.prompts.chapter_writer import build_writer_prompt_v4, build_layer2_context

        system_prompt, user_prompt = build_writer_prompt_v4(
            chapter_num=chapter_num,
            worldbook=wb,
            worldbook_prompt=q1_worldbook_preload if injection_v2 else worldbook_prompt,
            characters=q1_present_cards if injection_v2 else characters,
            truth_files_block=truth_files_block,
            prev_tail=prev_tail,
            context_block=context_block,
            outline=planning_text,     # P6-1A: Architect 细纲作为 outline 传入
            planning="",                # P6-1A: 不再有独立 planning,细纲已在 outline 中
            target_words=target_words,
            present_characters=present_characters,
            previous_present_characters=previous_present_characters,
            voiceprint_block=fingerprint_block,
            injection_v2=injection_v2,
            original_outline=outline,
            character_catalog=q1_character_catalog,
            worldbook_catalog=q1_worldbook_catalog,
            history_catalog=q1_history_catalog,
        )

        # 拆分 cacheable_prefix 和 dynamic_messages
        # 稳定段: system + worldbook + 全员一行速查（跨章不变）
        stable_layer2 = build_layer2_context(
            worldbook_prompt="" if injection_v2 else worldbook_prompt,
            characters=[] if injection_v2 else characters,
            truth_files_block="",  # truth_files 每章变化
            prev_tail="",
            context_block="",
            outline="",
            planning="",
            present_characters=present_characters,
            previous_present_characters=previous_present_characters,
            voiceprint_block=fingerprint_block,
            character_projection="quick",
        )

        cacheable_prefix = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": stable_layer2},
            {"role": "assistant", "content": "已加载世界观和角色卡。"},
        ]

        # 变化段: Layer 1 + 变化的 Layer 2 部分 + Layer 3
        from biyu.prompts.chapter_writer import (
            build_layer1_hard_rules, build_layer3_constraints,
            LAYER1_BEGIN, LAYER1_END, LAYER3_BEGIN, LAYER3_END,
        )
        layer1 = build_layer1_hard_rules(chapter_num, wb)
        variable_layer2 = build_layer2_context(
            worldbook_prompt=q1_worldbook_preload if injection_v2 else "",  # 旧态已在 prefix 中
            characters=q1_present_cards if injection_v2 else characters,
            truth_files_block=truth_files_block,
            prev_tail=prev_tail,
            context_block=context_block,
            outline=planning_text,     # P6-1A: Architect 细纲
            planning="",                # P6-1A: 细纲已在 outline 中
            present_characters=present_characters,
            previous_present_characters=previous_present_characters,
            injection_v2=injection_v2,
            original_outline=outline,
            character_catalog=q1_character_catalog,
            worldbook_catalog=q1_worldbook_catalog,
            history_catalog=q1_history_catalog,
            character_projection=(
                "combined" if injection_v2 else "selected_full"
            ),
        )
        layer3 = build_layer3_constraints(target_words)
        dynamic_content = (
            f"{layer1}\n\n"
            f"{variable_layer2}\n\n"
            f"{layer3}\n\n"
            f"现在开始写第 {chapter_num} 章正文。只输出正文,不要输出元信息。"
        )

        dynamic_messages = [
            {"role": "user", "content": dynamic_content},
        ]

        if injection_v2:
            writer_resp = await _run_q1_tool_loop(
                adapter=writer_adapter,
                fallback_adapter=None,
                messages=dynamic_messages,
                book_dir=book_dir,
                chapter_num=chapter_num,
                role="writer",
                guarded=False,
                generate_kwargs={
                    "cacheable_prefix": cacheable_prefix,
                    "temperature": 0.8,
                    "max_tokens": 16384,
                },
            )
        else:
            writer_resp = await _call_with_retry(
                writer_adapter, dynamic_messages,
                cacheable_prefix=cacheable_prefix,
                temperature=0.8,
                max_tokens=16384,
            )
    else:
        # v3 has no layered context; do not append voice content to its system
        # tail. Voiceprint-aware generation uses the v4 layered prompt.
        v3_system = _get_v3_system_prompt()
        writer_messages = [
            {"role": "system", "content": v3_system},
            {"role": "user", "content": build_writer_user_prompt(
                planning=planning_text,
                outline=outline,
                target_words=target_words,
                genre=genre,
                characters=characters,
                context_block=context_block,
                info_boundary=info_boundary,
                worldbook_prompt=worldbook_prompt,
                prev_tail=prev_tail,
                present_characters=present_characters,
            )},
        ]
        writer_resp = await _call_with_retry(
            writer_adapter, writer_messages, temperature=0.8,
            max_tokens=16384,
        )
    skeleton_text = writer_resp.text
    stage_latencies["writer"] = time.time() - t0
    total_cost += writer_resp.cost
    _log_cost(book, chapter_num, "writer", writer_resp.cost, stage_latencies["writer"])
    skeleton_count = count_cjk_chars(skeleton_text)
    print(f"  [2/4] OK - {stage_latencies['writer']:.1f}s, ¥{writer_resp.cost:.4f}, {skeleton_count}字")

    # ---- CutA: 早闸回流闭环(P6-A2-CutA, 方案 b 事后修订)----
    # Stage 2 Writer 完成后, 对 skeleton_text 跑 anchor 检查,
    # 若 miss+vm > 0 喂回 Writer 修订, 最多 2 轮, 仍不达标放行 + 标记。
    # 绝不回溯旧章节(只读 anchors.yaml), 异常不阻塞管线。
    skeleton_text, anchor_loop_state = await _cut_a_apply(
        skeleton_text=skeleton_text,
        anchors_yaml=book_dir / "anchors.yaml",
        chapter_id=f"T{chapter_num}",
        writer_adapter=writer_adapter,
        book=book,
        book_dir=book_dir,
        chapter_num=chapter_num,
        max_rounds=2,
    )
    skeleton_count = count_cjk_chars(skeleton_text)  # 修订后字数重算

    # ---- Chapter number fix (T-P3-A) ----
    skeleton_text = _fix_chapter_number(skeleton_text, chapter_num)

    # ---- Stage 3: WordGuard ----
    text_after_guard = skeleton_text
    guard_result: WordGuardResult | None = None
    print(f"  [3/4] WordGuard (字数检查: {skeleton_count}/{min_words})...")
    t0 = time.time()

    async def _continuation_fn(current_text: str, remaining: int) -> str | None:
        """Request continuation from planner model."""
        cont_prompt = (
            f"以下是上一章正文(已写{count_cjk_chars(current_text)}字,目标{target_words}字):\n\n"
            f"{current_text[-1500:]}\n\n"
            f"请从断点处自然续写约{remaining}字,保持风格和人物一致。\n"
            f"只输出续写正文,不要输出说明。"
        )
        messages = [{"role": "user", "content": cont_prompt}]
        resp = await _call_with_retry(planner_adapter, messages)
        return resp.text

    guard_result = await enforce_floor(
        text=skeleton_text,
        target=target_words,
        floor=min_words,
        continuation_fn=_continuation_fn,
    )
    text_after_guard = guard_result.text
    stage_latencies["wordguard"] = time.time() - t0
    if guard_result.continued:
        cont_cost = planning_resp.cost * (guard_result.continuation_word_count / max(skeleton_count, 1))
        total_cost += cont_cost
        _log_cost(book, chapter_num, "wordguard", cont_cost, stage_latencies["wordguard"])
    if guard_result.warning:
        warnings.append(guard_result.warning)
    print(
        f"  [3/4] {'篇幅提醒' if guard_result.warning else '篇幅合适'} - "
        f"{skeleton_count}→{guard_result.word_count}字"
        + (f" [WARN: {guard_result.warning}]" if guard_result.warning else "")
    )

    # ---- Stage 3.5: dash_fixer (破折号后处理) ----
    if prompt_version == "v4":
        from biyu.postproc.dash_fixer import fix_dashes
        dash_result = fix_dashes(text_after_guard)
        if dash_result.original_count != dash_result.fixed_count:
            dash_log_dir = book.logs_dir / f"ch{chapter_num}"
            dash_log_dir.mkdir(parents=True, exist_ok=True)
            (dash_log_dir / "skeleton_raw.md").write_text(dash_result.original_text, encoding="utf-8")
            (dash_log_dir / "skeleton_dashfixed.md").write_text(dash_result.fixed_text, encoding="utf-8")
            text_after_guard = dash_result.fixed_text
            print(
                f"  [dash_fixer] 破折号 {dash_result.original_count} → {dash_result.fixed_count}"
                f" ({len(dash_result.replacements)} 条规则触发)"
            )
            # Git commit: dash_fixer 修复
            try:
                from biyu.git_helper import commit_chapter
                dash_hash = commit_chapter(
                    book_dir, chapter_num,
                    f"dash_fixer 修复（{dash_result.original_count}→{dash_result.fixed_count}）",
                    auto=True,
                )
                print(f"  [git] dash_fixer 已提交: {dash_hash}")
            except Exception as e:
                print(f"  [git] dash_fixer 提交失败(warning): {e}")
        else:
            print(f"  [dash_fixer] 破折号 {dash_result.original_count} 个,无需修复")

    # ---- Stage 3.6: wenyan_fixer (文白夹杂后处理,可通过 wenyan_enabled=false 跳过) ----
    wenyan_enabled = registry.get_pipeline_config().get("wenyan_enabled", True)
    if prompt_version == "v4" and wenyan_enabled:
        from biyu.postproc.wenyan_fixer import fix_wenyan
        in_secret_realm = _detect_secret_realm(outline)
        wenyan_result = fix_wenyan(text_after_guard, in_secret_realm=in_secret_realm)
        if wenyan_result.replacements:
            text_after_guard = wenyan_result.fixed_text
            total_replaced = sum(r["count"] for r in wenyan_result.replacements)
            print(
                f"  [wenyan_fixer] 文白修复 {total_replaced} 处"
                f" ({len(wenyan_result.replacements)} 类文言词替换)"
            )
        else:
            print(f"  [wenyan_fixer] 无文白夹杂问题")
    elif not wenyan_enabled:
        print(f"  [wenyan_fixer] 跳过 (wenyan_enabled=false)")

    # ---- Stage 3.7: grammar_check (T-P3-C P1) ----
    if prompt_version == "v4":
        from biyu.grammar_check.checker import check_chapter as grammar_check, auto_fix as grammar_auto_fix
        print(f"  [grammar_check] 本地检查...")
        grammar_result = grammar_check(text_after_guard, book_dir)
        if grammar_result.has_issues:
            text_after_guard, grammar_fixed = grammar_auto_fix(text_after_guard, grammar_result)
            if grammar_fixed > 0:
                print(f"  [grammar_check] 修复 {grammar_fixed} 处（占位符{len(grammar_result.placeholders)} / 错别字{len(grammar_result.typos)} / 重复字{len(grammar_result.repeated_chars)}）")
                try:
                    from biyu.git_helper import commit_chapter
                    gh_hash = commit_chapter(book_dir, chapter_num, f"grammar 修复 ({grammar_fixed} 处)", auto=True)
                    print(f"  [git] grammar_check 已提交: {gh_hash}")
                except Exception as e:
                    print(f"  [git] grammar_check 提交失败(warning): {e}")
            else:
                print(f"  [grammar_check] 发现 {grammar_result.total_count} 处问题但无高置信自动修")
        else:
            print(f"  [grammar_check] 通过")

    # ---- Stage 3.8: Editor 审稿 (T-P3-C P1 / T-P3-D-2 multi-agent) ----
    editor_enabled = registry.get_pipeline_config().get("editor_enabled", True)
    editor_result_obj = None
    editor_section = ""  # 审计报告 section 4 内容
    if prompt_version == "v4" and editor_enabled:
        t0_ed = time.time()
        try:
            from biyu.editor.auto_fix import auto_fix_issues as editor_auto_fix

            # 加载上一章末尾
            prev_tail_for_editor = ""
            if chapter_num > 1:
                prev_ch = book_dir / "chapters" / f"ch{chapter_num - 1}.md"
                if prev_ch.exists():
                    prev_text = prev_ch.read_text(encoding="utf-8")
                    prev_tail_for_editor = prev_text[-500:]

            editor_adapter = registry.get_adapter_for_stage("writer", override=None)
            import yaml

            anchors = (wb or {}).get("narrative_anchors")
            editor_anchor = (
                yaml.safe_dump(anchors, allow_unicode=True, sort_keys=False).strip()
                if anchors else ""
            )
            editor_catalog = ""
            editor_observer = None
            if injection_v2:
                editor_anchor, editor_catalog, editor_observer = _q1_editor_inputs(
                    book_dir, wb, chapter_num
                )

            # 读取 editor config 判断 mode
            from biyu.editor.multi_agent import load_editor_config, review_chapter_multi_agent
            from biyu.editor.merge import render_audit_report
            ed_config = load_editor_config()
            ed_mode = ed_config.get("mode", "single")

            if ed_mode == "multi_agent":
                # Multi-agent 审稿
                print(f"  [Editor] Multi-Agent 审稿 (A/B/C)...")
                merge_result = await review_chapter_multi_agent(
                    chapter_num=chapter_num,
                    chapter_text=text_after_guard,
                    book_dir=book_dir,
                    adapter=editor_adapter,
                    prev_chapter_tail=prev_tail_for_editor,
                    injection_v2=injection_v2,
                    creative_anchor=editor_anchor,
                    lookup_catalog=editor_catalog,
                    tool_observer=editor_observer,
                )
                stage_latencies["editor"] = time.time() - t0_ed
                _log_cost(book, chapter_num, "editor", merge_result.total_cost, stage_latencies["editor"])

                editor_section = render_audit_report(chapter_num, merge_result)
                n_issues = merge_result.total_issues
                n_high = len(merge_result.high_issues)
                print(f"  [Editor] {n_issues} 个合并问题（{n_high} 个高严重度）")
                if merge_result.fallback_used:
                    print(f"  [Editor] ⚠️ 成本超限，已回退到 Phase 1 直接合并")

                # 高严重度 issue 触发 _pending
                if merge_result.high_issues:
                    write_to_pending = True
                    high_types = {i.type for i in merge_result.high_issues}
                    warnings.append(f"Editor 标记需审查: {', '.join(high_types)}")
                    print(f"  [Editor] → 进 _pending/（需老板审查）")

            else:
                if force_pending:
                    # 工作台先交候选与问题卡，由作者选择后再一轮一包修订；不在背后先改一遍。
                    from biyu.editor.editor import review_chapter as editor_review
                    print("  [Editor] 工作台候选审读（不自动改稿）...")
                    editor_result_obj = await editor_review(
                        chapter_num=chapter_num,
                        chapter_text=text_after_guard,
                        book_dir=book_dir,
                        adapter=editor_adapter,
                        prev_chapter_tail=prev_tail_for_editor,
                        planning=planning_text,
                        has_approved_planning=use_existing_planning,
                        injection_v2=injection_v2,
                        creative_anchor=editor_anchor,
                        lookup_catalog=editor_catalog,
                        tool_observer=editor_observer,
                    )
                    extra_cost = editor_result_obj.cost
                    rows = [
                        f"规划履约:{'偏离 ' + str(sum(i.type == '规划履约' for i in editor_result_obj.issues)) if use_existing_planning else '无合同,跳过'}",
                        "", "### 候选稿审读", "", "| # | 类型 | 严重度 | 行号 | 问题描述 | 建议 |",
                        "|---|------|--------|------|----------|------|",
                    ]
                    for idx, issue in enumerate(editor_result_obj.issues, 1):
                        rows.append(f"| {idx} | {issue.type} | {issue.severity} | L{issue.line} | {issue.explanation} | {issue.fix_suggestion or '-'} |")
                    if not editor_result_obj.issues:
                        rows.append("| - | 无 | - | - | 审读未发现问题 | - |")
                    editor_section = "\n".join(rows)
                else:
                    # 普通 CLI 保持既有自动修稿路径，八号裁定的默认行为不变。
                    print(f"  [Editor] V4-Pro 审稿+修稿 (single mode, max 2 round)...")
                    editor_results: list = []
                    revised_text, editor_section, extra_cost = await _editor_revision_loop(
                        chapter_num=chapter_num,
                        text=text_after_guard,
                        book_dir=book_dir,
                        editor_adapter=editor_adapter,
                        writer_adapter=writer_adapter,
                        book=book,
                        _log_cost_fn=lambda b, cnum, stage, cost, lat: _log_cost(b, cnum, stage, cost, lat),
                        prev_chapter_tail=prev_tail_for_editor,
                        planning=planning_text,
                        has_approved_planning=use_existing_planning,
                        max_revisions=2,
                        result_sink=editor_results,
                        injection_v2=injection_v2,
                        creative_anchor=editor_anchor,
                        lookup_catalog=editor_catalog,
                        tool_observer=editor_observer,
                    )
                    if editor_results:
                        editor_result_obj = editor_results[-1]
                stage_latencies["editor"] = time.time() - t0_ed
                total_cost += extra_cost
                _log_cost(book, chapter_num, "editor_total", extra_cost, stage_latencies["editor"])

                # 修订后的文本替换原文
                if not force_pending and revised_text != text_after_guard:
                    text_after_guard = revised_text
                    print(f"  [Editor] 修稿完成, 字数: {count_cjk_chars(text_after_guard)}")

                # 检查修后是否仍有高严重度 issue
                # editor_section 中已包含两轮结果, 这里只需要决定 _pending
                high_keywords = ["🔴 high"]
                if any(kw in editor_section for kw in high_keywords):
                    write_to_pending = True
                    warnings.append("Editor 第2轮审稿后仍有高严重度问题, 需老板审查")
                    print(f"  [Editor] → 进 _pending/（修后仍有问题）")

        except Exception as e:
            print(f"  [Editor] 审稿失败(warning): {e}")
            warnings.append(f"Editor 审稿失败(warning): {e}")

    # ---- Stage 4: Polish (可通过 polish_enabled=false 跳过) ----
    final_text = text_after_guard
    polish_result: PolishResult | None = None
    polisher_alias = overrides.get("polisher") or registry.get_pipeline_config().get("polisher", "kimi")
    polish_enabled = registry.get_pipeline_config().get("polish_enabled", True)

    if polish_enabled:
        print(f"  [4/4] Polish ({polisher_alias} 润色)...")
        t0 = time.time()
        polish_result = await polish_chapter(
            text_after_guard, registry,
            model_key=polisher_alias,
        )
        stage_latencies["polisher"] = time.time() - t0
        total_cost += polish_result.cost
        _log_cost(book, chapter_num, "polisher", polish_result.cost, stage_latencies["polisher"])
        if polish_result.success:
            final_text = polish_result.polished_text
            # D-03: Kimi 削减超 10% 则回退到润色前版本
            guard_count = count_cjk_chars(text_after_guard)
            polished_count = count_cjk_chars(final_text)
            if polished_count < guard_count * 0.9:
                warnings.append(
                    f"Kimi 削减超 10% ({guard_count}→{polished_count}),使用润色前版本"
                )
                final_text = text_after_guard
                print(f"  [4/4] WARN - Kimi 削减 {guard_count}→{polished_count},回退原文")
            else:
                print(f"  [4/4] OK - {stage_latencies['polisher']:.1f}s, ¥{polish_result.cost:.4f}")
        else:
            warnings.append(f"Kimi 润色失败: {polish_result.error}")
            print(f"  [4/4] FAIL - 降级使用原文: {polish_result.error}")
    else:
        print(f"  [4/4] Polish 跳过 (polish_enabled=false)")
        # 创建一个空的 polish_result 占位,后续 meta 写入不会崩
        polish_result = PolishResult(
            polished_text=text_after_guard,
            success=True,
            cost=0.0,
            error="",
        )

    total_latency = time.time() - total_start
    final_count = count_cjk_chars(final_text)

    # ---- Consistency check ----
    from biyu.consistency import check_chapter
    consistency_issues = check_chapter(book_dir, chapter_num, chapter_text=final_text)
    consistency_dicts = []
    if consistency_issues:
        for iss in consistency_issues:
            warnings.append(
                f"[一致性] {iss.rule}: {iss.character} 在 ch{chapter_num} "
                f"段落『{iss.location[:30]}...』"
            )
            consistency_dicts.append({
                "rule": iss.rule,
                "severity": iss.severity,
                "character": iss.character,
                "location": iss.location,
                "suggestion": iss.suggestion,
            })

    # ---- Save outputs ----
    # D-05: 正则清理元标记（双保险，prompt 层已加清理规则）
    final_text = re.sub(r'【[^】]{1,20}】', '', final_text)

    # ---- Auditor (T-P3-A) ----
    audit_results: list[AuditResult] = []
    audit_warnings: list[str] = []
    print(f"  [Auditor] 执行 9 项检查...")
    try:
        audit_ctx = {
            "book_dir": str(book_dir),
            "chapter_num": chapter_num,
            "worldbook": wb,
            "characters": characters,
            "present_characters": present_characters,
            "outline": outline,
            "planning": planning_text,
        }
        audit_results = run_audit(final_text, audit_ctx)
        # 保存审计报告
        report_path = save_audit_report(book_dir, chapter_num, audit_results)
        if editor_result_obj is not None:
            from biyu.audit_reports.state import build_report_from_editor_result
            structured_report = build_report_from_editor_result(chapter_num, editor_result_obj)
            structured_report.results = [
                {"checker": item.checker, "severity": item.severity.value, "message": item.message, "details": item.details}
                for item in audit_results
            ]
            report_path = structured_report.save(book_dir / "audit_reports")
        print(f"  [Auditor] 报告已保存: {report_path}")

        for ar in audit_results:
            severity_label = ar.severity.value if isinstance(ar.severity, Severity) else str(ar.severity)
            print(f"    [{severity_label}] {ar.checker}: {ar.message}")
            audit_warnings.append(f"[{severity_label}] {ar.checker}: {ar.message}")

            # BLOCK → 进 _pending/
            if ar.severity == Severity.BLOCK:
                write_to_pending = True
                warnings.append(f"Auditor BLOCK: {ar.checker} - {ar.message}")
    except Exception as e:
        audit_warnings.append(f"Auditor 整体异常: {e}")
        print(f"  [Auditor] 整体异常(warning): {e}")

    # 根据质量门或工作台定夺契约决定写入路径
    book.chapters_dir.mkdir(parents=True, exist_ok=True)
    if write_to_pending:
        output_path = _chapter_output_path(book.chapters_dir, chapter_num, pending=True)
        output_path.parent.mkdir(exist_ok=True)
        if force_pending:
            print(f"  → 写入 _pending/ch{chapter_num}.md (等待作者定夺)")
        else:
            print(f"  → 写入 _pending/ch{chapter_num}.md (质量未达标)")
    else:
        output_path = _chapter_output_path(book.chapters_dir, chapter_num, pending=False)
    output_path.write_text(final_text, encoding="utf-8")

    # ---- Git commit: 初次生成 ----
    try:
        from biyu.git_helper import commit_chapter
        commit_hash = commit_chapter(book_dir, chapter_num, "初次生成", auto=True)
        print(f"  [git] 已提交: {commit_hash}")
    except Exception as e:
        print(f"  [git] 提交失败(warning): {e}")

    log_dir = book.chapter_log_dir(chapter_num)
    (log_dir / "planning.md").write_text(planning_text, encoding="utf-8")
    (log_dir / "skeleton.md").write_text(skeleton_text, encoding="utf-8")
    if polish_result:
        (log_dir / "polished.md").write_text(polish_result.polished_text, encoding="utf-8")
    # compute quality string outside f-string to avoid format specifier issues
    (log_dir / "meta.md").write_text(
        f"Chapter {chapter_num}\n"
        f"Word count: {final_count}\n"
        f"Cost: ¥{total_cost:.4f}\n"
        f"Latency: {total_latency:.1f}s\n"
        f"Stages: {stage_latencies}\n"
        f"Models: planner={planner_alias}, writer={writer_alias}, polisher={polisher_alias}\n"
        f"Pending: {write_to_pending}\n"
        f"Warnings: {warnings}\n"
        f"Consistency issues: {len(consistency_issues)}\n",
        encoding="utf-8",
    )

    # Also write meta.json for programmatic access
    import json
    meta_dict = {
        "chapter": chapter_num,
        "word_count": final_count,
        "cost_cny": total_cost,
        "prompt_tokens": {
            "architect": int(getattr(planning_resp, "prompt_tokens", 0) or 0),
            "writer": int(getattr(writer_resp, "prompt_tokens", 0) or 0),
            "architect_and_writer_total": int(
                (getattr(planning_resp, "prompt_tokens", 0) or 0)
                + (getattr(writer_resp, "prompt_tokens", 0) or 0)
            ),
        },
        "latency_seconds": total_latency,
        "stage_latencies": stage_latencies,
        "models": {"planner": planner_alias, "writer": writer_alias, "polisher": polisher_alias},
        "prompt_version": prompt_version,
        "polish_skipped": not polish_enabled,
        "warnings": warnings,
        "consistency_issues": len(consistency_issues),
        "pending": write_to_pending,
        "audit_warnings": audit_warnings,
        "north_star_source": north_star_source,
        "setup_versions": generation_setup_versions,
        "anchor_loop": anchor_loop_state,  # CutA: 早闸回流闭环状态(P6-A2-CutA)
    }
    (log_dir / "meta.json").write_text(
        json.dumps(meta_dict, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # ---- Record to SQLite ----
    record_chapter(
        book_dir,
        chapter_num=chapter_num,
        word_count=final_count,
        cost_cny=total_cost,
        latency_seconds=total_latency,
        warnings=warnings,
        consistency_issues=consistency_dicts,
    )

    # ---- Long-run metrics CSV (Phase 4) ----
    try:
        _dr = dash_result
    except NameError:
        _dr = None
    try:
        _write_long_run_csv(
            book_dir=book_dir,
            chapter_num=chapter_num,
            model=writer_alias,
            planning_resp=planning_resp,
            writer_resp=writer_resp,
            total_cost=total_cost,
            audit_results=audit_results,
            dash_result=_dr,
            final_count=final_count,
            context_block=context_block,
            final_text=final_text,
        )
    except Exception as e:
        print(f"  [long_run_csv] \u5199\u5165\u5931\u8d25(warning): {e}")

    # ---- Index chapter for RAG (if applicable) ----
    if context_mode == "rag":
        try:
            retriever.index_chapter(chapter_num, final_text)
        except Exception as e:
            warnings.append(f"RAG 索引失败(warning): {e}")
            print(f"  [RAG] 索引失败(warning): {e}")

    # ---- Build audit report (T-P3-C) ----
    try:
        from biyu.audit_reports.builder import build_audit_report
        # Convert audit_results to serializable dicts
        audit_dicts = [
            {"checker": ar.checker, "severity": ar.severity.value if hasattr(ar.severity, "value") else str(ar.severity), "message": ar.message}
            for ar in audit_results
        ]
        report_path = build_audit_report(
            book_dir, chapter_num,
            audit_results=audit_dicts,
            word_count=final_count,
            postproc_summary="",
            pending=write_to_pending,
            editor_section=editor_section,
        )
        print(f"  [audit_report] 已生成: {report_path}")
    except Exception as e:
        print(f"  [audit_report] 生成失败(warning): {e}")

    # ---- F-1~F-4: 必检项机器核对(只报不拦;H-1 后默认关,走配置开关) ----
    try:
        if registry.get_feature("checklist") and (use_existing_planning or planning_text.strip()):
            _checklist_result, _cl_warnings = await _run_checklist_with_cost_log(
                book=book,
                book_dir=book_dir,
                chapter_num=chapter_num,
                planning_text=planning_text,
                chapter_text=final_text,
                adapter=registry.get_adapter("v3"),
            )
            warnings.extend(_cl_warnings)
    except Exception as e:
        print(f"  [F-4] 必检项核对异常(warning): {e}")

    return ChapterResult(
        chapter_num=chapter_num,
        final_text=final_text,
        word_count=final_count,
        cost_cny=total_cost,
        latency_seconds=total_latency,
        stage_latencies=stage_latencies,
        warnings=warnings,
        planning_text=planning_text,
        skeleton_text=skeleton_text,
        polished_text=polish_result.polished_text if polish_result else "",
        audit_warnings=audit_warnings,
    )


def _get_v3_system_prompt() -> str:
    """Get the V3 system prompt."""
    from biyu.prompts.v3_opening import V3_OPENING_SYSTEM
    return V3_OPENING_SYSTEM
