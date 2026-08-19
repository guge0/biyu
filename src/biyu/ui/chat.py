"""会话基座(P8-M3 T1):会话持久化 JSONL + CRUD + 成本累计。

API:
- ChatManager(data_root)
- .new_session(book, role, book_id=None, source="production") -> str
- .get_session(session_id) -> dict | None
- .list_sessions(book=None, book_id=None, include_test=False) -> list[dict]
- .add_message(session_id, role, content, tool_call=None, cost=None) -> dict
- .soft_delete(session_id)
- .get_session_cost(session_id) -> float

JSONL schema per message: {role, content, tool_call?, cost?, ts}
会话 id = 日期 + 短随机 (预答决策第3条)。

P8-M3R R6 T6.1:source 字段(默认 "production")用于区分真实使用与自动化测试会话,
list_sessions 默认隐 source="test"(include_test=True 才显)。
"""
from __future__ import annotations

import json
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path


class ChatManager:
    """会话管理器:JSONL 持久化 + 会话 CRUD。

    data_root 下按书目录组织:
        data/<book>/consults/<session_id>.json      ← 会话元数据
        data/<book>/consults/<session_id>.jsonl     ← 消息日志
    """

    def __init__(self, data_root: str | Path):
        self._data_root = Path(data_root)

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_book(book: str) -> str:
        """安全化书名:去路径成分,防穿越。"""
        return Path(book).name

    def _consults_dir(self, book: str) -> Path:
        return self._data_root / self._safe_book(book) / "consults"

    @staticmethod
    def _generate_id() -> str:
        date = datetime.now(timezone.utc).strftime("%Y%m%d")
        rand = secrets.token_hex(4)  # 8 hex chars
        return f"{date}-{rand}"

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    def new_session(
        self,
        book: str,
        role: str,
        book_id: str | None = None,
        source: str = "production",
    ) -> str:
        sid = self._generate_id()
        # 保证同进程内 created_at 严格递增,治 flaky:
        # Windows 默认 time.time() 精度受系统时钟限制,紧挨着的 new_session 调用
        # 可能落同精度窗口 → created_at 同值 → list_sessions 排序歧义
        # (id 是 secrets.token_hex 随机的,与创建顺序无关,作 tiebreaker 无效)。
        # 即便时间没推进也强制 +1μs,排序稳定。
        now = time.time()
        last = getattr(self, "_last_created_at", 0.0)
        if now <= last:
            now = last + 1e-6
        self._last_created_at = now
        meta: dict = {
            "id": sid,
            "book": book,
            "role": role,
            "created_at": now,
            "deleted": False,
            "source": source,
        }
        if book_id is not None:
            meta["book_id"] = book_id
        d = self._consults_dir(book)
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{sid}.json").write_text(
            json.dumps(meta, ensure_ascii=False), encoding="utf-8",
        )
        (d / f"{sid}.jsonl").write_text("", encoding="utf-8")
        return sid

    def get_session(self, session_id: str) -> dict | None:
        """按 session_id 搜所有书目录,返元数据 + 消息列表。"""
        for d in self._data_root.iterdir():
            if not d.is_dir():
                continue
            consults_dir = d / "consults"
            meta_file = consults_dir / f"{session_id}.json"
            if meta_file.exists():
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                meta["messages"] = self._read_messages(session_id, consults_dir)
                return meta
        return None

    def list_sessions(
        self,
        book: str | None = None,
        book_id: str | None = None,
        include_test: bool = False,
    ) -> list[dict]:
        """列出未删除的会话,按创建时间降序。

        过滤维度(并行,可叠加):
        - book:按书目录名过滤(旧契约,兼容回退)
        - book_id:按会话 meta.book_id 过滤(新契约,R1 slug ID);需扫所有目录
        - include_test:False(默认)隐 source="test" 会话;True 显(P8-M3R R6 T6.1)

        旧会话 meta 无 source 字段时,默认视为 "production"(不隐)。
        """
        sessions: list[dict] = []

        def _visible(meta: dict) -> bool:
            """是否应纳入列表(未删除 + source 过滤)。"""
            if meta.get("deleted", False):
                return False
            if not include_test and meta.get("source", "production") == "test":
                return False
            return True

        if book_id:
            # book_id 过滤:扫所有书目录,按 meta.book_id 筛
            for book_dir in self._data_root.iterdir():
                if not book_dir.is_dir():
                    continue
                consults_dir = book_dir / "consults"
                if not consults_dir.exists():
                    continue
                for f in consults_dir.glob("*.json"):
                    meta = json.loads(f.read_text(encoding="utf-8"))
                    if meta.get("book_id") == book_id and _visible(meta):
                        sessions.append(meta)
            sessions.sort(key=lambda s: s.get("created_at", 0), reverse=True)
            return sessions
        if book:
            d = self._consults_dir(book)
            if d.exists():
                for f in d.glob("*.json"):
                    meta = json.loads(f.read_text(encoding="utf-8"))
                    if _visible(meta):
                        sessions.append(meta)
            # 用 meta.created_at(time.time 微秒精度,与 docstring "按创建时间降序" 一致);
            # 与 book_id 分支(上方)和无 book 分支(下方)对齐。
            # 加 id 作 tiebreaker(同 created_at 时,会话 id 含日期+随机 hex 区分)。
            # 治 flaky:旧实现用 f.stat().st_mtime(秒级精度)→ 同秒创建会话排序歧义。
            sessions.sort(
                key=lambda s: (s.get("created_at", 0), s.get("id", "")),
                reverse=True,
            )
        else:
            for book_dir in self._data_root.iterdir():
                if not book_dir.is_dir():
                    continue
                consults_dir = book_dir / "consults"
                if consults_dir.exists():
                    for f in consults_dir.glob("*.json"):
                        meta = json.loads(f.read_text(encoding="utf-8"))
                        if _visible(meta):
                            sessions.append(meta)
            sessions.sort(key=lambda s: s.get("created_at", 0), reverse=True)
        return sessions

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        tool_call: dict | None = None,
        cost: float | None = None,
    ) -> dict:
        dirs = self._session_dirs(session_id)
        if dirs is None:
            raise ValueError(f"Session {session_id} not found")
        consults_dir, _ = dirs

        msg: dict = {"role": role, "content": content, "ts": time.time()}
        if tool_call is not None:
            msg["tool_call"] = tool_call
        if cost is not None:
            msg["cost"] = cost

        jsonl_path = consults_dir / f"{session_id}.jsonl"
        with jsonl_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(msg, ensure_ascii=False) + "\n")
        return msg

    def soft_delete(self, session_id: str) -> None:
        dirs = self._session_dirs(session_id)
        if dirs is None:
            raise ValueError(f"Session {session_id} not found")
        consults_dir, meta_path = dirs
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["deleted"] = True
        meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")

    def get_session_cost(self, session_id: str) -> float:
        session = self.get_session(session_id)
        if session is None:
            return 0.0
        total = 0.0
        for msg in session.get("messages", []):
            cost = msg.get("cost")
            if cost is not None:
                total += float(cost)
        return total

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _session_dirs(self, session_id: str) -> tuple[Path, Path] | None:
        """搜所有书目录,返 (consults_dir, meta_file_path)。"""
        for d in self._data_root.iterdir():
            if not d.is_dir():
                continue
            consults_dir = d / "consults"
            meta_file = consults_dir / f"{session_id}.json"
            if meta_file.exists():
                return consults_dir, meta_file
        return None

    @staticmethod
    def _read_messages(session_id: str, consults_dir: Path) -> list[dict]:
        jsonl_path = consults_dir / f"{session_id}.jsonl"
        if not jsonl_path.exists():
            return []
        text = jsonl_path.read_text(encoding="utf-8")
        msgs: list[dict] = []
        for line in text.strip().split("\n"):
            line = line.strip()
            if line:
                msgs.append(json.loads(line))
        return msgs
