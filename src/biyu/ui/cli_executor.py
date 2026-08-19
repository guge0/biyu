"""R3-1 generic CLI executor; it never imports pipeline/editor/writer business modules."""
from __future__ import annotations

import asyncio
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator
from uuid import uuid4

from biyu.config import resolve_book_dir
from .action_registry import action_for
from .workbench_state import read_workbench_step, write_workbench_step
from .workbench_versions import snapshot_candidate


_RUNNING: dict[tuple[str, int], dict[str, object]] = {}


def running_action(book: str, chapter: int) -> str | None:
    entry = _RUNNING.get((book, chapter))
    return str(entry["action"]) if entry else None


def _new_run_log(book_dir: Path, chapter: int, action_id: str) -> tuple[str, Path]:
    """Reserve a unique, append-only workbench run log."""
    now = datetime.now(timezone.utc)
    run_id = f"{now:%Y%m%dT%H%M%S}_{uuid4().hex[:8]}"
    run_dir = book_dir / "logs" / f"ch{chapter}" / "runs"
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / f"{run_id}.log"
    path.write_text(
        f"run_id={run_id}\naction={action_id}\nstarted_at={now.isoformat()}\nstatus=running\n---\n",
        encoding="utf-8",
    )
    return run_id, path


def _append_run_log(path: Path, text: str) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(text.rstrip("\r\n") + "\n")


async def execute(action_id: str, *, book: str, chapter: int, confirmed: bool, extra: dict[str, str]) -> AsyncGenerator[dict, None]:
    key = (book, chapter)
    if key in _RUNNING:
        yield {"type": "error", "message": "这一章正在处理中，请等当前操作结束后再试", "returncode": 409}
        return
    action = action_for(action_id, book=book, chapter=chapter)
    if action.confirm and not confirmed:
        yield {"type": "confirmation_required", "estimate": action.estimate}
        return
    book_dir = resolve_book_dir(book)
    previous_step = read_workbench_step(book_dir, chapter)
    start_steps = {
        "write": "generation",
        "regenerate": "generation",
        "rewrite": "revision",
        "adopt": "adoption",
        "revoke_planning": "planning",
    }
    if action_id in start_steps:
        write_workbench_step(book_dir, chapter, start_steps[action_id])
    run_id, run_log = _new_run_log(book_dir, chapter, action_id)
    # `biyu` is an entry point, not a runnable `python -m biyu.cli.main` module.
    argv = [sys.executable, "-c", "from biyu.cli.main import app; app()", *action.argv]
    if action_id in {"verdict", "adopt", "excerpt", "chapter_review", "archive_excerpt", "retag_excerpt", "rewrite"}:
        for flag in ("verdict", "positive", "negative", "content", "kind", "version", "anchor", "entry-id", "new-kind", "package"):
            if extra.get(flag):
                argv.extend((f"--{flag}", extra[flag]))
    env = os.environ.copy()
    env["BIYU_TRACK"] = "engineering"
    _RUNNING[key] = {
        "action": action_id,
        "started_at": time.time(),
        "run_id": run_id,
        "log_path": str(run_log),
    }
    last_output = ""
    try:
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
            )
        except Exception as exc:
            write_workbench_step(book_dir, chapter, previous_step)
            message = f"操作没有启动：{exc}"
            _append_run_log(run_log, f"---\nstatus=failed\nreturncode=launch_error\nerror={message}")
            yield {"type": "error", "message": message, "returncode": 1, "run_id": run_id}
            return
        _RUNNING[key]["process"] = proc
        if action.stdin_after_confirm:
            proc.stdin.write(action.stdin_after_confirm.encode("utf-8"))
            await proc.stdin.drain()
            proc.stdin.close()
        yield {
            "type": "started",
            "argv": action.argv,
            "run_id": run_id,
            "log_path": str(run_log.relative_to(book_dir)),
        }
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            decoded = line.decode("utf-8", errors="replace").rstrip()
            if decoded:
                last_output = decoded
            _append_run_log(run_log, decoded)
            yield {"type": "log", "text": decoded, "run_id": run_id}
        code = await proc.wait()
        if code:
            # A failed run owns no process transition: assets and author step stay put.
            write_workbench_step(book_dir, chapter, previous_step)
            message = f"操作没有完成（退出码 {code}）"
            if last_output:
                message += f"：{last_output}"
            _append_run_log(run_log, f"---\nstatus=failed\nreturncode={code}\nerror={message}")
            yield {"type": "error", "message": message, "returncode": code, "run_id": run_id}
        else:
            done_steps = {
                "talk": "planning",
                "write": "reading",
                "regenerate": "reading",
                "rewrite": "reading",
                "adopt": "review",
                "revoke_planning": "planning",
                "chapter_review": "review",
            }
            if action_id in done_steps:
                write_workbench_step(book_dir, chapter, done_steps[action_id])
            if action_id in {"write", "regenerate", "rewrite"}:
                snapshot_candidate(book_dir, chapter, run_id=run_id, action=action_id)
            _append_run_log(run_log, f"---\nstatus=done\nreturncode={code}")
            yield {"type": "done", "returncode": code, "run_id": run_id}
    finally:
        _RUNNING.pop(key, None)
