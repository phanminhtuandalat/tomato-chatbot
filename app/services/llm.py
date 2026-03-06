"""
LLM Service — gọi OpenRouter API.
Hỗ trợ: text, hình ảnh (vision), lịch sử hội thoại, trích xuất kiến thức từ ảnh.
"""

import hashlib
import logging
import time
from datetime import datetime
import httpx
from app.config import OPENROUTER_API_KEY, OPENROUTER_MODEL, OPENROUTER_MODEL_FAST

log = logging.getLogger(__name__)


SYSTEM_PROMPT_TEMPLATE = """Bạn là chuyên gia tư vấn trồng cà chua cho nông dân Việt Nam. Hiện tại: tháng {month}/{year}.

Quy tắc trả lời:
- Tiếng Việt, ngắn gọn, thực tế
- Khi có "Tài liệu tham khảo": BẮT BUỘC dùng số liệu trong đó (mật độ, khoảng cách, liều lượng...). KHÔNG được thay bằng số liệu khác dù quen thuộc hơn
- Khi KHÔNG có tài liệu tham khảo: nói rõ "Theo kinh nghiệm chung..." và khuyên tra thêm
- Nêu cụ thể: tên thuốc, liều lượng, thời điểm phun/bón
- KHÔNG bịa đặt thông tin — nếu không chắc, nói rõ "Tôi không chắc chắn về điều này"
- Bệnh nặng hoặc không xác định được → khuyên gọi 1900-9008 hoặc gặp cán bộ khuyến nông

Khi câu hỏi về bệnh/triệu chứng/sâu hại, phân tích theo thứ tự:
1. Mô tả triệu chứng đang thấy
2. Nguyên nhân có thể (bệnh, sâu, thiếu dinh dưỡng, điều kiện thời tiết)
3. Chẩn đoán cụ thể (nếu đủ thông tin) hoặc nói "cần xem thêm" nếu chưa rõ
4. Giải pháp: tên thuốc/biện pháp, liều lượng, thời điểm xử lý{region_line}{weather_line}"""

EXTRACT_PROMPT = """Bạn là chuyên gia nông nghiệp. Hãy đọc ảnh này và trích xuất toàn bộ kiến thức nông nghiệp có trong đó.

Yêu cầu:
- Viết bằng tiếng Việt, rõ ràng, đầy đủ
- Giữ nguyên các số liệu, tên thuốc, liều lượng
- Tổ chức thành các mục rõ ràng với tiêu đề
- Nếu là ảnh bệnh/sâu: mô tả triệu chứng, nguyên nhân, cách xử lý
- Nếu là bảng/infographic: chuyển thành văn bản có cấu trúc
- Nếu là trang sách: trích xuất toàn bộ nội dung

Chỉ trả về nội dung đã trích xuất, không thêm lời mở đầu hay kết."""

IMAGE_DIAGNOSIS_PROMPT = """Phân tích ảnh cây cà chua theo các bước sau:

1. **Nhận diện**: Đây có phải ảnh cây cà chua hoặc vườn cà chua không? Nếu không phải → nói rõ và dừng.
2. **Mô tả triệu chứng**: Màu sắc, hình dạng, vị trí trên cây (lá/thân/quả/rễ), mức độ lan rộng
3. **Chẩn đoán**: Bệnh, sâu hại, hoặc rối loạn sinh lý cụ thể. Nếu chưa đủ thông tin → nói "Tôi không chắc chắn, cần xem thêm"
4. **Giải pháp**: Tên thuốc/biện pháp, liều lượng, thời điểm xử lý, lưu ý

Trả lời bằng tiếng Việt, thực tế, cụ thể."""


def _system_prompt(region: str = "", weather: str = "") -> str:
    now = datetime.now()
    region_line = f"\n\nNgười dùng trồng ở {region}. Điều chỉnh lời khuyên phù hợp điều kiện địa phương." if region else ""
    weather_line = f"\nThời tiết hiện tại: {weather}. Lưu ý khi tư vấn phòng bệnh và tưới nước." if weather else ""
    return SYSTEM_PROMPT_TEMPLATE.format(month=now.month, year=now.year, region_line=region_line, weather_line=weather_line)


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://chatbot-ca-chua.app",
        "X-Title": "Chatbot Ca Chua",
    }


# ---------------------------------------------------------------------------
# Giới hạn token — bảo vệ chi phí
# ---------------------------------------------------------------------------

MAX_QUESTION_CHARS  = 400   # ~100 token
MAX_CONTEXT_CHARS   = 1800  # ~450 token (4 chunks rút gọn)
MAX_HISTORY_MSGS    = 6     # 3 lượt gần nhất
MAX_HISTORY_CHARS   = 250   # mỗi message tối đa ~60 token
MAX_TOKENS_RESPONSE = 700   # đủ cho câu trả lời nông nghiệp thực tế
MAX_IMAGE_PX        = 768   # resize ảnh xuống tối đa 768px, JPEG q=80


def _compress_image(data_url: str) -> str:
    """Resize + nén ảnh xuống MAX_IMAGE_PX trước khi gửi lên LLM."""
    try:
        import base64, io
        from PIL import Image

        header, b64 = data_url.split(",", 1)
        raw = base64.b64decode(b64)
        img = Image.open(io.BytesIO(raw)).convert("RGB")

        if max(img.size) > MAX_IMAGE_PX:
            img.thumbnail((MAX_IMAGE_PX, MAX_IMAGE_PX), Image.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=80, optimize=True)
        compressed = base64.b64encode(buf.getvalue()).decode()
        return f"data:image/jpeg;base64,{compressed}"
    except Exception:
        return data_url  # fallback: gửi nguyên


def _trim_history(history: list[dict]) -> list[dict]:
    """Giữ lại MAX_HISTORY_MSGS tin nhắn gần nhất, cắt nội dung dài."""
    recent = history[-MAX_HISTORY_MSGS:]
    trimmed = []
    for msg in recent:
        content = msg["content"]
        if isinstance(content, str) and len(content) > MAX_HISTORY_CHARS:
            content = content[:MAX_HISTORY_CHARS] + "…"
        trimmed.append({"role": msg["role"], "content": content})
    return trimmed


# ---------------------------------------------------------------------------
# Answer cache — tránh gọi API cho cùng câu hỏi
# ---------------------------------------------------------------------------

_cache: dict[str, tuple[str, float]] = {}  # key -> (answer, timestamp)
_CACHE_TTL  = 1800   # 30 phút
_CACHE_MAX  = 300    # tối đa 300 entries


def _cache_key(question: str, context: str) -> str:
    raw = question.strip().lower() + "|" + context[:200]
    return hashlib.md5(raw.encode()).hexdigest()


def _cache_get(key: str) -> str | None:
    entry = _cache.get(key)
    if entry and time.time() - entry[1] < _CACHE_TTL:
        return entry[0]
    return None


def _cache_set(key: str, answer: str) -> None:
    if len(_cache) >= _CACHE_MAX:
        oldest = min(_cache, key=lambda k: _cache[k][1])
        del _cache[oldest]
    _cache[key] = (answer, time.time())


class LLMError(Exception):
    """Lỗi có thông báo thân thiện để hiển thị cho người dùng."""


async def _call(messages: list[dict], model: str = OPENROUTER_MODEL_FAST,
                max_tokens: int = MAX_TOKENS_RESPONSE) -> str:
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=_headers(),
                json={"model": model, "max_tokens": max_tokens, "messages": messages},
            )
    except httpx.TimeoutException:
        raise LLMError("timeout")
    except httpx.ConnectError:
        raise LLMError("connect")

    if response.status_code == 401:
        raise LLMError("auth")
    if response.status_code in (402, 429):
        raise LLMError("quota")
    if response.status_code >= 500:
        raise LLMError("server")

    try:
        response.raise_for_status()
    except httpx.HTTPStatusError:
        log.error("OpenRouter HTTP %s: %s", response.status_code, response.text[:500])
        raise LLMError("http")

    try:
        data = response.json()
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        log.error("OpenRouter response thiếu choices: %s", response.text[:500])
        raise LLMError("response")


async def chat(
    question: str,
    context: str = "",
    image_base64: str = "",
    history: list[dict] | None = None,
    region: str = "",
    weather: str = "",
) -> str:
    """Trả lời câu hỏi của nông dân, có kèm context RAG và lịch sử hội thoại."""
    question = question[:MAX_QUESTION_CHARS]
    context  = context[:MAX_CONTEXT_CHARS]

    if image_base64:
        # Ảnh: dùng model mạnh (Sonnet) + không cache (mỗi ảnh khác nhau)
        image_base64 = _compress_image(image_base64)
        text = IMAGE_DIAGNOSIS_PROMPT
        if question:
            text += f"\n\nNgười dùng hỏi thêm: {question}"
        if context:
            text += f"\n\n---\nTài liệu tham khảo:\n{context}"
        user_content = [
            {"type": "image_url", "image_url": {"url": image_base64}},
            {"type": "text", "text": text},
        ]
        messages = [{"role": "system", "content": _system_prompt(region, weather)}]
        if history:
            messages.extend(_trim_history(history))
        messages.append({"role": "user", "content": user_content})
        return await _call(messages, model=OPENROUTER_MODEL)

    # Text: kiểm tra cache trước (chỉ cache khi không có history — độc lập ngữ cảnh)
    no_history = not history or len(history) == 0
    cache_key  = _cache_key(question, context) if no_history else None
    if cache_key:
        cached = _cache_get(cache_key)
        if cached:
            return cached

    if context:
        user_content = (
            f"Câu hỏi: {question}\n\n"
            f"---\nTài liệu tham khảo (dùng số liệu này, không thay bằng số liệu khác):\n{context}\n---\n\n"
            f"Trả lời dựa trên tài liệu trên. Nếu tài liệu có số liệu cụ thể (mật độ, khoảng cách, liều lượng), trích dẫn đúng."
        )
    else:
        user_content = question

    messages = [{"role": "system", "content": _system_prompt(region, weather)}]
    if history:
        messages.extend(_trim_history(history))
    messages.append({"role": "user", "content": user_content})

    # Text: dùng model nhanh/rẻ (Haiku)
    answer = await _call(messages, model=OPENROUTER_MODEL_FAST)

    if cache_key:
        _cache_set(cache_key, answer)

    return answer


async def verify_and_correct(question: str, wrong_answer: str, correction: str) -> dict:
    """
    Kiểm chứng thông tin sửa của người dùng và viết lại câu trả lời đúng.
    Trả về: {verified, confidence, corrected_answer, reason}
    """
    from app.services.rag import rag
    kb_context = rag.search(f"{question} {correction}", top_k=3)
    context_section = (
        f"\nTài liệu tham khảo:\n{kb_context[:2000]}"
        if kb_context else "\n(Không có tài liệu liên quan)"
    )

    prompt = f"""Người dùng phát hiện câu trả lời AI sai và cung cấp thông tin đúng hơn.

Câu hỏi gốc: {question[:300]}
Câu trả lời AI (bị báo sai): {wrong_answer[:400]}
Thông tin đúng theo người dùng: {correction[:500]}
{context_section}

Nhiệm vụ:
1. Kiểm tra thông tin người dùng cung cấp có đúng về kỹ thuật nông nghiệp/cà chua không
2. Nếu đúng (confidence >= 0.70): viết lại câu trả lời hoàn chỉnh, thực tế cho câu hỏi gốc
3. Nếu không đủ cơ sở xác nhận: nói rõ lý do

Trả về JSON (chỉ JSON):
{{"verified": true, "confidence": 0.9, "corrected_answer": "câu trả lời đầy đủ...", "reason": "lý do ngắn"}}"""

    raw = await _call([{"role": "user", "content": prompt}],
                      model=OPENROUTER_MODEL, max_tokens=600)
    import json, re
    try:
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        if m:
            data = json.loads(m.group())
            confidence = max(0.0, min(1.0, float(data.get("confidence", 0.0))))
            return {
                "verified":          confidence >= 0.7 and bool(data.get("verified", False)),
                "confidence":        confidence,
                "corrected_answer":  str(data.get("corrected_answer", ""))[:1000],
                "reason":            str(data.get("reason", ""))[:300],
            }
    except (json.JSONDecodeError, ValueError, KeyError) as e:
        log.warning("verify_and_correct parse error: %s | raw: %.200s", e, raw)

    return {"verified": False, "confidence": 0.0, "corrected_answer": "", "reason": "Không thể kiểm chứng"}


async def verify_tip(title: str, content: str, category: str) -> dict:
    """
    Kiểm chứng community tip bằng Sonnet, so với knowledge base hiện tại.
    Trả về: {valid, confidence, reason, action}
    action: "approve" (>=0.85) | "review" (0.4-0.85) | "reject" (<0.4)
    """
    from app.services.rag import rag
    kb_context = rag.search(f"{title} {content}", top_k=3)
    context_section = (
        f"\nTài liệu tham khảo trong hệ thống:\n{kb_context[:2000]}"
        if kb_context else "\n(Không có tài liệu liên quan trong knowledge base)"
    )

    prompt = f"""Bạn là chuyên gia nông nghiệp Việt Nam. Kiểm chứng thông tin dưới đây.

Thông tin cần kiểm chứng:
Tiêu đề: {title[:200]}
Danh mục: {category}
Nội dung: {content[:800]}
{context_section}

Đánh giá theo 4 tiêu chí:
1. Có phải kiến thức về cà chua / rau màu hợp lệ không?
2. Có mâu thuẫn với tài liệu tham khảo không?
3. Số liệu (liều lượng, mật độ, khoảng cách) có bất thường không?
4. Có phải spam hoặc quảng cáo không?

Trả về JSON (chỉ JSON, không giải thích):
{{"valid": true, "confidence": 0.9, "reason": "lý do ngắn gọn tiếng Việt", "action": "approve"}}

Quy tắc action:
- "approve": confidence >= 0.85, thông tin đúng kỹ thuật, không mâu thuẫn KB
- "review": confidence 0.40–0.85, cần người kiểm tra thêm
- "reject": confidence < 0.40, sai kỹ thuật / không liên quan / spam"""

    raw = await _call([{"role": "user", "content": prompt}],
                      model=OPENROUTER_MODEL, max_tokens=200)
    import json, re
    try:
        m = re.search(r'\{[^{}]+\}', raw, re.DOTALL)
        if m:
            data = json.loads(m.group())
            confidence = max(0.0, min(1.0, float(data.get("confidence", 0.5))))
            action = data.get("action", "review")
            if action not in ("approve", "review", "reject"):
                action = "approve" if confidence >= 0.85 else ("reject" if confidence < 0.4 else "review")
            return {
                "valid":      bool(data.get("valid", True)),
                "confidence": confidence,
                "reason":     str(data.get("reason", ""))[:500],
                "action":     action,
            }
    except (json.JSONDecodeError, ValueError, KeyError) as e:
        log.warning("verify_tip parse error: %s | raw: %.200s", e, raw)

    return {"valid": True, "confidence": 0.5, "reason": "Không thể kiểm chứng tự động", "action": "review"}


async def generate_correction_form(question: str, wrong_answer: str) -> dict:
    """
    Phân tích từng điểm sai trong câu trả lời, tạo câu hỏi trắc nghiệm sát với nội dung đó.
    Trả về: {intro, questions: [{id, type, label, options?, placeholder?, unit?}]}
    """
    prompt = f"""Bạn là chuyên gia nông nghiệp. Người dùng báo câu trả lời AI sai.

Câu hỏi: {question[:200]}
Câu trả lời AI (bị báo sai): {wrong_answer[:400]}

Bước 1 — Phân tích: Liệt kê từng thông tin cụ thể trong câu trả lời trên có thể sai:
ví dụ: "mật độ 20,000 cây/ha", "khoảng cách 50x50cm", "bón 200kg/ha", "dùng thuốc X"...

Bước 2 — Tạo câu hỏi: Với mỗi thông tin có thể sai, tạo 1 câu hỏi trắc nghiệm:
- Đưa GIÁ TRỊ SAI (từ câu trả lời AI) vào làm 1 option, để người dùng dễ nhận ra và chọn đúng
- Thêm 2-3 giá trị đúng phổ biến làm option khác
- Luôn có option "Khác" để người dùng tự nhập

Trả về JSON (chỉ JSON, không giải thích):
{{"intro":"Câu trả lời có thể sai ở chỗ nào? Bà con chọn thông tin đúng nhé:","questions":[
  {{"id":"q1","type":"choice","label":"Mật độ trồng là bao nhiêu cây/ha?","options":["20,000 cây/ha (AI trả lời)","33,000 cây/ha","40,000 cây/ha","Khác"]}},
  {{"id":"q2","type":"choice","label":"Khoảng cách trồng hàng × cây?","options":["50×50cm (AI trả lời)","60×40cm","70×50cm","Khác"]}},
  {{"id":"q3","type":"text","label":"Thông tin nào khác còn sai? (tuỳ chọn)","placeholder":"Ví dụ: liều phân bón, tên thuốc..."}}
]}}

Quy tắc:
- Mỗi câu hỏi cho 1 điểm thông tin cụ thể (số liệu, tên thuốc, kỹ thuật)
- Ghi rõ "(AI trả lời)" sau giá trị sai để người dùng dễ nhận biết
- type "choice": khi có giá trị cụ thể để so sánh
- type "number": khi cần nhập số chính xác (kèm unit)
- type "text": câu hỏi mở, tuỳ chọn, đặt cuối
- Tối đa 4 câu, chỉ hỏi những gì thực sự có trong câu trả lời sai"""

    raw = await _call([{"role": "user", "content": prompt}], model=OPENROUTER_MODEL, max_tokens=600)
    import json, re
    try:
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        if m:
            data = json.loads(m.group())
            if "questions" in data and len(data["questions"]) > 0:
                return data
    except (json.JSONDecodeError, ValueError, KeyError) as e:
        log.warning("generate_correction_form parse error: %s | raw: %.200s", e, raw)

    return {
        "intro": "Câu trả lời sai ở chỗ nào? Bà con cho biết thông tin đúng nhé:",
        "questions": [
            {"id": "q1", "type": "text", "label": "Thông tin đúng là gì?", "placeholder": "Ví dụ: mật độ phải là 40,000 cây/ha, khoảng cách 70×50cm..."},
            {"id": "q2", "type": "yesno", "label": "Bà con chắc chắn về thông tin này không?"},
        ]
    }


async def correct_chat_turn(
    question: str,
    wrong_answer: str,
    turns: list[dict],
    user_message: str,
) -> dict:
    """
    Multi-turn conversational correction.
    Trả về: {action: "continue"|"save"|"cancel", reply: str, corrected_answer: str, confidence: float}
    """
    from app.services.rag import rag
    kb_context = rag.search(f"{question} {user_message}", top_k=3)
    context_section = f"\nKiến thức tham khảo:\n{kb_context[:1500]}" if kb_context else ""

    history_text = ""
    for t in turns[-8:]:
        label = "Người dùng" if t["role"] == "user" else "Bot"
        history_text += f"{label}: {t['content']}\n"

    prompt = f"""Bạn đang hỗ trợ người dùng sửa câu trả lời sai của AI về cà chua. Hãy tương tác thân thiện, ngắn gọn.

Câu hỏi gốc: {question[:300]}
Câu trả lời cũ (bị báo sai): {wrong_answer[:400]}
{context_section}

Lịch sử hội thoại:
{history_text}
Người dùng (mới nhất): {user_message[:400]}

Hướng dẫn:
- Nếu người dùng chưa nói sai gì cụ thể: hỏi sai ở đâu
- Nếu người dùng đã nói sai gì: kiểm tra với KB, tóm tắt lại thông tin đúng và hỏi xác nhận
- Nếu người dùng xác nhận (đúng rồi, phải rồi, ok, đúng, ừ, vâng, cập nhật đi, chính xác): action=save, viết corrected_answer đầy đủ cho câu hỏi gốc
- Nếu người dùng hủy (thôi, bỏ qua, không cần, hủy, cancel): action=cancel
- Ngược lại: action=continue, hỏi thêm

Trả về JSON (chỉ JSON):
{{"action": "continue", "reply": "Câu hỏi/xác nhận ngắn...", "corrected_answer": "", "confidence": 0.0}}

Với action=save: corrected_answer là câu trả lời hoàn chỉnh cho câu hỏi gốc, ngắn gọn, thực tế."""

    # LLMError (timeout/auth/quota) propagate lên global handler — không bắt ở đây
    raw = await _call([{"role": "user", "content": prompt}],
                      model=OPENROUTER_MODEL, max_tokens=500)

    import json, re
    try:
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        if m:
            data = json.loads(m.group())
            action = data.get("action", "continue")
            if action not in ("continue", "save", "cancel"):
                action = "continue"
            return {
                "action":           action,
                "reply":            str(data.get("reply", ""))[:600],
                "corrected_answer": str(data.get("corrected_answer", ""))[:1000],
                "confidence":       max(0.0, min(1.0, float(data.get("confidence", 0.7)))),
            }
    except (json.JSONDecodeError, ValueError, KeyError) as e:
        log.warning("correct_chat_turn parse error: %s | raw: %.200s", e, raw)

    return {"action": "continue", "reply": "Tôi chưa hiểu rõ phản hồi. Bà con thử diễn đạt lại nhé.", "corrected_answer": "", "confidence": 0.0}


async def extract_from_image(image_base64: str) -> str:
    """Trích xuất kiến thức từ ảnh để lưu vào knowledge base."""
    messages = [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": image_base64}},
        {"type": "text", "text": EXTRACT_PROMPT},
    ]}]
    return await _call(messages, max_tokens=2048)
