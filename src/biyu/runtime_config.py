"""Persistent runtime data-root selection for author and development roles."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys
from typing import Mapping

from biyu.secure_config import user_config_dir


class RuntimeConfigurationError(ValueError):
    """A runtime cannot start without an unambiguous, valid configuration."""


@dataclass(frozen=True)
class RuntimeDataRoot:
    path: Path
    persistent_path: Path
    source: str
    config_path: Path

    @property
    def temporary(self) -> bool:
        return self.source == "environment"


def _normal_role(role: str) -> str:
    selected = role.strip().lower()
    if selected not in {"production", "development"}:
        raise RuntimeConfigurationError("运行角色必须是 production 或 development")
    return selected


def runtime_config_path(role: str, config_dir: Path | None = None) -> Path:
    selected = _normal_role(role)
    root = Path(config_dir) if config_dir is not None else user_config_dir()
    return root / f"runtime-{selected}.json"


def resolve_runtime_data_root(
    role: str,
    *,
    config_dir: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> RuntimeDataRoot:
    """Read the role's persistent file, then apply an explicit env override."""
    config_path = runtime_config_path(role, config_dir)
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise RuntimeConfigurationError(f"数据根持久配置不存在：{config_path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeConfigurationError(f"数据根持久配置读不出来：{config_path}（{exc}）") from exc

    stored = payload.get("data_root") if isinstance(payload, dict) else None
    if not isinstance(stored, str) or not stored.strip():
        raise RuntimeConfigurationError(f"数据根持久配置缺少有效的 data_root：{config_path}")

    values = os.environ if environ is None else environ
    override = values.get("BIYU_DATA_ROOT", "").strip()
    persistent_path = Path(stored.strip()).expanduser().resolve()
    if not persistent_path.is_dir():
        raise RuntimeConfigurationError(f"持久配置中的数据根不存在或不是目录：{persistent_path}")

    selected = override or str(persistent_path)
    source = "environment" if override else "persistent"
    path = Path(selected).expanduser().resolve()
    if not path.is_dir():
        raise RuntimeConfigurationError(f"数据根不存在或不是目录：{path}")
    return RuntimeDataRoot(
        path=path,
        persistent_path=persistent_path,
        source=source,
        config_path=config_path.resolve(),
    )


def verify_runtime_data_root(
    role: str,
    actual_root: Path,
    *,
    config_dir: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> Path:
    """Fail closed unless the actual root matches this run's resolved root."""
    selected = resolve_runtime_data_root(role, config_dir=config_dir, environ=environ)
    actual = Path(actual_root).expanduser().resolve()
    if actual != selected.path:
        raise RuntimeConfigurationError(
            "实际数据根与本次解析结果不一致："
            f"解析结果为 {selected.path}，实际为 {actual}"
        )
    return actual


def validate_runtime_port(role: str, port: int) -> int:
    selected = _normal_role(role)
    if selected == "development" and port == 8080:
        raise RuntimeConfigurationError("开发版禁止监听 8080；请使用 8090。")
    if not 1 <= port <= 65535:
        raise RuntimeConfigurationError(f"端口无效：{port}")
    return port


def _resolve_command(role: str) -> int:
    try:
        selected = resolve_runtime_data_root(role)
    except RuntimeConfigurationError as exc:
        print(str(exc))
        return 2
    print(json.dumps({
        "data_root": str(selected.path),
        "persistent_data_root": str(selected.persistent_path),
        "source": selected.source,
        "temporary": selected.temporary,
        "config_path": str(selected.config_path),
    }, ensure_ascii=False))
    return 0


def _verify_command(role: str, actual_root: str | None) -> int:
    if not actual_root:
        print("verify 缺少 --actual-root")
        return 2
    try:
        verified = verify_runtime_data_root(role, Path(actual_root))
    except RuntimeConfigurationError as exc:
        print(str(exc))
        return 2
    print(json.dumps({"verified_data_root": str(verified)}, ensure_ascii=False))
    return 0


def main() -> int:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["resolve", "verify"])
    parser.add_argument("--role", required=True, choices=["production", "development"])
    parser.add_argument("--actual-root")
    args = parser.parse_args()
    if args.command == "verify":
        return _verify_command(args.role, args.actual_root)
    return _resolve_command(args.role)


if __name__ == "__main__":
    raise SystemExit(main())


# ---------- 2026-10 版本差距红点:对比 HEAD 与 origin/main(老板要求) ----------
_BEHIND_CACHE: dict = {"ts": 0.0, "count": None}


def git_behind_count(project_root=None, max_age_seconds: float = 600.0) -> int | None:
    """本地 checkout 落后 origin/main 的提交数;网络/凭据不可用时返回 None(不亮红点)。

    带 10 分钟缓存:/api/version 高频轮询不得每次打网络。后台监控线程负责刷新。
    """
    import subprocess
    import time

    now = time.time()
    if now - _BEHIND_CACHE["ts"] < max_age_seconds:
        return _BEHIND_CACHE["count"]
    count: int | None = None
    try:
        root = str(Path(project_root) if project_root else Path.cwd())
        fetch = subprocess.run(
            ["git", "fetch", "origin", "main"], cwd=root,
            capture_output=True, text=True, timeout=25,
        )
        if fetch.returncode == 0:
            rev = subprocess.run(
                ["git", "rev-list", "--count", "HEAD..origin/main"], cwd=root,
                capture_output=True, text=True, timeout=10,
            )
            if rev.returncode == 0:
                count = int(rev.stdout.strip() or 0)
    except Exception:
        pass
    _BEHIND_CACHE.update(ts=now, count=count)
    return count


def git_pull_ff(project_root=None) -> tuple[bool, str]:
    """拉取最新(快进);服务进程不换代码,提示重启生效。"""
    import subprocess

    try:
        root = str(Path(project_root) if project_root else Path.cwd())
        result = subprocess.run(
            ["git", "pull", "--ff-only"], cwd=root,
            capture_output=True, text=True, timeout=90, encoding="utf-8", errors="replace",
        )
        output = (result.stdout + result.stderr).strip()
        return result.returncode == 0, output or ("已拉取" if result.returncode == 0 else "拉取失败")
    except Exception as exc:
        return False, str(exc)
