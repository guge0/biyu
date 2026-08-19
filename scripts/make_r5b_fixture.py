"""Build the deterministic, zero-LLM R5-1B browser-evidence fixture."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any


BOOK_ID = "R5B-fixture"
FIXED_TIME = "2026-07-24T00:00:00+00:00"
PARAGRAPHS = [
    "合成甲推开北坊测试门，先把一枚空白木牌放在桌角。",
    "合成乙没有接话，只把第二枚木牌翻到背面，露出一个圆点。",
    "门外传来三声短铃。合成甲停在窗边，确认声音来自空院。",
    "两人按占位方案交换位置，动作本身不代表任何真实故事设定。",
    "合成乙指出上一段解释重复，要求当前写手压短这一处。",
    "合成甲收起两枚木牌，北坊测试门重新合上，夹具段落到此结束。",
]
CURRENT_TEXT = "\n\n".join(PARAGRAPHS) + "\n"
OLDER_TEXT = CURRENT_TEXT.replace("解释重复", "句子稍长")


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(path: Path, value: Any) -> None:
    _write(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_fixture(data_root: Path, *, force: bool = False) -> Path:
    book = data_root / BOOK_ID
    if book.exists():
        if not force:
            validate_fixture(book)
            return book
        shutil.rmtree(book)

    _write_json(book / "book.json", {
        "id": BOOK_ID,
        "title": "R5-1B 隔离取证夹具",
        "genre": "fixture",
        "status": "testing",
    })
    _write(book / "outlines/ch1.md", "# ch1 合成细纲\n\n合成甲与合成乙完成一次无实义的占位交接。\n")
    planning = (
        "status: 已批\n"
        "# ch1 合成写作方案\n\n"
        "只写北坊测试门内的占位交接；不得增加角色死亡、背叛或设定揭示。\n"
    )
    _write(book / "logs/ch1/planning.md", planning)
    _write(book / "logs/ch1/plans/plan_v1.md", planning.removeprefix("status: 已批\n"))
    _write_json(book / "logs/ch1/plans/plan_v1.json", {"version": 1, "created_at": FIXED_TIME})
    _write(book / "logs/ch1/plans/current", "v1\n")
    _write(book / "chapters/_pending/ch1.md", CURRENT_TEXT)
    candidates = ((1, OLDER_TEXT, "archived"), (2, CURRENT_TEXT, "current"))
    for version, text, state in candidates:
        _write(book / f"logs/ch1/candidates/candidate_v{version}.md", text)
        _write_json(book / f"logs/ch1/candidates/candidate_v{version}.json", {
            "version": version,
            "run_id": f"fixture-v{version}",
            "action": "fixture",
            "from_plan": 1,
            "created_at": FIXED_TIME,
            "word_count": sum("\u4e00" <= char <= "\u9fff" for char in text),
            "official_base_words": None,
            "state": state,
        })
    for number in range(1, 4):
        root = book / f"logs/ch1/revisions/round_{number}"
        _write_json(root / "manifest.json", {
            "chapter": 1,
            "round": number,
            "created_at": FIXED_TIME,
            "candidate_sha": _sha(CURRENT_TEXT),
            "selected_issue_ids": [f"editor-{number}"],
            "status": "complete",
        })
        _write(root / "comments.md", f"# 本轮作者意见\n\n第 {number} 轮合成意见。\n\n## 逐条意见\n")
        _write_json(root / "issues.json", [{"id": f"editor-{number}", "paragraph": number + 1}])
        _write(root / "candidate.md", CURRENT_TEXT)
        _write(root / "planning.md", planning)
    _write_json(book / "logs/ch1/workbench_state.json", {
        "step": "reading",
        "updated_at": FIXED_TIME,
    })
    report = {
        "chapter": 1,
        "issues": [
            {
                "id": "fixture-block",
                "severity": "high",
                "type": "规划履约",
                "paragraph": 2,
                "quoted_text": PARAGRAPHS[1],
                "explanation": "合成 BLOCK 卡，用于界面定位。",
                "fix_suggestion": "保留占位事实，只调整表达。",
            },
            {
                "id": "fixture-warn",
                "severity": "medium",
                "type": "文风与AI味",
                "paragraph": 5,
                "quoted_text": PARAGRAPHS[4],
                "explanation": "合成 WARN 卡，用于验证当前意见不被卷走。",
                "fix_suggestion": "删去重复解释。",
            },
        ],
        "results": [
            {"checker": "fixture_pass", "severity": "PASS", "message": "合成 PASS 检查。"},
        ],
    }
    _write_json(book / "audit_reports/ch1.json", report)
    _write(book / "audit_reports/ch1.md", "## 合成审读报告\n\n仅供 R5-1B 隔离取证。\n")
    valid = {
        "layer": "执笔层",
        "action": "继续修订",
        "reason": "## 诊断结论\n\n结论为【执笔层】。论证核对过「方案层」与「细纲层」，但它们不是本次结论。",
        "rounds": 3,
        "candidate_sha": _sha(CURRENT_TEXT),
        "created_at": FIXED_TIME,
    }
    conflict = {
        "layer": "方案层",
        "action": "继续修订",
        "reason": "证据实际指向执笔层。",
    }
    _write_json(book / "logs/ch1/diagnosis.json", valid)
    _write_json(book / "logs/ch1/diagnosis_replays/conclusion_wins.json", valid)
    _write_json(book / "logs/ch1/diagnosis_replays/inconsistent_triple.json", conflict)
    validate_fixture(book)
    return book


def validate_fixture(book: Path) -> dict[str, Any]:
    from biyu.ui.diagnosis import diagnosis_is_fresh, revision_round_count
    from biyu.ui.workbench_state import asset_state, read_workbench_step
    from biyu.ui.workbench_versions import list_candidate_versions

    report = json.loads((book / "audit_reports/ch1.json").read_text(encoding="utf-8"))
    severities = {
        *(str(item.get("severity", "")).upper() for item in report.get("issues", [])),
        *(str(item.get("severity", "")).upper() for item in report.get("results", [])),
    }
    checks = {
        "chapter_ch1": (book / "chapters/_pending/ch1.md").exists(),
        "step_reading": read_workbench_step(book, 1) == "reading",
        "asset_candidate": asset_state(book, 1) == "candidate",
        "candidate_versions_ge_2": len(list_candidate_versions(book, 1)) >= 2,
        "complete_rounds_eq_3": revision_round_count(book, 1) == 3,
        "approved_planning": (book / "logs/ch1/planning.md").read_text(encoding="utf-8").startswith("status: 已批\n"),
        "cards_block_warn_pass": {"HIGH", "MEDIUM", "PASS"} <= severities and len(report.get("issues", [])) >= 2,
        "diagnosis_replay_fresh": diagnosis_is_fresh(book, 1)
        and (book / "logs/ch1/diagnosis_replays/conclusion_wins.json").exists()
        and (book / "logs/ch1/diagnosis_replays/inconsistent_triple.json").exists(),
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise RuntimeError("R5B fixture self-check failed: " + ", ".join(failed))
    return checks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--data-root", type=Path, default=Path(__file__).resolve().parents[1] / "data")
    args = parser.parse_args()
    book = build_fixture(args.data_root.resolve(), force=args.force)
    checks = validate_fixture(book)
    print(f"R5B fixture ready: {book}")
    for name in checks:
        print(f"PASS {name}")
    print("PASS zero_llm=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
