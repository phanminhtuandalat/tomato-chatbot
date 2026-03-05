"""
RAG đơn giản: tìm kiếm theo từ khóa trong file Markdown.
Không cần vector DB — phù hợp MVP.
"""

import re
from pathlib import Path


def _load_chunks(data_dir: str = "data") -> list[dict]:
    """Đọc file Markdown, tách thành các chunk theo section."""
    chunks = []
    data_path = Path(__file__).parent / data_dir

    for md_file in data_path.glob("*.md"):
        text = md_file.read_text(encoding="utf-8")
        # Tách theo heading ## (section chính)
        sections = re.split(r"\n(?=## )", text)
        for section in sections:
            section = section.strip()
            if len(section) > 50:
                # Lấy tiêu đề section làm tags
                title_match = re.match(r"#{1,3} (.+)", section)
                title = title_match.group(1) if title_match else ""
                chunks.append({
                    "title": title,
                    "content": section,
                    "source": md_file.name,
                })

    return chunks


# Load 1 lần khi khởi động
_CHUNKS = _load_chunks()


def search(query: str, top_k: int = 3) -> str:
    """
    Tìm các chunk liên quan đến query bằng keyword matching.
    Trả về chuỗi context để đưa vào Claude prompt.
    """
    query_words = set(re.findall(r"\w+", query.lower()))

    scored = []
    for chunk in _CHUNKS:
        chunk_text = (chunk["title"] + " " + chunk["content"]).lower()
        chunk_words = set(re.findall(r"\w+", chunk_text))
        # Điểm = số từ chung / tổng từ query
        overlap = len(query_words & chunk_words)
        if overlap > 0:
            scored.append((overlap, chunk))

    # Sắp xếp theo điểm giảm dần
    scored.sort(key=lambda x: x[0], reverse=True)
    top_chunks = [c for _, c in scored[:top_k]]

    if not top_chunks:
        return ""

    context_parts = []
    for chunk in top_chunks:
        context_parts.append(f"### {chunk['title']}\n{chunk['content']}")

    return "\n\n---\n\n".join(context_parts)
