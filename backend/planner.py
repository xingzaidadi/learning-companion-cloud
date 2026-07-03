from __future__ import annotations

from datetime import date, datetime, timedelta
from math import ceil
from sqlite3 import Connection, Row
from typing import Any

from .db import dumps, loads, utc_now
from .quiz import ensure_quiz_for_task
from .review import create_review_tasks
from .settings import get_settings


CATEGORY_LABELS = {
    "summer_homework": "暑假作业",
    "preview": "五年级预习",
    "ket": "KET 学习",
}


def _days_left(deadline: str | None, today: str) -> int:
    if not deadline:
        return 7
    try:
        target = datetime.strptime(deadline, "%Y-%m-%d").date()
        current = datetime.strptime(today, "%Y-%m-%d").date()
        return max((target - current).days + 1, 1)
    except ValueError:
        return 7


def _source_priority(source: Row) -> str:
    category = source["category"]
    if category == "summer_homework":
        return "P0"
    if category == "preview":
        return "P1"
    return "P2"


def _build_daily_task(source: Row, today: str) -> dict[str, Any]:
    category = source["category"]
    config = loads(source["config_json"], {})
    remaining = max(int(source["total_units"]) - int(source["completed_units"]), 1)
    daily_units = max(1, ceil(remaining / _days_left(source["deadline"], today)))
    label = config.get("display_label") or CATEGORY_LABELS.get(category, "学习任务")
    title = f"{label}：{source['title']}"
    sequence = config.get("lesson_sequence") or []
    current_lesson = ""
    if sequence:
        index = min(int(source["completed_units"]), len(sequence) - 1)
        current_lesson = sequence[index]
        title = f"{label}：{current_lesson}"

    if category == "summer_homework":
        unit_label = config.get("unit_label", "单位")
        pacing = config.get("pacing", f"每日 {daily_units} 个{unit_label}")
        description = f"{pacing}：完成 {source['subject'] or source['title']} 第 {int(source['completed_units']) + 1} {unit_label}，先做会的，难题做标记。"
        minutes = int(config.get("estimated_minutes", min(45, 20 + daily_units * 5)))
        standard = "书面完成并自行检查一遍，错题或不确定题做标记。"
        check_method = "checklist_quiz"
    elif category == "preview":
        topic = current_lesson or config.get("topic") or source["title"]
        steps = config.get("study_steps") or []
        step_text = "；".join(steps) if steps else "看讲解、做例题、完成练习"
        description = f"预习「{topic}」：{step_text}。"
        minutes = int(config.get("estimated_minutes", 30))
        standard = "能讲出今天学了什么、完成基础练习，并通过小测。"
        check_method = "quiz"
    else:
        module = config.get("module") or source["subject"] or "综合训练"
        description = f"KET {module} 短练：按计划完成一组训练。"
        minutes = int(config.get("estimated_minutes", 20))
        standard = "完成训练并记录不会的单词、句子或题目。"
        check_method = "quiz"

    return {
        "student_id": source["student_id"],
        "date": today,
        "source_id": source["id"],
        "priority": _source_priority(source),
        "title": title,
        "description": description,
        "estimated_minutes": minutes,
        "completion_standard": standard,
        "check_method": check_method,
    }


def generate_daily_tasks(conn: Connection, student_id: int = 1, target_date: str | None = None) -> list[dict[str, Any]]:
    today = target_date or date.today().isoformat()
    existing = conn.execute(
        "SELECT * FROM daily_tasks WHERE student_id = ? AND date = ? ORDER BY priority, id",
        (student_id, today),
    ).fetchall()
    if existing:
        return [dict(row) for row in existing]

    settings = get_settings(conn)
    rules = settings.get("path_rules", {})
    max_daily_tasks = int(rules.get("max_daily_tasks", 5))
    tasks: list[dict[str, Any]] = create_review_tasks(conn, student_id, today)
    for task in tasks:
        ensure_quiz_for_task(conn, task)

    remaining_slots = max(max_daily_tasks - len(tasks), 0)
    if remaining_slots == 0:
        return tasks

    block_new_preview = _should_block_new_preview(conn, student_id, today, rules)

    sources = conn.execute(
        """
        SELECT * FROM task_sources
        WHERE student_id = ? AND status = 'active'
          AND (? = 0 OR category != 'preview')
        ORDER BY
            CASE category
                WHEN 'summer_homework' THEN 1
                WHEN 'preview' THEN 2
                WHEN 'ket' THEN 3
                ELSE 4
            END,
            deadline IS NULL,
            deadline,
            id
        LIMIT ?
        """,
        (student_id, 1 if block_new_preview else 0, remaining_slots),
    ).fetchall()

    now = utc_now()
    for source in sources:
        task = _build_daily_task(source, today)
        cursor = conn.execute(
            """
            INSERT INTO daily_tasks (
                student_id, date, source_id, priority, title, description,
                estimated_minutes, completion_standard, check_method,
                status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'not_started', ?, ?)
            """,
            (
                task["student_id"],
                task["date"],
                task["source_id"],
                task["priority"],
                task["title"],
                task["description"],
                task["estimated_minutes"],
                task["completion_standard"],
                task["check_method"],
                now,
                now,
            ),
        )
        task["id"] = cursor.lastrowid
        task["status"] = "not_started"
        task["created_at"] = now
        task["updated_at"] = now
        ensure_quiz_for_task(conn, task)
        tasks.append(task)

    return tasks


def _should_block_new_preview(conn: Connection, student_id: int, today: str, rules: dict[str, Any]) -> bool:
    if not rules.get("low_score_blocks_new_preview", True):
        return False
    try:
        current = datetime.strptime(today, "%Y-%m-%d").date()
    except ValueError:
        current = date.today()
    yesterday = (current - timedelta(days=1)).isoformat()
    threshold = float(rules.get("quiz_pass_score", 0.8))
    low_quiz = conn.execute(
        """
        SELECT qr.correct, qr.total
        FROM quiz_results qr
        JOIN daily_tasks dt ON dt.id = qr.daily_task_id
        WHERE dt.student_id = ? AND dt.date >= ?
        ORDER BY qr.id DESC LIMIT 5
        """,
        (student_id, yesterday),
    ).fetchall()
    if any(row["total"] and row["correct"] / row["total"] < threshold for row in low_quiz):
        return True
    problem = conn.execute(
        """
        SELECT id FROM daily_tasks
        WHERE student_id = ? AND date >= ? AND status IN ('stuck', 'needs_revision')
        LIMIT 1
        """,
        (student_id, yesterday),
    ).fetchone()
    return problem is not None


def seed_demo_sources(conn: Connection, student_id: int = 1) -> int:
    count = conn.execute(
        "SELECT COUNT(*) AS count FROM task_sources WHERE student_id = ?",
        (student_id,),
    ).fetchone()["count"]
    if count:
        return 0

    now = utc_now()
    samples = [
        (
            "summer_homework",
            "数学暑假作业",
            "数学",
            40,
            0,
            "2026-08-20",
            {"estimated_minutes": 35},
        ),
        (
            "preview",
            "五年级数学第一节：小数乘整数",
            "数学",
            12,
            0,
            "2026-08-10",
            {
                "topic": "小数乘整数",
                "lesson_content": "理解小数乘整数的意义，掌握先按整数乘法计算，再根据小数位数点小数点。",
                "knowledge_points": "小数乘整数；小数点位置；积的小数位数",
                "estimated_minutes": 30,
            },
        ),
        (
            "ket",
            "KET 词汇与听力",
            "英语",
            30,
            0,
            "2026-08-25",
            {"module": "词汇 + 听力", "estimated_minutes": 20},
        ),
    ]
    for item in samples:
        conn.execute(
            """
            INSERT INTO task_sources (
                student_id, category, title, subject, total_units,
                completed_units, deadline, config_json, status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
            """,
            (
                student_id,
                item[0],
                item[1],
                item[2],
                item[3],
                item[4],
                item[5],
                dumps(item[6]),
                now,
                now,
            ),
        )
    return len(samples)
