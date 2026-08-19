"""Editor 主逻辑 — 调用 LLM 审稿 + function calling 工具查询。"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import yaml

from .parser import EditorResult, parse_editor_response, _extract_json
from .prompts import build_editor_system_prompt, build_editor_user_prompt
from .tools import (
    TOOL_DEFINITIONS,
    SUBMIT_REVIEW_SINGLE,
    EditorFailure,
    execute_tool,
)
from .tool_observer import (
    ToolObservation,
    ToolObserver,
    notify_tool_observer,
    query_text,
    result_matched,
)
from biyu.call_evidence import record_call_evidence

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# P7-8: UTF-8 FileHandler(治 P7-7 终端 GBK 拿不到干净 verbatim 的问题)
# ---------------------------------------------------------------------------

_EDITOR_FILE_HANDLER: logging.FileHandler | None = None


def _enable_editor_file_logging(log_path: Path | str | None = None) -> Path:
    """P7-8: 给 editor logger 加一个 UTF-8 FileHandler,绕过终端编码。

    P7-7 probe 发现:Windows 终端用 GBK 解码 UTF-8 字节,`logger.warning` 输出到
    stderr 后被 tee 写入 run.log 时中文乱码,污染 BAD_ARGUMENTS verbatim 诊断。
    本函数直接以 UTF-8 编码写文件,绕过终端。

    幂等性:默认路径(log_path=None)复用全局 handler,多次调用安全。
    自定义路径(测试用)每次创建新 handler,调用方负责清理。

    Args:
        log_path: 自定义日志文件路径;None 用默认 `data/.editor_logs/editor.log`。

    Returns:
        实际写入的 Path(创建失败时抛异常,符合 fail-fast 语义;调用方 try/except)。
    """
    global _EDITOR_FILE_HANDLER

    if log_path is None and _EDITOR_FILE_HANDLER is not None:
        return Path(_EDITOR_FILE_HANDLER.baseFilename)

    if log_path is None:
        from biyu.config import get_data_root

        path = get_data_root() / ".editor_logs" / "editor.log"
    else:
        path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(path, mode="a", encoding="utf-8")
    handler.setLevel(logging.WARNING)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s:%(lineno)d: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logger.addHandler(handler)

    if log_path is None:
        _EDITOR_FILE_HANDLER = handler

    return path

# ---------------------------------------------------------------------------
# Config: max_completion_tokens（reasoning + content 共享预算）
# ---------------------------------------------------------------------------

def _load_editor_max_tokens() -> int:
    """从 config/editor.yaml 读取 max_completion_tokens，默认 8192。

    P7-4 修路径 bug:parents[2] 指向 src/(不存在 src/config/),配置从未真生效;
    改为 parents[3] 指向项目根,匹配 config/editor.yaml 实际位置。
    P7-5 改出声:加载失败时 log.warning 含原因 + fallback 值,不许静默——
    旧版静默让路径 bug 失效 6 个月才被发现。
    """
    config_path = Path(__file__).parents[3] / "config" / "editor.yaml"
    try:
        with open(config_path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        return cfg.get("max_completion_tokens", 8192)
    except Exception as e:
        logger.warning(
            "editor.yaml 加载失败,fallback 到默认 max_completion_tokens=8192。"
            " 原因: %r (config_path=%s)。提示:配置改了但读到 fallback 值意味着"
            "路径或读取出错,需检查。",
            e, config_path,
        )
        return 8192


def _make_failure_result(failure: EditorFailure, chapter_text: str,
                         total_cost: float = 0.0,
                         queries_used: list[str] | None = None) -> EditorResult:
    """构造一个带 failure 标记的 EditorResult。"""
    result = EditorResult(raw_response="", parse_errors=[f"failure:{failure.value}"])
    result.queries_used = queries_used or []
    result.cost = total_cost
    return result


def _try_json_repair(args_str: str, tool_name: str, *, context: str = "tool_call") -> dict | None:
    """P7-8: json_repair 兜底修复畸形 JSON arguments。

    在 `json.loads` 失败时调用。覆盖 P7-7 实测的 BAD_ARGUMENTS 主流根因:
    confidence 字段忘加引号 / 值里未转义 ASCII 引号 / 缺逗号 等。

    红线松绑(P7-8,老板指令):
    - P7-4 "不许猜测/强转" 在 P7-8 部分松绑——json_repair 类型的标准化修复允许。
    - 仍保留:json_repair 不是万能,完全无结构的乱码它也修不好(返 None,调用方走原 BAD_ARGUMENTS 路径)。
    - 修复动作必须进 WARNING 日志(原文 + 修复后 + 是否成功),不静默。

    Args:
        args_str: 原始 arguments 字符串(json.loads 失败的那个)。
        tool_name: 工具名(submit_review / look_up_*)。
        context: 日志上下文标记("tool_call" 或 "submit_review")。

    Returns:
        dict:修复成功且解析为 dict 时返回。
        None:修复失败 / 修复后非 dict / json_repair 不可用。
    """
    try:
        from json_repair import repair_json
    except ImportError:
        logger.warning(
            "json_repair not installed; cannot repair malformed %s args (tool=%s). "
            "Original=%r",
            context, tool_name, args_str,
        )
        return None

    try:
        repaired_str = repair_json(args_str, return_objects=False)
    except Exception as e:
        logger.warning(
            "json_repair raised on %s args (tool=%s): %r. Original=%r",
            context, tool_name, e, args_str,
        )
        return None

    try:
        repaired_parsed = json.loads(repaired_str)
    except json.JSONDecodeError:
        logger.warning(
            "json_repair could not produce valid JSON for %s args (tool=%s). "
            "Original=%r Repaired=%r",
            context, tool_name, args_str, repaired_str,
        )
        return None

    if not isinstance(repaired_parsed, dict):
        logger.warning(
            "json_repair produced non-dict for %s args (tool=%s): type=%s. "
            "Original=%r Repaired=%r",
            context, tool_name, type(repaired_parsed).__name__, args_str, repaired_str,
        )
        return None

    # P7-8 安全网:json_repair 对完全乱码(无 JSON 结构)的默认行为是返空 dict `{}`。
    # 这会让 submit_review 把"LLM 完全乱码"当成"LLM 提交了空 issues 列表"通过,
    # 违反"完全乱码仍应 BAD_ARGUMENTS"的安全网。判定:修复后空 dict 时,
    # 只有原文以 `{` 开头(LLM 至少试图给 JSON 对象)才接受;否则视为乱码返 None。
    stripped_original = args_str.strip()
    if not repaired_parsed and not stripped_original.startswith("{"):
        logger.warning(
            "json_repair produced empty dict but original is non-JSON garbage "
            "(tool=%s context=%s). Rejecting repair. Original=%r",
            tool_name, context, args_str,
        )
        return None

    logger.warning(
        "json_repair repaired malformed %s args (tool=%s). "
        "Original=%r Repaired=%r",
        context, tool_name, args_str, repaired_str,
    )
    return repaired_parsed


def _safe_parse_tool_args(args_str: str, tool_name: str) -> dict:
    """安全解析工具调用 arguments JSON。

    P7-8: 在 `json.loads` 失败时,先尝试 `json_repair` 兜底修复主流畸形
    (confidence 忘加引号、未转义引号、缺逗号)。修复后仍失败才返空 dict。

    失败时记 WARNING 日志含**完整 verbatim 原文**(不截断、不猜测),
    返回空 dict 让 execute_tool 自然返 BAD_ARGUMENTS 给 LLM。

    红线(P7-4 → P7-8 松绑):
    - P7-4 "不许猜测/强转" → P7-8 允许 json_repair 类型的标准化修复(补引号 / 转义 / 补逗号)。
    - 仍保留:"完全无结构乱码"(json_repair 也修不好)→ 仍返 {},不人手猜测。
    """
    try:
        parsed = json.loads(args_str)
        if isinstance(parsed, dict):
            return parsed
        logger.warning(
            "tool_call arguments not a JSON object (tool=%s): %s",
            tool_name, args_str,
        )
        return {}
    except json.JSONDecodeError:
        # P7-8: 先尝试 json_repair 兜底修复
        repaired = _try_json_repair(args_str, tool_name, context="tool_call")
        if repaired is not None:
            return repaired
        # json_repair 也修不好 → 原行为(返空 dict)
        logger.warning(
            "tool_call arguments JSON parse failed, unrepairable (tool=%s): %s",
            tool_name, args_str,
        )
        return {}


def _parse_submit_review_call(submit_call: dict, chapter_text: str,
                               total_cost: float,
                               queries_used: list[str],
                               *,
                               has_approved_planning: bool = False,
                               approved_planning_text: str = "") -> EditorResult:
    """解析 submit_review 工具调用的 arguments，返回 EditorResult。

    如果 arguments JSON 解析失败，返回 RUN_FAIL failure result。
    """
    args_str = submit_call["function"]["arguments"]
    try:
        args = json.loads(args_str)
    except json.JSONDecodeError:
        logger.error("submit_review arguments JSON parse failed: %s", args_str[:200])
        return _make_failure_result(EditorFailure.BAD_ARGUMENTS, chapter_text, total_cost, queries_used)

    # 将 submit_review 的 issues + confidence 包装成 parse_editor_response 期望的 JSON
    data = {
        "issues": args.get("issues", []),
        "queries_used": queries_used,
        "confidence": args.get("confidence", "medium"),
    }
    fake_json = json.dumps(data, ensure_ascii=False)
    result = parse_editor_response(
        fake_json,
        chapter_text,
        has_approved_planning=has_approved_planning,
        approved_planning_text=approved_planning_text,
    )
    result.queries_used = queries_used
    result.cost = total_cost
    return result


async def review_chapter(
    chapter_num: int,
    chapter_text: str,
    book_dir: Path,
    adapter,  # LLMAdapter
    *,
    characters_summary: str = "",
    prev_chapter_tail: str = "",
    planning: str = "",
    has_approved_planning: bool = False,
    max_tool_rounds: int = 5,
    injection_v2: bool = False,
    creative_anchor: str = "",
    lookup_catalog: str = "",
    tool_observer: ToolObserver | None = None,
) -> EditorResult:
    """Editor 审稿：调用 LLM + function calling 工具查询。

    Args:
        chapter_num: 章节号。
        chapter_text: 章节正文。
        book_dir: 书目录。
        adapter: LLMAdapter 实例（DeepSeek V4-Pro）。
        characters_summary: 角色速查文本。
        prev_chapter_tail: 上一章末 500 字。
        planning: 规划件全文(已批的 planning.md 内容),用于规划履约检查。
        has_approved_planning: 是否存在经管线确定性判定的已批规划件。
        max_tool_rounds: 最大工具调用轮数。
        injection_v2: 是否启用 Q-1 注入分档。
        creative_anchor: 开启分档时预注入的创作锚点全文。
        lookup_catalog: 人物、世界观与历史的目录档文本。
        tool_observer: 每次本地 lookup 执行后的观察回调。

    Returns:
        EditorResult
    """
    system_prompt = build_editor_system_prompt(
        has_approved_planning=has_approved_planning,
    )
    user_prompt = build_editor_user_prompt(
        chapter_num=chapter_num,
        chapter_text=chapter_text,
        characters_summary=characters_summary,
        prev_chapter_tail=prev_chapter_tail,
        planning=planning,
        injection_v2=injection_v2,
        creative_anchor=creative_anchor,
        lookup_catalog=lookup_catalog,
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    # 多轮对话：LLM 调用 → 检查 tool_calls → 执行工具 → 继续对话
    queries_used: list[str] = []
    total_cost = 0.0
    max_completion_tokens = _load_editor_max_tokens()
    submit_retry_used = False  # P7-4: submit_review args 坏时,给 LLM 一次重试机会

    for round_num in range(max_tool_rounds + 1):
        # 前 N 轮给 lookup tools + submit_review；收尾轮只给 submit_review
        if round_num < max_tool_rounds:
            payload_tools = TOOL_DEFINITIONS + [SUBMIT_REVIEW_SINGLE]
        else:
            payload_tools = [SUBMIT_REVIEW_SINGLE]
            # P7-9: 收尾轮注入技术指令(独立于 EDITOR_SYSTEM_PROMPT 创作内容)。
            # 协议级强制 LLM 调 submit_review;非创作 prompt,原文进 delivery report 等老板过目。
            messages.append({
                "role": "user",
                "content": (
                    "【系统提示·最后一轮】这是最后一轮,不再允许查询工具。"
                    "请立即调用 submit_review 工具提交审读结果;"
                    "如果未发现 issue,也必须提交空审读(issues=[])。"
                ),
            })

        resp = await adapter.generate(
            messages,
            temperature=0.1,
            max_tokens=max_completion_tokens,
            tools=payload_tools,
        )
        if injection_v2:
            record_call_evidence(
                role="editor", chapter_num=chapter_num, round_num=round_num + 1,
                messages=messages, response=resp,
                final_round=round_num == max_tool_rounds,
            )
        total_cost += resp.cost
        resp_text = resp.text

        # 检查 finish_reason=length → TRUNCATION
        if getattr(resp, "finish_reason", None) == "length":
            logger.warning("Response truncated (finish_reason=length)")
            return _make_failure_result(EditorFailure.TRUNCATION, chapter_text, total_cost, queries_used)

        # 从标准 OpenAI 格式提取 tool_calls
        tool_calls = []
        if resp.raw is not None:
            choices = resp.raw.get("choices", [])
            if choices:
                message = choices[0].get("message", {})
                tool_calls = message.get("tool_calls") or []

        # 检查是否含 submit_review 调用
        submit_call = next(
            (tc for tc in tool_calls if tc["function"]["name"] == "submit_review"),
            None,
        )
        if submit_call:
            submit_args_str = submit_call["function"].get("arguments", "")
            try:
                # 仅测试可解析性;解析过的 args_str 在 _parse_submit_review_call 内部再 loads
                json.loads(submit_args_str)
            except json.JSONDecodeError:
                # P7-8: 先 json_repair 兜底修复(治 P7-7 实测 50% BAD_ARGUMENTS)
                repaired_args = _try_json_repair(
                    submit_args_str, "submit_review", context="submit_review",
                )
                if repaired_args is not None:
                    # 修复成功:用修复后的合法 JSON 替换 arguments,走正常解析路径
                    submit_call = {
                        **submit_call,
                        "function": {
                            **submit_call["function"],
                            "arguments": json.dumps(repaired_args, ensure_ascii=False),
                        },
                    }
                    return _parse_submit_review_call(
                        submit_call, chapter_text, total_cost, queries_used,
                        has_approved_planning=has_approved_planning,
                        approved_planning_text=planning if has_approved_planning else "",
                    )

                # P7-4 路径:json_repair 修不好 → 记 verbatim + 给 LLM 一次重试机会
                logger.error(
                    "submit_review arguments JSON parse failed (unrepairable) "
                    "(round=%d retry_used=%s): %s",
                    round_num, submit_retry_used, submit_args_str,
                )
                # 给 LLM 一次重试机会(且当前轮非 final 才有下一轮可重试)
                if not submit_retry_used and round_num < max_tool_rounds:
                    submit_retry_used = True
                    assistant_msg = {
                        "role": "assistant",
                        "content": resp_text,
                        "tool_calls": [submit_call],
                    }
                    if resp.reasoning_content:
                        assistant_msg["reasoning_content"] = resp.reasoning_content
                    messages.append(assistant_msg)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": submit_call.get("id", ""),
                        "name": "submit_review",
                        "content": json.dumps({
                            "error": "BAD_ARGUMENTS",
                            "message": "arguments JSON parse failed. "
                                       "Re-call submit_review with valid JSON arguments.",
                        }, ensure_ascii=False),
                    })
                    continue
                # 重试用过 或 final round → BAD_ARGUMENTS failure
                return _make_failure_result(
                    EditorFailure.BAD_ARGUMENTS, chapter_text, total_cost, queries_used
                )
            return _parse_submit_review_call(
                submit_call,
                chapter_text,
                total_cost,
                queries_used,
                has_approved_planning=has_approved_planning,
                approved_planning_text=planning if has_approved_planning else "",
            )

        # 非 submit_review 的工具调用，照常执行
        if not tool_calls:
            # 无工具调用也无 submit_review → 收尾轮是 RUN_FAIL，非收尾轮继续
            if round_num == max_tool_rounds:
                return _make_failure_result(EditorFailure.RUN_FAIL, chapter_text, total_cost, queries_used)
            # 非收尾轮但无工具调用：LLM 给了纯文本，视为提前结束但没调 submit_review
            return _make_failure_result(EditorFailure.RUN_FAIL, chapter_text, total_cost, queries_used)

        # 执行 lookup 工具调用
        assistant_msg = {"role": "assistant", "content": resp_text, "tool_calls": tool_calls}
        if resp.reasoning_content:
            assistant_msg["reasoning_content"] = resp.reasoning_content
        messages.append(assistant_msg)

        for tc in tool_calls:
            tool_name = tc["function"]["name"]
            tc_id = tc.get("id", "")
            # P7-4: 用 _safe_parse_tool_args 替代裸 try/except,记 verbatim 不静默吞
            tool_args = _safe_parse_tool_args(tc["function"].get("arguments", ""), tool_name)

            tool_result = execute_tool(tool_name, tool_args, book_dir)
            queries_used.append(f"{tool_name}({json.dumps(tool_args, ensure_ascii=False)})")
            notify_tool_observer(
                tool_observer,
                ToolObservation(
                    response_group=f"single:{round_num + 1}",
                    tool_name=tool_name,
                    query=query_text(tool_name, tool_args),
                    result=tool_result,
                    matched=result_matched(tool_name, tool_result),
                    query_index=len(queries_used),
                    response_round=round_num + 1,
                    response_prompt_tokens=int(getattr(resp, "prompt_tokens", 0) or 0),
                    response_completion_tokens=int(getattr(resp, "completion_tokens", 0) or 0),
                    response_total_tokens=int(getattr(resp, "total_tokens", 0) or 0),
                    response_cost=float(getattr(resp, "cost", 0.0) or 0.0),
                    response_tool_call_count=len(tool_calls),
                ),
            )

            messages.append({
                "role": "tool",
                "tool_call_id": tc_id,
                "name": tool_name,
                "content": tool_result,
            })

    # 循环结束但未返回 → 收尾轮未调 submit_review
    return _make_failure_result(EditorFailure.RUN_FAIL, chapter_text, total_cost, queries_used)
