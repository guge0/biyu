"""S-3B 缺陷2:数据根落在源码仓树内时,书稿必须有自己可提交的 git 仓。

现象(中枢实测):数据根在源码仓树内(即使 gitignore 目录)时,
ensure_local_repository 因 rev-parse 成功而拒绝自建仓,
repo_root_for_book 的守卫兜底又只会把外层源码仓根原样返回,
adopt 的 git add 撞外层忽略规则退出 1。
真实用户根(%APPDATA%)不在任何仓内,不受影响。
"""
from __future__ import annotations

import subprocess
from pathlib import Path


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )


def _make_fake_source_repo(tmp_path: Path) -> Path:
    """带笔驭源码仓指纹(pyproject.toml)的真实 git 仓;数据根模拟为其中被忽略的子目录。"""
    root = tmp_path / "biyu-dev-fake"
    root.mkdir()
    (root / "pyproject.toml").write_text("[project]\nname = 'biyu'\n", encoding="utf-8")
    (root / "src" / "biyu").mkdir(parents=True)
    (root / "src" / "biyu" / "config.py").write_text("# fingerprint\n", encoding="utf-8")
    (root / ".gitignore").write_text(".test-data/\n", encoding="utf-8")
    assert _git("init", cwd=root).returncode == 0
    _git("config", "user.name", "Keeper", cwd=root)
    _git("config", "user.email", "keeper@example", cwd=root)
    return root


def _make_plain_repo(tmp_path: Path) -> Path:
    root = tmp_path / "plain-repo"
    root.mkdir()
    (root / "readme.txt").write_text("not biyu\n", encoding="utf-8")
    assert _git("init", cwd=root).returncode == 0
    return root


def test_ensure_local_repository_self_builds_inside_source_repo(tmp_path) -> None:
    from biyu.git_helper import ensure_local_repository

    source = _make_fake_source_repo(tmp_path)
    data_root = source / ".test-data" / "BiyuTestData"
    root = ensure_local_repository(data_root)
    assert root == data_root
    assert (data_root / ".git").is_dir()
    probe = _git("rev-parse", "--show-toplevel", cwd=data_root)
    assert probe.returncode == 0
    assert Path(probe.stdout.strip()).resolve() == data_root.resolve()


def test_ensure_local_repository_keeps_non_source_outer_repo(tmp_path) -> None:
    """外层是普通仓(无源码仓指纹)时保持既有语义:不自建,归外层仓。"""
    from biyu.git_helper import ensure_local_repository

    outer = _make_plain_repo(tmp_path)
    data_root = outer / "data-root"
    root = ensure_local_repository(data_root)
    assert root == outer.resolve()
    assert not (data_root / ".git").exists()


def test_ensure_local_repository_normal_root_still_inits(tmp_path) -> None:
    from biyu.git_helper import ensure_local_repository

    data_root = tmp_path / "normal-root"
    root = ensure_local_repository(data_root)
    assert root == data_root
    assert (data_root / ".git").is_dir()


def test_ensure_local_repository_never_clobbers_source_repo_identity(tmp_path) -> None:
    """数据根本身就是源码仓根(误配)时绝不改写外层仓身份,也不重复 init。"""
    from biyu.git_helper import ensure_local_repository

    source = _make_fake_source_repo(tmp_path)
    root = ensure_local_repository(source)
    assert root == source.resolve()
    name = _git("config", "user.name", cwd=source).stdout.strip()
    assert name == "Keeper"


def test_repo_root_for_book_gives_book_own_repo_inside_source_repo(tmp_path) -> None:
    """守卫兜底:书在源码仓树内且无更近的书稿仓时,必须拿到能真实 git add 的仓。"""
    from biyu.git_helper import repo_root_for_book

    source = _make_fake_source_repo(tmp_path)
    book = source / ".test-data" / "BiyuTestData" / "some-book"
    (book / "chapters").mkdir(parents=True)
    (book / "chapters" / "ch1.md").write_text("第一章", encoding="utf-8")

    root = repo_root_for_book(book)
    assert root != source.resolve(), "书稿仓绝不能落到源码仓根"
    assert (root / ".git").is_dir()

    # 缺陷复现路径:对书稿文件 git add 必须成功(旧代码撞外层忽略规则退出 1)
    rel = book.resolve().relative_to(root).as_posix()
    added = _git("add", f"{rel}/chapters/ch1.md", cwd=root)
    assert added.returncode == 0, added.stderr


def test_source_repo_toplevel_containing_detects_and_skips(tmp_path) -> None:
    from biyu.git_helper import source_repo_toplevel_containing

    source = _make_fake_source_repo(tmp_path)
    nested = source / ".test-data"
    nested.mkdir()
    plain = _make_plain_repo(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()

    assert source_repo_toplevel_containing(nested).resolve() == source.resolve()
    assert source_repo_toplevel_containing(plain) is None
    assert source_repo_toplevel_containing(outside) is None
    assert source_repo_toplevel_containing(tmp_path / "ghost") is None


def test_startup_warning_fires_only_for_source_repo_roots(tmp_path, monkeypatch, caplog) -> None:
    """启动自检告警:数据根在源码仓树内时 warning,否则静默。"""
    import asyncio
    import logging

    from biyu.ui import app as app_module

    handler = app_module.s3b_warn_data_root_inside_source_repo

    source = _make_fake_source_repo(tmp_path)
    monkeypatch.setattr(
        "biyu.git_helper.source_repo_toplevel_containing",
        lambda _path: source.resolve(),
    )
    with caplog.at_level(logging.WARNING, logger="biyu.ui"):
        asyncio.run(handler())
    assert any("源码仓树内" in r.message for r in caplog.records)

    caplog.clear()
    monkeypatch.setattr(
        "biyu.git_helper.source_repo_toplevel_containing",
        lambda _path: None,
    )
    with caplog.at_level(logging.WARNING, logger="biyu.ui"):
        asyncio.run(handler())
    assert not any("源码仓树内" in r.message for r in caplog.records)
