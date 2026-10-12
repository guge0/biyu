"""2026-10 修复:写死的备用模型别名 v3 在开源示例目录里不存在。

全新安装(只有 models.yaml.example,别名为 deepseek-r1/deepseek-v3 等)第一次
跑导演或必检项核对会直接 KeyError: Unknown model alias: v3。
降级适配器改为按 planner_fallback → writer 解析,解析不到返回 None 跳过兜底。
"""
from __future__ import annotations

from pathlib import Path

import yaml

from biyu.pipeline import _degraded_fallback_adapter


def _make_registry(tmp_path: Path, models: dict, pipeline: dict):
    from biyu.llm.registry import ModelRegistry

    cfg = tmp_path / "models.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "providers": {
                    "deepseek": {
                        "base_url": "https://api.example.com/v1",
                        "api_key_env": "BIYU_TEST_KEY_X",
                    }
                },
                "models": models,
                "pipeline": pipeline,
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    return ModelRegistry(cfg)


def test_fallback_resolves_writer_alias_when_v3_absent(tmp_path) -> None:
    """示例目录形态:没有 v3,只有 deepseek 系别名 → 兜底解析到 writer 档。"""
    registry = _make_registry(
        tmp_path,
        models={
            "deepseek-r1": {"provider": "deepseek", "model_id": "deepseek-reasoner"},
            "deepseek-v3": {"provider": "deepseek", "model_id": "deepseek-chat"},
        },
        pipeline={"planner": "deepseek-r1", "writer": "deepseek-v3"},
    )
    adapter = _degraded_fallback_adapter(registry)
    assert adapter is not None
    assert type(adapter).__name__ == "DeepSeekAdapter"


def test_fallback_prefers_planner_fallback_key(tmp_path) -> None:
    registry = _make_registry(
        tmp_path,
        models={
            "r1": {"provider": "deepseek", "model_id": "deepseek-reasoner"},
            "cheap": {"provider": "deepseek", "model_id": "deepseek-chat"},
        },
        pipeline={"planner": "r1", "writer": "r1", "planner_fallback": "cheap"},
    )
    adapter = _degraded_fallback_adapter(registry)
    assert adapter is not None


def test_fallback_returns_none_when_nothing_resolves(tmp_path) -> None:
    """目录里啥都解析不到 → None,主路径不被兜底缺失阻断。"""
    registry = _make_registry(tmp_path, models={}, pipeline={})
    assert _degraded_fallback_adapter(registry) is None
