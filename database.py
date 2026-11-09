import sqlite3
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any

logger = logging.getLogger("atrees.database")
DB_PATH = Path(__file__).resolve().parent / "jobs.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Initializes the SQLite database schema."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT NOT NULL,
                url TEXT,
                channel_title TEXT,
                channel_id TEXT,
                message_id INTEGER,
                job_text TEXT,
                summary TEXT,
                estimated_budget TEXT,
                proposal TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending', -- pending, approved, skipped, submitted
                bot_message_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_url ON jobs(url);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_bot_msg ON jobs(bot_message_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);")
        conn.commit()
    logger.info("SQLite database initialized at: %s", DB_PATH)


def insert_job(
    platform: str,
    proposal: str,
    url: str = "",
    channel_title: str = "",
    channel_id: str = "",
    message_id: Optional[int] = None,
    job_text: str = "",
    summary: str = "",
    estimated_budget: str = "",
    status: str = "pending",
) -> int:
    """Inserts a new job in 'pending' status and returns the generated job ID."""
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO jobs (
                platform, url, channel_title, channel_id, message_id,
                job_text, summary, estimated_budget, proposal, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                platform,
                url,
                channel_title,
                str(channel_id),
                message_id,
                job_text,
                summary,
                estimated_budget,
                proposal,
                status,
                now,
                now,
            ),
        )
        conn.commit()
        return cursor.lastrowid


def link_bot_message_id(job_id: int, bot_message_id: int) -> None:
    """Links the Telegram bot alert message ID with the job."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE jobs SET bot_message_id = ? WHERE id = ?",
            (bot_message_id, job_id),
        )
        conn.commit()


def get_job_by_id(job_id: int) -> Optional[dict[str, Any]]:
    """Retrieves a job by its primary key ID."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_job_by_bot_message_id(bot_message_id: int) -> Optional[dict[str, Any]]:
    """Retrieves a job by the Telegram message ID sent by the bot."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM jobs WHERE bot_message_id = ?", (bot_message_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def update_job_status(job_id: int, status: str) -> bool:
    """Updates the status of a job (e.g. 'approved', 'skipped', 'submitted')."""
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE jobs SET status = ?, updated_at = ? WHERE id = ?",
            (status, now, job_id),
        )
        conn.commit()
        return cursor.rowcount > 0


def update_job_proposal(job_id: int, new_proposal: str) -> bool:
    """Updates the proposal text of a job (when tweaked by the user)."""
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE jobs SET proposal = ?, updated_at = ? WHERE id = ?",
            (new_proposal, now, job_id),
        )
        conn.commit()
        return cursor.rowcount > 0


def is_job_url_seen(url: str) -> bool:
    """Checks if a URL has already been recorded in the database."""
    if not url:
        return False
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM jobs WHERE url = ? LIMIT 1", (url,))
        return cursor.fetchone() is not None


def get_jobs_stats() -> dict[str, int]:
    """Returns aggregated statistics of all jobs by status."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending,
                SUM(CASE WHEN status = 'approved' THEN 1 ELSE 0 END) as approved,
                SUM(CASE WHEN status = 'submitted' THEN 1 ELSE 0 END) as submitted,
                SUM(CASE WHEN status = 'skipped' THEN 1 ELSE 0 END) as skipped,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed
            FROM jobs
            """
        )
        row = cursor.fetchone()
        if not row:
            return {"total": 0, "pending": 0, "approved": 0, "submitted": 0, "skipped": 0, "failed": 0}
        return {
            "total": row["total"] or 0,
            "pending": row["pending"] or 0,
            "approved": row["approved"] or 0,
            "submitted": row["submitted"] or 0,
            "skipped": row["skipped"] or 0,
            "failed": row["failed"] or 0,
        }


def get_pending_jobs(limit: int = 5) -> list[dict[str, Any]]:
    """Retrieves the most recent pending jobs."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM jobs 
            WHERE status = 'pending' 
            ORDER BY id DESC 
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]


# Auto-initialize database schema on import
init_db()

