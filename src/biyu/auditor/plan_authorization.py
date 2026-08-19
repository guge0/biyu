"""High-confidence guard for major events not authorized by approved planning."""
from __future__ import annotations

import re
from pathlib import Path

from biyu.auditor.base import AuditResult, BaseAuditor, Severity

RULE_ID = "PLAN_UNAUTHORIZED_MAJOR_EVENT"

_SENTENCE_RE = re.compile(r"[^。！？!?\n]+[。！？!?]?")
_ROLE_TOKEN_RE = re.compile(r"角色(?:[甲乙丙丁戊己庚辛壬癸]|[A-Za-z0-9]+)")
_DEATH_VERBS = ("杀死", "杀害", "斩杀", "刺死", "处死", "打死", "勒死", "毒死", "射杀")
_NON_ASSERTIVE_MARKERS = (
    "没有",
    "并未",
    "未曾",
    "不会",
    "不能",
    "如果",
    "假如",
    "倘若",
    "若是",
    "是否",
    "谈论",
    "讨论",
    "提到",
    "担心",
    "害怕",
)


def _known_roles(text: str, ctx: dict) -> list[str]:
    names: list[str] = []
    for item in ctx.get("characters", []):
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            name = item["name"].strip()
            if name:
                names.append(name)
    names.extend(_ROLE_TOKEN_RE.findall(text))
    return list(dict.fromkeys(names))


def _event_claims(text: str, roles: list[str]) -> list[dict[str, str]]:
    claims: list[dict[str, str]] = []
    ordered_roles = sorted(set(roles), key=len, reverse=True)
    for raw_sentence in _SENTENCE_RE.findall(text):
        sentence = raw_sentence.strip()
        if not sentence or any(marker in sentence for marker in _NON_ASSERTIVE_MARKERS):
            continue
        verb = next((candidate for candidate in _DEATH_VERBS if candidate in sentence), "")
        if not verb:
            continue
        verb_at = sentence.index(verb)
        actors = [name for name in ordered_roles if sentence.find(name) != -1 and sentence.find(name) < verb_at]
        targets = [name for name in ordered_roles if sentence.find(name, verb_at + len(verb)) != -1]
        if not actors or not targets:
            continue
        claims.append(
            {
                "kind": "角色死亡",
                "actor": actors[-1],
                "target": targets[0],
                "sentence": sentence,
            }
        )
    return claims


def _planning_text(ctx: dict) -> str:
    supplied = ctx.get("planning")
    if isinstance(supplied, str) and supplied.strip():
        return supplied
    book_dir = ctx.get("book_dir")
    chapter_num = ctx.get("chapter_num")
    if book_dir is None or chapter_num is None:
        return ""
    path = Path(book_dir) / "logs" / f"ch{chapter_num}" / "planning.md"
    try:
        return path.read_text(encoding="utf-8") if path.exists() else ""
    except OSError:
        return ""


def _is_approved(planning: str) -> bool:
    return bool(planning.splitlines()) and planning.splitlines()[0].strip() == "status: 已批"


def _authorized(claim: dict[str, str], planning_claims: list[dict[str, str]]) -> bool:
    return any(
        candidate["kind"] == claim["kind"]
        and candidate["actor"] == claim["actor"]
        and candidate["target"] == claim["target"]
        for candidate in planning_claims
    )


class PlanAuthorizationAuditor(BaseAuditor):
    """Block only explicit, evidenced death events absent from approved planning."""

    @property
    def name(self) -> str:
        return RULE_ID

    def run(self, chapter_text: str, ctx: dict) -> AuditResult:
        planning = _planning_text(ctx)
        if not planning or not _is_approved(planning):
            return AuditResult(
                checker=self.name,
                severity=Severity.SKIP,
                message="无已批规划件，方案外重大事件检查跳过",
                details={"planning_check": "没有可核对的已批规划件"},
            )

        roles = _known_roles(chapter_text + "\n" + planning, ctx)
        chapter_claims = _event_claims(chapter_text, roles)
        if not chapter_claims:
            return AuditResult(
                checker=self.name,
                severity=Severity.PASS,
                message="未发现可举证的方案外重大事件",
                details={"planning_check": "正文没有高置信重大事件主张"},
            )

        planning_claims = _event_claims(planning, roles)
        unauthorized = [claim for claim in chapter_claims if not _authorized(claim, planning_claims)]
        if not unauthorized:
            return AuditResult(
                checker=self.name,
                severity=Severity.PASS,
                message="正文重大事件均有已批规划依据",
                details={"planning_check": "已批规划件找到同角色、同对象、同事件授权"},
            )

        claim = unauthorized[0]
        planning_check = (
            f"已批规划件未找到授权：{claim['actor']}对{claim['target']}实施{claim['kind']}"
        )
        return AuditResult(
            checker=self.name,
            severity=Severity.BLOCK,
            message=f"方案外重大事件：{claim['sentence']}",
            details={
                "chapter_evidence": claim["sentence"],
                "planning_check": planning_check,
                "event_kind": claim["kind"],
                "actor": claim["actor"],
                "target": claim["target"],
            },
        )
