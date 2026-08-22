"""Inspect an occupied runtime port without terminating its process."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import urllib.error
import urllib.request


def _normal_path(value: str) -> str:
    return str(Path(value).expanduser().resolve()).casefold()


def inspect_port(port: int, requested_root: Path) -> int:
    url = f"http://127.0.0.1:{port}/api/version"
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, UnicodeError, json.JSONDecodeError):
        print(f"端口 {port} 已被其他程序占用。没有动它，请先关闭那个程序。")
        return 2

    existing = payload.get("data_root") if isinstance(payload, dict) else None
    if payload.get("runtime") != "笔驭" or not isinstance(existing, str):
        print(f"端口 {port} 已被其他程序占用。没有动它，请先关闭那个程序。")
        return 2
    if _normal_path(existing) == _normal_path(str(requested_root)):
        print("同一个数据位置的笔驭已经在运行。")
        return 3

    print(
        f"8080 上已经有一个笔驭在跑，它用的是 {existing}，"
        f"你这次要用的是 {requested_root.resolve()}。"
    )
    print("没有动它。先关掉那一个，再启动这一个。")
    return 2


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    args = parser.parse_args()
    return inspect_port(args.port, args.data_root)


if __name__ == "__main__":
    raise SystemExit(main())
