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
from app.services.embeddings import vector_search, EMBED_ENABLED
from app.database import (
    save_feedback, save_question, get_premium_quota, consume_premium, redeem_code,
    save_user_region, get_user_region, save_community_tip, save_image_submission,
    add_bonus_quota, update_tip_ai_result, approve_tip, reject_tip,
)
from datetime import datetime as _dt
from app.services.weather import get_weather, REGION_NAMES

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
    region: str = ""
    lat: float = 0.0
    lon: float = 0.0


_ERROR_MESSAGES = {
    "timeout":  "Hệ thống phản hồi chậm, vui lòng thử lại sau ít phút.",
    "connect":  "Không kết nối được đến máy chủ AI. Kiểm tra mạng và thử lại.",
    "auth":     "Lỗi xác thực API. Vui lòng liên hệ quản trị viên.",
    "quota":    "Hệ thống AI đang quá tải. Vui lòng thử lại sau vài phút.",
    "server":   "Máy chủ AI đang gặp sự cố. Vui lòng thử lại sau.",
    "response": "Nhận được phản hồi không hợp lệ từ AI. Vui lòng thử lại.",
    "http":     "Lỗi kết nối đến AI. Vui lòng thử lại sau.",
}


@router.post("/api/chat")
async def api_chat(req: ChatRequest, request: Request):
    question  = req.message.strip()
    image     = req.image.strip()
    device_id = _get_device_id(request)

    _check_rate(device_id, request.client.host, has_image=bool(image))

    if not question and not image:
        return JSONResponse({"answer": ""})

    # Lấy region: từ request → DB → ""
    region = req.region.strip()
    if not region:
        region = get_user_region(device_id)
    region_name = REGION_NAMES.get(region, "")

    # Lấy thời tiết bất đồng bộ (không block nếu lỗi)
    weather = await get_weather(region=region, lat=req.lat, lon=req.lon)

    # Log câu hỏi để analytics
    if question:
        save_question(
            ts=datetime.now().isoformat(timespec="seconds"),
            question=question,
            has_image=bool(image),
        )

    if question:
        if EMBED_ENABLED:
            results = await vector_search(question)
            context = "\n\n---\n\n".join(
                f"[{r['source']}] {r['title']}\n{r['content']}" for r in results
            ) if results else rag_module.rag.search(question)  # fallback BM25
        else:
            context = rag_module.rag.search(question)
    else:
        context = ""
    history = [{"role": m.role, "content": m.content} for m in req.history]

    try:
        answer = await llm.chat(
            question=question,
            context=context,
            image_base64=image,
            history=history,
            region=region_name,
            weather=weather,
        )
    except LLMError as e:
        log.error("LLMError [%s]", e)
        return JSONResponse({"answer": _ERROR_MESSAGES.get(str(e), "Lỗi không xác định. Vui lòng thử lại.")})
    except Exception as e:
        log.exception("llm.chat unexpected error: %s", e)
        return JSONResponse({"answer": "Lỗi hệ thống không xác định. Vui lòng thử lại sau ít phút."})

    # Lưu chẩn đoán vào dataset nếu có ảnh (không lưu ảnh để tiết kiệm DB)
    submission_id = None
    if image:
        try:
            submission_id = save_image_submission(device_id, answer)
        except Exception:
            pass  # không block response nếu lưu lỗi

    return JSONResponse({"answer": answer, "submission_id": submission_id})


# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------

class FeedbackRequest(BaseModel):
    question: str = ""
    answer: str   = ""
    rating: int
    reason: str = ""          # giải thích khi bấm 👎
    submission_id: int | None = None


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
async def api_feedback(req: FeedbackRequest, request: Request):
    if req.rating not in (1, -1):
        raise HTTPException(status_code=422, detail="rating phải là 1 hoặc -1")

    # Lưu feedback (nếu có reason thì gắn vào câu hỏi)
    question_with_reason = req.question
    if req.reason.strip():
        question_with_reason = f"{req.question}\n[Lý do 👎: {req.reason.strip()}]"
    save_feedback(
        ts=datetime.now().isoformat(timespec="seconds"),
        rating=req.rating,
        question=question_with_reason,
        answer=req.answer,
    )

    # Cập nhật feedback cho ảnh nếu có submission_id
    if req.submission_id:
        try:
            from app.database import update_image_feedback
            update_image_feedback(req.submission_id, req.rating)
        except Exception:
            pass

    # Thưởng quota: 👎 + lý do = +2, còn lại = +1
    device_id = _get_device_id(request)
    has_reason = bool(req.reason.strip())
    bonus = 2 if (req.rating == -1 and has_reason) else 1
    add_bonus_quota(device_id, bonus)

    return JSONResponse({"ok": True, "bonus": bonus})


# ---------------------------------------------------------------------------
# Correction — người dùng sửa câu trả lời sai
# ---------------------------------------------------------------------------

class CorrectionRequest(BaseModel):
    question:     str = ""
    wrong_answer: str = ""
    correction:   str = ""
    reason:       str = ""
    submission_id: int | None = None


class CorrectChatRequest(BaseModel):
    question:     str = ""
    wrong_answer: str = ""
    user_message: str = ""
    turns:        list[HistoryMessage] = []
    submission_id: int | None = None


@router.post("/api/correct-chat")
async def api_correct_chat(req: CorrectChatRequest, request: Request):
    device_id = _get_device_id(request)

    from app.services.llm import correct_chat_turn
    turns = [{"role": m.role, "content": m.content} for m in req.turns]
    result = await correct_chat_turn(
        question=req.question,
        wrong_answer=req.wrong_answer,
        turns=turns,
        user_message=req.user_message,
    )

    if result["action"] == "save" and result["corrected_answer"]:
        title   = f"Sửa: {req.question[:80]}"
        content = f"Câu hỏi: {req.question}\n\nThông tin đúng:\n{result['corrected_answer']}"
        tip_id  = save_community_tip(
            device_id=device_id, title=title, content=content,
            category="correction", region="",
        )
        update_tip_ai_result(tip_id, result["confidence"], "Verified via conversational correction", "approve")
        approve_tip(tip_id)
        _save_tip_as_doc(tip_id, title, result["corrected_answer"])

        save_feedback(
            ts=_dt.now().isoformat(timespec="seconds"),
            rating=-1,
            question=f"{req.question}\n[Sửa qua hội thoại]",
            answer=req.wrong_answer,
        )
        if req.submission_id:
            try:
                from app.database import update_image_feedback
                update_image_feedback(req.submission_id, -1)
            except Exception:
                pass

        add_bonus_quota(device_id, 3)
        result["bonus"] = 3

    return JSONResponse(result)


@router.post("/api/correct")
async def api_correct(req: CorrectionRequest, request: Request):
    device_id = _get_device_id(request)

    # Luôn lưu feedback -1 kèm lý do
    save_feedback(
        ts=_dt.now().isoformat(timespec="seconds"),
        rating=-1,
        question=f"{req.question}\n[Sửa: {req.correction[:200]}]" if req.correction else req.question,
        answer=req.wrong_answer,
    )
    if req.submission_id:
        try:
            from app.database import update_image_feedback
            update_image_feedback(req.submission_id, -1)
        except Exception:
            pass

    if not req.correction.strip():
        add_bonus_quota(device_id, 2)
        return JSONResponse({"verified": False, "bonus": 2})

    # Kiểm chứng thông tin sửa bằng Sonnet
    from app.services.llm import verify_and_correct
    try:
        result = await verify_and_correct(req.question, req.wrong_answer, req.correction)
    except Exception:
        result = {"verified": False, "confidence": 0.0, "corrected_answer": "", "reason": ""}

    if result["verified"]:
        # Lưu vào KB ngay
        title = f"Sửa: {req.question[:80]}"
        content = f"Câu hỏi: {req.question}\n\nThông tin đúng:\n{req.correction}\n\nGiải thích:\n{result['corrected_answer']}"
        tip_id = save_community_tip(
            device_id=device_id, title=title, content=content,
            category="correction", region="",
        )
        update_tip_ai_result(tip_id, result["confidence"], result["reason"], "approve")
        approve_tip(tip_id)
        _save_tip_as_doc(tip_id, title, content)
        add_bonus_quota(device_id, 3)  # thưởng nhiều hơn vì đóng góp có giá trị
        return JSONResponse({
            "verified":         True,
            "corrected_answer": result["corrected_answer"],
            "confidence":       result["confidence"],
            "bonus":            3,
        })

    add_bonus_quota(device_id, 2)
    return JSONResponse({
        "verified": False,
        "reason":   result.get("reason", ""),
        "bonus":    2,
    })


# ---------------------------------------------------------------------------
# User region
# ---------------------------------------------------------------------------

class RegionRequest(BaseModel):
    region: str

@router.post("/api/user-region")
async def api_save_region(req: RegionRequest, request: Request):
    from app.services.weather import REGION_NAMES
    if req.region not in REGION_NAMES:
        raise HTTPException(status_code=422, detail="Vùng không hợp lệ")
    device_id = _get_device_id(request)
    save_user_region(device_id, req.region)
    return JSONResponse({"ok": True})


@router.get("/api/regions")
async def api_regions():
    from app.services.weather import REGION_NAMES
    return JSONResponse({"regions": [{"key": k, "name": v} for k, v in REGION_NAMES.items()]})


# ---------------------------------------------------------------------------
# Community tips
# ---------------------------------------------------------------------------

class CommunityTipRequest(BaseModel):
    title: str
    content: str
    category: str = ""
    region: str = ""

TIP_BONUS = 5  # lượt hỏi thưởng khi gửi kinh nghiệm cộng đồng

_DATA_DIR = __import__("pathlib").Path(__file__).parent.parent.parent / "data"


def _save_tip_as_doc(tip_id: int, title: str, content: str) -> None:
    """Lưu tip đã duyệt thành file .md trong knowledge base."""
    import re, unicodedata
    from app.services import rag as rag_module
    name = unicodedata.normalize("NFD", title.lower())
    name = "".join(c for c in name if unicodedata.category(c) != "Mn")
    name = re.sub(r"[^\w\s-]", "", name)
    name = re.sub(r"[\s-]+", "_", name).strip("_")[:60] or "community"
    out = _DATA_DIR / f"{name}.md"
    out.write_text(
        f"# {title}\n\n> Nguồn: Kinh nghiệm cộng đồng (#{tip_id})\n\n{content}\n",
        encoding="utf-8",
    )
    rag_module.rag.reload()


@router.post("/api/community-tips")
async def api_submit_tip(req: CommunityTipRequest, request: Request):
    if len(req.title.strip()) < 5 or len(req.content.strip()) < 20:
        raise HTTPException(status_code=422, detail="Tiêu đề hoặc nội dung quá ngắn")
    device_id = _get_device_id(request)
    title   = req.title.strip()
    content = req.content.strip()

    # Lưu tip trước (status mặc định 'pending')
    tip_id = save_community_tip(
        device_id=device_id,
        title=title,
        content=content,
        category=req.category.strip(),
        region=req.region.strip(),
    )

    # AI verification bằng model mạnh
    from app.services.llm import verify_tip
    try:
        verdict = await verify_tip(title, content, req.category.strip())
    except Exception:
        verdict = {"action": "review", "confidence": 0.5, "reason": "Lỗi kiểm chứng tự động"}

    action     = verdict.get("action", "review")
    confidence = verdict.get("confidence", 0.5)
    reason     = verdict.get("reason", "")

    # Cập nhật kết quả AI vào DB
    update_tip_ai_result(tip_id, confidence, reason, action)

    if action == "reject":
        # AI chắc chắn sai — từ chối, không thưởng
        reject_tip(tip_id, reason)
        return JSONResponse({
            "ok": False, "rejected": True,
            "reason": reason or "Thông tin chưa phù hợp hoặc không liên quan đến cà chua.",
        })

    # approve hoặc review → thưởng quota
    add_bonus_quota(device_id, TIP_BONUS)

    if action == "approve":
        # AI tự tin cao → đưa vào KB ngay
        approve_tip(tip_id)
        _save_tip_as_doc(tip_id, title, content)
        return JSONResponse({"ok": True, "id": tip_id, "bonus": TIP_BONUS, "auto_approved": True})

    # review → chờ admin
    return JSONResponse({"ok": True, "id": tip_id, "bonus": TIP_BONUS, "pending_review": True})
