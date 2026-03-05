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
from app.database import save_feedback, save_question, get_premium_quota, consume_premium, redeem_code

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

    # Giới hạn ngày (tổng) — kiểm tra premium trước
    date, count = _daily_log.get(ip, ("", 0))
    if date == today and count >= DAILY_LIMIT:
        # Hết quota miễn phí → thử dùng premium
        if not consume_premium(ip, is_image=False):
            raise HTTPException(
                status_code=429,
                detail="QUOTA_EXCEEDED",
            )
    else:
        _daily_log[ip] = (today, count + 1) if date == today else (today, 1)

    # Giới hạn ảnh/ngày
    if has_image:
        idate, icount = _image_log.get(ip, ("", 0))
        if idate == today and icount >= IMAGE_LIMIT:
            if not consume_premium(ip, is_image=True):
                raise HTTPException(
                    status_code=429,
                    detail="IMAGE_QUOTA_EXCEEDED",
                )
        else:
            _image_log[ip] = (today, icount + 1) if idate == today else (today, 1)

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


class RedeemRequest(BaseModel):
    code: str

@router.post("/api/redeem")
async def api_redeem(req: RedeemRequest, request: Request):
    result = redeem_code(req.code.strip(), request.client.host)
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["reason"])
    return JSONResponse(result)

@router.get("/api/quota")
async def api_quota(request: Request):
    ip    = request.client.host
    today = datetime.now().strftime("%Y-%m-%d")
    _, used_q = _daily_log.get(ip, ("", 0))
    _, used_i = _image_log.get(ip, ("", 0))
    premium   = get_premium_quota(ip)
    return JSONResponse({
        "free":    {"requests": max(0, DAILY_LIMIT - used_q), "images": max(0, IMAGE_LIMIT - used_i)},
        "premium": premium,
    })

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
