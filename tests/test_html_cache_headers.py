"""S-10 段3a-6：HTML 响应必须带 Cache-Control: no-cache。

老板实拍里的「旧版 shell」就是浏览器缓存了旧页面（8765 便携包 HTML 无任何缓存头）。
本闸钉住：页面(/ 与 *.html，含 about)一律 no-cache；CSS/JS 等 ?v= 指纹静态资源不受影响，
接口 JSON 不受影响。返回体与路径零改动。
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from biyu.ui.app import app


def test_html_responses_carry_no_cache() -> None:
    client = TestClient(app)
    for path in ("/", "/index.html", "/workbench.html", "/book.html", "/about.html"):
        resp = client.get(path)
        assert resp.status_code == 200, path
        assert "text/html" in resp.headers.get("content-type", ""), path
        assert resp.headers.get("cache-control") == "no-cache", path


def test_static_assets_and_api_keep_their_own_caching() -> None:
    client = TestClient(app)
    css = client.get("/styles.css")
    assert css.status_code == 200
    assert "text/css" in css.headers.get("content-type", "")
    assert css.headers.get("cache-control") != "no-cache"
    version = client.get("/api/version")
    assert version.status_code == 200
    assert version.headers.get("cache-control") != "no-cache"
