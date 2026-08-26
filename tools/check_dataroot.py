"""Machine-check the data-root lockdown invariants."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import sys
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]

GREEN = "绿"
RED = "红"
NOT_DONE = "未做"


@dataclass(frozen=True)
class Result:
    name: str
    status: str
    detail: str


def _line_of(path: Path, needle: str) -> int | None:
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if needle in line:
            return number
    return None


def _source_result(
    name: str,
    path: Path,
    *,
    required: str | None = None,
    forbidden: str | None = None,
) -> Result:
    relative = path.relative_to(ROOT).as_posix()
    if required is not None:
        line = _line_of(path, required)
        if line is None:
            return Result(name, RED, f"{relative}:1 缺少要求的代码：{required}")
        return Result(name, GREEN, f"{relative}:{line}")
    assert forbidden is not None
    line = _line_of(path, forbidden)
    if line is not None:
        return Result(name, RED, f"{relative}:{line} 仍包含禁用内容：{forbidden}")
    return Result(name, GREEN, f"{relative} 未发现禁用内容")


def collect_results(environ: dict[str, str] | None = None) -> list[Result]:
    values = os.environ if environ is None else environ
    raw = values.get("BIYU_DATA_ROOT", "").strip()
    if raw:
        data_root = Path(raw).expanduser().resolve()
        explicit = Result("显式数据根", GREEN, f"BIYU_DATA_ROOT={data_root}")
    else:
        data_root = None
        explicit = Result("显式数据根", RED, "environment:BIYU_DATA_ROOT 未设置")

    config_path = ROOT / "src/biyu/config.py"
    trace_path = ROOT / "src/biyu/editor/multi_agent.py"
    backup_path = ROOT / "src/biyu/backup_service.py"
    results = [
        explicit,
        _source_result(
            "禁止生产根回落",
            config_path,
            forbidden='Path.home() / "BiyuData"',
        ),
        _source_result(
            "测试隔离生产根",
            config_path,
            required="测试进程禁止使用生产数据根",
        ),
        _source_result(
            "书级阶段追踪",
            trace_path,
            required='Path(book_dir).resolve() / "phase_trace"',
        ),
        _source_result(
            "移除固定追踪目录",
            trace_path,
            forbidden="T-P3-D-2.2",
        ),
        _source_result(
            "备份记录运行时来源",
            backup_path,
            required='"source_path": str(source.resolve())',
        ),
    ]

    role = values.get("BIYU_RUNTIME_ROLE", "").strip().lower()
    if role != "production":
        results.append(Result(
            "生产根顶层结构",
            NOT_DONE,
            f"environment:BIYU_RUNTIME_ROLE={role or '<未设置>'}，需在 production 角色核验",
        ))
    elif data_root is None:
        results.append(Result(
            "生产根顶层结构",
            NOT_DONE,
            "environment:BIYU_DATA_ROOT 未设置，无法核验生产根",
        ))
    elif not data_root.is_dir():
        results.append(Result(
            "生产根顶层结构",
            RED,
            f"{data_root} 不存在或不是目录",
        ))
    else:
        non_books = sorted(
            path for path in data_root.iterdir()
            if path.is_dir() and not (path / "book.json").is_file()
        )
        if non_books:
            details = "；".join(str(path) for path in non_books)
            results.append(Result("生产根顶层结构", RED, f"非书目录：{details}"))
        else:
            results.append(Result("生产根顶层结构", GREEN, str(data_root)))
    return results


def exit_code(results: Iterable[Result]) -> int:
    statuses = {result.status for result in results}
    return 1 if RED in statuses else 0


def main() -> int:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8", errors="replace")
    results = collect_results()
    for result in results:
        print(f"{result.name}: {result.status} - {result.detail}")
    return exit_code(results)


if __name__ == "__main__":
    raise SystemExit(main())
