"""First-run setup wizard API with user-level secret storage."""
from __future__ import annotations

import json
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException

from biyu.config import get_config_path, get_data_root
from biyu.llm import ModelRegistry
from biyu.secure_config import load_provider_secret, load_setup, save_setup, store_provider_secret

router = APIRouter(prefix="/api/setup", tags=["setup"])


def _catalog() -> list[dict[str, str]]:
    try:
        raw = yaml.safe_load(get_config_path().read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return []
    providers = raw.get("providers", {})
    result = []
    for alias, model in raw.get("models", {}).items():
        if str(model.get("type", "")) == "embedding":
            continue
        provider = str(model.get("provider", ""))
        if provider not in providers and not model.get("api_key"):
            continue
        result.append({"alias": str(alias), "provider": provider, "label": str(model.get("model_id") or model.get("model_name") or alias)})
    return result


def _books() -> list[dict[str, str]]:
    result = []
    root = get_data_root()
    root.mkdir(parents=True, exist_ok=True)
    for path in sorted(root.iterdir()):
        if not path.is_dir() or not (path / "book.json").exists():
            continue
        try:
            meta = json.loads((path / "book.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        result.append({"id": str(meta.get("id") or path.name), "title": str(meta.get("title") or meta.get("display_name") or path.name)})
    return result


def _configured_without_wizard() -> bool:
    try:
        registry = ModelRegistry(get_config_path())
        for alias in registry.available_models:
            cfg = registry._resolve_model_config(alias)
            key = str(cfg.get("api_key", ""))
            if key and not key.startswith("${") and "在此填入" not in key:
                return True
    except Exception:
        return False
    return False


@router.get("/status")
def setup_status() -> dict[str, Any]:
    settings = load_setup()
    selected = str(settings.get("selected_model", ""))
    catalog = _catalog()
    providers = {item["provider"] for item in catalog}
    configured_providers = {provider: bool(load_provider_secret(provider)) for provider in sorted(providers)}
    provider = next((item["provider"] for item in catalog if item["alias"] == selected), "")
    ready = bool(settings.get("complete") and selected and load_provider_secret(provider)) or _configured_without_wizard()
    return {
        "ready": ready,
        "selected_model": selected,
        "selected_book": str(settings.get("selected_book", "")),
        "models": catalog,
        "books": _books(),
        "configured_providers": configured_providers,
    }


def _create_book(title: str, genre: str) -> str:
    from biyu.book_service import create_book

    return create_book(title, genre, data_root=get_data_root()).book_id


@router.post("/complete")
async def complete_setup(payload: dict[str, Any]) -> dict[str, str]:
    model = str(payload.get("model", ""))
    selected = next((item for item in _catalog() if item["alias"] == model), None)
    if selected is None:
        raise HTTPException(status_code=400, detail="请选择列表中的模型")
    key = str(payload.get("api_key", "")).strip()
    if not key:
        raise HTTPException(status_code=400, detail="请填写 API Key")
    storage = store_provider_secret(selected["provider"], key)
    save_setup({"selected_model": model, "complete": False})
    try:
        adapter = ModelRegistry(get_config_path()).get_adapter(model)
        await adapter.generate([{"role": "user", "content": "连通性检查：只回复 OK"}], max_tokens=4)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"模型没有连通：{exc}") from exc
    book = str(payload.get("book", "")).strip()
    if payload.get("create_book"):
        title = str(payload.get("book_title", "")).strip()
        if not title:
            raise HTTPException(status_code=400, detail="请填写新书名")
        book = _create_book(title, str(payload.get("genre", "xuanhuan")))
    elif not any(item["id"] == book for item in _books()):
        raise HTTPException(status_code=400, detail="请选择一本已有的书，或新建一本")
    save_setup({"selected_model": model, "selected_book": book, "complete": True})
    return {"message": "设置完成，模型已连通", "model": model, "book": book, "secret_storage": storage}


@router.post("/update")
async def update_setup(payload: dict[str, Any]) -> dict[str, Any]:
    """Update the active model and optionally replace its provider secret."""
    model = str(payload.get("model", ""))
    selected = next((item for item in _catalog() if item["alias"] == model), None)
    if selected is None:
        raise HTTPException(status_code=400, detail="请选择列表中的模型")

    key = str(payload.get("api_key", "")).strip()
    if key:
        storage = store_provider_secret(selected["provider"], key)
    elif load_provider_secret(selected["provider"]):
        storage = "现有安全存储"
    else:
        raise HTTPException(status_code=400, detail="这个模型的服务商还没有配置 API Key")

    try:
        adapter = ModelRegistry(get_config_path()).get_adapter(model)
        await adapter.generate([{"role": "user", "content": "连通性检查：只回复 OK"}], max_tokens=4)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"模型没有连通：{exc}") from exc

    settings = load_setup()
    save_setup({
        "selected_model": model,
        "selected_book": str(settings.get("selected_book", "")),
        "complete": True,
    })
    return {
        "message": "连接设置已更新",
        "model": model,
        "key_configured": True,
        "secret_storage": storage,
    }
