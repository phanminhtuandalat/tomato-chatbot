"""
Gọi LLM qua OpenRouter API để trả lời câu hỏi về cà chua.
OpenRouter dùng format OpenAI-compatible.
"""

import os
import httpx

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
# Đổi model tùy ý, ví dụ:
# "anthropic/claude-sonnet-4-5"
# "google/gemini-flash-1.5"
# "meta-llama/llama-3.1-8b-instruct:free"
MODEL = os.getenv("OPENROUTER_MODEL", "anthropic/claude-sonnet-4-5")

SYSTEM_PROMPT = """Bạn là chuyên gia nông nghiệp hỗ trợ nông dân trồng cà chua tại Việt Nam.

Nguyên tắc trả lời:
- Trả lời bằng tiếng Việt, ngắn gọn, thực tế, dễ hiểu
- Ưu tiên dùng thông tin trong phần "Tài liệu tham khảo" nếu có
- Nêu cụ thể: tên thuốc, liều lượng, thời điểm xử lý
- Nếu không chắc hoặc bệnh nặng, luôn khuyên liên hệ cán bộ khuyến nông
- KHÔNG bịa đặt thông tin, KHÔNG đưa lời khuyên mơ hồ
- Với câu hỏi nguy hiểm (thuốc độc hại, liều cao bất thường): cảnh báo rõ ràng

Khi không có đủ thông tin:
Trả lời: "Tôi chưa có đủ thông tin để tư vấn chính xác về vấn đề này. Bạn nên liên hệ cán bộ khuyến nông địa phương hoặc gọi đường dây nóng 1900-9008."
"""


async def ask(question: str, context: str = "") -> str:
    """
    Gọi OpenRouter API, kèm context từ knowledge base nếu có.
    """
    user_content = question
    if context:
        user_content = f"""Câu hỏi của nông dân: {question}

---
Tài liệu tham khảo:
{context}
---

Hãy trả lời câu hỏi dựa trên tài liệu trên. Nếu tài liệu không đủ, hãy nói rõ."""

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://chatbot-ca-chua.app",  # tuỳ chỉnh
                "X-Title": "Chatbot Ca Chua",
            },
            json={
                "model": MODEL,
                "max_tokens": 1024,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
            },
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]
