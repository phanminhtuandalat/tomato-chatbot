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
