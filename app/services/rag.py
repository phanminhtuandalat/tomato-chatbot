"""
RAG Service — BM25 + bigrams, thread-safe singleton.

Nâng cấp từ TF-IDF sang BM25:
- BM25 chuẩn hoá theo độ dài đoạn văn (chunk dài không tự nhiên thắng)
- Bigrams giúp khớp cụm tiếng Việt: "héo rũ", "mốc sương", "đục quả"
- Title boost: nhân đôi token từ tiêu đề để ưu tiên section đúng chủ đề
- Fallback TF-IDF khi rank-bm25 chưa được cài
"""

import math
import re
import threading
import unicodedata
from pathlib import Path


DATA_DIR = Path(__file__).parent.parent.parent / "data"


# ---------------------------------------------------------------------------
# Chuẩn hoá và tokenize tiếng Việt
# ---------------------------------------------------------------------------

def normalize(text: str) -> str:
    """Bỏ dấu tiếng Việt, chuyển thường."""
    text = text.lower()
    text = unicodedata.normalize("NFD", text)
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def tokenize(text: str, with_bigrams: bool = True) -> list[str]:
    """
    Tách từ + bigrams.
    "héo rũ vi khuẩn" → ["heo", "ru", "vi", "khuan", "heo_ru", "ru_vi", "vi_khuan"]
    Bigrams giúp khớp cụm từ quan trọng trong tiếng Việt.
    """
    words = re.findall(r"[a-z0-9]+", normalize(text))
    words = [w for w in words if len(w) >= 2]
    if not with_bigrams or len(words) < 2:
        return words
    bigrams = [f"{words[i]}_{words[i+1]}" for i in range(len(words) - 1)]
    return words + bigrams


def tokenize_chunk(title: str, content: str) -> list[str]:
    """Title được nhân đôi để boost mức độ ưu tiên."""
    return tokenize(title) * 2 + tokenize(content)


# ---------------------------------------------------------------------------
# RAG Service
# ---------------------------------------------------------------------------

class RAGService:
    def __init__(self, data_dir: Path | None = None):
        self._data_dir = data_dir or DATA_DIR
        self._lock = threading.RLock()
        self._chunks: list[dict] = []
        self._bm25 = None
        self._load()

    def _load(self) -> None:
        chunks = []
        for md_file in sorted(self._data_dir.glob("*.md")):
            text = md_file.read_text(encoding="utf-8")
            sections = re.split(r"\n(?=#{1,3} )", text)
            for section in sections:
                section = section.strip()
                if len(section) < 40:
                    continue
                title_match = re.match(r"#{1,3} (.+)", section)
                title = title_match.group(1).strip() if title_match else ""
                chunks.append({
                    "title": title,
                    "content": section,
                    "source": md_file.stem,
                    "tokens": tokenize_chunk(title, section),
                })

        bm25 = _build_bm25([c["tokens"] for c in chunks])

        self._chunks = chunks
        self._bm25 = bm25

    def reload(self) -> None:
        """Reload knowledge base — thread-safe."""
        with self._lock:
            self._load()

    def search(self, query: str, top_k: int = 4) -> str:
        if not query.strip():
            return ""

        query_tokens = tokenize(query)
        if not query_tokens:
            return ""

        with self._lock:
            chunks = self._chunks
            bm25 = self._bm25

        if not chunks:
            return ""

        scores = _score(bm25, chunks, query_tokens)
        # Lấy top_k chunks có điểm > 0
        ranked = sorted(
            [(s, c) for s, c in zip(scores, chunks) if s > 0],
            key=lambda x: x[0],
            reverse=True,
        )[:top_k]

        if not ranked:
            return ""

        return "\n\n---\n\n".join(
            f"[{c['source']}] {c['title']}\n{c['content']}"
            for _, c in ranked
        )

    @property
    def chunk_count(self) -> int:
        with self._lock:
            return len(self._chunks)


# ---------------------------------------------------------------------------
# BM25 helpers — dùng rank-bm25 nếu có, fallback TF-IDF nếu không
# ---------------------------------------------------------------------------

def _build_bm25(corpus: list[list[str]]):
    try:
        from rank_bm25 import BM25Plus  # IDF luôn dương, tốt hơn BM25Okapi với corpus nhỏ
        return BM25Plus(corpus)
    except ImportError:
        return None  # fallback


def _score(bm25, chunks: list[dict], query_tokens: list[str]) -> list[float]:
    if bm25 is not None:
        return bm25.get_scores(query_tokens).tolist()
    # Fallback: TF-IDF smooth
    N = max(len(chunks), 1)
    df: dict[str, int] = {}
    for chunk in chunks:
        for w in set(chunk["tokens"]):
            df[w] = df.get(w, 0) + 1
    idf = {w: math.log((N + 1) / (c + 1)) + 1 for w, c in df.items()}
    query_set = set(query_tokens)
    return [
        sum(idf.get(w, 0) for w in query_set & set(c["tokens"]))
        for c in chunks
    ]


# Singleton
rag = RAGService()
