"""
Embedding Service — tạo và tìm kiếm vector embeddings.

Dùng OpenAI text-embedding-3-small (multilingual, rẻ):
- $0.02 / 1 triệu token ≈ toàn bộ knowledge base hiện tại < $0.01
- 1536 chiều, lưu dưới dạng float32 bytes trong SQLite

Chunking:
- Markdown: chia theo section (##) — giữ nguyên cấu trúc
- Plain text (PDF): chia theo kích thước với overlap để không mất ngữ cảnh

Fallback: nếu OPENAI_API_KEY chưa cấu hình → trả về [] để rag.py dùng BM25.
"""

import logging
import re
from datetime import datetime

import numpy as np

from app.config import OPENAI_API_KEY, OPENROUTER_API_KEY
from app.database import get_conn

log = logging.getLogger(__name__)

# Ưu tiên OpenAI trực tiếp; fallback về OpenRouter (cùng API format)
if OPENAI_API_KEY:
    _API_KEY      = OPENAI_API_KEY
    _BASE_URL     = None                          # OpenAI mặc định
    EMBED_MODEL   = "text-embedding-3-small"
elif OPENROUTER_API_KEY:
    _API_KEY      = OPENROUTER_API_KEY
    _BASE_URL     = "https://openrouter.ai/api/v1"
    EMBED_MODEL   = "openai/text-embedding-3-small"
else:
    _API_KEY      = None
    _BASE_URL     = None
    EMBED_MODEL   = ""

EMBED_DIMS    = 1536
CHUNK_SIZE    = 900    # ký tự (~225 token) — đủ nhỏ để search chính xác
CHUNK_OVERLAP = 150    # ký tự overlap giữa các chunk liền nhau
MIN_CHUNK     = 60     # bỏ qua chunk quá ngắn
SCORE_CUTOFF  = 0.30   # cosine similarity tối thiểu

EMBED_ENABLED = bool(_API_KEY)

_client = None


def _get_client():
    global _client
    if _client is None:
        from openai import AsyncOpenAI
        kwargs = {"api_key": _API_KEY}
        if _BASE_URL:
            kwargs["base_url"] = _BASE_URL
        _client = AsyncOpenAI(**kwargs)
    return _client


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def chunk_markdown(source: str, content: str) -> list[dict]:
    """Chia theo section markdown (##). Mỗi section = 1 chunk."""
    sections = re.split(r"\n(?=#{1,3} )", content)
    chunks = []
    for section in sections:
        section = section.strip()
        if len(section) < MIN_CHUNK:
            continue
        title_match = re.match(r"#{1,3} (.+)", section)
        title = title_match.group(1).strip() if title_match else ""
        chunks.append({"source": source, "title": title, "content": section})
    return chunks


def chunk_plain_text(source: str, doc_title: str, content: str) -> list[dict]:
    """Chia plain text theo kích thước với overlap — dùng cho PDF/DOCX/TXT."""
    chunks = []
    start = 0
    part  = 1
    while start < len(content):
        end  = start + CHUNK_SIZE
        text = content[start:end]

        # Tìm điểm ngắt tự nhiên (đoạn văn, câu)
        if end < len(content):
            for sep in ["\n\n", "\n", ". ", " "]:
                pos = text.rfind(sep)
                if pos > CHUNK_SIZE * 0.5:
                    text = text[: pos + len(sep)]
                    break

        text = text.strip()
        if len(text) >= MIN_CHUNK:
            chunks.append({
                "source":  source,
                "title":   f"{doc_title} — phần {part}" if doc_title else f"Phần {part}",
                "content": text,
            })
            part += 1

        advance = len(text) - CHUNK_OVERLAP
        if advance <= 0:
            advance = max(len(text), 1)
        start += advance

    return chunks


def smart_chunk(source: str, doc_title: str, content: str,
                is_markdown: bool = True) -> list[dict]:
    """Chọn chiến lược chunking phù hợp."""
    if is_markdown:
        chunks = chunk_markdown(source, content)
        # Section quá dài → tiếp tục chia nhỏ hơn
        result = []
        for c in chunks:
            if len(c["content"]) > CHUNK_SIZE * 2:
                sub = chunk_plain_text(c["source"], c["title"], c["content"])
                result.extend(sub)
            else:
                result.append(c)
        return result
    return chunk_plain_text(source, doc_title, content)


# ---------------------------------------------------------------------------
# Embedding API
# ---------------------------------------------------------------------------

async def _embed(text: str) -> list[float]:
    """Gọi OpenAI API để tạo embedding cho 1 text."""
    client   = _get_client()
    response = await client.embeddings.create(
        model=EMBED_MODEL,
        input=text[:8000],   # max ~2000 token
    )
    return response.data[0].embedding


def _to_blob(vec: list[float]) -> bytes:
    return np.array(vec, dtype=np.float32).tobytes()


def _from_blob(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)


# ---------------------------------------------------------------------------
# Index và Search
# ---------------------------------------------------------------------------

async def index_document(source: str, doc_title: str, content: str,
                         is_markdown: bool = True) -> int:
    """
    Chia nhỏ + tạo embeddings + lưu vào DB.
    Xoá chunks cũ của source trước khi index lại.
    Trả về số chunks đã tạo.
    """
    if not EMBED_ENABLED:
        return 0

    chunks = smart_chunk(source, doc_title, content, is_markdown)
    now    = datetime.now().isoformat(timespec="seconds")

    with get_conn() as conn:
        conn.execute("DELETE FROM chunks WHERE source=?", (source,))

    count = 0
    for chunk in chunks:
        # Ghép title vào text để embedding hiểu ngữ cảnh hơn
        embed_text = f"{chunk['title']}\n{chunk['content']}" if chunk["title"] else chunk["content"]
        try:
            vec  = await _embed(embed_text)
            blob = _to_blob(vec)
            with get_conn() as conn:
                conn.execute(
                    "INSERT INTO chunks (source, title, content, embedding, created_at) "
                    "VALUES (?,?,?,?,?)",
                    (chunk["source"], chunk["title"], chunk["content"], blob, now),
                )
            count += 1
        except Exception as e:
            log.error("Embedding lỗi chunk %s: %s", chunk["title"], e)

    log.info("Indexed %s: %d chunks", source, count)
    return count


async def vector_search(query: str, top_k: int = 4) -> list[dict]:
    """
    Tìm kiếm bằng cosine similarity.
    Load tất cả vectors từ DB vào numpy — đủ nhanh cho <20.000 chunks.
    """
    if not EMBED_ENABLED:
        return []

    try:
        query_vec  = np.array(await _embed(query), dtype=np.float32)
        query_norm = float(np.linalg.norm(query_vec))
        if query_norm == 0:
            return []

        with get_conn() as conn:
            rows = conn.execute(
                "SELECT source, title, content, embedding FROM chunks"
            ).fetchall()

        if not rows:
            return []

        # Vectorize tất cả embeddings
        matrix = np.stack([_from_blob(r["embedding"]) for r in rows])  # (N, 1536)
        norms  = np.linalg.norm(matrix, axis=1)
        norms[norms == 0] = 1e-10

        scores = (matrix @ query_vec) / (norms * query_norm)

        # Lấy top_k kết quả trên ngưỡng
        top_idx = scores.argsort()[::-1][:top_k]
        results = []
        for idx in top_idx:
            if scores[idx] >= SCORE_CUTOFF:
                r = rows[idx]
                results.append({
                    "source":  r["source"],
                    "title":   r["title"],
                    "content": r["content"],
                    "score":   float(scores[idx]),
                })
        return results

    except Exception as e:
        log.error("vector_search lỗi: %s", e)
        return []


def get_indexed_sources() -> set[str]:
    """Trả về set các source đã được index trong DB."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT source FROM chunks"
        ).fetchall()
    return {r["source"] for r in rows}
