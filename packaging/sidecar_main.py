"""笔驭 v1.0 打包版 sidecar 入口(packaging/)。

Electron 薄壳负责选端口、初始化安装版数据根、注入 BIYU_PROJECT_ROOT(home 载荷目录)
后拉起本进程;本进程只做一件事:以既有 FastAPI 应用(biyu.ui.app:app)原样起 uvicorn,
不改变任何既有 API 与数据根语义——缺 BIYU_DATA_ROOT 时沿用产品侧
「Data root not found; refusing to start」拒启行为。
"""
from __future__ import annotations

import os
import sys

_HOST = "127.0.0.1"


def _required_port() -> int:
    raw = (os.environ.get("BIYU_SIDECAR_PORT") or "").strip()
    if not raw.isdigit():
        print(
            "[biyu-sidecar] BIYU_SIDECAR_PORT 未设置或非法,拒绝启动(端口由 Electron 壳指定)。",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return int(raw)


def main() -> None:
    port = _required_port()
    if not (os.environ.get("BIYU_DATA_ROOT") or "").strip():
        print("[biyu-sidecar] BIYU_DATA_ROOT 未设置,拒绝启动(数据根锁定机制)。", file=sys.stderr)
        raise SystemExit(2)

    import uvicorn
    from biyu.ui.app import app  # 运行时导入:先快速失败,再做重导入

    uvicorn.run(app, host=_HOST, port=port, log_level="info")


if __name__ == "__main__":
    main()
