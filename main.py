"""
Chatbot cà chua — Web UI + Zalo OA webhook server
"""

import hashlib
import hmac
import json
import logging
import os
import importlib
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

import claude_client
import knowledge_base
import zalo_client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Chatbot Cà Chua")
app.mount("/static", StaticFiles(directory="static"), name="static")

ZALO_APP_SECRET = os.getenv("ZALO_APP_SECRET", "")


# ---------------------------------------------------------------------------
# Web UI
# ---------------------------------------------------------------------------

DATA_DIR = Path(__file__).parent / "data"

@app.get("/")
async def index():
    return FileResponse("static/index.html")

@app.get("/admin")
async def admin():
    return FileResponse("static/admin.html")


# ---------------------------------------------------------------------------
# Web chat API
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    message: str = ""
    image: str = ""  # base64 data URL, ví dụ: data:image/jpeg;base64,...


@app.post("/api/chat")
async def api_chat(req: ChatRequest):
    question = req.message.strip()
    image = req.image.strip()

    if not question and not image:
        return JSONResponse({"answer": ""})

    context = knowledge_base.search(question) if question else ""

    try:
        answer = await claude_client.ask(
            question=question,
            context=context,
            image_base64=image,
        )
    except Exception as e:
        logger.error(f"LLM error: {e}")
        answer = "Xin lỗi, hệ thống đang bận. Vui lòng thử lại sau hoặc gọi đường dây nóng khuyến nông: 1900-9008."

    return JSONResponse({"answer": answer})


# ---------------------------------------------------------------------------
# Admin API — quản lý knowledge base
# ---------------------------------------------------------------------------

def reload_kb():
    """Reload knowledge base sau khi thêm/xoá tài liệu."""
    import knowledge_base
    importlib.reload(knowledge_base)
    # Cập nhật reference trong module hiện tại
    import sys
    sys.modules["knowledge_base"] = knowledge_base


@app.post("/admin/upload")
async def admin_upload(file: UploadFile = File(...)):
    ext = Path(file.filename).suffix.lower()
    if ext not in (".pdf", ".docx", ".txt", ".md"):
        return JSONResponse({"ok": False, "error": f"Định dạng {ext} không được hỗ trợ"})

    raw = await file.read()
    tmp_path = DATA_DIR / ("_tmp" + ext)
    tmp_path.write_bytes(raw)

    try:
        from ingest import read_pdf, read_docx, read_txt, clean_text, save_to_knowledge_base, safe_filename
        title = Path(file.filename).stem.replace("_", " ").replace("-", " ").title()
        if ext == ".pdf":
            content = read_pdf(str(tmp_path))
        elif ext == ".docx":
            content = read_docx(str(tmp_path))
        else:
            content = read_txt(str(tmp_path))

        content = clean_text(content)
        if len(content) < 100:
            return JSONResponse({"ok": False, "error": "Nội dung quá ngắn"})

        out = save_to_knowledge_base(title, content, file.filename)
        reload_kb()
        return JSONResponse({"ok": True, "filename": out.name, "chars": len(content)})
    except Exception as e:
        logger.error(e)
        return JSONResponse({"ok": False, "error": str(e)})
    finally:
        tmp_path.unlink(missing_ok=True)


class UrlRequest(BaseModel):
    url: str

@app.post("/admin/upload-url")
async def admin_upload_url(req: UrlRequest):
    try:
        from ingest import read_url, clean_text, save_to_knowledge_base
        title, content = read_url(req.url)
        content = clean_text(content)
        if len(content) < 100:
            return JSONResponse({"ok": False, "error": "Nội dung trang quá ngắn hoặc không đọc được"})
        out = save_to_knowledge_base(title, content, req.url)
        reload_kb()
        return JSONResponse({"ok": True, "filename": out.name, "chars": len(content)})
    except Exception as e:
        logger.error(e)
        return JSONResponse({"ok": False, "error": str(e)})


class DeleteRequest(BaseModel):
    filename: str

@app.post("/admin/upload-image")
async def admin_upload_image(file: UploadFile = File(...), title: str = ""):
    ext = Path(file.filename).suffix.lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        return JSONResponse({"ok": False, "error": "Chỉ hỗ trợ ảnh JPG, PNG, WEBP"})

    import base64
    raw = await file.read()
    mime = "image/jpeg" if ext in (".jpg", ".jpeg") else f"image/{ext[1:]}"
    b64 = base64.b64encode(raw).decode()
    data_url = f"data:{mime};base64,{b64}"

    doc_title = title.strip() or Path(file.filename).stem.replace("_", " ").replace("-", " ").title()

    # Dùng vision AI để trích xuất kiến thức từ ảnh
    try:
        extracted = await claude_client.ask(
            question="",
            context="",
            image_base64=data_url,
            extract_mode=True,
        )
        if len(extracted) < 50:
            return JSONResponse({"ok": False, "error": "Không trích xuất được nội dung từ ảnh"})

        from ingest import save_to_knowledge_base, clean_text
        content = clean_text(extracted)
        out = save_to_knowledge_base(doc_title, content, file.filename)
        reload_kb()
        return JSONResponse({"ok": True, "filename": out.name, "chars": len(content), "preview": content[:200]})
    except Exception as e:
        logger.error(e)
        return JSONResponse({"ok": False, "error": str(e)})


@app.post("/admin/delete")
async def admin_delete(req: DeleteRequest):
    # Chỉ cho phép xoá file trong thư mục data/
    target = DATA_DIR / Path(req.filename).name
    if not target.exists():
        return JSONResponse({"ok": False, "error": "Không tìm thấy file"})
    target.unlink()
    reload_kb()
    return JSONResponse({"ok": True})


@app.get("/admin/docs")
async def admin_docs():
    docs = []
    for f in sorted(DATA_DIR.glob("*.md"), key=lambda x: x.stat().st_mtime, reverse=True):
        stat = f.stat()
        docs.append({
            "name": f.name,
            "size_kb": round(stat.st_size / 1024, 1),
            "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%d/%m/%Y %H:%M"),
        })
    return JSONResponse({"docs": docs})


# ---------------------------------------------------------------------------
# Zalo webhook
# ---------------------------------------------------------------------------

def verify_zalo_signature(raw_body: bytes, mac_header: str) -> bool:
    if not ZALO_APP_SECRET or not mac_header:
        return True
    expected = hmac.new(
        ZALO_APP_SECRET.encode(),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, mac_header)


async def handle_text_message(user_id: str, text: str):
    logger.info(f"[Zalo] [{user_id}] Hỏi: {text}")
    context = knowledge_base.search(text)
    try:
        answer = await claude_client.ask(question=text, context=context)
    except Exception as e:
        logger.error(f"LLM error: {e}")
        answer = "Xin lỗi, hệ thống đang bận. Vui lòng thử lại sau hoặc gọi đường dây nóng khuyến nông: 1900-9008."
    await zalo_client.send_message(user_id, answer)


async def handle_follow(user_id: str):
    welcome = (
        "Xin chào! Tôi là trợ lý tư vấn trồng cà chua.\n\n"
        "Bạn có thể hỏi tôi về:\n"
        "- Kỹ thuật trồng và chăm sóc\n"
        "- Sâu bệnh và cách xử lý\n"
        "- Phân bón và tưới nước\n"
        "- Thời điểm thu hoạch\n\n"
        "Hãy gõ câu hỏi của bạn!"
    )
    await zalo_client.send_message(user_id, welcome)


@app.post("/webhook/zalo")
async def zalo_webhook(request: Request):
    raw_body = await request.body()
    mac_header = request.headers.get("mac", "")

    if not verify_zalo_signature(raw_body, mac_header):
        raise HTTPException(status_code=403, detail="Invalid signature")

    body = json.loads(raw_body)
    event = body.get("event_name", "")
    user_id = body.get("sender", {}).get("id") or body.get("user_id_by_app", "")

    if event == "user_send_text":
        text = body.get("message", {}).get("text", "").strip()
        if text and user_id:
            await handle_text_message(user_id, text)
    elif event == "follow":
        if user_id:
            await handle_follow(user_id)

    return JSONResponse({"status": "ok"})


# ---------------------------------------------------------------------------
# Chạy local
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
