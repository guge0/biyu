"""Auditor 配置读取。从 config/auditor.yaml 读取每个检查器的开关和阈值。"""
from __future__ import annotations

from pathlib import Path

import yaml


def _default_config() -> dict:
    """默认配置——所有检查器启用，使用默认阈值。"""
    return {
        "checkers": {
            "dedup": {"enabled": True, "jaccard_threshold": 0.7},
            "worldbook_check": {"enabled": True},
            "character_presence": {"enabled": True},
            "transition": {"enabled": True},
            "style_repeat": {"enabled": True, "max_per_chapter": 1, "max_per_3chapters": 2},
        },
    }


def load_auditor_config(project_root: Path | None = None) -> dict:
    """读取 config/auditor.yaml。

    不存在时返回默认配置（不阻塞 pipeline）。
    """
    if project_root is None:
        # 推断: biyu/src/biyu/auditor/config.py → biyu/
        project_root = Path(__file__).resolve().parents[3]

    config_path = project_root / "config" / "auditor.yaml"
    if not config_path.exists():
        return _default_config()

    with open(config_path, encoding="utf-8") as f:
        user_config = yaml.safe_load(f) or {}

    # 合并: 用户配置覆盖默认值
    merged = _default_config()
    if "checkers" in user_config:
        for name, cfg in user_config["checkers"].items():
            if name in merged["checkers"]:
                merged["checkers"][name].update(cfg)
            else:
                merged["checkers"][name] = cfg
    return merged


def get_checker_config(config: dict, checker_name: str) -> dict:
    """获取某个检查器的配置。不存在时返回空 dict。"""
    return config.get("checkers", {}).get(checker_name, {})
