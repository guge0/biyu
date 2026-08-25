from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient


def test_fallback_secret_file_is_encrypted_and_settings_never_store_key(tmp_path: Path, monkeypatch) -> None:
    import biyu.secure_config as secure

    monkeypatch.setenv("BIYU_USER_CONFIG_DIR", str(tmp_path))
    monkeypatch.setitem(sys.modules, "keyring", SimpleNamespace(
        set_password=lambda *_args: (_ for _ in ()).throw(RuntimeError("no keyring")),
        get_password=lambda *_args: (_ for _ in ()).throw(RuntimeError("no keyring")),
    ))
    secret = "sk-test-plain-value"
    assert secure.store_provider_secret("provider", secret) == "本地加密文件"
    assert secure.load_provider_secret("provider") == secret
    assert secret.encode() not in (tmp_path / "secrets.enc").read_bytes()

    secure.save_setup({"selected_model": "model-a", "api_key": secret, "complete": True})
    assert secret not in (tmp_path / "setup.json").read_text(encoding="utf-8")


def test_setup_status_never_returns_provider_keys(tmp_path: Path, monkeypatch) -> None:
    import biyu.ui.setup as setup
    from biyu.ui.app import app

    config = tmp_path / "models.yaml"
    config.write_text(
        "providers:\n  demo:\n    api_key_env: DEMO_KEY\nmodels:\n  demo-model:\n    provider: demo\n    model_id: demo-chat\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(setup, "get_config_path", lambda: config)
    monkeypatch.setattr(setup, "get_data_root", lambda: tmp_path / "data")
    monkeypatch.setattr(setup, "load_setup", lambda: {})
    monkeypatch.setattr(setup, "_configured_without_wizard", lambda: False)
    response = TestClient(app).get("/api/setup/status")
    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is False
    assert body["models"] == [{"alias": "demo-model", "provider": "demo", "label": "demo-chat"}]
    assert body["configured_providers"] == {"demo": False}
    assert "api_key" not in json.dumps(body)


def test_regular_setup_update_reuses_secret_store_and_keeps_selected_book(monkeypatch) -> None:
    import biyu.ui.setup as setup
    from biyu.ui.app import app

    saved: list[dict[str, object]] = []
    stored: list[tuple[str, str]] = []

    class Adapter:
        async def generate(self, messages, max_tokens):
            assert messages == [{"role": "user", "content": "连通性检查：只回复 OK"}]
            assert max_tokens == 4

    class Registry:
        def __init__(self, _path):
            pass

        def get_adapter(self, alias):
            assert alias == "model-b"
            return Adapter()

        def get_adapter_for_key(self, alias, key):
            assert alias == "model-b"
            assert key == "replacement-secret"
            return Adapter()

    monkeypatch.setattr(setup, "_catalog", lambda: [
        {"alias": "model-a", "provider": "one", "label": "Model A"},
        {"alias": "model-b", "provider": "two", "label": "Model B"},
    ])
    monkeypatch.setattr(setup, "get_config_path", lambda: Path("catalog.yaml"))
    monkeypatch.setattr(setup, "ModelRegistry", Registry)
    monkeypatch.setattr(setup, "load_setup", lambda: {
        "selected_model": "model-a", "selected_book": "book-1", "complete": True,
    })
    monkeypatch.setattr(setup, "save_setup", lambda value: saved.append(value))
    monkeypatch.setattr(setup, "store_provider_secret", lambda provider, secret: stored.append((provider, secret)) or "系统钥匙串")

    response = TestClient(app).post("/api/setup/update", json={"model": "model-b", "api_key": "replacement-secret", "provider_keys": {"one": "other-secret"}})

    assert response.status_code == 200
    assert stored == [("two", "replacement-secret"), ("one", "other-secret")]
    assert saved == [{"provider": "two", "stage_overrides": {"writer": "model-b"}, "selected_book": "book-1", "complete": True}]
    assert "replacement-secret" not in response.text


def test_regular_setup_update_rejects_typed_unknown_model(monkeypatch) -> None:
    import biyu.ui.setup as setup
    from biyu.ui.app import app

    monkeypatch.setattr(setup, "_catalog", lambda: [
        {"alias": "model-a", "provider": "one", "label": "Model A"},
    ])
    response = TestClient(app).post("/api/setup/update", json={"model": "typed-by-user", "api_key": "secret"})
    assert response.status_code == 400
    assert response.json()["detail"] == "请选择列表中的模型"


def test_first_run_saves_provider_and_stage_overrides_without_legacy_global_model(monkeypatch, tmp_path: Path) -> None:
    import biyu.ui.setup as setup
    from biyu.ui.app import app

    saved = []
    class Adapter:
        async def generate(self, *_args, **_kwargs):
            return None
    class Registry:
        def __init__(self, _path): pass
        def get_adapter_for_key(self, alias, key):
            assert alias == "model-a" and key == "secret"
            return Adapter()
    monkeypatch.setattr(setup, "_catalog", lambda: [{"alias": "model-a", "provider": "demo", "label": "Demo"}])
    monkeypatch.setattr(setup, "ModelRegistry", Registry)
    monkeypatch.setattr(setup, "store_provider_secret", lambda *_args: "系统钥匙串")
    monkeypatch.setattr(setup, "save_setup", lambda value: saved.append(value))
    monkeypatch.setattr(setup, "_books", lambda: [{"id": "book-1", "title": "测试"}])
    response = TestClient(app).post("/api/setup/complete", json={"provider": "demo", "model": "model-a", "api_key": "secret", "book": "book-1", "stage_overrides": {"planner": "model-a"}})
    assert response.status_code == 200
    assert saved == [{"provider": "demo", "stage_overrides": {"planner": "model-a"}, "selected_book": "book-1", "complete": True}]


def test_first_run_can_save_connection_without_any_book(monkeypatch) -> None:
    import biyu.ui.setup as setup
    from biyu.ui.app import app

    saved = []

    class Adapter:
        async def generate(self, *_args, **_kwargs):
            return None

    class Registry:
        def __init__(self, _path):
            pass

        def get_adapter_for_key(self, alias, key):
            assert alias == "model-a" and key == "secret"
            return Adapter()

    monkeypatch.setattr(setup, "_catalog", lambda: [{"alias": "model-a", "provider": "demo", "label": "Demo"}])
    monkeypatch.setattr(setup, "_books", lambda: [])
    monkeypatch.setattr(setup, "ModelRegistry", Registry)
    monkeypatch.setattr(setup, "store_provider_secret", lambda *_args: "系统钥匙串")
    monkeypatch.setattr(setup, "save_setup", lambda value: saved.append(value))

    response = TestClient(app).post(
        "/api/setup/complete",
        json={"provider": "demo", "model": "model-a", "api_key": "secret"},
    )

    assert response.status_code == 200
    assert response.json()["book"] == ""
    assert saved == [{"provider": "demo", "stage_overrides": {}, "selected_book": "", "complete": True}]


def test_first_run_ui_masks_key_and_redirects_direct_workbench() -> None:
    index = Path("src/biyu/ui/static/index.html").read_text(encoding="utf-8")
    setup_js = Path("src/biyu/ui/static/setup.js").read_text(encoding="utf-8")
    workbench_js = Path("src/biyu/ui/static/workbench.js").read_text(encoding="utf-8")
    gitignore = Path(".gitignore").read_text(encoding="utf-8")
    assert 'type="password"' in index
    assert "保存并试一下连接" in index
    assert "document.getElementById('setup-key').value=''" in setup_js
    assert "location.href='/?setup=1'" in workbench_js
    assert "**/secrets.enc" in gitignore


def test_shelf_has_regular_model_settings_without_rendering_saved_key() -> None:
    index = Path("src/biyu/ui/static/index.html").read_text(encoding="utf-8")
    setup_js = Path("src/biyu/ui/static/setup.js").read_text(encoding="utf-8")

    assert 'id="connection-settings-button"' in index
    assert 'id="setup-key-state"' in index
    assert 'id="setup-key" type="password"' in index
    assert 'value=' not in index.split('id="setup-key"', 1)[1].split(">", 1)[0]
    assert "/api/setup/update" in setup_js
    assert "configured_providers" in setup_js
    assert "Key / 模型" in index
    assert 'id="setup-book-fields"' not in index
    assert "create_book" not in setup_js


def test_readme_requires_recheck_and_taste_comparison_before_enabling_polish() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "润色默认关闭" in readme
    assert "重新核对润色后的正文" in readme
    assert "确认改写结果符合预期" in readme


def test_setup_dialog_supports_multiple_provider_keys_and_can_close() -> None:
    index = Path("src/biyu/ui/static/index.html").read_text(encoding="utf-8")
    setup_js = Path("src/biyu/ui/static/setup.js").read_text(encoding="utf-8")

    assert 'id="setup-close"' in index
    assert 'id="setup-multi-provider-fields"' in index
    assert "provider_keys" in setup_js
    assert "event.key === 'Escape'" in setup_js
    assert "确认并关闭" in setup_js
    assert "还有设置没有确认，确定关闭吗？" in setup_js


def test_settings_reader_uses_markdown_renderer_for_book_level_cells() -> None:
    html = Path("src/biyu/ui/static/settings.html").read_text(encoding="utf-8")
    js = Path("src/biyu/ui/static/settings.js").read_text(encoding="utf-8")

    assert "/mini-md.js" in html
    assert "MiniMd.render(current.data.content)" in js


def test_model_settings_button_handles_status_race_before_snapshot_load() -> None:
    setup_js = Path("src/biyu/ui/static/setup.js").read_text(encoding="utf-8")

    assert "if (!snapshot)" in setup_js
    assert "正在读取连接设置，请稍候再试。" in setup_js
