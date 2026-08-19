"""[DEPRECATED] FastAPI 主应用(P8-M2 章节工作台壳)。

P8-M2.5 T1 壳统一后,作者工作台统一走 `biyu ui`(src/biyu/ui/app.py)。本 app
保留为只读旧入口(specs/P8-M2.5.md line 9):路由仍可访问,但不再加新功能;
M4 退役时一并清。

启动入口:`biyu serve`(src/biyu/cli/serve_cmd.py),已加 deprecated banner。

注意:web/routes.py 的 router 仍被 ui/app.py include 复用,代码本身不废弃;
**废弃的是这个独立的 web app 入口**。新功能(首页 / SSE 进度 / 扫榜缓存 / 提示词页)
一律加到 `biyu ui`,不加到这里。
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from biyu.web.routes import router

app = FastAPI(title="笔驭 BiYu", version="0.1.0")

# 挂载 API 路由
app.include_router(router)

# 挂载静态文件
_static_dir = Path(__file__).parent / "static"
if _static_dir.exists():
    app.mount("/", StaticFiles(directory=str(_static_dir), html=True), name="static")
