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
    """Title được nhân 3 để boost mức độ ưu tiên — chunk đúng chủ đề thắng."""
    return tokenize(title) * 3 + tokenize(content)


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

    # Ngưỡng để sub-chunk: section lớn hơn ngưỡng này sẽ bị chia nhỏ hơn
    CHUNK_SIZE_LIMIT = 500

    def _load(self) -> None:
        chunks = []
        for md_file in sorted(self._data_dir.glob("*.md")):
            text = md_file.read_text(encoding="utf-8")
            # Lấy tiêu đề tài liệu từ dòng # đầu tiên (level 1)
            doc_title_match = re.match(r"# (.+)", text.lstrip())
            doc_title = doc_title_match.group(1).strip() if doc_title_match else md_file.stem.replace("_", " ").title()

            sections = re.split(r"\n(?=#{1,3} )", text)
            for section in sections:
                section = section.strip()
                if len(section) < 40:
                    continue
                title_match = re.match(r"#{1,3} (.+)", section)
                section_title = title_match.group(1).strip() if title_match else ""

                sub_chunks = self._sub_chunk(section, section_title)
                for sub in sub_chunks:
                    chunks.append({
                        "title": section_title,
                        "doc_title": doc_title,
                        "content": sub,
                        "source": md_file.stem,
                        "tokens": tokenize_chunk(section_title, sub),
                    })

        bm25 = _build_bm25([c["tokens"] for c in chunks])
        self._chunks = chunks
        self._bm25 = bm25

    def _sub_chunk(self, section: str, title: str) -> list[str]:
        """Chia section lớn thành sub-chunks tại điểm ngắt đoạn văn.
        Section ngắn (≤ CHUNK_SIZE_LIMIT) giữ nguyên.
        FAQ có **Hỏi:** → mỗi cặp Q&A là 1 sub-chunk.
        Section dài khác: chia tại \\n\\n, gộp đến gần giới hạn.
        """
        if len(section) <= self.CHUNK_SIZE_LIMIT:
            return [section]

        # Nếu là FAQ (chứa **Hỏi:**), tách từng cặp Q&A riêng
        if re.search(r"\*\*Hỏi:", section):
            qa_blocks = re.split(r"\n(?=\*\*Hỏi:)", section)
            result = []
            for block in qa_blocks:
                block = block.strip()
                if not block or re.match(r"#{1,3} ", block):
                    continue
                # Gắn title vào đầu mỗi Q&A để BM25 vẫn biết context
                result.append(f"## {title}\n\n{block}")
            return result if result else [section]

        # Section thường: chia tại \n\n, gộp đến gần giới hạn
        paragraphs = re.split(r"\n\n+", section)
        result: list[str] = []
        current_parts: list[str] = [f"## {title}"]
        current_len = len(title) + 3

        for para in paragraphs:
            para = para.strip()
            if not para or para == f"## {title}" or re.match(r"#{1,3} ", para):
                continue
            if current_len + len(para) > self.CHUNK_SIZE_LIMIT and len(current_parts) > 1:
                result.append("\n\n".join(current_parts))
                current_parts = [f"## {title}", para]
                current_len = len(title) + 3 + len(para)
            else:
                current_parts.append(para)
                current_len += len(para)

        if len(current_parts) > 1:
            result.append("\n\n".join(current_parts))

        return result if result else [section]

    def reload(self) -> None:
        """Reload knowledge base — thread-safe."""
        with self._lock:
            self._load()

    def _rank(self, query: str, top_k: int = 4, max_per_source: int = 2) -> list[tuple[float, dict]]:
        """Trả về top_k chunks đã rank theo BM25/TF-IDF.
        max_per_source: tối đa bao nhiêu chunks từ cùng một nguồn — tránh 1 file lớn chiếm hết top-k.
        """
        if not query.strip():
            return []
        query_tokens = tokenize(query)
        if not query_tokens:
            return []
        with self._lock:
            chunks = self._chunks
            bm25   = self._bm25
        if not chunks:
            return []
        scores = _score(bm25, chunks, query_tokens)
        ranked_all = sorted(
            [(s, c) for s, c in zip(scores, chunks) if s > 0],
            key=lambda x: x[0],
            reverse=True,
        )
        if not ranked_all:
            return []

        # Score threshold: loại chunk có điểm thấp hơn 50% điểm cao nhất
        top_score = ranked_all[0][0]
        min_score = top_score * 0.5

        # Token coverage: ít nhất 40% query tokens phải xuất hiện trong chunk
        unique_query = set(query_tokens)
        min_coverage = max(1, int(len(unique_query) * 0.4))

        # Lọc: score threshold + token coverage + max_per_source
        result: list[tuple[float, dict]] = []
        source_count: dict[str, int] = {}
        for score, chunk in ranked_all:
            if score < min_score:
                break
            chunk_token_set = set(chunk["tokens"])
            matched = len(unique_query & chunk_token_set)
            if matched < min_coverage:
                continue
            src = chunk["source"]
            if source_count.get(src, 0) < max_per_source:
                result.append((score, chunk))
                source_count[src] = source_count.get(src, 0) + 1
            if len(result) >= top_k:
                break
        return result

    def search(self, query: str, top_k: int = 4) -> str:
        ranked = self._rank(query, top_k)
        if not ranked:
            return ""
        return "\n\n---\n\n".join(
            f"[{c['source']}] {c['title']}\n{c['content']}"
            for _, c in ranked
        )

    def search_with_meta(self, query: str, top_k: int = 4) -> tuple[str, list[dict]]:
        """Như search() nhưng trả thêm danh sách nguồn tham khảo (đã dedup)."""
        ranked = self._rank(query, top_k)
        if not ranked:
            return "", []
        context = "\n\n---\n\n".join(
            f"[{c['source']}] {c['title']}\n{c['content']}"
            for _, c in ranked
        )
        seen: set[str] = set()
        sources: list[dict] = []
        for _, c in ranked:
            if c["source"] not in seen:
                seen.add(c["source"])
                sources.append({"source": c["source"], "title": c["doc_title"]})
        return context, sources

    @property
    def chunk_count(self) -> int:
        with self._lock:
            return len(self._chunks)


# ---------------------------------------------------------------------------
# BM25 helpers — dùng rank-bm25 nếu có, fallback TF-IDF nếu không
# ---------------------------------------------------------------------------

def _build_bm25(corpus: list[list[str]]):
    if not corpus:
        return None
    try:
        from rank_bm25 import BM25Plus
        return BM25Plus(corpus)
    except ImportError:
        return None


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
