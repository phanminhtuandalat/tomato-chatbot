"""
Tất cả cấu hình từ environment variables.
Validate ngay khi import — fail fast nếu thiếu biến quan trọng.
"""

import os
from dotenv import load_dotenv

load_dotenv()


def _require(key: str) -> str:
    val = os.getenv(key, "").strip()
    if not val:
        raise RuntimeError(f"Thiếu biến môi trường bắt buộc: {key}")
    return val


def _get(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


# LLM
OPENROUTER_API_KEY    = _require("OPENROUTER_API_KEY")
OPENROUTER_API_KEY_2  = _get("OPENROUTER_API_KEY_2")   # backup key khi primary hết quota/bị ban
OPENAI_API_KEY        = _get("OPENAI_API_KEY")         # embeddings trực tiếp (tuỳ chọn)
OPENROUTER_MODEL      = _get("OPENROUTER_MODEL",       "anthropic/claude-sonnet-4-5")
OPENROUTER_MODEL_FAST = _get("OPENROUTER_MODEL_FAST",  "anthropic/claude-haiku-4-5")

# Weather (tuỳ chọn — OpenWeatherMap free tier)
OPENWEATHER_API_KEY = _get("OPENWEATHER_API_KEY")

# Zalo (tuỳ chọn — chỉ cần khi dùng Zalo OA)
ZALO_OA_ACCESS_TOKEN = _get("ZALO_OA_ACCESS_TOKEN")
ZALO_APP_SECRET      = _get("ZALO_APP_SECRET")

# Admin
ADMIN_USER     = _get("ADMIN_USER", "admin")
ADMIN_PASSWORD = _require("ADMIN_PASSWORD")

# Push notifications (tuỳ chọn — cần VAPID keys)
VAPID_PUBLIC_KEY  = _get("VAPID_PUBLIC_KEY")
VAPID_PRIVATE_KEY = _get("VAPID_PRIVATE_KEY")
VAPID_EMAIL       = _get("VAPID_EMAIL", "mailto:admin@tomato-chatbot.app")
PUSH_ENABLED      = bool(VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY)

# Telegram notifications (tuỳ chọn)
TELEGRAM_BOT_TOKEN = _get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID   = _get("TELEGRAM_CHAT_ID")

# Cost cap — giới hạn số lần gọi LLM mỗi ngày để kiểm soát chi phí
# Sonnet (~$0.01/call): mặc định 300 calls/ngày ≈ $3/ngày
# Haiku (~$0.001/call): mặc định 2000 calls/ngày ≈ $2/ngày
MAX_DAILY_SONNET_CALLS = int(_get("MAX_DAILY_SONNET_CALLS", "300"))
MAX_DAILY_HAIKU_CALLS  = int(_get("MAX_DAILY_HAIKU_CALLS",  "2000"))

# Server
PORT = int(_get("PORT", "8000"))
