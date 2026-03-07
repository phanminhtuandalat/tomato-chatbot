"""
Backup service — sao lưu SQLite DB qua Telegram Bot mỗi đêm lúc 3 AM.
Chỉ hoạt động khi TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID được cấu hình.
Không cần thêm dependency — dùng httpx (đã có sẵn).
"""

import asyncio
import gzip
import logging
from datetime import datetime, timedelta

import httpx

from app.database import DB_PATH

log = logging.getLogger(__name__)

BACKUP_HOUR = 3  # 3 AM, sau Evolution Engine (2 AM)


async def backup_db_to_telegram(bot_token: str, chat_id: str) -> bool:
    """
    Nén DB bằng gzip và gửi file qua Telegram.
    Trả về True nếu thành công.
    Telegram Bot giới hạn 50MB — DB SQLite của app này thường < 5MB.
    """
    try:
        raw = DB_PATH.read_bytes()
        compressed = gzip.compress(raw, compresslevel=9)
        ts = datetime.now().strftime("%Y%m%d_%H%M")
        filename = f"tomato_db_{ts}.db.gz"
        size_kb = len(compressed) / 1024

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"https://api.telegram.org/bot{bot_token}/sendDocument",
                data={
                    "chat_id": chat_id,
                    "caption": (
                        f"DB Backup {ts}\n"
                        f"Size: {size_kb:.1f} KB (raw: {len(raw)/1024:.1f} KB)\n"
                        f"Path: {DB_PATH}"
                    ),
                },
                files={"document": (filename, compressed, "application/gzip")},
            )

        if resp.status_code == 200:
            log.info("[Backup] Thanh cong: %s (%.1f KB compressed)", filename, size_kb)
            return True
        else:
            log.error("[Backup] Telegram API loi %s: %s", resp.status_code, resp.text[:300])
            return False

    except Exception as e:
        log.error("[Backup] Loi: %s", e)
        return False


async def backup_scheduler() -> None:
    """
    Background asyncio task — chạy vô hạn.
    Backup DB mỗi ngày lúc BACKUP_HOUR giờ.
    Tắt gracefully khi bị CancelledError.
    """
    from app.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.info("[Backup] Bo qua — chua cau hinh TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID")
        return

    log.info("[Backup] Scheduler khoi dong — backup moi ngay luc %02d:00", BACKUP_HOUR)

    while True:
        try:
            now = datetime.now()
            target = now.replace(hour=BACKUP_HOUR, minute=0, second=0, microsecond=0)
            if target <= now:
                target += timedelta(days=1)

            wait = (target - now).total_seconds()
            log.info("[Backup] Lan backup tiep theo: %s (sau %.0fh%.0fm)",
                     target.strftime("%d/%m %H:%M"), wait // 3600, (wait % 3600) // 60)

            await asyncio.sleep(wait)
            await backup_db_to_telegram(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)

        except asyncio.CancelledError:
            log.info("[Backup] Scheduler dung.")
            break
        except Exception as e:
            log.error("[Backup] Loi scheduler: %s — thu lai sau 1 gio", e)
            await asyncio.sleep(3600)
