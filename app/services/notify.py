"""
Telegram notification service với batching.

Gom nhiều sự kiện lại, gửi 1 tin khi đủ BATCH_SIZE hoặc sau BATCH_WINDOW giây.
Chỉ notify các sự kiện cần admin chú ý:
  - pending_review  : tip cần duyệt thủ công
  - auto_rejected   : tip bị từ chối tự động (có thể spam/sai)
  - correction      : user sửa KB thành công qua hội thoại
"""

import asyncio
import logging
import time
from datetime import datetime

import httpx

from app.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

log = logging.getLogger(__name__)

_BATCH_SIZE   = 1       # flush ngay mỗi sự kiện (tắt batch để test)
_BATCH_WINDOW = 3600    # hoặc khi đã chờ >= 1 giờ (giây)

_queue:     list[dict] = []
_last_sent: float      = 0.0
_lock:      asyncio.Lock | None = None  # lazy — tạo trong event loop


def _get_lock() -> asyncio.Lock:
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


def enabled() -> bool:
    return bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)


async def _send(text: str) -> None:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"},
            )
    except Exception as e:
        log.warning("Telegram notify failed: %s", e)


def _format(e: dict) -> str:
    title = e["title"][:80]
    if e["kind"] == "pending_review":
        return f"⏳ <b>Cần duyệt:</b> {title}"
    if e["kind"] == "auto_rejected":
        reason = e.get("reason", "")[:100]
        return f"❌ <b>Từ chối tự động:</b> {title}" + (f"\n    {reason}" if reason else "")
    if e["kind"] == "correction":
        return f"✏️ <b>User sửa KB:</b> {title}"
    return f"ℹ️ {title}"


async def _flush() -> None:
    global _last_sent, _queue
    if not _queue:
        return
    events, _queue = _queue[:], []
    _last_sent = time.time()
    now = datetime.now().strftime("%d/%m %H:%M")
    lines = [f"🍅 <b>Tomato KB — {now}</b>", ""]
    for e in events:
        lines.append(_format(e))
    lines += ["", f"📊 {len(events)} sự kiện · /admin để xử lý"]
    await _send("\n".join(lines))


async def push(kind: str, title: str, reason: str = "") -> None:
    """Thêm sự kiện, tự flush nếu đủ điều kiện. Không bao giờ raise exception."""
    if not enabled():
        return
    try:
        async with _get_lock():
            _queue.append({"kind": kind, "title": title, "reason": reason})
            if len(_queue) >= _BATCH_SIZE or (time.time() - _last_sent) >= _BATCH_WINDOW:
                await _flush()
    except Exception as e:
        log.warning("notify.push error: %s", e)
