from __future__ import annotations

from datetime import date, datetime, timedelta
from math import ceil
from sqlite3 import Connection, Row
from typing import Any

from .db import dumps, loads, utc_now
from .quiz import ensure_quiz_for_task
from .review import create_review_tasks
from .settings import get_settings
from .study_schedule import arrange_daily_schedule


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


def _source_text(source: Row) -> str:
    config = loads(source["config_json"], {})
    parts = [
        str(source["category"] or ""),
        str(source["title"] or ""),
        str(source["subject"] or ""),
        str(config.get("display_label") or ""),
        str(config.get("module") or ""),
        str(config.get("lesson_content") or ""),
        str(config.get("knowledge_points") or ""),
    ]
    return " ".join(parts)


def _source_subject(source: Row) -> str:
    text = _source_text(source)
    subject = str(source["subject"] or "")
    if subject:
        return subject
    if any(word in text for word in ("体育", "运动", "跳绳", "拉伸")):
        return "体育"
    if any(word in text for word in ("数学", "小数", "口算", "每日一练")):
        return "数学"
    if any(word in text for word in ("英语", "KET", "Unit", "单词")):
        return "英语"
    if any(word in text for word in ("语文", "诵读", "妙笔", "阅读", "课文")):
        return "语文"
    return "综合"


def _source_bucket(source: Row) -> str:
    text = _source_text(source)
    category = str(source["category"] or "")
    subject = _source_subject(source)
    if category == "ket" or "KET" in text:
        return "ket"
    if category == "preview":
        return "preview"
    if subject == "体育" or any(word in text for word in ("每日运动", "跳绳", "拉伸", "慢跑")):
        return "movement"
    if any(word in text for word in ("阅读书目", "一千零一夜", "民间故事", "外婆")):
        return "reading"
    if any(word in text for word in ("娱乐", "电影", "寻梦环游记")):
        return "leisure"
    if subject == "数学":
        if any(word in str(source["title"] or "") for word in ("口算", "每日一练")):
            return "math_light"
        return "math_core"
    if subject == "语文":
        return "chinese_homework"
    if subject == "英语":
        return "english_homework"
    return "general"


def _day_index(today: str) -> int:
    try:
        current = datetime.strptime(today, "%Y-%m-%d").date()
        return max((current - date(2026, 7, 4)).days, 0)
    except ValueError:
        return 0


def _is_weekend(today: str) -> bool:
    try:
        return datetime.strptime(today, "%Y-%m-%d").date().weekday() >= 5
    except ValueError:
        return False


def _pick_rotating(candidates: list[Row], day_index: int, used_ids: set[int]) -> Row | None:
    available = [source for source in candidates if int(source["id"]) not in used_ids]
    if not available:
        return None
    return available[day_index % len(available)]


def _select_balanced_sources(sources: list[Row], slots: int, today: str) -> list[Row]:
    if slots <= 0:
        return []
    day_index = _day_index(today)
    buckets: dict[str, list[Row]] = {}
    for source in sources:
        buckets.setdefault(_source_bucket(source), []).append(source)

    for bucket_sources in buckets.values():
        bucket_sources.sort(key=lambda source: (source["deadline"] is None, source["deadline"] or "", int(source["id"])))

    if slots >= 8:
        desired = ["math_core", "math_light", "chinese_homework", "english_homework", "preview", "ket", "reading", "movement"]
    elif slots == 7:
        desired = ["math_core", "math_light", "chinese_homework", "english_homework", "preview", "ket", "movement"]
    elif slots == 6:
        desired = ["math_core", "math_light", "chinese_homework", "english_homework", "preview", "movement"]
    else:
        desired = ["math_core", "chinese_homework", "english_homework", "preview", "movement"][:slots]

    if _is_weekend(today) and buckets.get("leisure") and "reading" in desired:
        desired[desired.index("reading")] = "leisure"

    selected: list[Row] = []
    used_ids: set[int] = set()
    subject_counts: dict[str, int] = {}

    def add_source(source: Row | None) -> None:
        if not source or int(source["id"]) in used_ids or len(selected) >= slots:
            return
        selected.append(source)
        used_ids.add(int(source["id"]))
        subject = _source_subject(source)
        subject_counts[subject] = subject_counts.get(subject, 0) + 1

    for bucket in desired:
        candidates = buckets.get(bucket, [])
        if bucket == "math_core" and not candidates:
            candidates = buckets.get("math_light", [])
        if bucket == "math_light" and not candidates:
            candidates = buckets.get("math_core", [])
        add_source(_pick_rotating(candidates, day_index, used_ids))

    remaining = [source for source in sources if int(source["id"]) not in used_ids]
    remaining.sort(
        key=lambda source: (
            subject_counts.get(_source_subject(source), 0),
            0 if _source_bucket(source) in {"movement", "reading", "ket", "preview"} else 1,
            source["deadline"] is None,
            source["deadline"] or "",
            int(source["id"]),
        )
    )
    for source in remaining:
        add_source(source)
    return selected


def _build_daily_task(source: Row, today: str) -> dict[str, Any]:
    category = source["category"]
    config = loads(source["config_json"], {})
    remaining = max(int(source["total_units"]) - int(source["completed_units"]), 1)
    configured_daily_units = int(config.get("daily_units") or 0)
    daily_units = configured_daily_units if configured_daily_units > 0 else max(1, ceil(remaining / _days_left(source["deadline"], today)))
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


def generate_daily_tasks(
    conn: Connection,
    student_id: int = 1,
    target_date: str | None = None,
    force_all_sources: bool = False,
) -> list[dict[str, Any]]:
    today = target_date or date.today().isoformat()
    existing = conn.execute(
        "SELECT * FROM daily_tasks WHERE student_id = ? AND date = ? ORDER BY priority, id",
        (student_id, today),
    ).fetchall()

    settings = get_settings(conn)
    rules = settings.get("path_rules", {})
    max_daily_tasks = int(rules.get("max_daily_tasks", 5))
    tasks: list[dict[str, Any]] = [dict(row) for row in existing]

    existing_source_ids = {int(task["source_id"]) for task in tasks if task.get("source_id") is not None}
    if len(tasks) < max_daily_tasks:
        review_tasks = create_review_tasks(conn, student_id, today)
        tasks.extend(review_tasks)
    for task in tasks:
        ensure_quiz_for_task(conn, task)

    remaining_slots = max(max_daily_tasks - len(tasks), 0)
    if remaining_slots == 0 and not force_all_sources:
        arrange_daily_schedule(conn, student_id, today)
        return _today_tasks(conn, student_id, today)

    block_new_preview = False if force_all_sources else _should_block_new_preview(conn, student_id, today, rules)
    source_limit = 500

    sources = conn.execute(
        """
        SELECT * FROM task_sources
        WHERE student_id = ? AND status = 'active'
          AND completed_units < total_units
          AND (? = 0 OR category != 'preview')
          AND id NOT IN (
              SELECT source_id FROM daily_tasks
              WHERE student_id = ? AND date = ? AND source_id IS NOT NULL
          )
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
        (student_id, 1 if block_new_preview else 0, student_id, today, source_limit),
    ).fetchall()
    if not force_all_sources:
        sources = _select_balanced_sources(list(sources), remaining_slots, today)

    now = utc_now()
    for source in sources:
        if int(source["id"]) in existing_source_ids:
            continue
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

    arrange_daily_schedule(conn, student_id, today)
    return _today_tasks(conn, student_id, today)


def _today_tasks(conn: Connection, student_id: int, target_date: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT * FROM daily_tasks
        WHERE student_id = ? AND date = ?
        ORDER BY
            CASE WHEN sort_order = 0 THEN 999999 ELSE sort_order END,
            priority,
            id
        """,
        (student_id, target_date),
    ).fetchall()
    return [dict(row) for row in rows]


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
