from __future__ import annotations

import inspect
import subprocess
from pathlib import Path

import pytest


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _truth_snapshot(book_dir: Path) -> dict[str, tuple[str, int]]:
    result: dict[str, tuple[str, int]] = {}
    for name in ("current_state.md", "particle_ledger.md", "pending_hooks.md"):
        path = book_dir / "truth_files" / name
        result[name] = (path.read_text(encoding="utf-8"), path.stat().st_mtime_ns)
    return result


def test_observer_not_called_on_generate(tmp_path: Path) -> None:
    """候选稿落盘不能再碰 Observer 或三份长期记忆。"""
    from biyu.pipeline import _chapter_output_path, generate_chapter

    book = tmp_path / "Book"
    for name in ("current_state.md", "particle_ledger.md", "pending_hooks.md"):
        _write(book / "truth_files" / name, f"原记忆-{name}\n")
    before = _truth_snapshot(book)

    source = inspect.getsource(generate_chapter)
    assert "update_truth_files(" not in source
    candidate = _chapter_output_path(book / "chapters", 1, pending=True)
    _write(candidate, "未采用候选稿")

    assert _truth_snapshot(book) == before


def test_observer_called_on_adopt_and_reads_official_path(tmp_path: Path) -> None:
    from biyu.cli import workbench_cmd as cmd

    book = tmp_path / "Book"
    _write(book / "chapters/_pending/ch1.md", "作者采用的正文")
    seen: list[Path] = []

    def observer(book_dir: Path, chapter: int, official_path: Path) -> bool:
        assert book_dir == book and chapter == 1
        assert official_path == book / "chapters/ch1.md"
        assert official_path.read_text(encoding="utf-8") == "作者采用的正文"
        seen.append(official_path)
        _write(book / "truth_files/current_state.md", "来自正式稿")
        return True

    result = cmd._adopt_pending(
        book,
        1,
        commit_fn=lambda *_args: "abc1234",
        observer_runner=observer,
    )

    assert result.commit_hash == "abc1234"
    assert seen == [book / "chapters/ch1.md"]
    assert cmd.read_memory_dirty(book, 1) is False


def test_adopt_idempotent_for_same_candidate_projection(tmp_path: Path) -> None:
    from biyu.cli import workbench_cmd as cmd

    book = tmp_path / "Book"

    def observer(_book: Path, chapter: int, official_path: Path) -> bool:
        # 投影式覆盖，不追加；同一正式稿重跑结果必须逐字一致。
        _write(
            book / "truth_files/current_state.md",
            f"ch{chapter}:{official_path.read_text(encoding='utf-8')}",
        )
        return True

    for _ in range(2):
        _write(book / "chapters/_pending/ch1.md", "同一候选稿")
        cmd._adopt_pending(
            book,
            1,
            commit_fn=lambda *_args: "abc1234",
            observer_runner=observer,
        )
        current = (book / "truth_files/current_state.md").read_text(encoding="utf-8")
        assert current == "ch1:同一候选稿"


def test_observer_fail_keeps_official_and_memory_dirty(tmp_path: Path) -> None:
    from biyu.cli import workbench_cmd as cmd

    book = tmp_path / "Book"
    _write(book / "chapters/_pending/ch1.md", "已由作者采用")

    result = cmd._adopt_pending(
        book,
        1,
        commit_fn=lambda *_args: "abc1234",
        observer_runner=lambda *_args: (_ for _ in ()).throw(RuntimeError("observer down")),
    )

    assert result.memory_updated is False
    assert (book / "chapters/ch1.md").read_text(encoding="utf-8") == "已由作者采用"
    assert not (book / "chapters/_pending/ch1.md").exists()
    assert cmd.read_memory_dirty(book, 1) is True


def test_adopt_git_failure_rolls_back_file_moves(tmp_path: Path) -> None:
    from biyu.cli import workbench_cmd as cmd

    book = tmp_path / "Book"
    _write(book / "chapters/ch1.md", "旧正式稿")
    _write(book / "chapters/_pending/ch1.md", "新候选稿")

    with pytest.raises(RuntimeError, match="commit failed"):
        cmd._adopt_pending(
            book,
            1,
            commit_fn=lambda *_args: (_ for _ in ()).throw(RuntimeError("commit failed")),
            observer_runner=lambda *_args: True,
        )

    assert (book / "chapters/ch1.md").read_text(encoding="utf-8") == "旧正式稿"
    assert (book / "chapters/_pending/ch1.md").read_text(encoding="utf-8") == "新候选稿"
    assert list((book / "logs/ch1/trash").glob("*.md")) == []


def test_memory_dirty_is_visible_and_has_a_retry_action(tmp_path: Path) -> None:
    from biyu.cli import workbench_cmd as cmd
    import biyu.ui.workbench as wb
    from biyu.ui.action_registry import action_for

    book = tmp_path / "Book"
    _write(book / "chapters/ch1.md", "正式正文")
    cmd._set_memory_dirty(book, 1, True, "observer down")

    snapshot = wb.chapter_snapshot(book, 1)
    assert snapshot["memory_dirty"] is True
    assert snapshot["actions"]["refresh_memory"]["enabled"] is True
    assert action_for("refresh_memory", book="Book", chapter=1).argv[:1] == ("refresh",)

    html = Path("src/biyu/ui/static/workbench.html").read_text(encoding="utf-8")
    assert "这一章的记忆还没更新" in html
    assert 'data-action="refresh_memory"' in html


def test_official_projection_restores_pre_chapter_base_before_retry(tmp_path: Path) -> None:
    import asyncio
    from types import SimpleNamespace

    from biyu.observer import update_official_chapter_projection

    book = tmp_path / "Book"
    official = _write(book / "chapters/ch1.md", "正式正文唯一事实")
    for name in ("current_state.md", "particle_ledger.md", "pending_hooks.md"):
        _write(book / "truth_files" / name, f"基线-{name}")

    prompts: list[str] = []

    class Adapter:
        async def generate(self, messages):
            prompt = messages[0]["content"]
            prompts.append(prompt)
            assert "投影结果" not in prompt
            return SimpleNamespace(
                text=(
                    "=== current_state ===\n投影结果\n"
                    "=== particle_ledger ===\n| 1 | 投影结果 |\n"
                    "=== pending_hooks ===\n投影结果"
                ),
                cost=0.0,
            )

    first = asyncio.run(update_official_chapter_projection(book, 1, official, Adapter()))
    first_truth = _truth_snapshot(book)
    second = asyncio.run(update_official_chapter_projection(book, 1, official, Adapter()))
    second_truth = _truth_snapshot(book)

    assert first is second is True
    assert {key: value[0] for key, value in first_truth.items()} == {
        key: value[0] for key, value in second_truth.items()
    }
    assert len(prompts) == 2


def test_commit_adoption_records_official_pending_and_recycle_together(tmp_path: Path, monkeypatch) -> None:
    from biyu.cli import workbench_cmd as cmd
    import biyu.git_helper as git_helper

    book = tmp_path / "data/Book"
    _write(book / "chapters/ch1.md", "旧正式稿")
    _write(book / "chapters/_pending/ch1.md", "新候选稿")
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "baseline"], cwd=tmp_path, check=True, capture_output=True)
    monkeypatch.setattr(git_helper, "_repo_root", lambda: tmp_path)

    cmd._adopt_pending(
        book,
        1,
        commit_fn=git_helper.commit_adoption,
        observer_runner=lambda *_args: True,
    )

    changed = subprocess.run(
        ["git", "show", "--no-renames", "--name-status", "--format=", "HEAD"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    assert "data/Book/chapters/ch1.md" in changed
    assert "data/Book/chapters/_pending/ch1.md" in changed
    assert "data/Book/logs/ch1/trash/official_" in changed


def test_rebuild_memory_backs_up_then_projects_official_chapters_only(tmp_path: Path) -> None:
    import asyncio
    from types import SimpleNamespace

    from biyu.observer import rebuild_hooks

    book = tmp_path / "Book"
    _write(book / "chapters/ch1.md", "正式事实")
    _write(book / "chapters/_pending/ch1.md", "候选污染，绝不能读取")
    _write(book / "truth_files/current_state.md", "候选污染状态")
    _write(book / "truth_files/particle_ledger.md", "候选污染账")
    _write(book / "truth_files/pending_hooks.md", "候选污染伏笔")
    _write(book / "truth_files/history/ch1/old.md", "旧快照也必须进入备份")
    _write(book / "characters.yaml", "characters: []\n")

    prompts: list[str] = []

    class Adapter:
        async def generate(self, messages):
            prompt = messages[0]["content"]
            prompts.append(prompt)
            return SimpleNamespace(
                text=(
                    "=== current_state ===\n正式投影\n"
                    "=== particle_ledger ===\n正式投影\n"
                    "=== pending_hooks ===\n正式投影"
                ),
                cost=0.0,
            )

    costs: list[tuple[int, float, float]] = []
    result = asyncio.run(rebuild_hooks(
        book,
        Adapter(),
        _log_cost_fn=lambda chapter, cost, latency: costs.append((chapter, cost, latency)),
    ))

    backup = book / "truth_files/backup_pre_env4"
    assert (backup / "current_state.md").read_text(encoding="utf-8") == "候选污染状态"
    assert (backup / "history/ch1/old.md").read_text(encoding="utf-8") == "旧快照也必须进入备份"
    assert (book / "truth_files/current_state.md").read_text(encoding="utf-8") == "正式投影"
    assert len(prompts) == 1
    assert "正式事实" in prompts[0]
    assert "候选污染，绝不能读取" not in prompts[0]
    assert result["chapters_processed"] == 1 and result["errors"] == []
    assert result["backup_path"] == str(backup)
    assert result["diff"]["truth_files/current_state.md"]["changed"] is True
    assert len(costs) == 1 and costs[0][0:2] == (1, 0.0)


def test_rebuild_memory_command_is_registered() -> None:
    from pathlib import Path

    main_source = Path("src/biyu/cli/main.py").read_text(encoding="utf-8")
    command_source = Path("src/biyu/cli/refresh_cmd.py").read_text(encoding="utf-8")
    assert '@app.command(name="rebuild-memory")' in main_source
    assert "def rebuild_memory_command(" in command_source
