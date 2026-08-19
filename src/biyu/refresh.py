"""改稿同步 — refresh(重跑Observer) + rollback(回退truth_files+归档章节)。"""
from __future__ import annotations

import shutil
from pathlib import Path

from biyu.config import BookConfig
from biyu.truth_files import (
    TRUTH_FILE_NAMES,
    snapshot_truth_files,
    truth_dir,
    write_truth_file,
)


def refresh_chapter(book_dir: Path, chapter_num: int, adapter=None) -> bool:
    """读 chN.md 正文，重跑 Observer，更新 truth_files。

    Args:
        book_dir: 书目录。
        chapter_num: 章节号。
        adapter: 可选 LLM adapter。为 None 时从 registry 获取。

    Returns:
        True if Observer update succeeded.
    """
    import asyncio
    from biyu.observer import update_official_chapter_projection
    from biyu.config import get_registry
    from biyu.cli.workbench_cmd import _set_memory_dirty

    book = BookConfig(book_dir)
    chapter_path = book.chapter_path(chapter_num)
    if not chapter_path.exists():
        print(f"  [refresh] 章节 ch{chapter_num}.md 不存在，跳过")
        return False

    if not chapter_path.read_text(encoding="utf-8").strip():
        print(f"  [refresh] 章节 ch{chapter_num}.md 内容为空，跳过")
        return False

    if adapter is None:
        registry = get_registry()
        observer_alias = registry.get_pipeline_config().get("writer", "v3")
        adapter = registry.get_adapter_for_stage("writer", override=observer_alias)

    ok = asyncio.run(update_official_chapter_projection(
        book_dir, chapter_num, chapter_path, adapter,
    ))
    _set_memory_dirty(book_dir, chapter_num, not ok, "Observer 未完成" if not ok else "")
    if ok:
        print(f"  [refresh] ch{chapter_num} Observer 更新成功")
    else:
        print(f"  [refresh] ch{chapter_num} Observer 更新失败")
    return ok


def refresh_range(book_dir: Path, from_ch: int, to_ch: int, adapter=None) -> list[tuple[int, bool]]:
    """逐章 refresh。

    Returns:
        List of (chapter_num, success) tuples.
    """
    if adapter is None:
        from biyu.config import get_registry
        registry = get_registry()
        observer_alias = registry.get_pipeline_config().get("writer", "v3")
        adapter = registry.get_adapter_for_stage("writer", override=observer_alias)

    results = []
    for ch in range(from_ch, to_ch + 1):
        print(f"\n--- Refresh ch{ch} ---")
        ok = refresh_chapter(book_dir, ch, adapter)
        results.append((ch, ok))
    return results


def rollback_to_chapter(book_dir: Path, to_chapter: int) -> bool:
    """从 history 恢复 truth_files 到指定章节状态，并归档后续章节。

    Args:
        book_dir: 书目录。
        to_chapter: 回退到的目标章节号。

    Returns:
        True if rollback succeeded.
    """
    book = BookConfig(book_dir)
    tdir = truth_dir(book_dir)
    history_dir = tdir / "history" / f"ch{to_chapter}"

    # 检查历史快照是否存在
    if not history_dir.exists():
        print(f"  [rollback] 历史快照不存在: {history_dir}")
        return False

    # 恢复 truth_files
    for name in TRUTH_FILE_NAMES:
        src = history_dir / name
        if src.exists():
            write_truth_file(book_dir, name, src.read_text(encoding="utf-8"))
            print(f"  [rollback] 已恢复: {name}")

    # 归档后续章节（移动到 chapters/archive/）
    archive_dir = book.chapters_dir / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)

    for ch_path in sorted(book.chapters_dir.glob("ch*.md")):
        # 从 chN.md 提取章节号
        stem = ch_path.stem
        try:
            ch_num = int(stem.replace("ch", ""))
        except ValueError:
            continue
        if ch_num > to_chapter:
            dest = archive_dir / ch_path.name
            shutil.move(str(ch_path), str(dest))
            print(f"  [rollback] 已归档: ch{ch_num}.md → archive/")

    # 归档后续日志
    for log_path in sorted(book.logs_dir.glob("ch*")):
        if log_path.is_dir():
            try:
                ch_num = int(log_path.name.replace("ch", ""))
            except ValueError:
                continue
            if ch_num > to_chapter:
                dest = book.logs_dir / "archive" / log_path.name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(log_path), str(dest))
                print(f"  [rollback] 已归档日志: ch{ch_num}/ → archive/")

    print(f"  [rollback] 回退完成，当前 truth_files 状态 = ch{to_chapter}")
    return True
