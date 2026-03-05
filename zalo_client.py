"""
Gửi tin nhắn đến người dùng qua Zalo OA API.
"""

import os
import httpx

ZALO_OA_ACCESS_TOKEN = os.getenv("ZALO_OA_ACCESS_TOKEN", "")
ZALO_API_URL = "https://openapi.zalo.me/v3.0/oa/message/cs"


async def send_message(user_id: str, text: str) -> bool:
    """
    Gửi tin nhắn text đến user_id.
    Zalo giới hạn 1 tin nhắn chủ động trong 48h sau lần user nhắn cuối.
    """
    # Zalo giới hạn 2000 ký tự mỗi tin nhắn
    if len(text) > 1900:
        text = text[:1900] + "\n\n[...] Xem thêm tại trạm khuyến nông địa phương."

    payload = {
        "recipient": {"user_id": user_id},
        "message": {"text": text},
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            ZALO_API_URL,
            headers={
                "access_token": ZALO_OA_ACCESS_TOKEN,
                "Content-Type": "application/json",
            },
            json=payload,
        )
        data = response.json()
        # Zalo trả về error code 0 là thành công
        return data.get("error") == 0
