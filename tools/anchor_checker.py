"""Anchor checker CLI — value-match 锚点检测命令行入口。

P6-A2: 引擎核心已抽到 biyu.anchor_check(供 auditor 共用, 装包后可用)。
本文件保留 CLI + 报告生成, 并 re-export 引擎函数以保向后兼容。
"""
from __future__ import annotations

import json
from pathlib import Path

# 引擎 re-export(向后兼容: 现有 `from tools.anchor_checker import check_atomic` 等不破)
from biyu.anchor_check import (  # noqa: F401
    check_atomic,
    check_composite,
    compute_stats,
    load_anchors,
    load_text,
    normalize,
    run_check,
    run_check_text,
    run_two_layer_check,
)


# ---------------------------------------------------------------------------
# 报告生成
# ---------------------------------------------------------------------------
def generate_json_report(results: list[dict], output_path: str | Path) -> None:
    """生成 JSON 格式报告。"""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)


def generate_md_report(results: list[dict], output_path: str | Path) -> None:
    """生成 Markdown 格式报告(含 在/MISSING/VALUE_MISMATCH 三态)。"""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Anchor Check Report\n"]

    for report in results:
        ch = report["chapter"]
        stats = report["stats"]
        atomic = report["atomic_results"]
        composite = report.get("composite_results", [])

        lines.append(f"## {ch}\n")
        if "source_file" in report:
            lines.append(f"- 源文件: `{report['source_file']}`\n")

        # 总体(三态)
        a = stats["atomic"]
        lines.append("### Atomic 概览(value-match 三态)\n")
        lines.append("| 指标 | 值 |")
        lines.append("|------|-----|")
        lines.append(f"| 总数 | {a['total']} |")
        lines.append(f"| 在场(present) | {a['hit']} |")
        lines.append(f"| 值错(VALUE_MISMATCH) | {a.get('value_mismatch', 0)} |")
        lines.append(f"| 缺(MISSING) | {a['miss']} |")
        pct = f"{a['ratio'] * 100:.1f}%"
        lines.append(f"| 在场率 | {pct} |")
        lines.append("")

        # 按类型
        if stats.get("by_type"):
            lines.append("### 按类型统计\n")
            lines.append("| 类型 | 总数 | 在场 | 值错 | 缺 | 在场率 |")
            lines.append("|------|------|------|------|-----|--------|")
            for t, s in stats["by_type"].items():
                r = f"{s['ratio'] * 100:.1f}%"
                lines.append(
                    f"| {t} | {s['total']} | {s['hit']} | {s.get('value_mismatch', 0)} | {s['miss']} | {r} |"
                )
            lines.append("")

        # 跨章锚
        cc = stats.get("cross_chapter", {})
        if cc.get("total", 0) > 0:
            lines.append("### 跨章锚(cross_chapter_of)\n")
            r = f"{cc['ratio'] * 100:.1f}%" if cc["ratio"] is not None else "N/A"
            lines.append(f"- 总数: {cc['total']}, 命中: {cc['hit']}, 命中率: {r}\n")

        # 逐锚命中表(三态)
        lines.append("### 逐锚命中表(在 / MISSING / VALUE_MISMATCH)\n")
        lines.append("| ID | 类型 | canonical | 状态 | 命中/错值方式 | 跨章 |")
        lines.append("|----|------|-----------|------|--------------|------|")
        for a in atomic:
            cross = a.get("cross_chapter_of") or ""
            status = a.get("status", "present" if a["hit"] else "missing")
            if status == "present":
                cell = a.get("hit_by") or ""
            elif status == "value_mismatch":
                cell = f"错值:{a.get('mismatch_by') or ''}"
            else:
                cell = ""
            lines.append(
                f"| {a['id']} | {a['type']} | {a['canonical']} "
                f"| {status} | {cell} | {cross} |"
            )
        lines.append("")

        # Composite
        if composite:
            lines.append("### Composite 结果\n")
            lines.append("| ID | 名称 | 全命中 | 成员状态 |")
            lines.append("|----|------|--------|----------|")
            for c in composite:
                all_hit_str = "✓" if c["all_hit"] else "✗"
                members_str = ", ".join(
                    f"{m['id']}({'✓' if m['hit'] else '✗'})" for m in c["members"]
                )
                lines.append(f"| {c['id']} | {c['name']} | {all_hit_str} | {members_str} |")
            lines.append("")

    output_path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------
def main() -> None:
    """命令行入口: python -m tools.anchor_checker <yaml> <text1> [text2 ...] [--chapter-ids ID ...] [--output-dir DIR]"""
    import argparse

    parser = argparse.ArgumentParser(description="Anchor checker (value-match)")
    parser.add_argument("yaml", help="anchors.yaml 路径")
    parser.add_argument("texts", nargs="+", help="待检测文本文件路径")
    parser.add_argument("--chapter-ids", nargs="*", help="章节 ID 列表, 与 texts 一一对应")
    parser.add_argument("--output-dir", default=".", help="输出目录")
    args = parser.parse_args()

    results = []
    for i, text_path in enumerate(args.texts):
        ch_id = args.chapter_ids[i] if args.chapter_ids and i < len(args.chapter_ids) else None
        report = run_check(args.yaml, text_path, chapter_id=ch_id)
        results.append(report)

    out_dir = Path(args.output_dir)
    generate_json_report(results, out_dir / "anchor_report.json")
    generate_md_report(results, out_dir / "anchor_report.md")

    # 打印摘要(三态)
    for r in results:
        ch = r["chapter"]
        a = r["stats"]["atomic"]
        pct = f"{a['ratio'] * 100:.1f}%"
        print(f"{ch}: 在 {a['hit']} / 值错 {a['value_mismatch']} / 缺 {a['miss']} (共 {a['total']}, 在场率 {pct})")


if __name__ == "__main__":
    main()
