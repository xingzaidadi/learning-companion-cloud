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
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA foreign_keys = ON")
    if DB_PATH.name != ":memory":
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
        except sqlite3.DatabaseError:
            pass
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
                score_json TEXT NOT NULL DEFAULT '{}',
                error_types_json TEXT NOT NULL DEFAULT '{}',
                mastery_json TEXT NOT NULL DEFAULT '{}',
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
                weakest_point TEXT NOT NULL DEFAULT '',
                parent_attention TEXT NOT NULL DEFAULT '',
                ten_minute_action TEXT NOT NULL DEFAULT '',
                passed_points_json TEXT NOT NULL DEFAULT '[]',
                failed_points_json TEXT NOT NULL DEFAULT '[]',
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

            CREATE TABLE IF NOT EXISTS learning_materials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
                source_id INTEGER REFERENCES task_sources(id) ON DELETE SET NULL,
                subject TEXT NOT NULL DEFAULT '',
                material_type TEXT NOT NULL DEFAULT 'notes',
                title TEXT NOT NULL,
                content_text TEXT NOT NULL DEFAULT '',
                file_path TEXT NOT NULL DEFAULT '',
                config_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
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
                review_stage TEXT NOT NULL DEFAULT 'D1',
                attempt_count INTEGER NOT NULL DEFAULT 0,
                last_result TEXT NOT NULL DEFAULT '',
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

            CREATE TABLE IF NOT EXISTS skill_mastery (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
                subject TEXT NOT NULL DEFAULT '',
                skill TEXT NOT NULL DEFAULT '',
                grade TEXT NOT NULL DEFAULT '五年级',
                book TEXT NOT NULL DEFAULT '上册',
                unit TEXT NOT NULL DEFAULT '',
                lesson TEXT NOT NULL DEFAULT '',
                mastery_score REAL NOT NULL DEFAULT 0.5,
                confidence REAL NOT NULL DEFAULT 0.5,
                evidence_json TEXT NOT NULL DEFAULT '[]',
                last_task_id INTEGER REFERENCES daily_tasks(id) ON DELETE SET NULL,
                last_quiz_result_id INTEGER REFERENCES quiz_results(id) ON DELETE SET NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(student_id, subject, skill, unit, lesson)
            );

            CREATE TABLE IF NOT EXISTS memory_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
                memory_type TEXT NOT NULL DEFAULT 'episodic',
                subject TEXT NOT NULL DEFAULT '',
                skill TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL,
                source_type TEXT NOT NULL DEFAULT '',
                source_id INTEGER,
                confidence REAL NOT NULL DEFAULT 0.6,
                status TEXT NOT NULL DEFAULT 'active',
                expires_at TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS material_chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                material_id INTEGER NOT NULL REFERENCES learning_materials(id) ON DELETE CASCADE,
                student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
                subject TEXT NOT NULL DEFAULT '',
                grade TEXT NOT NULL DEFAULT '五年级',
                book TEXT NOT NULL DEFAULT '上册',
                unit TEXT NOT NULL DEFAULT '',
                lesson TEXT NOT NULL DEFAULT '',
                section TEXT NOT NULL DEFAULT '',
                knowledge_type TEXT NOT NULL DEFAULT '',
                chunk_text TEXT NOT NULL,
                keywords_json TEXT NOT NULL DEFAULT '[]',
                source_ref TEXT NOT NULL DEFAULT '',
                exam_weight TEXT NOT NULL DEFAULT 'medium',
                must_master INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS material_embeddings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chunk_id INTEGER NOT NULL REFERENCES material_chunks(id) ON DELETE CASCADE,
                model TEXT NOT NULL DEFAULT 'local-hash-v1',
                dim INTEGER NOT NULL DEFAULT 64,
                vector_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(chunk_id, model)
            );

            CREATE TABLE IF NOT EXISTS tutor_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                daily_task_id INTEGER NOT NULL REFERENCES daily_tasks(id) ON DELETE CASCADE,
                student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
                status TEXT NOT NULL DEFAULT 'opened',
                stuck_note TEXT NOT NULL DEFAULT '',
                subject TEXT NOT NULL DEFAULT '',
                skill TEXT NOT NULL DEFAULT '',
                resolution TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tutor_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL REFERENCES tutor_sessions(id) ON DELETE CASCADE,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                meta_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS quiz_quality_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                daily_task_id INTEGER NOT NULL REFERENCES daily_tasks(id) ON DELETE CASCADE,
                score REAL NOT NULL DEFAULT 0,
                passed INTEGER NOT NULL DEFAULT 0,
                issues_json TEXT NOT NULL DEFAULT '[]',
                checked_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS knowledge_points (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
                subject TEXT NOT NULL DEFAULT '',
                unit TEXT NOT NULL DEFAULT '',
                lesson TEXT NOT NULL DEFAULT '',
                section TEXT NOT NULL DEFAULT '',
                knowledge_point TEXT NOT NULL,
                skill TEXT NOT NULL DEFAULT '',
                source_ref TEXT NOT NULL DEFAULT '',
                difficulty TEXT NOT NULL DEFAULT 'basic',
                exam_weight TEXT NOT NULL DEFAULT 'medium',
                must_master INTEGER NOT NULL DEFAULT 1,
                mastery_score REAL NOT NULL DEFAULT 0.5,
                confidence REAL NOT NULL DEFAULT 0.5,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(student_id, subject, unit, lesson, knowledge_point)
            );

            CREATE TABLE IF NOT EXISTS agent_trace_steps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER REFERENCES agent_runs(id) ON DELETE CASCADE,
                trace_id TEXT NOT NULL DEFAULT '',
                step_index INTEGER NOT NULL DEFAULT 0,
                step_type TEXT NOT NULL DEFAULT '',
                thought TEXT NOT NULL DEFAULT '',
                tool_name TEXT NOT NULL DEFAULT '',
                args_json TEXT NOT NULL DEFAULT '{}',
                decision_json TEXT NOT NULL DEFAULT '{}',
                observation_json TEXT NOT NULL DEFAULT '{}',
                validation_json TEXT NOT NULL DEFAULT '{}',
                latency_ms INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'ok',
                error TEXT NOT NULL DEFAULT '',
                retry_count INTEGER NOT NULL DEFAULT 0,
                score REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            """
        )
        _ensure_columns(
            conn,
            "quiz_items",
            {
                "subject": "TEXT NOT NULL DEFAULT ''",
                "skill": "TEXT NOT NULL DEFAULT ''",
                "difficulty": "TEXT NOT NULL DEFAULT 'basic'",
                "source_ref": "TEXT NOT NULL DEFAULT ''",
                "quality_score": "REAL NOT NULL DEFAULT 0",
                "answer_aliases_json": "TEXT NOT NULL DEFAULT '[]'",
                "grading_rubric_json": "TEXT NOT NULL DEFAULT '{}'",
            },
        )
        _ensure_columns(
            conn,
            "learning_materials",
            {
                "source_url": "TEXT NOT NULL DEFAULT ''",
                "source_type": "TEXT NOT NULL DEFAULT ''",
                "trust_level": "TEXT NOT NULL DEFAULT 'user_provided'",
                "coverage_json": "TEXT NOT NULL DEFAULT '{}'",
            },
        )
        _ensure_columns(
            conn,
            "daily_tasks",
            {
                "sort_order": "INTEGER NOT NULL DEFAULT 0",
                "planned_start": "TEXT NOT NULL DEFAULT ''",
                "planned_end": "TEXT NOT NULL DEFAULT ''",
                "schedule_block": "TEXT NOT NULL DEFAULT ''",
                "schedule_reason": "TEXT NOT NULL DEFAULT ''",
            },
        )
        _ensure_columns(
            conn,
            "agent_runs",
            {
                "confidence": "REAL NOT NULL DEFAULT 0",
                "evidence_json": "TEXT NOT NULL DEFAULT '[]'",
                "warnings_json": "TEXT NOT NULL DEFAULT '[]'",
                "latency_ms": "INTEGER NOT NULL DEFAULT 0",
                "quality_score": "REAL NOT NULL DEFAULT 0",
                "trace_id": "TEXT NOT NULL DEFAULT ''",
            },
        )
        _ensure_columns(
            conn,
            "skill_mastery",
            {
                "conflict_count": "INTEGER NOT NULL DEFAULT 0",
                "decay_factor": "REAL NOT NULL DEFAULT 1",
                "stable_weakness": "INTEGER NOT NULL DEFAULT 0",
            },
        )
        _ensure_columns(
            conn,
            "memory_records",
            {
                "compressed_from_json": "TEXT NOT NULL DEFAULT '[]'",
                "governance_event": "TEXT NOT NULL DEFAULT ''",
            },
        )
        _ensure_columns(
            conn,
            "agent_trace_steps",
            {
                "thought": "TEXT NOT NULL DEFAULT ''",
                "decision_json": "TEXT NOT NULL DEFAULT '{}'",
                "error": "TEXT NOT NULL DEFAULT ''",
                "retry_count": "INTEGER NOT NULL DEFAULT 0",
                "score": "REAL NOT NULL DEFAULT 0",
            },
        )
        _ensure_columns(
            conn,
            "quiz_results",
            {
                "score_json": "TEXT NOT NULL DEFAULT '{}'",
                "error_types_json": "TEXT NOT NULL DEFAULT '{}'",
                "mastery_json": "TEXT NOT NULL DEFAULT '{}'",
            },
        )
        _ensure_columns(
            conn,
            "review_items",
            {
                "review_stage": "TEXT NOT NULL DEFAULT 'D1'",
                "attempt_count": "INTEGER NOT NULL DEFAULT 0",
                "last_result": "TEXT NOT NULL DEFAULT ''",
            },
        )
        _ensure_columns(
            conn,
            "daily_reports",
            {
                "weakest_point": "TEXT NOT NULL DEFAULT ''",
                "parent_attention": "TEXT NOT NULL DEFAULT ''",
                "ten_minute_action": "TEXT NOT NULL DEFAULT ''",
                "passed_points_json": "TEXT NOT NULL DEFAULT '[]'",
                "failed_points_json": "TEXT NOT NULL DEFAULT '[]'",
            },
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
        _repair_dirty_question_mark_records(conn)


def _looks_like_dirty_question_text(value: str | None) -> bool:
    text = (value or "").strip()
    if len(text) < 3:
        return False
    compact = "".join(ch for ch in text if not ch.isspace())
    if len(compact) < 3:
        return False
    question_count = compact.count("?") + compact.count("？")
    return question_count >= 3 and question_count / max(len(compact), 1) >= 0.55


def _repair_dirty_question_mark_records(conn: sqlite3.Connection) -> None:
    now = utc_now()
    source_rows = conn.execute("SELECT id, title, subject, config_json FROM task_sources").fetchall()
    for row in source_rows:
        if any(_looks_like_dirty_question_text(row[field]) for field in ("title", "subject", "config_json")):
            conn.execute(
                """
                UPDATE task_sources
                SET title = ?, subject = ?, config_json = ?, status = 'archived', updated_at = ?
                WHERE id = ?
                """,
                ("计划标题待重新生成", "待确认", dumps({"warning": "原计划内容编码损坏，请在管理端重新粘贴中文原文。"}), now, row["id"]),
            )

    task_rows = conn.execute("SELECT id, title, description FROM daily_tasks").fetchall()
    for row in task_rows:
        if _looks_like_dirty_question_text(row["title"]) or _looks_like_dirty_question_text(row["description"]):
            conn.execute(
                """
                UPDATE daily_tasks
                SET title = ?, description = ?, updated_at = ?
                WHERE id = ?
                """,
                ("任务标题待重新生成", "原任务内容编码损坏，请回到管理端重新生成今日任务。", now, row["id"]),
            )


def _ensure_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    for name, definition in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def dict_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def dict_rows(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]
