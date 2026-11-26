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
from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
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
from biyu.ui.appearance import router as _appearance_router
from biyu.ui.backup import router as _backup_router
from biyu.web.routes import router as _web_router
from biyu import __version__


# Keep the runtime stamp truthful for source checkouts; release packaging can
# pin it explicitly through BIYU_BUILD_DATE.
BUILD_DATE = os.environ.get("BIYU_BUILD_DATE", "") or date.today().strftime("%Y%m%d")


def _version_key(value: str) -> tuple[int, ...] | None:
    """Parse a simple dotted release version without adding a dependency."""
    match = re.fullmatch(r"v?(\d+(?:\.\d+)*)", str(value).strip())
    if not match:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def _release_manifest_candidates() -> list[Path]:
    configured = os.environ.get("BIYU_RELEASE_MANIFEST", "").strip()
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured).expanduser())
    project_root = os.environ.get("BIYU_PROJECT_ROOT", "").strip()
    if project_root:
        candidates.append(Path(project_root) / "config" / "published_version.json")
    candidates.append(Path.cwd() / "config" / "published_version.json")
    data_root = os.environ.get("BIYU_DATA_ROOT", "").strip()
    if data_root:
        candidates.append(Path(data_root) / "published_version.json")
    seen: set[str] = set()
    unique: list[Path] = []
    for candidate in candidates:
        resolved = str(candidate.expanduser().resolve()).casefold()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(candidate)
    return unique


def _published_release() -> tuple[str | None, str | None, str | None]:
    """Read a local release manifest as ``(version, build, source)``."""
    env_version = os.environ.get("BIYU_PUBLISHED_VERSION", "").strip()
    if env_version:
        return env_version, os.environ.get("BIYU_PUBLISHED_BUILD", "").strip() or None, "environment"
    for path in _release_manifest_candidates():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if isinstance(payload, str):
            version, build = payload.strip(), None
        elif isinstance(payload, dict):
            version = str(payload.get("version") or payload.get("release") or "").strip()
            build_value = payload.get("build")
            build = str(build_value).strip() if build_value else None
        else:
            continue
        if version:
            return version, build, str(path)
    return None, None, None


def _release_update() -> dict[str, object]:
    current = __version__
    published, published_build, source = _published_release()
    role = os.environ.get("BIYU_RUNTIME_ROLE", "").strip().lower()
    enabled = role not in {"development", "test"}
    current_key = _version_key(current)
    published_key = _version_key(published or "")
    available = bool(enabled and published and published_key and current_key and published_key > current_key)
    return {
        "available": available,
        "current": current,
        "published": published,
        "published_build": published_build,
        "source": source,
    }


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
        # S-3C 浏览器模式（便携）页内提示通道:启动器经 BIYU_LAUNCH_MODE 注入,前端据此标注
        "launch_mode": os.environ.get("BIYU_LAUNCH_MODE", "").strip(),
    }

app = FastAPI(title="笔驭作者工作台", version=__version__)


# ---------- 本机服务防护(整改清单 #5) ----------
# 笔驭只服务本机。校验 Host 防 DNS rebinding(外部网页把自己的域名解析到 127.0.0.1
# 后以同源身份读书稿、调用付费生成);写操作再校验 Origin 防跨站提交。
# 局域网访问等特殊场景用 BIYU_ALLOWED_HOSTS(逗号分隔)显式放行。
# "testserver" 是 Starlette TestClient 的默认 Host,不是可公网解析的域名。
_LOCAL_HOSTS = ("127.0.0.1", "localhost", "testserver")


def _allowed_hosts() -> set[str]:
    extra = {h.strip().lower() for h in os.environ.get("BIYU_ALLOWED_HOSTS", "").split(",") if h.strip()}
    return set(_LOCAL_HOSTS) | extra


def _host_name(value: str) -> str:
    value = value.strip().lower()
    if value.startswith("["):
        return value.split("]", 1)[0] + "]"
    return value.split(":", 1)[0]


@app.middleware("http")
async def _local_only_guard(request: Request, call_next):
    allowed = _allowed_hosts()
    if _host_name(request.headers.get("host", "")) not in allowed:
        return JSONResponse({"detail": "笔驭只接受本机访问"}, status_code=400)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin", "")
        if origin and origin != "null":
            origin_host = _host_name(origin.split("://", 1)[-1])
            if origin_host not in allowed:
                return JSONResponse({"detail": "拒绝来自外部网页的请求"}, status_code=403)
    return await call_next(request)


# S-10 段3a-6：HTML 一律 no-cache——换版本后浏览器不再吃到旧页面（老板截图的
# 「旧版 shell」即缓存所致；带 ?v= 指纹的静态资源不受影响，接口返回体非 HTML 也不受影响）。
@app.middleware("http")
async def s10_html_no_cache(request: Request, call_next):
    response = await call_next(request)
    content_type = response.headers.get("content-type", "")
    if content_type.startswith("text/html"):
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.on_event("startup")
async def enforce_runtime_binding() -> None:
    _start_behind_monitor()


def _start_behind_monitor() -> None:
    """后台线程每 10 分钟刷新一次版本差距缓存;/api/version 只读缓存,零网络等待。"""
    import threading

    from biyu.runtime_config import git_behind_count

    def _loop() -> None:
        import time

        while True:
            try:
                git_behind_count(max_age_seconds=0)
            except Exception:
                pass
            time.sleep(600)

    threading.Thread(target=_loop, daemon=True, name="biyu-update-check").start()


def _behind_count_cached() -> int | None:
    from biyu.runtime_config import git_behind_count

    return git_behind_count(max_age_seconds=float("inf"))


@app.on_event("startup")
async def enforce_runtime_binding() -> None:
    _start_behind_monitor()
    from biyu.config import validate_runtime_binding
    from biyu.runtime_config import verify_runtime_data_root

    actual = validate_runtime_binding()
    role = os.environ.get("BIYU_RUNTIME_ROLE", "").strip().lower()
    if role in {"production", "development"}:
        verify_runtime_data_root(role, actual)


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


async def _in_app_daily_backup_loop() -> None:
    """S-7e：便携包没有 Windows 计划任务，笔驭开着时每小时看一次，超过 24 小时没备就补备。"""
    from datetime import datetime, timedelta

    from biyu.backup_service import get_backup_status, load_backup_settings, run_backup
    from biyu.config import get_data_root
    from biyu.secure_config import user_config_dir

    while True:
        await asyncio.sleep(3600)
        try:
            settings = load_backup_settings()
            if not settings.enabled:
                continue
            scope = "test" if os.environ.get("BIYU_RUNTIME_ROLE") == "test" else "production"
            destination = Path(settings.destination)
            status = get_backup_status(destination, scope=scope, status_dir=user_config_dir())
            last = status.last_backup_at
            if last:
                last_dt = datetime.fromisoformat(last)
                now = datetime.now(last_dt.tzinfo) if last_dt.tzinfo else datetime.now()
                if now - last_dt < timedelta(hours=24):
                    continue
            await asyncio.to_thread(
                run_backup, get_data_root(), destination, scope=scope, reason="daily", status_dir=user_config_dir()
            )
        except Exception:
            continue


@app.on_event("startup")
async def z2_in_app_daily_backup() -> None:
    if os.environ.get("BIYU_RUNTIME_ROLE") == "test":
        return
    asyncio.create_task(_in_app_daily_backup_loop())


@app.on_event("startup")
async def s3_seed_sample_book() -> None:
    """S-3 安装版首启:空书架幂等种入示例书《死亡回溯》(BIYU_SEED_SAMPLE_BOOK=1 时)。

    纯本地、秒级完成;种子失败只记日志,不阻塞应用启动。
    """
    import logging

    if os.environ.get("BIYU_SEED_SAMPLE_BOOK", "").strip() != "1":
        return
    try:
        from biyu.ui_seed import maybe_seed_sample_book

        outcome = maybe_seed_sample_book()
        logging.getLogger("biyu.ui_seed").info("sample book seed: %s", outcome)
    except Exception:
        logging.getLogger("biyu.ui_seed").exception("示例书种入失败(不影响启动)")


@app.on_event("startup")
async def s3b_warn_data_root_inside_source_repo() -> None:
    """S-3B 缺陷2 兜底:数据根落在笔驭源码仓树内时启动即告警(开发/走查环境误配)。

    真实用户根(%APPDATA% 等)不在任何仓内,不受影响;git add 撞忽略规则的
    守卫洞已在 ensure_local_repository/repo_root_for_book 补上,这里只做可见提醒。
    """
    import logging

    try:
        from biyu.config import get_data_root
        from biyu.git_helper import source_repo_toplevel_containing

        offender = source_repo_toplevel_containing(get_data_root())
    except Exception:
        return
    if offender is not None:
        logging.getLogger("biyu.ui").warning(
            "数据根位于笔驭源码仓树内(%s):相关书稿操作会改用数据根自己的仓,"
            "但请把测试数据根移到任何 git 仓之外,避免外层忽略规则干扰。",
            offender,
        )


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
app.include_router(_appearance_router)
from biyu.ui.ui_seed_routes import router as _ui_seed_router  # S-3:耕读历/印章只读接口
from biyu.ui.wizard import router as _wizard_router  # S-3 T4:一句话开书向导
from biyu.ui.legacy_migrate import router as _legacy_migrate_router  # S-3 T4:旧版数据根迁移
from biyu.ui.cell_draft import router as _cell_draft_router  # S-3 T5:设定/大纲格 AI 起草(草稿闸)
from biyu.ui.quickcheck_routes import router as _quickcheck_router  # S-3 T7:快检台(纯本地)
from biyu.ui.agent_routes import router as _agent_router  # S-4A:责编助手引擎(无 UI)
from biyu.ui.zhuque_routes import router as _zhuque_router  # S-6:朱雀体检与降分(快检台②卡)

app.include_router(_ui_seed_router)
app.include_router(_wizard_router)
app.include_router(_legacy_migrate_router)
app.include_router(_cell_draft_router)
app.include_router(_quickcheck_router)
app.include_router(_agent_router)
app.include_router(_zhuque_router)
from biyu.ui.diagnostics import router as _diagnostics_router  # S-7b:一键导出诊断包(不含 Key 与书稿)

app.include_router(_diagnostics_router)
# M2 章节工作台 + 审读路由(books/chapters/characters/truth_files/cost/SSE/reviews)
app.include_router(_web_router)


@app.get("/api/version")
def runtime_version() -> dict[str, object]:
    identity = _runtime_identity()
    update = _release_update()
    return {
        "version": __version__,
        "build": f"v{__version__} · {BUILD_DATE}",
        "runtime": _runtime_label(),
        "update": update,
        # Flat aliases keep simple clients compatible with the small original
        # version payload while the nested object carries release metadata.
        "update_available": update["available"],
        "latest_version": update["published"],
        # 2026-10 版本差距红点:落后 origin/main 的提交数(None=暂时无法判断)
        "behind_commits": _behind_count_cached(),
        **identity,
    }


@app.get("/api/features")
def runtime_features() -> dict[str, object]:
    """S-7a 功能开关一次性下发;页面据此藏入口,不要各自硬编码。"""
    from biyu.config import feature_enabled

    return {"features": {"zebian": feature_enabled("zebian")}}


@app.get("/api/license/status")
def license_status() -> dict[str, object]:
    """S-7a 内测授权状态:版本/到期日/剩余天数/各功能是否可用。"""
    from biyu import licensing

    return licensing.status()


@app.post("/api/update/pull")
def update_pull() -> dict:
    """拉取最新(快进)。运行中的服务不换代码,拉完需重启笔驭生效。"""
    from biyu.runtime_config import git_pull_ff

    ok, message = git_pull_ff()
    hint = "已拉取最新代码；请关闭笔驭并重新双击启动，更新才会生效。" if ok else message
    return {"ok": ok, "message": message, "hint": hint}


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

    html = _ASSET_REF.sub(replace, html)
    # S-10 3a修正·工单第8条：用户主题随 HTML 内联——首帧就是用户的主题。
    # theme-boot.js 优先回放 localStorage 缓存（同会话内最新），没有缓存时（冷启动/
    # 全新浏览器档案）用这段服务端注入的令牌，不再先亮 300ms 再变色。
    # data-theme 属性也一并注入（暗色 CSS 规则 keyed 在 html[data-theme="dark"] 上）。
    boot_css, theme_key = _server_theme_boot_css()
    if boot_css:
        inline = ('<script>window.__BIYU_THEME_BOOT__='
                  + json.dumps(boot_css).replace("<", "\\u003c").replace(">", "\\u003e")
                  + ';</script>')
        html = re.sub(r"(<head[^>]*>)", lambda m: m.group(1) + inline, html, count=1)
        html = re.sub(r"(<html[^>]*?)(>)",
                      lambda m: m.group(1) + f' data-theme="{theme_key}"' + m.group(2), html, count=1)
    # S-10 3g·工单第3条：浏览器标签图标——16 页共用本函数，统一注入两条 icon link
    #（现代浏览器选 SVG，老引擎退 ICO）；页面内全局栏「驭」品牌块不是浏览器图标，不动。
    html = re.sub(r"(<head[^>]*>)",
                  lambda m: m.group(1)
                  + '<link rel="icon" type="image/svg+xml" href="/favicon.svg">'
                  + '<link rel="icon" href="/favicon.ico" sizes="any">',
                  html, count=1)
    return html


_THEME_BOOT_CACHE: dict | None = None


def _theme_boot_presets() -> dict:
    """THEME_PRESETS / WALLPAPER_PRESETS 从 shell.js 的标记段解析——值只存一份（shell.js 是事实源）。"""
    global _THEME_BOOT_CACHE
    if _THEME_BOOT_CACHE is None:
        shell = (_static_dir / "shell.js").read_text(encoding="utf-8")
        themes = json.loads(re.search(r"/\*S1-THEME-BEGIN\*/(.*?)/\*S1-THEME-END\*/", shell, re.S).group(1))
        papers = json.loads(re.search(r"/\*S1-WALLPAPER-BEGIN\*/(.*?)/\*S1-WALLPAPER-END\*/", shell, re.S).group(1))
        _THEME_BOOT_CACHE = {"themes": themes, "papers": papers}
    return _THEME_BOOT_CACHE


def _server_theme_boot_css() -> tuple[str, str]:
    """把用户当前主题/取色覆盖/背景拼成与 shell.js cacheThemeTokens 同格式的 cssText。

    与 applyThemeTokens + applyCustomColors + applyBackgroundTokens 的默认分支一一对应；
    返回 (cssText, theme_key)；读不了偏好（文件损坏等）就返回空串，页面退回
    theme-boot 的 localStorage 路径。
    """
    from . import appearance
    try:
        prefs = appearance.load_ui_prefs()
    except Exception:
        return "", ""
    try:
        boot = _theme_boot_presets()
    except Exception:
        return "", ""
    theme_key = prefs.get("theme") if boot["themes"].get(prefs.get("theme")) else "default"
    preset = boot["themes"].get(theme_key) or boot["themes"]["default"]
    parts = [f"{k}: {v};" for k, v in preset.items() if k.startswith("--")]
    custom = prefs.get("custom") or {}
    for token in ("--paper", "--surface", "--ink", "--mark", "--mark-bg"):
        if custom.get(token):
            parts.append(f"{token}: {custom[token]};")
            if token == "--ink":
                parts.append(f"--ink-solid: {custom[token]};")
    bg = prefs.get("background") or {}
    image = "none"
    if bg.get("type") == "preset":
        image = boot["papers"].get(bg.get("preset")) or "none"
    elif bg.get("type") == "custom" and bg.get("file"):
        from urllib.parse import quote
        image = 'url("/api/ui/background-file/%s")' % quote(str(bg["file"]))
    try:
        overlay = min(98.0, max(65.0, float(bg.get("overlay", 90)))) / 100
    except (TypeError, ValueError):
        overlay = 0.90
    try:
        blur = max(0.0, float(bg.get("blur", 0)))
    except (TypeError, ValueError):
        blur = 0.0
    parts.append(f"--bg-image: {image};")
    parts.append(f"--bg-overlay-alpha: {overlay:.2f};")
    parts.append(f"--bg-blur: {int(blur)}px;")
    # S-10 3g·工单第2条：玻璃个性化随首帧注入——只在非默认时覆盖（与 shell.js applyGlassTokens
    # 同构：雾面浓度乘三团色基准档，卡片透明度直驱 --glass-bg，strong=min(0.95, 值+0.07)；
    # 默认值不写，HTML 出栈带的 preset 令牌本身已是 0.38/0.45）。
    mist = _clampf(bg.get("mist"), 0.0, 200.0, 100.0)
    glass = _clampf(bg.get("glass"), 0.20, 0.90, 0.38)
    if abs(mist - 100.0) > 1e-9:
        base = (30, 35, 30) if theme_key == "dark" else (45, 45, 40)
        for key, b in zip(("a", "b", "c"), base):
            v = int(b * mist / 10 + 0.5) / 10  # 与 JS Math.round 同向
            parts.append(f"--glass-blob-alpha-{key}: {v:g}%;")
    if abs(glass - 0.38) > 1e-9:
        parts.append(f"--glass-bg: {_swap_alpha(preset['--glass-bg'], glass)};")
        parts.append(f"--glass-strong: {_swap_alpha(preset['--glass-strong'], min(0.95, round(glass + 0.07, 2)))};")
    return " ".join(parts), theme_key


def _clampf(value, low: float, high: float, fallback: float) -> float:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return fallback
    return max(low, min(high, n))


def _swap_alpha(rgba: str, alpha: float) -> str:
    """把 rgba(...) 字面量末位 alpha 换成指定值（通道数保留）。"""
    return re.sub(r"^(rgba?\([^)]*,\s*)[\d.]+(\)$)",
                  lambda m: m.group(1) + f"{alpha:g}" + m.group(2), rgba)


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


@app.get("/favicon.svg", include_in_schema=False)
def favicon_svg() -> Response:
    """S-10 3g·工单第3条：显式路由钉死 content-type=image/svg+xml。

    本路由必须在 / 的 StaticFiles mount 之前注册（Starlette 按注册序匹配，mount 在后
    会吞掉一切）；Windows 下 mimetypes 读注册表，.svg 的类型不保证，不赌。
    """
    path = _static_dir / "favicon.svg"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="favicon.svg 不存在")
    return Response(content=path.read_bytes(), media_type="image/svg+xml")


if _static_dir.exists():
    app.mount("/", StaticFiles(directory=str(_static_dir), html=True), name="static")