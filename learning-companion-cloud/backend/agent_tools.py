from __future__ import annotations

from sqlite3 import Connection
from typing import Any
import uuid

from .db import dumps, loads, utc_now


def log_agent_run(
    conn: Connection,
    student_id: int,
    run_type: str,
    input_data: dict[str, Any],
    output_data: dict[str, Any] | list[Any],
    model: str = "rule",
    status: str = "ok",
    error: str = "",
) -> int:
    trace_id = uuid.uuid4().hex
    cursor = conn.execute(
        """
        INSERT INTO agent_runs (
            student_id, run_type, input_json, output_json, model, status, error,
            confidence, evidence_json, warnings_json, latency_ms, quality_score, trace_id, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, 0.8, '[]', '[]', 0, 0.8, ?, ?)
        """,
        (student_id, run_type, dumps(input_data), dumps(output_data), model, status, error, trace_id, utc_now()),
    )
    run_id = int(cursor.lastrowid)
    conn.execute(
        """
        INSERT INTO agent_trace_steps (
            run_id, trace_id, step_index, step_type, tool_name,
            args_json, observation_json, validation_json, latency_ms, status, created_at
        )
        VALUES (?, ?, 1, 'execute', ?, ?, ?, ?, 0, ?, ?)
        """,
        (
            run_id,
            trace_id,
            run_type,
            dumps(input_data),
            dumps({"output_preview": output_data if isinstance(output_data, dict) else {"items": len(output_data)}}),
            dumps({"status": status, "error": error}),
            status,
            utc_now(),
        ),
    )
    return run_id


def save_learning_plan(conn: Connection, student_id: int, raw_goal: str, parsed: dict[str, Any]) -> int:
    now = utc_now()
    cursor = conn.execute(
        """
        INSERT INTO learning_plans (student_id, raw_goal, parsed_json, status, created_at, updated_at)
        VALUES (?, ?, ?, 'active', ?, ?)
        """,
        (student_id, raw_goal, dumps(parsed), now, now),
    )
    return int(cursor.lastrowid)


def get_task(conn: Connection, task_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM daily_tasks WHERE id = ?", (task_id,)).fetchone()
    return dict(row) if row else None


def get_task_source(conn: Connection, source_id: int | None) -> dict[str, Any] | None:
    if not source_id:
        return None
    row = conn.execute("SELECT * FROM task_sources WHERE id = ?", (source_id,)).fetchone()
    if not row:
        return None
    data = dict(row)
    data["config"] = loads(data.pop("config_json"), {})
    return data


def save_task_guidance(
    conn: Connection,
    daily_task_id: int,
    guidance: list[str],
    completion_standard: str,
    created_by: str,
) -> None:
    conn.execute(
        """
        INSERT INTO task_guidance (daily_task_id, guidance_json, completion_standard, created_by, created_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(daily_task_id) DO UPDATE SET
            guidance_json = excluded.guidance_json,
            completion_standard = excluded.completion_standard,
            created_by = excluded.created_by,
            created_at = excluded.created_at
        """,
        (daily_task_id, dumps(guidance), completion_standard, created_by, utc_now()),
    )


def get_task_guidance(conn: Connection, daily_task_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM task_guidance WHERE daily_task_id = ?", (daily_task_id,)).fetchone()
    if not row:
        return None
    data = dict(row)
    data["guidance"] = loads(data.pop("guidance_json"), [])
    return data


def save_submissions(conn: Connection, daily_task_id: int, answers: dict[str, str]) -> None:
    now = utc_now()
    valid_item_ids = {
        int(row["id"])
        for row in conn.execute(
            "SELECT id FROM quiz_items WHERE daily_task_id = ?",
            (daily_task_id,),
        ).fetchall()
    }
    conn.execute("DELETE FROM submissions WHERE daily_task_id = ?", (daily_task_id,))
    for quiz_item_id, answer in answers.items():
        item_id = int(quiz_item_id) if str(quiz_item_id).isdigit() else None
        if item_id not in valid_item_ids:
            item_id = None
        conn.execute(
            """
            INSERT INTO submissions (daily_task_id, quiz_item_id, answer, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (daily_task_id, item_id, str(answer), now),
        )


def save_mastery_record(
    conn: Connection,
    student_id: int,
    daily_task_id: int,
    subject: str,
    knowledge_point: str,
    mastery_level: str,
    score: float,
    diagnosis: str,
    next_action: str,
) -> None:
    conn.execute(
        """
        INSERT INTO mastery_records (
            student_id, daily_task_id, subject, knowledge_point,
            mastery_level, score, diagnosis, next_action, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            student_id,
            daily_task_id,
            subject,
            knowledge_point,
            mastery_level,
            score,
            diagnosis,
            next_action,
            utc_now(),
        ),
    )


def latest_mastery(conn: Connection, student_id: int, limit: int = 20) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT mr.*, dt.title
        FROM mastery_records mr
        JOIN daily_tasks dt ON dt.id = mr.daily_task_id
        WHERE mr.student_id = ?
        ORDER BY mr.id DESC LIMIT ?
        """,
        (student_id, limit),
    ).fetchall()
    return [dict(row) for row in rows]


def agent_runs(conn: Connection, student_id: int, limit: int = 50) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM agent_runs WHERE student_id = ? ORDER BY id DESC LIMIT ?",
        (student_id, limit),
    ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        data = dict(row)
        data["input"] = loads(data.pop("input_json"), {})
        data["output"] = loads(data.pop("output_json"), {})
        result.append(data)
    return result
