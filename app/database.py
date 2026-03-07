"""
SQLite database — lưu feedback từ nông dân.
Dùng sqlite3 built-in, không cần ORM thêm.
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "app.db"


def init_db() -> None:
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS feedback (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                ts       TEXT    NOT NULL,
                rating   INTEGER NOT NULL,
                question TEXT    DEFAULT '',
                answer   TEXT    DEFAULT ''
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS questions (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                ts        TEXT    NOT NULL,
                question  TEXT    NOT NULL,
                has_image INTEGER DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS premium_codes (
                code       TEXT    PRIMARY KEY,
                requests   INTEGER NOT NULL,
                images     INTEGER NOT NULL DEFAULT 0,
                max_uses   INTEGER NOT NULL DEFAULT 1,
                used_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT    NOT NULL,
                note       TEXT    DEFAULT ''
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS code_redemptions (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                code    TEXT NOT NULL,
                ip      TEXT NOT NULL,
                ts      TEXT NOT NULL,
                UNIQUE(code, ip)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS premium_quota (
                ip         TEXT    PRIMARY KEY,
                requests   INTEGER NOT NULL DEFAULT 0,
                images     INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS push_subscriptions (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                ts       TEXT    NOT NULL,
                endpoint TEXT    NOT NULL UNIQUE,
                p256dh   TEXT    NOT NULL,
                auth     TEXT    NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chunks (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                source     TEXT    NOT NULL,
                title      TEXT    NOT NULL DEFAULT '',
                content    TEXT    NOT NULL,
                embedding  BLOB    NOT NULL,
                created_at TEXT    NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_regions (
                device_id  TEXT PRIMARY KEY,
                region     TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS community_tips (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id  TEXT    NOT NULL,
                title      TEXT    NOT NULL,
                content    TEXT    NOT NULL,
                category   TEXT    NOT NULL DEFAULT '',
                region     TEXT    NOT NULL DEFAULT '',
                created_at TEXT    NOT NULL,
                status     TEXT    NOT NULL DEFAULT 'pending',
                admin_note TEXT    NOT NULL DEFAULT ''
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tips_status ON community_tips(status)")
        # Migration: thêm các cột mới (bỏ qua nếu đã tồn tại)
        for col in [
            "ALTER TABLE community_tips ADD COLUMN ai_confidence REAL DEFAULT NULL",
            "ALTER TABLE community_tips ADD COLUMN ai_reason TEXT DEFAULT ''",
            "ALTER TABLE community_tips ADD COLUMN ai_action TEXT DEFAULT ''",
            "ALTER TABLE premium_codes ADD COLUMN max_uses INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE premium_codes ADD COLUMN used_count INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE premium_codes ADD COLUMN note TEXT DEFAULT ''",
            "ALTER TABLE premium_codes ADD COLUMN expires_at TEXT DEFAULT NULL",
        ]:
            try:
                conn.execute(col)
            except Exception:
                pass
        conn.execute("""
            CREATE TABLE IF NOT EXISTS image_submissions (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id  TEXT    NOT NULL,
                diagnosis  TEXT    NOT NULL DEFAULT '',
                feedback   INTEGER DEFAULT NULL,
                label      TEXT    DEFAULT NULL,
                created_at TEXT    NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_points (
                device_id        TEXT    PRIMARY KEY,
                total_earned     INTEGER NOT NULL DEFAULT 0,
                current_points   INTEGER NOT NULL DEFAULT 0,
                questions_earned INTEGER NOT NULL DEFAULT 0,
                updated_at       TEXT    NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS points_log (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id  TEXT    NOT NULL,
                action     TEXT    NOT NULL,
                points     INTEGER NOT NULL,
                created_at TEXT    NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS evolution_log (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                ts         TEXT    NOT NULL,
                action     TEXT    NOT NULL,
                topic      TEXT    NOT NULL DEFAULT '',
                result     TEXT    NOT NULL DEFAULT '',
                detail     TEXT    NOT NULL DEFAULT ''
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_evolution_ts ON evolution_log(ts)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_questions_ts ON questions(ts)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                device_id  TEXT PRIMARY KEY,
                messages   TEXT NOT NULL DEFAULT '[]',
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rate_limits (
                key   TEXT    NOT NULL,
                type  TEXT    NOT NULL,
                date  TEXT    NOT NULL,
                count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (key, type, date)
            )
        """)


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # WAL mode: cho phép đọc đồng thời khi đang ghi; busy_timeout tránh "database is locked"
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def redeem_code(code: str, ip: str) -> dict:
    """Đổi mã premium. Mỗi IP chỉ dùng 1 mã 1 lần, mã có giới hạn max_uses lượt."""
    from datetime import datetime
    with get_conn() as conn:
        row = conn.execute(
            "SELECT requests, images, max_uses, used_count, expires_at FROM premium_codes WHERE code=?",
            (code.upper(),)
        ).fetchone()
        if not row:
            return {"ok": False, "reason": "Mã không hợp lệ"}
        if row["used_count"] >= row["max_uses"]:
            return {"ok": False, "reason": "Mã đã hết lượt sử dụng"}
        if row["expires_at"] and datetime.now().isoformat() > row["expires_at"]:
            return {"ok": False, "reason": "Mã đã hết hạn"}
        # Kiểm tra IP này đã dùng mã này chưa
        already = conn.execute(
            "SELECT 1 FROM code_redemptions WHERE code=? AND ip=?", (code.upper(), ip)
        ).fetchone()
        if already:
            return {"ok": False, "reason": "Bạn đã kích hoạt mã này rồi"}
        # Ghi nhận lượt dùng
        conn.execute(
            "UPDATE premium_codes SET used_count=used_count+1 WHERE code=?", (code.upper(),)
        )
        conn.execute(
            "INSERT INTO code_redemptions (code, ip, ts) VALUES (?,?,?)",
            (code.upper(), ip, datetime.now().isoformat(timespec="seconds")),
        )
        conn.execute("""
            INSERT INTO premium_quota (ip, requests, images) VALUES (?, ?, ?)
            ON CONFLICT(ip) DO UPDATE SET
                requests = requests + excluded.requests,
                images   = images   + excluded.images
        """, (ip, row["requests"], row["images"]))
    return {"ok": True, "requests": row["requests"], "images": row["images"]}


def add_bonus_quota(device_id: str, requests: int) -> None:
    """Thưởng lượt hỏi miễn phí cho người dùng (feedback, tip...)."""
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO premium_quota (ip, requests, images) VALUES (?, ?, 0)
            ON CONFLICT(ip) DO UPDATE SET requests = requests + excluded.requests
        """, (device_id, requests))


def get_premium_quota(ip: str) -> dict:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT requests, images FROM premium_quota WHERE ip=?", (ip,)
        ).fetchone()
    return dict(row) if row else {"requests": 0, "images": 0}


def consume_premium(ip: str, is_image: bool = False) -> bool:
    """Trừ 1 quota premium. Trả True nếu còn quota."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT requests, images FROM premium_quota WHERE ip=?", (ip,)
        ).fetchone()
        if not row:
            return False
        if is_image:
            if row["images"] <= 0:
                return False
            conn.execute(
                "UPDATE premium_quota SET images=images-1 WHERE ip=?", (ip,)
            )
        else:
            if row["requests"] <= 0:
                return False
            conn.execute(
                "UPDATE premium_quota SET requests=requests-1 WHERE ip=?", (ip,)
            )
    return True


def create_premium_code(code: str, requests: int, images: int, max_uses: int = 1, note: str = "", expires_at: str | None = None) -> bool:
    from datetime import datetime
    with get_conn() as conn:
        try:
            conn.execute(
                "INSERT INTO premium_codes (code, requests, images, max_uses, created_at, note, expires_at) VALUES (?,?,?,?,?,?,?)",
                (code.upper(), requests, images, max_uses, datetime.now().isoformat(timespec="seconds"), note, expires_at),
            )
            return True
        except Exception:
            return False


def list_premium_codes() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT code, requests, images, max_uses, used_count, created_at, note FROM premium_codes ORDER BY created_at DESC"
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            # Lấy danh sách IP đã dùng mã này
            ips = conn.execute(
                "SELECT ip, ts FROM code_redemptions WHERE code=? ORDER BY ts DESC", (d["code"],)
            ).fetchall()
            d["redemptions"] = [{"ip": row["ip"], "ts": row["ts"]} for row in ips]
            result.append(d)
    return result


def delete_premium_code(code: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM premium_codes WHERE code=?", (code,))
        conn.execute("DELETE FROM code_redemptions WHERE code=?", (code,))


def reset_premium_code(code: str) -> bool:
    """Reset used_count=0 và xóa redemptions — cho phép dùng lại code."""
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE premium_codes SET used_count=0 WHERE code=?", (code,)
        )
        if cur.rowcount == 0:
            return False
        conn.execute("DELETE FROM code_redemptions WHERE code=?", (code,))
    return True


def save_push_subscription(ts: str, endpoint: str, p256dh: str, auth: str) -> None:
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO push_subscriptions (ts, endpoint, p256dh, auth)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(endpoint) DO UPDATE SET ts=excluded.ts, p256dh=excluded.p256dh, auth=excluded.auth
        """, (ts, endpoint, p256dh, auth))


def delete_push_subscription(endpoint: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM push_subscriptions WHERE endpoint=?", (endpoint,))


def get_all_subscriptions() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT endpoint, p256dh, auth FROM push_subscriptions").fetchall()
    return [dict(r) for r in rows]


def save_question(ts: str, question: str, has_image: bool = False) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO questions (ts, question, has_image) VALUES (?, ?, ?)",
            (ts, question[:500], 1 if has_image else 0),
        )


def get_analytics() -> dict:
    with get_conn() as conn:
        total_q = conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
        total_img = conn.execute("SELECT COUNT(*) FROM questions WHERE has_image=1").fetchone()[0]

        # Câu hỏi 7 ngày gần nhất theo ngày
        daily = conn.execute("""
            SELECT DATE(ts) as day, COUNT(*) as cnt
            FROM questions
            WHERE ts >= DATE('now', '-6 days')
            GROUP BY day ORDER BY day
        """).fetchall()

        # 20 câu hỏi gần nhất
        recent = conn.execute(
            "SELECT ts, question, has_image FROM questions ORDER BY id DESC LIMIT 20"
        ).fetchall()

        # Top từ khoá (đếm tần suất từ — chỉ lấy 10k gần nhất để tránh O(n) khi DB lớn)
        all_questions = conn.execute(
            "SELECT question FROM questions ORDER BY id DESC LIMIT 10000"
        ).fetchall()

    # Tính từ khoá phổ biến
    import unicodedata, re
    stop = {"tôi","bị","như","thế","nào","là","có","và","của","để","cho","khi","với","trong","từ","đến","được","một","này","không","hay","gì","về","cần","làm","sao","ra","vì"}
    freq: dict[str, int] = {}
    for (q,) in all_questions:
        text = unicodedata.normalize("NFC", q.lower())
        for word in re.findall(r"[a-zàáảãạăắặẳẵằâấầẩẫậđèéẻẽẹêếềểễệìíỉĩịòóỏõọôốồổỗộơớờởỡợùúủũụưứừửữựỳýỷỹỵ]+", text):
            if len(word) >= 3 and word not in stop:
                freq[word] = freq.get(word, 0) + 1
    top_keywords = sorted(freq.items(), key=lambda x: -x[1])[:15]

    return {
        "total_questions": total_q,
        "total_with_image": total_img,
        "daily": [{"day": r["day"], "count": r["cnt"]} for r in daily],
        "recent": [{"ts": r["ts"], "question": r["question"], "has_image": bool(r["has_image"])} for r in recent],
        "top_keywords": [{"word": w, "count": c} for w, c in top_keywords],
    }


def get_flywheel_data() -> dict:
    """
    Data Flywheel insights:
    1. bad_answers: câu trả lời bị 👎 nhiều lần (group by answer — chính xác hơn group by question)
    2. gaps: cụm từ (bigram + unigram) hay được hỏi nhưng KB chưa cover tốt
    """
    import unicodedata, re
    from app.services.rag import rag

    with get_conn() as conn:
        # FIX: group by answer — cùng câu trả lời tệ xuất hiện với nhiều câu hỏi khác nhau
        bad_rows = conn.execute("""
            SELECT question, answer, COUNT(*) as cnt, MAX(ts) as last_seen
            FROM feedback
            WHERE rating = -1 AND LENGTH(answer) > 10
            GROUP BY answer
            ORDER BY cnt DESC
            LIMIT 15
        """).fetchall()

        # Chỉ sample 10k gần nhất — đủ để phát hiện gaps, tránh O(n) khi DB lớn
        all_qs = conn.execute(
            "SELECT question FROM questions ORDER BY id DESC LIMIT 10000"
        ).fetchall()

    stop = {"tôi","bị","như","thế","nào","là","có","và","của","để","cho","khi",
            "với","trong","từ","đến","được","một","này","không","hay","gì",
            "về","cần","làm","sao","ra","vì","thì","mà","đã","đang","sẽ",
            "ạ","ơi","vậy","nhé","bao","lâu","như","thế","nào","có","phải"}
    _pat = re.compile(
        r"[a-zàáảãạăắặẳẵằâấầẩẫậđèéẻẽẹêếềểễệìíỉĩịòóỏõọôốồổỗộơớờởỡợùúủũụưứừửữựỳýỷỹỵ]+"
    )

    freq: dict[str, int] = {}
    for (q,) in all_qs:
        text = unicodedata.normalize("NFC", q.lower())
        words = [w for w in _pat.findall(text) if len(w) >= 3]
        # Unigram (từ đơn, ≥4 ký tự)
        for w in words:
            if len(w) >= 4 and w not in stop:
                freq[w] = freq.get(w, 0) + 1
        # Bigram (cụm 2 từ — bỏ qua nếu từ đầu hoặc từ sau là stop word)
        for i in range(len(words) - 1):
            if words[i] not in stop and words[i+1] not in stop:
                bigram = f"{words[i]} {words[i+1]}"
                freq[bigram] = freq.get(bigram, 0) + 1

    # Ưu tiên bigram (có ngữ nghĩa rõ hơn) — top 40 theo tần suất
    top = sorted(freq.items(), key=lambda x: -x[1])[:40]
    gaps = []
    for phrase, count in top:
        if count < 2:
            continue
        result = rag.search(phrase, top_k=2)
        # Ngưỡng cao hơn: cần ≥200 ký tự tài liệu liên quan mới coi là đã cover
        covered = bool(result and len(result) > 200)
        if not covered:
            is_bigram = " " in phrase
            gaps.append({"word": phrase, "count": count, "is_bigram": is_bigram})
        if len(gaps) >= 20:
            break

    return {
        "bad_questions": [
            {
                "question":  r["question"],
                "answer":    r["answer"][:200],
                "bad_count": r["cnt"],
                "last_seen": r["last_seen"],
            }
            for r in bad_rows
        ],
        "gaps": gaps,
    }


def save_user_region(device_id: str, region: str) -> None:
    from datetime import datetime
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO user_regions (device_id, region, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(device_id) DO UPDATE SET region=excluded.region, updated_at=excluded.updated_at
        """, (device_id, region, datetime.now().isoformat(timespec="seconds")))


def get_user_region(device_id: str) -> str:
    with get_conn() as conn:
        row = conn.execute("SELECT region FROM user_regions WHERE device_id=?", (device_id,)).fetchone()
    return row["region"] if row else ""


def save_community_tip(device_id: str, title: str, content: str, category: str, region: str) -> int:
    from datetime import datetime
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO community_tips (device_id, title, content, category, region, created_at) VALUES (?,?,?,?,?,?)",
            (device_id, title[:200], content[:8000], category, region,
             datetime.now().isoformat(timespec="seconds")),
        )
        return cur.lastrowid


def update_tip_ai_result(tip_id: int, confidence: float, reason: str, action: str) -> None:
    """Lưu kết quả AI verification vào tip."""
    # Map action sang status
    status = {"approve": "approved", "reject": "rejected"}.get(action, "review")
    with get_conn() as conn:
        conn.execute(
            "UPDATE community_tips SET ai_confidence=?, ai_reason=?, ai_action=?, status=? WHERE id=?",
            (confidence, reason[:500], action, status, tip_id),
        )


def get_review_tips() -> list[dict]:
    """Lấy các tip cần admin xem xét (AI không chắc chắn)."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM community_tips WHERE status='review' ORDER BY created_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def get_pending_tips() -> list[dict]:
    """Backward-compat: trả về tips chờ review."""
    return get_review_tips()


def approve_tip(tip_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM community_tips WHERE id=?", (tip_id,)).fetchone()
        if not row:
            return None
        conn.execute("UPDATE community_tips SET status='approved' WHERE id=?", (tip_id,))
    return dict(row)


def reject_tip(tip_id: int, note: str = "") -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE community_tips SET status='rejected', admin_note=? WHERE id=?", (note, tip_id)
        )
    return cur.rowcount > 0


def save_image_submission(device_id: str, diagnosis: str) -> int:
    from datetime import datetime
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO image_submissions (device_id, diagnosis, created_at) VALUES (?,?,?)",
            (device_id, diagnosis, datetime.now().isoformat(timespec="seconds")),
        )
        return cur.lastrowid


def update_image_feedback(submission_id: int, rating: int) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE image_submissions SET feedback=? WHERE id=?", (rating, submission_id))


def get_image_submissions(limit: int = 50) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, device_id, diagnosis, feedback, label, created_at FROM image_submissions ORDER BY id DESC LIMIT ?",
            (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Points system — tích điểm đổi lượt hỏi
# ---------------------------------------------------------------------------

POINTS_PER_QUESTION = 20  # 20 điểm = 1 lượt hỏi


def _pts_daily_ok(device_id: str, action: str, max_per_day: int) -> bool:
    """
    Kiểm tra giới hạn điểm/ngày qua SQLite (persist qua restart).
    Dùng lại rate_limits table — kind = "pts_{action}".
    """
    from datetime import datetime as _dt2
    today = _dt2.now().strftime("%Y-%m-%d")
    return check_and_increment_rate(device_id, f"pts_{action}", today, max_per_day)


def add_points(device_id: str, action: str, points: int, daily_limit: int | None = None) -> dict:
    """
    Cộng điểm cho user. Mỗi 20 điểm tự động đổi thành 1 lượt hỏi.
    daily_limit: số lần action này được thưởng điểm trong ngày (None = không giới hạn).
    Trả về: {points_added, questions_added, current_points, total_earned}
    """
    # Kiểm tra giới hạn ngày
    if daily_limit is not None and not _pts_daily_ok(device_id, action, daily_limit):
        return {"points_added": 0, "questions_added": 0, "current_points": 0, "total_earned": 0}

    from datetime import datetime as _dt2
    now = _dt2.now().isoformat(timespec="seconds")
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO user_points (device_id, total_earned, current_points, questions_earned, updated_at)
            VALUES (?, ?, ?, 0, ?)
            ON CONFLICT(device_id) DO UPDATE SET
                total_earned   = total_earned   + excluded.total_earned,
                current_points = current_points + excluded.current_points,
                updated_at     = excluded.updated_at
        """, (device_id, points, points, now))

        conn.execute(
            "INSERT INTO points_log (device_id, action, points, created_at) VALUES (?,?,?,?)",
            (device_id, action, points, now),
        )

        row = conn.execute(
            "SELECT total_earned, current_points, questions_earned FROM user_points WHERE device_id=?",
            (device_id,),
        ).fetchone()
        total_earned   = row["total_earned"]
        current_points = row["current_points"]

        # Tự động đổi điểm thành lượt hỏi
        questions_to_add = current_points // POINTS_PER_QUESTION
        if questions_to_add > 0:
            remaining = current_points % POINTS_PER_QUESTION
            conn.execute(
                "UPDATE user_points SET current_points=?, questions_earned=questions_earned+? WHERE device_id=?",
                (remaining, questions_to_add, device_id),
            )
            conn.execute("""
                INSERT INTO premium_quota (ip, requests, images) VALUES (?, ?, 0)
                ON CONFLICT(ip) DO UPDATE SET requests = requests + excluded.requests
            """, (device_id, questions_to_add))
            current_points = remaining

    return {
        "points_added":    points,
        "questions_added": questions_to_add,
        "current_points":  current_points,
        "total_earned":    total_earned,
    }


def get_points(device_id: str) -> dict:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT total_earned, current_points, questions_earned FROM user_points WHERE device_id=?",
            (device_id,),
        ).fetchone()
    return dict(row) if row else {"total_earned": 0, "current_points": 0, "questions_earned": 0}


def get_tip_device_id(tip_id: int) -> str | None:
    """Lấy device_id của người gửi tip (để thưởng điểm khi admin approve)."""
    with get_conn() as conn:
        row = conn.execute("SELECT device_id FROM community_tips WHERE id=?", (tip_id,)).fetchone()
    return row["device_id"] if row else None


# ---------------------------------------------------------------------------
# Rate limits — persistent daily counters (survive server restart)
# ---------------------------------------------------------------------------

def check_and_increment_rate(key: str, kind: str, date: str, limit: int) -> bool:
    """
    Tăng counter nguyên tử và kiểm tra giới hạn trong 1 transaction — không có race condition.
    1. INSERT row với count=0 nếu chưa tồn tại
    2. UPDATE count+1 CHỈ KHI count < limit (atomic trong transaction WAL)
    3. rowcount==0 → đã chạm giới hạn → trả False
    """
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO rate_limits (key, type, date, count) VALUES (?, ?, ?, 0)
            ON CONFLICT(key, type, date) DO NOTHING
        """, (key, kind, date))
        cur = conn.execute("""
            UPDATE rate_limits SET count = count + 1
            WHERE key=? AND type=? AND date=? AND count < ?
        """, (key, kind, date, limit))
    return cur.rowcount > 0


def get_daily_rate(key: str, kind: str, date: str) -> int:
    """Lấy số lần đã dùng trong ngày (để tính remaining quota)."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT count FROM rate_limits WHERE key=? AND type=? AND date=?",
            (key, kind, date),
        ).fetchone()
    return row["count"] if row else 0


def cleanup_old_rates(today: str) -> None:
    """Xóa records cũ hơn hôm nay để DB không phình to."""
    with get_conn() as conn:
        conn.execute("DELETE FROM rate_limits WHERE date < ?", (today,))


# ---------------------------------------------------------------------------
# Session memory — lưu lịch sử hội thoại server-side theo device_id
# ---------------------------------------------------------------------------

SESSION_MAX_MSGS = 20   # giữ tối đa 20 messages (~10 lượt hỏi đáp)
SESSION_TTL_H   = 24   # hết hạn sau 24h không hoạt động


def get_session_messages(device_id: str) -> list[dict]:
    """Lấy lịch sử hội thoại. Trả về [] nếu chưa có hoặc đã hết hạn."""
    import json
    from datetime import datetime, timedelta
    with get_conn() as conn:
        row = conn.execute(
            "SELECT messages, updated_at FROM sessions WHERE device_id=?",
            (device_id,),
        ).fetchone()
    if not row:
        return []
    # Hết hạn sau SESSION_TTL_H giờ không hoạt động
    try:
        updated = datetime.fromisoformat(row["updated_at"])
        if datetime.now() - updated > timedelta(hours=SESSION_TTL_H):
            return []
    except Exception:
        return []
    try:
        return json.loads(row["messages"])
    except Exception:
        return []


def save_session_messages(device_id: str, messages: list[dict]) -> None:
    """Lưu/cập nhật lịch sử hội thoại. Giữ tối đa SESSION_MAX_MSGS messages."""
    import json
    from datetime import datetime
    trimmed = messages[-SESSION_MAX_MSGS:]
    now = datetime.now().isoformat(timespec="seconds")
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO sessions (device_id, messages, updated_at) VALUES (?,?,?)
               ON CONFLICT(device_id) DO UPDATE SET messages=excluded.messages, updated_at=excluded.updated_at""",
            (device_id, json.dumps(trimmed, ensure_ascii=False), now),
        )


def clear_session(device_id: str) -> None:
    """Xóa session của một device (dùng khi user muốn bắt đầu cuộc trò chuyện mới)."""
    with get_conn() as conn:
        conn.execute("DELETE FROM sessions WHERE device_id=?", (device_id,))


# ---------------------------------------------------------------------------
# Evolution log
# ---------------------------------------------------------------------------

def save_evolution_log(ts: str, action: str, topic: str, result: str, detail: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO evolution_log (ts, action, topic, result, detail) VALUES (?,?,?,?,?)",
            (ts, action, topic, result, detail[:500]),
        )


def get_evolution_history(limit: int = 50) -> list[dict]:
    """Lấy lịch sử evolution — chỉ lấy cycle_complete và gap_filled thành công."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT ts, action, topic, result, detail
            FROM evolution_log
            ORDER BY id DESC
            LIMIT ?
        """, (limit,)).fetchall()
    return [dict(r) for r in rows]


def get_evolution_stats() -> dict:
    """Thống kê tổng hợp: tổng bài đã tạo, chu kỳ đã chạy, lần chạy cuối."""
    with get_conn() as conn:
        total_filled = conn.execute(
            "SELECT COUNT(*) FROM evolution_log WHERE action='gap_filled' AND result='success'"
        ).fetchone()[0]
        total_cycles = conn.execute(
            "SELECT COUNT(*) FROM evolution_log WHERE action='cycle_complete'"
        ).fetchone()[0]
        last_cycle = conn.execute(
            "SELECT ts FROM evolution_log WHERE action='cycle_complete' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return {
        "total_filled": total_filled,
        "total_cycles": total_cycles,
        "last_cycle":   last_cycle["ts"] if last_cycle else None,
    }


def save_feedback(ts: str, rating: int, question: str, answer: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO feedback (ts, rating, question, answer) VALUES (?, ?, ?, ?)",
            (ts, rating, question[:500], answer[:1000]),
        )


def get_feedback_stats() -> dict:
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]
        good  = conn.execute("SELECT COUNT(*) FROM feedback WHERE rating = 1").fetchone()[0]
        bad   = conn.execute("SELECT COUNT(*) FROM feedback WHERE rating = -1").fetchone()[0]
        rows  = conn.execute(
            "SELECT ts, rating, question, answer FROM feedback ORDER BY id DESC LIMIT 50"
        ).fetchall()
    return {
        "total": total,
        "good": good,
        "bad": bad,
        "items": [dict(r) for r in rows],
    }
