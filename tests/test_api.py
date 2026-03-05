"""
Tests cho API endpoints.
Chạy: pytest tests/
"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from main import app
    return TestClient(app, raise_server_exceptions=False)


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["chunks"] > 0


def test_chat_empty_message(client):
    r = client.post("/api/chat", json={"message": "", "image": ""})
    assert r.status_code == 200
    assert r.json()["answer"] == ""


def test_chat_returns_answer(client):
    r = client.post("/api/chat", json={"message": "cà chua bị vàng lá"})
    assert r.status_code == 200
    assert len(r.json()["answer"]) > 10


def test_feedback_valid(client):
    r = client.post("/api/feedback", json={
        "question": "test", "answer": "test answer", "rating": 1
    })
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_feedback_invalid_rating(client):
    r = client.post("/api/feedback", json={
        "question": "test", "answer": "test", "rating": 99
    })
    assert r.status_code == 422


def test_admin_requires_auth(client):
    r = client.get("/admin")
    assert r.status_code == 401


def test_admin_wrong_password(client):
    r = client.get("/admin", auth=("admin", "wrong_password"))
    assert r.status_code == 401


def test_admin_correct_password(client):
    import os
    password = os.getenv("ADMIN_PASSWORD", "")
    if not password:
        pytest.skip("ADMIN_PASSWORD chưa được set")
    r = client.get("/admin", auth=("admin", password))
    assert r.status_code == 200


def test_rate_limit(client):
    # Gửi 31 request liên tiếp từ cùng IP — request thứ 31 phải bị từ chối
    for i in range(30):
        client.post("/api/chat", json={"message": f"test {i}"})
    r = client.post("/api/chat", json={"message": "over limit"})
    assert r.status_code == 429
