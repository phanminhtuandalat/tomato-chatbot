"""
Tests cho API endpoints.
Chạy: pytest tests/
(client fixture được cung cấp bởi conftest.py)
"""

import pytest


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_index_page(client):
    r = client.get("/")
    assert r.status_code == 200


def test_chat_empty_message(client):
    r = client.post("/api/chat", json={"message": "", "image": ""})
    assert r.status_code == 200
    assert r.json()["answer"] == ""


def test_chat_returns_answer(client):
    """Bot phải trả lời — dù là lỗi cụ thể vì API key giả."""
    r = client.post("/api/chat", json={"message": "cà chua bị vàng lá"})
    assert r.status_code == 200
    answer = r.json()["answer"]
    assert isinstance(answer, str) and len(answer) > 5


def test_chat_with_history(client):
    r = client.post("/api/chat", json={
        "message": "bón phân lần 2 thế nào?",
        "history": [
            {"role": "user",      "content": "cà chua ra hoa rồi"},
            {"role": "assistant", "content": "Cần bón kali tăng đậu quả."},
        ],
    })
    assert r.status_code == 200
    assert "answer" in r.json()


def test_feedback_valid(client):
    r = client.post("/api/feedback", json={
        "question": "test", "answer": "test answer", "rating": 1
    })
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_feedback_thumbs_down(client):
    r = client.post("/api/feedback", json={
        "question": "test", "answer": "bad", "rating": -1
    })
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_feedback_invalid_rating(client):
    r = client.post("/api/feedback", json={
        "question": "test", "answer": "test", "rating": 99
    })
    assert r.status_code == 422


def test_quota_structure(client):
    r = client.get("/api/quota")
    assert r.status_code == 200
    data = r.json()
    assert "free" in data and "premium" in data
    assert "requests" in data["free"] and "images" in data["free"]


def test_redeem_invalid_code(client):
    r = client.post("/api/redeem", json={"code": "KHONGTON999"})
    assert r.status_code == 400


def test_admin_requires_auth(client):
    r = client.get("/admin")
    assert r.status_code == 401


def test_admin_wrong_password(client):
    r = client.get("/admin", auth=("admin", "wrong"))
    assert r.status_code == 401


def test_admin_correct_password(client):
    r = client.get("/admin", auth=("admin", "testpass"))
    assert r.status_code == 200


def test_admin_analytics(client):
    r = client.get("/admin/analytics", auth=("admin", "testpass"))
    assert r.status_code == 200
    data = r.json()
    assert "total_questions" in data and "top_keywords" in data


def test_admin_feedback_stats(client):
    r = client.get("/admin/feedback", auth=("admin", "testpass"))
    assert r.status_code == 200
    data = r.json()
    assert "total" in data and "good" in data and "bad" in data


def test_admin_create_and_list_codes(client):
    r = client.post("/admin/premium-code",
        auth=("admin", "testpass"),
        json={"code": "APITEST01", "requests": 20, "images": 5, "max_uses": 3},
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True

    r2 = client.get("/admin/premium-codes", auth=("admin", "testpass"))
    codes = [c["code"] for c in r2.json()["codes"]]
    assert "APITEST01" in codes


def test_admin_duplicate_code(client):
    client.post("/admin/premium-code",
        auth=("admin", "testpass"),
        json={"code": "DUPAPI01", "requests": 10, "images": 0},
    )
    r = client.post("/admin/premium-code",
        auth=("admin", "testpass"),
        json={"code": "DUPAPI01", "requests": 10, "images": 0},
    )
    assert r.json()["ok"] is False


def _reset_rate_state():
    """Reset cả in-memory per-minute log lẫn DB daily counters."""
    import app.routers.chat as chat_router
    from app.database import get_conn
    chat_router._request_log.clear()
    with get_conn() as conn:
        conn.execute("DELETE FROM rate_limits")


def test_rate_limit_per_minute(client):
    """21 requests liên tiếp từ cùng device → request thứ 21 bị chặn."""
    _reset_rate_state()

    for i in range(20):
        client.post("/api/chat", json={"message": f"test {i}"})
    r = client.post("/api/chat", json={"message": "over limit"})
    assert r.status_code == 429


def test_daily_limit(client):
    """Sau 5 câu hỏi miễn phí phải trả QUOTA_EXCEEDED."""
    _reset_rate_state()

    for i in range(5):
        client.post("/api/chat", json={"message": f"daily {i}"})
    r = client.post("/api/chat", json={"message": "should fail"})
    assert r.status_code == 429
    assert r.json()["detail"] == "QUOTA_EXCEEDED"
