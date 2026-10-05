from __future__ import annotations

import hashlib
import hmac
import io
import json
import os
import re
import secrets
import sqlite3
import threading
import time
import urllib.request
import uuid
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path

from flask import Flask, Response, abort, g, jsonify, request, send_from_directory
from PIL import Image, ImageOps
from werkzeug.security import check_password_hash, generate_password_hash


BASE_DIR = Path(__file__).resolve().parent
IS_PRODUCTION = os.getenv("FLASK_ENV", "").lower() == "production" or os.getenv("RENDER", "").lower() == "true"
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
USE_POSTGRES = DATABASE_URL.startswith(("postgres://", "postgresql://"))
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", str(BASE_DIR / "data" / "fangfei.sqlite3"))).resolve()
SESSION_COOKIE = "fangfei_session"
CSRF_COOKIE = "fangfei_csrf"
SESSION_DAYS = 14
MAX_BODY_BYTES = 6 * 1024 * 1024
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_JSON_DEPTH = 8
MAX_LIST_ITEMS = 100
MAX_STRING_CHARS = 10000
MAX_WORK_BODY_CHARS = 20000  # 投稿正文总字数上限，其他字段继续使用通用上限
USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,32}$")
ADMIN_USERNAME_RE = re.compile(r"^[\w\u4e00-\u9fff]{1,32}$", re.UNICODE)
PUBLIC_ROOTS = {"assets", "css", "images", "js", "vendor"}
PUBLIC_FILES = {"app.js", "styles.css", "pet.js", "favicon.ico"}
WORK_CATEGORIES = {"小说", "诗歌", "散文", "随笔", "剧本", "科幻", "杂文", "其他"}
WORK_FORMATS = {"single", "serial"}
SERIAL_STATUSES = {"ONGOING", "COMPLETED", "HIATUS"}
SHELF_STATUSES = {"READING", "FINISHED"}
PROFILE_COVER_THEMES = {"starry", "deepsea", "sky", "flower", "dragon", "qingli", ""}
RANKING_WEIGHTS = {"views": 1, "likes": 8, "favorites": 10, "comments": 4}

AVATAR_NAME_RE = re.compile(r"^[a-f0-9]{32}[.]webp$")
MAX_AVATAR_BYTES = 5 * 1024 * 1024
AVATAR_SIZE = 512
AVATAR_FORMATS = {"JPEG", "MPO", "PNG", "WEBP"}
BOOK_SHARE_IMAGE_SIZE = 1400

WORK_VISIBILITY = {"PUBLIC", "PRIVATE"}
WORK_STATUSES = {"draft", "pending", "pending_agent", "pending_review", "published", "rejected", "hidden"}
AGENT_POLICY_VERSION = "fangfei-agent-1.0"
AGENT_MODEL_NAME = "rules-v1"
TOPIC_STATUSES = {"DRAFT", "PUBLISHED", "ENDED", "ARCHIVED"}

# Agent 审核的字数参考值（用户要求：由类型最低字数下调为 5 字）
AGENT_MIN_WORDS = 5

# 有效作品的类型最低字数，集中配置，供排行榜与统计复用（排行榜口径未改动）
MIN_WORDS_BY_CATEGORY = {
    "小说": 800,
    "剧本": 500,
    "散文": 400,
    "随笔": 300,
    "杂文": 300,
    "科幻": 800,
    "诗歌": 60,
    "其他": 200,
}
DEFAULT_MIN_WORDS = 200

# 风控阈值集中配置，避免散落到各处
RISK_CONFIG = {
    "new_account_ms": 24 * 60 * 60 * 1000,
    "like_rate_per_hour": 60,
    "new_account_like_per_hour": 20,
    "like_burst_window_ms": 60 * 1000,
    "like_burst_max": 15,
    "same_author_like_per_hour": 25,
    "comment_rate_per_hour": 20,
    "new_account_comment_per_hour": 5,
    "comment_duplicate_window_ms": 10 * 60 * 1000,
    "similarity_high": 0.82,
    "similarity_medium": 0.60,
    "similarity_min_chars": 120,
}

app = Flask(__name__)
app.config.update(
    MAX_CONTENT_LENGTH=MAX_BODY_BYTES,
    JSON_SORT_KEYS=False,
)

RATE_LOCK = threading.Lock()
RATE_BUCKETS: dict[str, deque[float]] = defaultdict(deque)


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE COLLATE NOCASE,
  display_name TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'reader' CHECK (role IN ('reader', 'admin')),
  bio TEXT NOT NULL DEFAULT '',
  awards INTEGER,
  account_status TEXT NOT NULL DEFAULT 'active',
  avatar TEXT NOT NULL DEFAULT '',
  cover_theme TEXT NOT NULL DEFAULT '',
  literary_preferences TEXT NOT NULL DEFAULT '',
  genres_json TEXT NOT NULL DEFAULT '[]',
  created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS admin_roles (
  user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  level TEXT NOT NULL CHECK (level IN ('super', 'senior')),
  appointed_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
  appointed_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_admin_roles_level ON admin_roles(level);

CREATE TABLE IF NOT EXISTS admin_transfers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  old_admin_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  new_admin_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  operator_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  reason TEXT NOT NULL DEFAULT '',
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_admin_transfers_created ON admin_transfers(created_at DESC);

CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  csrf_token TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  last_seen_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS works (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  author_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  category TEXT NOT NULL,
  work_format TEXT NOT NULL DEFAULT 'single',
  serial_status TEXT NOT NULL DEFAULT 'ONGOING',
  tags_json TEXT NOT NULL DEFAULT '[]',
  excerpt TEXT NOT NULL DEFAULT '',
  body_json TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'published',
  review_note TEXT NOT NULL DEFAULT '',
  is_public INTEGER NOT NULL DEFAULT 1,
  allow_comments INTEGER NOT NULL DEFAULT 1,
  allow_favorites INTEGER NOT NULL DEFAULT 1,
  original_confirmed INTEGER NOT NULL DEFAULT 0,
  rights_confirmed INTEGER NOT NULL DEFAULT 0,
  views INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  published_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_works_author ON works(author_id);
CREATE INDEX IF NOT EXISTS idx_works_status_created ON works(status, created_at DESC);

CREATE TABLE IF NOT EXISTS chapters (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  work_id INTEGER NOT NULL REFERENCES works(id) ON DELETE CASCADE,
  chapter_number INTEGER NOT NULL,
  title TEXT NOT NULL,
  content TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'DRAFT',
  review_note TEXT NOT NULL DEFAULT '',
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  published_at INTEGER,
  UNIQUE (work_id, chapter_number)
);
CREATE INDEX IF NOT EXISTS idx_chapters_work_number ON chapters(work_id, chapter_number);

CREATE TABLE IF NOT EXISTS bookshelf (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  work_id INTEGER NOT NULL REFERENCES works(id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'READING',
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  UNIQUE (user_id, work_id)
);
CREATE INDEX IF NOT EXISTS idx_bookshelf_user ON bookshelf(user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS reading_progress (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  work_id INTEGER NOT NULL REFERENCES works(id) ON DELETE CASCADE,
  last_chapter_id INTEGER NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
  last_read_at INTEGER NOT NULL,
  UNIQUE (user_id, work_id)
);
CREATE INDEX IF NOT EXISTS idx_reading_progress_user ON reading_progress(user_id, last_read_at DESC);

CREATE TABLE IF NOT EXISTS work_follows (
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  work_id INTEGER NOT NULL REFERENCES works(id) ON DELETE CASCADE,
  created_at INTEGER NOT NULL,
  PRIMARY KEY (user_id, work_id)
);
CREATE INDEX IF NOT EXISTS idx_work_follows_work ON work_follows(work_id);

CREATE TABLE IF NOT EXISTS chapter_comments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  chapter_id INTEGER NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  parent_id INTEGER REFERENCES chapter_comments(id) ON DELETE CASCADE,
  text TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  deleted_at INTEGER,
  effective INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_chapter_comments_chapter_created ON chapter_comments(chapter_id, created_at);

CREATE TABLE IF NOT EXISTS chapter_comment_likes (
  comment_id INTEGER NOT NULL REFERENCES chapter_comments(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at INTEGER NOT NULL,
  PRIMARY KEY (comment_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_chapter_comment_likes_user ON chapter_comment_likes(user_id);

CREATE TABLE IF NOT EXISTS work_versions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  work_id INTEGER NOT NULL REFERENCES works(id) ON DELETE CASCADE,
  author_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  version_number INTEGER NOT NULL,
  title TEXT NOT NULL,
  category TEXT NOT NULL,
  tags_json TEXT NOT NULL DEFAULT '[]',
  excerpt TEXT NOT NULL DEFAULT '',
  body_json TEXT NOT NULL DEFAULT '[]',
  change_reason TEXT NOT NULL DEFAULT '',
  created_at INTEGER NOT NULL,
  UNIQUE (work_id, version_number)
);
CREATE INDEX IF NOT EXISTS idx_work_versions_work ON work_versions(work_id, version_number DESC);

CREATE TABLE IF NOT EXISTS book_shares (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  book_title TEXT NOT NULL,
  book_author TEXT NOT NULL DEFAULT '',
  recommendation TEXT NOT NULL,
  tags_json TEXT NOT NULL DEFAULT '[]',
  image_name TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'published',
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_book_shares_status_created ON book_shares(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_book_shares_user ON book_shares(user_id);

CREATE TABLE IF NOT EXISTS book_share_praises (
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  share_id INTEGER NOT NULL REFERENCES book_shares(id) ON DELETE CASCADE,
  created_at INTEGER NOT NULL,
  PRIMARY KEY (user_id, share_id)
);
CREATE INDEX IF NOT EXISTS idx_book_share_praises_share ON book_share_praises(share_id);

CREATE TABLE IF NOT EXISTS work_views (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  work_id INTEGER NOT NULL REFERENCES works(id) ON DELETE CASCADE,
  viewed_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_work_views_period ON work_views(work_id, viewed_at);

CREATE TABLE IF NOT EXISTS likes (
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  work_id INTEGER NOT NULL REFERENCES works(id) ON DELETE CASCADE,
  created_at INTEGER NOT NULL,
  PRIMARY KEY (user_id, work_id)
);
CREATE INDEX IF NOT EXISTS idx_likes_work ON likes(work_id);

CREATE TABLE IF NOT EXISTS favorites (
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  work_id INTEGER NOT NULL REFERENCES works(id) ON DELETE CASCADE,
  created_at INTEGER NOT NULL,
  PRIMARY KEY (user_id, work_id)
);
CREATE INDEX IF NOT EXISTS idx_favorites_work ON favorites(work_id);

CREATE TABLE IF NOT EXISTS follows (
  follower_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  author_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at INTEGER NOT NULL,
  PRIMARY KEY (follower_id, author_id),
  CHECK (follower_id <> author_id)
);
CREATE INDEX IF NOT EXISTS idx_follows_author ON follows(author_id);

CREATE TABLE IF NOT EXISTS blocks (
  blocker_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  blocked_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at INTEGER NOT NULL,
  PRIMARY KEY (blocker_id, blocked_id),
  CHECK (blocker_id <> blocked_id)
);
CREATE INDEX IF NOT EXISTS idx_blocks_blocked ON blocks(blocked_id);

CREATE TABLE IF NOT EXISTS comments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  work_id INTEGER NOT NULL REFERENCES works(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  text TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  deleted_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_comments_work_created ON comments(work_id, created_at);

CREATE TABLE IF NOT EXISTS activities (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  starts_at TEXT NOT NULL DEFAULT '',
  ends_at TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT '筹备中',
  rules TEXT NOT NULL DEFAULT '',
  created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS announcements (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  author_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  content TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'published',
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_announcements_status_created ON announcements(status, created_at DESC);

CREATE TABLE IF NOT EXISTS monthly_picks (
  month TEXT NOT NULL,
  work_id INTEGER NOT NULL REFERENCES works(id) ON DELETE CASCADE,
  rank INTEGER NOT NULL DEFAULT 1,
  reason TEXT NOT NULL DEFAULT '',
  PRIMARY KEY (month, work_id)
);

CREATE TABLE IF NOT EXISTS monthly_awards (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  work_id INTEGER NOT NULL REFERENCES works(id) ON DELETE CASCADE,
  author_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  category TEXT NOT NULL DEFAULT '',
  month TEXT NOT NULL,
  rank INTEGER NOT NULL DEFAULT 1,
  reason TEXT NOT NULL DEFAULT '',
  selected_at INTEGER NOT NULL,
  selected_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
  status TEXT NOT NULL DEFAULT 'active'
);
CREATE INDEX IF NOT EXISTS idx_monthly_awards_month ON monthly_awards(month, status, rank);

CREATE TABLE IF NOT EXISTS conversations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_low_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  user_high_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  UNIQUE (user_low_id, user_high_id),
  CHECK (user_low_id < user_high_id)
);

CREATE TABLE IF NOT EXISTS conversation_hidden (
  conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  hidden INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (conversation_id, user_id)
);

CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  sender_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  text TEXT NOT NULL,
  reply_to_id INTEGER REFERENCES messages(id) ON DELETE SET NULL,
  created_at INTEGER NOT NULL,
  read_at INTEGER,
  recalled_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_messages_conversation_created ON messages(conversation_id, created_at);

CREATE TABLE IF NOT EXISTS message_settings (
  user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  allow_strangers INTEGER NOT NULL DEFAULT 1,
  recall_minutes INTEGER NOT NULL DEFAULT 2,
  notifications INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS notifications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  type TEXT NOT NULL DEFAULT 'system',
  text TEXT NOT NULL,
  link TEXT NOT NULL DEFAULT '',
  work_id INTEGER,
  chapter_id INTEGER,
  created_at INTEGER NOT NULL,
  read_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_notifications_user_created ON notifications(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS reports (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  reporter_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  type TEXT NOT NULL,
  target_id TEXT NOT NULL DEFAULT '',
  target_label TEXT NOT NULL DEFAULT '',
  reason TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT '',
  message_excerpt TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT '待处理',
  created_at INTEGER NOT NULL,
  handled_at INTEGER,
  handled_by INTEGER REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS idx_reports_status_created ON reports(status, created_at DESC);

CREATE TABLE IF NOT EXISTS audit_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  actor_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
  action TEXT NOT NULL,
  target_type TEXT NOT NULL DEFAULT '',
  target_id TEXT NOT NULL DEFAULT '',
  detail TEXT NOT NULL DEFAULT '',
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs(created_at DESC);

CREATE TABLE IF NOT EXISTS topics (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  start_at INTEGER NOT NULL DEFAULT 0,
  end_at INTEGER NOT NULL DEFAULT 0,
  created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
  published_at INTEGER,
  status TEXT NOT NULL DEFAULT 'DRAFT',
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_topics_status ON topics(status, created_at DESC);

CREATE TABLE IF NOT EXISTS risk_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,
  level TEXT NOT NULL DEFAULT 'MEDIUM',
  detail TEXT NOT NULL DEFAULT '',
  target_type TEXT NOT NULL DEFAULT '',
  target_id TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'pending',
  created_at INTEGER NOT NULL,
  handled_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
  handled_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_risk_events_status ON risk_events(status, created_at DESC);

CREATE TABLE IF NOT EXISTS plagiarism_checks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  work_id INTEGER NOT NULL REFERENCES works(id) ON DELETE CASCADE,
  matched_work_id INTEGER REFERENCES works(id) ON DELETE SET NULL,
  score REAL NOT NULL DEFAULT 0,
  level TEXT NOT NULL DEFAULT 'low',
  status TEXT NOT NULL DEFAULT 'open',
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_plagiarism_work ON plagiarism_checks(work_id);

CREATE TABLE IF NOT EXISTS agent_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  agent_run_id TEXT NOT NULL UNIQUE,
  content_id INTEGER NOT NULL,
  content_type TEXT NOT NULL DEFAULT 'work',
  user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
  status TEXT NOT NULL DEFAULT 'running',
  error TEXT NOT NULL DEFAULT '',
  created_at INTEGER NOT NULL,
  duration INTEGER NOT NULL DEFAULT 0,
  policy_version TEXT NOT NULL DEFAULT '',
  model TEXT NOT NULL DEFAULT '',
  prompt_version TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_agent_runs_content ON agent_runs(content_type, content_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_runs_created ON agent_runs(created_at DESC);

CREATE TABLE IF NOT EXISTS agent_moderation_results (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  agent_run_id TEXT NOT NULL UNIQUE,
  content_id INTEGER NOT NULL,
  content_type TEXT NOT NULL DEFAULT 'work',
  risk_level TEXT NOT NULL DEFAULT 'LOW',
  category TEXT NOT NULL DEFAULT '',
  confidence REAL NOT NULL DEFAULT 0,
  recommendation TEXT NOT NULL DEFAULT 'REVIEW',
  needs_human_review INTEGER NOT NULL DEFAULT 1,
  details_json TEXT NOT NULL DEFAULT '[]',
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agent_results_content ON agent_moderation_results(content_type, content_id, created_at DESC);

CREATE TABLE IF NOT EXISTS agent_review_tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  agent_run_id TEXT NOT NULL UNIQUE,
  work_id INTEGER NOT NULL REFERENCES works(id) ON DELETE CASCADE,
  reason TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'open',
  created_at INTEGER NOT NULL,
  resolved_at INTEGER,
  resolved_by INTEGER REFERENCES users(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_agent_tasks_status ON agent_review_tasks(status, created_at DESC);

CREATE TABLE IF NOT EXISTS avatar_blobs (
  name TEXT PRIMARY KEY,
  content_type TEXT NOT NULL DEFAULT 'image/webp',
  data BLOB NOT NULL,
  created_at INTEGER NOT NULL
);
"""

SCHEMA_PG = (
    SCHEMA.replace("PRAGMA foreign_keys = ON;", "")
    .replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY")
    .replace(" COLLATE NOCASE", "")
    .replace("data BLOB NOT NULL", "data BYTEA NOT NULL")
)
# 毫秒时间戳超出 PostgreSQL INTEGER 范围，剩余整型列统一提升为 BIGINT
SCHEMA_PG = re.sub(r"\bINTEGER\b", "BIGINT", SCHEMA_PG)
SCHEMA_PG += "\nCREATE UNIQUE INDEX IF NOT EXISTS idx_users_username_lower ON users (LOWER(username));\n"

AUTO_ID_TABLES = {
    "users", "admin_transfers", "works", "work_views", "comments", "activities",
    "announcements", "monthly_awards", "conversations", "messages",
    "notifications", "reports", "audit_logs", "topics", "risk_events", "plagiarism_checks",
    "agent_runs", "agent_moderation_results", "agent_review_tasks",
    "work_versions", "book_shares", "chapters", "bookshelf", "reading_progress", "chapter_comments",
}


def _translate_pg_sql(sql: str) -> str:
    ignore = re.search(r"\bINSERT\s+OR\s+IGNORE\s+INTO\b", sql, flags=re.IGNORECASE)
    if ignore:
        sql = re.sub(r"\bINSERT\s+OR\s+IGNORE\s+INTO\b", "INSERT INTO", sql, count=1, flags=re.IGNORECASE)
    sql = sql.replace("?", "%s")
    if ignore and not re.search(r"\bON\s+CONFLICT\b", sql, flags=re.IGNORECASE):
        sql = sql.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
    match = re.match(r"^\s*INSERT\s+INTO\s+([A-Za-z_][A-Za-z0-9_]*)", sql, flags=re.IGNORECASE)
    if match and match.group(1).lower() in AUTO_ID_TABLES and not re.search(r"\bRETURNING\b", sql, flags=re.IGNORECASE):
        sql = sql.rstrip().rstrip(";") + " RETURNING id"
    return sql


class PgCursor:
    def __init__(self, cursor):
        self._cursor = cursor
        self.lastrowid = None

    def execute(self, query, params=None):
        query = _translate_pg_sql(query)
        self._cursor.execute(query, params or ())
        if re.search(r"\bRETURNING\s+id\b", query, flags=re.IGNORECASE):
            row = self._cursor.fetchone()
            self.lastrowid = row["id"] if isinstance(row, dict) else (row[0] if row else None)
        return self

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    def close(self):
        return self._cursor.close()

    @property
    def rowcount(self):
        return self._cursor.rowcount

    def __iter__(self):
        return iter(self._cursor)


class PgConnection:
    def __init__(self, connection):
        self._connection = connection

    def execute(self, query, params=None):
        return PgCursor(self._connection.cursor()).execute(query, params)

    def executescript(self, script):
        with self._connection.cursor() as cursor:
            for statement in script.split(";"):
                statement = statement.strip()
                if statement:
                    cursor.execute(statement)

    def commit(self):
        return self._connection.commit()

    def rollback(self):
        return self._connection.rollback()

    def close(self):
        return self._connection.close()


def _connect_db():
    if USE_POSTGRES:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("PostgreSQL requires psycopg[binary]. Install requirements.txt or use SQLite.") from exc
        return PgConnection(psycopg.connect(DATABASE_URL, row_factory=dict_row))
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DATABASE_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def now_ms() -> int:
    return int(time.time() * 1000)


def iso_time(ms: int | None) -> str:
    if not ms:
        return ""
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M")


def get_db():
    if "db" not in g:
        g.db = _connect_db()
    return g.db


@app.teardown_appcontext
def close_db(_error: BaseException | None) -> None:
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def migrate_columns(conn: sqlite3.Connection) -> None:
    migrations = {
        "users": {
            "account_status": "TEXT NOT NULL DEFAULT 'active'",
            "avatar": "TEXT NOT NULL DEFAULT ''",
            "cover_theme": "TEXT NOT NULL DEFAULT ''",
            "literary_preferences": "TEXT NOT NULL DEFAULT ''",
            "genres_json": "TEXT NOT NULL DEFAULT '[]'",
            "risk_level": "TEXT NOT NULL DEFAULT 'LOW'",
        },
        "works": {
            "work_format": "TEXT NOT NULL DEFAULT 'single'",
            "serial_status": "TEXT NOT NULL DEFAULT 'ONGOING'",
            "is_public": "INTEGER NOT NULL DEFAULT 1",
            "allow_comments": "INTEGER NOT NULL DEFAULT 1",
            "allow_favorites": "INTEGER NOT NULL DEFAULT 1",
            "original_confirmed": "INTEGER NOT NULL DEFAULT 0",
            "rights_confirmed": "INTEGER NOT NULL DEFAULT 0",
            "visibility": "TEXT NOT NULL DEFAULT 'PUBLIC'",
            "topic_id": "INTEGER",
            "citation_declared": "INTEGER NOT NULL DEFAULT 0",
            "citation_sources": "TEXT NOT NULL DEFAULT ''",
        },
        "likes": {"effective": "INTEGER NOT NULL DEFAULT 1"},
        "comments": {"effective": "INTEGER NOT NULL DEFAULT 1"},
        "reports": {
            "suspected_original_url": "TEXT NOT NULL DEFAULT ''",
            "handled_action": "TEXT NOT NULL DEFAULT ''",
        },
        "notifications": {
            "work_id": "INTEGER",
            "chapter_id": "INTEGER",
        },
    }
    for table, columns in migrations.items():
        if USE_POSTGRES:
            rows = conn.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = ?",
                (table,),
            ).fetchall()
            existing = {row["column_name"] for row in rows}
        else:
            existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        for name, ddl in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def sync_system_data() -> None:
    conn = _connect_db()
    try:
        has_super = conn.execute("SELECT 1 FROM admin_roles WHERE level = 'super' LIMIT 1").fetchone() is not None
        senior_count = conn.execute("SELECT COUNT(*) AS count FROM admin_roles WHERE level = 'senior'").fetchone()["count"]
        for row in conn.execute("SELECT id, created_at FROM users WHERE role = 'admin' ORDER BY id ASC").fetchall():
            existing = conn.execute("SELECT level FROM admin_roles WHERE user_id = ?", (row["id"],)).fetchone()
            if existing:
                if not has_super and existing["level"] == "senior":
                    conn.execute("UPDATE admin_roles SET level = 'super', updated_at = ? WHERE user_id = ?", (now_ms(), row["id"]))
                    has_super = True
                continue
            if not has_super:
                conn.execute(
                    "INSERT INTO admin_roles (user_id, level, appointed_at, updated_at) VALUES (?, 'super', ?, ?)",
                    (row["id"], row["created_at"], now_ms()),
                )
                has_super = True
            elif senior_count < 2:
                conn.execute(
                    "INSERT INTO admin_roles (user_id, level, appointed_at, updated_at) VALUES (?, 'senior', ?, ?)",
                    (row["id"], row["created_at"], now_ms()),
                )
                senior_count += 1
            else:
                conn.execute("UPDATE users SET role = 'reader' WHERE id = ?", (row["id"],))
        super_rows = conn.execute(
            "SELECT user_id FROM admin_roles WHERE level = 'super' ORDER BY appointed_at ASC, user_id ASC"
        ).fetchall()
        for row in super_rows[1:]:
            conn.execute("DELETE FROM admin_roles WHERE user_id = ?", (row["user_id"],))
            conn.execute("UPDATE users SET role = 'reader' WHERE id = ?", (row["user_id"],))
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (row["user_id"],))
        senior_rows = conn.execute(
            "SELECT user_id FROM admin_roles WHERE level = 'senior' ORDER BY appointed_at ASC, user_id ASC"
        ).fetchall()
        for row in senior_rows[2:]:
            conn.execute("DELETE FROM admin_roles WHERE user_id = ?", (row["user_id"],))
            conn.execute("UPDATE users SET role = 'reader' WHERE id = ?", (row["user_id"],))
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (row["user_id"],))
        conn.execute(
            """
            INSERT INTO monthly_awards (work_id, author_id, category, month, rank, reason, selected_at, selected_by, status)
            SELECT mp.work_id, w.author_id, w.category, mp.month, mp.rank, mp.reason,
                   COALESCE(w.published_at, w.created_at), NULL, 'active'
            FROM monthly_picks mp
            JOIN works w ON w.id = mp.work_id
            WHERE NOT EXISTS (
              SELECT 1 FROM monthly_awards ma
              WHERE ma.work_id = mp.work_id AND ma.month = mp.month AND ma.status = 'active'
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    conn = _connect_db()
    try:
        conn.executescript(SCHEMA_PG if USE_POSTGRES else SCHEMA)
        migrate_columns(conn)
        conn.commit()
    finally:
        conn.close()
    ensure_admin()
    sync_system_data()


def ensure_admin() -> None:
    conn = _connect_db()
    try:
        existing = conn.execute("SELECT id, username FROM users WHERE role = 'admin' ORDER BY id LIMIT 1").fetchone()
        password = os.getenv("ADMIN_PASSWORD", "")
        username = (os.getenv("ADMIN_USERNAME") or "admin").strip()
        display_name = (os.getenv("ADMIN_DISPLAY_NAME") or username or "管理员").strip()
        if existing:
            migrate_from = (os.getenv("ADMIN_UPDATE_FROM") or "").strip()
            if not migrate_from or existing["username"].casefold() != migrate_from.casefold():
                return
            if not password:
                raise RuntimeError("ADMIN_PASSWORD is required for administrator credential migration")
            if not ADMIN_USERNAME_RE.fullmatch(username):
                raise RuntimeError("ADMIN_USERNAME must be 1-32 word characters")
            if len(password) < 12:
                raise RuntimeError("ADMIN_PASSWORD must contain at least 12 characters")
            conn.execute(
                "UPDATE users SET username = ?, display_name = ?, password_hash = ? WHERE id = ?",
                (username, display_name[:40], generate_password_hash(password), existing["id"]),
            )
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (existing["id"],))
            conn.commit()
            return
        if not password:
            if IS_PRODUCTION:
                raise RuntimeError("ADMIN_PASSWORD is required to initialize the first production administrator")
            return
        if not ADMIN_USERNAME_RE.fullmatch(username):
            raise RuntimeError("ADMIN_USERNAME must be 1-32 word characters")
        if len(password) < 12:
            raise RuntimeError("ADMIN_PASSWORD must contain at least 12 characters")
        conn.execute(
            "INSERT INTO users (username, display_name, password_hash, role, bio, created_at) VALUES (?, ?, ?, 'admin', '', ?)",
            (username, display_name[:40], generate_password_hash(password), now_ms()),
        )
        conn.commit()
    finally:
        conn.close()


def json_error(message: str, status: int = 400):
    response = jsonify({"error": message})
    response.status_code = status
    return response


def json_ok(payload: dict, status: int = 200):
    response = jsonify(payload)
    response.status_code = status
    return response


def request_json() -> dict:
    if not request.is_json:
        abort(415)
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        abort(400)
    validate_json_shape(payload)
    return payload


def validate_json_shape(value, depth: int = 0, *, body: bool = False) -> None:
    if depth > MAX_JSON_DEPTH:
        abort(400)
    if isinstance(value, dict):
        if len(value) > MAX_LIST_ITEMS:
            abort(400)
        for key, child in value.items():
            if len(str(key)) > 80:
                abort(400)
            validate_json_shape(child, depth + 1, body=body or key == "body")
    elif isinstance(value, list):
        if not body and len(value) > MAX_LIST_ITEMS:
            abort(400)
        for child in value:
            validate_json_shape(child, depth + 1, body=body)
    elif isinstance(value, str):
        if not body and len(value) > MAX_STRING_CHARS:
            abort(400)


def clean_text(value, limit: int, *, required: bool = False) -> str:
    text = str(value if value is not None else "").strip()
    if required and not text:
        abort(400)
    if len(text) > limit:
        abort(400)
    return text


def parse_public_id(value: str) -> int | None:
    match = re.fullmatch(r"u(\d+)", str(value or ""))
    if not match:
        return None
    return int(match.group(1))


def parse_numeric_id(value) -> int | None:
    match = re.search(r"\d+", str(value or ""))
    return int(match.group(0)) if match else None


def user_row(user_id: int | None):
    if not user_id:
        return None
    return get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def row_value(row, key, default=None):
    return row[key] if key in row.keys() else default


def public_user(row) -> dict:
    try:
        genres = json.loads(row_value(row, "genres_json", "[]") or "[]")
    except (TypeError, ValueError):
        genres = []
    return {
        "id": f"u{row['id']}",
        "name": row["display_name"],
        "role": row["role"],
        "bio": row["bio"] or "",
        "awards": row["awards"],
        "avatar": row_value(row, "avatar", "") or "",
        "coverTheme": row_value(row, "cover_theme", "") or "",
        "preferences": row_value(row, "literary_preferences", "") or "",
        "genres": genres if isinstance(genres, list) else [],
        "joinedAt": iso_time(row["created_at"]),
    }


def current_user_row():
    if "user" in g:
        return g.user
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        g.user = None
        g.session = None
        return None
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    session = get_db().execute(
        "SELECT * FROM sessions WHERE token_hash = ? AND expires_at > ?",
        (token_hash, now_ms()),
    ).fetchone()
    if not session:
        g.user = None
        g.session = None
        return None
    user = get_db().execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    if not user or row_value(user, "account_status", "active") != "active":
        g.user = None
        g.session = None
        return None
    get_db().execute("UPDATE sessions SET last_seen_at = ? WHERE token_hash = ?", (now_ms(), token_hash))
    get_db().commit()
    g.user = user
    g.session = session
    return user


def issue_session(user_id: int) -> tuple[str, str]:
    raw_token = secrets.token_urlsafe(48)
    csrf_token = secrets.token_urlsafe(32)
    created = now_ms()
    expires = created + SESSION_DAYS * 24 * 60 * 60 * 1000
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    get_db().execute(
        "INSERT INTO sessions (token_hash, user_id, csrf_token, created_at, last_seen_at, expires_at) VALUES (?, ?, ?, ?, ?, ?)",
        (token_hash, user_id, csrf_token, created, created, expires),
    )
    get_db().commit()
    g.user = get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    g.session = get_db().execute("SELECT * FROM sessions WHERE token_hash = ?", (token_hash,)).fetchone()
    return raw_token, csrf_token


def set_session_cookie(response, raw_token: str):
    response.set_cookie(
        SESSION_COOKIE,
        raw_token,
        max_age=SESSION_DAYS * 24 * 60 * 60,
        secure=IS_PRODUCTION,
        httponly=True,
        samesite="Lax",
        path="/",
    )
    return response


def clear_session_cookie(response):
    response.delete_cookie(SESSION_COOKIE, path="/", secure=IS_PRODUCTION, httponly=True, samesite="Lax")
    return response


def get_csrf_value() -> str:
    user = current_user_row()
    if user and getattr(g, "session", None):
        return g.session["csrf_token"]
    if not hasattr(g, "guest_csrf"):
        g.guest_csrf = request.cookies.get(CSRF_COOKIE) or secrets.token_urlsafe(32)
    return g.guest_csrf


def require_auth(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user_row()
        if not user:
            return json_error("请先登录", 401)
        return view(*args, **kwargs)

    return wrapped


def require_admin(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user_row()
        if not user:
            return json_error("请先登录", 401)
        if user["role"] != "admin" or not admin_level(user):
            return json_error("权限不足", 403)
        return view(*args, **kwargs)

    return wrapped


def admin_level(user) -> str:
    if not user or user["role"] != "admin":
        return ""
    row = get_db().execute("SELECT level FROM admin_roles WHERE user_id = ?", (user["id"],)).fetchone()
    return row["level"] if row else ""


def is_super_admin(user) -> bool:
    return admin_level(user) == "super"


def require_super_admin(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user_row()
        if not user:
            return json_error("请先登录", 401)
        if user["role"] != "admin":
            return json_error("权限不足", 403)
        if not is_super_admin(user):
            return json_error("只有超级管理员可以执行此操作", 403)
        return view(*args, **kwargs)

    return wrapped


def rate_limit(bucket: str, limit: int, window_seconds: int) -> bool:
    key = f"{bucket}:{request.remote_addr or 'unknown'}"
    now = time.monotonic()
    with RATE_LOCK:
        values = RATE_BUCKETS[key]
        cutoff = now - window_seconds
        while values and values[0] < cutoff:
            values.popleft()
        if len(values) >= limit:
            return False
        values.append(now)
    return True


def audit(action: str, target_type: str = "", target_id: str = "", detail: str = "", actor_id: int | None = None) -> None:
    get_db().execute(
        "INSERT INTO audit_logs (actor_id, action, target_type, target_id, detail, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (actor_id, action[:80], target_type[:40], str(target_id)[:80], detail[:500], now_ms()),
    )


def notify(user_id: int, text: str, kind: str = "system", link: str = "", work_id=None, chapter_id=None) -> None:
    get_db().execute(
        "INSERT INTO notifications (user_id, type, text, link, work_id, chapter_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user_id, kind[:40], text[:300], link[:300], work_id, chapter_id, now_ms()),
    )


def notify_work_followers(db, work, chapter) -> None:
    """章节发布后通知追更读者，同一用户与章节只生成一次。"""
    if not work or not chapter:
        return
    if work["status"] != "published" or not bool(row_value(work, "is_public", 1)):
        return
    if (row_value(work, "visibility", "PUBLIC") or "PUBLIC") != "PUBLIC":
        return
    link = f"#/chapter/ch{chapter['id']}"
    text = f"《{work['title']}》更新了\n第{int(chapter['chapter_number'])}章：{chapter['title']}"
    followers = db.execute(
        "SELECT user_id FROM work_follows WHERE work_id = ? AND user_id <> ?",
        (work["id"], work["author_id"]),
    ).fetchall()
    for follower in followers:
        existing = db.execute(
            "SELECT 1 FROM notifications WHERE user_id = ? AND type = 'chapter_update' AND link = ? LIMIT 1",
            (follower["user_id"], link),
        ).fetchone()
        if existing:
            continue
        notify(follower["user_id"], text, "chapter_update", link, work["id"], chapter["id"])


def ensure_message_settings(user_id: int) -> None:
    get_db().execute(
        "INSERT OR IGNORE INTO message_settings (user_id, allow_strangers, recall_minutes, notifications) VALUES (?, 1, 2, 1)",
        (user_id,),
    )


def get_work(work_id: int, user_row_value=None):
    user = user_row_value or current_user_row()
    is_admin = bool(user and user["role"] == "admin")
    sql = """
      SELECT w.*, u.display_name AS author_name
      FROM works w JOIN users u ON u.id = w.author_id
      WHERE w.id = ?
    """
    params: list[object] = [work_id]
    if not is_admin:
        if user:
            sql += " AND ((w.status = 'published' AND w.is_public = 1 AND w.visibility = 'PUBLIC') OR w.author_id = ?)"
            params.append(user["id"])
        else:
            sql += " AND w.status = 'published' AND w.is_public = 1 AND w.visibility = 'PUBLIC'"
    return get_db().execute(sql, params).fetchone()


def snapshot_work_version(db, work, reason: str = "") -> int:
    """把当前作品内容保存为一个历史版本，不改动现有作品行。"""
    row = db.execute(
        "SELECT COALESCE(MAX(version_number), 0) + 1 AS next_version FROM work_versions WHERE work_id = ?",
        (work["id"],),
    ).fetchone()
    version_number = int(row["next_version"] or 1)
    db.execute(
        """
        INSERT INTO work_versions (
          work_id, author_id, version_number, title, category, tags_json,
          excerpt, body_json, change_reason, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            work["id"], work["author_id"], version_number, work["title"], work["category"],
            work["tags_json"], work["excerpt"], work["body_json"], reason[:200], now_ms(),
        ),
    )
    return version_number


def save_book_share_image(upload) -> str:
    raw = upload.read(MAX_IMAGE_BYTES + 1)
    if not raw:
        raise ValueError("图片文件为空")
    if len(raw) > MAX_IMAGE_BYTES:
        raise ValueError("图片不能超过 5MB")
    try:
        with Image.open(io.BytesIO(raw)) as probe:
            probe.verify()
        with Image.open(io.BytesIO(raw)) as source:
            if source.format not in AVATAR_FORMATS:
                raise ValueError("仅支持 JPG、PNG、WEBP 图片")
            image = ImageOps.contain(source.convert("RGB"), (BOOK_SHARE_IMAGE_SIZE, BOOK_SHARE_IMAGE_SIZE), method=Image.LANCZOS)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("图片无法识别") from exc
    buffer = io.BytesIO()
    image.save(buffer, "WEBP", quality=86, method=6)
    name = f"{secrets.token_hex(16)}.webp"
    get_db().execute(
        "INSERT INTO avatar_blobs (name, content_type, data, created_at) VALUES (?, ?, ?, ?)",
        (name, "image/webp", buffer.getvalue(), now_ms()),
    )
    return name


def build_book_shares(db, user_id: int | None) -> list[dict]:
    rows = db.execute(
        """
        SELECT bs.*, u.display_name AS author_name,
          (SELECT COUNT(*) FROM book_share_praises p WHERE p.share_id = bs.id) AS praise_count,
          EXISTS(SELECT 1 FROM book_share_praises p WHERE p.share_id = bs.id AND p.user_id = ?) AS praised
        FROM book_shares bs JOIN users u ON u.id = bs.user_id
        WHERE (bs.status = 'published' OR bs.user_id = ?) AND bs.status <> 'deleted'
        ORDER BY bs.created_at DESC LIMIT 200
        """,
        (user_id or 0, user_id or 0),
    ).fetchall()
    result = []
    for row in rows:
        try:
            tags = json.loads(row["tags_json"] or "[]")
        except (TypeError, ValueError):
            tags = []
        result.append({
            "id": f"bs{row['id']}",
            "userId": f"u{row['user_id']}",
            "author": row["author_name"],
            "bookTitle": row["book_title"],
            "bookAuthor": row["book_author"],
            "recommendation": row["recommendation"],
            "tags": tags if isinstance(tags, list) else [],
            "imageUrl": f"/book-share-images/{row['image_name']}" if row["image_name"] else "",
            "praiseCount": int(row["praise_count"] or 0),
            "praised": bool(row["praised"]),
            "mine": bool(user_id and row["user_id"] == user_id),
            "status": row["status"],
            "createdAt": iso_time(row["created_at"]),
            "updatedAt": iso_time(row["updated_at"]),
        })
    return result


def _ranking_period_start(period: str) -> int:
    now = datetime.now(timezone.utc)
    if period == "month":
        value = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    elif period == "quarter":
        value = datetime(now.year, ((now.month - 1) // 3) * 3 + 1, 1, tzinfo=timezone.utc)
    elif period == "year":
        value = datetime(now.year, 1, 1, tzinfo=timezone.utc)
    else:
        return 0
    return int(value.timestamp() * 1000)


def word_count(body) -> int:
    return len(re.sub(r"\s+", "", "".join(str(part) for part in (body or []) if part)))


def min_words_for(category: str) -> int:
    return MIN_WORDS_BY_CATEGORY.get(category, DEFAULT_MIN_WORDS)


def is_effective_work(body, category: str, status: str, visibility: str = "PUBLIC") -> bool:
    return status == "published" and visibility == "PUBLIC" and word_count(body) >= min_words_for(category)


def author_work_stats(db: sqlite3.Connection, author_id: int, public_only: bool = False) -> dict:
    """把投稿总数、有效作品数、公开/私密、草稿、审核中拆开统计。"""
    stats = {"submitted": 0, "effective": 0, "published": 0, "private": 0, "draft": 0, "pending": 0}
    where = "author_id = ?"
    if public_only:
        where += " AND status = 'published' AND is_public = 1 AND visibility = 'PUBLIC'"
    rows = db.execute(
        f"SELECT status, visibility, category, body_json FROM works WHERE {where}",
        (author_id,),
    ).fetchall()
    for row in rows:
        stats["submitted"] += 1
        visibility = row_value(row, "visibility", "PUBLIC") or "PUBLIC"
        status = row["status"]
        if visibility == "PRIVATE":
            stats["private"] += 1
        if status == "draft":
            stats["draft"] += 1
        if status in {"pending", "pending_agent", "pending_review"}:
            stats["pending"] += 1
        if status == "published" and visibility == "PUBLIC":
            stats["published"] += 1
        try:
            body = json.loads(row["body_json"] or "[]")
        except (TypeError, ValueError):
            body = []
        if is_effective_work(body, row["category"], status, visibility):
            stats["effective"] += 1
    return stats


def parse_day_ms(value, *, end_of_day: bool = False) -> int:
    text = clean_text(value, 30)
    if not text:
        return 0
    try:
        day = datetime.strptime(text[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return 0
    ms = int(day.timestamp() * 1000)
    return ms + 86399999 if end_of_day else ms


def record_risk(db, user_id, kind: str, detail: str, level: str = "MEDIUM", target_type: str = "", target_id: str = "") -> None:
    db.execute(
        "INSERT INTO risk_events (user_id, kind, level, detail, target_type, target_id, status, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)",
        (user_id, kind[:40], level, detail[:300], target_type[:20], str(target_id)[:40], now_ms()),
    )


def _recent_count(db, table: str, where: str, params: tuple) -> int:
    return db.execute(f"SELECT COUNT(*) AS count FROM {table} WHERE {where}", params).fetchone()["count"]


def _account_age_ms(user) -> int:
    return now_ms() - int(user["created_at"] or 0)


def evaluate_like_risk(db, user, work) -> tuple[bool, str]:
    cfg = RISK_CONFIG
    user_id = user["id"]
    now = now_ms()
    hourly = _recent_count(db, "likes", "user_id = ? AND created_at >= ?", (user_id, now - 3600 * 1000))
    if hourly >= cfg["like_rate_per_hour"]:
        return False, f"一小时内点赞 {hourly + 1} 次，超过 {cfg['like_rate_per_hour']} 次上限"
    burst = _recent_count(db, "likes", "user_id = ? AND created_at >= ?", (user_id, now - cfg["like_burst_window_ms"]))
    if burst >= cfg["like_burst_max"]:
        return False, f"{cfg['like_burst_window_ms'] // 1000} 秒内连续点赞 {burst + 1} 次"
    if _account_age_ms(user) < cfg["new_account_ms"] and hourly >= cfg["new_account_like_per_hour"]:
        return False, "新账号点赞频率偏高，暂时不计入统计"
    same_author = db.execute(
        "SELECT COUNT(*) AS count FROM likes l JOIN works w ON w.id = l.work_id"
        " WHERE l.user_id = ? AND w.author_id = ? AND l.created_at >= ?",
        (user_id, work["author_id"], now - 3600 * 1000),
    ).fetchone()["count"]
    if same_author >= cfg["same_author_like_per_hour"]:
        return False, "短时间集中给同一作者点赞，等待人工复核"
    return True, ""


def evaluate_comment_risk(db, user, work, text: str, chapter_id: int | None = None) -> tuple[bool, str]:
    cfg = RISK_CONFIG
    user_id = user["id"]
    now = now_ms()
    hourly = _recent_count(db, "comments", "user_id = ? AND deleted_at IS NULL AND created_at >= ?", (user_id, now - 3600 * 1000))
    if chapter_id is not None:
        hourly += _recent_count(db, "chapter_comments", "user_id = ? AND deleted_at IS NULL AND created_at >= ?", (user_id, now - 3600 * 1000))
    if hourly >= cfg["comment_rate_per_hour"]:
        return False, f"一小时内评论 {hourly + 1} 次，超过 {cfg['comment_rate_per_hour']} 次上限"
    if chapter_id is not None:
        duplicate = _recent_count(
            db,
            "chapter_comments",
            "user_id = ? AND chapter_id = ? AND text = ? AND created_at >= ?",
            (user_id, chapter_id, text, now - cfg["comment_duplicate_window_ms"]),
        )
    else:
        duplicate = _recent_count(
            db,
            "comments",
            "user_id = ? AND work_id = ? AND text = ? AND created_at >= ?",
            (user_id, work["id"], text, now - cfg["comment_duplicate_window_ms"]),
        )
    if duplicate:
        return False, "短时间内重复发表相同评论"
    if _account_age_ms(user) < cfg["new_account_ms"] and hourly >= cfg["new_account_comment_per_hour"]:
        return False, "新账号评论频率偏高，暂不计入统计"
    return True, ""


def _shingles(text: str, size: int = 10) -> set:
    compact = re.sub(r"\s+", "", text or "")
    if len(compact) < size:
        return {compact} if compact else set()
    return {compact[i:i + size] for i in range(len(compact) - size + 1)}


def detect_similarity(db: sqlite3.Connection, text: str, exclude_work_id=None) -> dict:
    """站内相似度检测。结果只作为疑似信号，由人工确认。"""
    cfg = RISK_CONFIG
    best = {"level": "low", "score": 0.0, "workId": "", "title": ""}
    compact = re.sub(r"\s+", "", text or "")
    if len(compact) < cfg["similarity_min_chars"]:
        return best
    target = _shingles(text)
    if not target:
        return best
    # ponytail: 对最近 500 篇作品做 shingle 比对，作品上万时改成倒排索引
    rows = db.execute(
        "SELECT id, title, body_json FROM works WHERE id != ? ORDER BY created_at DESC LIMIT 500",
        (exclude_work_id or -1,),
    ).fetchall()
    for row in rows:
        try:
            body = json.loads(row["body_json"] or "[]")
        except (TypeError, ValueError):
            body = []
        other = _shingles("\n".join(str(part) for part in body if part))
        if not other:
            continue
        overlap = len(target & other)
        if not overlap:
            continue
        score = overlap / len(target | other)
        if score > best["score"]:
            best = {"level": "low", "score": score, "workId": f"w{row['id']}", "title": row["title"]}
    if best["score"] >= cfg["similarity_high"]:
        best["level"] = "high"
    elif best["score"] >= cfg["similarity_medium"]:
        best["level"] = "medium"
    return best


def evaluate_work_content(db, author_id: int, body, category: str, work_id: int | None = None) -> dict:
    """规则型 Agent 审核器。只输出建议，不直接封禁或修改管理员权限。"""
    text = "\n".join(str(part) for part in (body or []) if part)
    signals: list[str] = []
    score = 0
    words = word_count(body)
    minimum = AGENT_MIN_WORDS
    if words < minimum:
        score += 2
        signals.append(f"字数低于审核参考值 {minimum}")
    similarity = detect_similarity(db, text, exclude_work_id=work_id)
    if similarity["level"] == "high":
        score += 5
        signals.append(f"站内相似度较高：{similarity['title']}")
    elif similarity["level"] == "medium":
        score += 3
        signals.append(f"站内存在相似内容：{similarity['title']}")
    link_count = len(re.findall(r"https?://|www\.", text, flags=re.IGNORECASE))
    if link_count > 8:
        score += 4
        signals.append("外部链接数量异常")
    elif link_count > 3:
        score += 2
        signals.append("外部链接偏多")
    if re.search(r"赌博|博彩|色情|诈骗|刷单|代写|出售账号", text, flags=re.IGNORECASE):
        score += 6
        signals.append("命中高风险词")
    compact = re.sub(r"\s+", "", text)
    if len(compact) >= 30:
        repeated = sum(1 for i in range(len(compact) - 8) if compact[i:i + 8] == compact[i + 4:i + 12])
        if repeated / max(1, len(compact) - 8) > 0.35:
            score += 2
            signals.append("重复片段偏多")
    author = db.execute("SELECT risk_level FROM users WHERE id = ?", (author_id,)).fetchone()
    account_risk = (author["risk_level"] if author and "risk_level" in author.keys() else "LOW") or "LOW"
    if account_risk in {"HIGH", "CRITICAL"}:
        score += 4
        signals.append(f"账号风险等级为 {account_risk}")
    pending_risks = db.execute(
        "SELECT level FROM risk_events WHERE user_id = ? AND status = 'pending'",
        (author_id,),
    ).fetchall()
    if any((row["level"] or "").upper() in {"HIGH", "CRITICAL"} for row in pending_risks):
        score += 4
        signals.append("账号存在未处理高风险记录")
    if score >= 8:
        level = "CRITICAL"
    elif score >= 5:
        level = "HIGH"
    elif score >= 2:
        level = "MEDIUM"
    else:
        level = "LOW"
    needs_human = level != "LOW"
    category_name = "正常"
    if signals:
        category_name = signals[0].split("：", 1)[0]
    recommendation = "ALLOW" if not needs_human else "REVIEW"
    return {
        "risk_level": level,
        "category": category_name,
        "confidence": 0.92 if level == "LOW" else 0.78 if level == "MEDIUM" else 0.84,
        "recommendation": recommendation,
        "needs_human_review": needs_human,
        "signals": signals or ["未发现明显风险信号"],
    }


def run_agent_review(work_id: int, author_id: int, title: str, body, category: str) -> dict:
    """执行投稿审核并安全落库。异常一律进入人工复核。"""
    agent_run_id = f"ar_{uuid.uuid4().hex}"
    started = time.monotonic()
    created_at = now_ms()
    db = get_db()
    try:
        result = evaluate_work_content(db, author_id, body, category, work_id=work_id)
        duration = max(0, int((time.monotonic() - started) * 1000))
        db.execute(
            """
            INSERT INTO agent_runs (
              agent_run_id, content_id, content_type, user_id, status, error, created_at,
              duration, policy_version, model, prompt_version
            ) VALUES (?, ?, 'work', ?, 'completed', '', ?, ?, ?, ?, 'none')
            """,
            (agent_run_id, work_id, author_id, created_at, duration, AGENT_POLICY_VERSION, AGENT_MODEL_NAME),
        )
        db.execute(
            """
            INSERT INTO agent_moderation_results (
              agent_run_id, content_id, content_type, risk_level, category, confidence,
              recommendation, needs_human_review, details_json, created_at
            ) VALUES (?, ?, 'work', ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                agent_run_id, work_id, result["risk_level"], result["category"], result["confidence"],
                result["recommendation"], int(result["needs_human_review"]),
                json.dumps(result["signals"], ensure_ascii=False), created_at,
            ),
        )
        if result["needs_human_review"]:
            db.execute(
                "INSERT INTO agent_review_tasks (agent_run_id, work_id, reason, status, created_at) VALUES (?, ?, ?, 'open', ?)",
                (agent_run_id, work_id, result["category"], created_at),
            )
            db.execute(
                "UPDATE works SET status = 'pending_review', review_note = ?, updated_at = ? WHERE id = ?",
                ("Agent 建议人工复核：" + "；".join(result["signals"]), created_at, work_id),
            )
        else:
            db.execute(
                "UPDATE works SET status = 'published', review_note = '', published_at = ?, updated_at = ? WHERE id = ?",
                (created_at, created_at, work_id),
            )
        db.commit()
        audit("Agent 审核", "work", str(work_id), f"Agent {result['risk_level']}，{result['recommendation']}", None)
        db.commit()
        return {"agent_run_id": agent_run_id, **result}
    except Exception as exc:
        try:
            db.rollback()
        except Exception:
            pass
        duration = max(0, int((time.monotonic() - started) * 1000))
        error_text = f"{type(exc).__name__}: {exc}"[:500]
        try:
            db.execute(
                """
                INSERT INTO agent_runs (
                  agent_run_id, content_id, content_type, user_id, status, error, created_at,
                  duration, policy_version, model, prompt_version
                ) VALUES (?, ?, 'work', ?, 'error', ?, ?, ?, ?, ?, 'none')
                """,
                (agent_run_id, work_id, author_id, error_text, created_at, duration, AGENT_POLICY_VERSION, AGENT_MODEL_NAME),
            )
            db.execute(
                """
                INSERT INTO agent_moderation_results (
                  agent_run_id, content_id, content_type, risk_level, category, confidence,
                  recommendation, needs_human_review, details_json, created_at
                ) VALUES (?, ?, 'work', 'HIGH', '审核异常', 0, 'REVIEW', 1, ?, ?)
                """,
                (agent_run_id, work_id, json.dumps(["Agent 执行异常，已转人工复核"], ensure_ascii=False), created_at),
            )
            db.execute(
                "INSERT INTO agent_review_tasks (agent_run_id, work_id, reason, status, created_at) VALUES (?, ?, '审核异常', 'open', ?)",
                (agent_run_id, work_id, created_at),
            )
            db.execute(
                "UPDATE works SET status = 'pending_review', review_note = 'Agent 审核异常，已转人工复核。', updated_at = ? WHERE id = ?",
                (created_at, work_id),
            )
            db.commit()
            audit("Agent 异常", "work", str(work_id), error_text, None)
            db.commit()
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass
        return {
            "agent_run_id": agent_run_id,
            "risk_level": "HIGH",
            "category": "审核异常",
            "confidence": 0,
            "recommendation": "REVIEW",
            "needs_human_review": True,
            "signals": ["Agent 执行异常，已转人工复核"],
            "error": error_text,
        }


def remove_old_avatar(value: str) -> None:
    if not value.startswith("/avatars/"):
        return
    name = value.rsplit("/", 1)[-1]
    if not AVATAR_NAME_RE.fullmatch(name):
        return
    get_db().execute("DELETE FROM avatar_blobs WHERE name = ?", (name,))


def build_rankings(db: sqlite3.Connection, authors: list[dict] | None = None) -> dict:
    periods = {name: _ranking_period_start(name) for name in ("month", "quarter", "year", "all")}
    author_names = {item.get("id"): item.get("name", "") for item in (authors or [])}
    work_rows = db.execute(
        """
        SELECT w.id, w.author_id, w.title, w.category, w.excerpt, w.views, w.body_json,
               w.published_at, w.created_at, u.display_name AS author_name
        FROM works w JOIN users u ON u.id = w.author_id
        WHERE w.status = 'published' AND w.is_public = 1 AND w.visibility = 'PUBLIC'
        ORDER BY COALESCE(w.published_at, w.created_at) DESC
        """
    ).fetchall()

    # 每个指标只做一次分组统计，避免逐作品逐时间范围查询导致上百次数据库往返
    metric_specs = (
        ("views", "work_views", "viewed_at", ""),
        ("likes", "likes", "created_at", "effective = 1"),
        ("favorites", "favorites", "created_at", ""),
        ("comments", "comments", "created_at", "deleted_at IS NULL AND effective = 1"),
    )
    metric_counts: dict[str, dict[str, dict[int, int]]] = {}
    for key, table, column, extra in metric_specs:
        where = f" WHERE {extra}" if extra else ""
        rows = db.execute(
            f"""
            SELECT work_id, COUNT(*) AS total,
                   SUM(CASE WHEN {column} >= ? THEN 1 ELSE 0 END) AS recent_month,
                   SUM(CASE WHEN {column} >= ? THEN 1 ELSE 0 END) AS recent_quarter,
                   SUM(CASE WHEN {column} >= ? THEN 1 ELSE 0 END) AS recent_year
            FROM {table}{where}
            GROUP BY work_id
            """,
            (periods["month"], periods["quarter"], periods["year"]),
        ).fetchall()
        per_period: dict[str, dict[int, int]] = {name: {} for name in periods}
        for item in rows:
            work_id = int(item["work_id"])
            per_period["all"][work_id] = int(item["total"] or 0)
            per_period["month"][work_id] = int(item["recent_month"] or 0)
            per_period["quarter"][work_id] = int(item["recent_quarter"] or 0)
            per_period["year"][work_id] = int(item["recent_year"] or 0)
        metric_counts[key] = per_period

    rankings: dict[str, dict] = {}
    for period, start in periods.items():
        work_items = []
        author_stats: dict[str, dict] = {}
        for row in work_rows:
            work_id = row["id"]
            if start:
                views = metric_counts["views"][period].get(int(work_id), 0)
            else:
                views = int(row["views"] or 0)
            likes = metric_counts["likes"][period].get(int(work_id), 0)
            favorites = metric_counts["favorites"][period].get(int(work_id), 0)
            comments = metric_counts["comments"][period].get(int(work_id), 0)
            score = (
                views * RANKING_WEIGHTS["views"]
                + likes * RANKING_WEIGHTS["likes"]
                + favorites * RANKING_WEIGHTS["favorites"]
                + comments * RANKING_WEIGHTS["comments"]
            )
            work_items.append(
                {
                    "id": f"w{work_id}",
                    "title": row["title"],
                    "authorId": f"u{row['author_id']}",
                    "author": row["author_name"],
                    "category": row["category"],
                    "excerpt": row["excerpt"],
                    "publishedAt": row["published_at"] or row["created_at"],
                    "views": views,
                    "likes": likes,
                    "favorites": favorites,
                    "comments": comments,
                    "score": score,
                }
            )
            author_id = f"u{row['author_id']}"
            stats = author_stats.setdefault(
                author_id,
                {"id": author_id, "name": row["author_name"] or author_names.get(author_id, ""), "works": 0, "awards": 0, "words": 0, "popularity": 0},
            )
            stats["popularity"] += score
            published_at = int(row["published_at"] or row["created_at"] or 0)
            if not start or published_at >= start:
                try:
                    body = json.loads(row["body_json"] or "[]")
                except (TypeError, ValueError):
                    body = []
                words = word_count(body)
                if words >= min_words_for(row["category"]):
                    stats["works"] += 1
                stats["words"] += words

        award_sql = """
            SELECT ma.author_id, COUNT(*) AS count
            FROM monthly_awards ma
            JOIN works w ON w.id = ma.work_id
            WHERE ma.status = 'active' AND w.status = 'published' AND w.is_public = 1 AND w.visibility = 'PUBLIC'
        """
        award_params: list[object] = []
        current = datetime.now(timezone.utc)
        if period == "month":
            award_sql += " AND ma.month = ?"
            award_params.append(current.strftime("%Y-%m"))
        elif period == "quarter":
            start_month = ((current.month - 1) // 3) * 3 + 1
            award_sql += " AND ma.month >= ? AND ma.month <= ?"
            award_params.extend((f"{current.year}-{start_month:02d}", f"{current.year}-{start_month + 2:02d}"))
        elif period == "year":
            award_sql += " AND ma.month LIKE ?"
            award_params.append(f"{current.year}-%")
        award_sql += " GROUP BY ma.author_id"
        for row in db.execute(award_sql, award_params).fetchall():
            author_id = f"u{row['author_id']}"
            stats = author_stats.setdefault(
                author_id,
                {"id": author_id, "name": author_names.get(author_id, ""), "works": 0, "awards": 0, "words": 0, "popularity": 0},
            )
            stats["awards"] = int(row["count"])
        rankings[period] = {
            "works": sorted(work_items, key=lambda item: (item["score"], item["views"], item["likes"]), reverse=True),
            "authors": [item for item in author_stats.values() if item["works"] or item["awards"] or item["words"] or item["popularity"]],
        }
    return rankings


def build_system_health(db, is_admin: bool) -> list[dict]:
    if not is_admin:
        return []
    checks: list[dict] = []

    def add(name: str, check):
        try:
            status, detail = check()
        except Exception as exc:
            try:
                db.rollback()
            except Exception:
                pass
            status, detail = "异常", f"检测失败：{type(exc).__name__}"
        checks.append({"name": name, "status": status, "detail": detail})

    def count_check(sql: str, suffix: str):
        count = int(db.execute(sql).fetchone()["count"])
        return "正常", f"{count} {suffix}"

    add("数据库", lambda: ("正常", "PostgreSQL" if USE_POSTGRES else "SQLite") if db.execute("SELECT 1").fetchone() else ("异常", "无响应"))
    add("作品保存", lambda: count_check("SELECT COUNT(*) AS count FROM works", "篇作品"))
    add("Agent", lambda: _agent_health(db))
    add("文件存储", lambda: count_check("SELECT COUNT(*) AS count FROM avatar_blobs", "个头像文件（存于数据库）"))
    add("投稿审核", lambda: count_check("SELECT COUNT(*) AS count FROM works WHERE status IN ('pending', 'pending_agent', 'pending_review')", "篇待处理"))
    add("私信", lambda: count_check("SELECT COUNT(*) AS count FROM conversations", "个会话"))
    add("排行榜", lambda: ("正常", f"{len(build_rankings(db))} 个时间范围"))
    add("月度评选", lambda: count_check("SELECT COUNT(*) AS count FROM monthly_awards WHERE status = 'active'", "条有效记录"))
    return checks


def _agent_health(db) -> tuple[str, str]:
    row = db.execute(
        "SELECT status, error, created_at, duration FROM agent_runs ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    if not row:
        return "无法检测", "尚无 Agent 运行记录"
    if row["status"] == "error":
        return "异常", f"最近一次异常：{row['error'] or '未知错误'}"
    return "正常", f"最近运行 {iso_time(row['created_at'])}，耗时 {int(row['duration'] or 0)}ms"


def chapter_body_parts(content: str) -> list[str]:
    return [part.strip() for part in re.split(r"\n\s*\n", content or "") if part.strip()]


def serialize_chapter(row) -> dict:
    content = row["content"] or ""
    return {
        "id": f"ch{row['id']}",
        "workId": f"w{row['work_id']}",
        "chapterNumber": int(row["chapter_number"]),
        "title": row["title"],
        "content": content,
        "body": chapter_body_parts(content),
        "status": row["status"],
        "reviewNote": row["review_note"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "publishedAt": row["published_at"],
    }


def serialize_chapter_comment(row, user_id, is_admin: bool, liked_ids: set, like_counts: dict) -> dict:
    comment_id = int(row["id"])
    author_id = int(row["user_id"])
    return {
        "id": f"cc{comment_id}",
        "chapterId": f"ch{row['chapter_id']}",
        "parentId": f"cc{row['parent_id']}" if row["parent_id"] else "",
        "who": row["author_name"],
        "userId": f"u{author_id}",
        "text": row["text"],
        "at": row["created_at"],
        "likes": int(like_counts.get(comment_id, 0)),
        "liked": comment_id in liked_ids,
        "mine": bool(user_id) and author_id == int(user_id),
        "canDelete": bool(user_id) and (author_id == int(user_id) or is_admin),
    }


def run_chapter_agent_review(chapter_id: int, author_id: int, work_id: int, title: str, content: str) -> dict:
    """章节沿用现有规则型 Agent 审核器，只把审核结果落到章节状态。"""
    agent_run_id = f"ar_{uuid.uuid4().hex}"
    started = time.monotonic()
    created_at = now_ms()
    db = get_db()
    try:
        result = evaluate_work_content(db, author_id, [content], "", work_id=work_id)
        duration = max(0, int((time.monotonic() - started) * 1000))
        db.execute(
            """
            INSERT INTO agent_runs (
              agent_run_id, content_id, content_type, user_id, status, error, created_at,
              duration, policy_version, model, prompt_version
            ) VALUES (?, ?, 'chapter', ?, 'completed', '', ?, ?, ?, ?, 'none')
            """,
            (agent_run_id, chapter_id, author_id, created_at, duration, AGENT_POLICY_VERSION, AGENT_MODEL_NAME),
        )
        db.execute(
            """
            INSERT INTO agent_moderation_results (
              agent_run_id, content_id, content_type, risk_level, category, confidence,
              recommendation, needs_human_review, details_json, created_at
            ) VALUES (?, ?, 'chapter', ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                agent_run_id, chapter_id, result["risk_level"], result["category"], result["confidence"],
                result["recommendation"], int(result["needs_human_review"]),
                json.dumps(result["signals"], ensure_ascii=False), created_at,
            ),
        )
        if result["recommendation"] == "BLOCK":
            status = "REJECTED"
            review_note = "Agent 建议拒绝：" + "；".join(result["signals"])
            published_at = None
        elif result["needs_human_review"]:
            status = "PENDING_REVIEW"
            review_note = "Agent 建议人工复核：" + "；".join(result["signals"])
            published_at = None
        else:
            status = "PUBLISHED"
            review_note = ""
            published_at = created_at
        db.execute(
            "UPDATE chapters SET status = ?, review_note = ?, published_at = ?, updated_at = ? WHERE id = ?",
            (status, review_note, published_at, created_at, chapter_id),
        )
        if status == "PUBLISHED":
            db.execute("UPDATE works SET updated_at = ? WHERE id = ?", (created_at, work_id))
            published_work = db.execute("SELECT * FROM works WHERE id = ?", (work_id,)).fetchone()
            published_chapter = db.execute("SELECT * FROM chapters WHERE id = ?", (chapter_id,)).fetchone()
            notify_work_followers(db, published_work, published_chapter)
        db.commit()
        audit("章节 Agent 审核", "chapter", str(chapter_id), f"章节《{title}》{status}", None)
        db.commit()
        return {"agent_run_id": agent_run_id, "status": status, **result}
    except Exception as exc:
        try:
            db.rollback()
        except Exception:
            pass
        duration = max(0, int((time.monotonic() - started) * 1000))
        error_text = f"{type(exc).__name__}: {exc}"[:500]
        try:
            db.execute(
                """
                INSERT INTO agent_runs (
                  agent_run_id, content_id, content_type, user_id, status, error, created_at,
                  duration, policy_version, model, prompt_version
                ) VALUES (?, ?, 'chapter', ?, 'error', ?, ?, ?, ?, ?, 'none')
                """,
                (agent_run_id, chapter_id, author_id, error_text, created_at, duration, AGENT_POLICY_VERSION, AGENT_MODEL_NAME),
            )
            db.execute(
                """
                INSERT INTO agent_moderation_results (
                  agent_run_id, content_id, content_type, risk_level, category, confidence,
                  recommendation, needs_human_review, details_json, created_at
                ) VALUES (?, ?, 'chapter', 'HIGH', '审核异常', 0, 'REVIEW', 1, ?, ?)
                """,
                (agent_run_id, chapter_id, json.dumps(["Agent 执行异常，已转人工复核"], ensure_ascii=False), created_at),
            )
            db.execute(
                "UPDATE chapters SET status = 'PENDING_REVIEW', review_note = ?, updated_at = ? WHERE id = ?",
                ("Agent 审核异常，已转人工复核。", created_at, chapter_id),
            )
            db.commit()
            audit("章节 Agent 异常", "chapter", str(chapter_id), error_text, None)
            db.commit()
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass
        return {
            "agent_run_id": agent_run_id,
            "status": "PENDING_REVIEW",
            "risk_level": "HIGH",
            "category": "审核异常",
            "confidence": 0,
            "recommendation": "REVIEW",
            "needs_human_review": True,
            "signals": ["Agent 执行异常，已转人工复核"],
            "error": error_text,
        }


def build_state(user) -> dict:
    db = get_db()
    user_id = user["id"] if user else None
    is_admin = bool(user and user["role"] == "admin")

    works_sql = """
      SELECT w.*, u.display_name AS author_name,
        (SELECT COUNT(*) FROM likes l WHERE l.work_id = w.id) AS likes_count,
        (SELECT COUNT(*) FROM likes l WHERE l.work_id = w.id AND l.effective = 1) AS effective_likes_count,
        (SELECT COUNT(*) FROM favorites f WHERE f.work_id = w.id) AS favorites_count,
        (SELECT COUNT(*) FROM comments c WHERE c.work_id = w.id AND c.deleted_at IS NULL) AS comments_count,
        (SELECT COUNT(*) FROM comments c WHERE c.work_id = w.id AND c.deleted_at IS NULL AND c.effective = 1) AS effective_comments_count
      FROM works w JOIN users u ON u.id = w.author_id
    """
    params: list[object] = []
    if not is_admin:
        if user_id:
            works_sql += " WHERE ((w.status = 'published' AND w.is_public = 1 AND w.visibility = 'PUBLIC') OR w.author_id = ?)"
            params.append(user_id)
        else:
            works_sql += " WHERE w.status = 'published' AND w.is_public = 1 AND w.visibility = 'PUBLIC'"
    works_sql += " ORDER BY COALESCE(w.published_at, w.created_at) DESC"
    work_rows = db.execute(works_sql, params).fetchall()
    comments_by_work: dict[int, list] = {}
    if work_rows:
        placeholders = ", ".join("?" for _ in work_rows)
        for comment in db.execute(
            f"""
            SELECT c.*, u.display_name AS author_name
            FROM comments c JOIN users u ON u.id = c.user_id
            WHERE c.deleted_at IS NULL AND c.work_id IN ({placeholders})
            ORDER BY c.created_at ASC
            """,
            [row["id"] for row in work_rows],
        ).fetchall():
            comments_by_work.setdefault(int(comment["work_id"]), []).append(comment)
    chapters_by_work: dict[int, list] = {}
    if work_rows:
        placeholders = ", ".join("?" for _ in work_rows)
        for chapter in db.execute(
            f"SELECT * FROM chapters WHERE work_id IN ({placeholders}) ORDER BY work_id ASC, chapter_number ASC, id ASC",
            [row["id"] for row in work_rows],
        ).fetchall():
            chapters_by_work.setdefault(int(chapter["work_id"]), []).append(chapter)
    chapter_comments_by_chapter: dict[int, list] = {}
    chapter_like_counts: dict[int, int] = {}
    liked_chapter_comments: set[int] = set()
    chapter_ids = [int(chapter["id"]) for rows in chapters_by_work.values() for chapter in rows]
    if chapter_ids:
        placeholders = ", ".join("?" for _ in chapter_ids)
        for comment in db.execute(
            f"""
            SELECT cc.*, u.display_name AS author_name
            FROM chapter_comments cc JOIN users u ON u.id = cc.user_id
            WHERE cc.deleted_at IS NULL AND cc.chapter_id IN ({placeholders})
            ORDER BY cc.created_at ASC
            """,
            chapter_ids,
        ).fetchall():
            chapter_comments_by_chapter.setdefault(int(comment["chapter_id"]), []).append(comment)
        comment_ids = [int(row["id"]) for rows in chapter_comments_by_chapter.values() for row in rows]
        if comment_ids:
            comment_placeholders = ", ".join("?" for _ in comment_ids)
            for row in db.execute(
                f"SELECT comment_id, COUNT(*) AS total FROM chapter_comment_likes WHERE comment_id IN ({comment_placeholders}) GROUP BY comment_id",
                comment_ids,
            ).fetchall():
                chapter_like_counts[int(row["comment_id"])] = int(row["total"])
            if user_id:
                liked_chapter_comments = {
                    int(row["comment_id"])
                    for row in db.execute(
                        f"SELECT comment_id FROM chapter_comment_likes WHERE user_id = ? AND comment_id IN ({comment_placeholders})",
                        [user_id] + comment_ids,
                    ).fetchall()
                }

    works = []
    for row in work_rows:
        comments = []
        for comment in comments_by_work.get(int(row["id"]), []):
            comments.append(
                {
                    "id": f"c{comment['id']}",
                    "who": comment["author_name"],
                    "userId": f"u{comment['user_id']}",
                    "text": comment["text"],
                    "at": comment["created_at"],
                }
            )
        visible_chapters = []
        for chapter in chapters_by_work.get(int(row["id"]), []):
            if is_admin or int(row["author_id"]) == int(user_id or 0) or chapter["status"] == "PUBLISHED":
                chapter_data = serialize_chapter(chapter)
                chapter_data["comments"] = [
                    serialize_chapter_comment(item, user_id, is_admin, liked_chapter_comments, chapter_like_counts)
                    for item in chapter_comments_by_chapter.get(int(chapter["id"]), [])
                ]
                visible_chapters.append(chapter_data)
        published_chapters = [chapter for chapter in visible_chapters if chapter["status"] == "PUBLISHED"]
        works.append(
            {
                "id": f"w{row['id']}",
                "title": row["title"],
                "author": row["author_name"],
                "authorId": f"u{row['author_id']}",
                "category": row["category"],
                "workFormat": row_value(row, "work_format", "single") or "single",
                "serialStatus": row_value(row, "serial_status", "ONGOING") or "ONGOING",
                "tags": json.loads(row["tags_json"] or "[]"),
                "likes": row["likes_count"],
                "views": row["views"],
                "favorites": row["favorites_count"],
                "commentsCount": row["comments_count"],
                "excerpt": row["excerpt"],
                "body": json.loads(row["body_json"] or "[]"),
                "comments": comments,
                "createdAt": row["published_at"] or row["created_at"],
                "publishedAt": row["published_at"],
                "updatedAt": row["updated_at"],
                "createdBy": f"u{row['author_id']}",
                "status": row["status"],
                "reviewNote": row["review_note"],
                "isPublic": bool(row_value(row, "is_public", 1)),
                "allowComments": bool(row_value(row, "allow_comments", 1)),
                "allowFavorites": bool(row_value(row, "allow_favorites", 1)),
                "originalConfirmed": bool(row_value(row, "original_confirmed", 0)),
                "rightsConfirmed": bool(row_value(row, "rights_confirmed", 0)),
                "visibility": row_value(row, "visibility", "PUBLIC") or "PUBLIC",
                "topicId": f"tp{row['topic_id']}" if row_value(row, "topic_id") else "",
                "hasCitation": bool(row_value(row, "citation_declared", 0)),
                "citationSources": row_value(row, "citation_sources", "") or "",
                "effectiveLikes": row["effective_likes_count"],
                "effectiveComments": row["effective_comments_count"],
                "chapters": visible_chapters,
                "chapterCount": len(published_chapters),
                "latestChapter": (published_chapters[-1]["title"] if published_chapters else ""),
                "effective": is_effective_work(
                    json.loads(row["body_json"] or "[]"), row["category"], row["status"],
                    row_value(row, "visibility", "PUBLIC") or "PUBLIC",
                ),
            }
        )

    public_work_filter = "" if is_admin else " AND w.is_public = 1 AND w.visibility = 'PUBLIC'"
    authors_sql = f"""
      SELECT u.*,
        (SELECT COUNT(*) FROM works w WHERE w.author_id = u.id AND w.status = 'published'{public_work_filter}) AS work_count,
        (SELECT COUNT(*) FROM follows f WHERE f.author_id = u.id) AS follower_count,
        (SELECT COUNT(*) FROM monthly_awards ma JOIN works w ON w.id = ma.work_id
          WHERE ma.author_id = u.id AND ma.status = 'active' AND w.status = 'published'{public_work_filter}) AS award_count,
        (SELECT COALESCE(SUM(w.views), 0) FROM works w WHERE w.author_id = u.id AND w.status = 'published'{public_work_filter}) AS views_count
      FROM users u
    """
    if not is_admin:
        authors_sql += " WHERE EXISTS (SELECT 1 FROM works w WHERE w.author_id = u.id AND w.status = 'published' AND w.is_public = 1 AND w.visibility = 'PUBLIC')"
    authors_sql += " ORDER BY work_count DESC, u.created_at ASC"
    authors = []
    for row in db.execute(authors_sql).fetchall():
        author = public_user(row)
        author.update({
            "workCount": row["work_count"],
            "followerCount": row["follower_count"],
            "awardCount": row["award_count"],
            "views": row["views_count"],
            "stats": author_work_stats(db, row["id"], public_only=not is_admin),
        })
        authors.append(author)

    activities = [
        {
            "id": f"e{row['id']}",
            "title": row["title"],
            "desc": row["description"],
            "date": " - ".join(value for value in (row["starts_at"], row["ends_at"]) if value),
            "status": row["status"],
            "rules": row["rules"],
        }
        for row in db.execute("SELECT * FROM activities ORDER BY created_at DESC").fetchall()
    ]

    announcement_sql = "SELECT * FROM announcements"
    if not is_admin:
        announcement_sql += " WHERE status IN ('published', 'pinned')"
    announcement_sql += " ORDER BY CASE WHEN status = 'pinned' THEN 0 ELSE 1 END, created_at DESC"
    total_users = int(db.execute("SELECT COUNT(*) AS count FROM users").fetchone()["count"]) if is_admin else 0
    announcements = []
    for row in db.execute(announcement_sql).fetchall():
        confirmed_count = 0
        if is_admin:
            confirmed_count = int(db.execute(
                "SELECT COUNT(*) AS count FROM notifications WHERE type = 'announcement_confirm' AND link = ?",
                (f"announcement:{row['id']}",),
            ).fetchone()["count"])
        announcements.append({
            "id": f"ann{row['id']}",
            "title": row["title"],
            "content": row["content"],
            "status": row["status"],
            "pinned": row["status"] == "pinned",
            "at": iso_time(row["created_at"]),
            "updatedAt": iso_time(row["updated_at"]),
            "confirmedCount": confirmed_count,
            "unconfirmedCount": max(0, total_users - confirmed_count) if is_admin else 0,
        })

    monthly_visibility = "AND w.status = 'published' AND w.is_public = 1 AND w.visibility = 'PUBLIC'"
    monthly_awards = [
        {
            "id": f"a{row['id']}",
            "workId": f"w{row['work_id']}",
            "authorId": f"u{row['author_id']}",
            "category": row["category"],
            "month": row["month"],
            "rank": int(row["rank"]),
            "reason": row["reason"],
            "selectedAt": iso_time(row["selected_at"]),
            "selectedBy": f"u{row['selected_by']}" if row["selected_by"] else "",
            "selectedByName": row["selected_by_name"] or "",
            "status": row["status"],
        }
        for row in db.execute(
            f"""
            SELECT ma.*, u.display_name AS selected_by_name
            FROM monthly_awards ma
            LEFT JOIN users u ON u.id = ma.selected_by
            JOIN works w ON w.id = ma.work_id
            WHERE ma.status = 'active'
            {monthly_visibility}
            ORDER BY ma.month DESC, ma.rank ASC, ma.id DESC
            """
        ).fetchall()
    ]
    monthly_picks = [row["workId"] for row in monthly_awards]

    followed = []
    followed_works = []
    blocked = []
    blocked_users = []
    liked = []
    favorited = []
    bookshelf = []
    reading_progress = []
    notifications = []
    announcement_confirms = []
    conversations = []
    message_settings = {"allowStrangers": True, "recallMinutes": 2, "notifications": True}
    reports = []
    audit_logs = []
    users = []
    admin_roles = []
    admin_transfers = []
    agent_runs = []
    agent_results = []
    agent_tasks = []

    if user_id:
        followed = [f"u{row['author_id']}" for row in db.execute("SELECT author_id FROM follows WHERE follower_id = ?", (user_id,)).fetchall()]
        followed_works = [f"w{row['work_id']}" for row in db.execute("SELECT work_id FROM work_follows WHERE user_id = ?", (user_id,)).fetchall()]
        blocked_rows = db.execute(
            """
            SELECT u.* FROM blocks b JOIN users u ON u.id = b.blocked_id
            WHERE b.blocker_id = ? ORDER BY b.created_at DESC
            """,
            (user_id,),
        ).fetchall()
        blocked = [f"u{row['id']}" for row in blocked_rows]
        blocked_users = [public_user(row) for row in blocked_rows]
        liked = [f"w{row['work_id']}" for row in db.execute("SELECT work_id FROM likes WHERE user_id = ?", (user_id,)).fetchall()]
        favorited = [f"w{row['work_id']}" for row in db.execute("SELECT work_id FROM favorites WHERE user_id = ?", (user_id,)).fetchall()]
        bookshelf = [
            {
                "id": f"bs{row['id']}",
                "workId": f"w{row['work_id']}",
                "status": row["status"],
                "addedAt": row["created_at"],
                "updatedAt": row["updated_at"],
            }
            for row in db.execute(
                "SELECT * FROM bookshelf WHERE user_id = ? ORDER BY updated_at DESC", (user_id,)
            ).fetchall()
        ]
        reading_progress = [
            {
                "workId": f"w{row['work_id']}",
                "chapterId": f"ch{row['last_chapter_id']}",
                "lastReadAt": row["last_read_at"],
            }
            for row in db.execute(
                "SELECT * FROM reading_progress WHERE user_id = ? ORDER BY last_read_at DESC", (user_id,)
            ).fetchall()
        ]
        notifications = [
            {
                "id": f"n{row['id']}",
                "text": row["text"],
                "at": iso_time(row["created_at"]),
                "read": bool(row["read_at"]),
                "type": row["type"],
                "link": row["link"],
                "workId": f"w{row['work_id']}" if row["work_id"] else "",
                "chapterId": f"ch{row['chapter_id']}" if row["chapter_id"] else "",
            }
            for row in db.execute(
                "SELECT * FROM notifications WHERE user_id = ? ORDER BY created_at DESC LIMIT 100",
                (user_id,),
            ).fetchall()
        ]
        announcement_confirms = [
            row["link"].split(":", 1)[1]
            for row in db.execute(
                "SELECT link FROM notifications WHERE user_id = ? AND type = 'announcement_confirm' AND link LIKE ?",
                (user_id, "announcement:%"),
            ).fetchall()
        ]
        settings = db.execute("SELECT * FROM message_settings WHERE user_id = ?", (user_id,)).fetchone()
        if settings:
            message_settings = {
                "allowStrangers": bool(settings["allow_strangers"]),
                "recallMinutes": int(settings["recall_minutes"]),
                "notifications": bool(settings["notifications"]),
            }
        conversation_rows = db.execute(
            """
            SELECT c.*, CASE WHEN c.user_low_id = ? THEN c.user_high_id ELSE c.user_low_id END AS other_id
            FROM conversations c
            WHERE c.user_low_id = ? OR c.user_high_id = ?
            ORDER BY c.updated_at DESC
            """,
            (user_id, user_id, user_id),
        ).fetchall()
        for conversation in conversation_rows:
            hidden = db.execute(
                "SELECT hidden FROM conversation_hidden WHERE conversation_id = ? AND user_id = ?",
                (conversation["id"], user_id),
            ).fetchone()
            message_rows = db.execute(
                "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at ASC",
                (conversation["id"],),
            ).fetchall()
            unread = sum(1 for item in message_rows if item["sender_id"] != user_id and not item["read_at"])
            conversations.append(
                {
                    "id": f"cv{conversation['id']}",
                    "userId": f"u{conversation['other_id']}",
                    "hidden": bool(hidden and hidden["hidden"]),
                    "unread": unread,
                    "messages": [
                        {
                            "id": f"m{item['id']}",
                            "mine": item["sender_id"] == user_id,
                            "text": item["text"],
                            "at": item["created_at"],
                            "replyTo": f"m{item['reply_to_id']}" if item["reply_to_id"] else "",
                            "recalled": bool(item["recalled_at"]),
                        }
                        for item in message_rows
                    ],
                }
            )

    if is_admin:
        user_rows = db.execute("SELECT * FROM users ORDER BY created_at ASC LIMIT 500").fetchall()
        role_rows = db.execute("SELECT * FROM admin_roles").fetchall()
        user_names = {f"u{row['id']}": row["display_name"] for row in user_rows}
        admin_roles = [
            {
                "userId": f"u{row['user_id']}",
                "name": user_names.get(f"u{row['user_id']}", ""),
                "level": row["level"],
                "appointedAt": iso_time(row["appointed_at"]),
            }
            for row in role_rows
        ]
        users = []
        for row in user_rows:
            item = public_user(row)
            level = next((entry["level"] for entry in admin_roles if entry["userId"] == item["id"]), "")
            item["adminLevel"] = level
            item["accountStatus"] = row_value(row, "account_status", "active")
            users.append(item)
        admin_transfers = [
            {
                "id": f"t{row['id']}",
                "oldAdminId": f"u{row['old_admin_id']}",
                "oldName": row["old_name"] or "",
                "newAdminId": f"u{row['new_admin_id']}",
                "newName": row["new_name"] or "",
                "operatorId": f"u{row['operator_id']}",
                "operatorName": row["operator_name"] or "",
                "reason": row["reason"],
                "at": iso_time(row["created_at"]),
            }
            for row in db.execute(
                """
                SELECT t.*, old.display_name AS old_name, new.display_name AS new_name,
                       operator.display_name AS operator_name
                FROM admin_transfers t
                LEFT JOIN users old ON old.id = t.old_admin_id
                LEFT JOIN users new ON new.id = t.new_admin_id
                LEFT JOIN users operator ON operator.id = t.operator_id
                ORDER BY t.created_at DESC LIMIT 100
                """
            ).fetchall()
        ]
        reports = [
            {
                "id": f"r{row['id']}",
                "type": row["type"],
                "target": row["target_label"],
                "reason": row["reason"],
                "detail": row["detail"],
                "message": row["message_excerpt"],
                "at": iso_time(row["created_at"]),
                "status": row["status"],
            }
            for row in db.execute("SELECT * FROM reports ORDER BY created_at DESC LIMIT 200").fetchall()
        ]
        audit_logs = [
            {
                "id": f"l{row['id']}",
                "actorId": f"u{row['actor_id']}" if row["actor_id"] else "",
                "actorName": row["actor_name"] or "系统",
                "action": row["action"],
                "text": row["detail"] or row["action"],
                "at": iso_time(row["created_at"]),
            }
            for row in db.execute(
                """
                SELECT a.*, u.display_name AS actor_name
                FROM audit_logs a LEFT JOIN users u ON u.id = a.actor_id
                ORDER BY a.created_at DESC LIMIT 100
                """
            ).fetchall()
        ]
        agent_runs = [
            {
                "runId": row["agent_run_id"],
                "contentType": row["content_type"],
                "contentId": f"ch{row['content_id']}" if row["content_type"] == "chapter" else f"w{row['content_id']}",
                "workId": f"w{row['content_id']}" if row["content_type"] == "work" else "",
                "userId": f"u{row['user_id']}" if row["user_id"] else "",
                "status": row["status"],
                "error": row["error"],
                "duration": int(row["duration"] or 0),
                "policyVersion": row["policy_version"],
                "model": row["model"],
                "at": iso_time(row["created_at"]),
            }
            for row in db.execute(
                "SELECT * FROM agent_runs ORDER BY created_at DESC LIMIT 100"
            ).fetchall()
        ]
        agent_results = [
            {
                "runId": row["agent_run_id"],
                "contentType": row["content_type"],
                "contentId": f"ch{row['content_id']}" if row["content_type"] == "chapter" else f"w{row['content_id']}",
                "workId": f"w{row['content_id']}" if row["content_type"] == "work" else "",
                "riskLevel": row["risk_level"],
                "category": row["category"],
                "confidence": float(row["confidence"] or 0),
                "recommendation": row["recommendation"],
                "needsHumanReview": bool(row["needs_human_review"]),
                "at": iso_time(row["created_at"]),
            }
            for row in db.execute(
                "SELECT * FROM agent_moderation_results ORDER BY created_at DESC LIMIT 100"
            ).fetchall()
        ]
        agent_tasks = [
            {
                "runId": row["agent_run_id"],
                "workId": f"w{row['work_id']}",
                "reason": row["reason"],
                "status": row["status"],
                "at": iso_time(row["created_at"]),
            }
            for row in db.execute(
                "SELECT * FROM agent_review_tasks ORDER BY CASE WHEN status = 'open' THEN 0 ELSE 1 END, created_at DESC LIMIT 100"
            ).fetchall()
        ]

    topic_sql = """
      SELECT t.*, u.display_name AS creator_name,
        (SELECT COUNT(*) FROM works w WHERE w.topic_id = t.id AND w.status IN ('pending', 'published')) AS submissions
      FROM topics t LEFT JOIN users u ON u.id = t.created_by
    """
    if not is_admin:
        topic_sql += " WHERE t.status != 'DRAFT'"
    topic_sql += " ORDER BY COALESCE(t.published_at, t.created_at) DESC"
    topics = [
        {
            "id": f"tp{row['id']}",
            "title": row["title"],
            "description": row["description"],
            "startAt": iso_time(row["start_at"]),
            "endAt": iso_time(row["end_at"]),
            "startMs": int(row["start_at"] or 0),
            "endMs": int(row["end_at"] or 0),
            "status": row["status"],
            "submissions": int(row["submissions"]),
            "creatorName": row["creator_name"] or "",
            "publishedAt": iso_time(row["published_at"]) if row["published_at"] else "",
        }
        for row in db.execute(topic_sql).fetchall()
    ]

    risk_events = []
    plagiarism_flags = []
    if is_admin:
        risk_events = [
            {
                "id": f"rk{row['id']}",
                "userId": f"u{row['user_id']}" if row["user_id"] else "",
                "userName": row["user_name"] or "未知用户",
                "kind": row["kind"],
                "level": row["level"],
                "detail": row["detail"],
                "status": row["status"],
                "at": iso_time(row["created_at"]),
            }
            for row in db.execute(
                """
                SELECT r.*, u.display_name AS user_name FROM risk_events r
                LEFT JOIN users u ON u.id = r.user_id
                ORDER BY r.created_at DESC LIMIT 200
                """
            ).fetchall()
        ]
        plagiarism_flags = [
            {
                "id": f"pc{row['id']}",
                "workId": f"w{row['work_id']}",
                "workTitle": row["work_title"] or "",
                "matchedWorkId": f"w{row['matched_work_id']}" if row["matched_work_id"] else "",
                "matchedTitle": row["matched_title"] or "",
                "score": round(float(row["score"] or 0) * 100),
                "level": row["level"],
                "status": row["status"],
                "at": iso_time(row["created_at"]),
            }
            for row in db.execute(
                """
                SELECT p.*, w.title AS work_title, m.title AS matched_title
                FROM plagiarism_checks p
                LEFT JOIN works w ON w.id = p.work_id
                LEFT JOIN works m ON m.id = p.matched_work_id
                WHERE p.level != 'low'
                ORDER BY p.created_at DESC LIMIT 100
                """
            ).fetchall()
        ]

    book_shares = build_book_shares(db, user_id)
    current_user = public_user(user) if user else {"id": "", "name": "访客", "role": "guest"}
    if user and user["role"] == "admin":
        current_user["adminLevel"] = admin_level(user)

    return {
        "schemaVersion": 13,
        "currentUser": current_user,
        "followed": followed,
        "followedWorks": followed_works,
        "blocked": blocked,
        "blockedUsers": blocked_users,
        "likedWorks": liked,
        "favoritedWorks": favorited,
        "bookshelf": bookshelf,
        "readingProgress": reading_progress,
        "likedChapterComments": [f"cc{value}" for value in sorted(liked_chapter_comments)],
        "notifications": notifications,
        "announcementConfirms": announcement_confirms,
        "works": works,
        "authors": authors,
        "activities": activities,
        "announcements": announcements,
        "bookShares": book_shares,
        "reports": reports,
        "auditLogs": audit_logs,
        "messageSettings": message_settings,
        "monthlyPicks": monthly_picks,
        "monthlyAwards": monthly_awards,
        "conversations": conversations,
        "users": users,
        "adminRoles": admin_roles,
        "adminTransfers": admin_transfers,
        "topics": topics,
        "riskEvents": risk_events,
        "plagiarismFlags": plagiarism_flags,
        "agentRuns": agent_runs,
        "agentResults": agent_results,
        "agentTasks": agent_tasks,
        "systemHealth": build_system_health(db, is_admin),
        "rankings": build_rankings(db, authors),
        "rankingWeights": RANKING_WEIGHTS,
    }


# 访客状态与登录用户无关，且读多写少；短缓存可省下每次请求几十次数据库往返。
_GUEST_STATE_CACHE = {"at": 0.0, "state": None}
GUEST_STATE_TTL = 15


def bootstrap_payload() -> dict:
    user = current_user_row()
    if user:
        # 写操作后重新读取当前用户，避免响应里返回修改前的缓存行
        user = get_db().execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
        g.user = user
        return {
            "csrfToken": get_csrf_value(),
            "state": build_state(user),
        }
    now = time.time()
    if _GUEST_STATE_CACHE["state"] is None or now - _GUEST_STATE_CACHE["at"] > GUEST_STATE_TTL:
        _GUEST_STATE_CACHE["state"] = build_state(None)
        _GUEST_STATE_CACHE["at"] = now
    return {
        "csrfToken": get_csrf_value(),
        "state": _GUEST_STATE_CACHE["state"],
    }


@app.before_request
def enforce_csrf():
    if not request.path.startswith("/api/"):
        return None
    user = current_user_row()
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        expected = g.session["csrf_token"] if user and getattr(g, "session", None) else request.cookies.get(CSRF_COOKIE)
        supplied = request.headers.get("X-CSRF-Token", "")
        if not expected or not supplied or not hmac.compare_digest(str(expected), str(supplied)):
            return json_error("请求校验失败，请刷新页面后重试", 403)
    return None


@app.after_request
def security_headers(response):
    response.headers.setdefault("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    if IS_PRODUCTION and request.is_secure:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    if request.path.startswith("/api/") or request.path == "/":
        session = getattr(g, "session", None)
        token = session["csrf_token"] if session else getattr(g, "guest_csrf", None)
        if token:
            response.set_cookie(
                CSRF_COOKIE,
                token,
                max_age=SESSION_DAYS * 24 * 60 * 60,
                secure=IS_PRODUCTION,
                httponly=True,
                samesite="Lax",
                path="/",
            )
    return response


@app.errorhandler(400)
def handle_bad_request(_error):
    return json_error("请求参数无效", 400) if request.path.startswith("/api/") else ("Bad Request", 400)


@app.errorhandler(403)
def handle_forbidden(_error):
    return json_error("请求未被允许", 403) if request.path.startswith("/api/") else ("Forbidden", 403)


@app.errorhandler(404)
def handle_not_found(_error):
    return json_error("接口不存在", 404) if request.path.startswith("/api/") else ("Not Found", 404)


@app.errorhandler(413)
def handle_too_large(_error):
    return json_error("请求体过大", 413)


@app.errorhandler(415)
def handle_unsupported_media(_error):
    return json_error("请求格式不支持", 415)


@app.errorhandler(500)
def handle_server_error(_error):
    return json_error("服务器处理失败", 500)


@app.get("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")


@app.get("/<path:filename>")
def public_file(filename: str):
    first = filename.split("/", 1)[0]
    if filename not in PUBLIC_FILES and first not in PUBLIC_ROOTS:
        abort(404)
    if filename.endswith((".py", ".db", ".sqlite", ".sqlite3")):
        abort(404)
    return send_from_directory(BASE_DIR, filename)


@app.get("/api/bootstrap")
def bootstrap():
    return json_ok(bootstrap_payload())


@app.post("/api/auth/register")
def register():
    # 注册接口已按要求取消频率限制：正常用户不再因连续提交被判为频繁。
    # 下面仍保留 register_burst 风险记录（只写风控信号，不拦截注册）。
    payload = request_json()
    username = clean_text(payload.get("username"), 32, required=True)
    display_name = clean_text(payload.get("displayName"), 40, required=True)
    password = str(payload.get("password") or "")
    if not USERNAME_RE.fullmatch(username):
        return json_error("用户名需为 3-32 位字母、数字或下划线", 400)
    if len(password) < 8 or len(password) > 128:
        return json_error("密码需为 8-128 位", 400)
    db = get_db()
    if db.execute("SELECT 1 FROM users WHERE LOWER(username) = LOWER(?)", (username,)).fetchone():
        return json_error("该用户名已被使用", 409)
    try:
        cursor = db.execute(
            "INSERT INTO users (username, display_name, password_hash, role, bio, created_at) VALUES (?, ?, ?, 'reader', '', ?)",
            (username, display_name, generate_password_hash(password), now_ms()),
        )
    except Exception:
        # 并发重复提交时唯一约束会拒绝第二次写入；不覆盖已有账户，只返回同样的提示
        db.rollback()
        if db.execute("SELECT 1 FROM users WHERE LOWER(username) = LOWER(?)", (username,)).fetchone():
            return json_error("该用户名已被使用", 409)
        raise
    user_id = cursor.lastrowid
    if not rate_limit("register_burst", 3, 3600):
        record_risk(db, user_id, "register_burst", "同一来源一小时内注册多个账号", level="MEDIUM", target_type="user", target_id=str(user_id))
    ensure_message_settings(user_id)
    notify(user_id, "欢迎来到芳菲文学社。从浏览作品或投稿开始。", "system")
    audit("注册账号", "user", str(user_id), f"用户 {display_name} 注册", user_id)
    db.commit()
    raw_token, csrf_token = issue_session(user_id)
    response = json_ok(bootstrap_payload())
    response.set_cookie(CSRF_COOKIE, csrf_token, max_age=SESSION_DAYS * 24 * 60 * 60, secure=IS_PRODUCTION, httponly=True, samesite="Lax", path="/")
    return set_session_cookie(response, raw_token)


@app.post("/api/auth/login")
def login():
    if not rate_limit("login", 10, 600):
        return json_error("登录尝试过于频繁", 429)
    payload = request_json()
    username = clean_text(payload.get("username"), 32, required=True)
    password = str(payload.get("password") or "")
    user = get_db().execute("SELECT * FROM users WHERE LOWER(username) = LOWER(?)", (username,)).fetchone()
    if not user or row_value(user, "account_status", "active") != "active" or not check_password_hash(user["password_hash"], password):
        return json_error("用户名或密码不正确", 401)
    raw_token, csrf_token = issue_session(user["id"])
    response = json_ok(bootstrap_payload())
    response.set_cookie(CSRF_COOKIE, csrf_token, max_age=SESSION_DAYS * 24 * 60 * 60, secure=IS_PRODUCTION, httponly=True, samesite="Lax", path="/")
    return set_session_cookie(response, raw_token)


@app.post("/api/auth/logout")
@require_auth
def logout():
    if getattr(g, "session", None):
        get_db().execute("DELETE FROM sessions WHERE token_hash = ?", (g.session["token_hash"],))
        get_db().commit()
    g.user = None
    g.session = None
    g.guest_csrf = secrets.token_urlsafe(32)
    response = json_ok(bootstrap_payload())
    response.set_cookie(CSRF_COOKIE, g.guest_csrf, max_age=SESSION_DAYS * 24 * 60 * 60, secure=IS_PRODUCTION, httponly=True, samesite="Lax", path="/")
    return clear_session_cookie(response)


@app.post("/api/auth/change-password")
@require_auth
def change_password():
    payload = request_json()
    current_password = str(payload.get("currentPassword") or "")
    new_password = str(payload.get("newPassword") or "")
    if not check_password_hash(g.user["password_hash"], current_password):
        return json_error("当前密码不正确", 400)
    if len(new_password) < 8 or len(new_password) > 128:
        return json_error("新密码需为 8-128 位", 400)
    get_db().execute("UPDATE users SET password_hash = ? WHERE id = ?", (generate_password_hash(new_password), g.user["id"]))
    audit("修改密码", "user", str(g.user["id"]), "用户修改密码", g.user["id"])
    get_db().commit()
    return json_ok(bootstrap_payload())


@app.post("/api/profile")
@require_auth
def update_profile():
    payload = request_json()
    name = clean_text(payload.get("displayName"), 40, required=True)
    bio = clean_text(payload.get("bio"), 300)
    avatar = clean_text(payload.get("avatar"), 4)
    cover_theme = clean_text(payload.get("coverTheme"), 20)
    preferences = clean_text(payload.get("preferences"), 500)
    genres_value = payload.get("genres") if isinstance(payload.get("genres"), list) else []
    genres = [clean_text(item, 20) for item in genres_value if clean_text(item, 20)]
    genres = [item for item in dict.fromkeys(genres) if item in WORK_CATEGORIES][:6]
    if cover_theme not in PROFILE_COVER_THEMES:
        return json_error("背景主题无效", 400)
    get_db().execute(
        """
        UPDATE users SET display_name = ?, bio = ?, avatar = ?, cover_theme = ?,
          literary_preferences = ?, genres_json = ?
        WHERE id = ?
        """,
        (name, bio, avatar, cover_theme, preferences, json.dumps(genres, ensure_ascii=False), g.user["id"]),
    )
    audit("修改资料", "user", str(g.user["id"]), "用户更新个人资料", g.user["id"])
    get_db().commit()
    return json_ok(bootstrap_payload())


def save_work(work_id: int | None = None):
    payload = request_json()
    action = clean_text(payload.get("action") or "submit", 10)
    if action not in {"draft", "submit"}:
        return json_error("投稿操作无效", 400)
    title = clean_text(payload.get("title"), 80, required=True)
    category = clean_text(payload.get("category") or "其他", 20, required=True)
    if category not in WORK_CATEGORIES:
        return json_error("作品类型无效", 400)
    work_format = clean_text(payload.get("workFormat") or "single", 10).lower()
    if work_format not in WORK_FORMATS:
        return json_error("作品形式无效", 400)
    serial_status = clean_text(payload.get("serialStatus") or "ONGOING", 20).upper()
    if serial_status not in SERIAL_STATUSES:
        return json_error("连载状态无效", 400)
    if work_format == "single":
        serial_status = "ONGOING"
    tags_value = payload.get("tags") if isinstance(payload.get("tags"), list) else []
    tags = [clean_text(tag, 20) for tag in tags_value if clean_text(tag, 20)][:10]
    body_value = payload.get("body") if isinstance(payload.get("body"), list) else []
    body_text = "\n".join(str(part) for part in body_value if part)
    if len(body_text) > MAX_WORK_BODY_CHARS or word_count(body_value) > MAX_WORK_BODY_CHARS:
        return json_error(f"正文超过 {MAX_WORK_BODY_CHARS} 字限制", 400)
    body = [clean_text(paragraph, MAX_WORK_BODY_CHARS) for paragraph in body_value if clean_text(paragraph, MAX_WORK_BODY_CHARS)]
    original_confirmed = bool(payload.get("originalConfirmed"))
    rights_confirmed = bool(payload.get("rightsConfirmed"))
    if action == "submit":
        if not body:
            return json_error("提交审核前需要填写正文", 400)
        if not original_confirmed or not rights_confirmed:
            return json_error("提交审核前需要确认原创与展示授权", 400)
    is_public = bool(payload.get("isPublic", True))
    allow_comments = bool(payload.get("allowComments", True))
    allow_favorites = bool(payload.get("allowFavorites", True))
    visibility = clean_text(payload.get("visibility") or "PUBLIC", 10).upper()
    if visibility not in WORK_VISIBILITY:
        return json_error("作品可见性无效", 400)
    has_citation = bool(payload.get("hasCitation"))
    citation_sources = clean_text(payload.get("citationSources"), 500) if has_citation else ""
    topic_id = parse_numeric_id(payload.get("topicId"))
    excerpt = clean_text(payload.get("excerpt"), 200) or (body[0][:90] if body else "")
    timestamp = now_ms()
    db = get_db()
    if topic_id and not db.execute("SELECT 1 FROM topics WHERE id = ?", (topic_id,)).fetchone():
        return json_error("投稿话题不存在", 404)
    if work_id is None:
        if not rate_limit("create_work", 20, 3600):
            return json_error("投稿过于频繁", 429)
        status = "draft" if action == "draft" else "pending_agent"
        cursor = db.execute(
            """
            INSERT INTO works (
              author_id, title, category, work_format, serial_status, tags_json, excerpt, body_json, status, review_note,
              is_public, allow_comments, allow_favorites, original_confirmed, rights_confirmed,
              visibility, topic_id, citation_declared, citation_sources,
              created_at, updated_at, published_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                g.user["id"], title, category, work_format, serial_status,
                json.dumps(tags, ensure_ascii=False), excerpt, json.dumps(body, ensure_ascii=False), status,
                int(is_public), int(allow_comments), int(allow_favorites), int(original_confirmed), int(rights_confirmed),
                visibility, topic_id, int(has_citation), citation_sources, timestamp, timestamp, None,
            ),
        )
        work_id = cursor.lastrowid
    else:
        existing = db.execute("SELECT * FROM works WHERE id = ? AND author_id = ?", (work_id, g.user["id"])).fetchone()
        if not existing:
            return json_error("作品不存在或无权修改", 404)
        if existing["status"] not in {"draft", "rejected", "pending", "pending_agent", "pending_review", "published"}:
            return json_error("当前状态的投稿不能修改", 409)
        if existing["status"] == "published" and action == "draft":
            return json_error("已发表作品修改后必须重新提交审核", 409)
        if existing["status"] == "published":
            snapshot_work_version(db, existing, "修改已发表作品，保留原版本")
        status = "draft" if action == "draft" else "pending_agent"
        db.execute(
            """
            UPDATE works SET title = ?, category = ?, work_format = ?, serial_status = ?, tags_json = ?, excerpt = ?, body_json = ?,
              status = ?, review_note = '', is_public = ?, allow_comments = ?, allow_favorites = ?,
              original_confirmed = ?, rights_confirmed = ?, visibility = ?, topic_id = ?,
              citation_declared = ?, citation_sources = ?, updated_at = ?, published_at = NULL
            WHERE id = ? AND author_id = ?
            """,
            (
                title, category, work_format, serial_status, json.dumps(tags, ensure_ascii=False), excerpt,
                json.dumps(body, ensure_ascii=False), status, int(is_public), int(allow_comments),
                int(allow_favorites), int(original_confirmed), int(rights_confirmed),
                visibility, topic_id, int(has_citation), citation_sources, timestamp,
                work_id, g.user["id"],
            ),
        )
    if action == "submit":
        similarity = detect_similarity(db, "\n".join(body), exclude_work_id=work_id)
        matched_id = parse_numeric_id(similarity.get("workId"))
        db.execute(
            "INSERT INTO plagiarism_checks (work_id, matched_work_id, score, level, status, created_at) VALUES (?, ?, ?, ?, 'open', ?)",
            (work_id, matched_id, float(similarity["score"]), similarity["level"], timestamp),
        )
        if similarity["level"] == "high":
            record_risk(
                db, g.user["id"], "similar_work",
                f"作品《{title}》与《{similarity['title']}》相似度 {similarity['score']:.0%}",
                level="HIGH", target_type="work", target_id=str(work_id),
            )
    if action == "submit":
        # 先提交作品本身，Agent 无论成功或异常都不会丢失稿件。
        db.commit()
        agent_result = run_agent_review(work_id, g.user["id"], title, body, category)
        if agent_result.get("needs_human_review"):
            notice = f"作品《{title}》已提交，Agent 建议人工复核。"
        else:
            notice = f"作品《{title}》已通过 Agent 自动审核并发布。"
    else:
        notice = f"作品《{title}》已保存为草稿。"
    action_text = "保存草稿" if action == "draft" else "提交审核"
    audit(action_text, "work", str(work_id), f"{action_text}《{title}》", g.user["id"])
    notify(g.user["id"], notice, "work", f"#/work/w{work_id}")
    db.commit()
    return json_ok(bootstrap_payload())


@app.post("/api/works")
@require_auth
def create_work():
    return save_work()


@app.post("/api/works/<int:work_id>")
@require_auth
def update_work(work_id: int):
    return save_work(work_id)


def owned_serial_work(work_id: int):
    work = get_db().execute("SELECT * FROM works WHERE id = ?", (work_id,)).fetchone()
    if not work:
        return None
    if work["author_id"] != g.user["id"] or (work["work_format"] or "single") != "serial" or work["status"] == "hidden":
        return None
    return work


def owned_chapter(chapter_id: int):
    chapter = get_db().execute("SELECT * FROM chapters WHERE id = ?", (chapter_id,)).fetchone()
    if not chapter:
        return None, None
    work = owned_serial_work(chapter["work_id"])
    if not work:
        return None, None
    return chapter, work


def chapter_input():
    payload = request_json()
    action = clean_text(payload.get("action") or "draft", 10)
    if action not in {"draft", "submit"}:
        return None, "章节操作无效"
    title = clean_text(payload.get("title"), 120, required=True)
    body_value = payload.get("body") if isinstance(payload.get("body"), list) else []
    body_text = "\n".join(str(part) for part in body_value if part)
    if len(body_text) > MAX_WORK_BODY_CHARS or word_count(body_value) > MAX_WORK_BODY_CHARS:
        return None, f"章节正文超过 {MAX_WORK_BODY_CHARS} 字限制"
    body = [clean_text(paragraph, MAX_WORK_BODY_CHARS) for paragraph in body_value if clean_text(paragraph, MAX_WORK_BODY_CHARS)]
    if action == "submit" and not body:
        return None, "提交审核前需要填写章节正文"
    return (action, title, "\n\n".join(body)), ""


@app.post("/api/works/<int:work_id>/chapters")
@require_auth
def create_chapter(work_id: int):
    work = owned_serial_work(work_id)
    if not work:
        return json_error("连载作品不存在或无权操作", 404)
    chapter_data, error = chapter_input()
    if error:
        return json_error(error, 400)
    action, title, content = chapter_data
    if action == "submit" and work["status"] != "published":
        return json_error("连载作品发布后才能提交章节审核", 409)
    db = get_db()
    timestamp = now_ms()
    number = int(db.execute("SELECT COALESCE(MAX(chapter_number), 0) + 1 AS next_number FROM chapters WHERE work_id = ?", (work_id,)).fetchone()["next_number"])
    cursor = db.execute(
        "INSERT INTO chapters (work_id, chapter_number, title, content, status, review_note, created_at, updated_at) VALUES (?, ?, ?, ?, 'DRAFT', '', ?, ?)",
        (work_id, number, title, content, timestamp, timestamp),
    )
    chapter_id = cursor.lastrowid
    db.commit()
    if action == "submit":
        result = run_chapter_agent_review(chapter_id, g.user["id"], work_id, title, content)
        label = "已通过 Agent 审核并发布" if result.get("status") == "PUBLISHED" else "已提交，等待人工复核"
        notify(g.user["id"], f"章节《{title}》{label}。", "chapter", f"#/serial/w{work_id}")
        audit("提交章节", "chapter", str(chapter_id), f"提交《{title}》", g.user["id"])
    else:
        audit("保存章节草稿", "chapter", str(chapter_id), f"保存《{title}》草稿", g.user["id"])
    db.commit()
    return json_ok(bootstrap_payload())


@app.post("/api/chapters/<int:chapter_id>")
@require_auth
def update_chapter(chapter_id: int):
    chapter, work = owned_chapter(chapter_id)
    if not chapter or not work:
        return json_error("章节不存在或无权操作", 404)
    if chapter["status"] not in {"DRAFT", "REJECTED"}:
        return json_error("当前章节状态不能编辑", 409)
    chapter_data, error = chapter_input()
    if error:
        return json_error(error, 400)
    action, title, content = chapter_data
    if action == "submit" and work["status"] != "published":
        return json_error("连载作品发布后才能提交章节审核", 409)
    db = get_db()
    timestamp = now_ms()
    db.execute(
        "UPDATE chapters SET title = ?, content = ?, status = 'DRAFT', review_note = '', published_at = NULL, updated_at = ? WHERE id = ?",
        (title, content, timestamp, chapter_id),
    )
    db.commit()
    if action == "submit":
        result = run_chapter_agent_review(chapter_id, g.user["id"], work["id"], title, content)
        label = "已通过 Agent 审核并发布" if result.get("status") == "PUBLISHED" else "已提交，等待人工复核"
        notify(g.user["id"], f"章节《{title}》{label}。", "chapter", f"#/serial/w{work['id']}")
        audit("提交章节", "chapter", str(chapter_id), f"提交《{title}》", g.user["id"])
    else:
        audit("保存章节草稿", "chapter", str(chapter_id), f"保存《{title}》草稿", g.user["id"])
    db.commit()
    return json_ok(bootstrap_payload())


@app.post("/api/chapters/<int:chapter_id>/delete")
@require_auth
def delete_chapter(chapter_id: int):
    chapter, work = owned_chapter(chapter_id)
    if not chapter or not work:
        return json_error("章节不存在或无权操作", 404)
    if chapter["status"] != "DRAFT":
        return json_error("只能删除章节草稿", 409)
    db = get_db()
    db.execute("DELETE FROM chapters WHERE id = ? AND work_id = ?", (chapter_id, work["id"]))
    audit("删除章节草稿", "chapter", str(chapter_id), f"删除《{chapter['title']}》草稿", g.user["id"])
    db.commit()
    return json_ok(bootstrap_payload())


@app.post("/api/works/<int:work_id>/chapters/reorder")
@require_auth
def reorder_chapters(work_id: int):
    work = owned_serial_work(work_id)
    if not work:
        return json_error("连载作品不存在或无权操作", 404)
    payload = request_json()
    order = payload.get("order") if isinstance(payload.get("order"), list) else []
    chapter_ids = [parse_numeric_id(item) for item in order]
    if any(not chapter_id for chapter_id in chapter_ids) or len(set(chapter_ids)) != len(chapter_ids):
        return json_error("章节顺序无效", 400)
    rows = get_db().execute("SELECT id FROM chapters WHERE work_id = ?", (work_id,)).fetchall()
    existing = {int(row["id"]) for row in rows}
    if set(chapter_ids) != existing:
        return json_error("章节顺序必须包含全部章节", 400)
    db = get_db()
    timestamp = now_ms()
    for index, chapter_id in enumerate(chapter_ids, 1):
        db.execute("UPDATE chapters SET chapter_number = ?, updated_at = ? WHERE id = ? AND work_id = ?", (-index, timestamp, chapter_id, work_id))
    for index, chapter_id in enumerate(chapter_ids, 1):
        db.execute("UPDATE chapters SET chapter_number = ? WHERE id = ? AND work_id = ?", (index, chapter_id, work_id))
    audit("调整章节顺序", "work", str(work_id), "调整连载章节顺序", g.user["id"])
    db.commit()
    return json_ok(bootstrap_payload())


@app.post("/api/shelf/<int:work_id>")
@require_auth
def update_shelf(work_id: int):
    work = public_work(work_id)
    if not work:
        return json_error("作品不存在或尚未公开", 404)
    payload = request_json()
    status = clean_text(payload.get("status") or "READING", 12)
    if status not in SHELF_STATUSES:
        return json_error("书架状态无效", 400)
    db = get_db()
    timestamp = now_ms()
    cursor = db.execute(
        "UPDATE bookshelf SET status = ?, updated_at = ? WHERE user_id = ? AND work_id = ?",
        (status, timestamp, g.user["id"], work_id),
    )
    if cursor.rowcount == 0:
        db.execute(
            "INSERT OR IGNORE INTO bookshelf (user_id, work_id, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (g.user["id"], work_id, status, timestamp, timestamp),
        )
    audit("更新书架", "work", str(work_id), f"{work['title']} · {status}", g.user["id"])
    db.commit()
    return json_ok(bootstrap_payload())


@app.post("/api/shelf/<int:work_id>/remove")
@require_auth
def remove_shelf(work_id: int):
    db = get_db()
    db.execute("DELETE FROM bookshelf WHERE user_id = ? AND work_id = ?", (g.user["id"], work_id))
    audit("移出书架", "work", str(work_id), "", g.user["id"])
    db.commit()
    return json_ok(bootstrap_payload())


@app.post("/api/works/<int:work_id>/follow")
@require_auth
def toggle_work_follow(work_id: int):
    work = public_work(work_id)
    if not work:
        return json_error("作品不存在或尚未公开", 404)
    db = get_db()
    existing = db.execute(
        "SELECT 1 FROM work_follows WHERE user_id = ? AND work_id = ?", (g.user["id"], work_id)
    ).fetchone()
    if existing:
        db.execute("DELETE FROM work_follows WHERE user_id = ? AND work_id = ?", (g.user["id"], work_id))
        audit("取消追更", "work", str(work_id), f"取消追更《{work['title']}》", g.user["id"])
    else:
        db.execute(
            "INSERT OR IGNORE INTO work_follows (user_id, work_id, created_at) VALUES (?, ?, ?)",
            (g.user["id"], work_id, now_ms()),
        )
        audit("追更作品", "work", str(work_id), f"追更《{work['title']}》", g.user["id"])
    db.commit()
    return json_ok(bootstrap_payload())


@app.post("/api/chapters/<int:chapter_id>/progress")
@require_auth
def record_reading_progress(chapter_id: int):
    chapter = get_db().execute("SELECT * FROM chapters WHERE id = ?", (chapter_id,)).fetchone()
    if not chapter or chapter["status"] != "PUBLISHED":
        return json_error("章节不存在或尚未公开", 404)
    if not public_work(int(chapter["work_id"])):
        return json_error("作品不存在或尚未公开", 404)
    db = get_db()
    timestamp = now_ms()
    cursor = db.execute(
        "UPDATE reading_progress SET last_chapter_id = ?, last_read_at = ? WHERE user_id = ? AND work_id = ?",
        (chapter_id, timestamp, g.user["id"], chapter["work_id"]),
    )
    if cursor.rowcount == 0:
        db.execute(
            "INSERT OR IGNORE INTO reading_progress (user_id, work_id, last_chapter_id, last_read_at) VALUES (?, ?, ?, ?)",
            (g.user["id"], chapter["work_id"], chapter_id, timestamp),
        )
    db.commit()
    return json_ok(bootstrap_payload())


@app.post("/api/chapters/<int:chapter_id>/comments")
@require_auth
def create_chapter_comment(chapter_id: int):
    chapter = get_db().execute("SELECT * FROM chapters WHERE id = ?", (chapter_id,)).fetchone()
    if not chapter or chapter["status"] != "PUBLISHED":
        return json_error("章节不存在或尚未公开", 404)
    work = public_work(int(chapter["work_id"]))
    if not work:
        return json_error("作品不存在或尚未公开", 404)
    if not bool(row_value(work, "allow_comments", 1)):
        return json_error("作者已关闭评论", 403)
    payload = request_json()
    text = clean_text(payload.get("text"), 500, required=True)
    db = get_db()
    parent = None
    parent_id = parse_numeric_id(payload.get("parentId")) if payload.get("parentId") else None
    if parent_id:
        parent = db.execute(
            "SELECT * FROM chapter_comments WHERE id = ? AND chapter_id = ? AND deleted_at IS NULL",
            (parent_id, chapter_id),
        ).fetchone()
        if not parent:
            return json_error("要回复的章评不存在", 404)
    effective, reason = evaluate_comment_risk(db, g.user, work, text, chapter_id=int(chapter_id))
    cursor = db.execute(
        "INSERT INTO chapter_comments (chapter_id, user_id, parent_id, text, created_at, effective) VALUES (?, ?, ?, ?, ?, ?)",
        (chapter_id, g.user["id"], parent_id, text, now_ms(), int(effective)),
    )
    comment_id = cursor.lastrowid
    if not effective:
        record_risk(db, g.user["id"], "comment_pattern", reason, level="MEDIUM", target_type="chapter_comment", target_id=str(comment_id))
    link = f"#/chapter/ch{chapter_id}"
    if work["author_id"] != g.user["id"]:
        notify(work["author_id"], f"{g.user['display_name']} 评论了《{work['title']}》第 {chapter['chapter_number']} 章", "comment", link)
    if parent and int(parent["user_id"]) != int(g.user["id"]):
        notify(parent["user_id"], f"{g.user['display_name']} 回复了你的章评", "comment", link)
    audit("发表章评", "chapter_comment", str(comment_id), f"评论《{work['title']}》第 {chapter['chapter_number']} 章", g.user["id"])
    db.commit()
    return json_ok(bootstrap_payload())


@app.post("/api/chapter-comments/<int:comment_id>/delete")
@require_auth
def delete_chapter_comment(comment_id: int):
    comment = get_db().execute("SELECT * FROM chapter_comments WHERE id = ?", (comment_id,)).fetchone()
    if not comment:
        return json_error("章评不存在", 404)
    is_owner = int(comment["user_id"]) == int(g.user["id"])
    if not is_owner and not (g.user["role"] == "admin" and admin_level(g.user)):
        return json_error("只能删除自己的章评", 403)
    get_db().execute(
        "UPDATE chapter_comments SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL",
        (now_ms(), comment_id),
    )
    audit("删除章评", "chapter_comment", str(comment_id), "删除章评", g.user["id"])
    get_db().commit()
    return json_ok(bootstrap_payload())


@app.post("/api/chapter-comments/<int:comment_id>/like")
@require_auth
def toggle_chapter_comment_like(comment_id: int):
    comment = get_db().execute(
        "SELECT * FROM chapter_comments WHERE id = ? AND deleted_at IS NULL", (comment_id,)
    ).fetchone()
    if not comment:
        return json_error("章评不存在", 404)
    chapter = get_db().execute("SELECT * FROM chapters WHERE id = ?", (comment["chapter_id"],)).fetchone()
    if not chapter or chapter["status"] != "PUBLISHED" or not public_work(int(chapter["work_id"])):
        return json_error("章评不存在或不可访问", 404)
    db = get_db()
    existing = db.execute(
        "SELECT 1 FROM chapter_comment_likes WHERE comment_id = ? AND user_id = ?",
        (comment_id, g.user["id"]),
    ).fetchone()
    if existing:
        db.execute("DELETE FROM chapter_comment_likes WHERE comment_id = ? AND user_id = ?", (comment_id, g.user["id"]))
    else:
        db.execute(
            "INSERT INTO chapter_comment_likes (comment_id, user_id, created_at) VALUES (?, ?, ?)",
            (comment_id, g.user["id"], now_ms()),
        )
    db.commit()
    return json_ok(bootstrap_payload())


@app.get("/api/works/<int:work_id>/versions")
@require_auth
def list_work_versions(work_id: int):
    work = get_db().execute("SELECT * FROM works WHERE id = ?", (work_id,)).fetchone()
    if not work:
        return json_error("作品不存在", 404)
    if work["author_id"] != g.user["id"] and not (g.user["role"] == "admin" and admin_level(g.user)):
        return json_error("权限不足", 403)
    rows = get_db().execute(
        "SELECT * FROM work_versions WHERE work_id = ? ORDER BY version_number DESC",
        (work_id,),
    ).fetchall()
    versions = []
    for row in rows:
        try:
            tags = json.loads(row["tags_json"] or "[]")
        except (TypeError, ValueError):
            tags = []
        versions.append({
            "id": f"v{row['id']}",
            "version": int(row["version_number"]),
            "title": row["title"],
            "category": row["category"],
            "tags": tags if isinstance(tags, list) else [],
            "excerpt": row["excerpt"],
            "body": json.loads(row["body_json"] or "[]"),
            "changeReason": row["change_reason"],
            "at": iso_time(row["created_at"]),
        })
    return json_ok({"versions": versions})


@app.post("/api/works/<int:work_id>/delete")
@require_auth
def delete_own_work(work_id: int):
    db = get_db()
    work = db.execute("SELECT * FROM works WHERE id = ? AND author_id = ?", (work_id, g.user["id"])).fetchone()
    if not work:
        return json_error("作品不存在或无权操作", 404)
    if work["status"] == "hidden":
        return json_error("这篇作品已经撤下", 409)
    note = "作者撤下已发表作品" if work["status"] == "published" else "作者删除投稿"
    db.execute(
        "UPDATE works SET status = 'hidden', review_note = ?, updated_at = ? WHERE id = ? AND author_id = ?",
        (note, now_ms(), work_id, g.user["id"]),
    )
    audit("撤下作品" if work["status"] == "published" else "删除投稿", "work", str(work_id), f"{note}《{work['title']}》", g.user["id"])
    db.commit()
    return json_ok(bootstrap_payload())


def public_work(work_id: int):
    work = get_work(work_id)
    if not work or work["status"] != "published" or not bool(row_value(work, "is_public", 1)):
        return None
    if (row_value(work, "visibility", "PUBLIC") or "PUBLIC") != "PUBLIC":
        return None
    return work


@app.post("/api/works/<int:work_id>/view")
def record_view(work_id: int):
    if not rate_limit(f"view:{work_id}", 1, 1800):
        return json_ok({"ok": True})
    work = public_work(work_id)
    if not work:
        return json_error("作品不存在", 404)
    get_db().execute("UPDATE works SET views = views + 1 WHERE id = ?", (work_id,))
    get_db().execute("INSERT INTO work_views (work_id, viewed_at) VALUES (?, ?)", (work_id, now_ms()))
    get_db().commit()
    return json_ok({"ok": True})


@app.post("/api/works/<int:work_id>/like")
@require_auth
def toggle_like(work_id: int):
    work = public_work(work_id)
    if not work:
        return json_error("作品不存在", 404)
    db = get_db()
    existing = db.execute("SELECT 1 FROM likes WHERE user_id = ? AND work_id = ?", (g.user["id"], work_id)).fetchone()
    if existing:
        db.execute("DELETE FROM likes WHERE user_id = ? AND work_id = ?", (g.user["id"], work_id))
    else:
        effective, reason = evaluate_like_risk(db, g.user, work)
        cursor = db.execute(
            "INSERT INTO likes (user_id, work_id, created_at, effective) VALUES (?, ?, ?, ?)",
            (g.user["id"], work_id, now_ms(), int(effective)),
        )
        if not effective:
            record_risk(db, g.user["id"], "like_pattern", reason, level="MEDIUM", target_type="like", target_id=f"{g.user['id']}:{work_id}")
    db.commit()
    return json_ok(bootstrap_payload())


@app.post("/api/works/<int:work_id>/favorite")
@require_auth
def toggle_favorite(work_id: int):
    work = public_work(work_id)
    if not work:
        return json_error("作品不存在", 404)
    if not bool(row_value(work, "allow_favorites", 1)):
        return json_error("作者已关闭收藏", 403)
    db = get_db()
    existing = db.execute("SELECT 1 FROM favorites WHERE user_id = ? AND work_id = ?", (g.user["id"], work_id)).fetchone()
    if existing:
        db.execute("DELETE FROM favorites WHERE user_id = ? AND work_id = ?", (g.user["id"], work_id))
    else:
        db.execute("INSERT INTO favorites (user_id, work_id, created_at) VALUES (?, ?, ?)", (g.user["id"], work_id, now_ms()))
    db.commit()
    return json_ok(bootstrap_payload())


@app.post("/api/works/<int:work_id>/comments")
@require_auth
def create_comment(work_id: int):
    work = public_work(work_id)
    if not work:
        return json_error("作品不存在", 404)
    if not bool(row_value(work, "allow_comments", 1)):
        return json_error("作者已关闭评论", 403)
    payload = request_json()
    text = clean_text(payload.get("text"), 500, required=True)
    effective, reason = evaluate_comment_risk(get_db(), g.user, work, text)
    cursor = get_db().execute(
        "INSERT INTO comments (work_id, user_id, text, created_at, effective) VALUES (?, ?, ?, ?, ?)",
        (work_id, g.user["id"], text, now_ms(), int(effective)),
    )
    if not effective:
        record_risk(get_db(), g.user["id"], "comment_pattern", reason, level="MEDIUM", target_type="comment", target_id=str(cursor.lastrowid))
    if work["author_id"] != g.user["id"]:
        notify(work["author_id"], f"{g.user['display_name']} 评论了《{work['title']}》", "comment", f"#/work/w{work_id}")
    audit("发表评论", "comment", str(cursor.lastrowid), f"评论作品《{work['title']}》", g.user["id"])
    get_db().commit()
    return json_ok(bootstrap_payload())


@app.post("/api/authors/<int:author_id>/follow")
@require_auth
def toggle_follow(author_id: int):
    if author_id == g.user["id"]:
        return json_error("不能关注自己", 400)
    author = user_row(author_id)
    if not author:
        return json_error("作者不存在", 404)
    db = get_db()
    existing = db.execute("SELECT 1 FROM follows WHERE follower_id = ? AND author_id = ?", (g.user["id"], author_id)).fetchone()
    if existing:
        db.execute("DELETE FROM follows WHERE follower_id = ? AND author_id = ?", (g.user["id"], author_id))
    else:
        db.execute("INSERT INTO follows (follower_id, author_id, created_at) VALUES (?, ?, ?)", (g.user["id"], author_id, now_ms()))
        notify(author_id, f"{g.user['display_name']} 关注了你", "follow")
    db.commit()
    return json_ok(bootstrap_payload())


@app.post("/api/conversations")
@require_auth
def create_conversation():
    payload = request_json()
    other_id = parse_public_id(payload.get("authorId"))
    if not other_id or other_id == g.user["id"]:
        return json_error("收信人无效", 400)
    if not user_row(other_id):
        return json_error("收信人不存在", 404)
    low, high = sorted((g.user["id"], other_id))
    db = get_db()
    row = db.execute("SELECT * FROM conversations WHERE user_low_id = ? AND user_high_id = ?", (low, high)).fetchone()
    if not row:
        db.execute("INSERT INTO conversations (user_low_id, user_high_id, created_at, updated_at) VALUES (?, ?, ?, ?)", (low, high, now_ms(), now_ms()))
        db.commit()
    return json_ok(bootstrap_payload())


def conversation_for_user(conversation_id: int):
    return get_db().execute(
        "SELECT * FROM conversations WHERE id = ? AND (user_low_id = ? OR user_high_id = ?)",
        (conversation_id, g.user["id"], g.user["id"]),
    ).fetchone()


@app.post("/api/conversations/<int:conversation_id>/messages")
@require_auth
def send_message(conversation_id: int):
    conversation = conversation_for_user(conversation_id)
    if not conversation:
        return json_error("会话不存在", 404)
    other_id = conversation["user_low_id"] if conversation["user_high_id"] == g.user["id"] else conversation["user_high_id"]
    if get_db().execute("SELECT 1 FROM blocks WHERE (blocker_id = ? AND blocked_id = ?) OR (blocker_id = ? AND blocked_id = ?)", (g.user["id"], other_id, other_id, g.user["id"])).fetchone():
        return json_error("当前会话已被拉黑", 403)
    payload = request_json()
    text = clean_text(payload.get("text"), 1000, required=True)
    reply_to = None
    reply_text = str(payload.get("replyTo") or "")
    if reply_text:
        match = re.fullmatch(r"m(\d+)", reply_text)
        if match:
            reply_to = int(match.group(1))
            if not get_db().execute("SELECT 1 FROM messages WHERE id = ? AND conversation_id = ?", (reply_to, conversation_id)).fetchone():
                return json_error("回复消息无效", 400)
    get_db().execute(
        "INSERT INTO messages (conversation_id, sender_id, text, reply_to_id, created_at) VALUES (?, ?, ?, ?, ?)",
        (conversation_id, g.user["id"], text, reply_to, now_ms()),
    )
    get_db().execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now_ms(), conversation_id))
    notify(other_id, f"{g.user['display_name']} 发来一条私信", "message", "#/messages")
    get_db().commit()
    return json_ok(bootstrap_payload())


@app.post("/api/conversations/<int:conversation_id>/read")
@require_auth
def read_conversation(conversation_id: int):
    conversation = conversation_for_user(conversation_id)
    if not conversation:
        return json_error("会话不存在", 404)
    get_db().execute(
        "UPDATE messages SET read_at = ? WHERE conversation_id = ? AND sender_id <> ? AND read_at IS NULL",
        (now_ms(), conversation_id, g.user["id"]),
    )
    get_db().commit()
    return json_ok(bootstrap_payload())


@app.post("/api/conversations/<int:conversation_id>/messages/<int:message_id>/recall")
@require_auth
def recall_message(conversation_id: int, message_id: int):
    conversation = conversation_for_user(conversation_id)
    if not conversation:
        return json_error("会话不存在", 404)
    message = get_db().execute("SELECT * FROM messages WHERE id = ? AND conversation_id = ?", (message_id, conversation_id)).fetchone()
    if not message or message["sender_id"] != g.user["id"]:
        return json_error("只能撤回自己的消息", 403)
    if message["recalled_at"]:
        return json_ok(bootstrap_payload())
    settings = get_db().execute("SELECT recall_minutes FROM message_settings WHERE user_id = ?", (g.user["id"],)).fetchone()
    minutes = int(settings["recall_minutes"]) if settings else 2
    if now_ms() - message["created_at"] > minutes * 60 * 1000:
        return json_error("超过可撤回时间", 400)
    get_db().execute("UPDATE messages SET recalled_at = ? WHERE id = ?", (now_ms(), message_id))
    audit("撤回私信", "message", str(message_id), "用户撤回私信", g.user["id"])
    get_db().commit()
    return json_ok(bootstrap_payload())


@app.post("/api/conversations/<int:conversation_id>/hide")
@require_auth
def hide_conversation(conversation_id: int):
    conversation = conversation_for_user(conversation_id)
    if not conversation:
        return json_error("会话不存在", 404)
    get_db().execute(
        "INSERT INTO conversation_hidden (conversation_id, user_id, hidden) VALUES (?, ?, 1) ON CONFLICT(conversation_id, user_id) DO UPDATE SET hidden = 1",
        (conversation_id, g.user["id"]),
    )
    get_db().commit()
    return json_ok(bootstrap_payload())


@app.post("/api/users/<int:user_id>/block")
@require_auth
def toggle_block(user_id: int):
    if user_id == g.user["id"]:
        return json_error("不能拉黑自己", 400)
    if not user_row(user_id):
        return json_error("用户不存在", 404)
    db = get_db()
    existing = db.execute("SELECT 1 FROM blocks WHERE blocker_id = ? AND blocked_id = ?", (g.user["id"], user_id)).fetchone()
    if existing:
        db.execute("DELETE FROM blocks WHERE blocker_id = ? AND blocked_id = ?", (g.user["id"], user_id))
    else:
        db.execute("INSERT INTO blocks (blocker_id, blocked_id, created_at) VALUES (?, ?, ?)", (g.user["id"], user_id, now_ms()))
    db.commit()
    return json_ok(bootstrap_payload())


@app.post("/api/message-settings")
@require_auth
def save_message_settings():
    payload = request_json()
    allow_strangers = bool(payload.get("allowStrangers", True))
    notifications = bool(payload.get("notifications", True))
    try:
        recall_minutes = int(payload.get("recallMinutes", 2))
    except (TypeError, ValueError):
        return json_error("撤回时间无效", 400)
    if recall_minutes not in {2, 5, 10}:
        return json_error("撤回时间无效", 400)
    ensure_message_settings(g.user["id"])
    get_db().execute(
        "UPDATE message_settings SET allow_strangers = ?, notifications = ?, recall_minutes = ? WHERE user_id = ?",
        (int(allow_strangers), int(notifications), recall_minutes, g.user["id"]),
    )
    get_db().commit()
    return json_ok(bootstrap_payload())


@app.post("/api/reports")
@require_auth
def create_report():
    payload = request_json()
    report_type = clean_text(payload.get("type"), 20, required=True)
    target_id = clean_text(payload.get("targetId"), 80)
    target_label = clean_text(payload.get("target"), 120, required=True)
    reason = clean_text(payload.get("reason"), 80, required=True)
    detail = clean_text(payload.get("detail"), 500)
    message_excerpt = clean_text(payload.get("message"), 500)
    suspected_url = clean_text(payload.get("suspectedOriginalUrl"), 300)
    cursor = get_db().execute(
        "INSERT INTO reports (reporter_id, type, target_id, target_label, reason, detail, message_excerpt, suspected_original_url, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '待处理', ?)",
        (g.user["id"], report_type, target_id, target_label, reason, detail, message_excerpt, suspected_url, now_ms()),
    )
    notify(g.user["id"], "举报已提交，编辑部将结合必要上下文处理", "report")
    audit("提交举报", "report", str(cursor.lastrowid), f"举报 {target_label}: {reason}", g.user["id"])
    get_db().commit()
    return json_ok(bootstrap_payload())


@app.post("/api/notifications/read")
@require_auth
def read_notifications():
    get_db().execute("UPDATE notifications SET read_at = ? WHERE user_id = ? AND read_at IS NULL", (now_ms(), g.user["id"]))
    get_db().commit()
    return json_ok(bootstrap_payload())


@app.get("/avatars/<name>")
def serve_avatar(name: str):
    if not AVATAR_NAME_RE.fullmatch(name):
        abort(404)
    row = get_db().execute(
        "SELECT content_type, data FROM avatar_blobs WHERE name = ?", (name,)
    ).fetchone()
    if not row:
        abort(404)
    return Response(
        bytes(row["data"]),
        mimetype=row["content_type"] or "image/webp",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.post("/api/profile/avatar")
@require_auth
def upload_avatar():
    if not rate_limit(f"avatar:{g.user['id']}", 10, 3600):
        return json_error("头像上传过于频繁", 429)
    upload = request.files.get("avatar")
    if not upload:
        return json_error("请选择头像文件", 400)
    raw = upload.read(MAX_AVATAR_BYTES + 1)
    if not raw:
        return json_error("头像文件为空", 400)
    if len(raw) > MAX_AVATAR_BYTES:
        return json_error("头像文件不能超过 5MB", 413)
    # 用 Pillow 解码真实图片，不信任客户端 Content-Type
    try:
        with Image.open(io.BytesIO(raw)) as probe:
            probe.verify()
        with Image.open(io.BytesIO(raw)) as image_source:
            if image_source.format not in AVATAR_FORMATS:
                return json_error("仅支持 JPG、PNG、WEBP 格式", 415)
            rgba = image_source.mode in {"RGBA", "LA", "P"}
            image = ImageOps.fit(image_source.convert("RGBA" if rgba else "RGB"), (AVATAR_SIZE, AVATAR_SIZE), method=Image.LANCZOS)
    except Exception:
        return json_error("头像文件无法识别", 415)
    buffer = io.BytesIO()
    image.save(buffer, "WEBP", quality=88, method=6)
    stored_name = f"{secrets.token_hex(16)}.webp"
    db = get_db()
    db.execute(
        "INSERT INTO avatar_blobs (name, content_type, data, created_at) VALUES (?, ?, ?, ?)",
        (stored_name, "image/webp", buffer.getvalue(), now_ms()),
    )
    previous = row_value(g.user, "avatar", "") or ""
    db.execute("UPDATE users SET avatar = ? WHERE id = ?", (f"/avatars/{stored_name}", g.user["id"]))
    remove_old_avatar(previous)
    audit("更新头像", "user", str(g.user["id"]), "用户上传新头像", g.user["id"])
    db.commit()
    return json_ok(bootstrap_payload())


def book_share_form_payload() -> dict:
    if request.is_json:
        payload = request_json()
    elif request.form:
        payload = request.form.to_dict()
    else:
        abort(415)
    tags_value = payload.get("tags")
    if isinstance(tags_value, str):
        tags_value = [item.strip() for item in re.split(r"[,，]", tags_value) if item.strip()]
    tags = [clean_text(item, 20) for item in tags_value if clean_text(item, 20)] if isinstance(tags_value, list) else []
    return {
        "bookTitle": clean_text(payload.get("bookTitle"), 120, required=True),
        "bookAuthor": clean_text(payload.get("bookAuthor"), 80),
        "recommendation": clean_text(payload.get("recommendation"), 2000, required=True),
        "tags": list(dict.fromkeys(tags))[:8],
    }


@app.get("/book-share-images/<name>")
def serve_book_share_image(name: str):
    if not AVATAR_NAME_RE.fullmatch(name):
        abort(404)
    row = get_db().execute(
        "SELECT content_type, data FROM avatar_blobs WHERE name = ?", (name,)
    ).fetchone()
    if not row:
        abort(404)
    return Response(
        bytes(row["data"]),
        mimetype=row["content_type"] or "image/webp",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.post("/api/book-shares")
@require_auth
def create_book_share():
    fields = book_share_form_payload()
    image_name = ""
    upload = request.files.get("image")
    if upload and upload.filename:
        try:
            image_name = save_book_share_image(upload)
        except ValueError as exc:
            return json_error(str(exc), 413 if "5MB" in str(exc) else 415)
    timestamp = now_ms()
    cursor = get_db().execute(
        """
        INSERT INTO book_shares (user_id, book_title, book_author, recommendation, tags_json, image_name, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, 'published', ?, ?)
        """,
        (g.user["id"], fields["bookTitle"], fields["bookAuthor"], fields["recommendation"], json.dumps(fields["tags"], ensure_ascii=False), image_name, timestamp, timestamp),
    )
    audit("发布书友分享", "book_share", str(cursor.lastrowid), f"发布书友分享《{fields['bookTitle']}》", g.user["id"])
    get_db().commit()
    return json_ok(bootstrap_payload())


@app.post("/api/book-shares/<int:share_id>")
@require_auth
def update_book_share(share_id: int):
    row = get_db().execute("SELECT * FROM book_shares WHERE id = ? AND user_id = ?", (share_id, g.user["id"])).fetchone()
    if not row or row["status"] == "deleted":
        return json_error("书友分享不存在或无权修改", 404)
    fields = book_share_form_payload()
    image_name = row["image_name"] or ""
    upload = request.files.get("image")
    if upload and upload.filename:
        try:
            image_name = save_book_share_image(upload)
        except ValueError as exc:
            return json_error(str(exc), 413 if "5MB" in str(exc) else 415)
    get_db().execute(
        """
        UPDATE book_shares SET book_title = ?, book_author = ?, recommendation = ?, tags_json = ?,
          image_name = ?, updated_at = ? WHERE id = ? AND user_id = ?
        """,
        (fields["bookTitle"], fields["bookAuthor"], fields["recommendation"], json.dumps(fields["tags"], ensure_ascii=False), image_name, now_ms(), share_id, g.user["id"]),
    )
    audit("修改书友分享", "book_share", str(share_id), f"修改书友分享《{fields['bookTitle']}》", g.user["id"])
    get_db().commit()
    return json_ok(bootstrap_payload())


@app.post("/api/book-shares/<int:share_id>/delete")
@require_auth
def delete_book_share(share_id: int):
    row = get_db().execute("SELECT * FROM book_shares WHERE id = ? AND user_id = ?", (share_id, g.user["id"])).fetchone()
    if not row or row["status"] == "deleted":
        return json_error("书友分享不存在或已删除", 404)
    get_db().execute("UPDATE book_shares SET status = 'deleted', updated_at = ? WHERE id = ? AND user_id = ?", (now_ms(), share_id, g.user["id"]))
    audit("删除书友分享", "book_share", str(share_id), f"删除书友分享《{row['book_title']}》", g.user["id"])
    get_db().commit()
    return json_ok(bootstrap_payload())


@app.post("/api/book-shares/<int:share_id>/praise")
@require_auth
def toggle_book_share_praise(share_id: int):
    row = get_db().execute("SELECT * FROM book_shares WHERE id = ? AND status = 'published'", (share_id,)).fetchone()
    if not row:
        return json_error("书友分享不存在", 404)
    db = get_db()
    existing = db.execute("SELECT 1 FROM book_share_praises WHERE user_id = ? AND share_id = ?", (g.user["id"], share_id)).fetchone()
    if existing:
        db.execute("DELETE FROM book_share_praises WHERE user_id = ? AND share_id = ?", (g.user["id"], share_id))
    else:
        db.execute("INSERT OR IGNORE INTO book_share_praises (user_id, share_id, created_at) VALUES (?, ?, ?)", (g.user["id"], share_id, now_ms()))
    db.commit()
    return json_ok(bootstrap_payload())


@app.post("/api/admin/topics")
@require_admin
def save_topic():
    payload = request_json()
    topic_id = parse_numeric_id(payload.get("topicId"))
    title = clean_text(payload.get("title"), 80, required=True)
    description = clean_text(payload.get("description"), 1000)
    status = clean_text(payload.get("status") or "DRAFT", 20).upper()
    if status not in TOPIC_STATUSES:
        return json_error("话题状态无效", 400)
    start_at = parse_day_ms(payload.get("startAt"))
    end_at = parse_day_ms(payload.get("endAt"), end_of_day=True)
    if start_at and end_at and end_at < start_at:
        return json_error("截止时间不能早于开始时间", 400)
    db = get_db()
    if topic_id:
        existing = db.execute("SELECT * FROM topics WHERE id = ?", (topic_id,)).fetchone()
        if not existing:
            return json_error("话题不存在", 404)
        published_at = existing["published_at"]
        if status == "PUBLISHED" and not published_at:
            published_at = now_ms()
        db.execute(
            "UPDATE topics SET title = ?, description = ?, start_at = ?, end_at = ?, status = ?, published_at = ?, updated_at = ? WHERE id = ?",
            (title, description, start_at, end_at, status, published_at, now_ms(), topic_id),
        )
    else:
        cursor = db.execute(
            "INSERT INTO topics (title, description, start_at, end_at, created_by, published_at, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (title, description, start_at, end_at, g.user["id"], now_ms() if status == "PUBLISHED" else None, status, now_ms(), now_ms()),
        )
        topic_id = cursor.lastrowid
    audit("保存每周话题", "topic", str(topic_id), f"保存话题《{title}》({status})", g.user["id"])
    db.commit()
    return json_ok(bootstrap_payload())


@app.post("/api/admin/topics/<int:topic_id>/status")
@require_admin
def set_topic_status(topic_id: int):
    payload = request_json()
    status = clean_text(payload.get("status"), 20).upper()
    if status not in TOPIC_STATUSES:
        return json_error("话题状态无效", 400)
    db = get_db()
    row = db.execute("SELECT * FROM topics WHERE id = ?", (topic_id,)).fetchone()
    if not row:
        return json_error("话题不存在", 404)
    published_at = row["published_at"]
    if status == "PUBLISHED" and not published_at:
        published_at = now_ms()
    db.execute("UPDATE topics SET status = ?, published_at = ?, updated_at = ? WHERE id = ?", (status, published_at, now_ms(), topic_id))
    audit("更新话题状态", "topic", str(topic_id), f"话题《{row['title']}》状态更新为 {status}", g.user["id"])
    db.commit()
    return json_ok(bootstrap_payload())


@app.post("/api/admin/risk/<int:risk_id>")
@require_admin
def handle_risk(risk_id: int):
    payload = request_json()
    action = clean_text(payload.get("action"), 20, required=True)
    if action not in {"normal", "excluded", "restored", "limited"}:
        return json_error("风控操作无效", 400)
    db = get_db()
    row = db.execute("SELECT * FROM risk_events WHERE id = ?", (risk_id,)).fetchone()
    if not row:
        return json_error("风控记录不存在", 404)
    db.execute(
        "UPDATE risk_events SET status = ?, handled_by = ?, handled_at = ? WHERE id = ?",
        (action, g.user["id"], now_ms(), risk_id),
    )
    effective = 1 if action in {"normal", "restored"} else 0
    target_raw = str(row["target_id"] or "")
    if row["target_type"] == "like" and ":" in target_raw:
        user_part, work_part = target_raw.split(":", 1)
        db.execute(
            "UPDATE likes SET effective = ? WHERE user_id = ? AND work_id = ?",
            (effective, parse_numeric_id(user_part), parse_numeric_id(work_part)),
        )
    elif row["target_type"] == "like" and target_raw.isdigit() and not USE_POSTGRES:
        db.execute("UPDATE likes SET effective = ? WHERE rowid = ?", (effective, int(target_raw)))
    elif row["target_type"] == "comment":
        target_id = parse_numeric_id(target_raw)
        if target_id:
            db.execute("UPDATE comments SET effective = ? WHERE id = ?", (effective, target_id))
    if action == "limited" and row["user_id"]:
        db.execute("UPDATE users SET risk_level = 'HIGH' WHERE id = ?", (row["user_id"],))
    elif action in {"normal"} and row["user_id"]:
        db.execute("UPDATE users SET risk_level = 'LOW' WHERE id = ?", (row["user_id"],))
    audit("处理风控记录", "risk", str(risk_id), f"风控记录处理为 {action}", g.user["id"])
    db.commit()
    return json_ok(bootstrap_payload())


@app.post("/api/admin/announcements")
@require_admin
def create_announcement():
    payload = request_json()
    title = clean_text(payload.get("title"), 80, required=True)
    content = clean_text(payload.get("content"), 1000, required=True)
    cursor = get_db().execute(
        "INSERT INTO announcements (author_id, title, content, status, created_at, updated_at) VALUES (?, ?, ?, 'published', ?, ?)",
        (g.user["id"], title, content, now_ms(), now_ms()),
    )
    audit("发布公告", "announcement", str(cursor.lastrowid), f"发布公告《{title}》", g.user["id"])
    get_db().commit()
    return json_ok(bootstrap_payload())


@app.post("/api/admin/announcements/<int:announcement_id>/toggle")
@require_admin
def toggle_announcement(announcement_id: int):
    row = get_db().execute("SELECT * FROM announcements WHERE id = ?", (announcement_id,)).fetchone()
    if not row:
        return json_error("公告不存在", 404)
    new_status = "archived" if row["status"] in {"published", "pinned"} else "published"
    get_db().execute("UPDATE announcements SET status = ?, updated_at = ? WHERE id = ?", (new_status, now_ms(), announcement_id))
    audit("更新公告", "announcement", str(announcement_id), f"{'发布' if new_status == 'published' else '撤回'}公告《{row['title']}》", g.user["id"])
    get_db().commit()
    return json_ok(bootstrap_payload())


@app.post("/api/admin/announcements/<int:announcement_id>/pin")
@require_admin
def pin_announcement(announcement_id: int):
    row = get_db().execute("SELECT * FROM announcements WHERE id = ?", (announcement_id,)).fetchone()
    if not row:
        return json_error("公告不存在", 404)
    new_status = "published" if row["status"] == "pinned" else "pinned"
    get_db().execute("UPDATE announcements SET status = ?, updated_at = ? WHERE id = ?", (new_status, now_ms(), announcement_id))
    audit("取消置顶公告" if new_status == "published" else "置顶公告", "announcement", str(announcement_id), f"{'取消置顶' if new_status == 'published' else '置顶'}公告《{row['title']}》", g.user["id"])
    get_db().commit()
    return json_ok(bootstrap_payload())


@app.post("/api/admin/announcements/<int:announcement_id>/delete")
@require_admin
def delete_announcement(announcement_id: int):
    row = get_db().execute("SELECT * FROM announcements WHERE id = ?", (announcement_id,)).fetchone()
    if not row:
        return json_error("公告不存在", 404)
    get_db().execute("UPDATE announcements SET status = 'archived', updated_at = ? WHERE id = ?", (now_ms(), announcement_id))
    audit("归档公告", "announcement", str(announcement_id), f"归档公告《{row['title']}》", g.user["id"])
    get_db().commit()
    return json_ok(bootstrap_payload())


@app.post("/api/announcements/<int:announcement_id>/confirm")
@require_auth
def confirm_announcement(announcement_id: int):
    db = get_db()
    row = db.execute(
        "SELECT id, title, status FROM announcements WHERE id = ? AND status IN ('published', 'pinned')",
        (announcement_id,),
    ).fetchone()
    if not row:
        return json_error("公告不存在或已撤回", 404)
    link = f"announcement:{announcement_id}"
    existing = db.execute(
        "SELECT id FROM notifications WHERE user_id = ? AND type = 'announcement_confirm' AND link = ? ORDER BY id DESC LIMIT 1",
        (g.user["id"], link),
    ).fetchone()
    confirmed_at = now_ms()
    if existing:
        db.execute("UPDATE notifications SET read_at = ? WHERE id = ?", (confirmed_at, existing["id"]))
    else:
        db.execute(
            "INSERT INTO notifications (user_id, type, text, link, created_at, read_at) VALUES (?, 'announcement_confirm', ?, ?, ?, ?)",
            (g.user["id"], f"已确认公告《{row['title']}》", link, confirmed_at, confirmed_at),
        )
    audit("确认公告", "announcement", str(announcement_id), f"确认公告《{row['title']}》", g.user["id"])
    db.commit()
    return json_ok(bootstrap_payload())


@app.post("/api/admin/works/<int:work_id>/review")
@require_admin
def review_work(work_id: int):
    payload = request_json()
    action = clean_text(payload.get("action"), 20, required=True)
    note = clean_text(payload.get("note"), 300)
    if action not in {"publish", "reject", "hide"}:
        return json_error("审核操作无效", 400)
    work = get_db().execute("SELECT * FROM works WHERE id = ?", (work_id,)).fetchone()
    if not work:
        return json_error("作品不存在", 404)
    status = {"publish": "published", "reject": "rejected", "hide": "hidden"}[action]
    published_at = now_ms() if action == "publish" else work["published_at"]
    reviewed_at = now_ms()
    get_db().execute(
        "UPDATE works SET status = ?, review_note = ?, published_at = ?, updated_at = ? WHERE id = ?",
        (status, note, published_at, reviewed_at, work_id),
    )
    get_db().execute(
        "UPDATE agent_review_tasks SET status = 'resolved', resolved_at = ?, resolved_by = ? WHERE work_id = ? AND status = 'open'",
        (reviewed_at, g.user["id"], work_id),
    )
    label = {"publish": "通过审核", "reject": "退回修改", "hide": "下架作品"}[action]
    notify(work["author_id"], f"作品《{work['title']}》{label}。" + (f" 审核意见：{note}" if note else ""), "work", f"#/work/w{work_id}")
    audit(label, "work", str(work_id), f"{label}《{work['title']}》", g.user["id"])
    get_db().commit()
    return json_ok(bootstrap_payload())


@app.post("/api/admin/chapters/<int:chapter_id>/review")
@require_admin
def review_chapter(chapter_id: int):
    payload = request_json()
    action = clean_text(payload.get("action"), 20, required=True)
    note = clean_text(payload.get("note"), 300)
    if action not in {"publish", "reject"}:
        return json_error("章节审核操作无效", 400)
    db = get_db()
    chapter = db.execute("SELECT * FROM chapters WHERE id = ?", (chapter_id,)).fetchone()
    if not chapter:
        return json_error("章节不存在", 404)
    if chapter["status"] != "PENDING_REVIEW":
        return json_error("当前章节不在人工复核状态", 409)
    work = db.execute("SELECT * FROM works WHERE id = ?", (chapter["work_id"],)).fetchone()
    if not work:
        return json_error("所属作品不存在", 404)
    reviewed_at = now_ms()
    status = "PUBLISHED" if action == "publish" else "REJECTED"
    published_at = reviewed_at if action == "publish" else None
    db.execute(
        "UPDATE chapters SET status = ?, review_note = ?, published_at = ?, updated_at = ? WHERE id = ?",
        (status, note, published_at, reviewed_at, chapter_id),
    )
    if status == "PUBLISHED":
        db.execute("UPDATE works SET updated_at = ? WHERE id = ?", (reviewed_at, work["id"]))
        notify_work_followers(db, work, chapter)
    label = "已通过审核" if action == "publish" else "已退回修改"
    notify(
        work["author_id"],
        f"连载《{work['title']}》第 {chapter['chapter_number']} 章《{chapter['title']}》{label}。"
        + (f" 审核意见：{note}" if note else ""),
        "chapter",
        f"#/serial/w{work['id']}",
    )
    audit("审核章节", "chapter", str(chapter_id), f"{label}《{chapter['title']}》", g.user["id"])
    db.commit()
    return json_ok(bootstrap_payload())


@app.post("/api/admin/works/<int:work_id>/delete")
@require_admin
def delete_work(work_id: int):
    work = get_db().execute("SELECT * FROM works WHERE id = ?", (work_id,)).fetchone()
    if not work:
        return json_error("作品不存在", 404)
    db = get_db()
    db.execute(
        "UPDATE works SET status = 'hidden', review_note = '管理员下架', updated_at = ? WHERE id = ?",
        (now_ms(), work_id),
    )
    db.execute(
        "UPDATE reports SET status = '已处理', handled_at = ?, handled_by = ? WHERE target_id IN (?, ?) AND status <> '已处理'",
        (now_ms(), g.user["id"], str(work_id), f"w{work_id}"),
    )
    notify(work["author_id"], f"作品《{work['title']}》已被管理员下架。", "work")
    audit("下架作品", "work", str(work_id), f"管理员下架作品《{work['title']}》", g.user["id"])
    db.commit()
    return json_ok(bootstrap_payload())


@app.post("/api/admin/comments/<int:comment_id>/delete")
@require_admin
def delete_comment(comment_id: int):
    comment = get_db().execute("SELECT * FROM comments WHERE id = ?", (comment_id,)).fetchone()
    if not comment:
        return json_error("评论不存在", 404)
    get_db().execute("UPDATE comments SET deleted_at = ? WHERE id = ?", (now_ms(), comment_id))
    audit("删除评论", "comment", str(comment_id), "管理员删除评论", g.user["id"])
    get_db().commit()
    return json_ok(bootstrap_payload())


@app.post("/api/admin/reports/<int:report_id>/status")
@require_admin
def update_report_status(report_id: int):
    payload = request_json()
    status = clean_text(payload.get("status"), 20, required=True)
    if status not in {"待处理", "处理中", "已处理", "已驳回"}:
        return json_error("举报状态无效", 400)
    action = clean_text(payload.get("action"), 20)
    if action and action not in {"驳回", "要求补充材料", "暂时隐藏", "确认侵权并下架"}:
        return json_error("处理动作无效", 400)
    row = get_db().execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()
    if not row:
        return json_error("举报记录不存在", 404)
    get_db().execute(
        "UPDATE reports SET status = ?, handled_action = ?, handled_at = ?, handled_by = ? WHERE id = ?",
        (status, action, now_ms(), g.user["id"], report_id),
    )
    if action in {"暂时隐藏", "确认侵权并下架"} and row["type"] in {"作品", "版权举报"}:
        target_work = parse_numeric_id(row["target_id"])
        if target_work:
            get_db().execute("UPDATE works SET status = 'hidden', updated_at = ? WHERE id = ?", (now_ms(), target_work))
    elif action in {"暂时隐藏", "确认侵权并下架"} and row["type"] == "书友分享":
        target_share = parse_numeric_id(row["target_id"])
        if target_share:
            get_db().execute("UPDATE book_shares SET status = 'hidden', updated_at = ? WHERE id = ?", (now_ms(), target_share))
    audit("处理举报", "report", str(report_id), f"举报状态更新为{status}" + (f"，动作：{action}" if action else ""), g.user["id"])
    get_db().commit()
    return json_ok(bootstrap_payload())


@app.post("/api/admin/activities")
@require_admin
def create_activity():
    payload = request_json()
    title = clean_text(payload.get("title"), 80, required=True)
    description = clean_text(payload.get("description"), 1000)
    starts_at = clean_text(payload.get("startsAt"), 30)
    ends_at = clean_text(payload.get("endsAt"), 30)
    status = clean_text(payload.get("status") or "筹备中", 20)
    rules = clean_text(payload.get("rules"), 1000)
    if status not in {"筹备中", "报名中", "进行中", "已结束"}:
        return json_error("活动状态无效", 400)
    cursor = get_db().execute(
        "INSERT INTO activities (title, description, starts_at, ends_at, status, rules, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (title, description, starts_at, ends_at, status, rules, now_ms()),
    )
    audit("创建活动", "activity", str(cursor.lastrowid), f"创建活动《{title}》", g.user["id"])
    get_db().commit()
    return json_ok(bootstrap_payload())


@app.post("/api/admin/monthly-awards")
@require_admin
def save_monthly_award():
    payload = request_json()
    work_id = parse_numeric_id(payload.get("workId"))
    month = clean_text(payload.get("month"), 7, required=True)
    if not work_id or not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        return json_error("月份或作品无效", 400)
    try:
        rank = int(payload.get("rank", 1))
    except (TypeError, ValueError):
        return json_error("名次无效", 400)
    if rank < 1 or rank > 20:
        return json_error("名次无效", 400)
    reason = clean_text(payload.get("reason"), 300)
    work = get_db().execute(
        "SELECT * FROM works WHERE id = ? AND status = 'published' AND is_public = 1 AND visibility = 'PUBLIC'",
        (work_id,),
    ).fetchone()
    if not work:
        return json_error("只有公开作品可以进入月度优秀", 400)
    existing = get_db().execute(
        "SELECT id FROM monthly_awards WHERE work_id = ? AND month = ? AND status = 'active'",
        (work_id, month),
    ).fetchone()
    if existing:
        get_db().execute(
            "UPDATE monthly_awards SET category = ?, rank = ?, reason = ?, selected_at = ?, selected_by = ? WHERE id = ?",
            (work["category"], rank, reason, now_ms(), g.user["id"], existing["id"]),
        )
        award_id = existing["id"]
    else:
        cursor = get_db().execute(
            """
            INSERT INTO monthly_awards (work_id, author_id, category, month, rank, reason, selected_at, selected_by, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active')
            """,
            (work_id, work["author_id"], work["category"], month, rank, reason, now_ms(), g.user["id"]),
        )
        award_id = cursor.lastrowid
    notify(work["author_id"], f"作品《{work['title']}》入选 {month} 月度优秀。", "award", f"#/work/w{work_id}")
    audit("月度评选", "monthly_award", str(award_id), f"{month} 入选《{work['title']}》", g.user["id"])
    get_db().commit()
    return json_ok(bootstrap_payload())


@app.post("/api/admin/monthly-awards/<int:award_id>/revoke")
@require_admin
def revoke_monthly_award(award_id: int):
    row = get_db().execute("SELECT * FROM monthly_awards WHERE id = ? AND status = 'active'", (award_id,)).fetchone()
    if not row:
        return json_error("获奖记录不存在", 404)
    get_db().execute("UPDATE monthly_awards SET status = 'revoked' WHERE id = ?", (award_id,))
    audit("撤销获奖", "monthly_award", str(award_id), "撤销月度优秀记录", g.user["id"])
    get_db().commit()
    return json_ok(bootstrap_payload())


@app.post("/api/admin/users/<int:user_id>/status")
@require_admin
def update_user_status(user_id: int):
    payload = request_json()
    status = clean_text(payload.get("status"), 20, required=True)
    if status not in {"active", "suspended"}:
        return json_error("用户状态无效", 400)
    target = user_row(user_id)
    if not target:
        return json_error("用户不存在", 404)
    if target["role"] == "admin":
        return json_error("不能修改管理员账号状态", 403)
    if user_id == g.user["id"]:
        return json_error("不能修改自己的账号状态", 400)
    get_db().execute("UPDATE users SET account_status = ? WHERE id = ?", (status, user_id))
    audit("更新用户状态", "user", str(user_id), f"用户状态更新为{status}", g.user["id"])
    get_db().commit()
    return json_ok(bootstrap_payload())


@app.post("/api/admin/admins/appoint")
@require_super_admin
def appoint_admin():
    payload = request_json()
    user_id = parse_public_id(payload.get("userId"))
    target = user_row(user_id) if user_id else None
    if not target or target["role"] != "reader":
        return json_error("只能任命普通用户为高级管理员", 400)
    existing = get_db().execute("SELECT * FROM admin_roles WHERE user_id = ?", (user_id,)).fetchone()
    if existing:
        return json_error("该用户已经拥有管理员身份", 409)
    current_count = get_db().execute("SELECT COUNT(*) AS count FROM admin_roles WHERE level = 'senior'").fetchone()["count"]
    if current_count >= 2:
        return json_error("高级管理员最多 2 名", 409)
    get_db().execute(
        "INSERT INTO admin_roles (user_id, level, appointed_by, appointed_at, updated_at) VALUES (?, 'senior', ?, ?, ?)",
        (user_id, g.user["id"], now_ms(), now_ms()),
    )
    get_db().execute("UPDATE users SET role = 'admin' WHERE id = ?", (user_id,))
    notify(user_id, "你已被任命为高级管理员。", "admin")
    audit("任命高级管理员", "user", str(user_id), f"任命 {target['display_name']} 为高级管理员", g.user["id"])
    get_db().commit()
    return json_ok(bootstrap_payload())


@app.post("/api/admin/admins/revoke")
@require_super_admin
def revoke_admin():
    payload = request_json()
    user_id = parse_public_id(payload.get("userId"))
    target = user_row(user_id) if user_id else None
    if not target or user_id == g.user["id"]:
        return json_error("不能撤销该账号", 400)
    role = get_db().execute("SELECT * FROM admin_roles WHERE user_id = ? AND level = 'senior'", (user_id,)).fetchone()
    if not role:
        return json_error("该用户不是高级管理员", 404)
    get_db().execute("DELETE FROM admin_roles WHERE user_id = ?", (user_id,))
    get_db().execute("UPDATE users SET role = 'reader' WHERE id = ?", (user_id,))
    get_db().execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    notify(user_id, "你的高级管理员权限已被撤销。", "admin")
    audit("撤销高级管理员", "user", str(user_id), f"撤销 {target['display_name']} 的高级管理员权限", g.user["id"])
    get_db().commit()
    return json_ok(bootstrap_payload())


@app.post("/api/admin/admins/transfer")
@require_super_admin
def transfer_admin():
    payload = request_json()
    old_id = parse_public_id(payload.get("oldAdminId"))
    new_id = parse_public_id(payload.get("newAdminId"))
    reason = clean_text(payload.get("reason"), 300, required=True)
    old_user = user_row(old_id) if old_id else None
    new_user = user_row(new_id) if new_id else None
    if not old_user or not new_user or old_id == new_id:
        return json_error("转交账号无效", 400)
    old_role = get_db().execute("SELECT * FROM admin_roles WHERE user_id = ? AND level = 'senior'", (old_id,)).fetchone()
    if not old_role:
        return json_error("原账号不是高级管理员", 400)
    if new_user["role"] != "reader":
        return json_error("新账号必须为普通用户", 400)
    get_db().execute("DELETE FROM admin_roles WHERE user_id = ?", (old_id,))
    get_db().execute(
        "INSERT INTO admin_roles (user_id, level, appointed_by, appointed_at, updated_at) VALUES (?, 'senior', ?, ?, ?)",
        (new_id, g.user["id"], now_ms(), now_ms()),
    )
    get_db().execute("UPDATE users SET role = 'reader' WHERE id = ?", (old_id,))
    get_db().execute("UPDATE users SET role = 'admin' WHERE id = ?", (new_id,))
    get_db().execute("DELETE FROM sessions WHERE user_id = ?", (old_id,))
    get_db().execute(
        "INSERT INTO admin_transfers (old_admin_id, new_admin_id, operator_id, reason, created_at) VALUES (?, ?, ?, ?, ?)",
        (old_id, new_id, g.user["id"], reason, now_ms()),
    )
    notify(old_id, "你的高级管理员权限已转交。", "admin")
    notify(new_id, "你已接任高级管理员。", "admin")
    audit("转交高级管理员", "user", str(new_id), f"{old_user['display_name']} 转交 {new_user['display_name']}：{reason}", g.user["id"])
    get_db().commit()
    return json_ok(bootstrap_payload())



KEEPALIVE_SECONDS = int(os.getenv("KEEPALIVE_SECONDS", "600"))


def _start_keepalive() -> None:
    """Render 免费实例闲置 15 分钟会休眠；定时请求自己的公开地址即可保持唤醒。"""
    base = (os.getenv("RENDER_EXTERNAL_URL") or "").strip().rstrip("/")
    if not base:
        return
    target = f"{base}/api/bootstrap"

    def loop() -> None:
        while True:
            time.sleep(KEEPALIVE_SECONDS)
            try:
                with urllib.request.urlopen(target, timeout=90) as response:
                    response.read(64)
            except Exception:
                pass

    threading.Thread(target=loop, daemon=True, name="fangfei-keepalive").start()


init_db()
_start_keepalive()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "8787")), debug=False)
