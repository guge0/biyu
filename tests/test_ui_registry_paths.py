"""S-3C:ui 层取 adapter 必须走 BIYU_PROJECT_ROOT 感知的配置路径。

背景(2026-10-27 异常矩阵排查):ModelRegistry() 无参默认路径是「源码仓相对路径」,
忽略 BIYU_PROJECT_ROOT——冻结/便携环境下指向不存在的 config/models.yaml,作者保存
Key 后向导推演/责编对话仍报「开书模型不可用」;开发机多仓并存时也会读错仓的 Key。
ui 层五个调用点一律显式传 get_config_path()。
"""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

_CALL_SITES = (
    "src/biyu/ui/wizard.py",
    "src/biyu/ui/routes.py",
    "src/biyu/ui/naming.py",
    "src/biyu/ui/summarize.py",
    "src/biyu/ui/cell_draft.py",
)


def test_ui_never_uses_checkout_relative_registry_default() -> None:
    for rel in _CALL_SITES:
        text = (REPO / rel).read_text(encoding="utf-8")
        assert "ModelRegistry()" not in text, f"{rel} 仍在用无参 ModelRegistry()(源码仓相对路径)"
        assert "ModelRegistry(get_config_path())" in text, rel


def test_chat_adapter_respects_project_root_env(monkeypatch, tmp_path: Path) -> None:
    """BIYU_PROJECT_ROOT 指到哪,责编对话的 adapter 就读哪份配置(便携包可用性闸)。"""
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "models.yaml").write_text(
        "providers:\n"
        "  deepseek:\n"
        "    base_url: http://127.0.0.1:9/v1\n"
        "    api_key: sk-invalid-s3c-test\n"
        "models:\n"
        "  v4_flash:\n"
        "    provider: deepseek\n"
        "    model_id: deepseek-v4-flash\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("BIYU_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("BIYU_USER_CONFIG_DIR", str(tmp_path / "uc"))
    from biyu.ui import routes

    adapter = routes._get_chat_adapter()
    assert adapter is not None, "隔离配置下应能取到 adapter"
    assert "127.0.0.1:9" in str(adapter.base_url)


# ---------- S-3C 别名回落(免 Key 首启目录无 v4_flash 的干净机可用性) ----------


def _example_like_registry(tmp_path: Path, monkeypatch):
    """按 models.yaml.example 的形态造 registry:有 deepseek-v3,没有 v4_flash。"""
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir(exist_ok=True)
    (cfg_dir / "models.yaml").write_text(
        "providers:\n"
        "  deepseek:\n"
        "    base_url: http://127.0.0.1:9/v1\n"
        "    api_key_env: DEEPSEEK_API_KEY\n"
        "models:\n"
        "  deepseek-r1:\n"
        "    provider: deepseek\n"
        "    model_id: deepseek-reasoner\n"
        "  deepseek-v3:\n"
        "    provider: deepseek\n"
        "    model_id: deepseek-chat\n"
        "pipeline:\n"
        "  writer: deepseek-v3\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("BIYU_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("BIYU_USER_CONFIG_DIR", str(tmp_path / "uc"))
    from biyu.llm import ModelRegistry

    from biyu.config import get_config_path

    return ModelRegistry(get_config_path())


def test_fallback_uses_setup_selected_model_when_v4_flash_missing(monkeypatch, tmp_path: Path) -> None:
    """便携包实锤缺陷:模板目录没有 v4_flash,作者选中的模型必须被用上,而不是报「请保存 Key」。"""
    monkeypatch.setenv("BIYU_USER_CONFIG_DIR", str(tmp_path / "uc"))
    (tmp_path / "uc").mkdir()
    (tmp_path / "uc" / "setup.json").write_text('{"complete": true, "selected_model": "deepseek-v3"}', encoding="utf-8")
    registry = _example_like_registry(tmp_path, monkeypatch)
    from biyu.ui.model_alias import resolve_ui_adapter

    adapter, alias = resolve_ui_adapter(registry)
    assert alias == "deepseek-v3"
    assert adapter.model_name == "deepseek-chat"


def test_fallback_order_prefers_v4_flash_when_present(monkeypatch, tmp_path: Path) -> None:
    """开发机私有配置有 v4_flash:老板裁定的快速档不变。"""
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "models.yaml").write_text(
        "providers:\n"
        "  deepseek:\n"
        "    base_url: http://127.0.0.1:9/v1\n"
        "    api_key: sk-invalid-s3c-test\n"
        "models:\n"
        "  deepseek-v3:\n"
        "    provider: deepseek\n"
        "    model_id: deepseek-chat\n"
        "  v4_flash:\n"
        "    provider: deepseek\n"
        "    model_id: deepseek-v4-flash\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("BIYU_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("BIYU_USER_CONFIG_DIR", str(tmp_path / "uc"))
    from biyu.llm import ModelRegistry

    from biyu.config import get_config_path
    from biyu.ui.model_alias import resolve_ui_adapter

    _adapter, alias = resolve_ui_adapter(ModelRegistry(get_config_path()))
    assert alias == "v4_flash"


def test_all_ui_call_sites_use_resolver(monkeypatch, tmp_path: Path) -> None:
    for rel in _CALL_SITES:
        text = (REPO / rel).read_text(encoding="utf-8")
        assert "resolve_ui_adapter" in text, f"{rel} 未走别名回落解析(干净机会因 v4_flash 缺失而不可用)"
