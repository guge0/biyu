"""Fingerprint CLI 子命令 — extract / write / validate / blind-test / multi-genre-test."""
from __future__ import annotations

import json
import sys

import typer
from rich.console import Console
from rich.table import Table

console = Console()
fingerprint_app = typer.Typer(help="声纹学习：提取作者风格指纹，用声纹写新内容")


@fingerprint_app.command()
def extract(
    source: str = typer.Option(..., "--source", "-s", help="源文本路径（文件或目录）"),
    output: str = typer.Option(..., "--output", "-o", help="输出 JSON 路径"),
    sample_size: int = typer.Option(8000, "--sample-size", help="采样目标字数"),
) -> None:
    """从源文本提取声纹。"""
    from biyu.fingerprint.extractor import extract_fingerprint

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    console.print(f"[cyan]提取声纹中...[/cyan] 源: {source}")

    fingerprint, usage = extract_fingerprint(
        source_path=source,
        output_path=output,
        sample_size=sample_size,
    )

    console.print(f"[green]声纹已保存到[/green] {output}")
    console.print(f"  总字数: {fingerprint.source_info.total_chars}")
    console.print(f"  采样字数: {fingerprint.source_info.sampled_chars}")
    console.print(f"  采样方法: {fingerprint.source_info.sampling_method}")
    console.print(f"  风格描述长度: {len(fingerprint.style_description)} 字")
    console.print(f"  代表段落: {len(fingerprint.exemplar_passages)} 段")
    console.print(f"  AI雷区: {len(fingerprint.ai_pitfalls)} 条")
    console.print(f"  成本: ¥{usage.get('cost', 0):.4f}")


@fingerprint_app.command()
def write(
    fingerprint: str = typer.Option(..., "--fingerprint", "-f", help="声纹 JSON 路径"),
    prompt: str = typer.Option(..., "--prompt", "-p", help="写作请求"),
    output: str = typer.Option(None, "--output", "-o", help="输出文件路径"),
    max_words: int = typer.Option(1500, "--max-words", help="最大字数"),
) -> None:
    """用声纹写新内容。"""
    from biyu.fingerprint.writer import write_with_fingerprint

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    console.print("[cyan]写作中...[/cyan]")

    text, usage = write_with_fingerprint(
        fingerprint_path=fingerprint,
        user_prompt=prompt,
        output_path=output,
        max_words=max_words,
    )

    console.print(f"[green]写作完成[/green] ({len(text)} 字)")
    if output:
        console.print(f"  已保存到: {output}")
    else:
        console.print(text)
    console.print(f"  成本: ¥{usage.get('cost', 0):.4f}")


@fingerprint_app.command()
def validate(
    fingerprint: str = typer.Option(..., "--fingerprint", "-f", help="声纹 JSON 路径"),
) -> None:
    """校验声纹 JSON schema + 估算后续调用成本。"""
    from biyu.fingerprint.schema import Fingerprint
    from biyu.fingerprint.writer import load_fingerprint

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    try:
        fp = load_fingerprint(fingerprint)
    except Exception as e:
        console.print(f"[red]校验失败[/red]: {e}")
        raise typer.Exit(1)

    # 校验字段
    errors = []
    if not (400 <= len(fp.style_description) <= 3000):
        errors.append(f"style_description 长度 {len(fp.style_description)} 不在 400-3000 范围")
    if not (5 <= len(fp.exemplar_passages) <= 8):
        errors.append(f"exemplar_passages 数量 {len(fp.exemplar_passages)} 不在 5-8 范围")
    if not (5 <= len(fp.ai_pitfalls) <= 10):
        errors.append(f"ai_pitfalls 数量 {len(fp.ai_pitfalls)} 不在 5-10 范围")

    # 检查 why_* 字段
    for i, p in enumerate(fp.exemplar_passages):
        if not p.why_representative.strip():
            errors.append(f"exemplar_passages[{i}].why_representative 为空")
    for i, p in enumerate(fp.ai_pitfalls):
        if not p.why_it_happens.strip():
            errors.append(f"ai_pitfalls[{i}].why_it_happens 为空")

    # 估算写作成本（system prompt 估算）
    from biyu.fingerprint.prompts import format_exemplars, format_pitfalls
    exemplars_text = format_exemplars([p.model_dump() for p in fp.exemplar_passages])
    pitfalls_text = format_pitfalls([p.model_dump() for p in fp.ai_pitfalls])
    est_input_tokens = (len(fp.style_description) + len(exemplars_text) + len(pitfalls_text)) // 2
    est_output_tokens = 1500  # 1500 字 ≈ 1500 tokens
    est_cost = est_input_tokens * 0.001 / 1000 + est_output_tokens * 0.0035 / 1000

    table = Table(title="声纹校验报告")
    table.add_column("项", style="cyan")
    table.add_column("值", style="green")
    table.add_row("schema_version", str(fp.schema_version))
    table.add_row("source_path", fp.source_info.source_path)
    table.add_row("total_chars", str(fp.source_info.total_chars))
    table.add_row("sampled_chars", str(fp.source_info.sampled_chars))
    table.add_row("sampling_method", fp.source_info.sampling_method)
    table.add_row("style_description 长度", str(len(fp.style_description)))
    table.add_row("exemplar_passages 数量", str(len(fp.exemplar_passages)))
    table.add_row("ai_pitfalls 数量", str(len(fp.ai_pitfalls)))
    table.add_row("估算写作输入 tokens", str(est_input_tokens))
    table.add_row("估算单次写作成本", f"¥{est_cost:.4f}")
    table.add_row("校验结果", "[green]PASS[/green]" if not errors else "[red]FAIL[/red]")

    console.print(table)

    if errors:
        for e in errors:
            console.print(f"[red]  ✗ {e}[/red]")
        raise typer.Exit(1)
    else:
        console.print("[green]所有字段校验通过[/green]")


@fingerprint_app.command("blind-test")
def blind_test(
    fingerprint: str = typer.Option(..., "--fingerprint", "-f", help="声纹 JSON 路径"),
    source: str = typer.Option(..., "--source", "-s", help="源文本路径（用于取真段落）"),
    rounds: int = typer.Option(3, "--rounds", "-r", help="测试轮数"),
    output_dir: str = typer.Option(None, "--output-dir", "-o", help="输出目录"),
) -> None:
    """盲测：V4-Pro 评审人格能否区分 AI 生成 vs 原文。"""
    from biyu.fingerprint.evaluation.blind_test import run_blind_test

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    console.print("[cyan]盲测中...[/cyan]")

    results, summary = run_blind_test(
        fingerprint_path=fingerprint,
        source_path=source,
        rounds=rounds,
        output_dir=output_dir,
    )

    for r in results:
        mark = "[green]答错[/green]" if not r["is_correct"] else "[red]答对[/red]"
        console.print(
            f"  轮 {r['round']} ({r['topic']}): "
            f"正确段={r['correct_segment']} 选择={r['opus_choice']} "
            f"{mark} confidence={r['confidence']}"
        )

    console.print(f"\n错误率: {summary['error_rate']:.0%} ({rounds - summary['correct_count']}/{rounds})")
    console.print(f"总成本: ¥{summary['total_cost']:.4f}")
    if summary["passed"]:
        console.print("[green]盲测通过[/green] (错误率 >= 33%)")
    else:
        console.print("[red]盲测未通过[/red] (错误率 < 33%，Opus 全答对)")


@fingerprint_app.command("multi-genre-test")
def multi_genre_test(
    fingerprint: str = typer.Option(..., "--fingerprint", "-f", help="声纹 JSON 路径"),
    output_dir: str = typer.Option(None, "--output-dir", "-o", help="输出目录"),
) -> None:
    """多题材鲁棒性测试：同一声纹写 3 个不同题材。"""
    from biyu.fingerprint.evaluation.multi_genre_test import run_multi_genre_test

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    console.print("[cyan]多题材测试中...[/cyan]")

    result = run_multi_genre_test(
        fingerprint_path=fingerprint,
        output_dir=output_dir,
    )

    console.print(f"一致性评分: {result['consistency_score']}/5")
    console.print(f"判定: {result['verdict']}")
    console.print(f"各篇字数: {result['char_counts']}")
    console.print(f"总成本: ¥{result['total_cost']:.4f}")

    if result["what_remains_same"]:
        console.print("\n保持一致的方面:")
        for item in result["what_remains_same"]:
            console.print(f"  - {item}")

    if result["passed"]:
        console.print("\n[green]多题材测试通过[/green]")
    else:
        console.print("\n[red]多题材测试未通过[/red]")
