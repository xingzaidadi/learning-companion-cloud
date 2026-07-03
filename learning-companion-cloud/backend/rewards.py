from __future__ import annotations

from datetime import date
from sqlite3 import Connection

from .db import utc_now


def add_reward(conn: Connection, student_id: int, points: int, badge: str, reason: str, target_date: str | None = None) -> None:
    conn.execute(
        """
        INSERT INTO student_rewards (student_id, date, points, badge, reason, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (student_id, target_date or date.today().isoformat(), points, badge, reason, utc_now()),
    )


def today_rewards(conn: Connection, student_id: int, target_date: str | None = None) -> dict[str, object]:
    rows = conn.execute(
        """
        SELECT * FROM student_rewards
        WHERE student_id = ? AND date = ?
        ORDER BY id DESC
        """,
        (student_id, target_date or date.today().isoformat()),
    ).fetchall()
    items = [dict(row) for row in rows]
    return {
        "points": sum(item["points"] for item in items),
        "badges": [item["badge"] for item in items if item["badge"]],
        "items": items,
    }
