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
OPENROUTER_API_KEY = _require("OPENROUTER_API_KEY")
OPENROUTER_MODEL   = _get("OPENROUTER_MODEL", "anthropic/claude-sonnet-4-5")

# Zalo (tuỳ chọn — chỉ cần khi dùng Zalo OA)
ZALO_OA_ACCESS_TOKEN = _get("ZALO_OA_ACCESS_TOKEN")
ZALO_APP_SECRET      = _get("ZALO_APP_SECRET")

# Admin
ADMIN_USER     = _get("ADMIN_USER", "admin")
ADMIN_PASSWORD = _require("ADMIN_PASSWORD")

# Server
PORT = int(_get("PORT", "8000"))
