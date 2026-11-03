"""书架“已配 Key”与连接弹窗“API Key 状态”同一口径（整改清单 #2）。"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _config(tmp_path: Path, provider_block: str) -> Path:
    config = tmp_path / "models.yaml"
    config.write_text(
        "providers:\n  demo:\n" + provider_block
        + "models:\n  demo-model:\n    provider: demo\n    model_id: demo-chat\n",
        encoding="utf-8",
    )
    return config


@pytest.mark.parametrize(
    ("provider_block", "env", "keyring_value", "expected"),
    [
        ("    api_key: sk-inline-123456\n", {}, "", "inline"),
        ("    api_key: ${DEMO_KEY}\n", {"DEMO_KEY": "sk-env-123456"}, "", "env"),
        ("    api_key_env: DEMO_KEY\n", {"DEMO_KEY": "sk-env-123456"}, "", "env"),
        ("    api_key_env: DEMO_KEY\n", {}, "sk-keyring-123456", "keyring"),
        ("    base_url: https://example.invalid\n", {}, "sk-keyring-123456", "keyring"),
        ("    base_url: https://example.invalid\n", {}, "", ""),
        ("    api_key: 在此填入你的Key\n", {}, "sk-keyring-123456", ""),
    ],
)
def test_status_reports_effective_key_source(tmp_path, monkeypatch, provider_block, env, keyring_value, expected):
    import biyu.ui.setup as setup
    from biyu.ui.app import app

    monkeypatch.delenv("DEMO_KEY", raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    config = _config(tmp_path, provider_block)
    monkeypatch.setattr(setup, "get_config_path", lambda: config)
    monkeypatch.setattr(setup, "get_data_root", lambda: tmp_path / "data")
    monkeypatch.setattr(setup, "load_setup", lambda: {})
    monkeypatch.setattr(setup, "load_provider_secret", lambda _provider: keyring_value)

    body = TestClient(app).get("/api/setup/status").json()

    assert body["key_sources"] == {"demo": expected}
    assert body["configured_providers"] == {"demo": bool(expected)}
    assert "sk-" not in str(body["key_sources"])


def test_update_with_blank_key_uses_inline_key_instead_of_keyring(tmp_path, monkeypatch):
    """S-3C 事故场景：钥匙串里是假 Key、配置文件有可用内联 Key，留空保存不该拿钥匙串去测。"""
    import biyu.ui.setup as setup
    from biyu.ui.app import app

    config = _config(tmp_path, "    api_key: sk-inline-123456\n")
    used: list[str] = []

    class Adapter:
        async def generate(self, *_args, **_kwargs):
            return None

    class Registry:
        def __init__(self, _path):
            pass

        def get_adapter(self, alias):
            used.append("effective")
            return Adapter()

        def get_adapter_for_key(self, alias, key):
            used.append(key)
            return Adapter()

    monkeypatch.setattr(setup, "get_config_path", lambda: config)
    monkeypatch.setattr(setup, "ModelRegistry", Registry)
    monkeypatch.setattr(setup, "load_setup", lambda: {})
    monkeypatch.setattr(setup, "save_setup", lambda _value: None)
    monkeypatch.setattr(setup, "load_provider_secret", lambda _provider: "sk-invalid-s3c-401")
    monkeypatch.setattr(setup, "store_provider_secret", lambda *_args: "系统钥匙串")

    response = TestClient(app).post("/api/setup/update", json={"model": "demo-model", "api_key": ""})

    assert response.status_code == 200
    assert used == ["effective"]
    assert response.json()["secret_storage"] == "配置文件里的 Key"


def test_update_with_new_key_warns_when_inline_key_still_wins(tmp_path, monkeypatch):
    import biyu.ui.setup as setup
    from biyu.ui.app import app

    config = _config(tmp_path, "    api_key: sk-inline-123456\n")

    class Adapter:
        async def generate(self, *_args, **_kwargs):
            return None

    class Registry:
        def __init__(self, _path):
            pass

        def get_adapter_for_key(self, alias, key):
            return Adapter()

    monkeypatch.setattr(setup, "get_config_path", lambda: config)
    monkeypatch.setattr(setup, "ModelRegistry", Registry)
    monkeypatch.setattr(setup, "load_setup", lambda: {})
    monkeypatch.setattr(setup, "save_setup", lambda _value: None)
    monkeypatch.setattr(setup, "load_provider_secret", lambda _provider: "")
    monkeypatch.setattr(setup, "store_provider_secret", lambda *_args: "系统钥匙串")

    response = TestClient(app).post("/api/setup/update", json={"model": "demo-model", "api_key": "sk-new-999999"})

    assert response.status_code == 200
    assert "优先生效" in response.json()["message"]


def test_key_dialog_shows_source_from_backend():
    js = (Path(__file__).resolve().parents[1] / "src" / "biyu" / "ui" / "static" / "setup.js").read_text(encoding="utf-8")
    assert "key_sources" in js
