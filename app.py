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
PUBLIC_ROOTS = {"assets", "css", "images", "js", "vendor"}
PUBLIC_FILES = {"app.js", "styles.css", "pet.js", "favicon.ico"}

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
  created_at INTEGER NOT NULL
);

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
  views INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  published_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_works_author ON works(author_id);
CREATE INDEX IF NOT EXISTS idx_works_status_created ON works(status, created_at DESC);

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


def init_db() -> None:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DATABASE_PATH, timeout=15)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()
    ensure_admin()


def ensure_admin() -> None:
    conn = sqlite3.connect(DATABASE_PATH, timeout=15)
    try:
        existing = conn.execute("SELECT id FROM users WHERE role = 'admin' ORDER BY id LIMIT 1").fetchone()
        if existing:
            return
        password = os.getenv("ADMIN_PASSWORD", "")
        if not password:
            if IS_PRODUCTION:
                raise RuntimeError("ADMIN_PASSWORD is required to initialize the first production administrator")
            return
        username = (os.getenv("ADMIN_USERNAME") or "admin").strip()
        display_name = (os.getenv("ADMIN_DISPLAY_NAME") or "管理员").strip()
        if not USERNAME_RE.fullmatch(username):
            raise RuntimeError("ADMIN_USERNAME must be 3-32 letters, numbers, or underscores")
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


def public_user(row) -> dict:
    return {
        "id": f"u{row['id']}",
        "name": row["display_name"],
        "role": row["role"],
        "bio": row["bio"] or "",
        "awards": row["awards"],
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
    if not user:
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
        if user["role"] != "admin":
            return json_error("权限不足", 403)
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
        sql += " AND w.status = 'published'"
    return get_db().execute(sql, params).fetchone()


def build_state(user) -> dict:
    db = get_db()
    user_id = user["id"] if user else None
    is_admin = bool(user and user["role"] == "admin")

    works_sql = """
      SELECT w.*, u.display_name AS author_name,
        (SELECT COUNT(*) FROM likes l WHERE l.work_id = w.id) AS likes_count,
        (SELECT COUNT(*) FROM favorites f WHERE f.work_id = w.id) AS favorites_count
      FROM works w JOIN users u ON u.id = w.author_id
    """
    params: list[object] = []
    if not is_admin:
        works_sql += " WHERE w.status = 'published'"
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
                "excerpt": row["excerpt"],
                "body": json.loads(row["body_json"] or "[]"),
                "comments": comments,
                "createdAt": row["published_at"] or row["created_at"],
                "updatedAt": row["updated_at"],
                "createdBy": f"u{row['author_id']}",
                "status": row["status"],
                "reviewNote": row["review_note"],
            }
        )

    authors_sql = """
      SELECT u.*,
        (SELECT COUNT(*) FROM works w WHERE w.author_id = u.id AND w.status = 'published') AS work_count
      FROM users u
    """
    if not is_admin:
        authors_sql += " WHERE EXISTS (SELECT 1 FROM works w WHERE w.author_id = u.id AND w.status = 'published')"
    authors_sql += " ORDER BY work_count DESC, u.created_at ASC"
    authors = [public_user(row) for row in db.execute(authors_sql).fetchall()]

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

    monthly_picks = [
        f"w{row['work_id']}"
        for row in db.execute(
            "SELECT work_id FROM monthly_picks ORDER BY month DESC, rank ASC, work_id ASC"
        ).fetchall()
    ]

    followed = []
    blocked = []
    liked = []
    favorited = []
    notifications = []
    conversations = []
    message_settings = {"allowStrangers": True, "recallMinutes": 2, "notifications": True}
    reports = []
    audit_logs = []

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
                "text": row["detail"] or row["action"],
                "at": iso_time(row["created_at"]),
            }
            for row in db.execute("SELECT * FROM audit_logs ORDER BY created_at DESC LIMIT 100").fetchall()
        ]

    return {
        "schemaVersion": 4,
        "currentUser": public_user(user) if user else {"id": "", "name": "访客", "role": "guest"},
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
        "conversations": conversations,
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
    if not user or not check_password_hash(user["password_hash"], password):
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


@app.post("/api/works")
@require_auth
def create_work():
    if not rate_limit("create_work", 20, 3600):
        return json_error("投稿过于频繁", 429)
    payload = request_json()
    title = clean_text(payload.get("title"), 80, required=True)
    category = clean_text(payload.get("category"), 20, required=True)
    tags_value = payload.get("tags") if isinstance(payload.get("tags"), list) else []
    tags = [clean_text(tag, 20) for tag in tags_value if clean_text(tag, 20)][:10]
    body_value = payload.get("body") if isinstance(payload.get("body"), list) else []
    body = [clean_text(paragraph, MAX_STRING_CHARS, required=True) for paragraph in body_value if clean_text(paragraph, MAX_STRING_CHARS)]
    if not body:
        return json_error("正文不能为空", 400)
    excerpt = body[0][:90]
    timestamp = now_ms()
    cursor = get_db().execute(
        """
        INSERT INTO works (author_id, title, category, tags_json, excerpt, body_json, status, created_at, updated_at, published_at)
        VALUES (?, ?, ?, ?, ?, ?, 'published', ?, ?, ?)
        """,
        (g.user["id"], title, category, json.dumps(tags, ensure_ascii=False), excerpt, json.dumps(body, ensure_ascii=False), timestamp, timestamp, timestamp),
    )
    audit("创建作品", "work", str(cursor.lastrowid), f"发布作品《{title}》", g.user["id"])
    notify(g.user["id"], f"作品《{title}》已进入公开作品区。", "work", f"#/work/w{cursor.lastrowid}")
    get_db().commit()
    return json_ok(bootstrap_payload())


@app.post("/api/works/<int:work_id>/like")
@require_auth
def toggle_like(work_id: int):
    work = get_work(work_id)
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
    work = get_work(work_id)
    if not work:
        return json_error("作品不存在", 404)
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
    work = get_work(work_id)
    if not work:
        return json_error("作品不存在", 404)
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


init_db()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "8787")), debug=False)
