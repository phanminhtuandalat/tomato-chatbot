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
from app.database import (
    get_feedback_stats, get_analytics, create_premium_code, list_premium_codes,
    get_flywheel_data, get_review_tips, approve_tip, reject_tip, get_image_submissions,
    get_tip_device_id, add_points, get_evolution_history, get_evolution_stats,
)
from app.services import rag as rag_module
from app.services.embeddings import index_document, EMBED_ENABLED

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
        if EMBED_ENABLED:
            await index_document(out.stem, title, out.read_text(encoding="utf-8"))
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
        if EMBED_ENABLED:
            await index_document(out.stem, title, out.read_text(encoding="utf-8"))
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
        if EMBED_ENABLED:
            await index_document(out.stem, doc_title, out.read_text(encoding="utf-8"))
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
    source = target.stem
    target.unlink()
    rag_module.rag.reload()
    if EMBED_ENABLED:
        from app.database import get_conn
        with get_conn() as conn:
            conn.execute("DELETE FROM chunks WHERE source=?", (source,))
    return JSONResponse({"ok": True})


@router.post("/admin/reindex")
async def reindex_all(_: None = Depends(require_admin)):
    """Tạo lại toàn bộ embeddings từ knowledge base hiện tại."""
    if not EMBED_ENABLED:
        return JSONResponse({"ok": False, "error": "OPENAI_API_KEY chưa được cấu hình"})
    total = 0
    errors = []
    for md_file in sorted(DATA_DIR.glob("*.md")):
        try:
            content = md_file.read_text(encoding="utf-8")
            n = await index_document(md_file.stem, md_file.stem.replace("_", " ").title(), content)
            total += n
        except Exception as e:
            errors.append(f"{md_file.name}: {e}")
    return JSONResponse({"ok": True, "total_chunks": total, "errors": errors})


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
    expires_at: str | None = None  # ISO date string, ví dụ "2026-12-31" hoặc None = không hết hạn

@router.post("/admin/premium-code")
async def create_code(req: PremiumCodeRequest, _: None = Depends(require_admin)):
    ok = create_premium_code(req.code, req.requests, req.images, req.max_uses, req.note, req.expires_at)
    if not ok:
        return JSONResponse({"ok": False, "error": "Mã đã tồn tại"})
    return JSONResponse({"ok": True, "code": req.code.upper()})

@router.get("/admin/premium-codes")
async def get_codes(_: None = Depends(require_admin)):
    return JSONResponse({"codes": list_premium_codes()})

@router.get("/admin/analytics")
async def analytics_report(_: None = Depends(require_admin)):
    return JSONResponse(get_analytics())

@router.get("/admin/flywheel")
async def flywheel_report(_: None = Depends(require_admin)):
    return JSONResponse(get_flywheel_data())


# ---------------------------------------------------------------------------
# Community tips
# ---------------------------------------------------------------------------

class RejectRequest(BaseModel):
    note: str = ""

@router.get("/admin/community-tips")
async def community_tips(_: None = Depends(require_admin)):
    return JSONResponse({"tips": get_review_tips()})


@router.post("/admin/community-approve/{tip_id}")
async def community_approve(tip_id: int, _: None = Depends(require_admin)):
    # Lấy device_id trước khi approve (để thưởng điểm đúng người)
    submitter_id = get_tip_device_id(tip_id)
    tip = approve_tip(tip_id)
    if not tip:
        return JSONResponse({"ok": False, "error": "Không tìm thấy góp ý"})
    # Tạo file .md và đưa vào knowledge base
    out = _save_doc(tip["title"], tip["content"], f"community_tip_{tip_id}")
    rag_module.rag.reload()
    if EMBED_ENABLED:
        await index_document(out.stem, tip["title"], out.read_text(encoding="utf-8"))
    # Thưởng +20 điểm cho người gửi tip (tip từ review → admin approve)
    if submitter_id and tip.get("status") != "approved":
        add_points(submitter_id, "tip_approved", 20)
    return JSONResponse({"ok": True, "filename": out.name})


@router.post("/admin/community-reject/{tip_id}")
async def community_reject(tip_id: int, req: RejectRequest, _: None = Depends(require_admin)):
    ok = reject_tip(tip_id, req.note)
    return JSONResponse({"ok": ok})


# ---------------------------------------------------------------------------
# Data Flywheel — AI tạo bài từ gap
# ---------------------------------------------------------------------------

class GapContentRequest(BaseModel):
    topic: str

@router.post("/admin/generate-gap-content")
async def generate_gap_content(req: GapContentRequest, _: None = Depends(require_admin)):
    topic = req.topic.strip()[:100]
    if not topic:
        return JSONResponse({"ok": False, "error": "Chưa có chủ đề"})

    prompt = f"""Bạn là chuyên gia trồng cà chua Việt Nam. Viết một bài kiến thức ngắn (~400 từ) về chủ đề: "{topic}"

Cấu trúc bài:
# [Tiêu đề rõ ràng về {topic}]

## Tổng quan
[2-3 câu giới thiệu]

## Triệu chứng / Đặc điểm
[Mô tả cụ thể bà con nhận biết]

## Nguyên nhân
[Nguyên nhân chính]

## Cách xử lý
[Tên thuốc/biện pháp, liều lượng, thời điểm — cụ thể cho điều kiện Việt Nam]

## Phòng ngừa
[2-3 biện pháp phòng ngừa]

Yêu cầu: tiếng Việt, thực tế, có số liệu cụ thể (liều lượng, khoảng cách, thời gian). KHÔNG bịa đặt."""

    try:
        from app.services.llm import _call, OPENROUTER_MODEL
        raw = await _call(
            [{"role": "user", "content": prompt}],
            model=OPENROUTER_MODEL,
            max_tokens=700,
        )
        # Lưu thành file .md và đưa vào KB
        title = f"Hướng dẫn: {topic}"
        out = _save_doc(title, raw.strip(), f"gap_auto_{topic[:30]}")
        rag_module.rag.reload()
        if EMBED_ENABLED:
            await index_document(out.stem, title, out.read_text(encoding="utf-8"))
        return JSONResponse({"ok": True, "filename": out.name, "preview": raw[:300]})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


# ---------------------------------------------------------------------------
# Self-Evolution Engine
# ---------------------------------------------------------------------------

@router.get("/admin/evolution-log")
async def evolution_log(_: None = Depends(require_admin)):
    return JSONResponse({
        "stats":   get_evolution_stats(),
        "history": get_evolution_history(limit=100),
    })


@router.post("/admin/run-evolution")
async def run_evolution(_: None = Depends(require_admin)):
    """Chạy thủ công 1 chu kỳ evolution ngay lập tức."""
    from app.services.evolution import run_evolution_cycle
    result = await run_evolution_cycle()
    return JSONResponse(result)


@router.post("/admin/evolution-config")
async def evolution_config_update(req: dict, _: None = Depends(require_admin)):
    """Cập nhật config evolution (GAP_MIN_COUNT, GAP_MAX_PER_CYCLE, EVOLUTION_HOUR)."""
    import app.services.evolution as evo
    if "gap_min_count" in req:
        evo.GAP_MIN_COUNT = max(1, int(req["gap_min_count"]))
    if "gap_max_per_cycle" in req:
        evo.GAP_MAX_PER_CYCLE = max(1, min(20, int(req["gap_max_per_cycle"])))
    if "evolution_hour" in req:
        evo.EVOLUTION_HOUR = max(0, min(23, int(req["evolution_hour"])))
    return JSONResponse({
        "gap_min_count":     evo.GAP_MIN_COUNT,
        "gap_max_per_cycle": evo.GAP_MAX_PER_CYCLE,
        "evolution_hour":    evo.EVOLUTION_HOUR,
    })


# ---------------------------------------------------------------------------
# Test Telegram
# ---------------------------------------------------------------------------

@router.post("/admin/test-notify")
async def test_notify(_: None = Depends(require_admin)):
    from app.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
    from app.services.notify import enabled
    import httpx

    if not enabled():
        missing = []
        if not TELEGRAM_BOT_TOKEN: missing.append("TELEGRAM_BOT_TOKEN")
        if not TELEGRAM_CHAT_ID:   missing.append("TELEGRAM_CHAT_ID")
        return JSONResponse({"ok": False, "reason": f"Thiếu biến môi trường: {', '.join(missing)}"})

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ID, "text": "🍅 TEST — Telegram notify hoạt động!"},
            )
        data = res.json()
        if res.status_code == 200 and data.get("ok"):
            return JSONResponse({"ok": True})
        return JSONResponse({"ok": False, "reason": f"Telegram lỗi {res.status_code}: {data.get('description', str(data))}"})
    except Exception as e:
        return JSONResponse({"ok": False, "reason": str(e)})


# ---------------------------------------------------------------------------
# Image dataset
# ---------------------------------------------------------------------------

@router.get("/admin/image-submissions")
async def image_submissions(_: None = Depends(require_admin)):
    return JSONResponse({"submissions": get_image_submissions()})
