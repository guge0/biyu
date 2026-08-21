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


def _runtime_identity() -> dict[str, str]:
    root = Path(os.environ.get("BIYU_PROJECT_ROOT") or Path.cwd()).resolve()
    try:
        short_sha = subprocess.check_output(["git", "-C", str(root), "rev-parse", "--short=8", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.SubprocessError):
        short_sha = "unknown"
    return {"role": _runtime_label(), "checkout": root.name, "repo": "guge0/biyu", "sha": short_sha, "data_root": str(Path(os.environ.get("BIYU_DATA_ROOT") or "").resolve())}

app = FastAPI(title="笔驭作者工作台", version="0.2.0")


@app.on_event("startup")
async def enforce_runtime_binding() -> None:
    from biyu.config import validate_runtime_binding

    validate_runtime_binding()


@app.on_event("startup")
async def z1_startup_backup() -> None:
    """Start the configured backup without making a failed backup block the UI."""
    if os.environ.get("BIYU_AUTO_BACKUP") != "1":
        return
    from biyu.backup_service import run_backup
    from biyu.config import get_data_root

    scope = "test" if os.environ.get("BIYU_RUNTIME_ROLE") == "test" else "production"
    source = get_data_root()
    destination = Path(os.environ.get("BIYU_BACKUP_ROOT", r"D:\BiyuBackup"))

    async def _run() -> None:
        try:
            await asyncio.to_thread(run_backup, source, destination, scope=scope, reason="startup")
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
def runtime_version() -> dict[str, str]:
    identity = _runtime_identity()
    return {"version": __version__, "build": f"{BUILD_DATE} · {identity['sha']}", "runtime": _runtime_label(), **identity}


_ASSET_REF = re.compile(r'(?P<prefix>(?:src|href)="/(?P<name>[^"?]+))\?v=[^"]+(?P<suffix>")')


def render_static_html(path: Path) -> str:
    html = path.read_text(encoding="utf-8")

    def replace(match: re.Match[str]) -> str:
        asset = _static_dir / match.group("name")
        if not asset.is_file():
            return match.group(0)
        digest = hashlib.sha256(asset.read_bytes()).hexdigest()[:8]
        return f'{match.group("prefix")}?v={digest}{match.group("suffix")}'

    return _ASSET_REF.sub(replace, html)


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
