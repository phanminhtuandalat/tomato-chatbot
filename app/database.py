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
