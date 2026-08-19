"""Opinion-led, on-demand evidence pack for the Ring 4 rework diagnosis."""
from __future__ import annotations

import json
import hashlib
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


PROMPT_PATH = Path(__file__).resolve().parents[3] / "prompts" / "workbench" / "diagnosis.md"
LAYERS = {
    "细纲层": "退回细纲",
    "方案层": "退回改方案",
    "执笔层": "继续修订",
}
STYLE_HINTS = ("措辞", "节奏", "人物", "表达", "文风", "句子", "台词")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {} if path.suffix == ".json" else []


def _complete_rounds(book_dir: Path, chapter: int) -> list[Path]:
    root = book_dir / "logs" / f"ch{chapter}" / "revisions"
    rounds = []
    for path in root.glob("round_[0-9]*") if root.exists() else []:
        manifest = _json(path / "manifest.json")
        if manifest.get("status") == "complete":
            rounds.append(path)
    return sorted(rounds, key=lambda path: int(path.name.split("_", 1)[1]))


def revision_round_count(book_dir: Path, chapter: int) -> int:
    return len(_complete_rounds(book_dir, chapter))


def candidate_sha(book_dir: Path, chapter: int) -> str:
    pending = book_dir / "chapters" / "_pending" / f"ch{chapter}.md"
    official = book_dir / "chapters" / f"ch{chapter}.md"
    text = _read(pending if pending.exists() else official)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def diagnosis_is_fresh(book_dir: Path, chapter: int, value: dict[str, Any] | None = None) -> bool:
    value = value or read_diagnosis(book_dir, chapter)
    if value and "candidate_sha" not in value:
        return True
    return bool(
        value
        and value.get("candidate_sha")
        and value.get("candidate_sha") == candidate_sha(book_dir, chapter)
        and int(value.get("rounds", -1)) == revision_round_count(book_dir, chapter)
    )


def _parse_result(text: str) -> tuple[str, str, str]:
    """Parse the constrained result object; never search the reasoning body."""
    value: Any
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        # Ring-4 signed prompt emitted one constrained ``层：理由`` line.
        # Keep that installed contract without scanning beyond its prefix.
        match = re.fullmatch(r"(细纲层|方案层|执笔层)[：:]\s*(.+)", text, re.S)
        if not match:
            raise RuntimeError("诊断没有给出完整的结构化结论，请重试")
        layer, reason = match.groups()
        return layer, LAYERS[layer], reason.strip()
    if not isinstance(value, dict):
        raise RuntimeError("诊断结构无效：必须返回一个对象")
    layer = str(value.get("layer", "")).strip()
    action = str(value.get("action", "")).strip()
    reason = str(value.get("reason", "")).strip()
    if layer not in LAYERS or not action or not reason:
        raise RuntimeError("诊断没有给出完整的 layer/action/reason")
    if action != LAYERS[layer]:
        raise RuntimeError("诊断的 layer/action/reason 不一致，未生成分流")
    return layer, action, reason


def _general_comment(comments: str) -> str:
    before_details = comments.split("## 逐条意见", 1)[0]
    lines = [line.strip() for line in before_details.splitlines() if line.strip() and not line.startswith("#")]
    value = " ".join(lines).strip()
    return "" if value in {"（无整体意见）", "(无整体意见)"} else value


def _paragraphs(text: str) -> list[str]:
    return [block.strip() for block in re.split(r"\n\s*\n", text) if block.strip()]


def _scoped_context(text: str, anchors: set[int]) -> str:
    paragraphs = _paragraphs(text)
    selected: set[int] = set()
    for anchor in anchors:
        center = max(0, anchor - 1)
        selected.update(index for index in (center - 1, center, center + 1) if 0 <= index < len(paragraphs))
    return "\n\n".join(f"[第 {index + 1} 段] {paragraphs[index]}" for index in sorted(selected))


def _problem_sentences(book_dir: Path, chapter: int) -> list[dict[str, Any]]:
    path = book_dir / "样本库" / "负例候选.md"
    result = []
    for line in _read(path).splitlines():
        if not line.startswith("- {"):
            continue
        try:
            item = json.loads(line[2:])
        except json.JSONDecodeError:
            continue
        if item.get("type") == "problem" and int(item.get("chapter", 0) or 0) == chapter and item.get("id"):
            result.append(item)
    return result


def build_diagnosis_messages(book_dir: Path, chapter: int, prompt_path: Path | None = None) -> list[dict[str, str]]:
    rounds = _complete_rounds(book_dir, chapter)
    if len(rounds) < 3:
        raise ValueError("同一章完成第 3 轮修订后才能诊断")
    prompt = prompt_path or PROMPT_PATH
    if not prompt.exists():
        raise RuntimeError(f"诊断提示词尚未签署安装: {prompt}")

    opinion_blocks: list[str] = []
    context_blocks: list[str] = []
    all_opinions = ""
    for round_path in rounds:
        number = int(round_path.name.split("_", 1)[1])
        comments = _read(round_path / "comments.md")
        issues = _json(round_path / "issues.json")
        if not isinstance(issues, list):
            issues = []
        opinion_blocks.append(f"### 第 {number} 轮\n\n{comments}\n\n问题卡索引：\n{json.dumps(issues, ensure_ascii=False)}")
        all_opinions += "\n" + comments + "\n" + json.dumps(issues, ensure_ascii=False)
        anchors = {
            int(issue.get("paragraph") or issue.get("line") or 0)
            for issue in issues
            if int(issue.get("paragraph") or issue.get("line") or 0) > 0
        }
        candidate = _read(round_path / "candidate.md")
        broad = bool(_general_comment(comments)) or (bool(issues) and not anchors)
        selected = candidate if broad else _scoped_context(candidate, anchors)
        context_blocks.append(f"### 第 {number} 轮候选\n\n{selected or '（本轮没有可定位的候选上下文）'}")

    problem_items = _problem_sentences(book_dir, chapter)
    counts: dict[str, int] = {}
    for item in problem_items:
        text = str(item.get("text", "")).strip()
        counts[text] = counts.get(text, 0) + 1
    expand_problem_text = any(hint in all_opinions for hint in STYLE_HINTS)
    problem_index = []
    for item in problem_items:
        text = str(item.get("text", "")).strip()
        row = {
            "id": item.get("id"),
            "version_sha": item.get("version_sha"),
            "anchor": item.get("anchor"),
        }
        if expand_problem_text or counts.get(text, 0) > 1:
            row["text"] = text
        problem_index.append(row)

    outline = _read(book_dir / "outlines" / f"ch{chapter}.md")
    planning = _read(book_dir / "logs" / f"ch{chapter}" / "planning.md")
    evidence = "\n\n".join((
        "## 作者意见与问题卡索引\n\n" + "\n\n".join(opinion_blocks),
        "## 本章问题句索引\n\n" + json.dumps(problem_index, ensure_ascii=False),
        "## 按需读取的候选上下文\n\n" + "\n\n".join(context_blocks),
        "## 层级核对材料\n\n### 当前方案\n" + planning + "\n\n### 本章细纲\n" + outline,
    ))
    return [
        {"role": "system", "content": prompt.read_text(encoding="utf-8")},
        {"role": "user", "content": evidence},
    ]


def read_diagnosis(book_dir: Path, chapter: int) -> dict[str, Any]:
    value = _json(book_dir / "logs" / f"ch{chapter}" / "diagnosis.json")
    return value if isinstance(value, dict) else {}


async def diagnose_chapter(
    book_dir: Path,
    chapter: int,
    *,
    adapter=None,
    log_cost_fn: Callable[[float, float], None] | None = None,
) -> dict[str, Any]:
    messages = build_diagnosis_messages(book_dir, chapter)
    if adapter is None:
        from biyu.config import get_registry

        adapter = get_registry().get_adapter_for_stage("planner")
    started = time.time()
    # Reasoning models may spend the first several hundred tokens internally;
    # leave enough headroom for the required one-line visible conclusion.
    response = await adapter.generate(messages=messages, temperature=0.1, max_tokens=1500)
    latency = time.time() - started
    if log_cost_fn is not None:
        log_cost_fn(float(getattr(response, "cost", 0.0)), latency)
    text = str(response.text).strip()
    layer, action, reason = _parse_result(text)
    result = {
        "layer": layer,
        "reason": reason,
        "action": action,
        "rounds": revision_round_count(book_dir, chapter),
        "candidate_sha": candidate_sha(book_dir, chapter),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    path = book_dir / "logs" / f"ch{chapter}" / "diagnosis.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result
