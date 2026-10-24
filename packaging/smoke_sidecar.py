"""打包冒烟(T1 红绿载体,T10 复用):干净临时数据根拉起 biyu-sidecar.exe。

流程:挑空闲端口 → 干净 env(剥离宿主 BIYU_*)注入安装版语义 → 拉起 exe →
轮询 /api/version → 断言 200 与版本字段 → taskkill 杀进程树 → 输出 JSON 结果。
构建前运行=红(exe 缺失);构建后运行=绿(带启动耗时)。
用法:.venv\\Scripts\\python.exe packaging\\smoke_sidecar.py [--exe path] [--home path]
"""
from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

_DEFAULT_REPO = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _build_env(data_root: Path, home: Path, port: int) -> dict[str, str]:
    env = {k: v for k, v in __import__("os").environ.items() if not k.startswith("BIYU_")}
    env.update(
        {
            "BIYU_ENV": "prod",
            "BIYU_RUNTIME_ROLE": "production",
            "BIYU_DATA_ROOT": str(data_root),
            "BIYU_DATA_ROOT_SOURCE": "environment",
            "BIYU_PRODUCTION_DATA_ROOT": str(data_root),
            "BIYU_PROJECT_ROOT": str(home),
            "BIYU_CHECKOUT_NAME": "biyu-studio",
            "BIYU_SIDECAR_PORT": str(port),
        }
    )
    return env


def _kill_tree(pid: int) -> None:
    subprocess.run(
        ["taskkill", "/PID", str(pid), "/T", "/F"],
        capture_output=True,
        check=False,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", default=str(_DEFAULT_REPO / "packaging" / "dist" / "biyu-sidecar" / "biyu-sidecar.exe"))
    # exe 目录兼任 BIYU_PROJECT_ROOT(构建脚本已把 config/docs/prompts/assets 铺在 exe 旁)
    ap.add_argument("--home", default=None)
    ap.add_argument("--timeout", type=float, default=60.0)
    args = ap.parse_args()

    exe = Path(args.exe)
    home = Path(args.home) if args.home else exe.parent
    result: dict[str, object] = {"exe": str(exe), "home": str(home)}

    if not exe.is_file():
        result["ok"] = False
        result["error"] = f"sidecar executable not found: {exe}(先运行 packaging/build_sidecar.ps1)"
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1
    if not (home / "config" / "models.yaml.example").is_file():
        result["ok"] = False
        result["error"] = f"home payload missing config/models.yaml.example under {home}"
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    data_root = Path(tempfile.mkdtemp(prefix="biyu-smoke-"))
    data_root.mkdir(parents=True, exist_ok=True)
    port = _free_port()
    result["data_root"] = str(data_root)
    result["port"] = port

    env = _build_env(data_root, home, port)
    t0 = time.perf_counter()
    proc = subprocess.Popen(
        [str(exe)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=str(home),
    )

    version_payload: dict | None = None
    deadline = time.monotonic() + args.timeout
    url = f"http://127.0.0.1:{port}/api/version"
    last_err = ""
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            tail = (proc.stdout.read() or b"")[-2000:].decode("utf-8", "replace") if proc.stdout else ""
            result["ok"] = False
            result["error"] = f"sidecar exited early code={proc.returncode}: {tail}"
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 1
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.status == 200:
                    version_payload = json.loads(resp.read().decode("utf-8"))
                    break
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
            last_err = str(exc)
        time.sleep(0.25)

    startup_ms = round((time.perf_counter() - t0) * 1000)
    _kill_tree(proc.pid)
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        result["kill_timeout"] = True

    if version_payload is None:
        result["ok"] = False
        result["error"] = f"/api/version not ready in {args.timeout}s: {last_err}"
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    result.update(
        {
            "ok": True,
            "startup_ms": startup_ms,
            "version": version_payload,
        }
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
