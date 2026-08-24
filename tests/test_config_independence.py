from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
import yaml


def _write_catalog(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """providers:
  deepseek:
    base_url: https://api.deepseek.com/v1
    api_key_env: DEEPSEEK_API_KEY
models:
  safe-writer:
    provider: deepseek
    model_id: deepseek-chat
    max_tokens: 8000
pipeline:
  planner: safe-writer
  writer: safe-writer
  polisher: safe-writer
features:
  web_architect: true
  checklist: true
""",
        encoding="utf-8",
    )
    return path


def test_no_private_config_starts_and_opens_first_run_setup(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import biyu.config as config
    import biyu.ui.setup as setup
    from biyu.ui.app import app

    project = tmp_path / "project"
    data = project / "data"
    data.mkdir(parents=True)
    _write_catalog(project / "config" / "models.yaml.example")

    monkeypatch.setattr(config, "get_project_root", lambda: project)
    monkeypatch.setenv("BIYU_RUNTIME_ROLE", "test")
    monkeypatch.setenv("BIYU_DATA_ROOT", str(data))
    monkeypatch.setenv("BIYU_TEST_DATA_ROOT", str(data))
    monkeypatch.setattr(setup, "load_setup", lambda: {})
    monkeypatch.setattr(setup, "_configured_without_wizard", lambda: False)

    assert not (project / "config" / "models.yaml").exists()
    with TestClient(app) as client:
        page = client.get("/")
        status = client.get("/api/setup/status")

    assert page.status_code == 200
    assert "连接模型" in page.text
    assert status.status_code == 200
    assert status.json()["ready"] is False
    assert [item["alias"] for item in status.json()["models"]] == ["safe-writer"]


def test_workbench_feature_flags_use_safe_catalog_without_private_config(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import biyu.config as config
    import biyu.ui.workbench as workbench

    catalog = _write_catalog(tmp_path / "config" / "models.yaml.example")
    monkeypatch.setattr(config, "get_config_path", lambda: catalog)

    assert workbench._web_architect_enabled() is True
    assert workbench._checklist_feature_enabled() is True


def test_fingerprint_adapter_falls_back_to_writer_alias_when_v4_pro_is_absent(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import biyu.fingerprint.adapter as fingerprint_adapter
    from biyu.llm.registry import ModelRegistry

    catalog = _write_catalog(tmp_path / "config" / "models.yaml.example")
    monkeypatch.setattr(
        fingerprint_adapter,
        "get_registry",
        lambda: ModelRegistry(catalog),
    )

    config = fingerprint_adapter._get_adapter_config()

    assert config["model_id"] == "deepseek-chat"
    assert config["base_url"] == "https://api.deepseek.com/v1"


def test_example_catalog_exposes_four_supported_chat_providers() -> None:
    path = Path("config/models.yaml.example")
    text = path.read_text(encoding="utf-8")
    catalog = yaml.safe_load(text)

    assert {"deepseek", "kimi", "glm", "doubao"} <= set(catalog["providers"])
    chat_providers = {
        model["provider"]
        for model in catalog["models"].values()
        if model.get("type") != "embedding"
    }
    assert {"deepseek", "kimi", "glm", "doubao"} <= chat_providers
    assert "pipeline.planner = 导演（现役）" in text
    assert "pipeline.observer 当前无生产消费者，改了不生效" in text
    assert "routing 九项当前无生产消费者，改了不生效" in text


def test_readme_explains_model_and_provider_boundaries() -> None:
    text = Path("README.md").read_text(encoding="utf-8")

    assert "DeepSeek、Kimi（Moonshot）、GLM、豆包" in text
    assert "Key / 模型" in text
    assert "endpoint ID" in text
    assert "adapter" in text
