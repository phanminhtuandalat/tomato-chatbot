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


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
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
            "SELECT requests, images, max_uses, used_count FROM premium_codes WHERE code=?",
            (code.upper(),)
        ).fetchone()
        if not row:
            return {"ok": False, "reason": "Mã không hợp lệ"}
        if row["used_count"] >= row["max_uses"]:
            return {"ok": False, "reason": "Mã đã hết lượt sử dụng"}
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


def create_premium_code(code: str, requests: int, images: int, max_uses: int = 1, note: str = "") -> bool:
    from datetime import datetime
    with get_conn() as conn:
        try:
            conn.execute(
                "INSERT INTO premium_codes (code, requests, images, max_uses, created_at, note) VALUES (?,?,?,?,?,?)",
                (code.upper(), requests, images, max_uses, datetime.now().isoformat(timespec="seconds"), note),
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

        # Top từ khoá (đếm tần suất từ)
        all_questions = conn.execute("SELECT question FROM questions").fetchall()

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
    1. bad_questions: câu hỏi bị đánh giá 👎 nhiều nhất
    2. gaps: từ khoá hay được hỏi nhưng knowledge base chưa cover tốt
    """
    import unicodedata, re
    from app.services.rag import rag

    with get_conn() as conn:
        # Câu hỏi bị đánh giá 👎 (nhóm theo nội dung)
        bad_rows = conn.execute("""
            SELECT question, answer, COUNT(*) as cnt, MAX(ts) as last_seen
            FROM feedback
            WHERE rating = -1 AND LENGTH(question) > 5
            GROUP BY question
            ORDER BY cnt DESC
            LIMIT 15
        """).fetchall()

        # Tất cả câu hỏi để tính gap
        all_qs = conn.execute("SELECT question FROM questions").fetchall()

    # Tính tần suất từ khoá (giống get_analytics)
    stop = {"tôi","bị","như","thế","nào","là","có","và","của","để","cho","khi",
            "với","trong","từ","đến","được","một","này","không","hay","gì",
            "về","cần","làm","sao","ra","vì","thì","mà","đã","đang","sẽ"}
    freq: dict[str, int] = {}
    for (q,) in all_qs:
        text = unicodedata.normalize("NFC", q.lower())
        for word in re.findall(
            r"[a-zàáảãạăắặẳẵằâấầẩẫậđèéẻẽẹêếềểễệìíỉĩịòóỏõọôốồổỗộơớờởỡợùúủũụưứừửữựỳýỷỹỵ]+",
            text
        ):
            if len(word) >= 3 and word not in stop:
                freq[word] = freq.get(word, 0) + 1

    # Kiểm tra từng từ khoá có được knowledge base cover không
    top_keywords = sorted(freq.items(), key=lambda x: -x[1])[:30]
    gaps = []
    for word, count in top_keywords:
        if count < 2:
            continue
        result = rag.search(word, top_k=1)
        covered = bool(result and len(result) > 50)
        if not covered:
            gaps.append({"word": word, "count": count})

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
        "gaps": gaps[:15],
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
            (device_id, title[:200], content[:3000], category, region,
             datetime.now().isoformat(timespec="seconds")),
        )
        return cur.lastrowid


def get_pending_tips() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM community_tips WHERE status='pending' ORDER BY created_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


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
