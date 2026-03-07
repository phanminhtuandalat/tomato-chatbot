"""
Tests cho database functions.
"""

import pytest
from datetime import datetime, timedelta
from app.database import (
    save_feedback, get_feedback_stats,
    save_question, get_analytics,
    create_premium_code, list_premium_codes,
    redeem_code, get_premium_quota, consume_premium,
    check_and_increment_rate, get_daily_rate,
    add_points, get_points, POINTS_PER_QUESTION,
)

TODAY     = datetime.now().strftime("%Y-%m-%d")
YESTERDAY = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
TOMORROW  = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")


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


# ---------------------------------------------------------------------------
# Rate limiting — check_and_increment_rate (DB-backed, atomic)
# ---------------------------------------------------------------------------

def test_rate_first_call_allowed():
    assert check_and_increment_rate("rl_u1", "chat", TODAY, 5) is True


def test_rate_increments_counter():
    check_and_increment_rate("rl_u2", "chat", TODAY, 5)
    assert get_daily_rate("rl_u2", "chat", TODAY) == 1


def test_rate_blocks_at_limit():
    for _ in range(3):
        check_and_increment_rate("rl_u3", "chat", TODAY, 3)
    assert check_and_increment_rate("rl_u3", "chat", TODAY, 3) is False


def test_rate_counter_not_exceeded_past_limit():
    """Counter không vượt quá limit — đảm bảo atomic UPDATE WHERE count < limit."""
    for _ in range(5):
        check_and_increment_rate("rl_u4", "chat", TODAY, 2)
    assert get_daily_rate("rl_u4", "chat", TODAY) == 2  # không phải 5


def test_rate_different_days_independent():
    check_and_increment_rate("rl_u5", "chat", YESTERDAY, 1)
    check_and_increment_rate("rl_u5", "chat", YESTERDAY, 1)  # blocked
    assert check_and_increment_rate("rl_u5", "chat", TODAY, 1) is True


def test_rate_different_types_independent():
    for _ in range(5):
        check_and_increment_rate("rl_u6", "chat", TODAY, 5)
    # Different type should be unaffected
    assert check_and_increment_rate("rl_u6", "image", TODAY, 2) is True


# ---------------------------------------------------------------------------
# Points system — add_points, daily limit, auto-conversion
# ---------------------------------------------------------------------------

def test_points_add_basic():
    result = add_points("pts_u1", "feedback", 5)
    assert result["points_added"] == 5
    assert result["current_points"] == 5


def test_points_auto_convert_to_question():
    """20 điểm tự động đổi thành 1 lượt hỏi."""
    add_points("pts_u2", "feedback", 10)
    result = add_points("pts_u2", "correction", 10)
    assert result["questions_added"] == 1
    assert result["current_points"] == 0  # hết điểm sau khi đổi


def test_points_partial_conversion():
    """25 điểm = 1 lượt + 5 điểm còn lại."""
    result = add_points("pts_u3", "tip", 25)
    assert result["questions_added"] == 1
    assert result["current_points"] == 5


def test_points_daily_limit():
    """Daily limit: lần thứ 3 không được thưởng điểm (limit=2)."""
    add_points("pts_u4", "feedback", 5, daily_limit=2)
    add_points("pts_u4", "feedback", 5, daily_limit=2)
    result = add_points("pts_u4", "feedback", 5, daily_limit=2)
    assert result["points_added"] == 0


def test_points_different_actions_independent():
    """Mỗi action có daily limit riêng."""
    add_points("pts_u5", "feedback", 5, daily_limit=1)
    add_points("pts_u5", "feedback", 5, daily_limit=1)  # blocked
    result = add_points("pts_u5", "correction", 15, daily_limit=1)
    assert result["points_added"] == 15  # action khác, không bị block


def test_points_new_user():
    pts = get_points("pts_brand_new_xyz")
    assert pts["current_points"] == 0
    assert pts["total_earned"] == 0


# ---------------------------------------------------------------------------
# Premium code expiry
# ---------------------------------------------------------------------------

def test_code_expired():
    create_premium_code("EXP_TEST01", 10, 0, 1, "test", expires_at=YESTERDAY)
    result = redeem_code("EXP_TEST01", "200.1.1.1")
    assert result["ok"] is False
    assert "hết hạn" in result["reason"]


def test_code_future_expiry_works():
    create_premium_code("EXP_TEST02", 10, 0, 1, "test", expires_at=TOMORROW)
    result = redeem_code("EXP_TEST02", "200.1.1.2")
    assert result["ok"] is True


def test_code_no_expiry_works():
    create_premium_code("EXP_TEST03", 10, 0, 1, "test", expires_at=None)
    result = redeem_code("EXP_TEST03", "200.1.1.3")
    assert result["ok"] is True
