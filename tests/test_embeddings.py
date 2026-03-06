"""
Tests cho embedding service — chunking logic (không cần API key).
"""

from app.services.embeddings import chunk_markdown, chunk_plain_text, smart_chunk


SAMPLE_MD = """# Bệnh Héo Rũ

## Nguyên nhân
Vi khuẩn Ralstonia solanacearum tồn tại trong đất.

## Triệu chứng
Cây héo đột ngột lúc trưa, sáng hồi lại. Cắt thân thấy dịch chảy.

## Phòng trị
Bón vôi nâng pH. Luân canh với lúa. Nhổ cây bệnh ngay.
"""


def test_chunk_markdown_splits_by_section():
    chunks = chunk_markdown("test", SAMPLE_MD)
    assert len(chunks) >= 2
    titles = [c["title"] for c in chunks]
    assert any("Nguyên nhân" in t for t in titles)
    assert any("Triệu chứng" in t for t in titles)


def test_chunk_markdown_filters_short():
    md = "# Title\n\nok\n\n## Section\nNội dung đủ dài để không bị lọc bỏ vì quá ngắn."
    chunks = chunk_markdown("test", md)
    # "ok" quá ngắn phải bị lọc
    assert all(len(c["content"]) >= 60 for c in chunks)


def test_chunk_plain_text_creates_overlap():
    long_text = "Cà chua trồng theo kỹ thuật hiện đại. " * 50  # ~1900 chars
    chunks = chunk_plain_text("test", "Tài liệu test", long_text)
    assert len(chunks) >= 2
    # Mỗi chunk không được quá dài
    assert all(len(c["content"]) <= 1200 for c in chunks)


def test_chunk_plain_text_title_numbering():
    text = "Nội dung về cà chua rất dài. " * 60
    chunks = chunk_plain_text("test", "Tài liệu", text)
    assert chunks[0]["title"] == "Tài liệu — phần 1"
    if len(chunks) > 1:
        assert chunks[1]["title"] == "Tài liệu — phần 2"


def test_smart_chunk_markdown():
    chunks = smart_chunk("test_doc", "Test", SAMPLE_MD, is_markdown=True)
    assert len(chunks) >= 2
    assert all(c["source"] == "test_doc" for c in chunks)


def test_smart_chunk_plain():
    text = "Thông tin kỹ thuật trồng cà chua. " * 40
    chunks = smart_chunk("doc", "Title", text, is_markdown=False)
    assert len(chunks) >= 1
    assert all("source" in c and "content" in c and "title" in c for c in chunks)


def test_chunk_preserves_source():
    chunks = chunk_markdown("benh_hai", SAMPLE_MD)
    assert all(c["source"] == "benh_hai" for c in chunks)


def test_chunk_empty_content():
    chunks = chunk_markdown("test", "")
    assert chunks == []

    chunks = chunk_plain_text("test", "Title", "")
    assert chunks == []
