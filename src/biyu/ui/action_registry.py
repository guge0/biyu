"""R3-1 UI button registry: data only, all business actions remain CLI commands."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Action:
    argv: tuple[str, ...]
    confirm: bool
    estimate: str
    stdin_after_confirm: str = ""


def action_for(action_id: str, *, book: str, chapter: int) -> Action:
    common = ("-c", str(chapter), "-b", book)
    actions = {
        "approve_planning": Action(("planning", "approve", *common), True, "¥0"),
        "revoke_planning": Action(("planning", "approve", *common, "--revoke"), True, "¥0"),
        "write": Action(("write", *common, "--force-pending"), True, "按本书历史记录预估"),
        "regenerate": Action(("write", *common, "--force-pending"), True, "按本书历史记录预估"),
        "rewrite": Action(("workbench", "revise", *common), True, "按本书历史记录预估"),
        "review": Action(("review-standalone", *common), True, "按本书历史记录预估"),
        "verdict": Action(("verdict", "add", *common), False, "¥0"),
        "talk": Action(("talk", "章节导演", *common), False, "¥0"),
        "approve_chapter": Action(("approve", str(chapter), "-b", book), True, "¥0", "y\n"),
        "adopt": Action(("workbench", "adopt", *common), True, "¥0"),
        "refresh_memory": Action(("refresh", *common), True, "按本书历史记录预估"),
        "excerpt": Action(("workbench", "excerpt", *common), False, "¥0"),
        "chapter_review": Action(("workbench", "chapter-review", *common), False, "¥0"),
        "archive_excerpt": Action(("workbench", "excerpt-archive", *common), False, "¥0"),
        "retag_excerpt": Action(("workbench", "excerpt-retag", *common), False, "¥0"),
        "diagnose": Action(("workbench", "diagnose", *common), True, "按一次短诊断调用预估"),
    }
    if action_id not in actions:
        raise KeyError(action_id)
    return actions[action_id]
