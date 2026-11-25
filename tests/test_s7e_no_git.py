"""S-7e：便携包里 git 找不到时，开书与保存不能失败；包内 MinGit 能被找到。"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from biyu import git_helper


def _no_git(monkeypatch):
    monkeypatch.setattr(git_helper.shutil, "which", lambda _name: None)
    real_run = subprocess.run

    def fake_run(cmd, *a, **k):
        if cmd and cmd[0] == "git":
            raise FileNotFoundError("git")
        return real_run(cmd, *a, **k)

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(git_helper.subprocess, "run", fake_run)


def test_bundled_git_is_found(tmp_path: Path, monkeypatch):
    git_exe = tmp_path / "git" / "cmd" / "git.exe"
    git_exe.parent.mkdir(parents=True)
    git_exe.write_bytes(b"")
    monkeypatch.setattr(git_helper.shutil, "which", lambda _name: None)
    monkeypatch.setenv("BIYU_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("PATH", "C:\\nothing")
    assert git_helper.ensure_git_on_path() == str(git_exe)
    assert str(git_exe.parent) in __import__("os").environ["PATH"]


def test_create_book_without_git(tmp_path: Path, monkeypatch):
    _no_git(monkeypatch)
    monkeypatch.delenv("BIYU_PROJECT_ROOT", raising=False)
    from biyu.book_service import create_book

    created = create_book("没有git的书", "dushi", data_root=tmp_path / "data")
    assert created.book_dir.is_dir()
    assert (created.book_dir / "book.json").exists()


def test_run_git_without_git_raises_runtime_error(tmp_path: Path, monkeypatch):
    _no_git(monkeypatch)
    with pytest.raises(RuntimeError):
        git_helper._run_git("status", cwd=tmp_path)
    with pytest.raises(RuntimeError):
        git_helper.repo_root_for_book(tmp_path)
