"""
Tests cho database functions.
"""

import pytest
from app.database import (
    save_feedback, get_feedback_stats,
    save_question, get_analytics,
    create_premium_code, list_premium_codes,
    redeem_code, get_premium_quota, consume_premium,
)


def test_save_and_get_feedback():
    save_feedback("2024-01-01T10:00:00", 1,  "câu hỏi test", "câu trả lời test")
    save_feedback("2024-01-01T10:01:00", -1, "câu hỏi tệ",   "câu trả lời tệ")
    stats = get_feedback_stats()
    assert stats["total"] >= 2
    assert stats["good"] >= 1
    assert stats["bad"]  >= 1
    assert isinstance(stats["items"], list)


def test_save_and_get_analytics():
    save_question("2024-01-01T10:00:00", "cà chua bị vàng lá", has_image=False)
    save_question("2024-01-01T10:01:00", "sâu đục quả",         has_image=True)
    data = get_analytics()
    assert data["total_questions"] >= 2
    assert data["total_with_image"] >= 1
    assert isinstance(data["daily"],        list)
    assert isinstance(data["recent"],       list)
    assert isinstance(data["top_keywords"], list)


def test_create_and_list_premium_codes():
    ok = create_premium_code("DBTEST01", requests=30, images=5, max_uses=3, note="test")
    assert ok is True

    codes = list_premium_codes()
    codes_dict = {c["code"]: c for c in codes}
    assert "DBTEST01" in codes_dict
    c = codes_dict["DBTEST01"]
    assert c["requests"]  == 30
    assert c["images"]    == 5
    assert c["max_uses"]  == 3
    assert c["used_count"] == 0
    assert isinstance(c["redemptions"], list)


def test_create_duplicate_code_fails():
    create_premium_code("DUPDB01", requests=10, images=0)
    ok = create_premium_code("DUPDB01", requests=10, images=0)
    assert ok is False


def test_redeem_code_success():
    create_premium_code("REDEEM01", requests=15, images=3, max_uses=5)
    result = redeem_code("REDEEM01", "192.168.1.1")
    assert result["ok"] is True
    assert result["requests"] == 15
    assert result["images"]   == 3

    quota = get_premium_quota("192.168.1.1")
    assert quota["requests"] >= 15
    assert quota["images"]   >= 3


def test_redeem_invalid_code():
    result = redeem_code("KHONGCO99", "192.168.1.2")
    assert result["ok"] is False
    assert "không hợp lệ" in result["reason"]


def test_redeem_same_ip_twice():
    create_premium_code("ONCEONLY1", requests=10, images=0, max_uses=10)
    redeem_code("ONCEONLY1", "10.0.0.1")
    result = redeem_code("ONCEONLY1", "10.0.0.1")
    assert result["ok"] is False
    assert "đã kích hoạt" in result["reason"]


def test_redeem_exhausted_code():
    create_premium_code("MAXTEST01", requests=5, images=0, max_uses=1)
    redeem_code("MAXTEST01", "10.1.1.1")
    result = redeem_code("MAXTEST01", "10.1.1.2")
    assert result["ok"] is False
    assert "hết lượt" in result["reason"]


def test_consume_premium():
    create_premium_code("CONSUME01", requests=3, images=2, max_uses=10)
    redeem_code("CONSUME01", "10.2.2.2")

    assert consume_premium("10.2.2.2", is_image=False) is True
    assert consume_premium("10.2.2.2", is_image=False) is True
    assert consume_premium("10.2.2.2", is_image=False) is True
    # Hết requests
    assert consume_premium("10.2.2.2", is_image=False) is False

    # Ảnh vẫn còn
    assert consume_premium("10.2.2.2", is_image=True) is True


def test_premium_quota_empty_ip():
    quota = get_premium_quota("ip.chua.co.bao.gio")
    assert quota["requests"] == 0
    assert quota["images"]   == 0
