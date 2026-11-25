"""S-6/S-8-1 · 朱雀路由契约:status / key / check / fix 两步走 / fix-blind 分层 /
deai / jobs / 409 / 无 Key 文案。

client 与 engine 全部打桩,测试不走网络、不烧钱。Key 走测试隔离的加密文件
(conftest 已设 BIYU_KEYRING_DISABLED=1 与独立 BIYU_USER_CONFIG_DIR)。
"""
from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from biyu.ui import zhuque_routes

CANNED_RESULT = {
    "text": "改好的整章",
    "rows": [{"before": "旧段", "after": "新段", "s0": 0.8, "s1": 0.2, "status": "已过线",
              "layer": "zhzh", "polished": True, "attempts": [], "best_try": None, "risks": []}],
    "windows": [{"order": 1, "start": 0, "end": 5, "text": "改好的整章", "conf": 0.2, "label": 0}],
    "verdict": {"labels_ratio": {"0": 1.0, "1": 0.0, "2": 0.0}, "softmax_confidence": 0.05},
    "polish": {"kept": 1, "tried": 1},
    "usage": {"zhzh": 3, "bt": 0, "polish": 1, "generates": 4, "cost_cny": 0.02, "zhuque_tokens": 500},
    "elapsed_seconds": 1.0,
}


class FakeZhuqueClient:
    """打桩的朱雀客户端:一窗 0.8 红,整章判定偏 AI。"""

    used_tokens = 123

    def __init__(self, key, transport=None, **kwargs) -> None:
        self.used_tokens = 123

    async def windows(self, text: str):
        return [{"order": 1, "start": 0, "end": len(text), "text": text, "conf": 0.8, "label": 1}]

    async def verdict(self, text: str):
        return {"labels_ratio": {"0": 0.2, "1": 0.7, "2": 0.1}, "softmax_confidence": 0.7}


class FakeRewriterAdapter:
    model_name = "glm-5.2"
    api_key = "stub"

    def estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        return 0.004


REWRITER_OK = {"available": True, "provider": "GLM", "model": "glm-5.2",
               "verified": True, "adapter": FakeRewriterAdapter()}


async def fake_fix_chapter(text, terms, *, adapter, scorer, on_event=None, polish_enabled=True):
    if on_event:
        on_event({"stage": "window", "state": "done", "index": 1, "total": 1,
                  "status": "已过线", "s1": 0.2})
        on_event({"stage": "done"})
    return dict(CANNED_RESULT, polish_enabled=polish_enabled)


async def fake_fix_blind(text, terms, targets=None, *, layer="zhzh", adapter, on_event=None):
    if on_event:
        on_event({"stage": "done"})
    return dict(CANNED_RESULT, layer=layer)


async def fake_deai_text(text, terms, *, adapter, on_event=None):
    if on_event:
        on_event({"stage": "done"})
    return {"text": text, "rows": [], "usage": {"generates": 1, "cost_cny": 0.001, "zhuque_tokens": 0},
            "elapsed_seconds": 0.1}


@pytest.fixture()
def client():
    return TestClient(__import__("biyu.ui.app", fromlist=["app"]).app)


@pytest.fixture(autouse=True)
def _reset_state():
    zhuque_routes._JOBS.clear()
    zhuque_routes._RUNNING = False
    zhuque_routes._LAST_CHECK.update(red=None, fixable=None, chars=None)
    yield
    zhuque_routes._JOBS.clear()
    zhuque_routes._RUNNING = False
    # 清掉本文件写进测试隔离目录的假 Key,不串到别的测试
    from biyu.secure_config import user_config_dir
    for name in ("secrets.enc", "secret.key"):
        path = user_config_dir() / name
        if path.exists():
            path.unlink()


def _wait_job(client: TestClient, job_id: str, timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/zhuque/jobs/{job_id}")
        assert body.status_code == 200
        payload = body.json()
        if payload["status"] != "running":
            return payload
        time.sleep(0.05)
    pytest.fail("任务没在时限内完成")


def _save_key(client: TestClient) -> None:
    resp = client.post("/api/zhuque/key", json={"key": "sk-zhuque-test"})
    assert resp.status_code == 200 and resp.json()["ok"] is True


# ---------- status / key ----------

def test_status_shape_and_no_key(client, monkeypatch) -> None:
    monkeypatch.setattr(zhuque_routes, "_rewriter_info", lambda: REWRITER_OK)
    body = client.get("/api/zhuque/status").json()
    assert body["has_key"] is False
    assert body["rewriter"] == {"provider": "GLM", "model": "glm-5.2",
                                "verified": True, "available": True}


# ---------- _rewriter_info:只有 glm-5.2 标已验证(S-6b) ----------

class _StubRegistry:
    """只够 _rewriter_info 用的假 registry:models 字典 + 按配置造 adapter。"""

    def __init__(self, models: dict) -> None:
        self._models = models

    def get_adapter(self, alias: str):
        cfg = self._models[alias]
        return SimpleNamespace(api_key=cfg.get("api_key", "k"),
                               model_name=cfg.get("model_id", alias))


def _stub_registry(monkeypatch, models: dict) -> None:
    monkeypatch.setattr(zhuque_routes, "get_config_path", lambda: "unused")
    monkeypatch.setattr(zhuque_routes, "ModelRegistry", lambda _path: _StubRegistry(models))


def test_rewriter_verified_only_for_glm_52(client, monkeypatch) -> None:
    _stub_registry(monkeypatch, {"glm-5.2": {"provider": "glm", "model_id": "glm-5.2"}})
    info = zhuque_routes._rewriter_info()
    assert info["available"] is True and info["verified"] is True
    assert info["model"] == "glm-5.2" and info["provider"] == "GLM"


def test_rewriter_other_glm_model_unverified(client, monkeypatch) -> None:
    """其它 GLM 模型可用,但不标已验证(r12 只实测过 glm-5.2 的文字质量)。"""
    _stub_registry(monkeypatch, {"glm-4.6": {"provider": "glm", "model_id": "glm-4.6"}})
    info = zhuque_routes._rewriter_info()
    assert info["available"] is True and info["verified"] is False
    assert info["model"] == "glm-4.6"


def test_rewriter_renamed_glm_52_still_verified(client, monkeypatch) -> None:
    """作者给 glm-5.2 起了别的别名:模型本身验证过,仍标已验证。"""
    _stub_registry(monkeypatch, {"回译": {"provider": "glm", "model_id": "glm-5.2"}})
    info = zhuque_routes._rewriter_info()
    assert info["available"] is True and info["verified"] is True
    assert info["model"] == "glm-5.2"


def test_rewriter_deepseek_v4_pro_verified_when_no_glm(client, monkeypatch) -> None:
    """S-8-3:没配 GLM 时,配置里的 v4_pro(deepseek-v4-pro)是已验证档。"""
    _stub_registry(monkeypatch, {"v4_pro": {"provider": "deepseek",
                                            "model_id": "deepseek-v4-pro"}})
    info = zhuque_routes._rewriter_info()
    assert info["available"] is True and info["verified"] is True
    assert info["provider"] == "DeepSeek" and info["model"] == "deepseek-v4-pro"


def test_rewriter_v4_pro_without_key_falls_back_to_chat_model(client, monkeypatch) -> None:
    """v4_pro 配了但 DeepSeek 没 Key:仍回落作者当前聊天模型(未验证)。"""
    _stub_registry(monkeypatch, {
        "v4_pro": {"provider": "deepseek", "model_id": "deepseek-v4-pro", "api_key": ""},
        "deepseek-chat": {"provider": "deepseek", "model_id": "deepseek-chat"},
    })
    monkeypatch.setattr(
        zhuque_routes, "resolve_ui_adapter",
        lambda registry: (SimpleNamespace(api_key="k", model_name="deepseek-chat"),
                          "deepseek-chat"),
    )
    info = zhuque_routes._rewriter_info()
    assert info["available"] is True and info["verified"] is False
    assert info["provider"] == "DeepSeek" and info["model"] == "deepseek-chat"


def test_rewriter_fallback_model_unverified(client, monkeypatch) -> None:
    """没配 GLM、回落作者当前聊天模型:一律未验证。"""
    _stub_registry(monkeypatch, {"deepseek-chat": {"provider": "deepseek",
                                                   "model_id": "deepseek-chat"}})
    monkeypatch.setattr(
        zhuque_routes, "resolve_ui_adapter",
        lambda registry: (SimpleNamespace(api_key="k", model_name="deepseek-chat"),
                          "deepseek-chat"),
    )
    info = zhuque_routes._rewriter_info()
    assert info["available"] is True and info["verified"] is False
    assert info["provider"] == "DeepSeek" and info["model"] == "deepseek-chat"


def test_key_save_and_delete_roundtrip(client) -> None:
    _save_key(client)
    assert "sk-zhuque-test" not in client.get("/api/zhuque/status").text  # Key 不回显
    assert client.get("/api/zhuque/status").json()["has_key"] is True
    deleted = client.delete("/api/zhuque/key")
    assert deleted.status_code == 200 and deleted.json()["ok"] is True
    assert client.get("/api/zhuque/status").json()["has_key"] is False


def test_key_empty_rejected(client) -> None:
    resp = client.post("/api/zhuque/key", json={"key": "   "})
    assert resp.status_code == 400


# ---------- check ----------

def test_check_without_key_gives_plain_error(client) -> None:
    resp = client.post("/api/zhuque/check", json={"text": "任意一章。"})
    assert resp.status_code == 400
    assert "朱雀 Key" in resp.json()["detail"]


def test_check_returns_verdict_and_windows(client, monkeypatch) -> None:
    _save_key(client)
    monkeypatch.setattr(zhuque_routes, "ZhuqueClient", FakeZhuqueClient)
    resp = client.post("/api/zhuque/check", json={"text": "张今空收刀入鞘。"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["windows"][0]["conf"] == 0.8 and body["windows"][0]["order"] == 1
    assert body["verdict"]["labels_ratio"]["1"] == 0.7
    assert body["fixable"] == 1 and body["red"] == 1
    assert body["used_tokens"] == 123


def test_check_oversize_rejected(client, monkeypatch) -> None:
    _save_key(client)
    monkeypatch.setattr(zhuque_routes, "ZhuqueClient", FakeZhuqueClient)
    resp = client.post("/api/zhuque/check", json={"text": "字" * 200_001})
    assert resp.status_code == 413


# ---------- fix 两步走 ----------

def test_fix_estimate_only_neither_key_nor_job(client, monkeypatch) -> None:
    """estimate_only=true 只回预估,不要求 Key、不建任务。"""
    monkeypatch.setattr(zhuque_routes, "_rewriter_info", lambda: REWRITER_OK)
    resp = client.post("/api/zhuque/fix", json={"text": "字" * 3000, "estimate_only": True})
    assert resp.status_code == 200
    est = resp.json()["estimate"]
    assert est["minutes"] > 0 and est["cost_cny"] > 0 and est["zhuque_tokens"] > 0
    assert est["red_windows"] >= 1 and est["model"] == "glm-5.2"
    assert zhuque_routes._JOBS == {}


def test_fix_estimate_uses_last_check_when_same_text(client, monkeypatch) -> None:
    _save_key(client)
    monkeypatch.setattr(zhuque_routes, "ZhuqueClient", FakeZhuqueClient)
    monkeypatch.setattr(zhuque_routes, "_rewriter_info", lambda: REWRITER_OK)
    text = "张今空收刀入鞘。"
    client.post("/api/zhuque/check", json={"text": text})
    est = client.post("/api/zhuque/fix", json={"text": text, "estimate_only": True}).json()["estimate"]
    assert est["red_windows"] == 1


def test_fix_confirmation_creates_job_with_result_and_cost_log(client, monkeypatch) -> None:
    _save_key(client)
    monkeypatch.setattr(zhuque_routes, "_rewriter_info", lambda: REWRITER_OK)
    monkeypatch.setattr(zhuque_routes.engine, "fix_chapter", fake_fix_chapter)
    resp = client.post("/api/zhuque/fix", json={"text": "张今空收刀入鞘。", "terms": ["张今空"]})
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    payload = _wait_job(client, job_id)
    assert payload["status"] == "done"
    assert payload["result"]["rows"][0]["status"] == "已过线"
    assert payload["progress"]["pass"] == 1
    # 用量按现有 cost_log 方式记账
    from biyu.config import get_data_root
    log = Path(get_data_root()) / "cost_log.csv"
    assert log.exists()
    content = log.read_text(encoding="utf-8-sig")
    assert "zhuque" in content and "快检台" in content


def test_fix_without_key_plain_error(client, monkeypatch) -> None:
    monkeypatch.setattr(zhuque_routes, "_rewriter_info", lambda: REWRITER_OK)
    resp = client.post("/api/zhuque/fix", json={"text": "一段。"})
    assert resp.status_code == 400
    assert "朱雀 Key" in resp.json()["detail"]


def test_fix_without_rewriter_plain_error(client, monkeypatch) -> None:
    _save_key(client)
    unavailable = {"available": False, "provider": None, "model": None,
                   "verified": False, "adapter": None}
    monkeypatch.setattr(zhuque_routes, "_rewriter_info", lambda: unavailable)
    resp = client.post("/api/zhuque/fix", json={"text": "一段。"})
    assert resp.status_code == 400
    assert "还没配降 AI 率用的模型 Key" in resp.json()["detail"]  # S-7b 文案


def test_second_job_while_running_gets_409(client, monkeypatch) -> None:
    _save_key(client)
    monkeypatch.setattr(zhuque_routes, "_rewriter_info", lambda: REWRITER_OK)
    release = threading.Event()

    async def slow_fix(text, terms, *, adapter, scorer, on_event=None, polish_enabled=True):
        while not release.is_set():
            await asyncio.sleep(0.02)
        return dict(CANNED_RESULT)

    monkeypatch.setattr(zhuque_routes.engine, "fix_chapter", slow_fix)
    first = client.post("/api/zhuque/fix", json={"text": "第一章。"})
    assert first.status_code == 200
    job_id = first.json()["job_id"]

    second = client.post("/api/zhuque/fix", json={"text": "第二章。"})
    assert second.status_code == 409
    assert "任务在跑" in second.json()["detail"]
    blind = client.post("/api/zhuque/fix-blind", json={"text": "第三章。"})
    assert blind.status_code == 409

    release.set()
    assert _wait_job(client, job_id)["status"] == "done"


def test_unknown_job_404(client) -> None:
    assert client.get("/api/zhuque/jobs/does-not-exist").status_code == 404


# ---------- fix-blind ----------

def test_fix_blind_needs_rewriter_but_not_key(client, monkeypatch) -> None:
    monkeypatch.setattr(zhuque_routes, "_rewriter_info", lambda: REWRITER_OK)
    monkeypatch.setattr(zhuque_routes.engine, "fix_blind", fake_fix_blind)
    resp = client.post("/api/zhuque/fix-blind", json={"text": "一段。", "terms": [], "targets": None})
    assert resp.status_code == 200
    payload = _wait_job(client, resp.json()["job_id"])
    assert payload["kind"] == "fix-blind" and payload["status"] == "done"
    assert payload["result"]["rows"][0]["status"] == "已过线"


def test_fix_blind_without_rewriter_plain_error(client, monkeypatch) -> None:
    unavailable = {"available": False, "provider": None, "model": None,
                   "verified": False, "adapter": None}
    monkeypatch.setattr(zhuque_routes, "_rewriter_info", lambda: unavailable)
    resp = client.post("/api/zhuque/fix-blind", json={"text": "一段。"})
    assert resp.status_code == 400
    assert "还没配降 AI 率用的模型 Key" in resp.json()["detail"]  # S-7b 文案


def test_fix_blind_passes_layer_through(client, monkeypatch) -> None:
    """/fix-blind 接受 layer 并透传给引擎(作者对仍红的窗用 bt 再跑)。"""
    monkeypatch.setattr(zhuque_routes, "_rewriter_info", lambda: REWRITER_OK)
    seen: dict = {}

    async def spy_fix_blind(text, terms, targets=None, *, layer="zhzh", adapter, on_event=None):
        seen["layer"] = layer
        return await fake_fix_blind(text, terms, targets, layer=layer,
                                    adapter=adapter, on_event=on_event)

    monkeypatch.setattr(zhuque_routes.engine, "fix_blind", spy_fix_blind)
    resp = client.post("/api/zhuque/fix-blind",
                       json={"text": "一段。", "targets": [2], "layer": "bt"})
    assert resp.status_code == 200
    assert _wait_job(client, resp.json()["job_id"])["result"]["layer"] == "bt"
    assert seen["layer"] == "bt"


def test_fix_blind_rejects_unknown_layer(client, monkeypatch) -> None:
    monkeypatch.setattr(zhuque_routes, "_rewriter_info", lambda: REWRITER_OK)
    resp = client.post("/api/zhuque/fix-blind", json={"text": "一段。", "layer": "顺一遍"})
    assert resp.status_code == 422   # Literal 校验直接拒


# ---------- deai(独立去 AI 味,付费功能) ----------

def test_deai_creates_job_without_zhuque_key(client, monkeypatch) -> None:
    """deai 不碰朱雀、不需要 Key;复用现有 job 机制。"""
    monkeypatch.setattr(zhuque_routes, "_rewriter_info", lambda: REWRITER_OK)
    monkeypatch.setattr(zhuque_routes.engine, "deai_text", fake_deai_text)
    resp = client.post("/api/zhuque/deai", json={"text": "一段要去 AI 味的正文。", "terms": []})
    assert resp.status_code == 200
    payload = _wait_job(client, resp.json()["job_id"])
    assert payload["kind"] == "deai" and payload["status"] == "done"
    assert payload["result"]["text"] == "一段要去 AI 味的正文。"


def test_deai_without_rewriter_plain_error(client, monkeypatch) -> None:
    unavailable = {"available": False, "provider": None, "model": None,
                   "verified": False, "adapter": None}
    monkeypatch.setattr(zhuque_routes, "_rewriter_info", lambda: unavailable)
    resp = client.post("/api/zhuque/deai", json={"text": "一段。"})
    assert resp.status_code == 400
    assert "改写模型不可用" in resp.json()["detail"]


def test_deai_oversize_rejected(client, monkeypatch) -> None:
    monkeypatch.setattr(zhuque_routes, "_rewriter_info", lambda: REWRITER_OK)
    resp = client.post("/api/zhuque/deai", json={"text": "字" * 200_001})
    assert resp.status_code == 413


# ---------- _license_block 授权闸(check_feature 不允许 → 402) ----------

@pytest.mark.parametrize("path,payload", [
    ("/api/zhuque/fix", {"text": "一段。"}),
    ("/api/zhuque/fix-blind", {"text": "一段。"}),
    ("/api/zhuque/deai", {"text": "一段。"}),
])
def test_paid_endpoints_go_through_feature_gate(client, monkeypatch, path, payload) -> None:
    from biyu.licensing import LicenseDecision

    monkeypatch.setattr(zhuque_routes, "_rewriter_info", lambda: REWRITER_OK)
    monkeypatch.setattr(zhuque_routes, "check_feature",
                        lambda feature: LicenseDecision(False, "beta_expired", "内测版已到期"))
    resp = client.post(path, json=payload)
    assert resp.status_code == 402
    assert resp.json() == {"detail": "内测版已到期", "code": "license_required"}
    assert zhuque_routes._JOBS == {}


# ---------- 旧前端兼容 ----------

def test_fix_accepts_legacy_smooth_enabled(client, monkeypatch) -> None:
    """旧前端传 smooth_enabled=False:路由映射为引擎的 polish_enabled=False。"""
    _save_key(client)
    monkeypatch.setattr(zhuque_routes, "_rewriter_info", lambda: REWRITER_OK)
    monkeypatch.setattr(zhuque_routes.engine, "fix_chapter", fake_fix_chapter)
    resp = client.post("/api/zhuque/fix",
                       json={"text": "张今空收刀入鞘。", "smooth_enabled": False})
    assert resp.status_code == 200
    payload = _wait_job(client, resp.json()["job_id"])
    assert payload["result"]["polish_enabled"] is False


# ---------- report ----------

def test_report_maps_pdf_scores_to_windows(client, monkeypatch) -> None:
    from tests.test_zhuque_report import RAW
    monkeypatch.setattr(zhuque_routes, "extract_pdf_text", lambda data: RAW)
    text = (
        "夜色深沉，南城旧武馆的后院里静得可怕，张今空站在石阶旁，嘴角勾起一抹三分薄凉七分讥诮的弧度，"
        "眼神微眯透出危险的气息，某种意义上来说，昨晚那场死亡回溯的阴影似乎还在他心头萦绕。"
        "方圆端着茶碗走过来，她的身影在月光下宛如一尊凝固的雕塑，张今空心里仿佛闪过一丝莫名的悲凉，"
        "却只是缓缓低头擦刀。"
    )
    resp = client.post(
        "/api/zhuque/report",
        files={"pdf": ("报告.pdf", b"%PDF-stub", "application/pdf")},
        data={"text": text},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["fragments"] == 2
    window = body["windows"][0]
    assert window["score"] == 0.9123   # 横跨两片段取更差值
    assert window["label"] == "疑似"   # 0.5–0.99 属「疑似」
    assert body["red"] == 1


def test_report_without_fragment_marks_rejected(client, monkeypatch) -> None:
    monkeypatch.setattr(zhuque_routes, "extract_pdf_text", lambda data: "这不是朱雀报告")
    resp = client.post(
        "/api/zhuque/report",
        files={"pdf": ("x.pdf", b"stub", "application/pdf")},
        data={"text": "一段。"},
    )
    assert resp.status_code == 400
    assert "朱雀" in resp.json()["detail"]
