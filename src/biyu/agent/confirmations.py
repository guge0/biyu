"""S-4A 确认闸 — 待确认动作存储。

落盘:data/<book>/consults/pending_actions.jsonl(追加式)。
字段(工单):id, session_id, book, chapter, action_id, estimate,
status(pending/confirmed/cancelled), created_at。

约束:action_id 只允许 4 个 run 动作(write/rewrite/review/diagnose),
且必须在 ui.action_registry 中存在(approve/adopt 等作者钦定动作进不来)。
"""
from __future__ import annotations

import json
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path

# 只有这 4 个 run 动作可登记(与 agent/tools.py 的 request_* 一一对应)
RUN_ACTION_IDS = ("write", "rewrite", "review", "diagnose")

_VALID_STATUSES = ("pending", "confirmed", "cancelled")


class PendingActionError(ValueError):
    """登记/流转不合法(书名穿越、非 run 动作、状态倒流等)。"""


def _safe_book(book: str) -> str:
    """书名必须是不含路径成分的单段目录名;路径穿越直接拒绝(不静默改写)。"""
    name = str(book or "").strip()
    if not name or name in {".", ".."} or "/" in name or "\\" in name:
        raise PendingActionError(f"书名不合法:{book!r}(不接受路径)")
    if Path(name).name != name:
        raise PendingActionError(f"书名不合法:{book!r}(不接受路径)")
    return name


class PendingActionStore:
    """待确认动作的 JSONL 存储;一个实例管一个数据根。"""

    def __init__(self, data_root: str | Path):
        self._data_root = Path(data_root)

    # ------------------------------------------------------------------
    # 路径
    # ------------------------------------------------------------------

    def _file(self, book: str) -> Path:
        name = _safe_book(book)
        book_dir = (self._data_root / name).resolve()
        if book_dir.parent != self._data_root.resolve():
            raise PendingActionError(f"书名不合法:{book!r}(解析后越出数据根)")
        return book_dir / "consults" / "pending_actions.jsonl"

    # ------------------------------------------------------------------
    # 写
    # ------------------------------------------------------------------

    def add(
        self,
        *,
        book: str,
        chapter: int,
        action_id: str,
        session_id: str | None = None,
    ) -> dict:
        """登记一条待确认动作,返回完整记录。

        校验:action_id ∈ RUN_ACTION_IDS 且在 action_registry 中存在。
        """
        if action_id not in RUN_ACTION_IDS:
            raise PendingActionError(
                f"动作 {action_id!r} 不属于可登记的 run 动作({'/'.join(RUN_ACTION_IDS)})"
            )
        from biyu.ui.action_registry import action_for

        try:
            action = action_for(action_id, book=book, chapter=int(chapter))
        except KeyError as exc:
            raise PendingActionError(f"动作 {action_id!r} 不在动作清单中") from exc
        record = {
            "id": self._new_id(),
            "session_id": session_id or "",
            "book": _safe_book(book),
            "chapter": int(chapter),
            "action_id": action_id,
            "estimate": action.estimate,
            "status": "pending",
            "created_at": time.time(),
        }
        path = self._file(book)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record

    def mark(self, action_record_id: str, status: str) -> dict:
        """按 id 流转状态(仅 pending → confirmed/cancelled),返回更新后的记录。"""
        if status not in _VALID_STATUSES[1:]:
            raise PendingActionError(f"目标状态不合法:{status!r}")
        record, path = self._locate(action_record_id)
        if record["status"] != "pending":
            raise PendingActionError(
                f"动作 {action_record_id} 当前状态是 {record['status']}，不能再改为 {status}"
            )
        record["status"] = status
        self._rewrite(path, action_record_id, record)
        return record

    # ------------------------------------------------------------------
    # 读
    # ------------------------------------------------------------------

    def get(self, action_record_id: str) -> dict | None:
        record, _ = self._locate(action_record_id, missing_ok=True)
        return record or None

    def list_actions(self, book: str | None = None, status: str | None = None) -> list[dict]:
        """列待确认动作;book=None 扫所有书目录,按登记顺序返回。"""
        records: list[dict] = []
        if book is not None:
            path = self._file(book)
            records.extend(self._read_file(path))
        else:
            for name in self._book_names():
                records.extend(self._read_file(self._file(name)))
        if status is not None:
            records = [r for r in records if r.get("status") == status]
        return records

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _book_names(self) -> list[str]:
        root = self._data_root.resolve()
        if not root.exists():
            return []
        return sorted(p.name for p in root.iterdir() if p.is_dir())

    @staticmethod
    def _read_file(path: Path) -> list[dict]:
        if not path.exists():
            return []
        records: list[dict] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # 追加式历史件,单行损坏跳过
        return records

    def _locate(self, action_record_id: str, missing_ok: bool = False) -> tuple[dict, Path]:
        for name in self._book_names():
            path = self._file(name)
            for record in self._read_file(path):
                if record.get("id") == action_record_id:
                    return record, path
        if missing_ok:
            return {}, Path()  # 占位;调用方只取 record
        raise LookupError(f"待确认动作不存在:{action_record_id}")

    def _rewrite(self, path: Path, action_record_id: str, updated: dict) -> None:
        lines: list[str] = []
        for record in self._read_file(path):
            if record.get("id") == action_record_id:
                record = updated
            lines.append(json.dumps(record, ensure_ascii=False))
        temp = path.with_suffix(".jsonl.tmp")
        temp.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        temp.replace(path)

    @staticmethod
    def _new_id() -> str:
        date = datetime.now(timezone.utc).strftime("%Y%m%d")
        rand = secrets.token_hex(4)
        return f"pa-{date}-{rand}"
