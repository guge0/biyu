from __future__ import annotations

import json
import asyncio
from pathlib import Path

import httpx


def test_openai_compatible_normalizes_v1_and_returns_chat_text(monkeypatch) -> None:
    from biyu.llm.openai_compatible import OpenAICompatibleAdapter

    seen = {}

    async def handler(request: httpx.Request):
        seen["url"] = str(request.url)
        seen["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"model": "local", "choices": [{"message": {"content": "OK"}}]})

    adapter = OpenAICompatibleAdapter(model_name="local", api_key="secret", base_url=" http://localhost:11434 ")
    original_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs))

    result = asyncio.run(adapter.generate([{"role": "user", "content": "hi"}], max_tokens=4))
    assert result.text == "OK"
    assert seen["url"] == "http://localhost:11434/v1/chat/completions"
    assert seen["payload"]["model"] == "local"


def test_custom_setup_is_user_config_and_does_not_modify_yaml(tmp_path: Path, monkeypatch) -> None:
    import biyu.secure_config as secure

    monkeypatch.setenv("BIYU_USER_CONFIG_DIR", str(tmp_path))
    secure.save_setup({"custom_provider": {"base_url": "http://localhost:11434/v1", "model_id": "local"}})
    secure.store_provider_secret("custom", "secret")
    assert json.loads((tmp_path / "setup.json").read_text(encoding="utf-8"))["custom_provider"]["model_id"] == "local"
    assert "secret" not in (tmp_path / "setup.json").read_text(encoding="utf-8")


def test_custom_connection_failure_does_not_change_existing_setup(tmp_path: Path, monkeypatch) -> None:
    import biyu.ui.setup as setup
    from biyu.ui.app import app
    from fastapi.testclient import TestClient

    monkeypatch.setenv("BIYU_USER_CONFIG_DIR", str(tmp_path))
    setup_path = tmp_path / "setup.json"
    setup_path.write_text('{"provider":"deepseek","complete":true}\n', encoding="utf-8")
    monkeypatch.setattr(setup, "get_config_path", lambda: tmp_path / "models.yaml")
    monkeypatch.setattr(setup, "load_provider_secret", lambda _provider: "old-secret")
    class Broken:
        async def generate(self, *_args, **_kwargs):
            raise RuntimeError("拒绝连接")
    monkeypatch.setattr("biyu.llm.openai_compatible.OpenAICompatibleAdapter", lambda **_kwargs: Broken())

    response = TestClient(app).post("/api/setup/update", json={"provider": "custom", "base_url": "http://bad/v1", "model_id": "local", "api_key": "new-secret"})
    assert response.status_code == 400
    assert setup_path.read_text(encoding="utf-8") == '{"provider":"deepseek","complete":true}\n'


def test_registry_builds_custom_adapter_from_user_config(tmp_path: Path, monkeypatch) -> None:
    import biyu.secure_config as secure
    from biyu.llm.registry import ModelRegistry

    monkeypatch.setenv("BIYU_USER_CONFIG_DIR", str(tmp_path))
    secure.save_setup({"custom_provider": {"base_url": "http://localhost:11434/v1", "model_id": "local"}})
    secure.store_provider_secret("custom", "secret")
    config = tmp_path / "models.yaml"
    config.write_text("providers: {}\nmodels: {}\npipeline: {}\n", encoding="utf-8")
    registry = ModelRegistry(config)
    adapter = registry.get_adapter("custom-main")
    assert adapter.model_name == "local"
    assert adapter.base_url == "http://localhost:11434/v1"


def test_stage_resolution_uses_provider_recommendation_then_explicit_override(tmp_path: Path, monkeypatch) -> None:
    import biyu.secure_config as secure
    from biyu.llm.registry import ModelRegistry

    monkeypatch.setenv("BIYU_USER_CONFIG_DIR", str(tmp_path))
    secure.save_setup({"provider": "demo", "stage_overrides": {"planner": "demo-writer"}})
    config = tmp_path / "models.yaml"
    config.write_text(
        "providers:\n  demo: {api_key: key, base_url: http://localhost/v1}\n"
        "models:\n  demo-reasoner: {provider: demo, model_id: reasoner}\n  demo-writer: {provider: demo, model_id: writer}\n"
        "pipeline: {planner: demo-reasoner, writer: demo-writer}\n"
        "provider_recommendations: {demo: {planner: demo-reasoner, writer: demo-writer}}\n",
        encoding="utf-8",
    )
    registry = ModelRegistry(config)
    assert registry._configured_stage_alias("planner") == "demo-writer"
    secure.save_setup({"provider": "demo", "stage_overrides": {}})
    registry = ModelRegistry(config)
    assert registry._configured_stage_alias("planner") == "demo-reasoner"


def test_provider_catalog_always_has_complete_landing_for_each_provider(monkeypatch, tmp_path: Path) -> None:
    import biyu.ui.setup as setup
    config = tmp_path / "models.yaml"
    config.write_text("providers:\n  kimi: {api_key: key}\nmodels:\n  kimi-main: {provider: kimi, model_id: kimi-k2.5}\npipeline: {}\n", encoding="utf-8")
    monkeypatch.setattr(setup, "get_config_path", lambda: config)
    monkeypatch.setattr(setup, "load_setup", lambda: {})
    rows = setup._provider_catalog()
    assert set(rows[0]["models"]) == {"planner", "writer", "polisher"}
