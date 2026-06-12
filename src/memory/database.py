"""
SQLite database for story memory, dedup tracking, and usage history.

Tables:
  - stories: All discovered stories with URLs, hashes, scores
  - generated_videos: Completed video packages
  - used_hooks: Hook phrases to avoid repetition
  - used_structures: Script structure types for rotation
  - used_templates: Visual templates for variation
"""

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS stories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url_hash TEXT UNIQUE NOT NULL,
    title_hash TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT NOT NULL,
    source_name TEXT,
    published_at TEXT,
    discovered_at TEXT NOT NULL DEFAULT (datetime('now')),
    score_total INTEGER,
    score_data TEXT,
    accepted INTEGER DEFAULT 0,
    processed INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS generated_videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    package_id TEXT UNIQUE NOT NULL,
    story_url_hash TEXT NOT NULL,
    script_hash TEXT NOT NULL,
    structure_type TEXT,
    template_type TEXT,
    accent_color TEXT,
    hook_text TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    output_dir TEXT,
    quality_score INTEGER,
    review_status TEXT DEFAULT 'pending',
    FOREIGN KEY (story_url_hash) REFERENCES stories(url_hash)
);

CREATE TABLE IF NOT EXISTS used_hooks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hook_text TEXT NOT NULL,
    hook_hash TEXT NOT NULL,
    used_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS used_structures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    structure_type TEXT NOT NULL,
    used_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS used_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    template_type TEXT NOT NULL,
    accent_color TEXT,
    used_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS scheduled_posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    package_id TEXT NOT NULL UNIQUE,
    scheduled_time TEXT NOT NULL,
    status TEXT DEFAULT 'queued',
    buffer_post_id TEXT,
    buffer_channel_id TEXT,
    buffer_channel_name TEXT,
    buffer_status TEXT,
    buffer_error TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_stories_url_hash ON stories(url_hash);
CREATE INDEX IF NOT EXISTS idx_stories_title_hash ON stories(title_hash);
CREATE INDEX IF NOT EXISTS idx_videos_story ON generated_videos(story_url_hash);
CREATE INDEX IF NOT EXISTS idx_hooks_hash ON used_hooks(hook_hash);
"""


class Database:
    """SQLite database manager for story memory and dedup tracking."""

    def __init__(self, db_path: str = "./data/news_shorts.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._initialize()

    def _initialize(self) -> None:
        """Create tables if they don't exist."""
        conn = self._get_connection()
        conn.executescript(DB_SCHEMA)
        self._ensure_scheduled_post_columns(conn)
        conn.commit()
        logger.info(f"Database initialized at {self.db_path}")

    def _ensure_scheduled_post_columns(self, conn: sqlite3.Connection) -> None:
        """Add schedule integration columns for existing local databases."""
        existing = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(scheduled_posts)").fetchall()
        }
        columns = {
            "buffer_post_id": "TEXT",
            "buffer_channel_id": "TEXT",
            "buffer_channel_name": "TEXT",
            "buffer_status": "TEXT",
            "buffer_error": "TEXT",
        }
        for name, column_type in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE scheduled_posts ADD COLUMN {name} {column_type}")

    def _get_connection(self) -> sqlite3.Connection:
        """Get or create a database connection."""
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    # ----- Story Operations -----

    def story_exists(self, url_hash: str) -> bool:
        """Check if a story URL has already been seen."""
        conn = self._get_connection()
        row = conn.execute(
            "SELECT 1 FROM stories WHERE url_hash = ?", (url_hash,)
        ).fetchone()
        return row is not None

    def title_similar_exists(self, title_hash: str) -> bool:
        """Check if a story with a similar title has been processed."""
        conn = self._get_connection()
        row = conn.execute(
            "SELECT 1 FROM stories WHERE title_hash = ? AND processed = 1",
            (title_hash,),
        ).fetchone()
        return row is not None

    def add_story(
        self,
        url_hash: str,
        title_hash: str,
        url: str,
        title: str,
        source_name: str,
        published_at: Optional[str] = None,
        score_total: Optional[int] = None,
        score_data: Optional[dict] = None,
        accepted: bool = False,
    ) -> None:
        """Record a discovered story."""
        conn = self._get_connection()
        try:
            conn.execute(
                """INSERT OR IGNORE INTO stories 
                   (url_hash, title_hash, url, title, source_name, published_at,
                    score_total, score_data, accepted)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    url_hash,
                    title_hash,
                    url,
                    title,
                    source_name,
                    published_at,
                    score_total,
                    json.dumps(score_data) if score_data else None,
                    1 if accepted else 0,
                ),
            )
            conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Failed to add story: {e}")

    def mark_story_processed(self, url_hash: str) -> None:
        """Mark a story as having been turned into a video."""
        conn = self._get_connection()
        conn.execute(
            "UPDATE stories SET processed = 1 WHERE url_hash = ?", (url_hash,)
        )
        conn.commit()

    def was_story_processed(self, url_hash: str) -> bool:
        """Check if a story was already turned into a video."""
        conn = self._get_connection()
        row = conn.execute(
            "SELECT processed FROM stories WHERE url_hash = ?", (url_hash,)
        ).fetchone()
        return row is not None and row["processed"] == 1

    # ----- Video Operations -----

    def add_generated_video(
        self,
        package_id: str,
        story_url_hash: str,
        script_hash: str,
        structure_type: str,
        template_type: str,
        accent_color: str,
        hook_text: str,
        output_dir: str,
        quality_score: int,
    ) -> None:
        """Record a generated video package."""
        conn = self._get_connection()
        try:
            conn.execute(
                """INSERT INTO generated_videos 
                   (package_id, story_url_hash, script_hash, structure_type,
                    template_type, accent_color, hook_text, output_dir, quality_score)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    package_id,
                    story_url_hash,
                    script_hash,
                    structure_type,
                    template_type,
                    accent_color,
                    hook_text,
                    output_dir,
                    quality_score,
                ),
            )
            conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Failed to add generated video: {e}")

    # ----- Scheduling Operations -----

    def schedule_post(
        self,
        package_id: str,
        scheduled_time: str,
        status: str = "queued",
        buffer_post_id: Optional[str] = None,
        buffer_channel_id: Optional[str] = None,
        buffer_channel_name: Optional[str] = None,
        buffer_status: Optional[str] = None,
        buffer_error: Optional[str] = None,
    ) -> None:
        """Queue a video for posting."""
        conn = self._get_connection()
        conn.execute(
            """INSERT INTO scheduled_posts
               (package_id, scheduled_time, status, buffer_post_id, buffer_channel_id,
                buffer_channel_name, buffer_status, buffer_error)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(package_id) DO UPDATE SET 
               scheduled_time=excluded.scheduled_time,
               status=excluded.status,
               buffer_post_id=excluded.buffer_post_id,
               buffer_channel_id=excluded.buffer_channel_id,
               buffer_channel_name=excluded.buffer_channel_name,
               buffer_status=excluded.buffer_status,
               buffer_error=excluded.buffer_error""",
            (
                package_id,
                scheduled_time,
                status,
                buffer_post_id,
                buffer_channel_id,
                buffer_channel_name,
                buffer_status,
                buffer_error,
            ),
        )
        conn.commit()

    def get_scheduled_posts(self) -> list[dict]:
        """Get all queued scheduled posts."""
        conn = self._get_connection()
        rows = conn.execute(
            """SELECT package_id, scheduled_time, status, created_at, buffer_post_id,
                      buffer_channel_id, buffer_channel_name, buffer_status, buffer_error
               FROM scheduled_posts
               ORDER BY scheduled_time ASC"""
        ).fetchall()
        return [dict(row) for row in rows]

    def update_schedule_status(self, package_id: str, status: str) -> None:
        """Update the status of a scheduled post."""
        conn = self._get_connection()
        conn.execute(
            "UPDATE scheduled_posts SET status = ? WHERE package_id = ?",
            (status, package_id)
        )
        conn.commit()

    def delete_scheduled_post(self, package_id: str) -> None:
        """Remove a scheduled post row for a deleted package."""
        conn = self._get_connection()
        conn.execute("DELETE FROM scheduled_posts WHERE package_id = ?", (package_id,))
        conn.commit()

    # ----- Hook Operations -----

    def add_used_hook(self, hook_text: str, hook_hash: str) -> None:
        """Record a used hook phrase."""
        conn = self._get_connection()
        conn.execute(
            "INSERT INTO used_hooks (hook_text, hook_hash) VALUES (?, ?)",
            (hook_text, hook_hash),
        )
        conn.commit()

    def get_recent_hooks(self, limit: int = 20) -> list[str]:
        """Get recently used hook phrases."""
        conn = self._get_connection()
        rows = conn.execute(
            "SELECT hook_text FROM used_hooks ORDER BY used_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [row["hook_text"] for row in rows]

    # ----- Structure Operations -----

    def add_used_structure(self, structure_type: str) -> None:
        """Record a used script structure."""
        conn = self._get_connection()
        conn.execute(
            "INSERT INTO used_structures (structure_type) VALUES (?)",
            (structure_type,),
        )
        conn.commit()

    def get_recent_structures(self, limit: int = 10) -> list[str]:
        """Get recently used script structures."""
        conn = self._get_connection()
        rows = conn.execute(
            "SELECT structure_type FROM used_structures ORDER BY used_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [row["structure_type"] for row in rows]

    # ----- Template Operations -----

    def add_used_template(self, template_type: str, accent_color: str) -> None:
        """Record a used visual template."""
        conn = self._get_connection()
        conn.execute(
            "INSERT INTO used_templates (template_type, accent_color) VALUES (?, ?)",
            (template_type, accent_color),
        )
        conn.commit()

    def get_recent_templates(self, limit: int = 10) -> list[tuple[str, str]]:
        """Get recently used templates with their colors."""
        conn = self._get_connection()
        rows = conn.execute(
            "SELECT template_type, accent_color FROM used_templates ORDER BY used_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [(row["template_type"], row["accent_color"]) for row in rows]

    # ----- Stats -----

    def get_stats(self) -> dict:
        """Get database statistics."""
        conn = self._get_connection()
        stats = {}
        stats["total_stories"] = conn.execute("SELECT COUNT(*) FROM stories").fetchone()[0]
        stats["processed_stories"] = conn.execute(
            "SELECT COUNT(*) FROM stories WHERE processed = 1"
        ).fetchone()[0]
        stats["total_videos"] = conn.execute(
            "SELECT COUNT(*) FROM generated_videos"
        ).fetchone()[0]
        stats["total_hooks"] = conn.execute("SELECT COUNT(*) FROM used_hooks").fetchone()[0]
        return stats
