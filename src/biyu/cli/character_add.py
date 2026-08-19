"""角色添加和升格逻辑。"""
from __future__ import annotations

import subprocess
from pathlib import Path

import questionary
import yaml
from ruamel.yaml import YAML
from rich.console import Console
from rich.panel import Panel

console = Console()

VALID_TIERS = ["protagonist", "antagonist", "major_supporting", "supporting", "npc"]


def _find_book_dir(book: str | None) -> Path:
    """查找书目录。"""
    from biyu.config import get_data_root
    data_dir = get_data_root()
    if book:
        book_dir = data_dir / book
    else:
        # 自动检测
        books = [d for d in data_dir.iterdir() if d.is_dir() and (d / "characters.yaml").exists()]
        if len(books) == 1:
            book_dir = books[0]
        elif len(books) == 0:
            console.print("[red]未找到任何书目录[/red]")
            raise typer.Exit(1)
        else:
            book = questionary.select("选择书:", choices=[b.name for b in books]).ask()
            book_dir = data_dir / book
    if not book_dir.exists():
        console.print(f"[red]书目录不存在: {book_dir}[/red]")
        raise typer.Exit(1)
    return book_dir


def _load_characters(book_dir: Path) -> tuple[dict, list[dict]]:
    """加载 characters.yaml。"""
    yaml_path = book_dir / "characters.yaml"
    with open(yaml_path, encoding="utf-8") as f:
        parser = YAML(typ="rt")
        parser.preserve_quotes = True
        data = parser.load(f)
    return data, data.get("characters", [])


def _save_characters(book_dir: Path, data: dict) -> None:
    """保存 characters.yaml。"""
    from biyu.setup_asset_versions import update_characters_list

    update_characters_list(book_dir, data.get("characters"), reason="cli_write")


def add_character(name: str, book: str | None, auto: bool) -> None:
    """交互式或自动添加角色。"""
    import typer

    book_dir = _find_book_dir(book)
    data, characters = _load_characters(book_dir)

    # 检查是否已存在
    existing_names = [c.get("name", "") for c in characters]
    if name in existing_names:
        console.print(f"[red]角色 '{name}' 已存在[/red]")
        raise typer.Exit(1)

    if auto:
        _add_auto(name, book_dir, data)
    else:
        _add_interactive(name, book_dir, data)


def _add_auto(name: str, book_dir: Path, data: dict) -> None:
    """AI 辅助全自动添加（简化字段，仅 npc）。"""
    characters = data.get("characters", [])

    tier = questionary.select(
        "tier:",
        choices=VALID_TIERS,
        default="npc",
    ).ask()

    first_chapter = int(questionary.text("首次出场章节:", default="1").ask() or "1")
    brief = questionary.text("简短描述:").ask() or ""

    new_char = {
        "name": name,
        "tier": tier,
        "brief": brief,
        "tier_history": [
            {"from_chapter": first_chapter, "tier": tier, "reason": "初设"}
        ],
    }

    characters.append(new_char)
    data["characters"] = characters
    _save_characters(book_dir, data)

    console.print(Panel(
        f"角色名: {name}\n"
        f"tier: {tier}\n"
        f"首次出场: CH{first_chapter}\n"
        f"描述: {brief}",
        title="✅ 角色卡已添加",
        border_style="green",
    ))

    _auto_git_commit(book_dir, name, "add")


def _add_interactive(name: str, book_dir: Path, data: dict) -> None:
    """交互式添加角色。"""
    characters = data.get("characters", [])

    tier = questionary.select(
        "tier:",
        choices=VALID_TIERS,
        default="supporting",
    ).ask()

    first_chapter = int(questionary.text("首次出场章节:", default="1").ask() or "1")
    role = questionary.text("角色定位(role):").ask() or ""
    age_raw = questionary.text("年龄:").ask() or ""
    occupation = questionary.text("职业:").ask() or ""
    background = questionary.text("背景(2-3 句话):").ask() or ""
    personality = questionary.text("个性(2-3 句话):").ask() or ""
    appearance = questionary.text("外貌描写:").ask() or ""

    new_char: dict = {
        "name": name,
        "tier": tier,
        "role": role,
        "occupation": occupation,
        "background": background,
        "personality": personality,
        "tier_history": [
            {"from_chapter": first_chapter, "tier": tier, "reason": "初设"}
        ],
    }

    if age_raw:
        try:
            new_char["age"] = int(age_raw)
        except ValueError:
            new_char["age"] = age_raw
    if appearance:
        new_char["appearance"] = appearance

    # voice_examples
    want_ai = questionary.confirm("voice_examples: 用 AI 辅助生成？", default=False).ask()
    if want_ai:
        voice_examples = _ai_generate_voice(name, tier, first_chapter, role or occupation, characters)
    else:
        voice_examples = []
        for i in range(3):
            ve = questionary.text(f"  voice_example {i+1} (留空结束):").ask()
            if not ve:
                break
            voice_examples.append(ve)

    if voice_examples:
        new_char["voice_examples"] = voice_examples

    # aliases
    narrator_default = questionary.text("叙述者默认称呼:", default=name).ask() or name
    self_referent = questionary.text("自称:", default="我").ask() or "我"
    new_char["aliases"] = {
        "narrator_default": narrator_default,
        "self_referent": self_referent,
        "called_by": {},
    }

    # 确认
    console.print(Panel(
        yaml.dump(new_char, allow_unicode=True, default_flow_style=False),
        title="角色卡草稿",
        border_style="cyan",
    ))

    confirm = questionary.select("确认？", choices=["y", "edit", "n"]).ask()
    if confirm == "n":
        console.print("[yellow]取消[/yellow]")
        return
    # edit 暂不实现完整编辑，走 y

    characters.append(new_char)
    data["characters"] = characters
    _save_characters(book_dir, data)

    console.print(f"[green]✅ {name} 角色卡已添加到 characters.yaml[/green]")
    console.print(f"[green]✅ tier_history 自动记录[/green]")

    _auto_git_commit(book_dir, name, "add")


def _ai_generate_voice(
    name: str,
    tier: str,
    chapter: int,
    description: str,
    existing_chars: list[dict],
) -> list[str]:
    """AI 辅助生成 voice_examples。"""
    # 收集已有角色的 voice_examples 作为参考
    sample_voices = []
    for c in existing_chars[:3]:
        ve = c.get("voice_examples", [])
        if ve:
            sample_voices.extend(ve[:2])

    sample_str = "\n".join(f"- {v}" for v in sample_voices[:6]) if sample_voices else "无参考"

    prompt = f"""老板正在为笔驭项目新增一个角色卡。请根据已知信息生成 voice_examples 和 personality 字段草稿。

已知信息:
- 角色名: {name}
- tier: {tier}
- 首次出场章节: {chapter}
- 角色描述: {description}

参考: 这本书的语言基调是轻喜剧爽文 + 平凡少年逆袭。
参考其他角色 voice_examples 风格:
{sample_str}

生成:
1. personality (2-3 句话)
2. voice_examples (3 条典型台词)

输出 JSON:
{{
  "personality": "...",
  "voice_examples": ["...", "...", "..."]
}}"""

    try:
        # 尝试调用 LLM
        import asyncio
        from biyu.config import get_registry

        registry = get_registry()
        adapter = registry.get_adapter("v4_pro")
        messages = [{"role": "user", "content": prompt}]
        resp = asyncio.run(adapter.generate(messages, temperature=0.7, max_tokens=512))
        text = resp.text.strip()

        # 解析 JSON
        import json
        # 尝试提取 JSON
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]

        result = json.loads(text)
        voices = result.get("voice_examples", [])
        if voices:
            console.print("[cyan]AI 生成 voice_examples:[/cyan]")
            for v in voices:
                console.print(f"  - {v}")
            return voices
    except Exception as e:
        console.print(f"[yellow]AI 生成失败: {e}, 使用空列表[/yellow]")

    return []


def promote_character(
    name: str,
    to_tier: str,
    from_chapter: int,
    book: str | None,
    reason: str,
) -> None:
    """角色升格。"""
    import typer

    if to_tier not in VALID_TIERS:
        console.print(f"[red]无效 tier: {to_tier}，可选: {VALID_TIERS}[/red]")
        raise typer.Exit(1)

    book_dir = _find_book_dir(book)
    data, characters = _load_characters(book_dir)

    # 找到角色
    target_char = None
    for c in characters:
        if c.get("name") == name:
            target_char = c
            break

    if target_char is None:
        console.print(f"[red]角色 '{name}' 不存在[/red]")
        raise typer.Exit(1)

    old_tier = target_char.get("tier", "supporting")

    if old_tier == to_tier:
        console.print(f"[yellow]{name} 已经是 {to_tier}[/yellow]")
        return

    # 检查出场记录
    appearances = _load_appearances(book_dir, name)
    total_words = sum(
        _estimate_words(a) for a in appearances
    )
    ch_count = len(appearances)

    console.print(Panel(
        f"角色: {name}\n"
        f"当前 tier: {old_tier}\n"
        f"目标 tier: {to_tier}\n"
        f"出场记录: {ch_count} 章\n"
        f"预估总字数: ~{total_words}\n"
        f"生效章节: CH{from_chapter}",
        title="升格确认",
        border_style="cyan",
    ))

    if total_words < 2000 and to_tier in ("major_supporting", "antagonist", "protagonist"):
        console.print("[yellow]⚠️ 出场记录太少(总字数 < 2000)，建议手填扩展信息[/yellow]")

    # 确认
    confirm = questionary.confirm("确认升格？", default=False).ask()
    if not confirm:
        console.print("[yellow]取消[/yellow]")
        return

    # 更新 tier
    target_char["tier"] = to_tier

    # 追加 tier_history
    if "tier_history" not in target_char:
        target_char["tier_history"] = []
    target_char["tier_history"].append({
        "from_chapter": from_chapter,
        "tier": to_tier,
        "reason": reason or f"{old_tier} → {to_tier}",
    })

    _save_characters(book_dir, data)

    console.print(f"[green]✅ {name} tier: {old_tier} → {to_tier} (从 CH{from_chapter} 起)[/green]")
    console.print(f"[green]✅ tier_history 追加完成[/green]")

    _auto_git_commit(book_dir, name, "promote")


def _load_appearances(book_dir: Path, name: str) -> list[dict]:
    """加载角色的出场记录。"""
    appearances_path = book_dir / "truth_files" / "character_appearances.yaml"
    if not appearances_path.exists():
        return []

    with open(appearances_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    char_data = data.get(name, {})
    return char_data.get("appearances", [])


def _estimate_words(appearance: dict) -> int:
    """估算出场字数。"""
    type_ = appearance.get("type", "brief")
    if type_ == "focus":
        return 1500
    elif type_ == "scene":
        return 750
    else:
        return 150


def _auto_git_commit(book_dir: Path, name: str, action: str) -> None:
    """自动 git commit。"""
    try:
        from biyu.git_helper import _run_git, repo_root_for_book

        repo_root = repo_root_for_book(book_dir)
        yaml_rel = (book_dir.resolve().relative_to(repo_root) / "characters.yaml").as_posix()
        _run_git("add", "--", yaml_rel, cwd=repo_root)

        if action == "add":
            msg = f"feat: characters 新增角色 \"{name}\""
        else:
            msg = f"feat: {name} 升格 (characters.yaml)"

        _run_git("commit", "-m", msg, "--", yaml_rel, cwd=repo_root)
        console.print(f"[green]✅ git commit: {msg}[/green]")
    except Exception as e:
        console.print(f"[yellow]git commit 失败(非致命): {e}[/yellow]")
