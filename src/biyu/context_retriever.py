"""跨章上下文检索 — 长Context路径(默认) + RAG路径(Phase 3-4可选)。

默认 long_context: 直接拼接全部历史章节,不依赖任何额外库。
RAG: 向量检索,需要 chromadb,只在 context_mode=rag 时才 import。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class ContextRetriever(ABC):
    """跨章上下文检索的统一接口。"""

    @abstractmethod
    def retrieve(self, chapter_num: int) -> list[str]:
        """返回历史章节文本列表,供注入 Writer prompt。"""
        ...

    @abstractmethod
    def index_chapter(self, chapter_num: int, text: str) -> None:
        """每章生成后,索引到检索库(长context路径不需要)。"""
        ...


class LongContextRetriever(ContextRetriever):
    """长 context 路径:直接返回全部历史章节(默认)。"""

    def __init__(self, book_dir: Path):
        self.book_dir = book_dir
        self.chapters_dir = book_dir / "chapters"

    def retrieve(self, chapter_num: int) -> list[str]:
        chapters: list[str] = []
        if not self.chapters_dir.exists():
            return chapters
        outlines_dir = self.book_dir / "outlines"
        # Writer needs the immediately preceding prose for continuity, while
        # older chapters contribute only their compact author outlines.
        for i in range(1, max(chapter_num - 1, 1)):
            outline_path = outlines_dir / f"ch{i}.md"
            if outline_path.exists():
                chapters.append(outline_path.read_text(encoding="utf-8"))
            else:
                chapters.append("（无细纲）")
        previous = self.chapters_dir / f"ch{chapter_num - 1}.md"
        if chapter_num > 1 and previous.exists():
            chapters.append(previous.read_text(encoding="utf-8"))
        return chapters

    def index_chapter(self, chapter_num: int, text: str) -> None:
        pass  # 长 context 不需要索引


class RAGRetriever(ContextRetriever):
    """RAG 路径:向量检索(Phase 3-4 启用)。需要 chromadb。"""

    def __init__(self, book_dir: Path):
        import chromadb  # 只在 RAG 模式才 import

        self.client = chromadb.PersistentClient(
            path=str(book_dir / "vectordb")
        )
        self.collection = self.client.get_or_create_collection("chapters")

    def retrieve(self, chapter_num: int) -> list[str]:
        # RAG 模式下需要 query,这里用章节号做占位
        # 实际使用时 pipeline 应该传 outline 作为 query
        results = self.collection.query(
            query_texts=[f"第{chapter_num}章"],
            n_results=10,
        )
        return results["documents"][0] if results["documents"] else []

    def retrieve_with_query(self, query: str, top_k: int = 10) -> list[str]:
        """用大纲文本作为 query 做语义检索。"""
        results = self.collection.query(query_texts=[query], n_results=top_k)
        return results["documents"][0] if results["documents"] else []

    def index_chapter(self, chapter_num: int, text: str) -> None:
        chunks = self._split_chunks(text, max_chars=400)
        for i, chunk in enumerate(chunks):
            self.collection.upsert(
                documents=[chunk],
                ids=[f"ch{chapter_num}_chunk{i}"],
                metadatas=[{"chapter": chapter_num}],
            )

    @staticmethod
    def _split_chunks(text: str, max_chars: int = 400) -> list[str]:
        """按段落切块,超长段落再切。"""
        paragraphs = text.split("\n\n")
        chunks: list[str] = []
        current = ""
        for p in paragraphs:
            if len(current) + len(p) > max_chars and current:
                chunks.append(current.strip())
                current = p
            else:
                current += "\n\n" + p if current else p
        if current.strip():
            chunks.append(current.strip())
        return chunks


def get_retriever(book_dir: Path, context_mode: str = "long_context") -> ContextRetriever:
    """工厂方法:根据 context_mode 选择 retriever。

    Args:
        book_dir: 书目录
        context_mode: "long_context"(默认) 或 "rag"

    Returns:
        ContextRetriever 实例。
    """
    if context_mode == "rag":
        try:
            return RAGRetriever(book_dir)
        except ImportError:
            import warnings
            warnings.warn(
                "chromadb 未安装,降级到 long_context 模式",
                stacklevel=2,
            )
            return LongContextRetriever(book_dir)
    return LongContextRetriever(book_dir)
