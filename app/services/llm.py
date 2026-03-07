"""
LLM Service — gọi OpenRouter API.
Hỗ trợ: text, hình ảnh (vision), lịch sử hội thoại, trích xuất kiến thức từ ảnh.
"""

import asyncio
import hashlib
import logging
import time
from datetime import datetime
import httpx
from app.config import (
    OPENROUTER_API_KEY, OPENROUTER_API_KEY_2,
    OPENROUTER_MODEL, OPENROUTER_MODEL_FAST, OPENROUTER_MODEL_VISION,
    MAX_DAILY_SONNET_CALLS, MAX_DAILY_HAIKU_CALLS,
)

log = logging.getLogger(__name__)


SYSTEM_PROMPT_TEMPLATE = """Bạn là chuyên gia tư vấn trồng cà chua, nói chuyện thân thiện như người quen với bà con nông dân Việt Nam. Hiện tại: tháng {month}/{year}.

Phong cách:
- Gọi người dùng là "bà con", xưng "tôi"
- Tiếng Việt giản dị, ngắn gọn — như đang nói chuyện trực tiếp, không như sách giáo khoa
- Dùng danh sách gạch đầu dòng hoặc đánh số (1. 2. 3.) — KHÔNG dùng bảng
- Tên thuốc/hoá chất viết **đậm**

Nội dung:
- Khi có "Tài liệu tham khảo": BẮT BUỘC dùng số liệu trong đó (mật độ, khoảng cách, liều lượng). KHÔNG thay bằng số liệu khác
- Nêu cụ thể: tên thuốc, liều lượng, thời điểm phun/bón
- Nếu không chắc: nói thẳng "Tôi không chắc, bà con nên hỏi thêm cán bộ khuyến nông"
- Bệnh nặng hoặc khó xác định → khuyên gọi **1900-9008** hoặc gặp cán bộ khuyến nông

Khi hỏi về bệnh/sâu hại, trả lời theo thứ tự:
1. Triệu chứng đang thấy
2. Nguyên nhân có thể
3. Chẩn đoán (hoặc "cần xem thêm" nếu chưa rõ)
4. Cách xử lý: tên thuốc, liều lượng, thời điểm{region_line}{weather_line}"""

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
MAX_HISTORY_MSGS    = 10    # 5 lượt gần nhất
MAX_HISTORY_CHARS   = 800   # mỗi message ~200 từ — đủ giữ ngữ cảnh trả lời nông nghiệp
MAX_TOKENS_RESPONSE = 1500  # đủ cho câu trả lời đầy đủ: triệu chứng + chẩn đoán + thuốc + liều lượng
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


def _check_cost_cap(model: str) -> None:
    """Kiểm tra giới hạn LLM calls/ngày. Raise LLMError('quota') nếu vượt giới hạn."""
    from app.database import check_and_increment_rate
    today = datetime.now().strftime("%Y-%m-%d")
    if OPENROUTER_MODEL in model:
        kind, limit = "llm_sonnet", MAX_DAILY_SONNET_CALLS
    elif OPENROUTER_MODEL_VISION in model or "gemini" in model:
        kind, limit = "llm_vision", MAX_DAILY_HAIKU_CALLS   # Gemini Flash ~ giá Haiku
    else:
        kind, limit = "llm_haiku", MAX_DAILY_HAIKU_CALLS
    if not check_and_increment_rate("global", kind, today, limit):
        log.warning("[CostCap] Đã chạm giới hạn %s calls/ngày cho model %s", limit, model)
        raise LLMError("quota")


import json as _json


async def _call_stream(
    messages: list[dict],
    model: str = OPENROUTER_MODEL_FAST,
    max_tokens: int = MAX_TOKENS_RESPONSE,
):
    """Streaming version — async generator yields text chunks."""
    _check_cost_cap(model)

    api_keys = [OPENROUTER_API_KEY]
    if OPENROUTER_API_KEY_2:
        api_keys.append(OPENROUTER_API_KEY_2)

    for key_idx, api_key in enumerate(api_keys):
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream(
                    "POST",
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://chatbot-ca-chua.app",
                        "X-Title": "Chatbot Ca Chua",
                    },
                    json={"model": model, "max_tokens": max_tokens,
                          "messages": messages, "stream": True},
                ) as response:
                    if response.status_code in (401, 402, 429):
                        log.warning("[LLM stream] key%d status %s — thử key tiếp",
                                    key_idx + 1, response.status_code)
                        await response.aread()
                        continue
                    if response.status_code >= 500:
                        raise LLMError("server")
                    response.raise_for_status()

                    async for line in response.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        data = line[6:].strip()
                        if data == "[DONE]":
                            return
                        try:
                            chunk = _json.loads(data)
                            content = chunk["choices"][0]["delta"].get("content", "")
                            if content:
                                yield content
                        except Exception:
                            pass
            return  # thành công, không thử key tiếp
        except httpx.TimeoutException:
            raise LLMError("timeout")
        except httpx.ConnectError:
            raise LLMError("connect")

    raise LLMError("auth")


async def chat_stream(
    question: str,
    context: str = "",
    image_base64: str = "",
    history: list[dict] | None = None,
    region: str = "",
    weather: str = "",
):
    """Streaming version of chat(). Async generator yields text chunks."""
    question = question[:MAX_QUESTION_CHARS]
    context  = context[:MAX_CONTEXT_CHARS]

    if image_base64:
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
        async for chunk in _call_stream(messages, model=OPENROUTER_MODEL_VISION):
            yield chunk
        return

    if context:
        user_content = (
            f"Câu hỏi: {question}\n\n"
            f"---\nTài liệu tham khảo (dùng số liệu này, không thay bằng số liệu khác):\n{context}\n---\n\n"
            f"Trả lời dựa trên tài liệu trên."
        )
    else:
        user_content = question

    messages = [{"role": "system", "content": _system_prompt(region, weather)}]
    if history:
        messages.extend(_trim_history(history))
    messages.append({"role": "user", "content": user_content})

    async for chunk in _call_stream(messages, model=OPENROUTER_MODEL_FAST):
        yield chunk


async def _call(messages: list[dict], model: str = OPENROUTER_MODEL_FAST,
                max_tokens: int = MAX_TOKENS_RESPONSE) -> str:
    # Kiểm tra cost cap trước khi gọi API
    _check_cost_cap(model)

    # Thử primary key trước, fallback sang secondary key khi auth/quota lỗi
    api_keys = [OPENROUTER_API_KEY]
    if OPENROUTER_API_KEY_2:
        api_keys.append(OPENROUTER_API_KEY_2)

    last_error: LLMError | None = None

    for key_idx, api_key in enumerate(api_keys):
        for attempt in range(2):  # 2 lần thử mỗi key (retry server/timeout)
            if attempt == 1:
                await asyncio.sleep(1.0)

            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    response = await client.post(
                        "https://openrouter.ai/api/v1/chat/completions",
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json",
                            "HTTP-Referer": "https://chatbot-ca-chua.app",
                            "X-Title": "Chatbot Ca Chua",
                        },
                        json={"model": model, "max_tokens": max_tokens, "messages": messages},
                    )
            except httpx.TimeoutException:
                last_error = LLMError("timeout")
                log.warning("[LLM] key%d timeout attempt%d", key_idx + 1, attempt + 1)
                continue
            except httpx.ConnectError:
                raise LLMError("connect")

            if response.status_code == 401:
                last_error = LLMError("auth")
                log.warning("[LLM] key%d auth failed — thử key tiếp theo", key_idx + 1)
                break  # thử key tiếp theo
            if response.status_code in (402, 429):
                last_error = LLMError("quota")
                log.warning("[LLM] key%d quota exceeded — thử key tiếp theo", key_idx + 1)
                break  # thử key tiếp theo
            if response.status_code >= 500:
                last_error = LLMError("server")
                log.warning("[LLM] key%d server %s attempt%d", key_idx + 1, response.status_code, attempt + 1)
                continue

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

    raise last_error or LLMError("server")


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
        # Ảnh: dùng Gemini Vision + không cache (mỗi ảnh khác nhau)
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
        return await _call(messages, model=OPENROUTER_MODEL_VISION)

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


async def extract_from_image(image_base64: str) -> str:
    """Trích xuất kiến thức từ ảnh để lưu vào knowledge base."""
    messages = [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": image_base64}},
        {"type": "text", "text": EXTRACT_PROMPT},
    ]}]
    return await _call(messages, model=OPENROUTER_MODEL_VISION, max_tokens=2048)
