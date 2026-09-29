from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path

from flask import Flask, abort, g, jsonify, request, send_from_directory
from werkzeug.security import check_password_hash, generate_password_hash


BASE_DIR = Path(__file__).resolve().parent
IS_PRODUCTION = os.getenv("FLASK_ENV", "").lower() == "production" or os.getenv("RENDER", "").lower() == "true"
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", str(BASE_DIR / "data" / "fangfei.sqlite3"))).resolve()
SESSION_COOKIE = "fangfei_session"
CSRF_COOKIE = "fangfei_csrf"
SESSION_DAYS = 14
MAX_BODY_BYTES = 2 * 1024 * 1024
MAX_JSON_DEPTH = 8
MAX_LIST_ITEMS = 100
MAX_STRING_CHARS = 10000
USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,32}$")
ADMIN_USERNAME_RE = re.compile(r"^[\w\u4e00-\u9fff]{1,32}$", re.UNICODE)
PUBLIC_ROOTS = {"assets", "css", "images", "js", "vendor"}
PUBLIC_FILES = {"app.js", "styles.css", "pet.js", "favicon.ico"}
WORK_CATEGORIES = {"小说", "诗歌", "散文", "随笔", "剧本", "科幻", "杂文", "其他"}
PROFILE_COVER_THEMES = {"starry", "deepsea", "sky", "flower", "dragon", "qingli", ""}

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
"""


def now_ms() -> int:
    return int(time.time() * 1000)


def iso_time(ms: int | None) -> str:
    if not ms:
        return ""
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M")


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(DATABASE_PATH, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        g.db = conn
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
        },
        "works": {
            "is_public": "INTEGER NOT NULL DEFAULT 1",
            "allow_comments": "INTEGER NOT NULL DEFAULT 1",
            "allow_favorites": "INTEGER NOT NULL DEFAULT 1",
            "original_confirmed": "INTEGER NOT NULL DEFAULT 0",
            "rights_confirmed": "INTEGER NOT NULL DEFAULT 0",
        },
    }
    for table, columns in migrations.items():
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        for name, ddl in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def sync_system_data() -> None:
    conn = sqlite3.connect(DATABASE_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
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
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DATABASE_PATH, timeout=15)
    try:
        conn.executescript(SCHEMA)
        migrate_columns(conn)
        conn.commit()
    finally:
        conn.close()
    ensure_admin()
    sync_system_data()


def ensure_admin() -> None:
    conn = sqlite3.connect(DATABASE_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
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


def validate_json_shape(value, depth: int = 0) -> None:
    if depth > MAX_JSON_DEPTH:
        abort(400)
    if isinstance(value, dict):
        if len(value) > MAX_LIST_ITEMS:
            abort(400)
        for key, child in value.items():
            if len(str(key)) > 80:
                abort(400)
            validate_json_shape(child, depth + 1)
    elif isinstance(value, list):
        if len(value) > MAX_LIST_ITEMS:
            abort(400)
        for child in value:
            validate_json_shape(child, depth + 1)
    elif isinstance(value, str):
        if len(value) > MAX_STRING_CHARS:
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


def notify(user_id: int, text: str, kind: str = "system", link: str = "") -> None:
    get_db().execute(
        "INSERT INTO notifications (user_id, type, text, link, created_at) VALUES (?, ?, ?, ?, ?)",
        (user_id, kind[:40], text[:300], link[:300], now_ms()),
    )


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
            sql += " AND ((w.status = 'published' AND w.is_public = 1) OR w.author_id = ?)"
            params.append(user["id"])
        else:
            sql += " AND w.status = 'published' AND w.is_public = 1"
    return get_db().execute(sql, params).fetchone()


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


def build_rankings(db: sqlite3.Connection, authors: list[dict] | None = None) -> dict:
    periods = {name: _ranking_period_start(name) for name in ("month", "quarter", "year", "all")}
    author_names = {item.get("id"): item.get("name", "") for item in (authors or [])}
    rankings: dict[str, dict] = {}
    for period, start in periods.items():
        work_rows = db.execute(
            """
            SELECT w.id, w.author_id, w.title, w.category, w.excerpt, w.views, w.body_json,
                   w.published_at, w.created_at, u.display_name AS author_name
            FROM works w JOIN users u ON u.id = w.author_id
            WHERE w.status = 'published' AND w.is_public = 1
            ORDER BY COALESCE(w.published_at, w.created_at) DESC
            """
        ).fetchall()
        work_items = []
        author_stats: dict[str, dict] = {}
        for row in work_rows:
            work_id = row["id"]
            if start:
                views = db.execute(
                    "SELECT COUNT(*) AS count FROM work_views WHERE work_id = ? AND viewed_at >= ?",
                    (work_id, start),
                ).fetchone()["count"]
                likes = db.execute(
                    "SELECT COUNT(*) AS count FROM likes WHERE work_id = ? AND created_at >= ?",
                    (work_id, start),
                ).fetchone()["count"]
                favorites = db.execute(
                    "SELECT COUNT(*) AS count FROM favorites WHERE work_id = ? AND created_at >= ?",
                    (work_id, start),
                ).fetchone()["count"]
                comments = db.execute(
                    "SELECT COUNT(*) AS count FROM comments WHERE work_id = ? AND deleted_at IS NULL AND created_at >= ?",
                    (work_id, start),
                ).fetchone()["count"]
            else:
                views = int(row["views"] or 0)
                likes = db.execute("SELECT COUNT(*) AS count FROM likes WHERE work_id = ?", (work_id,)).fetchone()["count"]
                favorites = db.execute("SELECT COUNT(*) AS count FROM favorites WHERE work_id = ?", (work_id,)).fetchone()["count"]
                comments = db.execute(
                    "SELECT COUNT(*) AS count FROM comments WHERE work_id = ? AND deleted_at IS NULL",
                    (work_id,),
                ).fetchone()["count"]
            score = views + likes * 8 + favorites * 10 + comments * 4
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
                stats["works"] += 1
                try:
                    body = json.loads(row["body_json"] or "[]")
                except (TypeError, ValueError):
                    body = []
                stats["words"] += len(re.sub(r"\s+", "", "".join(str(part) for part in body if part)))

        award_sql = "SELECT author_id, COUNT(*) AS count FROM monthly_awards WHERE status = 'active'"
        award_params: list[object] = []
        if start:
            award_sql += " AND selected_at >= ?"
            award_params.append(start)
        award_sql += " GROUP BY author_id"
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


def build_state(user) -> dict:
    db = get_db()
    user_id = user["id"] if user else None
    is_admin = bool(user and user["role"] == "admin")

    works_sql = """
      SELECT w.*, u.display_name AS author_name,
        (SELECT COUNT(*) FROM likes l WHERE l.work_id = w.id) AS likes_count,
        (SELECT COUNT(*) FROM favorites f WHERE f.work_id = w.id) AS favorites_count,
        (SELECT COUNT(*) FROM comments c WHERE c.work_id = w.id AND c.deleted_at IS NULL) AS comments_count
      FROM works w JOIN users u ON u.id = w.author_id
    """
    params: list[object] = []
    if not is_admin:
        if user_id:
            works_sql += " WHERE ((w.status = 'published' AND w.is_public = 1) OR w.author_id = ?)"
            params.append(user_id)
        else:
            works_sql += " WHERE w.status = 'published' AND w.is_public = 1"
    works_sql += " ORDER BY COALESCE(w.published_at, w.created_at) DESC"
    works = []
    for row in db.execute(works_sql, params).fetchall():
        comments = []
        for comment in db.execute(
            """
            SELECT c.*, u.display_name AS author_name
            FROM comments c JOIN users u ON u.id = c.user_id
            WHERE c.work_id = ? AND c.deleted_at IS NULL
            ORDER BY c.created_at ASC
            """,
            (row["id"],),
        ).fetchall():
            comments.append(
                {
                    "id": f"c{comment['id']}",
                    "who": comment["author_name"],
                    "userId": f"u{comment['user_id']}",
                    "text": comment["text"],
                    "at": comment["created_at"],
                }
            )
        works.append(
            {
                "id": f"w{row['id']}",
                "title": row["title"],
                "author": row["author_name"],
                "authorId": f"u{row['author_id']}",
                "category": row["category"],
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
            }
        )

    authors_sql = """
      SELECT u.*,
        (SELECT COUNT(*) FROM works w WHERE w.author_id = u.id AND w.status = 'published') AS work_count,
        (SELECT COUNT(*) FROM follows f WHERE f.author_id = u.id) AS follower_count,
        (SELECT COUNT(*) FROM monthly_awards ma WHERE ma.author_id = u.id AND ma.status = 'active') AS award_count,
        (SELECT COALESCE(SUM(w.views), 0) FROM works w WHERE w.author_id = u.id AND w.status = 'published') AS views_count
      FROM users u
    """
    if not is_admin:
        authors_sql += " WHERE EXISTS (SELECT 1 FROM works w WHERE w.author_id = u.id AND w.status = 'published')"
    authors_sql += " ORDER BY work_count DESC, u.created_at ASC"
    authors = []
    for row in db.execute(authors_sql).fetchall():
        author = public_user(row)
        author.update({
            "workCount": row["work_count"],
            "followerCount": row["follower_count"],
            "awardCount": row["award_count"],
            "views": row["views_count"],
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
        announcement_sql += " WHERE status = 'published'"
    announcement_sql += " ORDER BY created_at DESC"
    announcements = [
        {
            "id": f"ann{row['id']}",
            "title": row["title"],
            "content": row["content"],
            "status": row["status"],
            "at": iso_time(row["created_at"]),
        }
        for row in db.execute(announcement_sql).fetchall()
    ]

    monthly_visibility = "" if is_admin else "AND w.status = 'published' AND w.is_public = 1"
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
    blocked = []
    liked = []
    favorited = []
    notifications = []
    conversations = []
    message_settings = {"allowStrangers": True, "recallMinutes": 2, "notifications": True}
    reports = []
    audit_logs = []
    users = []
    admin_roles = []
    admin_transfers = []

    if user_id:
        followed = [f"u{row['author_id']}" for row in db.execute("SELECT author_id FROM follows WHERE follower_id = ?", (user_id,)).fetchall()]
        blocked = [f"u{row['blocked_id']}" for row in db.execute("SELECT blocked_id FROM blocks WHERE blocker_id = ?", (user_id,)).fetchall()]
        liked = [f"w{row['work_id']}" for row in db.execute("SELECT work_id FROM likes WHERE user_id = ?", (user_id,)).fetchall()]
        favorited = [f"w{row['work_id']}" for row in db.execute("SELECT work_id FROM favorites WHERE user_id = ?", (user_id,)).fetchall()]
        notifications = [
            {
                "id": f"n{row['id']}",
                "text": row["text"],
                "at": iso_time(row["created_at"]),
                "read": bool(row["read_at"]),
                "type": row["type"],
                "link": row["link"],
            }
            for row in db.execute(
                "SELECT * FROM notifications WHERE user_id = ? ORDER BY created_at DESC LIMIT 100",
                (user_id,),
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

    current_user = public_user(user) if user else {"id": "", "name": "访客", "role": "guest"}
    if user and user["role"] == "admin":
        current_user["adminLevel"] = admin_level(user)

    return {
        "schemaVersion": 6,
        "currentUser": current_user,
        "followed": followed,
        "blocked": blocked,
        "likedWorks": liked,
        "favoritedWorks": favorited,
        "notifications": notifications,
        "works": works,
        "authors": authors,
        "activities": activities,
        "announcements": announcements,
        "reports": reports,
        "auditLogs": audit_logs,
        "messageSettings": message_settings,
        "monthlyPicks": monthly_picks,
        "monthlyAwards": monthly_awards,
        "conversations": conversations,
        "users": users,
        "adminRoles": admin_roles,
        "adminTransfers": admin_transfers,
        "rankings": build_rankings(db, authors),
        "rankingWeights": {"views": 1, "likes": 8, "favorites": 10, "comments": 4},
    }


def bootstrap_payload() -> dict:
    user = current_user_row()
    return {
        "csrfToken": get_csrf_value(),
        "state": build_state(user),
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
    if not rate_limit("register", 8, 3600):
        return json_error("注册尝试过于频繁", 429)
    payload = request_json()
    username = clean_text(payload.get("username"), 32, required=True)
    display_name = clean_text(payload.get("displayName"), 40, required=True)
    password = str(payload.get("password") or "")
    if not USERNAME_RE.fullmatch(username):
        return json_error("用户名需为 3-32 位字母、数字或下划线", 400)
    if len(password) < 8 or len(password) > 128:
        return json_error("密码需为 8-128 位", 400)
    db = get_db()
    if db.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
        return json_error("该用户名已被使用", 409)
    cursor = db.execute(
        "INSERT INTO users (username, display_name, password_hash, role, bio, created_at) VALUES (?, ?, ?, 'reader', '', ?)",
        (username, display_name, generate_password_hash(password), now_ms()),
    )
    user_id = cursor.lastrowid
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
    user = get_db().execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
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
    tags_value = payload.get("tags") if isinstance(payload.get("tags"), list) else []
    tags = [clean_text(tag, 20) for tag in tags_value if clean_text(tag, 20)][:10]
    body_value = payload.get("body") if isinstance(payload.get("body"), list) else []
    body = [clean_text(paragraph, MAX_STRING_CHARS) for paragraph in body_value if clean_text(paragraph, MAX_STRING_CHARS)]
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
    excerpt = clean_text(payload.get("excerpt"), 200) or (body[0][:90] if body else "")
    timestamp = now_ms()
    db = get_db()
    if work_id is None:
        if not rate_limit("create_work", 20, 3600):
            return json_error("投稿过于频繁", 429)
        status = "draft" if action == "draft" else "pending"
        cursor = db.execute(
            """
            INSERT INTO works (
              author_id, title, category, tags_json, excerpt, body_json, status, review_note,
              is_public, allow_comments, allow_favorites, original_confirmed, rights_confirmed,
              created_at, updated_at, published_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                g.user["id"], title, category, json.dumps(tags, ensure_ascii=False), excerpt,
                json.dumps(body, ensure_ascii=False), status, int(is_public), int(allow_comments),
                int(allow_favorites), int(original_confirmed), int(rights_confirmed),
                timestamp, timestamp, None,
            ),
        )
        work_id = cursor.lastrowid
    else:
        existing = db.execute("SELECT * FROM works WHERE id = ? AND author_id = ?", (work_id, g.user["id"])).fetchone()
        if not existing:
            return json_error("作品不存在或无权修改", 404)
        if existing["status"] not in {"draft", "rejected"}:
            return json_error("只有草稿或未通过作品可以修改", 409)
        status = "draft" if action == "draft" else "pending"
        db.execute(
            """
            UPDATE works SET title = ?, category = ?, tags_json = ?, excerpt = ?, body_json = ?,
              status = ?, review_note = '', is_public = ?, allow_comments = ?, allow_favorites = ?,
              original_confirmed = ?, rights_confirmed = ?, updated_at = ?, published_at = NULL
            WHERE id = ? AND author_id = ?
            """,
            (
                title, category, json.dumps(tags, ensure_ascii=False), excerpt,
                json.dumps(body, ensure_ascii=False), status, int(is_public), int(allow_comments),
                int(allow_favorites), int(original_confirmed), int(rights_confirmed), timestamp,
                work_id, g.user["id"],
            ),
        )
    action_text = "保存草稿" if action == "draft" else "提交审核"
    audit(action_text, "work", str(work_id), f"{action_text}《{title}》", g.user["id"])
    notify(g.user["id"], f"作品《{title}》{'已保存为草稿' if action == 'draft' else '已提交审核，等待编辑部处理'}。", "work", f"#/work/w{work_id}")
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


def public_work(work_id: int):
    work = get_work(work_id)
    if not work or work["status"] != "published" or not bool(row_value(work, "is_public", 1)):
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
        db.execute("INSERT INTO likes (user_id, work_id, created_at) VALUES (?, ?, ?)", (g.user["id"], work_id, now_ms()))
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
    cursor = get_db().execute(
        "INSERT INTO comments (work_id, user_id, text, created_at) VALUES (?, ?, ?, ?)",
        (work_id, g.user["id"], text, now_ms()),
    )
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
    recall_minutes = int(payload.get("recallMinutes", 2))
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
    cursor = get_db().execute(
        "INSERT INTO reports (reporter_id, type, target_id, target_label, reason, detail, message_excerpt, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, '待处理', ?)",
        (g.user["id"], report_type, target_id, target_label, reason, detail, message_excerpt, now_ms()),
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
    new_status = "archived" if row["status"] == "published" else "published"
    get_db().execute("UPDATE announcements SET status = ?, updated_at = ? WHERE id = ?", (new_status, now_ms(), announcement_id))
    audit("更新公告", "announcement", str(announcement_id), f"{'发布' if new_status == 'published' else '撤回'}公告《{row['title']}》", g.user["id"])
    get_db().commit()
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
    get_db().execute(
        "UPDATE works SET status = ?, review_note = ?, published_at = ?, updated_at = ? WHERE id = ?",
        (status, note, published_at, now_ms(), work_id),
    )
    label = {"publish": "通过审核", "reject": "退回修改", "hide": "下架作品"}[action]
    notify(work["author_id"], f"作品《{work['title']}》{label}。" + (f" 审核意见：{note}" if note else ""), "work", f"#/work/w{work_id}")
    audit(label, "work", str(work_id), f"{label}《{work['title']}》", g.user["id"])
    get_db().commit()
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
    row = get_db().execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()
    if not row:
        return json_error("举报记录不存在", 404)
    get_db().execute("UPDATE reports SET status = ?, handled_at = ?, handled_by = ? WHERE id = ?", (status, now_ms(), g.user["id"], report_id))
    audit("处理举报", "report", str(report_id), f"举报状态更新为{status}", g.user["id"])
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
    work_id = parse_public_id(payload.get("workId"))
    month = clean_text(payload.get("month"), 7, required=True)
    if not work_id or not re.fullmatch(r"\d{4}-\d{2}", month):
        return json_error("月份或作品无效", 400)
    try:
        rank = int(payload.get("rank", 1))
    except (TypeError, ValueError):
        return json_error("名次无效", 400)
    if rank < 1 or rank > 20:
        return json_error("名次无效", 400)
    reason = clean_text(payload.get("reason"), 300)
    work = get_db().execute("SELECT * FROM works WHERE id = ? AND status = 'published' AND is_public = 1", (work_id,)).fetchone()
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


init_db()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "8787")), debug=False)
