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
from app.database import save_feedback, save_question

router = APIRouter()

# ---------------------------------------------------------------------------
# Rate limiting đơn giản — in-memory, 30 req/phút/IP
# ---------------------------------------------------------------------------

_request_log: dict[str, list[float]] = defaultdict(list)
_daily_log:   dict[str, tuple[str, int]] = {}  # ip -> (date, count)
_image_log:   dict[str, tuple[str, int]] = {}  # ip -> (date, count)

RATE_LIMIT   = 20   # request/phút/IP
DAILY_LIMIT  = 5    # câu hỏi/ngày/IP
IMAGE_LIMIT  = 2    # ảnh/ngày/IP
WINDOW       = 60.0


def _check_rate(ip: str, has_image: bool = False) -> None:
    now   = time.time()
    today = datetime.now().strftime("%Y-%m-%d")

    # Giới hạn ngày (tổng)
    date, count = _daily_log.get(ip, ("", 0))
    if date == today:
        if count >= DAILY_LIMIT:
            raise HTTPException(
                status_code=429,
                detail="Bạn đã dùng hết 5 câu hỏi miễn phí hôm nay. Vui lòng quay lại vào ngày mai nhé! 🍅",
            )
        _daily_log[ip] = (today, count + 1)
    else:
        _daily_log[ip] = (today, 1)

    # Giới hạn ảnh/ngày
    if has_image:
        idate, icount = _image_log.get(ip, ("", 0))
        if idate == today:
            if icount >= IMAGE_LIMIT:
                raise HTTPException(
                    status_code=429,
                    detail="Bạn đã gửi đủ 2 ảnh miễn phí hôm nay. Vui lòng quay lại vào ngày mai nhé! 📷",
                )
            _image_log[ip] = (today, icount + 1)
        else:
            _image_log[ip] = (today, 1)

    # Giới hạn phút
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
    question = req.message.strip()
    image    = req.image.strip()

    _check_rate(request.client.host, has_image=bool(image))

    if not question and not image:
        return JSONResponse({"answer": ""})

    # Log câu hỏi để analytics
    if question:
        save_question(
            ts=datetime.now().isoformat(timespec="seconds"),
            question=question,
            has_image=bool(image),
        )

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
