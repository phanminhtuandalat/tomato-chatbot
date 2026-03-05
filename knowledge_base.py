"""
RAG tối ưu cho tiếng Việt:
- Chuẩn hoá bỏ dấu để tìm kiếm (nông dân gõ không dấu vẫn tìm được)
- Chunk nhỏ hơn theo ### để context chính xác hơn
- Điểm TF-IDF đơn giản: từ hiếm được ưu tiên hơn từ phổ biến
"""

import math
import re
import unicodedata
from pathlib import Path


# ---------------------------------------------------------------------------
# Chuẩn hoá tiếng Việt
# ---------------------------------------------------------------------------

def normalize(text: str) -> str:
    """Bỏ dấu tiếng Việt, chuyển thường — để so sánh không phân biệt dấu."""
    text = text.lower()
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return text


def tokenize(text: str) -> list[str]:
    """Tách từ, bỏ stopword ngắn (1-2 ký tự)."""
    words = re.findall(r"[a-z0-9]+", normalize(text))
    return [w for w in words if len(w) > 2]


# ---------------------------------------------------------------------------
# Load và chunk tài liệu
# ---------------------------------------------------------------------------

def _load_chunks(data_dir: str = "data") -> list[dict]:
    """
    Đọc Markdown, tách theo ### (subsection) để chunk nhỏ và chính xác hơn.
    Nếu section không có ###, dùng ## làm chunk.
    """
    chunks = []
    data_path = Path(__file__).parent / data_dir

    for md_file in sorted(data_path.glob("*.md")):
        text = md_file.read_text(encoding="utf-8")
        # Tách theo bất kỳ heading nào (## hoặc ###)
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

    return chunks


_CHUNKS = _load_chunks()

# ---------------------------------------------------------------------------
# TF-IDF đơn giản: tính IDF cho từng từ
# ---------------------------------------------------------------------------

def _build_idf(chunks: list[dict]) -> dict[str, float]:
    N = len(chunks)
    df: dict[str, int] = {}
    for chunk in chunks:
        for word in set(chunk["tokens"]):
            df[word] = df.get(word, 0) + 1
    return {word: math.log(N / count) for word, count in df.items()}


_IDF = _build_idf(_CHUNKS)


# ---------------------------------------------------------------------------
# Tìm kiếm
# ---------------------------------------------------------------------------

def search(query: str, top_k: int = 3) -> str:
    """
    Tìm chunk liên quan nhất bằng TF-IDF + chuẩn hoá dấu tiếng Việt.
    Trả về chuỗi context để đưa vào Claude prompt.
    """
    if not query.strip():
        return ""

    query_tokens = set(tokenize(query))
    if not query_tokens:
        return ""

    scored = []
    for chunk in _CHUNKS:
        chunk_token_set = set(chunk["tokens"])
        # Điểm = tổng IDF của các từ chung (từ hiếm quan trọng được ưu tiên)
        score = sum(_IDF.get(w, 0) for w in query_tokens & chunk_token_set)
        if score > 0:
            scored.append((score, chunk))

    scored.sort(key=lambda x: x[0], reverse=True)
    top_chunks = [c for _, c in scored[:top_k]]

    if not top_chunks:
        return ""

    return "\n\n---\n\n".join(
        f"[{c['source']}] {c['title']}\n{c['content']}"
        for c in top_chunks
    )
