"""
Chatbot cà chua — Web UI + Zalo OA webhook server
"""

import hashlib
import hmac
import json
import logging
import os

from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException
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

@app.get("/")
async def index():
    return FileResponse("static/index.html")


# ---------------------------------------------------------------------------
# Web chat API
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    message: str

@app.post("/api/chat")
async def api_chat(req: ChatRequest):
    question = req.message.strip()
    if not question:
        return JSONResponse({"answer": ""})

    context = knowledge_base.search(question)
    try:
        answer = await claude_client.ask(question=question, context=context)
    except Exception as e:
        logger.error(f"LLM error: {e}")
        answer = "Xin lỗi, hệ thống đang bận. Vui lòng thử lại sau hoặc gọi đường dây nóng khuyến nông: 1900-9008."

    return JSONResponse({"answer": answer})


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
        logger.error(f"Claude API error: {e}")
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
