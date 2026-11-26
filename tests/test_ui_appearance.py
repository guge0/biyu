"""S-1 外观系统：UI 偏好持久化与背景图上传的服务端契约。

覆盖 spec REQ-1（主题持久化/未知键/设置损坏降级）与 REQ-3（上传/非图片拒绝/文件丢失降级）
中能落到服务端的部分；纯前端行为（切换立即生效、82% 自动蒙层）由真实走查取证。
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from biyu.ui.app import app
from biyu.secure_config import user_config_dir

DEFAULT_PREFS = {
    "theme": "default",
    "custom": None,
    "background": {
        "type": "none",
        "preset": None,
        "file": None,
        "overlay": 90,
        "blur": 0,
        "mist": 100,
        "glass": 0.38,
    },
}

PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGBgAAAABQAB"
    "h6FO1AAAAABJRU5ErkJggg=="
)


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("BIYU_USER_CONFIG_DIR", str(tmp_path / "usercfg"))
    return TestClient(app)


def _prefs_path(tmp_path: Path) -> Path:
    return tmp_path / "usercfg" / "ui.json"


def test_prefs_default_when_no_file(client):
    resp = client.get("/api/ui/prefs")
    assert resp.status_code == 200
    assert resp.json() == DEFAULT_PREFS


def test_prefs_put_roundtrip_persists(client, tmp_path):
    payload = {
        "theme": "dark",
        "custom": {"--paper": "#181614"},
        "background": {
            "type": "preset",
            "preset": "xuan",
            "file": None,
            "overlay": 82,
            "blur": 4,
            "mist": 150,
            "glass": 0.25,
        },
    }
    assert client.put("/api/ui/prefs", json=payload).status_code == 200
    assert client.get("/api/ui/prefs").json() == payload
    stored = json.loads(_prefs_path(tmp_path).read_text(encoding="utf-8"))
    assert stored["theme"] == "dark"


def test_prefs_corrupt_file_falls_back_to_defaults(client, tmp_path):
    _prefs_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    _prefs_path(tmp_path).write_text("{not-json", encoding="utf-8")
    resp = client.get("/api/ui/prefs")
    assert resp.status_code == 200
    assert resp.json() == DEFAULT_PREFS


def test_prefs_put_sanitizes_values(client):
    payload = {
        "theme": "dark",
        "custom": {"--ok": "#00FF00", "--paper": "red", "extra": 1},
        "background": {"type": "preset", "preset": "xuan", "file": "../../x",
                       "overlay": 120, "blur": -5},
        "injected": True,
    }
    resp = client.put("/api/ui/prefs", json=payload)
    assert resp.status_code == 200
    prefs = client.get("/api/ui/prefs").json()
    assert prefs["theme"] == "dark"
    assert prefs["custom"] is None  # 非法令牌键/值整组丢弃，不落半成品
    bg = prefs["background"]
    assert bg["file"] is None
    assert bg["overlay"] == 98
    assert bg["blur"] == 0
    assert "injected" not in prefs


def test_prefs_glass_fields_clamped(client, tmp_path):
    """S-10 3g·工单第2条：雾面浓度 0–200%、卡片透明度 0.20–0.90，越界夹取。"""
    payload = {
        "theme": "default",
        "custom": None,
        "background": {"type": "none", "preset": None, "file": None,
                       "overlay": 90, "blur": 0, "mist": 300, "glass": 0.05},
    }
    client.put("/api/ui/prefs", json=payload)
    bg = client.get("/api/ui/prefs").json()["background"]
    assert bg["mist"] == 200
    assert bg["glass"] == 0.20


def test_prefs_legacy_file_without_glass_fields_gets_defaults(client, tmp_path):
    """3g：旧 ui.json 缺 mist/glass 字段时回落默认值，不报错、不丢原有字段。"""
    _prefs_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    _prefs_path(tmp_path).write_text(json.dumps({
        "theme": "parchment",
        "custom": None,
        "background": {"type": "preset", "preset": "xuan", "file": None,
                       "overlay": 90.0, "blur": 0},
    }), encoding="utf-8")
    prefs = client.get("/api/ui/prefs").json()
    assert prefs["theme"] == "parchment"
    assert prefs["background"]["type"] == "preset"
    assert prefs["background"]["mist"] == 100
    assert prefs["background"]["glass"] == 0.38


def test_prefs_put_accepts_only_safe_tokens(client):
    payload = {
        "theme": "default",
        "custom": {"--paper": "#FFF000", "--mark-bg": "#F6E6E1"},
        "background": DEFAULT_PREFS["background"],
    }
    assert client.put("/api/ui/prefs", json=payload).status_code == 200
    prefs = client.get("/api/ui/prefs").json()
    assert set(prefs["custom"]) == {"--paper", "--mark-bg"}


def test_background_upload_saves_image_and_serves_it_back(client, tmp_path):
    resp = client.post("/api/ui/background", json={
        "name": "wall.png",
        "data": base64.b64encode(PNG_BYTES).decode("ascii"),
    })
    assert resp.status_code == 200
    body = resp.json()
    saved_name = body["file"]
    assert saved_name.endswith(".png")
    assert body["url"] == f"/api/ui/background-file/{saved_name}"
    data_root = Path(client.get("/api/version").json()["data_root"])
    saved = data_root / "ui-backgrounds" / saved_name
    assert saved.read_bytes() == PNG_BYTES

    served = client.get(body["url"])
    assert served.status_code == 200
    assert served.headers["content-type"].startswith("image/png")
    assert served.content == PNG_BYTES


def test_background_upload_rejects_non_image(client, tmp_path):
    data_root = Path(client.get("/api/version").json()["data_root"])
    bg_dir = data_root / "ui-backgrounds"
    before = sorted(p.name for p in bg_dir.iterdir()) if bg_dir.exists() else []

    resp = client.post("/api/ui/background", json={
        "name": "evil.png",
        "data": base64.b64encode(b"<html><script>alert(1)</script></html>").decode("ascii"),
    })
    assert resp.status_code == 400
    assert "图片" in resp.json()["detail"]
    after = sorted(p.name for p in bg_dir.iterdir()) if bg_dir.exists() else []
    assert after == before


def test_background_file_unknown_name_404(client):
    assert client.get("/api/ui/background-file/deadbeef.png").status_code == 404


def test_background_file_rejects_path_traversal(client):
    for bad in ("..%2F..%2Fsetup.json", "a/b.png", "..\\x.png"):
        assert client.get(f"/api/ui/background-file/{bad}").status_code in (404, 400)


def test_background_file_missing_after_delete_404(client):
    resp = client.post("/api/ui/background", json={
        "name": "gone.png",
        "data": base64.b64encode(PNG_BYTES).decode("ascii"),
    })
    saved_name = resp.json()["file"]
    data_root = Path(client.get("/api/version").json()["data_root"])
    (data_root / "ui-backgrounds" / saved_name).unlink()
    assert client.get(f"/api/ui/background-file/{saved_name}").status_code == 404


def test_prefs_prunes_background_file_that_vanished_on_disk(client):
    """REQ-3 降级：设置引用的背景图被删后，读偏好即回落无背景，客户端不再请求 404。"""
    upload = client.post("/api/ui/background", json={
        "name": "vanish.png",
        "data": base64.b64encode(PNG_BYTES).decode("ascii"),
    }).json()
    payload = {
        "theme": "default",
        "custom": None,
        "background": {"type": "custom", "preset": None, "file": upload["file"],
                       "overlay": 82, "blur": 0},
    }
    client.put("/api/ui/prefs", json=payload)
    data_root = Path(client.get("/api/version").json()["data_root"])
    (data_root / "ui-backgrounds" / upload["file"]).unlink()

    prefs = client.get("/api/ui/prefs").json()
    assert prefs["background"]["type"] == "none"
    assert prefs["background"]["file"] is None
