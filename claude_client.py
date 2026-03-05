"""
Gọi LLM qua OpenRouter API — hỗ trợ cả text và hình ảnh (vision).
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


def get_system_prompt() -> str:
    now = datetime.now()
    return SYSTEM_PROMPT_TEMPLATE.format(month=now.month, year=now.year)


async def ask(question: str, context: str = "", image_base64: str = "") -> str:
    """
    Gọi OpenRouter API.
    - image_base64: chuỗi base64 data URL (data:image/jpeg;base64,...)
    """
    if image_base64:
        text = question or "Bạn hãy phân tích ảnh cây cà chua này và cho biết có vấn đề gì không?"
        if context:
            text += f"\n\n---\nTài liệu tham khảo:\n{context}"
        user_content = [
            {"type": "image_url", "image_url": {"url": image_base64}},
            {"type": "text", "text": text},
        ]
    else:
        user_content = question
        if context:
            user_content = f"""Câu hỏi của nông dân: {question}

---
Tài liệu tham khảo:
{context}
---

Hãy trả lời câu hỏi dựa trên tài liệu trên, có tính đến mùa vụ hiện tại. Nếu tài liệu không đủ, hãy nói rõ."""

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://chatbot-ca-chua.app",
                "X-Title": "Chatbot Ca Chua",
            },
            json={
                "model": MODEL,
                "max_tokens": 1024,
                "messages": [
                    {"role": "system", "content": get_system_prompt()},
                    {"role": "user", "content": user_content},
                ],
            },
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]
