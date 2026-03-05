"""
RAG Service — thread-safe singleton.
Dùng RLock để đảm bảo reload() và search() không xung đột
khi server chạy nhiều worker.
"""

import math
import re
import threading
import unicodedata
from pathlib import Path


DATA_DIR = Path(__file__).parent.parent.parent / "data"


# ---------------------------------------------------------------------------
# Chuẩn hoá tiếng Việt
# ---------------------------------------------------------------------------

def normalize(text: str) -> str:
    """Bỏ dấu tiếng Việt, chuyển thường."""
    text = text.lower()
    text = unicodedata.normalize("NFD", text)
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def tokenize(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", normalize(text))
    return [w for w in words if len(w) >= 2]


# ---------------------------------------------------------------------------
# RAG Service
# ---------------------------------------------------------------------------

class RAGService:
    def __init__(self, data_dir: Path | None = None):
        self._data_dir = data_dir or DATA_DIR
        self._lock = threading.RLock()
        self._chunks: list[dict] = []
        self._idf: dict[str, float] = {}
        self._load()

    def _load(self) -> None:
        chunks = []
        for md_file in sorted(self._data_dir.glob("*.md")):
            text = md_file.read_text(encoding="utf-8")
            sections = re.split(r"\n(?=#{2,3} )", text)
            for section in sections:
                section = section.strip()
                if len(section) < 40:
                    continue
                title_match = re.match(r"#{2,3} (.+)", section)
                title = title_match.group(1).strip() if title_match else ""
                chunks.append({
                    "title": title,
                    "content": section,
                    "source": md_file.stem,
                    "tokens": tokenize(title + " " + section),
                })

        # Tính IDF
        N = max(len(chunks), 1)
        df: dict[str, int] = {}
        for chunk in chunks:
            for word in set(chunk["tokens"]):
                df[word] = df.get(word, 0) + 1
        # Smooth IDF: +1 đảm bảo luôn > 0, kể cả khi chỉ có 1 chunk
        idf = {w: math.log((N + 1) / (count + 1)) + 1 for w, count in df.items()}

        self._chunks = chunks
        self._idf = idf

    def reload(self) -> None:
        """Reload knowledge base — thread-safe."""
        with self._lock:
            self._load()

    def search(self, query: str, top_k: int = 3) -> str:
        if not query.strip():
            return ""

        query_tokens = set(tokenize(query))
        if not query_tokens:
            return ""

        with self._lock:
            scored = []
            for chunk in self._chunks:
                score = sum(
                    self._idf.get(w, 0)
                    for w in query_tokens & set(chunk["tokens"])
                )
                if score > 0:
                    scored.append((score, chunk))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = [c for _, c in scored[:top_k]]

        if not top:
            return ""

        return "\n\n---\n\n".join(
            f"[{c['source']}] {c['title']}\n{c['content']}"
            for c in top
        )

    @property
    def chunk_count(self) -> int:
        with self._lock:
            return len(self._chunks)


# Singleton — khởi tạo 1 lần khi import
rag = RAGService()
