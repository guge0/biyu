"""S-3C · UI 层快速模型别名解析(便携包/首启目录可用性修复)。

背景(2026-10-27 异常矩阵实锤):ui 五处(向导 premise/责编对话/起名/纪要/细纲起草)
硬编码 `get_adapter("v4_flash")`。开发机私有 models.yaml 定义了 v4_flash,但
干净机/便携包只有免 Key 的 models.yaml.example(别名是 deepseek-r1/deepseek-v3 等),
没有 v4_flash → 作者保存 Key 后这些功能仍报「不可用/请保存 Key」,责编对话静默降级。

解析顺序:
1. v4_flash(老板裁定的快速档;开发机私有配置在,行为不变);
2. 作者在连接设置选中的模型(selected_model——作者实际选了什么就用什么);
3. 管线 writer 档别名;
4. 目录里首个非 embedding 别名。
全部失败时抛最后一个异常,由调用方既有的「不可用:请先保存 Key」人话文案承接。
"""
from __future__ import annotations

from typing import Any

from biyu.secure_config import load_setup

DEFAULT_FAST_ALIAS = "v4_flash"


def resolve_ui_adapter(registry: Any, *, prefer: str = DEFAULT_FAST_ALIAS) -> tuple[Any, str]:
    """按解析顺序取第一个可用的 adapter,返回 (adapter, 实际用的别名)。"""
    last_error: Exception | None = None
    for alias in _candidate_aliases(registry, prefer):
        try:
            return registry.get_adapter(alias), alias
        except (KeyError, ValueError, FileNotFoundError) as exc:
            last_error = exc
    assert last_error is not None
    raise last_error


def _candidate_aliases(registry: Any, prefer: str) -> list[str]:
    candidates: list[str] = [prefer]
    selected = ""
    try:
        selected = str(load_setup().get("selected_model", "") or "").strip()
    except Exception:
        selected = ""
    if selected:
        candidates.append(selected)
    writer = ""
    try:
        writer = str((registry.get_pipeline_config() or {}).get("writer", "") or "").strip()
    except Exception:
        writer = ""
    if writer:
        candidates.append(writer)
    models = getattr(registry, "_models", {}) or {}
    for alias in models:
        cfg = models.get(alias) if isinstance(models, dict) else None
        if isinstance(cfg, dict) and str(cfg.get("type", "")) != "embedding" and alias not in candidates:
            candidates.append(alias)
    return candidates
