from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from pathlib import Path


TABLE_ORDER = [
    "users", "admin_roles", "admin_transfers", "sessions", "works", "work_views",
    "likes", "favorites", "follows", "blocks", "comments", "activities",
    "announcements", "monthly_picks", "monthly_awards", "conversations",
    "conversation_hidden", "messages", "message_settings", "notifications",
    "reports", "audit_logs", "topics", "risk_events", "plagiarism_checks",
    "agent_runs", "agent_moderation_results", "agent_review_tasks",
]


def quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def table_columns(conn, table: str) -> list[str]:
    if isinstance(conn, sqlite3.Connection):
        return [row[1] for row in conn.execute(f"PRAGMA table_info({quote(table)})").fetchall()]
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = ? ORDER BY ordinal_position",
        (table,),
    ).fetchall()
    return [row["column_name"] for row in rows]


def table_count(conn, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) AS count FROM {quote(table)}").fetchone()["count"])


def source_table_names(conn: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    }


def backup_sqlite(source: Path) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = source.with_name(f"{source.stem}.backup-{stamp}{source.suffix}")
    source_conn = sqlite3.connect(str(source))
    backup_conn = sqlite3.connect(str(backup))
    try:
        source_conn.backup(backup_conn)
    finally:
        backup_conn.close()
        source_conn.close()
    return backup


def main() -> int:
    parser = argparse.ArgumentParser(description="安全迁移 SQLite 到 PostgreSQL；不会 DROP、TRUNCATE 或覆盖现有数据。")
    parser.add_argument("--source", default="data/fangfei.sqlite3", help="SQLite 源数据库路径")
    parser.add_argument("--target", default=os.getenv("DATABASE_URL", ""), help="PostgreSQL DATABASE_URL")
    parser.add_argument("--dry-run", action="store_true", help="只检查并生成备份，不写入目标库")
    args = parser.parse_args()

    source = Path(args.source).resolve()
    if not source.exists():
        print(f"源数据库不存在：{source}")
        return 2
    if not args.dry_run and not args.target.startswith(("postgres://", "postgresql://")):
        print("目标必须提供 PostgreSQL DATABASE_URL。")
        return 2

    backup = backup_sqlite(source)
    print(f"已生成 SQLite 备份：{backup}")

    source_conn = sqlite3.connect(str(source))
    source_conn.row_factory = sqlite3.Row
    if args.dry_run:
        try:
            source_tables = source_table_names(source_conn)
            planned = [table for table in TABLE_ORDER if table in source_tables]
            extra = sorted(source_tables - set(planned) - {"sqlite_sequence"})
            print(f"dry-run：源库 {len(source_tables)} 张表，计划迁移 {len(planned)} 张。")
            for table in planned + extra:
                print(f"  {table}: {table_count(source_conn, table)} 行")
            print("dry-run 完成：未连接目标库，未写入任何数据。")
            return 0
        finally:
            source_conn.close()

    os.environ["DATABASE_URL"] = args.target
    os.environ["FLASK_ENV"] = "development"
    os.environ.pop("RENDER", None)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import app as app_module

    target_conn = app_module._connect_db()
    try:
        source_tables = source_table_names(source_conn)
        target_tables = {
            row["table_name"]
            for row in target_conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
            ).fetchall()
        }
        ordered = [table for table in TABLE_ORDER if table in source_tables and table in target_tables]
        ordered += sorted(source_tables - set(ordered) - {"sqlite_sequence"} & target_tables)
        for table in ordered:
            source_cols = table_columns(source_conn, table)
            target_cols = table_columns(target_conn, table)
            cols = [name for name in source_cols if name in target_cols]
            if not cols or args.dry_run:
                continue
            column_sql = ", ".join(quote(name) for name in cols)
            placeholder_sql = ", ".join(["%s"] * len(cols))
            insert_sql = f"INSERT INTO {quote(table)} ({column_sql}) VALUES ({placeholder_sql}) ON CONFLICT DO NOTHING"
            rows = source_conn.execute(f"SELECT {column_sql} FROM {quote(table)}").fetchall()
            for row in rows:
                target_conn.execute(insert_sql, tuple(row[name] for name in cols))
            target_conn.commit()
            print(f"已迁移 {table}: {len(rows)} 行")

        failures = []
        for table in ordered:
            if args.dry_run:
                continue
            src_count = table_count(source_conn, table)
            dst_count = table_count(target_conn, table)
            if dst_count < src_count:
                failures.append((table, src_count, dst_count))
            else:
                print(f"数量校验 {table}: {src_count} -> {dst_count}")
            if "id" in table_columns(target_conn, table):
                target_conn.execute(
                    "SELECT setval(pg_get_serial_sequence(%s, 'id'), COALESCE(MAX(id), 1), true) FROM " + quote(table),
                    (table,),
                )
        target_conn.commit()
        if failures:
            print("迁移未完成，目标库数量少于源库：")
            for table, src_count, dst_count in failures:
                print(f"  {table}: {src_count} -> {dst_count}")
            return 3
        relation_checks = [
            ("admin_roles", "user_id", "users", "id"),
            ("works", "author_id", "users", "id"),
            ("comments", "work_id", "works", "id"),
            ("comments", "user_id", "users", "id"),
            ("likes", "work_id", "works", "id"),
            ("likes", "user_id", "users", "id"),
            ("favorites", "work_id", "works", "id"),
            ("favorites", "user_id", "users", "id"),
            ("messages", "conversation_id", "conversations", "id"),
            ("notifications", "user_id", "users", "id"),
            ("monthly_awards", "work_id", "works", "id"),
            ("agent_review_tasks", "work_id", "works", "id"),
        ]
        orphan_failures = []
        for child, child_col, parent, parent_col in relation_checks:
            sql = (
                f"SELECT COUNT(*) AS count FROM {quote(child)} c "
                f"LEFT JOIN {quote(parent)} p ON p.{quote(parent_col)} = c.{quote(child_col)} "
                f"WHERE c.{quote(child_col)} IS NOT NULL AND p.{quote(parent_col)} IS NULL"
            )
            count = int(target_conn.execute(sql).fetchone()["count"])
            if count:
                orphan_failures.append((child, child_col, count))
        if orphan_failures:
            print("关系校验失败，目标库存在孤立记录：")
            for child, child_col, count in orphan_failures:
                print(f"  {child}.{child_col}: {count}")
            return 4
        print("关系校验通过。迁移完成，源数据库和备份均未删除。")
        return 0
    finally:
        source_conn.close()
        target_conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
