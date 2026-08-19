"""V4-Pro adapter 最小包装 — 暴露同步接口给 fingerprint 模块."""
from __future__ import annotations

import asyncio
import json
import re

import httpx

from biyu.config import get_registry
from biyu.llm.base import resolve_env_vars


def _run_async(coro):
    """在同步 CLI 层包装 async 调用."""
    return asyncio.run(coro)


def _get_adapter_config() -> dict:
    """获取 V4-Pro 的 adapter 配置（provider + model 信息）."""
    registry = get_registry()
    alias = (
        "v4_pro"
        if "v4_pro" in registry.available_models
        else registry.get_pipeline_config().get("writer")
    )
    if not alias:
        raise KeyError("No v4_pro model or writer pipeline config")
    cfg = registry._resolve_model_config(alias)
    provider = cfg.get("provider", "deepseek")
    provider_cfg = registry._providers.get(provider, {})
    base_url = cfg.get("base_url", provider_cfg.get("base_url", "")).rstrip("/")
    api_key = cfg.get("api_key", provider_cfg.get("api_key", ""))
    model_id = cfg.get("model_name", "deepseek-v4-pro")
    max_tokens = cfg.get("max_tokens", 16384)
    cost_in = cfg.get("cost_per_1k_input", 0.0)
    cost_out = cfg.get("cost_per_1k_output", 0.0)
    return {
        "base_url": base_url,
        "api_key": api_key,
        "model_id": model_id,
        "max_tokens": max_tokens,
        "cost_per_1k_input": cost_in,
        "cost_per_1k_output": cost_out,
    }


def _estimate_cost(cost_in: float, cost_out: float, prompt_tokens: int, completion_tokens: int) -> float:
    return (prompt_tokens * cost_in + completion_tokens * cost_out) / 1000.0


def _extract_json_object(text: str) -> dict:
    """从 LLM 输出中提取 JSON 对象，处理常见的格式问题."""
    # 尝试找到第一个 { 和最后一个 } 之间的内容
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise json.JSONDecodeError("No JSON object found", text, 0)

    json_str = text[start:end + 1]

    # 尝试修复常见问题：
    # 1. 将中文引号替换为英文引号
    json_str = json_str.replace("\u201c", '"').replace("\u201d", '"')
    # 2. 将中文冒号替换为英文冒号（在键值对中）
    # json_str = json_str.replace("\uff1a", ":")  # 不要全局替换，可能影响中文内容

    # 尝试直接解析
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        pass

    # 尝试用正则修复：将裸露的换行符替换为 \\n
    try:
        fixed = re.sub(r'(?<!\\)\n(?=[^"]*(?:"[^"]*"[^"]*)*$)', '\\n', json_str)
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    # 最后手段：逐字符修复
    try:
        # 将 passage 值中的未转义换行替换为空格
        fixed_lines = []
        in_string = False
        escape = False
        for ch in json_str:
            if escape:
                fixed_lines.append(ch)
                escape = False
                continue
            if ch == '\\':
                fixed_lines.append(ch)
                escape = True
                continue
            if ch == '"' and not escape:
                in_string = not in_string
                fixed_lines.append(ch)
                continue
            if ch == '\n' and in_string:
                fixed_lines.append(' ')
                continue
            fixed_lines.append(ch)
        return json.loads("".join(fixed_lines))
    except json.JSONDecodeError as e:
        raise json.JSONDecodeError(
            f"Failed to parse JSON after all repair attempts: {e}",
            text, 0,
        )


async def _direct_generate(
    messages: list[dict],
    max_tokens: int = 3000,
    read_timeout: float = 300.0,
) -> tuple[str, dict]:
    """直接 httpx 调用 V4-Pro，支持自定义超时."""
    cfg = _get_adapter_config()
    url = f"{cfg['base_url']}/chat/completions"
    headers = {
        "Authorization": f"Bearer {cfg['api_key']}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": cfg["model_id"],
        "messages": messages,
        "max_tokens": max_tokens,
        "stream": False,
    }

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(connect=10.0, read=read_timeout, write=30.0, pool=10.0),
    ) as client:
        resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()

    choice = data["choices"][0]
    text = choice["message"].get("content", "")
    usage_data = data.get("usage", {})
    prompt_tokens = usage_data.get("prompt_tokens", 0)
    completion_tokens = usage_data.get("completion_tokens", 0)
    cost = _estimate_cost(cfg["cost_per_1k_input"], cfg["cost_per_1k_output"],
                          prompt_tokens, completion_tokens)

    return text, {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": usage_data.get("total_tokens", prompt_tokens + completion_tokens),
        "cost": cost,
        "model": data.get("model", cfg["model_id"]),
    }


async def generate(messages: list[dict], max_tokens: int = 3000) -> tuple[str, dict]:
    """调用 V4-Pro 生成文本。"""
    return await _direct_generate(messages, max_tokens, read_timeout=300.0)


async def generate_json(prompt: str, max_tokens: int = 8000) -> tuple[dict, dict]:
    """调用 V4-Pro 生成 JSON 输出。

    Args:
        prompt: 用户 prompt（单条消息）
        max_tokens: 最大 token 数

    Returns:
        (parsed_dict, usage_info)
    """
    messages = [{"role": "user", "content": prompt}]
    text, usage = await _direct_generate(messages, max_tokens, read_timeout=600.0)

    text = text.strip()
    # 剥离可能的 markdown 代码块
    if text.startswith("```"):
        first_newline = text.index("\n") + 1
        text = text[first_newline:]
        if text.endswith("```"):
            text = text[:-3].strip()

    # 尝试直接解析
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        # 如果失败，尝试提取第一个完整的 JSON 对象
        parsed = _extract_json_object(text)
    return parsed, usage


def generate_sync(messages: list[dict], max_tokens: int = 3000) -> tuple[str, dict]:
    """同步包装 — 供 evaluation 等模块直接调用."""
    return _run_async(generate(messages, max_tokens))
