"""Anchor check auditor — value-match 三态, 正文层管线 QC(P6-A2 转正)。

把 biyu.anchor_check 的 value-match 引擎接入 run_audit:
- 确定性、二值、零 LLM
- VALUE_MISMATCH → BLOCK(事实矛盾, 需人审)
- 仅 MISSING → WARN(漏提, 非矛盾)
- 全部在场 → PASS
- 无 anchors.yaml → SKIP

anchors 定位(优先级):
1. ctx["anchor_check"]["anchors_path"] —— eval 集中放 anchors 时用
2. book_dir/anchors.yaml —— 常规书目录

chapter_id 映射:
1. ctx["anchor_check"]["chapter_key_map"][chapter_num] —— 显式映射
2. f"{prefix}{chapter_num}", prefix 默认 "T"
"""
from __future__ import annotations

from pathlib import Path

from biyu.anchor_check import run_check_text
from biyu.auditor.base import AuditResult, BaseAuditor, Severity


class AnchorCheckAuditor(BaseAuditor):
    """value-match 硬信息锚点检查(正文层)。"""

    @property
    def name(self) -> str:
        return "anchor_check"

    def run(self, chapter_text: str, ctx: dict) -> AuditResult:
        cfg = ctx.get("anchor_check", {}) or {}

        # 1. 定位 anchors.yaml
        anchors_path_str = cfg.get("anchors_path")
        if anchors_path_str:
            anchors_path = Path(anchors_path_str)
        else:
            book_dir = Path(ctx.get("book_dir", "."))
            anchors_path = book_dir / "anchors.yaml"

        if not anchors_path.exists():
            return AuditResult(
                checker=self.name,
                severity=Severity.SKIP,
                message="anchor_check: 无 anchors.yaml, 跳过",
            )

        # 2. 解析 chapter_id
        chapter_num = ctx.get("chapter_num", 0)
        chapter_key_map = cfg.get("chapter_key_map") or {}
        if chapter_num in chapter_key_map:
            chapter_id = chapter_key_map[chapter_num]
        else:
            prefix = cfg.get("chapter_key_prefix", "T")
            chapter_id = f"{prefix}{chapter_num}"

        # 3. 跑 value-match(零 LLM)
        report = run_check_text(str(anchors_path), chapter_text, chapter_id)
        stats = report["stats"]["atomic"]
        atomic = report["atomic_results"]

        present = stats["hit"]
        value_mismatch = stats["value_mismatch"]
        missing = stats["miss"]
        total = stats["total"]

        mismatches = [
            {"id": a["id"], "canonical": a["canonical"], "mismatch_by": a.get("mismatch_by")}
            for a in atomic if a.get("status") == "value_mismatch"
        ]
        missing_list = [
            {"id": a["id"], "canonical": a["canonical"]}
            for a in atomic if a.get("status") == "missing"
        ]

        details = {
            "chapter_id": chapter_id,
            "total": total,
            "present": present,
            "missing": missing,
            "value_mismatch": value_mismatch,
            "mismatches": mismatches,
            "missing_list": missing_list,
        }

        if value_mismatch > 0:
            ids = ", ".join(m["id"] for m in mismatches)
            return AuditResult(
                checker=self.name,
                severity=Severity.BLOCK,
                message=f"anchor_check: {value_mismatch} 处值错(VALUE_MISMATCH) [{ids}]",
                details=details,
            )
        if missing > 0:
            return AuditResult(
                checker=self.name,
                severity=Severity.WARN,
                message=f"anchor_check: {missing}/{total} 锚点缺失(MISSING), 无值错",
                details=details,
            )
        return AuditResult(
            checker=self.name,
            severity=Severity.PASS,
            message=f"anchor_check: {total} 锚点全部在场(无值错)",
            details=details,
        )
