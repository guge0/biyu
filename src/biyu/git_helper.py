"""git 操作封装 — 所有 CLI 命令和 pipeline 统一调用。

commit message 前缀约定:
  auto: <message>      自动修改(dash_fixer / Auditor 修复)
  manual: <message>    老板手改
  regen: <message>     重生成
  [draft]: <message>   Reviser 草稿修改
"""
from __future__ import annotations

import subprocess
from pathlib import Path


def _repo_root(book_dir: Path | None = None) -> Path:
    """Resolve the Git repository owning ``book_dir`` (source repo if omitted)."""
    start = (book_dir or Path(__file__).resolve().parents[2]).resolve()
    if start.is_file():
        start = start.parent
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], cwd=str(start),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(f"找不到书稿所属的本地版本仓: {start}")
    return Path(result.stdout.strip()).resolve()


def repo_root_for_book(book_dir: Path) -> Path:
    """Compatibility seam for callers/tests that previously patched zero-arg `_repo_root`."""
    try:
        return _repo_root(book_dir)
    except TypeError:
        return _repo_root()


def ensure_local_repository(data_root: Path) -> Path:
    """Create the author data repository when it is not already in a Git worktree."""
    data_root = data_root.expanduser().resolve()
    data_root.mkdir(parents=True, exist_ok=True)
    probe = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], cwd=str(data_root),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    initialized = probe.returncode != 0
    if not initialized:
        root = Path(probe.stdout.strip()).resolve()
    else:
        subprocess.run(
            ["git", "init"], cwd=str(data_root), capture_output=True, text=True,
            encoding="utf-8", errors="replace", check=True,
        )
        root = data_root
    if initialized:
        _run_git("config", "user.name", "Biyu Local", cwd=root)
        _run_git("config", "user.email", "biyu@local", cwd=root)
    return root


def _run_git(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Run a git command and return the result. Raises on failure."""
    cwd = cwd or _repo_root()
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result


def _book_rel_path(book_dir: Path, chapter_id: int) -> str:
    """Return the repo-relative path to a chapter file."""
    repo_root = repo_root_for_book(book_dir)
    rel = book_dir.resolve().relative_to(repo_root)
    return (rel / "chapters" / f"ch{chapter_id}.md").as_posix()


def _pending_rel_path(book_dir: Path, chapter_id: int) -> str:
    """Return the repo-relative path to a _pending chapter file."""
    repo_root = repo_root_for_book(book_dir)
    rel = book_dir.resolve().relative_to(repo_root)
    return (rel / "chapters" / "_pending" / f"ch{chapter_id}.md").as_posix()


# ---------------------------------------------------------------------------
# Core: commit
# ---------------------------------------------------------------------------

def commit_chapter(
    book_dir: Path,
    chapter_id: int,
    message: str,
    *,
    auto: bool = True,
) -> str:
    """Commit a chapter file with the appropriate prefix.

    Args:
        book_dir: Absolute path to the book directory.
        chapter_id: Chapter number.
        message: Commit body (without prefix).
        auto: True for automated changes, False for manual edits.

    Returns:
        The commit hash.
    """
    prefix = "auto" if auto else "manual"
    commit_msg = f"{prefix}: CH{chapter_id} {message}"

    # Determine which file to commit: chapters/ or _pending/
    chapter_path = book_dir / "chapters" / f"ch{chapter_id}.md"
    pending_path = book_dir / "chapters" / "_pending" / f"ch{chapter_id}.md"

    files_to_add: list[str] = []
    repo_root = repo_root_for_book(book_dir)

    if chapter_path.exists():
        rel = chapter_path.resolve().relative_to(repo_root).as_posix()
        files_to_add.append(rel)
    if pending_path.exists():
        rel = pending_path.resolve().relative_to(repo_root).as_posix()
        files_to_add.append(rel)

    # Also add audit_reports if it exists
    audit_path = book_dir / "audit_reports" / f"ch{chapter_id}.md"
    if audit_path.exists():
        rel = audit_path.resolve().relative_to(repo_root).as_posix()
        files_to_add.append(rel)

    if not files_to_add:
        raise FileNotFoundError(f"CH{chapter_id}: 未找到章节文件")

    _run_git("add", *files_to_add, cwd=repo_root)
    result = _run_git("commit", "-m", commit_msg, cwd=repo_root)
    # Extract short hash from output like "[main abc1234] ..."
    output = result.stdout.strip()
    for part in output.split():
        if part.startswith("["):
            continue
        if len(part) >= 7:
            return part[:7]
    return "unknown"


def commit_regen(
    book_dir: Path,
    chapter_id: int,
    message: str = "重生成",
) -> str:
    """Commit a regenerated chapter."""
    commit_msg = f"regen: CH{chapter_id} {message}"

    chapter_path = book_dir / "chapters" / f"ch{chapter_id}.md"
    repo_root = repo_root_for_book(book_dir)
    files_to_add: list[str] = []

    if chapter_path.exists():
        files_to_add.append(chapter_path.resolve().relative_to(repo_root).as_posix())

    # Also add logs
    log_dir = book_dir / "logs" / f"ch{chapter_id}"
    if log_dir.exists():
        files_to_add.append(log_dir.resolve().relative_to(repo_root).as_posix())

    if not files_to_add:
        raise FileNotFoundError(f"CH{chapter_id}: 未找到章节文件")

    _run_git("add", *files_to_add, cwd=repo_root)
    result = _run_git("commit", "-m", commit_msg, cwd=repo_root)
    output = result.stdout.strip()
    for part in output.split():
        if part.startswith("["):
            continue
        if len(part) >= 7:
            return part[:7]
    return "unknown"


# ---------------------------------------------------------------------------
# Core: move between _pending and chapters
# ---------------------------------------------------------------------------

def move_to_chapters(book_dir: Path, chapter_id: int) -> bool:
    """Move a chapter from _pending/ to chapters/."""
    pending = book_dir / "chapters" / "_pending" / f"ch{chapter_id}.md"
    target = book_dir / "chapters" / f"ch{chapter_id}.md"

    if not pending.exists():
        # Already in chapters/ or doesn't exist — idempotent
        return target.exists()

    if target.exists():
        target.unlink()

    repo_root = repo_root_for_book(book_dir)
    pending_rel = pending.resolve().relative_to(repo_root).as_posix()
    target_rel = target.resolve().relative_to(repo_root).as_posix()

    _run_git("mv", pending_rel, target_rel, cwd=repo_root)
    return True


def commit_adoption(
    book_dir: Path,
    chapter_id: int,
    recycle_path: Path | None = None,
) -> str:
    """Commit only the files participating in one workbench adoption.

    The pending deletion, official file and optional recycled former official
    are staged together so a failed commit can be rolled back as one unit by
    the caller without touching unrelated user changes.
    """
    repo_root = repo_root_for_book(book_dir)
    paths = [
        book_dir / "chapters" / "_pending" / f"ch{chapter_id}.md",
        book_dir / "chapters" / f"ch{chapter_id}.md",
    ]
    if recycle_path is not None:
        paths.append(recycle_path)

    rel_paths = []
    for path in paths:
        rel = path.resolve().relative_to(repo_root).as_posix()
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", rel], cwd=str(repo_root),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        ).returncode == 0
        if path.exists() or tracked:
            rel_paths.append(rel)
    if not rel_paths:
        raise FileNotFoundError(f"CH{chapter_id}: 没有可采用的正文文件")
    # Force a content rehash for the tracked official file. On fast Windows
    # moves, old/new drafts can share size and mtime and otherwise look clean.
    official_rel = paths[1].resolve().relative_to(repo_root).as_posix()
    if paths[1].exists():
        _run_git("add", "--renormalize", "--", official_rel, cwd=repo_root)
    _run_git("add", "-A", "--", *rel_paths, cwd=repo_root)
    try:
        result = _run_git(
            "commit",
            "-m",
            f"manual: CH{chapter_id} 作者采用为正式正文",
            "--",
            *rel_paths,
            cwd=repo_root,
        )
    except Exception:
        # Only clear this transaction's index entries; never rewrite worktree.
        _run_git("restore", "--staged", "--", *rel_paths, cwd=repo_root)
        raise

    return _run_git("rev-parse", "--short", "HEAD", cwd=repo_root).stdout.strip()


# ---------------------------------------------------------------------------
# Query: history / diff
# ---------------------------------------------------------------------------

def get_chapter_history(
    book_dir: Path,
    chapter_id: int,
    max_entries: int = 20,
) -> list[dict]:
    """Get the commit history for a chapter file.

    Returns list of dicts with keys: hash, date, author, message.
    """
    # Check both possible locations
    chapter_rel = _book_rel_path(book_dir, chapter_id)
    pending_rel = _pending_rel_path(book_dir, chapter_id)

    paths = []
    repo_root = repo_root_for_book(book_dir)
    ch_path = repo_root / chapter_rel
    pend_path = repo_root / pending_rel
    if ch_path.exists():
        paths.append(chapter_rel)
    if pend_path.exists():
        paths.append(pending_rel)

    if not paths:
        # Try git log even if file doesn't exist locally (deleted)
        paths.append(chapter_rel)

    result = _run_git(
        "log", f"--max-count={max_entries}",
        "--pretty=format:%h|%ai|%an|%s",
        "--",
        *paths,
        cwd=repo_root,
    )

    entries = []
    for line in result.stdout.strip().splitlines():
        if not line.strip():
            continue
        parts = line.split("|", 3)
        if len(parts) >= 4:
            entries.append({
                "hash": parts[0],
                "date": parts[1],
                "author": parts[2],
                "message": parts[3],
            })
    return entries


def diff_chapter(
    book_dir: Path,
    chapter_id: int,
    from_ref: str | None = None,
    to_ref: str | None = None,
) -> str:
    """Get the diff for a chapter between two commits.

    If from_ref is None, uses the previous commit for the file.
    If to_ref is None, uses HEAD.
    """
    chapter_rel = _book_rel_path(book_dir, chapter_id)

    if from_ref is None:
        # Get the last two commits for this file and diff them
        history = get_chapter_history(book_dir, chapter_id, max_entries=2)
        if len(history) >= 2:
            from_ref = history[1]["hash"]
        else:
            return "（仅一个版本，无 diff 可显示）"

    to_ref = to_ref or "HEAD"

    try:
        result = _run_git("diff", f"{from_ref}..{to_ref}", "--", chapter_rel, cwd=repo_root_for_book(book_dir))
        return result.stdout or "（无差异）"
    except RuntimeError:
        return "（diff 获取失败）"


def rollback_chapter(
    book_dir: Path,
    chapter_id: int,
    target_commit: str,
) -> bool:
    """Roll back a chapter file to a specific commit version."""
    chapter_rel = _book_rel_path(book_dir, chapter_id)
    repo_root = repo_root_for_book(book_dir)

    try:
        # Restore the file from the target commit
        _run_git("checkout", target_commit, "--", chapter_rel, cwd=repo_root)
        # Commit the rollback
        _run_git("add", chapter_rel, cwd=repo_root)
        _run_git("commit", "-m", f"manual: CH{chapter_id} 回滚到 {target_commit[:7]}", cwd=repo_root)
        return True
    except RuntimeError:
        return False


# ---------------------------------------------------------------------------
# Reviser commits (T-P3-D-3)
# ---------------------------------------------------------------------------

def commit_reviser_change(
    book_dir: Path,
    chapter_id: int,
    issue_id: str,
) -> str:
    """Commit a Reviser change with [draft] prefix.

    Args:
        book_dir: Absolute path to the book directory.
        chapter_id: Chapter number.
        issue_id: Issue ID (e.g., ch27-001).

    Returns:
        The commit hash.
    """
    commit_msg = f"[draft]: CH{chapter_id} Reviser 修复 {issue_id}"

    chapter_path = book_dir / "chapters" / f"ch{chapter_id}.md"
    pending_path = book_dir / "chapters" / "_pending" / f"ch{chapter_id}.md"
    repo_root = repo_root_for_book(book_dir)
    files_to_add: list[str] = []

    if chapter_path.exists():
        files_to_add.append(chapter_path.resolve().relative_to(repo_root).as_posix())
    if pending_path.exists():
        files_to_add.append(pending_path.resolve().relative_to(repo_root).as_posix())

    # Also add audit_reports JSON + MD
    audit_json = book_dir / "audit_reports" / f"ch{chapter_id}.json"
    audit_md = book_dir / "audit_reports" / f"ch{chapter_id}.md"
    if audit_json.exists():
        files_to_add.append(audit_json.resolve().relative_to(repo_root).as_posix())
    if audit_md.exists():
        files_to_add.append(audit_md.resolve().relative_to(repo_root).as_posix())

    if not files_to_add:
        raise FileNotFoundError(f"CH{chapter_id}: 未找到章节文件")

    _run_git("add", *files_to_add, cwd=repo_root)
    result = _run_git("commit", "-m", commit_msg, cwd=repo_root)
    output = result.stdout.strip()
    for part in output.split():
        if part.startswith("["):
            continue
        if len(part) >= 7:
            return part[:7]
    return "unknown"


def commit_finalize(
    book_dir: Path,
    chapter_id: int,
) -> str:
    """Commit a finalized chapter (all issues resolved).

    Args:
        book_dir: Absolute path to the book directory.
        chapter_id: Chapter number.

    Returns:
        The commit hash.
    """
    commit_msg = f"auto: CH{chapter_id} 定稿（所有 issue 已处理）"

    chapter_path = book_dir / "chapters" / f"ch{chapter_id}.md"
    pending_path = book_dir / "chapters" / "_pending" / f"ch{chapter_id}.md"
    repo_root = repo_root_for_book(book_dir)
    files_to_add: list[str] = []

    if chapter_path.exists():
        files_to_add.append(chapter_path.resolve().relative_to(repo_root).as_posix())
    if pending_path.exists():
        files_to_add.append(pending_path.resolve().relative_to(repo_root).as_posix())

    # Also add audit_reports
    audit_json = book_dir / "audit_reports" / f"ch{chapter_id}.json"
    audit_md = book_dir / "audit_reports" / f"ch{chapter_id}.md"
    if audit_json.exists():
        files_to_add.append(audit_json.resolve().relative_to(repo_root).as_posix())
    if audit_md.exists():
        files_to_add.append(audit_md.resolve().relative_to(repo_root).as_posix())

    if not files_to_add:
        raise FileNotFoundError(f"CH{chapter_id}: 未找到章节文件")

    _run_git("add", *files_to_add, cwd=repo_root)
    result = _run_git("commit", "-m", commit_msg, cwd=repo_root)
    output = result.stdout.strip()
    for part in output.split():
        if part.startswith("["):
            continue
        if len(part) >= 7:
            return part[:7]
    return "unknown"


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def get_recent_commits(max_entries: int = 10) -> list[dict]:
    """Get recent commits across the whole repo."""
    result = _run_git(
        "log", f"--max-count={max_entries}",
        "--pretty=format:%h|%ai|%s",
    )
    entries = []
    for line in result.stdout.strip().splitlines():
        if not line.strip():
            continue
        parts = line.split("|", 2)
        if len(parts) >= 3:
            entries.append({
                "hash": parts[0],
                "date": parts[1],
                "message": parts[2],
            })
    return entries


def get_cost_from_log(book_dir: Path) -> float:
    """Sum total cost from cost_log.csv."""
    cost_path = book_dir / "logs" / "cost_log.csv"
    if not cost_path.exists():
        return 0.0
    total = 0.0
    import csv
    with open(cost_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                total += float(row["cost_cny"])
            except (ValueError, KeyError):
                pass
    return total
