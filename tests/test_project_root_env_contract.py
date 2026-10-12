"""2026-10 修复:安装运行包读不到 checkout 的私有配置。

get_project_root() 此前纯按 __file__ 推算,安装包(.venv/site-packages)会落到
.venv/Lib,README 教用户建的私有 config/models.yaml 永远读不到,示例目录顶上。
现优先读启动器设置的 BIYU_PROJECT_ROOT。
"""
from __future__ import annotations

from pathlib import Path

from biyu.config import get_config_path, get_project_root


def test_project_root_honors_env_and_finds_private_config(tmp_path, monkeypatch) -> None:
    (tmp_path / "config").mkdir()
    private = tmp_path / "config" / "models.yaml"
    private.write_text(
        "providers: {}\nmodels: {mymodel: {provider: deepseek, model_id: x}}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("BIYU_PROJECT_ROOT", str(tmp_path))

    assert get_project_root() == tmp_path.resolve()
    assert get_config_path() == private.resolve()


def test_project_root_without_env_falls_back_to_source_tree(monkeypatch) -> None:
    monkeypatch.delenv("BIYU_PROJECT_ROOT", raising=False)
    root = get_project_root()
    # 测试跑在源码 checkout 里:回退推断应命中仓库根(有 pyproject.toml 与 src/biyu)
    assert (root / "pyproject.toml").is_file()
    assert (root / "src" / "biyu" / "config.py").is_file()


def test_env_pointing_at_bare_dir_falls_to_example_without_crash(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BIYU_PROJECT_ROOT", str(tmp_path))
    path = get_config_path()  # 不崩溃,退到某个 example
    assert path.name.startswith("models.yaml")
