from __future__ import annotations

from datetime import datetime, timedelta
from sqlite3 import Connection
from typing import Any


DEFAULT_WINDOWS = [
    {"block": "上午深度学习", "start": "09:00", "end": "10:25", "best_for": ["数学", "语文"], "max_minutes": 85},
    {"block": "上午轻输入", "start": "10:45", "end": "11:30", "best_for": ["英语", "语文"], "max_minutes": 45},
    {"block": "下午练习巩固", "start": "14:30", "end": "15:20", "best_for": ["数学", "英语", "综合"], "max_minutes": 50},
    {"block": "傍晚复盘补漏", "start": "16:10", "end": "16:45", "best_for": ["语文", "英语", "综合"], "max_minutes": 35},
]

BREAK_MINUTES = 10


def infer_subject_from_task(task: dict[str, Any]) -> str:
    text = f"{task.get('title', '')} {task.get('description', '')} {task.get('completion_standard', '')}"
    if any(word in text for word in ("英语", "Unit", "school", "library", "classroom", "teacher", "单词")):
        return "英语"
    if any(word in text for word in ("数学", "小数", "乘法", "除法", "计算", "应用题", "面积")):
        return "数学"
    if any(word in text for word in ("语文", "课文", "生字", "白鹭", "阅读", "作文", "日积月累")):
        return "语文"
    return "综合"


def _task_kind(task: dict[str, Any]) -> str:
    title = task.get("title", "")
    check_method = task.get("check_method", "")
    if check_method == "review_quiz" or title.startswith("D1 补漏"):
        return "补漏复习"
    if "预习" in title:
        return "新课预习"
    if "作业" in title:
        return "书面作业"
    return "综合任务"


def _priority_rank(task: dict[str, Any]) -> int:
    status_rank = {
        "checking": 0,
        "needs_revision": 1,
        "stuck": 2,
        "in_progress": 3,
        "paused": 4,
        "not_started": 5,
        "completed": 9,
    }.get(task.get("status", "not_started"), 5)
    kind_rank = {"补漏复习": 0, "书面作业": 1, "新课预习": 2, "综合任务": 3}.get(_task_kind(task), 3)
    subject_rank = {"数学": 0, "语文": 1, "英语": 2, "综合": 3}.get(infer_subject_from_task(task), 3)
    priority_rank = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}.get(task.get("priority", "P2"), 2)
    return status_rank * 1000 + kind_rank * 100 + priority_rank * 10 + subject_rank


def _parse_time(value: str) -> datetime:
    return datetime.strptime(value, "%H:%M")


def _format_time(value: datetime) -> str:
    return value.strftime("%H:%M")


def _schedule_reason(task: dict[str, Any], block: str) -> str:
    subject = infer_subject_from_task(task)
    kind = _task_kind(task)
    status = task.get("status", "")
    if status in {"checking", "needs_revision", "stuck"}:
        return "先处理检查/订正/卡住任务，避免带着问题进入新内容。"
    if kind == "补漏复习":
        return "补漏放在当天靠前位置，利用间隔复习减少遗忘。"
    if subject in {"数学", "语文"} and "上午" in block:
        return "上午注意力较稳定，适合数学计算、语文理解等高认知任务。"
    if subject == "英语":
        return "英语安排在较轻时段，适合听读、跟读、词汇复现。"
    return "按任务优先级和学科交替安排，避免同类任务连续消耗注意力。"


def arrange_daily_schedule(conn: Connection, student_id: int = 1, target_date: str = "", respect_existing_order: bool = False) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT *
        FROM daily_tasks
        WHERE student_id = ? AND date = ?
        ORDER BY priority, id
        """,
        (student_id, target_date),
    ).fetchall()
    tasks = [dict(row) for row in rows]
    if not tasks:
        return []

    if respect_existing_order:
        pending = sorted(tasks, key=lambda task: (int(task.get("sort_order") or 999999), _priority_rank(task), int(task["id"])))
    else:
        pending = sorted(tasks, key=_priority_rank)
    windows = [
        {
            **window,
            "cursor": _parse_time(window["start"]),
            "end_time": _parse_time(window["end"]),
        }
        for window in DEFAULT_WINDOWS
    ]
    fallback_cursor = _parse_time("19:30")
    sort_order = 10
    arranged: list[dict[str, Any]] = []
    last_subject = ""

    for task in pending:
        minutes = max(10, min(int(task.get("estimated_minutes") or 20), 45))
        subject = infer_subject_from_task(task)
        candidates = sorted(
            windows,
            key=lambda window: (
                0 if subject in window["best_for"] else 1,
                1 if subject == last_subject else 0,
                window["cursor"],
            ),
        )
        selected = None
        for window in candidates:
            if window["cursor"] + timedelta(minutes=minutes) <= window["end_time"]:
                selected = window
                break
        if selected is None:
            start = fallback_cursor
            end = start + timedelta(minutes=minutes)
            block = "晚间弹性补齐"
            fallback_cursor = end + timedelta(minutes=BREAK_MINUTES)
        else:
            start = selected["cursor"]
            end = start + timedelta(minutes=minutes)
            block = selected["block"]
            selected["cursor"] = end + timedelta(minutes=BREAK_MINUTES)

        conn.execute(
            """
            UPDATE daily_tasks
            SET sort_order = ?, planned_start = ?, planned_end = ?,
                schedule_block = ?, schedule_reason = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (sort_order, _format_time(start), _format_time(end), block, _schedule_reason(task, block), task["id"]),
        )
        task.update(
            {
                "sort_order": sort_order,
                "planned_start": _format_time(start),
                "planned_end": _format_time(end),
                "schedule_block": block,
                "schedule_reason": _schedule_reason(task, block),
            }
        )
        arranged.append(task)
        sort_order += 10
        last_subject = subject
    return arranged
