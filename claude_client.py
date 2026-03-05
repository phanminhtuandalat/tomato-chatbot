"""
Gọi LLM qua OpenRouter API — hỗ trợ text, hình ảnh, và lịch sử hội thoại.
"""

import os
from datetime import datetime
import httpx

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
MODEL = os.getenv("OPENROUTER_MODEL", "anthropic/claude-sonnet-4-5")

SYSTEM_PROMPT_TEMPLATE = """Bạn là chuyên gia nông nghiệp hỗ trợ nông dân trồng cà chua tại Việt Nam.

Thời điểm hiện tại: tháng {month} năm {year}.

Nguyên tắc trả lời:
- Trả lời bằng tiếng Việt, ngắn gọn, thực tế, dễ hiểu
- Ưu tiên dùng thông tin trong phần "Tài liệu tham khảo" nếu có
- Luôn gắn lời khuyên với thời điểm tháng {month} hiện tại (mùa vụ, thời tiết)
- Nêu cụ thể: tên thuốc, liều lượng, thời điểm xử lý
- Nếu không chắc hoặc bệnh nặng, luôn khuyên liên hệ cán bộ khuyến nông
- KHÔNG bịa đặt thông tin, KHÔNG đưa lời khuyên mơ hồ

Khi phân tích ảnh:
- Mô tả rõ triệu chứng nhìn thấy trong ảnh
- Đưa ra chẩn đoán khả năng cao nhất
- Gợi ý cách xử lý cụ thể phù hợp với tháng {month}
- Nếu ảnh không đủ rõ, yêu cầu chụp thêm góc khác

Khi không có đủ thông tin:
Trả lời: "Tôi chưa có đủ thông tin để tư vấn chính xác. Bạn nên liên hệ cán bộ khuyến nông địa phương hoặc gọi đường dây nóng 1900-9008."
"""

EXTRACT_PROMPT = """Bạn là chuyên gia nông nghiệp. Hãy đọc ảnh này và trích xuất toàn bộ kiến thức nông nghiệp có trong đó.

Yêu cầu:
- Viết bằng tiếng Việt, rõ ràng, đầy đủ
- Giữ nguyên các số liệu, tên thuốc, liều lượng
- Tổ chức thành các mục rõ ràng với tiêu đề
- Nếu là ảnh bệnh/sâu: mô tả triệu chứng, nguyên nhân, cách xử lý
- Nếu là bảng/infographic: chuyển thành văn bản có cấu trúc
- Nếu là trang sách: trích xuất toàn bộ nội dung

Chỉ trả về nội dung đã trích xuất, không thêm lời mở đầu hay kết."""


def get_system_prompt() -> str:
    now = datetime.now()
    return SYSTEM_PROMPT_TEMPLATE.format(month=now.month, year=now.year)


async def ask(
    question: str,
    context: str = "",
    image_base64: str = "",
    extract_mode: bool = False,
    history: list[dict] | None = None,
) -> str:
    """
    Gọi OpenRouter API.
    - history: danh sách {"role": "user"/"assistant", "content": "..."}
    - image_base64: data URL ảnh
    - extract_mode: trích xuất kiến thức từ ảnh để lưu vào knowledge base
    """

    # ── Chế độ trích xuất ảnh vào knowledge base ──
    if image_base64 and extract_mode:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=_headers(),
                json={
                    "model": MODEL,
                    "max_tokens": 2048,
                    "messages": [{"role": "user", "content": [
                        {"type": "image_url", "image_url": {"url": image_base64}},
                        {"type": "text", "text": EXTRACT_PROMPT},
                    ]}],
                },
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]

    # ── Xây dựng nội dung tin nhắn mới ──
    if image_base64:
        text = question or "Phân tích ảnh cây cà chua này và cho biết có vấn đề gì không?"
        if context:
            text += f"\n\n---\nTài liệu tham khảo:\n{context}"
        new_user_content = [
            {"type": "image_url", "image_url": {"url": image_base64}},
            {"type": "text", "text": text},
        ]
    else:
        if context:
            new_user_content = (
                f"Câu hỏi: {question}\n\n"
                f"---\nTài liệu tham khảo:\n{context}\n---\n\n"
                f"Trả lời dựa trên tài liệu, có tính đến mùa vụ hiện tại."
            )
        else:
            new_user_content = question

    # ── Ghép lịch sử hội thoại ──
    messages = [{"role": "system", "content": get_system_prompt()}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": new_user_content})

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=_headers(),
            json={"model": MODEL, "max_tokens": 1024, "messages": messages},
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://chatbot-ca-chua.app",
        "X-Title": "Chatbot Ca Chua",
    }
