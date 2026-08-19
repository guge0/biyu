"""T5.4(P8-M3R)— GET /api/chat/mode 端点测试。

Spec(specs/P8-M3R.md R5 T5.4):
  - 新增 /api/chat/mode 端点返当前 PLACEHOLDER_FLAGS
  - editor.html placeholder-banner 根据 mode 显示(黄=占位 / 绿=真 LLM)

验收:
  - 200 OK
  - 返回 {editor_placeholder, director_placeholder, level, label}
  - level ∈ {real, placeholder, mixed}
  - level 与 flags 一致(全 False → real;全 True → placeholder;混合 → mixed)

零烧钱,纯 TestClient。本端点不读 data_root,无需隔离。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from biyu.ui.app import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_chat_mode_returns_200_and_fields(client: TestClient):
    """/api/chat/mode 返 200 + 4 个字段。"""
    resp = client.get("/api/chat/mode")
    assert resp.status_code == 200
    data = resp.json()
    assert "editor_placeholder" in data
    assert "director_placeholder" in data
    assert "level" in data
    assert "label" in data


def test_chat_mode_level_matches_flags(client: TestClient):
    """level 与 PLACEHOLDER_FLAGS 一致(实际生产环境两 flags 都是 False → real)。"""
    from biyu.ui.prompts_editor import PLACEHOLDER_FLAGS

    resp = client.get("/api/chat/mode")
    data = resp.json()
    ed = PLACEHOLDER_FLAGS.get("editor", True)
    dr = PLACEHOLDER_FLAGS.get("director", True)
    if not ed and not dr:
        assert data["level"] == "real", "两 flags 均 False 时 level 应为 real"
    elif ed and dr:
        assert data["level"] == "placeholder"
    else:
        assert data["level"] == "mixed"


def test_chat_mode_labels_are_nonempty(client: TestClient):
    """label 字段必非空(给 UI 显)。"""
    resp = client.get("/api/chat/mode")
    data = resp.json()
    assert isinstance(data["label"], str) and len(data["label"]) > 0


def test_chat_mode_editor_director_consistent_with_module(client: TestClient):
    """返值的 editor_placeholder / director_placeholder 与模块 PLACEHOLDER_FLAGS 一致。"""
    from biyu.ui.prompts_editor import PLACEHOLDER_FLAGS

    resp = client.get("/api/chat/mode")
    data = resp.json()
    assert data["editor_placeholder"] is bool(PLACEHOLDER_FLAGS.get("editor", True))
    assert data["director_placeholder"] is bool(PLACEHOLDER_FLAGS.get("director", True))
