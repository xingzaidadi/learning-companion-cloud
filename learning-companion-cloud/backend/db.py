from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator


BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"


def _resolve_db_path() -> Path:
    configured = os.getenv("DATABASE_PATH")
    if not configured:
        return DATA_DIR / "learning.db"
    path = Path(configured)
    if str(path).replace("\\", "/").startswith("/app/") and not Path("/app").exists():
        return DATA_DIR / "learning.db"
    return path


DB_PATH = _resolve_db_path()


def utc_now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def loads(value: str | None, default: Any = None) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS students (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                age INTEGER NOT NULL DEFAULT 11,
                current_grade TEXT NOT NULL DEFAULT '四年级',
                next_grade TEXT NOT NULL DEFAULT '五年级',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS task_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
                category TEXT NOT NULL CHECK(category IN ('summer_homework', 'preview', 'ket')),
                title TEXT NOT NULL,
                subject TEXT NOT NULL DEFAULT '',
                total_units INTEGER NOT NULL DEFAULT 1,
                completed_units INTEGER NOT NULL DEFAULT 0,
                deadline TEXT,
                config_json TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS daily_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
                date TEXT NOT NULL,
                source_id INTEGER REFERENCES task_sources(id) ON DELETE SET NULL,
                priority TEXT NOT NULL CHECK(priority IN ('P0', 'P1', 'P2', 'P3')),
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                estimated_minutes INTEGER NOT NULL DEFAULT 20,
                completion_standard TEXT NOT NULL DEFAULT '',
                check_method TEXT NOT NULL DEFAULT 'quiz',
                status TEXT NOT NULL DEFAULT 'not_started',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS task_progress (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                daily_task_id INTEGER NOT NULL REFERENCES daily_tasks(id) ON DELETE CASCADE,
                event_type TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS quiz_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                daily_task_id INTEGER NOT NULL REFERENCES daily_tasks(id) ON DELETE CASCADE,
                question_type TEXT NOT NULL DEFAULT 'short',
                question TEXT NOT NULL,
                options_json TEXT NOT NULL DEFAULT '[]',
                answer TEXT NOT NULL,
                explanation TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS quiz_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                daily_task_id INTEGER NOT NULL REFERENCES daily_tasks(id) ON DELETE CASCADE,
                total INTEGER NOT NULL,
                correct INTEGER NOT NULL,
                wrong_items_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS daily_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
                date TEXT NOT NULL,
                completed_count INTEGER NOT NULL DEFAULT 0,
                total_count INTEGER NOT NULL DEFAULT 0,
                summary TEXT NOT NULL,
                problems TEXT NOT NULL DEFAULT '',
                tomorrow_first_step TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                UNIQUE(student_id, date)
            );

            CREATE TABLE IF NOT EXISTS notification_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
                event_type TEXT NOT NULL,
                channel TEXT NOT NULL,
                message TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS import_batches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
                raw_text TEXT NOT NULL,
                created_count INTEGER NOT NULL DEFAULT 0,
                skipped_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS review_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
                source_task_id INTEGER REFERENCES daily_tasks(id) ON DELETE SET NULL,
                question TEXT NOT NULL,
                answer TEXT NOT NULL DEFAULT '',
                explanation TEXT NOT NULL DEFAULT '',
                reason TEXT NOT NULL DEFAULT 'wrong_quiz',
                due_date TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS weekly_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
                week_start TEXT NOT NULL,
                week_end TEXT NOT NULL,
                summary TEXT NOT NULL,
                problems TEXT NOT NULL DEFAULT '',
                next_week_focus TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                UNIQUE(student_id, week_start)
            );

            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS student_rewards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
                date TEXT NOT NULL,
                points INTEGER NOT NULL DEFAULT 0,
                badge TEXT NOT NULL DEFAULT '',
                reason TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS agent_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
                run_type TEXT NOT NULL,
                input_json TEXT NOT NULL DEFAULT '{}',
                output_json TEXT NOT NULL DEFAULT '{}',
                model TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'ok',
                error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS learning_plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
                raw_goal TEXT NOT NULL,
                parsed_json TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS task_guidance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                daily_task_id INTEGER NOT NULL REFERENCES daily_tasks(id) ON DELETE CASCADE,
                guidance_json TEXT NOT NULL DEFAULT '[]',
                completion_standard TEXT NOT NULL DEFAULT '',
                created_by TEXT NOT NULL DEFAULT 'rule',
                created_at TEXT NOT NULL,
                UNIQUE(daily_task_id)
            );

            CREATE TABLE IF NOT EXISTS submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                daily_task_id INTEGER NOT NULL REFERENCES daily_tasks(id) ON DELETE CASCADE,
                quiz_item_id INTEGER REFERENCES quiz_items(id) ON DELETE SET NULL,
                answer TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS mastery_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
                daily_task_id INTEGER NOT NULL REFERENCES daily_tasks(id) ON DELETE CASCADE,
                subject TEXT NOT NULL DEFAULT '',
                knowledge_point TEXT NOT NULL DEFAULT '',
                mastery_level TEXT NOT NULL DEFAULT 'B',
                score REAL NOT NULL DEFAULT 0,
                diagnosis TEXT NOT NULL DEFAULT '',
                next_action TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            """
        )

        row = conn.execute("SELECT id FROM students LIMIT 1").fetchone()
        if row is None:
            now = utc_now()
            conn.execute(
                """
                INSERT INTO students (name, age, current_grade, next_grade, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                ("孩子", 11, "四年级", "五年级", now),
            )


def dict_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def dict_rows(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]
