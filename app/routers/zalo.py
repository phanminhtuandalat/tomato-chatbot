"""
Zalo webhook router.
"""

import hashlib
import hmac
import json
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app.config import ZALO_APP_SECRET, ZALO_OA_ACCESS_TOKEN
from app.services import llm
from app.services import rag as rag_module

router = APIRouter()
logger = logging.getLogger(__name__)


def _verify_signature(raw_body: bytes, mac_header: str) -> bool:
    if not ZALO_APP_SECRET or not mac_header:
        return True
    expected = hmac.new(ZALO_APP_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, mac_header)


async def _send(user_id: str, text: str) -> None:
    if not ZALO_OA_ACCESS_TOKEN:
        return
    import httpx
    if len(text) > 1900:
        text = text[:1900] + "\n\n[...] Liên hệ cán bộ khuyến nông để biết thêm."
    async with httpx.AsyncClient(timeout=10.0) as client:
        await client.post(
            "https://openapi.zalo.me/v3.0/oa/message/cs",
            headers={"access_token": ZALO_OA_ACCESS_TOKEN, "Content-Type": "application/json"},
            json={"recipient": {"user_id": user_id}, "message": {"text": text}},
        )


@router.post("/webhook/zalo")
async def zalo_webhook(request: Request):
    raw_body  = await request.body()
    mac_header = request.headers.get("mac", "")

    if not _verify_signature(raw_body, mac_header):
        raise HTTPException(status_code=403, detail="Invalid signature")

    body    = json.loads(raw_body)
    event   = body.get("event_name", "")
    user_id = body.get("sender", {}).get("id") or body.get("user_id_by_app", "")

    if event == "user_send_text" and user_id:
        text = body.get("message", {}).get("text", "").strip()
        if text:
            context = rag_module.rag.search(text)
            try:
                answer = await llm.chat(question=text, context=context)
            except Exception as e:
                logger.error(f"LLM error: {e}")
                answer = "Xin lỗi, hệ thống đang bận. Vui lòng thử lại sau hoặc gọi 1900-9008."
            await _send(user_id, answer)

    elif event == "follow" and user_id:
        await _send(user_id,
            "Xin chào! Tôi là trợ lý tư vấn trồng cà chua.\n\n"
            "Hỏi tôi về: kỹ thuật trồng, sâu bệnh, phân bón, thu hoạch.\n"
            "Bạn cũng có thể gửi ảnh lá/quả bị bệnh để tôi nhận dạng!"
        )

    return JSONResponse({"status": "ok"})
