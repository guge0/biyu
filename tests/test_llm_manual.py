"""手动测试：GLM-4.6、DeepSeek-V3、DeepSeek-R1 生成/流式 + 路由。"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from biyu.llm import ModelRegistry

# T7-2: 本文件是手动调试脚本(函数接受 registry 参数 + __main__ 入口),
# 不是 pytest 单测。pytest 误收集导致 3 errors(fixture 'registry' not found)。
# 标 manual marker + pyproject.toml addopts 默认 deselect。
# 显式跑:`pytest tests/test_llm_manual.py -m manual`(会因缺 fixture 失败,正常)。
pytestmark = pytest.mark.manual

console = Console()

PROMPT = "写一段100字的玄幻小说开头"
MESSAGES = [{"role": "user", "content": PROMPT}]


def _check_config() -> bool:
    config_path = Path(__file__).resolve().parents[1] / "config" / "models.yaml"
    if not config_path.exists():
        console.print("[red]config/models.yaml 不存在，请参考 models.yaml.example 创建[/red]")
        return False
    return True


async def _test_generate(registry: ModelRegistry, model_key: str, label: str, color: str) -> None:
    """测试非流式生成，显示输出、tokens和费用。"""
    console.rule(f"[bold {color}]{label} 生成测试")
    try:
        adapter = registry.get_adapter(model_key)
        resp = await adapter.generate(MESSAGES, temperature=0.7)
        # R1推理模型显示推理过程
        if resp.reasoning_content:
            console.print(Panel(
                resp.reasoning_content[:500] + ("..." if len(resp.reasoning_content) > 500 else ""),
                title=f"[dim]推理过程[/dim]",
                border_style="dim",
                style="dim",
            ))
        console.print(Panel(resp.text, title=f"{label} 输出", border_style=color))
        console.print(
            f"[dim]模型: {resp.model} | "
            f"Tokens: {resp.prompt_tokens}+{resp.completion_tokens}={resp.total_tokens} | "
            f"费用: ¥{resp.cost:.4f}[/dim]"
        )
    except Exception as e:
        console.print(f"[red]{label} 生成失败: {e}[/red]")


async def _test_stream(registry: ModelRegistry, model_key: str, label: str, color: str) -> None:
    """测试流式生成。"""
    console.rule(f"[bold {color}]{label} 流式测试")
    try:
        adapter = registry.get_adapter(model_key)
        console.print(f"[bold]提示: {PROMPT}[/bold]\n")
        collected = []
        async for chunk in adapter.stream(MESSAGES, temperature=0.7):
            console.print(chunk, end="", highlight=False)
            collected.append(chunk)
        console.print()
        console.print(f"[dim]共收到 {len(collected)} 个片段[/dim]")
    except Exception as e:
        console.print(f"[red]{label} 流式失败: {e}[/red]")


async def _test_routing(registry: ModelRegistry) -> None:
    """显示任务路由表。"""
    console.rule("[bold yellow]路由测试")
    table = Table(title="Task → Model")
    table.add_column("Task", style="yellow")
    table.add_column("Model", style="cyan")
    table.add_column("Adapter", style="green")
    for task in registry.available_tasks:
        try:
            adapter = registry.get_for_task(task)
            table.add_row(task, adapter.model_name, adapter.__class__.__name__)
        except Exception as e:
            table.add_row(task, "[red]ERROR[/red]", str(e))
    console.print(table)


async def main():
    console.print(Panel("[bold]笔驭 BiYu — LLM Adapter 手动测试[/bold]", border_style="blue"))

    if not _check_config():
        return

    try:
        registry = ModelRegistry()
    except Exception as e:
        console.print(f"[red]加载配置失败: {e}[/red]")
        return

    console.print(f"[dim]可用模型: {', '.join(registry.available_models)}[/dim]\n")

    # 路由表
    await test_routing(registry)

    # GLM-4.6 生成 + 流式
    await test_generate(registry, "glm-4.6", "GLM-4.6", "cyan")
    await test_stream(registry, "glm-4.6", "GLM-4.6", "magenta")

    # DeepSeek-V3 生成
    await test_generate(registry, "deepseek-v3", "DeepSeek-V3", "green")

    # DeepSeek-R1 生成（含推理过程）
    await test_generate(registry, "deepseek-r1", "DeepSeek-R1", "yellow")

    console.rule("[bold blue]测试完成")


if __name__ == "__main__":
    asyncio.run(main())
