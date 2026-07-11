"""
app/db/database.py
------------------
SQLite database setup and query logging.
Creates query_logs table to store every RAG query for evaluation.
"""

import sqlite3
import json
import uuid
import logging
from pathlib import Path
from datetime import datetime
from contextlib import contextmanager

log = logging.getLogger("RAG_Pipeline")

DB_PATH = Path("data/rag_logs.db")


def init_db():
    """Create tables if they don't exist. Called once at startup."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS query_logs (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                query_id      TEXT NOT NULL UNIQUE,
                question      TEXT NOT NULL,
                rewritten_question TEXT,
                answer        TEXT,
                contexts      TEXT,   -- JSON array of retrieved chunk texts
                cache_hit     INTEGER DEFAULT 0,
                latency_ms    REAL,
                created_at    TEXT NOT NULL
            )
        """)
        conn.commit()
    log.info("✅ SQLite DB initialized at %s", DB_PATH)


@contextmanager
def _get_conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def log_query(
    question: str,
    answer: str,
    contexts: list[str],
    rewritten_question: str = None,
    cache_hit: bool = False,
    latency_ms: float = None,
) -> str:
    """
    Insert a completed query+answer into query_logs.
    Returns the generated query_id (UUID).
    """
    query_id = str(uuid.uuid4())
    with _get_conn() as conn:
        conn.execute(
            """
            INSERT INTO query_logs
                (query_id, question, rewritten_question, answer, contexts,
                 cache_hit, latency_ms, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                query_id,
                question,
                rewritten_question,
                answer,
                json.dumps(contexts, ensure_ascii=False),
                int(cache_hit),
                latency_ms,
                datetime.utcnow().isoformat(),
            ),
        )
        conn.commit()
    log.info("[DB] Logged query_id=%s", query_id)
    return query_id


def get_query(query_id: str) -> dict | None:
    """Fetch a single log entry by query_id."""
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM query_logs WHERE query_id = ?", (query_id,)
        ).fetchone()
    if not row:
        return None
    return _row_to_dict(row)


def get_recent_queries(limit: int = 20) -> list[dict]:
    """Fetch the most recent N query logs."""
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM query_logs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["contexts"] = json.loads(d["contexts"]) if d["contexts"] else []
    d["cache_hit"] = bool(d["cache_hit"])
    return d