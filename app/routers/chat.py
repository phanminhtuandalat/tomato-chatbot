"""
Chat router — /api/chat, /api/feedback
Có rate limiting: tối đa 30 request/phút mỗi IP.
"""

import time
from collections import defaultdict
from datetime import datetime

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.services import llm, rag as rag_module
from app.database import save_feedback

router = APIRouter()

# ---------------------------------------------------------------------------
# Rate limiting đơn giản — in-memory, 30 req/phút/IP
# ---------------------------------------------------------------------------

_request_log: dict[str, list[float]] = defaultdict(list)
RATE_LIMIT = 30
WINDOW = 60.0


def _check_rate(ip: str) -> None:
    now = time.time()
    timestamps = [t for t in _request_log[ip] if now - t < WINDOW]
    if len(timestamps) >= RATE_LIMIT:
        raise HTTPException(
            status_code=429,
            detail="Quá nhiều yêu cầu. Vui lòng chờ 1 phút rồi thử lại.",
        )
    timestamps.append(now)
    _request_log[ip] = timestamps


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

class HistoryMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    message: str = ""
    image: str = ""
    history: list[HistoryMessage] = []


@router.post("/api/chat")
async def api_chat(req: ChatRequest, request: Request):
    _check_rate(request.client.host)

    question = req.message.strip()
    image    = req.image.strip()

    if not question and not image:
        return JSONResponse({"answer": ""})

    context = rag_module.rag.search(question) if question else ""
    history = [{"role": m.role, "content": m.content} for m in req.history]

    try:
        answer = await llm.chat(
            question=question,
            context=context,
            image_base64=image,
            history=history,
        )
    except Exception:
        answer = "Xin lỗi, hệ thống đang bận. Vui lòng thử lại sau hoặc gọi đường dây nóng khuyến nông: 1900-9008."

    return JSONResponse({"answer": answer})


# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------

class FeedbackRequest(BaseModel):
    question: str = ""
    answer: str   = ""
    rating: int


@router.post("/api/feedback")
async def api_feedback(req: FeedbackRequest):
    if req.rating not in (1, -1):
        raise HTTPException(status_code=422, detail="rating phải là 1 hoặc -1")
    save_feedback(
        ts=datetime.now().isoformat(timespec="seconds"),
        rating=req.rating,
        question=req.question,
        answer=req.answer,
    )
    return JSONResponse({"ok": True})
