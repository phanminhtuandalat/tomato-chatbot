"""
Push notification router.
POST /api/push-subscribe   — lưu subscription từ browser
DELETE /api/push-subscribe — xoá subscription
POST /admin/push-send      — admin gửi thông báo đến tất cả subscribers
GET  /api/vapid-public-key — trả về public key cho browser
"""

import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.config import VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY, VAPID_EMAIL, PUSH_ENABLED
from app.database import save_push_subscription, delete_push_subscription, get_all_subscriptions
from app.routers.admin import require_admin

logger = logging.getLogger(__name__)
router = APIRouter()


class SubscriptionKeys(BaseModel):
    p256dh: str
    auth: str

class PushSubscription(BaseModel):
    endpoint: str
    keys: SubscriptionKeys

class PushMessage(BaseModel):
    title: str
    body: str
    url: str = "/"


@router.get("/api/vapid-public-key")
async def vapid_public_key():
    if not PUSH_ENABLED:
        return JSONResponse({"enabled": False, "key": ""})
    return JSONResponse({"enabled": True, "key": VAPID_PUBLIC_KEY})


@router.post("/api/push-subscribe")
async def subscribe(sub: PushSubscription):
    if not PUSH_ENABLED:
        return JSONResponse({"ok": False, "reason": "push_disabled"})
    save_push_subscription(
        ts=datetime.now().isoformat(timespec="seconds"),
        endpoint=sub.endpoint,
        p256dh=sub.keys.p256dh,
        auth=sub.keys.auth,
    )
    return JSONResponse({"ok": True})


@router.delete("/api/push-subscribe")
async def unsubscribe(sub: PushSubscription):
    delete_push_subscription(sub.endpoint)
    return JSONResponse({"ok": True})


@router.post("/admin/push-send")
async def send_push(msg: PushMessage, _: None = Depends(require_admin)):
    if not PUSH_ENABLED:
        raise HTTPException(status_code=400, detail="Push notifications chưa được cấu hình. Cần thêm VAPID_PUBLIC_KEY và VAPID_PRIVATE_KEY.")

    import base64
    from pywebpush import webpush, WebPushException

    # Decode private key từ base64 PEM về PEM string
    try:
        priv_pem = base64.b64decode(VAPID_PRIVATE_KEY + "==").decode()
    except Exception:
        priv_pem = VAPID_PRIVATE_KEY  # fallback nếu đã là PEM

    subs = get_all_subscriptions()
    if not subs:
        return JSONResponse({"ok": True, "sent": 0, "failed": 0, "reason": "no_subscribers"})

    payload = json.dumps({"title": msg.title, "body": msg.body, "url": msg.url})
    sent = failed = 0
    dead_endpoints = []

    for sub in subs:
        try:
            webpush(
                subscription_info={
                    "endpoint": sub["endpoint"],
                    "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]},
                },
                data=payload,
                vapid_private_key=priv_pem,
                vapid_claims={"sub": VAPID_EMAIL},
            )
            sent += 1
        except WebPushException as e:
            status = e.response.status_code if e.response else 0
            if status in (404, 410):  # subscription expired
                dead_endpoints.append(sub["endpoint"])
            else:
                logger.warning("Push failed for %s: %s", sub["endpoint"][:40], e)
            failed += 1
        except Exception as e:
            logger.warning("Push error: %s", e)
            failed += 1

    for ep in dead_endpoints:
        delete_push_subscription(ep)

    return JSONResponse({"ok": True, "sent": sent, "failed": failed, "total": len(subs)})
