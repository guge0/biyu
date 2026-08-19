"""biyu revise 命令 — 交互/单条 issue 操作入口。"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

console = Console()

# Reviser 调用上限 soft warning
_REVISER_SOFT_LIMIT = 5


def _load_report(book_dir: Path, chapter_num: int):
    """加载 AuditReportJSON。"""
    from biyu.audit_reports.state import AuditReportJSON

    report_dir = book_dir / "audit_reports"
    json_path = report_dir / f"ch{chapter_num}.json"
    if not json_path.exists():
        console.print(f"[red]未找到 ch{chapter_num} 的审稿报告[/red]")
        raise SystemExit(1)
    return AuditReportJSON.load(json_path), report_dir


def _save_and_render(report, report_dir: Path, book_dir: Path) -> None:
    """保存 JSON + 重新渲染 MD。"""
    from biyu.audit_reports.builder import build_audit_md_from_json

    report.save(report_dir)
    build_audit_md_from_json(report, book_dir)


def _load_chapter_text(book_dir: Path, chapter_num: int) -> str:
    """读取章节正文。"""
    ch_path = book_dir / "chapters" / f"ch{chapter_num}.md"
    if not ch_path.exists():
        ch_path = book_dir / "chapters" / "_pending" / f"ch{chapter_num}.md"
    if not ch_path.exists():
        console.print(f"[red]未找到 ch{chapter_num} 的正文文件[/red]")
        raise SystemExit(1)
    return ch_path.read_text(encoding="utf-8")


def _write_chapter_text(book_dir: Path, chapter_num: int, text: str) -> Path:
    """写回章节正文，返回写入路径。"""
    ch_path = book_dir / "chapters" / f"ch{chapter_num}.md"
    if not ch_path.exists():
        ch_path = book_dir / "chapters" / "_pending" / f"ch{chapter_num}.md"
    ch_path.write_text(text, encoding="utf-8")
    return ch_path


def _check_reviser_limit(issue) -> bool:
    """检查 Reviser 调用次数是否超过软上限。

    Returns:
        True if should proceed (possibly with warning), False if user aborted.
    """
    if issue.reviser_call_count >= _REVISER_SOFT_LIMIT:
        console.print(
            f"[yellow]⚠️ issue {issue.id} 已调用 Reviser "
            f"{issue.reviser_call_count} 次（建议上限 {_REVISER_SOFT_LIMIT}）。"
            f"继续可能增加成本。[/yellow]"
        )
        try:
            ans = input("继续? [y/N] ").strip().lower()
            if ans != "y":
                return False
        except (EOFError, KeyboardInterrupt):
            return False
    return True


async def _apply_suggestion(
    report, issue, book_dir: Path, chapter_num: int, report_dir: Path,
) -> bool:
    """调 Reviser 改写段落 → resolved_by_biyu。"""
    if not _check_reviser_limit(issue):
        return False

    from biyu.config import BookConfig, get_registry
    from biyu.reviser import revise_paragraph, apply_revision

    chapter_text = _load_chapter_text(book_dir, chapter_num)
    registry = get_registry()
    adapter = registry.get_adapter_for_stage("writer")

    result = await revise_paragraph(
        chapter_text=chapter_text,
        paragraph_index=issue.paragraph,
        issue_description=issue.description,
        fix_suggestion=issue.suggestion,
        adapter=adapter,
    )

    if not result.success:
        console.print(f"[red]Reviser 失败: {result.error}[/red]")
        return False

    # 替换段落
    new_text = apply_revision(chapter_text, issue.paragraph, result.revised_paragraph)
    ch_path = _write_chapter_text(book_dir, chapter_num, new_text)

    # 更新状态
    issue.add_suggestion(result.revised_paragraph, source="reviser", cost_yuan=result.cost)
    issue.transition("resolved_by_biyu", note=f"Reviser 改写 (¥{result.cost:.4f})")

    report.reviser_total_cost_yuan += result.cost
    report.reviser_call_count += 1

    # 保存 + 渲染
    _save_and_render(report, report_dir, book_dir)

    # Git commit
    try:
        from biyu.git_helper import commit_reviser_change
        commit_hash = commit_reviser_change(book_dir, chapter_num, issue.id)
        console.print(f"[green]✅ 已应用并提交: {commit_hash}[/green]")
    except Exception as e:
        console.print(f"[yellow]Git 提交失败(warning): {e}[/yellow]")

    console.print(f"  成本: ¥{result.cost:.4f}")
    return True


async def _regen_suggestion(
    report, issue, book_dir: Path, chapter_num: int, report_dir: Path,
    reason: str = "",
) -> bool:
    """Reviser 新方案 → 追加 suggestions_history，status 保持 open。"""
    if not _check_reviser_limit(issue):
        return False

    from biyu.config import BookConfig, get_registry
    from biyu.reviser import revise_paragraph

    chapter_text = _load_chapter_text(book_dir, chapter_num)
    registry = get_registry()
    adapter = registry.get_adapter_for_stage("writer")

    # 如果有 reason，附加到 suggestion 后面
    enhanced_suggestion = issue.suggestion
    if reason:
        enhanced_suggestion += f"\n补充要求: {reason}"

    result = await revise_paragraph(
        chapter_text=chapter_text,
        paragraph_index=issue.paragraph,
        issue_description=issue.description,
        fix_suggestion=enhanced_suggestion,
        adapter=adapter,
    )

    if not result.success:
        console.print(f"[red]Reviser 失败: {result.error}[/red]")
        return False

    # 追加 suggestion，status 保持 open
    issue.add_suggestion(result.revised_paragraph, source="reviser", cost_yuan=result.cost)
    report.reviser_total_cost_yuan += result.cost
    report.reviser_call_count += 1

    # 保存 + 渲染
    _save_and_render(report, report_dir, book_dir)

    console.print(f"[green]✅ 已生成新方案 (第 {issue.reviser_call_count} 次)[/green]")
    console.print(f"  新方案: {result.revised_paragraph[:80]}...")
    console.print(f"  成本: ¥{result.cost:.4f}")
    return True


def _interactive_mode(report, book_dir: Path, chapter_num: int, report_dir: Path) -> None:
    """交互模式：列 open issues，逐条选择操作。"""
    open_issues = report.open_issues()
    if not open_issues:
        console.print("[green]✅ 没有 open 的 issue[/green]")
        return

    console.print(f"\n[bold]CH{chapter_num} — {len(open_issues)} 个 open issue[/bold]\n")

    for idx, issue in enumerate(open_issues, 1):
        console.print(f"  [{idx}] {issue.severity.upper():6s} {issue.type:10s} | {issue.description[:50]}")
        console.print(f"      ID: {issue.id}  行: {issue.paragraph}")
        console.print(f"      建议: {issue.suggestion[:60]}")
        console.print()

    while True:
        console.print("[bold]操作:[/bold] apply=N | regen=N | resolve=N | dismiss=N | sync | quit")
        try:
            cmd = input("> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            break

        if cmd in ("quit", "q", "exit"):
            break

        if cmd == "sync":
            from biyu.audit_reports.sync import sync_md_to_json
            updated = sync_md_to_json(book_dir, chapter_num)
            console.print(f"[green]同步完成: {updated} 条更新[/green]")
            # Reload
            report, report_dir = _load_report(book_dir, chapter_num)
            continue

        parts = cmd.split("=", 1)
        if len(parts) != 2:
            console.print("[yellow]格式: action=N[/yellow]")
            continue

        action, num_str = parts
        try:
            num = int(num_str)
        except ValueError:
            console.print("[yellow]请输入数字[/yellow]")
            continue

        if num < 1 or num > len(open_issues):
            console.print(f"[yellow]编号范围: 1-{len(open_issues)}[/yellow]")
            continue

        issue = open_issues[num - 1]

        if action == "apply":
            asyncio.get_event_loop().run_until_complete(
                _apply_suggestion(report, issue, book_dir, chapter_num, report_dir)
            )
        elif action == "regen":
            reason = ""
            try:
                reason = input("补充要求（回车跳过）: ").strip()
            except (EOFError, KeyboardInterrupt):
                pass
            asyncio.get_event_loop().run_until_complete(
                _regen_suggestion(report, issue, book_dir, chapter_num, report_dir, reason=reason)
            )
        elif action == "resolve":
            issue.transition("resolved_by_author", note="CLI resolve-self")
            _save_and_render(report, report_dir, book_dir)
            console.print(f"[green]✅ {issue.id} → resolved_by_author[/green]")
        elif action == "dismiss":
            issue.transition("dismissed", note="CLI dismiss")
            _save_and_render(report, report_dir, book_dir)
            console.print(f"[green]✅ {issue.id} → dismissed[/green]")
        else:
            console.print(f"[yellow]未知操作: {action}[/yellow]")

        # 刷新 open_issues
        open_issues = report.open_issues()
        if not open_issues:
            console.print("[green]✅ 所有 issue 已处理完毕[/green]")
            break

    # 退出前保存
    report.save(report_dir)
    from biyu.audit_reports.builder import build_audit_md_from_json
    build_audit_md_from_json(report, book_dir)


def revise_command(
    chapter: int = 0,
    issue: str = "",
    apply: bool = False,
    regen: bool = False,
    resolve_self: bool = False,
    dismiss: bool = False,
    sync: bool = False,
    reason: str = "",
    book: str = "",
) -> None:
    """biyu revise 命令主入口。

    无参数 → 交互模式
    --issue ID --apply/--regen/--resolve-self/--dismiss → 单条操作
    --sync → MD checkbox → JSON
    """
    from biyu.config import BookConfig, get_data_root

    data_dir = get_data_root()
    if book:
        book_dir = data_dir / book
    else:
        books = [d for d in data_dir.iterdir() if d.is_dir() and (d / "characters.yaml").exists()]
        if len(books) == 1:
            book_dir = books[0]
        elif len(books) == 0:
            console.print("[red]未找到任何书目录[/red]")
            raise SystemExit(1)
        else:
            console.print("[yellow]多本书，请指定 --book[/yellow]")
            raise SystemExit(1)
    if not book_dir.exists():
        console.print(f"[red]书目录不存在: {book_dir}[/red]")
        raise SystemExit(1)

    chapter_num = chapter
    if chapter_num == 0 and issue:
        # 从 issue ID 推导章节号: "ch27-001" → 27
        try:
            chapter_num = int(issue.split("-")[0].replace("ch", ""))
        except (ValueError, IndexError):
            console.print(f"[red]无法从 issue ID '{issue}' 推导章节号[/red]")
            raise SystemExit(1)

    if chapter_num == 0:
        console.print("[red]请指定 --chapter 或 --issue[/red]")
        raise SystemExit(1)

    # --sync 模式
    if sync:
        from biyu.audit_reports.sync import sync_md_to_json
        updated = sync_md_to_json(book_dir, chapter_num)
        console.print(f"同步完成: {updated} 条 issue 从 MD checkbox 更新到 JSON")
        return

    report, report_dir = _load_report(book_dir, chapter_num)

    # 无 issue ID → 交互模式
    if not issue:
        _interactive_mode(report, book_dir, chapter_num, report_dir)
        return

    # 单条操作
    target = report.get_issue(issue)
    if target is None:
        console.print(f"[red]未找到 issue: {issue}[/red]")
        raise SystemExit(1)

    if apply:
        asyncio.get_event_loop().run_until_complete(
            _apply_suggestion(report, target, book_dir, chapter_num, report_dir)
        )
    elif regen:
        asyncio.get_event_loop().run_until_complete(
            _regen_suggestion(report, target, book_dir, chapter_num, report_dir, reason=reason)
        )
    elif resolve_self:
        target.transition("resolved_by_author", note="CLI resolve-self")
        _save_and_render(report, report_dir, book_dir)
        console.print(f"[green]✅ {target.id} → resolved_by_author[/green]")
    elif dismiss:
        target.transition("dismissed", note="CLI dismiss")
        _save_and_render(report, report_dir, book_dir)
        console.print(f"[green]✅ {target.id} → dismissed[/green]")
    else:
        console.print("[yellow]请指定操作: --apply / --regen / --resolve-self / --dismiss[/yellow]")
