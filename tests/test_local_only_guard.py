"""本机服务防护：Host / Origin 校验（整改清单 #5）。"""
from __future__ import annotations

from fastapi.testclient import TestClient


def _client() -> TestClient:
    from biyu.ui.app import app

    return TestClient(app)


def test_local_hosts_are_allowed():
    client = _client()
    for host in ("127.0.0.1:8080", "localhost:8765", "127.0.0.1"):
        assert client.get("/api/version", headers={"Host": host}).status_code == 200


def test_foreign_host_is_rejected():
    # DNS rebinding:外部域名被解析到 127.0.0.1 后,浏览器发来的 Host 仍是外部域名
    response = _client().get("/api/version", headers={"Host": "evil.example:8080"})
    assert response.status_code == 400


def test_cross_site_write_is_rejected():
    response = _client().post(
        "/api/quickcheck/scan",
        json={"text": "测试"},
        headers={"Host": "127.0.0.1:8080", "Origin": "https://evil.example"},
    )
    assert response.status_code == 403


def test_same_origin_write_is_allowed():
    response = _client().post(
        "/api/quickcheck/scan",
        json={"text": "测试"},
        headers={"Host": "127.0.0.1:8080", "Origin": "http://127.0.0.1:8080"},
    )
    assert response.status_code == 200


def test_extra_hosts_can_be_allowed_explicitly(monkeypatch):
    monkeypatch.setenv("BIYU_ALLOWED_HOSTS", "192.168.1.20")
    assert _client().get("/api/version", headers={"Host": "192.168.1.20:8080"}).status_code == 200


def test_fastapi_version_matches_release():
    from biyu import __version__
    from biyu.ui.app import app

    assert app.version == __version__
