"""
Admin router — quản lý knowledge base, xem feedback.
Tất cả endpoints đều yêu cầu HTTP Basic Auth.
"""

import secrets
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel

from app.config import ADMIN_USER, ADMIN_PASSWORD
from app.database import get_feedback_stats, get_analytics, create_premium_code, list_premium_codes
from app.services import rag as rag_module

router  = APIRouter()
security = HTTPBasic()
DATA_DIR = Path(__file__).parent.parent.parent / "data"


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def require_admin(credentials: HTTPBasicCredentials = Depends(security)):
    ok_user = secrets.compare_digest(credentials.username.encode(), ADMIN_USER.encode())
    ok_pass = secrets.compare_digest(credentials.password.encode(), ADMIN_PASSWORD.encode())
    if not (ok_user and ok_pass):
        raise HTTPException(
            status_code=401,
            detail="Sai tên đăng nhập hoặc mật khẩu",
            headers={"WWW-Authenticate": "Basic realm='Admin'"},
        )


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@router.get("/admin")
async def admin_page(_: None = Depends(require_admin)):
    return FileResponse("static/admin.html")


# ---------------------------------------------------------------------------
# Knowledge base management
# ---------------------------------------------------------------------------

def _save_doc(title: str, content: str, source: str) -> Path:
    import re, unicodedata
    name = unicodedata.normalize("NFD", title.lower())
    name = "".join(c for c in name if unicodedata.category(c) != "Mn")
    name = re.sub(r"[^\w\s-]", "", name)
    name = re.sub(r"[\s-]+", "_", name).strip("_")[:60] or "document"
    out  = DATA_DIR / (name + ".md")
    out.write_text(f"# {title}\n\n> Nguồn: {source}\n\n{content}\n", encoding="utf-8")
    return out


def _clean(text: str) -> str:
    import re
    text = re.sub(r"\n{3,}", "\n\n", text)
    return re.sub(r" {2,}", " ", text).strip()


@router.post("/admin/upload")
async def upload_file(file: UploadFile = File(...), _: None = Depends(require_admin)):
    ext = Path(file.filename).suffix.lower()
    if ext not in (".pdf", ".docx", ".txt", ".md"):
        return JSONResponse({"ok": False, "error": f"Định dạng {ext} không được hỗ trợ"})

    raw = await file.read()
    tmp = DATA_DIR / ("_tmp" + ext)
    tmp.write_bytes(raw)

    try:
        title = Path(file.filename).stem.replace("_", " ").replace("-", " ").title()
        if ext == ".pdf":
            from pypdf import PdfReader
            content = "\n\n".join(p.extract_text() or "" for p in PdfReader(str(tmp)).pages)
        elif ext == ".docx":
            from docx import Document
            content = "\n\n".join(p.text for p in Document(str(tmp)).paragraphs if p.text.strip())
        else:
            content = tmp.read_text(encoding="utf-8", errors="ignore")

        content = _clean(content)
        if len(content) < 100:
            return JSONResponse({"ok": False, "error": "Nội dung quá ngắn"})

        out = _save_doc(title, content, file.filename)
        rag_module.rag.reload()
        return JSONResponse({"ok": True, "filename": out.name, "chars": len(content)})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})
    finally:
        tmp.unlink(missing_ok=True)


class UrlRequest(BaseModel):
    url: str

@router.post("/admin/upload-url")
async def upload_url(req: UrlRequest, _: None = Depends(require_admin)):
    try:
        import httpx
        from bs4 import BeautifulSoup
        resp = httpx.get(req.url, follow_redirects=True, timeout=20,
                         headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        title = soup.title.string.strip() if soup.title else req.url
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        main = soup.find("article") or soup.find("main") or soup.body
        lines = (main or soup).get_text(separator="\n").splitlines()
        content = _clean("\n".join(l.strip() for l in lines if l.strip()))
        if len(content) < 100:
            return JSONResponse({"ok": False, "error": "Nội dung trang quá ngắn"})
        out = _save_doc(title, content, req.url)
        rag_module.rag.reload()
        return JSONResponse({"ok": True, "filename": out.name, "chars": len(content)})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


@router.post("/admin/upload-image")
async def upload_image(file: UploadFile = File(...), title: str = "", _: None = Depends(require_admin)):
    ext = Path(file.filename).suffix.lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp"):
        return JSONResponse({"ok": False, "error": "Chỉ hỗ trợ JPG, PNG, WEBP"})

    import base64
    from app.services.llm import extract_from_image
    raw  = await file.read()
    mime = "image/jpeg" if ext in (".jpg", ".jpeg") else f"image/{ext[1:]}"
    b64  = f"data:{mime};base64,{base64.b64encode(raw).decode()}"

    try:
        extracted = await extract_from_image(b64)
        if len(extracted) < 50:
            return JSONResponse({"ok": False, "error": "Không trích xuất được nội dung"})
        doc_title = title.strip() or Path(file.filename).stem.replace("_", " ").title()
        out = _save_doc(doc_title, _clean(extracted), file.filename)
        rag_module.rag.reload()
        return JSONResponse({"ok": True, "filename": out.name, "chars": len(extracted), "preview": extracted[:200]})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


class DeleteRequest(BaseModel):
    filename: str

@router.post("/admin/delete")
async def delete_doc(req: DeleteRequest, _: None = Depends(require_admin)):
    target = DATA_DIR / Path(req.filename).name
    if not target.exists():
        return JSONResponse({"ok": False, "error": "Không tìm thấy file"})
    target.unlink()
    rag_module.rag.reload()
    return JSONResponse({"ok": True})


@router.get("/admin/docs")
async def list_docs(_: None = Depends(require_admin)):
    docs = [
        {
            "name": f.name,
            "size_kb": round(f.stat().st_size / 1024, 1),
            "modified": datetime.fromtimestamp(f.stat().st_mtime).strftime("%d/%m/%Y %H:%M"),
        }
        for f in sorted(DATA_DIR.glob("*.md"), key=lambda x: x.stat().st_mtime, reverse=True)
    ]
    return JSONResponse({"docs": docs})


@router.get("/admin/feedback")
async def feedback_report(_: None = Depends(require_admin)):
    return JSONResponse(get_feedback_stats())


class PremiumCodeRequest(BaseModel):
    code: str
    requests: int
    images: int = 0
    max_uses: int = 1
    note: str = ""

@router.post("/admin/premium-code")
async def create_code(req: PremiumCodeRequest, _: None = Depends(require_admin)):
    ok = create_premium_code(req.code, req.requests, req.images, req.max_uses, req.note)
    if not ok:
        return JSONResponse({"ok": False, "error": "Mã đã tồn tại"})
    return JSONResponse({"ok": True, "code": req.code.upper()})

@router.get("/admin/premium-codes")
async def get_codes(_: None = Depends(require_admin)):
    return JSONResponse({"codes": list_premium_codes()})

@router.get("/admin/analytics")
async def analytics_report(_: None = Depends(require_admin)):
    return JSONResponse(get_analytics())
