"""
Chat router — /api/chat, /api/feedback
Có rate limiting: tối đa 30 request/phút mỗi IP.
"""

import logging
import time
from collections import defaultdict
from datetime import datetime

from fastapi import APIRouter, Request, HTTPException

log = logging.getLogger(__name__)
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.services import llm, rag as rag_module
from app.services.llm import LLMError
from app.database import save_feedback, save_question, get_premium_quota, consume_premium, redeem_code

router = APIRouter()

# ---------------------------------------------------------------------------
# Rate limiting đơn giản — in-memory, 30 req/phút/IP
# ---------------------------------------------------------------------------

_request_log: dict[str, list[float]] = defaultdict(list)
_daily_log:   dict[str, tuple[str, int]] = {}  # device_id -> (date, count)
_image_log:   dict[str, tuple[str, int]] = {}  # device_id -> (date, count)
_ip_daily_log: dict[str, tuple[str, int]] = {} # ip -> (date, count) — chặn abuse

RATE_LIMIT   = 20   # request/phút/device
DAILY_LIMIT  = 5    # câu hỏi/ngày/device (cookie)
IMAGE_LIMIT  = 2    # ảnh/ngày/device (cookie)
IP_DAY_LIMIT = 15   # tổng câu hỏi/ngày/IP — chặn incognito/xóa cookie
WINDOW       = 60.0


def _get_device_id(request: Request) -> str:
    """Cookie 'did' là định danh chính; fallback về IP nếu chưa có cookie."""
    return request.cookies.get("did") or request.client.host


def _check_rate(device_id: str, ip: str, has_image: bool = False) -> None:
    now   = time.time()
    today = datetime.now().strftime("%Y-%m-%d")

    # Lớp 2: chặn cứng theo IP (bảo vệ khỏi incognito/xóa cookie)
    ip_date, ip_count = _ip_daily_log.get(ip, ("", 0))
    if ip_date == today and ip_count >= IP_DAY_LIMIT:
        raise HTTPException(status_code=429, detail="QUOTA_EXCEEDED")
    _ip_daily_log[ip] = (today, ip_count + 1) if ip_date == today else (today, 1)

    # Lớp 1: giới hạn theo device (cookie)
    date, count = _daily_log.get(device_id, ("", 0))
    if date == today and count >= DAILY_LIMIT:
        # Hết quota miễn phí → thử dùng premium
        if not consume_premium(device_id, is_image=False):
            raise HTTPException(status_code=429, detail="QUOTA_EXCEEDED")
    else:
        _daily_log[device_id] = (today, count + 1) if date == today else (today, 1)

    # Giới hạn ảnh/ngày
    if has_image:
        idate, icount = _image_log.get(device_id, ("", 0))
        if idate == today and icount >= IMAGE_LIMIT:
            if not consume_premium(device_id, is_image=True):
                raise HTTPException(status_code=429, detail="IMAGE_QUOTA_EXCEEDED")
        else:
            _image_log[device_id] = (today, icount + 1) if idate == today else (today, 1)

    # Giới hạn phút
    timestamps = [t for t in _request_log[device_id] if now - t < WINDOW]
    if len(timestamps) >= RATE_LIMIT:
        raise HTTPException(
            status_code=429,
            detail="Quá nhiều yêu cầu. Vui lòng chờ 1 phút rồi thử lại.",
        )
    timestamps.append(now)
    _request_log[device_id] = timestamps


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

    _check_rate(_get_device_id(request), request.client.host, has_image=bool(image))

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

    _ERROR_MESSAGES = {
        "timeout":  "Hệ thống phản hồi chậm, vui lòng thử lại sau ít phút.",
        "connect":  "Không kết nối được đến máy chủ AI. Kiểm tra mạng và thử lại.",
        "auth":     "Lỗi xác thực API. Vui lòng liên hệ quản trị viên.",
        "quota":    "Hệ thống AI đang quá tải. Vui lòng thử lại sau vài phút.",
        "server":   "Máy chủ AI đang gặp sự cố. Vui lòng thử lại sau.",
        "response": "Nhận được phản hồi không hợp lệ từ AI. Vui lòng thử lại.",
        "http":     "Lỗi kết nối đến AI. Vui lòng thử lại sau.",
    }

    try:
        answer = await llm.chat(
            question=question,
            context=context,
            image_base64=image,
            history=history,
        )
    except LLMError as e:
        log.error("LLMError [%s]", e)
        answer = _ERROR_MESSAGES.get(str(e), "Lỗi không xác định. Vui lòng thử lại.")
    except Exception as e:
        log.exception("llm.chat unexpected error: %s", e)
        answer = "Lỗi hệ thống không xác định. Vui lòng thử lại hoặc gọi 1900-9008."

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
    result = redeem_code(req.code.strip(), _get_device_id(request))
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["reason"])
    return JSONResponse(result)

@router.get("/api/quota")
async def api_quota(request: Request):
    ip    = _get_device_id(request)
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
