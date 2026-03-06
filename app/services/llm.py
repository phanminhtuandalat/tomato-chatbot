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
- Ưu tiên thông tin từ "Tài liệu tham khảo" nếu có; gắn với mùa vụ tháng {month}
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
_CACHE_TTL  = 3600   # 1 giờ
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
            f"---\nTài liệu tham khảo:\n{context}\n---\n\n"
            f"Trả lời dựa trên tài liệu, có tính đến mùa vụ hiện tại."
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


async def extract_from_image(image_base64: str) -> str:
    """Trích xuất kiến thức từ ảnh để lưu vào knowledge base."""
    messages = [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": image_base64}},
        {"type": "text", "text": EXTRACT_PROMPT},
    ]}]
    return await _call(messages, max_tokens=2048)
