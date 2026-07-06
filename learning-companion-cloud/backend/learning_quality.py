from __future__ import annotations

from datetime import date, timedelta
from sqlite3 import Connection
from typing import Any

from .db import loads, utc_now
from .review import create_review_item


def score_learning_day(conn: Connection, student_id: int = 1, target_date: str | None = None) -> dict[str, Any]:
    today = target_date or date.today().isoformat()
    tasks = [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM daily_tasks WHERE student_id = ? AND date = ? ORDER BY sort_order, id",
            (student_id, today),
        ).fetchall()
    ]
    quiz_rows = [
        dict(row)
        for row in conn.execute(
            """
            SELECT qr.*, dt.title
            FROM quiz_results qr
            JOIN daily_tasks dt ON dt.id = qr.daily_task_id
            WHERE dt.student_id = ? AND dt.date = ?
            ORDER BY qr.id DESC
            """,
            (student_id, today),
        ).fetchall()
    ]
    stuck_count = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM task_progress tp
        JOIN daily_tasks dt ON dt.id = tp.daily_task_id
        WHERE dt.student_id = ? AND dt.date = ? AND tp.event_type = 'stuck'
        """,
        (student_id, today),
    ).fetchone()["count"]
    total = len(tasks)
    completed = sum(1 for task in tasks if task["status"] in {"completed", "done"})
    completion_score = completed / total if total else 0.0
    quiz_scores: list[float] = []
    failed_points: list[str] = []
    passed_points: list[str] = []
    for row in quiz_rows:
        total_items = int(row.get("total") or 0)
        correct = int(row.get("correct") or 0)
        score = correct / total_items if total_items else 0.0
        quiz_scores.append(score)
        title = str(row.get("title") or "")
        if row.get("status") == "completed":
            passed_points.append(title)
        else:
            failed_points.append(title)
    understanding_score = sum(quiz_scores) / len(quiz_scores) if quiz_scores else (0.7 if completed else 0.0)
    practice_score = min(1.0, len(quiz_rows) / max(total, 1)) if total else 0.0
    remediation_score = 1.0 if not failed_points else 0.65
    focus_penalty = min(0.2, float(stuck_count) * 0.05)
    overall = max(
        0.0,
        min(
            1.0,
            completion_score * 0.3
            + understanding_score * 0.35
            + practice_score * 0.2
            + remediation_score * 0.15
            - focus_penalty,
        ),
    )
    score_100 = round(overall * 100)
    if score_100 >= 90:
        level = "优秀"
    elif score_100 >= 80:
        level = "达标"
    elif score_100 >= 60:
        level = "需补漏"
    else:
        level = "需家长介入"
    return {
        "date": today,
        "score": score_100,
        "level": level,
        "dimensions": {
            "completion": round(completion_score * 100),
            "understanding": round(understanding_score * 100),
            "practice": round(practice_score * 100),
            "remediation": round(remediation_score * 100),
            "focus_penalty": round(focus_penalty * 100),
        },
        "completed_tasks": completed,
        "total_tasks": total,
        "quiz_count": len(quiz_rows),
        "stuck_count": int(stuck_count),
        "passed_points": passed_points[:8],
        "failed_points": failed_points[:8],
        "recommendation": _recommendation(score_100, failed_points, stuck_count),
    }


def ensure_remediation_queue(conn: Connection, student_id: int = 1, target_date: str | None = None) -> dict[str, Any]:
    today = target_date or date.today().isoformat()
    quiz_rows = [
        dict(row)
        for row in conn.execute(
            """
            SELECT qr.*, dt.title, dt.completion_standard
            FROM quiz_results qr
            JOIN daily_tasks dt ON dt.id = qr.daily_task_id
            WHERE dt.student_id = ? AND dt.date = ? AND qr.status != 'completed'
            ORDER BY qr.id DESC
            """,
            (student_id, today),
        ).fetchall()
    ]
    created: list[int] = []
    skipped = 0
    for row in quiz_rows:
        source_task_id = int(row["daily_task_id"])
        exists = conn.execute(
            """
            SELECT id FROM review_items
            WHERE student_id = ? AND source_task_id = ? AND reason IN ('auto_remediation', 'wrong_quiz', 'mastery_low')
              AND status IN ('pending', 'scheduled')
            LIMIT 1
            """,
            (student_id, source_task_id),
        ).fetchone()
        if exists:
            skipped += 1
            continue
        wrong_items = loads(row.get("wrong_items_json"), [])
        wrong_text = "；".join(str(item.get("question") or item)[:36] for item in wrong_items[:3]) if isinstance(wrong_items, list) else ""
        review_id = create_review_item(
            conn,
            student_id,
            source_task_id,
            f"{row['title']}：{wrong_text or '复盘错题并完成同类变式'}",
            str(row.get("completion_standard") or ""),
            "自动补救：小测未通过，次日先补薄弱点，再继续新内容。",
            "auto_remediation",
            1,
            "D1",
        )
        created.append(review_id)
    now = utc_now()
    if created:
        tomorrow = (date.fromisoformat(today) + timedelta(days=1)).isoformat()
        conn.execute(
            """
            INSERT INTO task_progress (daily_task_id, event_type, note, created_at)
            SELECT id, 'remediation_queue', ?, ?
            FROM daily_tasks
            WHERE student_id = ? AND date = ?
            ORDER BY id LIMIT 1
            """,
            (f"已创建 {len(created)} 个补救项，最早 {tomorrow} 进入今日任务。", now, student_id, today),
        )
    return {"created": created, "created_count": len(created), "skipped": skipped}


def _recommendation(score: int, failed_points: list[str], stuck_count: int) -> str:
    if score >= 90:
        return "保持当前节奏，明天可以继续新课，并用 5 分钟口头复述今天最重要的一点。"
    if failed_points:
        return f"明天先补漏：{failed_points[0][:28]}，要求孩子说出错因和改法。"
    if stuck_count:
        return "明天开始前先看昨日卡点，确认第一步会做，再进入新任务。"
    return "明天先安排 10 分钟复盘，再继续新内容。"
