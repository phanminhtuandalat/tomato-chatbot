"""
Tests cho RAG service.
Chạy: pytest tests/
"""

from pathlib import Path
from app.services.rag import RAGService, normalize, tokenize


def test_normalize_removes_diacritics():
    assert normalize("cà chua") == "ca chua"
    assert normalize("héo rũ") == "heo ru"
    assert normalize("bón phân") == "bon phan"


def test_tokenize_minimum_length():
    tokens = tokenize("cà chua bị vàng lá")
    assert "chua" in tokens
    assert "vang" in tokens
    # Ký tự đơn bị lọc
    assert "b" not in tokens


def test_search_with_diacritics(tmp_path):
    """Tìm có dấu và không dấu phải cho cùng kết quả."""
    (tmp_path / "test.md").write_text(
        "## Bệnh héo rũ\nCây cà chua bị héo rũ do nấm Fusarium. Không có thuốc trị.",
        encoding="utf-8",
    )
    svc = RAGService(data_dir=tmp_path)

    result_accent    = svc.search("héo rũ")
    result_no_accent = svc.search("heo ru")

    assert result_accent != "",    "Tìm có dấu phải ra kết quả"
    assert result_no_accent != "", "Tìm không dấu phải ra kết quả"
    assert "Fusarium" in result_accent or "Fusarium" in result_no_accent


def test_search_empty_query():
    from app.services.rag import rag
    assert rag.search("") == ""
    assert rag.search("   ") == ""


def test_search_returns_relevant_content():
    from app.services.rag import rag
    result = rag.search("vàng lá cà chua")
    assert result != "", "Search phải trả về nội dung khi có dữ liệu"


def test_reload_is_idempotent():
    from app.services.rag import rag
    count_before = rag.chunk_count
    rag.reload()
    count_after = rag.chunk_count
    assert count_before == count_after


def test_search_top_k(tmp_path):
    """top_k phải giới hạn số chunk trả về."""
    for i in range(5):
        (tmp_path / f"doc{i}.md").write_text(
            f"## Chủ đề {i}\nCà chua trồng theo phương pháp {i}.",
            encoding="utf-8",
        )
    svc = RAGService(data_dir=tmp_path)
    result = svc.search("cà chua", top_k=2)
    # Kết quả chứa separator "---" giữa các chunk, tối đa 1 separator cho 2 chunks
    assert result.count("---") <= 1
