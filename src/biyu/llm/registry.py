from __future__ import annotations

import os
from pathlib import Path

import yaml

from biyu.secure_config import load_provider_secret, load_setup

from .base import LLMAdapter, resolve_env_vars
from .deepseek import DeepSeekAdapter
from .doubao import DoubaoAdapter
from .glm import GLMAdapter
from .kimi import KimiAdapter
from .openai_compatible import OpenAICompatibleAdapter

_ADAPTER_MAP: dict[str, type[LLMAdapter]] = {
    "glm": GLMAdapter,
    "deepseek": DeepSeekAdapter,
    "kimi": KimiAdapter,
    "moonshot": KimiAdapter,  # moonshot provider uses KimiAdapter
    "doubao": DoubaoAdapter,
    "openai_compatible": OpenAICompatibleAdapter,
}


class ModelRegistry:
    """Load models.yaml and create adapters on demand.

    Supports two config formats:
    - New (F-Eng-02): providers + models (short aliases) + pipeline
    - Legacy: flat models with inline provider/api_key/base_url + routing
    """

    def __init__(self, config_path: str | Path | None = None):
        if config_path is None:
            config_path = Path(__file__).resolve().parents[3] / "config" / "models.yaml"
        self._config_path = Path(config_path)
        self._providers: dict = {}
        self._models: dict = {}
        self._pipeline: dict = {}
        self._routing: dict = {}
        self._features: dict = {}
        self._adapters: dict[str, LLMAdapter] = {}
        self._load()

    def _load(self) -> None:
        if not self._config_path.exists():
            raise FileNotFoundError(f"Config not found: {self._config_path}")
        with open(self._config_path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        self._providers = raw.get("providers", {})
        self._models = raw.get("models", {})
        self._pipeline = raw.get("pipeline", {})
        self._routing = raw.get("routing", {})
        self._features = raw.get("features", {})
        setup = load_setup()
        custom = setup.get("custom_provider") if isinstance(setup, dict) else None
        if isinstance(custom, dict) and custom.get("base_url") and custom.get("model_id"):
            self._providers["custom"] = {"base_url": str(custom["base_url"]), "api_key": load_provider_secret("custom")}
            self._models["custom-main"] = {"provider": "custom", "model_id": str(custom["model_id"]), "max_tokens": 8000}
            self._pipeline.setdefault("custom", "custom-main")
        if "custom" in self._providers:
            self._providers["custom"]["provider"] = "openai_compatible"

    def get_feature(self, name: str) -> bool:
        """特性开关(H-1):未配置一律视为关(默认关)。"""
        return bool(self._features.get(name, False))

    def _resolve_model_config(self, alias: str) -> dict:
        """Resolve a model alias to a full config dict ready for adapter construction.

        New format: model has 'provider' referencing self._providers.
        Legacy format: model has inline api_key/base_url/provider.
        """
        if alias not in self._models:
            raise KeyError(f"Unknown model alias: {alias}")

        model_cfg = dict(self._models[alias])

        # Resolve env vars in all string values
        model_cfg = {
            k: resolve_env_vars(v) if isinstance(v, str) else v
            for k, v in model_cfg.items()
        }

        # New format: provider references providers section
        provider_name = model_cfg.get("provider")
        adapter_provider = "openai_compatible" if provider_name == "custom" else provider_name
        if provider_name and provider_name in self._providers:
            provider_cfg = self._providers[provider_name]

            # Merge base_url from provider if not in model
            if "base_url" not in model_cfg and "base_url" in provider_cfg:
                model_cfg["base_url"] = resolve_env_vars(provider_cfg["base_url"])

            # Resolve api_key from provider
            if "api_key" not in model_cfg:
                if "api_key" in provider_cfg:
                    model_cfg["api_key"] = resolve_env_vars(provider_cfg["api_key"])
                elif "api_key_env" in provider_cfg:
                    env_var = provider_cfg["api_key_env"]
                    model_cfg["api_key"] = os.environ.get(env_var, "") or load_provider_secret(provider_name)
                else:
                    model_cfg["api_key"] = load_provider_secret(provider_name)

            # model_id → model_name for adapter constructor
            if "model_id" in model_cfg:
                model_cfg.setdefault("model_name", model_cfg.pop("model_id"))

        if provider_name == "custom":
            model_cfg["provider"] = adapter_provider

        # model_id → model_name fallback (legacy compat)
        if "model_id" in model_cfg and "model_name" not in model_cfg:
            model_cfg["model_name"] = model_cfg.pop("model_id")

        return model_cfg

    def get_adapter(self, model_name: str) -> LLMAdapter:
        """Get or create an adapter by model alias."""
        if model_name in self._adapters:
            return self._adapters[model_name]

        cfg = self._resolve_model_config(model_name)
        provider = cfg.pop("provider", None)
        adapter_cls = _ADAPTER_MAP.get(provider)
        if adapter_cls is None:
            raise ValueError(f"Unknown provider: {provider}")
        cfg.setdefault("model_name", model_name)
        adapter = adapter_cls(**cfg)
        self._adapters[model_name] = adapter
        return adapter

    def get_adapter_for_key(self, model_name: str, api_key: str) -> LLMAdapter:
        """Build an uncached adapter for setup connection checks."""
        cfg = self._resolve_model_config(model_name)
        provider = cfg.pop("provider", None)
        adapter_cls = _ADAPTER_MAP.get(provider)
        if adapter_cls is None:
            raise ValueError(f"Unknown provider: {provider}")
        cfg["api_key"] = api_key
        cfg.setdefault("model_name", model_name)
        return adapter_cls(**cfg)

    def get_pipeline_config(self) -> dict:
        """Return the pipeline stage → alias mapping."""
        return dict(self._pipeline)

    def _selected_model_override(self) -> str | None:
        default_path = Path(__file__).resolve().parents[3] / "config" / "models.yaml"
        if self._config_path.resolve() != default_path.resolve():
            return None
        selected = str(load_setup().get("selected_model", ""))
        return selected if selected in self._models else None

    def get_adapter_for_stage(self, stage: str, override: str | None = None) -> LLMAdapter:
        """Get adapter for a pipeline stage, with optional CLI override.

        Args:
            stage: Pipeline stage name (planner/writer/polisher).
            override: Optional model alias to override the configured one.
                      Only affects this call, does not modify yaml.
        """
        alias = override or self._configured_stage_alias(stage)
        if alias is None:
            raise KeyError(f"No pipeline config for stage: {stage}")
        return self.get_adapter(alias)

    def _configured_stage_alias(self, stage: str) -> str | None:
        """Resolve new provider/recommendation settings before legacy selected_model."""
        settings = load_setup()
        provider = str(settings.get("provider", ""))
        recommendations = self._raw_recommendations()
        overrides = settings.get("stage_overrides", {})
        if isinstance(overrides, dict) and overrides.get(stage) in self._models:
            return str(overrides[stage])
        if provider == "custom" and settings.get("custom_provider", {}).get("model_id"):
            return "custom-main"
        recommended = recommendations.get(provider, {}) if isinstance(recommendations, dict) else {}
        alias = recommended.get(stage)
        if alias in self._models:
            return alias
        return self._selected_model_override() or self._pipeline.get(stage)

    def _raw_recommendations(self) -> dict:
        try:
            raw = yaml.safe_load(self._config_path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            return {}
        return raw.get("provider_recommendations", {}) or {}

    def get_for_task(self, task: str) -> LLMAdapter:
        """Get adapter by routing task name (legacy compat)."""
        model_name = self._selected_model_override() or self._routing.get(task)
        if model_name is None:
            raise KeyError(f"No routing for task: {task}")
        return self.get_adapter(model_name)

    @property
    def available_models(self) -> list[str]:
        return list(self._models.keys())

    @property
    def available_tasks(self) -> list[str]:
        return list(self._routing.keys())
