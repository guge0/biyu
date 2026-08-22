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


def _provider_catalog() -> list[dict[str, Any]]:
    """Expose provider choices and their effective stage assignments."""
    try:
        raw = yaml.safe_load(get_config_path().read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return []
    models = raw.get("models", {})
    pipeline = raw.get("pipeline", {})
    recommendations = raw.get("provider_recommendations", {})
    providers = raw.get("providers", {})
    result = []
    for provider, cfg in providers.items():
        if not isinstance(cfg, dict):
            continue
        configured = recommendations.get(provider, {}) if isinstance(recommendations, dict) else {}
        assigned = {}
        for stage in ("planner", "writer", "polisher"):
            alias = configured.get(stage) or pipeline.get(stage)
            if alias and isinstance(models.get(alias), dict) and models.get(alias, {}).get("provider") == provider:
                assigned[stage] = models[alias].get("model_id", alias)
        if not assigned:
            provider_models = {a: m for a, m in models.items() if isinstance(m, dict) and m.get("provider") == provider and m.get("type") != "embedding"}
            ids = list(provider_models)
            if ids:
                planner = next((a for a in ids if "reason" in str(provider_models[a].get("model_id", "")).lower()), ids[0])
                writer = next((a for a in ids if "chat" in str(provider_models[a].get("model_id", "")).lower()), ids[0])
                assigned = {"planner": provider_models[planner].get("model_id", planner), "writer": provider_models[writer].get("model_id", writer), "polisher": provider_models[writer].get("model_id", writer)}
        if assigned:
            fallback = assigned.get("writer") or next(iter(assigned.values()))
            for stage in ("planner", "writer", "polisher"):
                assigned.setdefault(stage, fallback)
            result.append({"provider": provider, "label": {"deepseek": "DeepSeek", "glm": "智谱", "kimi": "Kimi", "doubao": "豆包"}.get(provider, provider), "models": assigned})
    custom = load_setup().get("custom_provider")
    if isinstance(custom, dict) and custom.get("model_id"):
        result.append({"provider": "custom", "models": {stage: custom["model_id"] for stage in ("planner", "writer", "polisher")}})
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
    active_provider = str(settings.get("provider", "")) or provider
    ready = bool(settings.get("complete") and (settings.get("provider") or selected) and (load_provider_secret(provider) or settings.get("provider") == "custom")) or _configured_without_wizard()
    return {
        "ready": ready,
        "selected_model": selected,
        "provider": active_provider,
        "selected_book": str(settings.get("selected_book", "")),
        "models": catalog,
        "books": _books(),
        "configured_providers": configured_providers,
        "providers": _provider_catalog(),
        "custom_provider": load_setup().get("custom_provider", {}),
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
    try:
        registry = ModelRegistry(get_config_path())
        adapter = registry.get_adapter_for_key(model, key) if hasattr(registry, "get_adapter_for_key") else registry.get_adapter(model)
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
    provider_name = str(payload.get("provider") or selected["provider"])
    extra_providers = _store_extra_provider_keys(payload, provider_name)
    save_setup({"provider": provider_name, "stage_overrides": payload.get("stage_overrides") or {}, "selected_book": book, "complete": True})
    return {"message": "设置完成，模型已连通", "provider": provider_name, "model": model, "book": book, "secret_storage": storage, "extra_providers": ",".join(extra_providers)}


@router.post("/update")
async def update_setup(payload: dict[str, Any]) -> dict[str, Any]:
    """Update the active model and optionally replace its provider secret."""
    if str(payload.get("provider", "")) == "custom":
        base_url = str(payload.get("base_url", "")).strip()
        model_id = str(payload.get("model_id", "")).strip()
        key = str(payload.get("api_key", "")).strip()
        if not base_url or not model_id:
            raise HTTPException(status_code=400, detail="请填写接口地址和模型 ID")
        if not key and not load_provider_secret("custom"):
            raise HTTPException(status_code=400, detail="还没有填 API Key，先填一个再选模型。")
        try:
            from biyu.llm.openai_compatible import OpenAICompatibleAdapter
            adapter = OpenAICompatibleAdapter(model_name=model_id, api_key=key or load_provider_secret("custom"), base_url=base_url)
            await adapter.generate([
                {"role": "system", "content": "你是连接测试。"},
                {"role": "user", "content": "只回复 OK"},
            ], max_tokens=16)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"连不上 {base_url}：{exc}。配置没有改动。") from exc
        if key:
            store_provider_secret("custom", key)
        old = load_setup()
        save_setup({**old, "custom_provider": {"base_url": base_url.rstrip("/"), "model_id": model_id}, "provider": "custom", "stage_overrides": payload.get("stage_overrides", {}), "complete": True})
        return {"message": "连接设置已更新", "provider": "custom", "model": model_id, "key_configured": True}

    model = str(payload.get("model", ""))
    selected = next((item for item in _catalog() if item["alias"] == model), None)
    if selected is None:
        raise HTTPException(status_code=400, detail="请选择列表中的模型")

    key = str(payload.get("api_key", "")).strip()
    existing_key = load_provider_secret(selected["provider"])
    if key or existing_key:
        storage = "新 Key（测试后保存）" if key else "现有安全存储"
        test_key = key or existing_key
    elif load_provider_secret(selected["provider"]):
        storage = "现有安全存储"
    else:
        raise HTTPException(status_code=400, detail="这个模型的服务商还没有配置 API Key")

    try:
        registry = ModelRegistry(get_config_path())
        adapter = registry.get_adapter_for_key(model, test_key) if hasattr(registry, "get_adapter_for_key") else registry.get_adapter(model)
        await adapter.generate([{"role": "user", "content": "连通性检查：只回复 OK"}], max_tokens=4)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"模型没有连通：{exc}") from exc

    if key:
        store_provider_secret(selected["provider"], key)
    extra_providers = _store_extra_provider_keys(payload, selected["provider"])
    settings = load_setup()
    provider_name = selected["provider"]
    save_setup({
        "provider": provider_name,
        "stage_overrides": payload.get("stage_overrides") or ({"writer": model} if model != _provider_default_alias(provider_name, "writer") else {}),
        "selected_book": str(settings.get("selected_book", "")),
        "complete": True,
    })
    return {
        "message": "连接设置已更新",
        "provider": provider_name,
        "key_configured": True,
        "secret_storage": storage,
        "extra_providers": ",".join(extra_providers),
    }


def _provider_default_alias(provider: str, stage: str) -> str:
    try:
        raw = yaml.safe_load(get_config_path().read_text(encoding="utf-8")) or {}
        return str((raw.get("provider_recommendations", {}).get(provider, {}) or {}).get(stage, ""))
    except (OSError, yaml.YAMLError):
        return ""


def _store_extra_provider_keys(payload: dict[str, Any], selected_provider: str) -> list[str]:
    """Save additional provider keys entered in the same setup dialog.

    The selected model remains the one that receives the connectivity check;
    extra keys are stored for later model selection and never returned.
    """
    raw = payload.get("provider_keys")
    if not isinstance(raw, dict):
        return []
    allowed = {str(item.get("provider", "")) for item in _provider_catalog()}
    allowed.update(str(item.get("provider", "")) for item in _catalog())
    stored: list[str] = []
    for provider, value in raw.items():
        provider_name, secret = str(provider).strip(), str(value).strip()
        if provider_name in allowed and secret and provider_name != selected_provider:
            store_provider_secret(provider_name, secret)
            stored.append(provider_name)
    return stored
