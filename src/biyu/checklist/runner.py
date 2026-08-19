"""F-1/F-2 必检项核对 · 结果落盘与管线挂载。

落盘(工单 5.2):
- `data/<书>/logs/ch<N>/candidates/<版本名>_checklist.json`(结构化)
- 同目录 `<版本名>_checklist.md`(人可读,由 JSON 渲染)

挂载:正文生成后调用 `run_and_save_checklist`(engine_version 参数选 f1/f2),
核对只报不拦;planning 无「## 必检项」块或 LLM 全败 → warnings 说明,正文照常落盘。
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from biyu.checklist.engine import (
    ChecklistResult,
    judge_checklist,
    render_markdown,
)
from biyu.checklist.f4_engine import (
    F4Result,
    judge_checklist_f4,
    render_markdown_f4,
)
from biyu.checklist.parser import ChecklistMissingError, parse_checklist


def default_version() -> str:
    return f"ch_{time.strftime('%Y%m%d_%H%M%S')}"


async def run_and_save_checklist(
    book_dir: Path,
    chapter_num: int,
    planning_text: str,
    chapter_text: str,
    adapter,
    version: str | None = None,
    engine_version: str = "f4",
) -> tuple[ChecklistResult | F4Result | None, list[str]]:
    """核对并落盘。返回 (结果, warnings);任何失败都不抛(只报)。"""
    warnings: list[str] = []
    if not chapter_text or not chapter_text.strip():
        warnings.append("必检项核对跳过: 正文为空")
        return None, warnings
    try:
        spec = parse_checklist(planning_text)
    except ChecklistMissingError as e:
        warnings.append(f"必检项核对跳过: {e}")
        return None, warnings

    version = version or default_version()
    try:
        # 引擎只保留 f4(老板指令清理 f1/f2/f3);engine_version 参数兼容旧值一律走 f4
        result = await judge_checklist_f4(spec, chapter_text, adapter, version=version, chapter=chapter_num)
    except Exception as e:
        warnings.append(f"必检项核对失败: {e}")
        return None, warnings

    candidates_dir = book_dir / "logs" / f"ch{chapter_num}" / "candidates"
    candidates_dir.mkdir(parents=True, exist_ok=True)
    json_path = candidates_dir / f"{version}_checklist.json"
    md_path = candidates_dir / f"{version}_checklist.md"
    payload = result.to_dict()
    payload["candidate_sha"] = hashlib.sha256(chapter_text.encode("utf-8")).hexdigest()
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown_f4(result), encoding="utf-8")

    s = result.summary
    if isinstance(result, F4Result):
        print(
            f"  [{result.engine_version.upper()} 必检项] met {s['met']} / unmet {s['unmet']} / unclear {s['unclear']}"
            f" / invalid {s['invalid']}({s['invalid_rate']}) (共 {s['total']}) → {json_path.relative_to(book_dir)}"
        )
        if s["unmet"] > 0:
            warnings.append(f"必检项 {s['unmet']} 条未达成,详见 {json_path.name}")
        if s["invalid"] > 0:
            warnings.append(f"必检项 {s['invalid']} 条引证无效(invalid),详见 {json_path.name}")
    else:
        print(
            f"  [F-1 必检项] met {s['met']} / unmet {s['unmet']} / unclear {s['unclear']}"
            f" (共 {s['total']}) → {json_path.relative_to(book_dir)}"
        )
        if s["unmet"] > 0:
            warnings.append(f"F-1 必检项 {s['unmet']} 条未达成,详见 {json_path.name}")
        if s["unclear"] > 0:
            warnings.append(f"F-1 必检项 {s['unclear']} 条无法判定(unclear),详见 {json_path.name}")
    return result, warnings
