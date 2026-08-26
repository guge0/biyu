"""Multi-agent Editor 编排器 — 3-agent Blind Peer Review。

Editor-A 网文编辑 / Editor-B 角色顾问 / Editor-C 设定审计
两阶段：Phase 1 独立审稿 → Phase 2 反思校准 → Phase 3 投票合并
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

import yaml

from .merge import merge_issues, render_audit_report
from .parser import _extract_json
from .schema import AgentIssue, AgentIssueList, MergeResult
from .tools import (
    EditorFailure,
    SUBMIT_REVIEW_AGENT,
    execute_tool,
    get_tools_for_agent,
)
from .tool_observer import (
    ToolObservation,
    ToolObserver,
    notify_tool_observer,
    query_text,
    result_matched,
)
from biyu.call_evidence import record_call_evidence

# Prompt imports
from .agent_prompts.editor_a import EDITOR_A_SYSTEM_PROMPT
from .agent_prompts.editor_b import EDITOR_B_SYSTEM_PROMPT
from .agent_prompts.editor_c import EDITOR_C_SYSTEM_PROMPT
from .agent_prompts.reflection import build_reflection_prompt

AGENT_PROMPTS = {
    "A": EDITOR_A_SYSTEM_PROMPT,
    "B": EDITOR_B_SYSTEM_PROMPT,
    "C": EDITOR_C_SYSTEM_PROMPT,
}


# ---------------------------------------------------------------------------
# 配置加载
# ---------------------------------------------------------------------------

_EDITOR_CONFIG_CACHE: dict[str, Any] | None = None


def load_editor_config() -> dict[str, Any]:
    """加载 editor.yaml 配置，带简单缓存。"""
    global _EDITOR_CONFIG_CACHE
    if _EDITOR_CONFIG_CACHE is not None:
        return _EDITOR_CONFIG_CACHE

    config_path = Path(__file__).parents[3] / "config" / "editor.yaml"
    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            _EDITOR_CONFIG_CACHE = yaml.safe_load(f) or {}
    else:
        logger.warning("editor.yaml not found at %s, falling back to single mode", config_path)
        _EDITOR_CONFIG_CACHE = {"mode": "single"}

    return _EDITOR_CONFIG_CACHE


def clear_config_cache() -> None:
    """清除配置缓存（测试用）。"""
    global _EDITOR_CONFIG_CACHE
    _EDITOR_CONFIG_CACHE = None


# ---------------------------------------------------------------------------
# Phase 1: 独立审稿
# ---------------------------------------------------------------------------

async def _run_agent_phase1(
    agent_id: str,
    chapter_num: int,
    chapter_text: str,
    book_dir: Path,
    adapter: Any,
    config: dict[str, Any],
    prev_chapter_tail: str,
    *,
    injection_v2: bool = False,
    creative_anchor: str = "",
    lookup_catalog: str = "",
    tool_observer: ToolObserver | None = None,
) -> tuple[AgentIssueList, float]:
    """运行单个 agent 的 Phase 1。

    Returns:
        (AgentIssueList, cost)
    """
    system_prompt = AGENT_PROMPTS[agent_id]
    allowed_tools = get_tools_for_agent(agent_id)
    max_tool_calls = config.get("agents", {}).get("max_tool_calls_per_agent_phase1", 3)
    max_issues = config.get("agents", {}).get("max_issues_per_agent", 8)

    # 构建 user prompt
    parts = [f"请审阅第 {chapter_num} 章正文：\n"]
    if prev_chapter_tail:
        if injection_v2:
            parts.append("--- 上一章结尾(若本章另起新场景,可不接续) ---")
        else:
            parts.append("--- 上一章末 500 字 ---")
        parts.append(prev_chapter_tail)
        parts.append("--- 本章正文 ---\n")
    parts.append(chapter_text)
    if injection_v2 and creative_anchor:
        parts.append("--- 创作锚点 ---")
        parts.append(creative_anchor)
    if injection_v2 and lookup_catalog:
        parts.append("--- 以下只是清单,要用再查,不必全查 ---")
        parts.append(lookup_catalog)
    user_prompt = "\n".join(parts)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    total_cost = 0.0
    query_index = 0
    max_completion_tokens = config.get("max_completion_tokens", 8192)

    for round_num in range(max_tool_calls + 1):
        # 前 N 轮给 lookup tools + submit_review；收尾轮只给 submit_review
        if round_num < max_tool_calls:
            payload_tools = allowed_tools + [SUBMIT_REVIEW_AGENT]
        else:
            payload_tools = [SUBMIT_REVIEW_AGENT]

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
                final_round=round_num == max_tool_calls,
            )
        total_cost += resp.cost
        resp_text = resp.text

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
            issue_list = _parse_submit_review(submit_call, agent_id, 1, chapter_num, max_issues)
            return issue_list, total_cost

        # 非 submit_review 的工具调用，照常执行
        if not tool_calls:
            # 无工具调用也无 submit_review
            if round_num == max_tool_calls:
                # 收尾轮不调 submit_review → 返回空列表
                logger.warning("Phase1 agent-%s: final round without submit_review", agent_id)
                return AgentIssueList(agent=agent_id, phase=1, chapter=chapter_num), total_cost
            # 非收尾轮无工具调用但无 submit_review → 也返回空
            return AgentIssueList(agent=agent_id, phase=1, chapter=chapter_num), total_cost

        # 执行 lookup 工具调用
        assistant_msg = {"role": "assistant", "content": resp_text, "tool_calls": tool_calls}
        if resp.reasoning_content:
            assistant_msg["reasoning_content"] = resp.reasoning_content
        messages.append(assistant_msg)

        for tc in tool_calls:
            tool_name = tc["function"]["name"]
            tc_id = tc.get("id", "")
            try:
                tool_args = json.loads(tc["function"]["arguments"])
            except json.JSONDecodeError:
                tool_args = {}

            tool_result = execute_tool(tool_name, tool_args, book_dir)
            query_index += 1
            notify_tool_observer(
                tool_observer,
                ToolObservation(
                    response_group=f"agent-{agent_id}:{round_num + 1}",
                    tool_name=tool_name,
                    query=query_text(tool_name, tool_args),
                    result=tool_result,
                    matched=result_matched(tool_name, tool_result),
                    query_index=query_index,
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

    # 循环结束但未返回
    return AgentIssueList(agent=agent_id, phase=1, chapter=chapter_num), total_cost


# ---------------------------------------------------------------------------
# Phase 2: 反思校准
# ---------------------------------------------------------------------------

async def _run_agent_phase2(
    agent_id: str,
    chapter_num: int,
    adapter: Any,
    own_v1: AgentIssueList,
    peer_v1s: list[AgentIssueList],
    config: dict[str, Any],
    *,
    injection_v2: bool = False,
) -> tuple[AgentIssueList, float]:
    """运行单个 agent 的 Phase 2 反思。

    关键隔离：函数签名只接受 own_v1 + peer_v1s，v2 数据在作用域内不存在。
    Phase 2 传 submit_review 作为唯一工具。

    Returns:
        (AgentIssueList, cost)
    """
    max_issues = config.get("agents", {}).get("max_issues_per_agent", 8)

    # 构建 prompt
    own_json = own_v1.to_json()
    peer_jsons = [p.to_json() for p in peer_v1s]
    system_prompt, user_prompt = build_reflection_prompt(
        agent_id=agent_id,
        chapter_num=chapter_num,
        own_v1_json=own_json,
        peer_v1_jsons=peer_jsons,
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    # Phase 2 传 submit_review 作为唯一工具
    max_completion_tokens = config.get("max_completion_tokens", 8192)
    resp = await adapter.generate(
        messages,
        temperature=0.1,
        max_tokens=max_completion_tokens,
        tools=[SUBMIT_REVIEW_AGENT],
    )
    if injection_v2:
        record_call_evidence(
            role="editor", chapter_num=chapter_num, round_num=1,
            messages=messages, response=resp, final_round=True,
        )
    total_cost = resp.cost

    # 检查 submit_review 调用
    tool_calls = []
    if resp.raw is not None:
        choices = resp.raw.get("choices", [])
        if choices:
            message = choices[0].get("message", {})
            tool_calls = message.get("tool_calls") or []

    submit_call = next(
        (tc for tc in tool_calls if tc["function"]["name"] == "submit_review"),
        None,
    )
    if submit_call:
        return _parse_submit_review(submit_call, agent_id, 2, chapter_num, max_issues), total_cost

    # 未调 submit_review → 返回空列表
    logger.warning("Phase2 agent-%s: no submit_review call", agent_id)
    return AgentIssueList(agent=agent_id, phase=2, chapter=chapter_num), total_cost


# ---------------------------------------------------------------------------
# submit_review 解析
# ---------------------------------------------------------------------------

def _parse_submit_review(
    submit_call: dict,
    agent_id: str,
    phase: int,
    chapter_num: int,
    max_issues: int,
) -> AgentIssueList:
    """解析 submit_review 工具调用的 arguments，返回 AgentIssueList。

    如果 arguments JSON 解析失败，返回空 AgentIssueList。
    """
    args_str = submit_call["function"]["arguments"]
    try:
        args = json.loads(args_str)
    except json.JSONDecodeError:
        logger.error("agent-%s phase%d: submit_review arguments JSON parse failed", agent_id, phase)
        return AgentIssueList(agent=agent_id, phase=phase, chapter=chapter_num)

    raw_issues = args.get("issues", [])
    if not isinstance(raw_issues, list):
        return AgentIssueList(agent=agent_id, phase=phase, chapter=chapter_num)

    issues: list[AgentIssue] = []
    for raw in raw_issues:
        if not isinstance(raw, dict):
            continue
        issue = AgentIssue.from_dict(raw)
        # 校验 type
        errors = issue.validate(agent_id)
        if errors:
            continue  # 越界 type 被拒绝
        issues.append(issue)

    # 限制 issue 数量
    if len(issues) > max_issues:
        issues = issues[:max_issues]

    return AgentIssueList(agent=agent_id, phase=phase, chapter=chapter_num, issues=issues)


# ---------------------------------------------------------------------------
# 旧 _parse_agent_response 保留（兼容旧的直接 JSON 输入）
# ---------------------------------------------------------------------------

def _parse_agent_response(
    raw_text: str,
    agent_id: str,
    phase: int,
    chapter_num: int,
    max_issues: int,
) -> AgentIssueList:
    """解析 agent 的 JSON 响应为 AgentIssueList。

    注意：新流程中 LLM 通过 submit_review 工具提交，此函数仅作为
    回退/兼容入口使用。不再尝试 _repair_json。
    """
    json_str = _extract_json(raw_text)
    if not json_str:
        return AgentIssueList(agent=agent_id, phase=phase, chapter=chapter_num)

    data = None
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        # 不再修复，直接返回空
        return AgentIssueList(agent=agent_id, phase=phase, chapter=chapter_num)

    raw_issues = data.get("issues", [])
    if not isinstance(raw_issues, list):
        return AgentIssueList(agent=agent_id, phase=phase, chapter=chapter_num)

    issues: list[AgentIssue] = []
    for raw in raw_issues:
        if not isinstance(raw, dict):
            continue
        issue = AgentIssue.from_dict(raw)
        # 校验 type
        errors = issue.validate(agent_id)
        if errors:
            continue  # 越界 type 被拒绝
        issues.append(issue)

    # 限制 issue 数量
    if len(issues) > max_issues:
        issues = issues[:max_issues]

    return AgentIssueList(agent=agent_id, phase=phase, chapter=chapter_num, issues=issues)


# ---------------------------------------------------------------------------
# 核心编排
# ---------------------------------------------------------------------------

async def review_chapter_multi_agent(
    chapter_num: int,
    chapter_text: str,
    book_dir: Path,
    adapter: Any,
    *,
    prev_chapter_tail: str = "",
    injection_v2: bool = False,
    creative_anchor: str = "",
    lookup_catalog: str = "",
    tool_observer: ToolObserver | None = None,
) -> MergeResult:
    """多 Agent 审稿主入口。

    流程：
    1. Phase 1: 3 agent 并行独立审稿
    2. Phase 1 后检查成本，超限则 fallback
    3. Phase 2: 3 agent 并行反思校准
    4. Phase 3: 纯代码投票合并

    Args:
        chapter_num: 章节号。
        chapter_text: 章节正文。
        book_dir: 书目录。
        adapter: LLMAdapter 实例。
        prev_chapter_tail: 上一章末 500 字。
        injection_v2: 是否启用 Q-1 注入分档。
        creative_anchor: 开启分档时预注入的创作锚点全文。
        lookup_catalog: 人物、世界观与历史的目录档文本。
        tool_observer: 每次本地 lookup 执行后的观察回调。

    Returns:
        MergeResult
    """
    config = load_editor_config()
    agent_cfg = config.get("agents", {})
    fallback_threshold = config.get("fallback_threshold_yuan_per_chapter", 0.05)
    fallback_on_budget = config.get("fallback_on_budget_exceed", True)

    # ---- Phase 1: Compose ----
    phase1_tasks = {
        aid: _run_agent_phase1(
            agent_id=aid,
            chapter_num=chapter_num,
            chapter_text=chapter_text,
            book_dir=book_dir,
            adapter=adapter,
            config=config,
            prev_chapter_tail=prev_chapter_tail,
            injection_v2=injection_v2,
            creative_anchor=creative_anchor,
            lookup_catalog=lookup_catalog,
            tool_observer=tool_observer,
        )
        for aid in ("A", "B", "C")
    }

    phase1_results = await asyncio.gather(*phase1_tasks.values())
    v1_lists: dict[str, AgentIssueList] = {}
    total_cost = 0.0
    for aid, (issue_list, cost) in zip(phase1_tasks.keys(), phase1_results):
        v1_lists[aid] = issue_list
        total_cost += cost

    # Phase 1 trace logging (diagnostic only)
    _dump_phase_trace("phase1", v1_lists, chapter_num, book_dir=book_dir)

    # Phase 1 后成本检查
    if fallback_on_budget and total_cost > fallback_threshold:
        # 超限 fallback：用 v1 直接 merge，跳过 Phase 2
        result = merge_issues(v1_lists)
        result.total_cost = total_cost
        result.fallback_used = True
        return result

    # ---- Phase 2: Review（反思校准）----
    phase2_tasks = {}
    for aid in ("A", "B", "C"):
        own_v1 = v1_lists[aid]
        peer_v1s = [v1_lists[p] for p in ("A", "B", "C") if p != aid]
        phase2_tasks[aid] = _run_agent_phase2(
            agent_id=aid,
            chapter_num=chapter_num,
            adapter=adapter,
            own_v1=own_v1,
            peer_v1s=peer_v1s,
            config=config,
            injection_v2=injection_v2,
        )

    phase2_results = await asyncio.gather(*phase2_tasks.values())
    v2_lists: dict[str, AgentIssueList] = {}
    for aid, (issue_list, cost) in zip(phase2_tasks.keys(), phase2_results):
        v2_lists[aid] = issue_list
        total_cost += cost

    # Phase 2 trace logging (diagnostic only)
    _dump_phase_trace("phase2", v2_lists, chapter_num, book_dir=book_dir)

    # ---- Phase 3: Merge ----
    result = merge_issues(v2_lists)
    result.total_cost = total_cost
    return result


# ---------------------------------------------------------------------------
# Phase trace logging helper (diagnostic only)
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)

def _dump_phase_trace(
    phase_name: str,
    agent_lists: dict[str, AgentIssueList],
    chapter_num: int,
    *,
    book_dir: Path,
) -> None:
    """Dump per-agent issue counts and full JSON under the owning book.

    This is a logging-only helper. It does not modify any state.
    Output: <book_dir>/phase_trace/{phase_name}_trace_{timestamp}.json
    """
    ts = time.strftime("%Y%m%d_%H%M%S")
    trace_data = {
        "phase": phase_name,
        "chapter": chapter_num,
        "timestamp": ts,
        "agents": {},
    }
    for aid, issue_list in agent_lists.items():
        trace_data["agents"][aid] = {
            "issue_count": len(issue_list.issues),
            "issues": [i.to_dict() for i in issue_list.issues],
        }

    logger.info(
        "[%s] ch%d agent issue counts: %s",
        phase_name,
        chapter_num,
        {aid: len(il.issues) for aid, il in agent_lists.items()},
    )

    try:
        phase_trace_dir = Path(book_dir).resolve() / "phase_trace"
        phase_trace_dir.mkdir(parents=True, exist_ok=True)
        out_path = phase_trace_dir / f"{phase_name}_trace_{ts}.json"
        out_path.write_text(
            json.dumps(trace_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("[%s] trace saved to %s", phase_name, out_path)
    except Exception as exc:
        logger.warning("[%s] failed to save trace: %s", phase_name, exc)
