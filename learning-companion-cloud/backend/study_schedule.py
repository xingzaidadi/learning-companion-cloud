from __future__ import annotations

from datetime import datetime, timedelta
from sqlite3 import Connection
from typing import Any


DEFAULT_WINDOWS = [
    {"block": "上午深度学习", "start": "08:30", "end": "10:10", "best_for": ["数学", "语文"], "max_minutes": 100, "mode": "deep"},
    {"block": "上午轻输入", "start": "10:30", "end": "11:30", "best_for": ["英语", "语文"], "max_minutes": 60, "mode": "light"},
    {"block": "下午练习巩固", "start": "14:00", "end": "15:40", "best_for": ["数学", "英语", "综合"], "max_minutes": 100, "mode": "practice"},
    {"block": "下午运动阅读", "start": "16:00", "end": "18:00", "best_for": ["体育", "语文", "综合"], "max_minutes": 120, "mode": "active"},
    {"block": "晚上轻复盘", "start": "19:00", "end": "20:40", "best_for": ["英语", "语文", "综合"], "max_minutes": 100, "mode": "evening"},
]

BREAK_MINUTES = 10
MORNING_END = "11:30"
MAX_START_IDLE_MINUTES = 30


def infer_subject_from_task(task: dict[str, Any]) -> str:
    text = f"{task.get('title', '')} {task.get('description', '')} {task.get('completion_standard', '')}"
    if any(word in text for word in ("体育", "运动", "跳绳", "拉伸", "慢跑")):
        return "体育"
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
    subject_rank = {"数学": 0, "语文": 1, "英语": 2, "体育": 3, "综合": 4}.get(infer_subject_from_task(task), 4)
    priority_rank = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}.get(task.get("priority", "P2"), 2)
    return status_rank * 1000 + kind_rank * 100 + priority_rank * 10 + subject_rank


def _parse_time(value: str) -> datetime:
    return datetime.strptime(value, "%H:%M")


def _format_time(value: datetime) -> str:
    return value.strftime("%H:%M")


def _has_morning_task(arranged: list[dict[str, Any]]) -> bool:
    morning_end = _parse_time(MORNING_END)
    for task in arranged:
        planned_start = task.get("planned_start")
        if planned_start and _parse_time(str(planned_start)) < morning_end:
            return True
    return False


def _morning_anchor_rank(
    window: dict[str, Any],
    subject: str,
    arranged: list[dict[str, Any]],
    urgent: bool,
) -> tuple[int, ...]:
    earliest_start = _parse_time(DEFAULT_WINDOWS[0]["start"])
    idle_minutes = int((window["cursor"] - earliest_start).total_seconds() // 60)
    would_leave_large_initial_gap = not arranged and idle_minutes > MAX_START_IDLE_MINUTES
    needs_morning_anchor = not arranged or not _has_morning_task(arranged)
    is_morning_window = window["cursor"] < _parse_time(MORNING_END)

    if urgent:
        return (0 if is_morning_window else 1, idle_minutes, 0 if subject in window["best_for"] else 1, 0)
    return (
        1 if would_leave_large_initial_gap else 0,
        0 if (needs_morning_anchor and is_morning_window) else 1,
        idle_minutes,
        0 if subject in window["best_for"] else 1,
    )


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
    if "晚上" in block:
        return "晚上只做轻复盘、订正、阅读或听说，不安排新的高强度内容，20:40 后进入收尾。"
    return "按任务优先级和学科交替安排，避免同类任务连续消耗注意力。"


def _is_evening_fit(task: dict[str, Any]) -> bool:
    text = f"{task.get('title', '')} {task.get('description', '')} {task.get('completion_standard', '')}"
    subject = infer_subject_from_task(task)
    kind = _task_kind(task)
    if task.get("status") in {"checking", "needs_revision", "stuck"}:
        return True
    if kind == "补漏复习":
        return True
    if any(word in text for word in ("KET", "听力", "口语", "跟读", "单词", "阅读", "诵读", "背诵", "日积月累", "订正", "错题", "复盘")):
        return True
    if subject in {"英语", "语文", "综合"} and int(task.get("estimated_minutes") or 20) <= 35:
        return True
    return False


def _window_score(task: dict[str, Any], window: dict[str, Any], last_subject: str, arranged: list[dict[str, Any]]) -> tuple[Any, ...]:
    subject = infer_subject_from_task(task)
    mode = window.get("mode", "")
    urgent = task.get("status") in {"checking", "needs_revision", "stuck"}
    anchor_rank = _morning_anchor_rank(window, subject, arranged, urgent)
    if mode == "evening" and not _is_evening_fit(task):
        return (*anchor_rank, 9, 9, window["cursor"])
    if urgent:
        return (*anchor_rank, 0 if mode in {"evening", "light", "practice"} else 1, 0, window["cursor"])
    if _task_kind(task) == "补漏复习":
        return (*anchor_rank, 0 if mode in {"deep", "light", "evening"} else 1, 0, window["cursor"])
    fit_rank = 0 if subject in window["best_for"] else 2
    if mode == "evening":
        fit_rank = 0 if _is_evening_fit(task) else 9
    subject_repeat_penalty = 1 if subject == last_subject else 0
    deep_penalty = 2 if mode == "evening" and subject == "数学" else 0
    return (*anchor_rank, fit_rank + deep_penalty, subject_repeat_penalty, window["cursor"])


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
        minutes = max(10, min(int(task.get("estimated_minutes") or 20), 60))
        subject = infer_subject_from_task(task)
        candidates = sorted(windows, key=lambda window: _window_score(task, window, last_subject, arranged))
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
    arranged.sort(key=lambda task: (task.get("planned_start") or "99:99", int(task["id"])))
    for index, task in enumerate(arranged, start=1):
        chronological_order = index * 10
        if int(task.get("sort_order") or 0) != chronological_order:
            conn.execute(
                "UPDATE daily_tasks SET sort_order = ?, updated_at = datetime('now') WHERE id = ?",
                (chronological_order, task["id"]),
            )
            task["sort_order"] = chronological_order
    return arranged
