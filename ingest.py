"""
Công cụ thêm tài liệu vào knowledge base.

Hỗ trợ:
  - PDF:  python ingest.py file.pdf
  - DOCX: python ingest.py file.docx
  - TXT:  python ingest.py file.txt
  - URL:  python ingest.py https://example.com/bai-viet

Kết quả: tạo file .md trong thư mục data/ và server tự nhận ngay.
"""

import re
import sys
import unicodedata
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Đọc nội dung từ nhiều định dạng
# ---------------------------------------------------------------------------

def read_pdf(path: str) -> str:
    from pypdf import PdfReader
    reader = PdfReader(path)
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n\n".join(pages)


def read_docx(path: str) -> str:
    from docx import Document
    doc = Document(path)
    return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())


def read_txt(path: str) -> str:
    return Path(path).read_text(encoding="utf-8", errors="ignore")


def read_url(url: str) -> tuple[str, str]:
    """Trả về (title, content)."""
    import httpx
    from bs4 import BeautifulSoup

    print(f"Đang tải: {url}")
    resp = httpx.get(url, follow_redirects=True, timeout=20,
                     headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    # Lấy tiêu đề
    title = soup.title.string.strip() if soup.title else url

    # Xoá script, style, nav, footer
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()

    # Lấy nội dung chính
    main = soup.find("article") or soup.find("main") or soup.body
    text = main.get_text(separator="\n") if main else soup.get_text(separator="\n")

    # Dọn dẹp khoảng trắng thừa
    lines = [l.strip() for l in text.splitlines()]
    text = "\n".join(l for l in lines if l)

    return title, text


# ---------------------------------------------------------------------------
# Làm sạch và chuẩn hoá văn bản
# ---------------------------------------------------------------------------

def clean_text(text: str) -> str:
    # Bỏ khoảng trắng thừa
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r" {2,}", " ", text)
    return text.strip()


def safe_filename(name: str) -> str:
    """Tạo tên file an toàn từ tên tài liệu."""
    name = unicodedata.normalize("NFD", name)
    name = "".join(c for c in name if unicodedata.category(c) != "Mn")
    name = re.sub(r"[^\w\s-]", "", name.lower())
    name = re.sub(r"[\s-]+", "_", name).strip("_")
    return name[:60] or "document"


# ---------------------------------------------------------------------------
# Lưu vào data/
# ---------------------------------------------------------------------------

def save_to_knowledge_base(title: str, content: str, source: str) -> Path:
    filename = safe_filename(title) + ".md"
    out_path = DATA_DIR / filename

    md_content = f"# {title}\n\n> Nguồn: {source}\n\n{content}\n"
    out_path.write_text(md_content, encoding="utf-8")
    return out_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print("Cách dùng:")
        print("  python ingest.py ten_file.pdf")
        print("  python ingest.py ten_file.docx")
        print("  python ingest.py ten_file.txt")
        print("  python ingest.py https://example.com/bai-viet")
        sys.exit(1)

    source = sys.argv[1]

    # Xác định loại nguồn
    if source.startswith("http://") or source.startswith("https://"):
        title, content = read_url(source)
        print(f"Đã tải: {title}")
    else:
        path = Path(source)
        if not path.exists():
            print(f"Không tìm thấy file: {source}")
            sys.exit(1)

        title = path.stem.replace("_", " ").replace("-", " ").title()
        ext = path.suffix.lower()

        if ext == ".pdf":
            print(f"Đang đọc PDF: {path.name}")
            content = read_pdf(source)
        elif ext == ".docx":
            print(f"Đang đọc DOCX: {path.name}")
            content = read_docx(source)
        elif ext in (".txt", ".md"):
            print(f"Đang đọc text: {path.name}")
            content = read_txt(source)
        else:
            print(f"Định dạng không hỗ trợ: {ext}")
            print("Hỗ trợ: .pdf, .docx, .txt, .md, hoặc URL")
            sys.exit(1)

    content = clean_text(content)

    if len(content) < 100:
        print("Nội dung quá ngắn, bỏ qua.")
        sys.exit(1)

    out_path = save_to_knowledge_base(title, content, source)

    print(f"\nDa them vao knowledge base:")
    print(f"  File: {out_path.name}")
    print(f"  Do dai: {len(content):,} ky tu")
    print(f"\nKhoi dong lai server de ap dung:")
    print(f"  python main.py")


if __name__ == "__main__":
    main()
