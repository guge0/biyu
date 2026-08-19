"""Observer 步骤 — 每章生成后自动更新真相文件。

用 V4(deepseek-chat)读正文+当前真相文件,输出更新后的三件套。
失败时 warning 但不阻塞 pipeline。
"""
from __future__ import annotations

import asyncio
import codecs
import hashlib
import io
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Callable

from biyu.truth_files import (
    TRUTH_FILE_NAMES,
    init_truth_files,
    parse_observer_output,
    read_all_truth_files,
    read_truth_file,
    reset_truth_files,
    snapshot_truth_files,
    write_truth_file,
)


def _ensure_utf8_stdout() -> None:
    """确保 stdout/stderr 使用 UTF-8 编码(Windows GBK 环境)。"""
    if sys.platform == "win32":
        for stream in (sys.stdout, sys.stderr):
            if hasattr(stream, "buffer") and hasattr(stream, "reconfigure"):
                try:
                    stream.reconfigure(encoding="utf-8", errors="replace")
                except (AttributeError, io.UnsupportedOperation):
                    pass


def build_observer_prompt(
    chapter_num: int,
    chapter_text: str,
    truth_data: dict[str, str],
) -> str:
    """构造 Observer prompt。"""
    current_state = truth_data.get("current_state.md", "")
    ledger = truth_data.get("particle_ledger.md", "")
    hooks = truth_data.get("pending_hooks.md", "")

    return f"""\
你是小说连载的设定管理员。刚生成了第{chapter_num}章,请更新三个真相文件。

当前真相文件：
{current_state}

{ledger}

{hooks}

本章正文：
{chapter_text}

规则：
1. current_state：更新所有发生变化的字段,未变化的保持原值
2. particle_ledger：新增本章的属性变化行,不删旧行
3. pending_hooks 伏笔三态状态机(严格遵守,不可跳步):
   状态定义:
   - open: 新伏笔,尚未被推进
   - advancing: 已有推进但未闭合(被提及/有新线索/角色有新认知,但答案未揭示、冲突未解决)
   - closed: 完整闭合(答案被揭示/角色明确解决冲突/故事线自然完结)

   转换规则:
   - 新伏笔 → open
   - 本章有提及或推进但未闭合 → advancing(从open或advancing均可进入)
   - 本章完整闭合(答案揭示/冲突解决) → closed
   - 本章无推进 → 保持原状态
   - 含糊提及(仅再次提及但无实质性推进) → 保持原状态,不推进到advancing

   ⚠️ 关键: "推进"≠"闭合"! 伏笔被再次提及或出现新线索 → advancing,不是closed!
   只有伏笔的答案被明确揭示、冲突被角色明确解决,才能标closed。

4. 严格基于正文事实,不推测、不编造
5. 输出完整的三个 markdown 表格,用 === 分隔

输出格式：
=== current_state ===
（完整表格）
=== particle_ledger ===
（完整表格）
=== pending_hooks ===
（完整表格）
"""


async def update_truth_files(
    book_dir: Path,
    chapter_num: int,
    chapter_text: str,
    adapter,  # LLMAdapter instance
    _log_cost_fn: Callable[[float, float], None] | None = None,
) -> bool:
    """Observer: 读正文,更新真相文件。

    Args:
        book_dir: 书目录
        chapter_num: 章节号
        chapter_text: 本章正文
        adapter: V4 LLMAdapter (deepseek-chat)
        _log_cost_fn: 成本日志回调 (cost, latency) -> None。
            DI 注入,默认 None 时跳过日志(refresh/rebuild 等老 caller 用此默认);
            生产 pipeline 传闭包绑定 book/chapter_num/stage="observer"(参照 _run_anchor_loop DI 模式)。

    Returns:
        True if update succeeded, False otherwise.
    """
    from biyu.setup_asset_versions import validate_characters_yaml_before_model

    # This validation deliberately sits outside the Observer catch-all: malformed
    # founding data must fail visibly before the first paid adapter call.
    validate_characters_yaml_before_model(book_dir)
    t_start = time.time()
    response = None

    def log_cost(cost: float, latency: float, status: str = "ok") -> None:
        if _log_cost_fn is None:
            return
        try:
            _log_cost_fn(cost, latency, status=status)
        except TypeError:
            _log_cost_fn(cost, latency)

    try:
        _ensure_utf8_stdout()
        # 确保 truth_files 目录存在
        init_truth_files(book_dir)

        # 读取当前真相文件
        truth_data = read_all_truth_files(book_dir)

        # 构造 prompt
        prompt = build_observer_prompt(chapter_num, chapter_text, truth_data)
        messages = [{"role": "user", "content": prompt}]

        # 调用 V4
        resp = await adapter.generate(messages)
        response = resp

        if not resp.text or not resp.text.strip():
            print(f"  [Observer] V4 返回空文本,跳过真相文件更新")
            log_cost(resp.cost, time.time() - t_start, "empty")
            return False

        # 解析输出
        parsed = parse_observer_output(resp.text)

        # 快照当前 truth_files 到历史目录
        snapshot_truth_files(book_dir, chapter_num)

        # 写回文件
        updated = 0
        for name in TRUTH_FILE_NAMES:
            content = parsed.get(name, "")
            if content:
                write_truth_file(book_dir, name, content)
                updated += 1

        if updated == 0:
            print(f"  [Observer] 解析失败:未能从输出中提取任何真相文件")
            log_cost(resp.cost, time.time() - t_start, "error")
            return False

        # Ring 5: retain the model result once.  Subsequent memory rebuilds
        # replay this immutable shard locally and never call the adapter.
        from biyu.projections import entries_from_truth, select_new_shard
        select_new_shard(book_dir, chapter_num, {
            "chapter": chapter_num,
            "official_sha256": hashlib.sha256(chapter_text.encode("utf-8")).hexdigest(),
            "files": {name: entries_from_truth(name, content) for name, content in parsed.items() if content},
        })

        latency = time.time() - t_start
        log_cost(resp.cost, latency)
        print(f"  [Observer] 真相文件已更新({updated}/3), ¥{resp.cost:.4f}")

        # 同步死亡角色到 characters.yaml
        _sync_dead_characters(book_dir)

        # 更新角色出场记录
        update_character_appearances(book_dir, chapter_num, chapter_text)

        return True

    except Exception as e:
        if response is not None:
            log_cost(response.cost, time.time() - t_start, "error")
        print(f"  [Observer] 更新失败(warning,不阻塞): {e}")
        return False


def _projection_base_dir(book_dir: Path, chapter_num: int) -> Path:
    return book_dir / "truth_files" / "projection_base" / f"ch{chapter_num}"


def replay_persisted_projections(book_dir: Path) -> bool:
    """Rebuild visible truth only by replaying persisted official shards."""
    from biyu.memory_projection import rebuild_memory
    from biyu.projections import read_shards, select_shard_for_official
    from biyu.truth_files import read_pins

    chapters_dir = book_dir / "chapters"
    chapters = {
        int(path.stem.removeprefix("ch"))
        for path in chapters_dir.glob("ch*.md")
        if path.stem.removeprefix("ch").isdigit()
    } if chapters_dir.exists() else set()
    for chapter in chapters:
        official = chapters_dir / f"ch{chapter}.md"
        select_shard_for_official(book_dir, chapter, hashlib.sha256(official.read_bytes()).hexdigest())
    result = rebuild_memory(read_shards(book_dir, chapters), chapters, read_pins(book_dir))
    for name, content in result.texts().items():
        if name in TRUTH_FILE_NAMES:
            write_truth_file(book_dir, name, content)
    return True


def _restore_or_create_projection_base(book_dir: Path, chapter_num: int) -> None:
    """Restore the state before chN, or record it on the first projection.

    This makes re-running Observer for the same adopted chapter replace that
    chapter's projection instead of appending it again.
    """
    init_truth_files(book_dir)
    base_dir = _projection_base_dir(book_dir, chapter_num)
    if base_dir.exists():
        for name in TRUTH_FILE_NAMES:
            source = base_dir / name
            if source.exists():
                shutil.copy2(source, book_dir / "truth_files" / name)
        base_characters = base_dir / "characters.yaml"
        if base_characters.exists():
            from biyu.setup_asset_versions import (
                record_setup_restore_notice,
                save_setup_asset_version,
            )
            current_characters = book_dir / "characters.yaml"
            before = current_characters.read_bytes() if current_characters.exists() else b""
            will_change = before != base_characters.read_bytes()
            version = save_setup_asset_version(
                book_dir, "characters", reason="before_projection_restore",
            )
            if version is not None and will_change:
                print(f"  [Observer] 单章重算将恢复角色资料；当前编辑已保存在版本 {version}。")
            shutil.copy2(base_characters, current_characters)
            save_setup_asset_version(book_dir, "characters", reason="after_projection_restore")
            if version is not None and will_change:
                record_setup_restore_notice(book_dir, version=version, reason="单章重算")
        base_appearances = base_dir / "character_appearances.yaml"
        current_appearances = book_dir / "truth_files" / "character_appearances.yaml"
        if base_appearances.exists():
            shutil.copy2(base_appearances, current_appearances)
        elif current_appearances.exists():
            current_appearances.unlink()
        return

    base_dir.mkdir(parents=True, exist_ok=False)
    for name in TRUTH_FILE_NAMES:
        source = book_dir / "truth_files" / name
        if source.exists():
            shutil.copy2(source, base_dir / name)
    characters = book_dir / "characters.yaml"
    if characters.exists():
        shutil.copy2(characters, base_dir / "characters.yaml")
    appearances = book_dir / "truth_files" / "character_appearances.yaml"
    if appearances.exists():
        shutil.copy2(appearances, base_dir / "character_appearances.yaml")


async def update_official_chapter_projection(
    book_dir: Path,
    chapter_num: int,
    official_path: Path,
    adapter,
    _log_cost_fn: Callable[..., None] | None = None,
) -> bool:
    """Project one adopted on-disk official chapter into long-term memory."""
    expected = book_dir / "chapters" / f"ch{chapter_num}.md"
    if official_path.resolve() != expected.resolve():
        raise ValueError("Observer 只接受落盘后的正式正文路径")
    chapter_text = official_path.read_text(encoding="utf-8")
    if not chapter_text.strip():
        raise ValueError("正式正文为空，不能更新记忆")

    from biyu.setup_asset_versions import validate_characters_yaml_before_model
    validate_characters_yaml_before_model(book_dir)

    _restore_or_create_projection_base(book_dir, chapter_num)
    ok = await update_truth_files(
        book_dir,
        chapter_num,
        chapter_text,
        adapter,
        _log_cost_fn=_log_cost_fn,
    )
    # A retry may have restored characters.yaml even when this chapter has no
    # death event, so keep the SQLite projection aligned in every branch.
    from biyu.db import init_db, sync_characters_from_yaml
    init_db(book_dir)
    sync_characters_from_yaml(book_dir)
    return ok


# ---------------------------------------------------------------------------
# 死亡角色同步 — 从 current_state.md 检测死亡事件,更新 characters.yaml
# ---------------------------------------------------------------------------

# 匹配死亡相关模式: 角色名 + 死亡关键词
_DEATH_PATTERNS = re.compile(
    r"([\u4e00-\u9fff]{2,6})"  # 2-6个汉字的角色名
    r"(?:已死|被杀|死亡|阵亡|身亡|殒命|陨落|战死|击杀|斩杀|击毙)",
)
_DEATH_PATTERNS_REVERSE = re.compile(
    r"(?:击杀|斩杀|击毙|杀死|杀害|杀死)"
    r"([\u4e00-\u9fff]{2,6})",
)


def _sync_dead_characters(book_dir: Path) -> int:
    """从 current_state.md 检测死亡事件,更新 characters.yaml 中对应角色 status → dead。

    Returns:
        Number of characters newly marked as dead.
    """
    from ruamel.yaml import YAML
    from biyu.db import sync_characters_from_yaml
    from biyu.setup_asset_versions import (
        save_setup_asset_version,
        write_bytes_atomically,
    )

    current_state = read_truth_file(book_dir, "current_state.md")
    if not current_state:
        return 0

    # 提取死亡角色名
    dead_names: set[str] = set()
    for m in _DEATH_PATTERNS.finditer(current_state):
        dead_names.add(m.group(1))
    for m in _DEATH_PATTERNS_REVERSE.finditer(current_state):
        dead_names.add(m.group(1))

    if not dead_names:
        return 0

    # 加载 characters.yaml
    yaml_path = book_dir / "characters.yaml"
    if not yaml_path.exists():
        return 0

    original_bytes = yaml_path.read_bytes()
    has_utf8_bom = original_bytes.startswith(codecs.BOM_UTF8)
    original = original_bytes.decode("utf-8-sig" if has_utf8_bom else "utf-8")
    had_final_newline = original.endswith(("\n", "\r"))
    uses_crlf = "\r\n" in original
    parse_source = original.replace("\r\n", "\n")
    roundtrip = YAML(typ="rt")
    roundtrip.preserve_quotes = True
    roundtrip.width = 4096
    sequence_style = re.search(
        r"(?m)^characters:[^\S\r\n]*\r?\n(?P<indent> *)-",
        parse_source,
    )
    if sequence_style and len(sequence_style.group("indent")) > 0:
        offset = len(sequence_style.group("indent"))
        roundtrip.indent(mapping=2, sequence=offset + 2, offset=offset)
    data = roundtrip.load(parse_source)
    if not isinstance(data, dict):
        return 0

    characters = data.get("characters", [])
    if not isinstance(characters, list):
        return 0
    changed = 0
    for char in characters:
        if not isinstance(char, dict):
            continue
        name = char.get("name", "")
        # 主角永远不会被自动标为 dead（防止"主角击杀XXX"等误匹配）
        if char.get("role") == "protagonist":
            continue
        if name in dead_names and char.get("status") != "dead":
            char["status"] = "dead"
            changed += 1
            print(f"  [Observer] 角色状态更新: {name} → dead")

    if changed > 0:
        save_setup_asset_version(book_dir, "characters", reason="before_observer_status")
        output = io.StringIO()
        roundtrip.dump(data, output)
        rendered = output.getvalue()
        if uses_crlf:
            rendered = rendered.replace("\n", "\r\n")
        if not had_final_newline:
            rendered = rendered.rstrip("\r\n")
        rendered_bytes = rendered.encode("utf-8")
        if has_utf8_bom:
            rendered_bytes = codecs.BOM_UTF8 + rendered_bytes
        write_bytes_atomically(yaml_path, rendered_bytes)
        save_setup_asset_version(book_dir, "characters", reason="after_observer_status")
        # 重新同步到 SQLite
        sync_characters_from_yaml(book_dir)

    return changed


# ---------------------------------------------------------------------------
# 角色出场记录 — 每章生成后自动更新 character_appearances.yaml
# ---------------------------------------------------------------------------

def update_character_appearances(
    book_dir: Path,
    chapter_num: int,
    chapter_text: str,
) -> int:
    """扫描章节正文，更新 character_appearances.yaml。

    Args:
        book_dir: 书目录
        chapter_num: 章节号
        chapter_text: 本章正文

    Returns:
        Number of character appearance records added.
    """
    import yaml

    yaml_path = book_dir / "characters.yaml"
    if not yaml_path.exists():
        return 0

    with open(yaml_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    chars = data.get("characters", [])

    # 构建搜索词
    char_search = _build_appearance_search_terms(chars)

    # 分段
    paragraphs = _split_paragraphs(chapter_text)

    # 检测出场
    added = 0
    appearances_to_add: dict[str, dict] = {}

    for char_name, search_terms in char_search.items():
        if not search_terms:
            continue

        mention_count = 0
        matching_chars = 0

        for para in paragraphs:
            found = False
            for term in search_terms:
                if term in para:
                    found = True
                    mention_count += para.count(term)
                    break
            if found:
                matching_chars += len(para)

        if mention_count == 0:
            continue

        type_ = _judge_appearance_type(matching_chars)
        summary = _extract_appearance_summary(chapter_text, search_terms, char_name)

        appearances_to_add[char_name] = {
            "chapter": chapter_num,
            "type": type_,
            "summary": summary,
        }

    if not appearances_to_add:
        return 0

    # 读取/创建 character_appearances.yaml
    truth_dir = book_dir / "truth_files"
    truth_dir.mkdir(parents=True, exist_ok=True)
    appearances_path = truth_dir / "character_appearances.yaml"

    if appearances_path.exists():
        with open(appearances_path, encoding="utf-8") as f:
            appearances_data = yaml.safe_load(f) or {}
    else:
        appearances_data = {}

    for char_name, record in appearances_to_add.items():
        if char_name not in appearances_data:
            appearances_data[char_name] = {"appearances": []}

        # 移除该章节的旧记录（如果有，防止重复）
        appearances_data[char_name]["appearances"] = [
            a for a in appearances_data[char_name]["appearances"]
            if a.get("chapter") != chapter_num
        ]
        appearances_data[char_name]["appearances"].append(record)
        added += 1

    with open(appearances_path, "w", encoding="utf-8") as f:
        yaml.dump(appearances_data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    if added > 0:
        print(f"  [Observer] 角色出场记录已更新: {added} 个角色")

    return added


def _build_appearance_search_terms(chars: list[dict]) -> dict[str, set[str]]:
    """为每个角色构建搜索词集合。"""
    char_search: dict[str, set[str]] = {}
    for char in chars:
        name = char.get("name", "")
        terms: set[str] = set()
        terms.add(name)

        aliases = char.get("aliases", {})
        if isinstance(aliases, dict):
            nd = aliases.get("narrator_default", "")
            if nd and nd != name:
                terms.add(nd)

        # 只保留 >= 3 字符的词以减少误报
        terms = {t for t in terms if len(t) >= 3 or t == name}
        char_search[name] = terms

    return char_search


def _split_paragraphs(text: str) -> list[str]:
    """Split text into paragraphs."""
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def _judge_appearance_type(char_count: int) -> str:
    """按字数判断出场类型。"""
    if char_count > 1500:
        return "focus"
    elif char_count >= 300:
        return "scene"
    else:
        return "brief"


def _extract_appearance_summary(text: str, search_terms: set[str], char_name: str) -> str:
    """提取出场摘要（取首次提及段落的第一句）。"""
    paragraphs = _split_paragraphs(text)
    for para in paragraphs:
        for term in search_terms:
            if term in para:
                sentence_end = re.search(r"[。！？…]", para)
                if sentence_end:
                    s = para[:sentence_end.end()]
                else:
                    s = para[:60]
                if len(s) > 80:
                    s = s[:77] + "..."
                return s
    return f"{char_name}出场"


# ---------------------------------------------------------------------------
# 伏笔三态重分类 — 将 partially_closed 修正为 advancing
# ---------------------------------------------------------------------------

# 伏笔状态映射: 旧状态 → 新状态
_HOOK_STATUS_MAP = {
    "partially_closed": "advancing",
    "partial_closed": "advancing",
    "partially-resolved": "advancing",
}


def reclassify_hooks(hooks_md: str) -> tuple[str, list[dict]]:
    """对 pending_hooks.md 内容做状态重分类。

    规则:
    - partially_closed / partial_closed → advancing
    - open / advancing / closed → 保持不变

    Args:
        hooks_md: pending_hooks.md 的原始内容。

    Returns:
        (reclassified_content, changes) — 重分类后的内容和变更列表。
        changes 中每项: {"hook_id": str, "old": str, "new": str}
    """
    lines = hooks_md.split("\n")
    result_lines: list[str] = []
    changes: list[dict] = []

    # 找到表头行和分隔行,确定"状态"列的位置
    header_idx = None
    status_col_idx = None
    hook_id_col_idx = None

    for i, line in enumerate(lines):
        if "hook_id" in line and "状态" in line:
            header_idx = i
            cols = [c.strip() for c in line.split("|")]
            for j, col in enumerate(cols):
                if col == "hook_id":
                    hook_id_col_idx = j
                if col == "状态":
                    status_col_idx = j
            break

    if header_idx is None or status_col_idx is None:
        return hooks_md, []

    for i, line in enumerate(lines):
        if i <= header_idx:
            result_lines.append(line)
            continue

        # 跳过分隔行
        stripped = line.strip()
        if stripped.startswith("|") and all(
            c in "|-:" for c in stripped.replace(" ", "")
        ):
            result_lines.append(line)
            continue

        # 跳过空行
        if not stripped:
            result_lines.append(line)
            continue

        # 解析数据行
        cells = line.split("|")
        if status_col_idx >= len(cells):
            result_lines.append(line)
            continue

        old_status = cells[status_col_idx].strip()
        new_status = _HOOK_STATUS_MAP.get(old_status, old_status)

        if new_status != old_status:
            cells[status_col_idx] = f" {new_status} "
            result_lines.append("|".join(cells))
            hook_id = ""
            if hook_id_col_idx is not None and hook_id_col_idx < len(cells):
                hook_id = cells[hook_id_col_idx].strip()
            changes.append({"hook_id": hook_id, "old": old_status, "new": new_status})
        else:
            result_lines.append(line)

    return "\n".join(result_lines), changes


def reclassify_pending_hooks_file(book_dir: Path) -> list[dict]:
    """对 book 目录下的 pending_hooks.md 做就地重分类。

    Returns:
        变更列表。
    """
    from biyu.truth_files import read_truth_file, write_truth_file

    hooks_md = read_truth_file(book_dir, "pending_hooks.md")
    if not hooks_md:
        return []

    new_content, changes = reclassify_hooks(hooks_md)
    if changes:
        write_truth_file(book_dir, "pending_hooks.md", new_content)
        for c in changes:
            print(f"  [reclassify] {c['hook_id']}: {c['old']} → {c['new']}")
    else:
        print("  [reclassify] 无需修改")

    return changes


def _sha256(path: Path) -> str:
    if not path.exists():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _memory_surface_hashes(book_dir: Path) -> dict[str, str]:
    paths = {
        **{f"truth_files/{name}": book_dir / "truth_files" / name for name in TRUTH_FILE_NAMES},
        "truth_files/character_appearances.yaml": book_dir / "truth_files" / "character_appearances.yaml",
        "characters.yaml": book_dir / "characters.yaml",
        "book.db": book_dir / "book.db",
    }
    return {name: _sha256(path) for name, path in paths.items()}


def backup_truth_files_pre_ring4(book_dir: Path) -> Path:
    """Create the one-time full truth_files backup required before rebuild."""
    tdir = book_dir / "truth_files"
    tdir.mkdir(parents=True, exist_ok=True)
    target = tdir / "backup_pre_env4"
    if target.exists():
        return target
    target.mkdir(parents=False, exist_ok=False)
    for source in list(tdir.iterdir()):
        if source == target:
            continue
        destination = target / source.name
        if source.is_dir():
            shutil.copytree(source, destination)
        else:
            shutil.copy2(source, destination)
    return target


def _reset_memory_projection(book_dir: Path) -> None:
    """Clear derived projection while preserving its one-time backup."""
    tdir = book_dir / "truth_files"
    characters = book_dir / "characters.yaml"
    founding = tdir / "founding_characters.yaml"
    if characters.exists() and not founding.exists():
        shutil.copy2(characters, founding)
    if founding.exists():
        from biyu.setup_asset_versions import (
            record_setup_restore_notice,
            save_setup_asset_version,
        )
        before = characters.read_bytes() if characters.exists() else b""
        version = save_setup_asset_version(
            book_dir, "characters", reason="before_founding_restore",
        )
        will_change = before != founding.read_bytes()
        if version is not None and will_change:
            print(f"  [Observer] 全书重建将恢复角色资料；当前编辑已保存在版本 {version}。")
        shutil.copy2(founding, characters)
        save_setup_asset_version(book_dir, "characters", reason="after_founding_restore")
        if version is not None and will_change:
            record_setup_restore_notice(book_dir, version=version, reason="全书重建")

    for directory_name in ("history", "projection_base"):
        directory = tdir / directory_name
        if directory.exists():
            shutil.rmtree(directory)
    appearances = tdir / "character_appearances.yaml"
    if appearances.exists():
        appearances.unlink()
    reset_truth_files(book_dir)

    from biyu.db import init_db, sync_characters_from_yaml
    init_db(book_dir)
    sync_characters_from_yaml(book_dir)


async def rebuild_hooks(
    book_dir: Path,
    adapter,
    _log_cost_fn: Callable[[int, float, float], None] | None = None,
) -> dict:
    """从全部正式章节重建完整记忆投影，并返回可审计 diff。

    遍历 chapters/ 下的所有 chN.md,逐章调用 Observer 重建真相文件。
    每章会快照当前 truth_files 到 history/ 再覆盖更新。

    ⚠️ 本函数会产生 LLM 调用成本,请确认预算后再运行。

    Args:
        book_dir: 书目录。
        adapter: V4 LLMAdapter。

    Returns:
        {"chapters_processed": int, "errors": list[str]}
    """
    chapters_dir = book_dir / "chapters"
    if not chapters_dir.exists():
        return {"chapters_processed": 0, "errors": ["chapters/ 目录不存在"]}

    from biyu.setup_asset_versions import validate_characters_yaml_before_model
    validate_characters_yaml_before_model(book_dir)

    # 收集所有 chN.md(不含 _pending)
    chapter_files = sorted(
        chapters_dir.glob("ch*.md"),
        key=lambda p: int(re.search(r"ch(\d+)", p.name).group(1)),
    )
    chapter_files = [
        f for f in chapter_files
        if not f.parent.name.startswith("_")
    ]

    before = _memory_surface_hashes(book_dir)
    backup_path = backup_truth_files_pre_ring4(book_dir)
    _reset_memory_projection(book_dir)

    processed = 0
    errors: list[str] = []

    for ch_path in chapter_files:
        m = re.search(r"ch(\d+)", ch_path.name)
        if not m:
            continue
        ch_num = int(m.group(1))
        print(f"  [rebuild_hooks] 处理第 {ch_num} 章...")
        chapter_log = None
        if _log_cost_fn is not None:
            chapter_log = lambda cost, latency, ch=ch_num: _log_cost_fn(ch, cost, latency)
        ok = await update_official_chapter_projection(
            book_dir,
            ch_num,
            ch_path,
            adapter,
            _log_cost_fn=chapter_log,
        )
        from biyu.cli.workbench_cmd import _set_memory_dirty
        _set_memory_dirty(
            book_dir,
            ch_num,
            not ok,
            "Observer 未完成" if not ok else "",
        )
        if ok:
            processed += 1
        else:
            errors.append(f"ch{ch_num}: Observer 更新失败")

    # 最后做一次 reclassify 确保状态干净
    reclassify_pending_hooks_file(book_dir)

    after = _memory_surface_hashes(book_dir)
    diff = {
        name: {
            "before_sha256": before.get(name, ""),
            "after_sha256": after.get(name, ""),
            "changed": before.get(name, "") != after.get(name, ""),
        }
        for name in sorted(set(before) | set(after))
    }
    print(f"  [rebuild_hooks] 完成: {processed}/{len(chapter_files)} 章处理成功")
    return {
        "chapters_processed": processed,
        "errors": errors,
        "backup_path": str(backup_path),
        "diff": diff,
    }
