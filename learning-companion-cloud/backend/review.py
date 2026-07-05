from __future__ import annotations

from datetime import date, timedelta
from sqlite3 import Connection
from typing import Any

from .db import utc_now
from .question_engine import build_variant_questions


def create_review_item(
    conn: Connection,
    student_id: int,
    source_task_id: int | None,
    question: str,
    answer: str = "",
    explanation: str = "",
    reason: str = "wrong_quiz",
    days_later: int = 1,
    review_stage: str | None = None,
) -> int:
    now = utc_now()
    due_date = (date.today() + timedelta(days=days_later)).isoformat()
    stage = review_stage or f"D{days_later}"
    cursor = conn.execute(
        """
        INSERT INTO review_items (
            student_id, source_task_id, question, answer, explanation,
            reason, due_date, status, review_stage, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
        """,
        (student_id, source_task_id, question, answer, explanation, reason, due_date, stage, now, now),
    )
    return int(cursor.lastrowid)


def due_review_items(conn: Connection, student_id: int, target_date: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT * FROM review_items
        WHERE student_id = ? AND status = 'pending' AND due_date <= ?
        ORDER BY due_date, id
        LIMIT 3
        """,
        (student_id, target_date),
    ).fetchall()
    return [dict(row) for row in rows]


def create_review_tasks(conn: Connection, student_id: int, target_date: str) -> list[dict[str, Any]]:
    items = due_review_items(conn, student_id, target_date)
    created: list[dict[str, Any]] = []
    now = utc_now()
    for item in items:
        cursor = conn.execute(
            """
            INSERT INTO daily_tasks (
                student_id, date, source_id, priority, title, description,
                estimated_minutes, completion_standard, check_method,
                status, created_at, updated_at
            )
            VALUES (?, ?, NULL, 'P0', ?, ?, 15, ?, 'review_quiz', 'not_started', ?, ?)
            """,
            (
                student_id,
                target_date,
                f"{item.get('review_stage', 'D1')} 补漏：{item['question'][:24]}",
                f"复习前面留下的问题：{item['question']}\n错因/来源：{item.get('reason', 'wrong_quiz')}",
                "能说出正确答案、错因，并完成一道同类变式。",
                now,
                now,
            ),
        )
        conn.execute(
            "UPDATE review_items SET status = 'scheduled', attempt_count = attempt_count + 1, updated_at = ? WHERE id = ?",
            (now, item["id"]),
        )
        conn.execute(
            """
            INSERT INTO task_progress (daily_task_id, event_type, note, created_at)
            VALUES (?, 'review_item', ?, ?)
            """,
            (cursor.lastrowid, str(item["id"]), now),
        )
        created.append(
            {
                "id": cursor.lastrowid,
                "student_id": student_id,
                "date": target_date,
                "source_id": None,
                "priority": "P0",
                "title": f"{item.get('review_stage', 'D1')} 补漏：{item['question'][:24]}",
                "description": f"复习前面留下的问题：{item['question']}\n错因/来源：{item.get('reason', 'wrong_quiz')}",
                "estimated_minutes": 15,
                "completion_standard": "能说出正确答案、错因，并完成一道同类变式。",
                "check_method": "review_quiz",
                "status": "not_started",
                "created_at": now,
                "updated_at": now,
            }
        )
    return created


def review_book(conn: Connection, student_id: int) -> dict[str, Any]:
    rows = [
        dict(row)
        for row in conn.execute(
            """
            SELECT * FROM review_items
            WHERE student_id = ?
            ORDER BY due_date, id DESC
            LIMIT 200
            """,
            (student_id,),
        ).fetchall()
    ]
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        key = row["reason"]
        row["variants"] = build_variant_questions(row["question"], row["answer"])
        grouped.setdefault(key, []).append(row)
    return {
        "total": len(rows),
        "pending": sum(1 for row in rows if row["status"] == "pending"),
        "scheduled": sum(1 for row in rows if row["status"] == "scheduled"),
        "done": sum(1 for row in rows if row["status"] == "done"),
        "items": rows,
        "groups": grouped,
    }
