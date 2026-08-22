"""作者工作台 FastAPI 主应用 — 统一壳(P8-M2.5 T1)。

T1 壳统一后:本 app 是 `biyu ui` 单入口,聚合
- M1 立项屏路由(/api/env /api/session /api/propose,来自 biyu.ui.routes)
- M2 章节工作台 + 审读路由(/api/books/* 等,来自 biyu.web.routes)

工程选择(D-83 工程细节,中枢备案):用 include_router 把 web router 挂到 ui app,
不物理搬代码。原因:
- 满足 spec 验收"`biyu ui` 单入口可完成"(specs/P8-M2.5.md line 25)
- web/ 现有测试(test_web_review_routes.py 依赖 `biyu.web.app:app`)零回归
- 后续 T2-T5 在 ui/ 里加新路由,web/ 保留作 deprecated 旧入口

启动入口:biyu.ui_cmd 调 uvicorn.run("biyu.ui.app:app", ...)。
"""
from __future__ import annotations

import json
import os
import asyncio
import subprocess
import hashlib
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from biyu.ui.routes import router as _ui_router
from biyu.ui.workbench import router as _workbench_router
from biyu.ui.setup import router as _setup_router
from biyu.ui.voiceprint import router as _voiceprint_router
from biyu.ui.voiceprint_import import router as _voiceprint_import_router
from biyu.ui.overview import router as _overview_router
from biyu.ui.good_sentences import router as _good_sentences_router
from biyu.ui.settings import router as _settings_router
from biyu.ui.backup import router as _backup_router
from biyu.web.routes import router as _web_router
from biyu import __version__


BUILD_DATE = "20260819"


def _runtime_label() -> str:
    """Return the product name; deployment details stay in diagnostics."""
    return "笔驭"


def _runtime_identity() -> dict[str, object]:
    root = Path(os.environ.get("BIYU_PROJECT_ROOT") or Path.cwd()).resolve()
    try:
        short_sha = subprocess.check_output(["git", "-C", str(root), "rev-parse", "--short=8", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.SubprocessError):
        short_sha = "unknown"
    source = os.environ.get("BIYU_DATA_ROOT_SOURCE", "environment")
    return {
        "role": _runtime_label(),
        "checkout": root.name,
        "repo": "guge0/biyu",
        "sha": short_sha,
        "data_root": str(Path(os.environ.get("BIYU_DATA_ROOT") or "").resolve()),
        "data_root_temporary": source == "environment",
    }

app = FastAPI(title="笔驭作者工作台", version="0.2.0")


@app.on_event("startup")
async def enforce_runtime_binding() -> None:
    from biyu.config import validate_runtime_binding

    validate_runtime_binding()


@app.on_event("startup")
async def z1_startup_backup() -> None:
    """Start the configured backup without making a failed backup block the UI."""
    from biyu.backup_service import load_backup_settings, run_backup
    from biyu.config import get_data_root
    from biyu.secure_config import user_config_dir

    settings = load_backup_settings()
    if not settings.enabled:
        return

    scope = "test" if os.environ.get("BIYU_RUNTIME_ROLE") == "test" else "production"
    source = get_data_root()
    destination = Path(settings.destination)

    async def _run() -> None:
        try:
            await asyncio.to_thread(
                run_backup, source, destination, scope=scope, reason="startup", status_dir=user_config_dir()
            )
        except Exception:
            # run_backup persists the failed state; the author UI reads it on load.
            return

    asyncio.create_task(_run())


# 写保护：写方法只允许落在当前进程 primary 数据根的书。
# 匹配 /api/workbench/books/{book}/... 与 /api/books/{book}/... 的写请求。
def _write_protection(request: Request) -> JSONResponse | None:
    if request.method not in ("POST", "PUT", "DELETE", "PATCH"):
        return None
    path = request.url.path
    book: str | None = None
    if path.startswith("/api/workbench/books/"):
        rest = path[len("/api/workbench/books/"):]
        book = rest.split("/", 1)[0]
    elif path.startswith("/api/settings/books/"):
        rest = path[len("/api/settings/books/"):]
        book = rest.split("/", 1)[0]
    elif path.startswith("/api/books/"):
        rest = path[len("/api/books/"):]
        book = rest.split("/", 1)[0]
    if not book:
        return None
    try:
        from biyu.ui.workbench import _book_root, get_data_root as active_data_root
        owner = _book_root(book)
        if owner == active_data_root().resolve():
            return None
    except HTTPException:
        return None  # 书不存在交给原路由报 404
    return JSONResponse(
        status_code=403,
        content={"detail": f"书「{book}」不属于当前运行数据根，只读；写入暂不开放。"},
    )


@app.middleware("http")
async def i1_dual_root_write_gate(request: Request, call_next):
    blocked = _write_protection(request)
    if blocked is not None:
        return blocked
    return await call_next(request)

# M1 立项屏路由(env/session/propose)
app.include_router(_ui_router)
app.include_router(_workbench_router)
app.include_router(_setup_router)
app.include_router(_voiceprint_router)
app.include_router(_voiceprint_import_router)
app.include_router(_overview_router)
app.include_router(_good_sentences_router)
app.include_router(_settings_router)
app.include_router(_backup_router)
# M2 章节工作台 + 审读路由(books/chapters/characters/truth_files/cost/SSE/reviews)
app.include_router(_web_router)


@app.get("/api/version")
def runtime_version() -> dict[str, object]:
    identity = _runtime_identity()
    return {"version": __version__, "build": f"{BUILD_DATE} · {identity['sha']}", "runtime": _runtime_label(), **identity}


_ASSET_REF = re.compile(r'(?P<prefix>(?:src|href)="/(?P<name>[^"?]+))\?v=[^"]+(?P<suffix>")')
def _landing_path() -> Path:
    project_root = os.environ.get("BIYU_PROJECT_ROOT")
    if project_root:
        return Path(project_root).resolve() / "docs" / "index.html"
    return Path(__file__).resolve().parents[3] / "docs" / "index.html"


def render_static_html(path: Path) -> str:
    html = path.read_text(encoding="utf-8")

    def replace(match: re.Match[str]) -> str:
        asset = _static_dir / match.group("name")
        if not asset.is_file():
            return match.group(0)
        digest = hashlib.sha256(asset.read_bytes()).hexdigest()[:8]
        return f'{match.group("prefix")}?v={digest}{match.group("suffix")}'

    return _ASSET_REF.sub(replace, html)


@app.get("/about.html", response_class=HTMLResponse)
def about_page() -> str:
    """Serve the repository landing page directly; keep one canonical file."""
    if not _landing_path().is_file():
        return "<!doctype html><html lang=\"zh-CN\"><meta charset=\"utf-8\"><title>笔驭</title><p>介绍页不在。</p>"
    return '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>介绍 · 笔驭</title>
<style>*{box-sizing:border-box}html,body{height:100%;margin:0}nav{height:58px;padding:0 28px;display:flex;align-items:center;justify-content:space-between;background:#f8f5ee;border-bottom:1px solid #e0dacc;font-family:system-ui,sans-serif}nav a{color:#262119;text-decoration:none}.links{display:flex;gap:28px}.active{font-weight:700;border-bottom:2px solid #262119}iframe{display:block;width:100%;height:calc(100% - 58px);border:0}@media(max-width:600px){nav{padding:0 16px}.links{gap:18px}}</style>
<nav><a href="/" class="brand">笔驭</a><div class="links"><a href="/">书架</a><a class="active" aria-current="page">介绍</a></div></nav><iframe src="/about-content.html" title="笔驭介绍"></iframe></html>'''


@app.get("/about-content.html", response_class=HTMLResponse)
def about_content() -> str:
    landing_page = _landing_path()
    if not landing_page.is_file():
        return "<!doctype html><html lang=\"zh-CN\"><meta charset=\"utf-8\"><p>介绍页不在。</p>"
    return landing_page.read_text(encoding="utf-8")


@app.get("/{page}.html", response_class=HTMLResponse)
def static_html(page: str) -> str:
    path = _static_dir / f"{page}.html"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="页面不存在")
    return render_static_html(path)


@app.get("/", response_class=HTMLResponse)
def static_index() -> str:
    return render_static_html(_static_dir / "index.html")

# 挂静态文件(html=True 让 / 自动返 index.html)
_static_dir = Path(__file__).parent / "static"
if _static_dir.exists():
    app.mount("/", StaticFiles(directory=str(_static_dir), html=True), name="static")
