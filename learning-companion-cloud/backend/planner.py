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


def _is_invalid_source(source: Row) -> bool:
    title = str(source["title"] or "")
    subject = str(source["subject"] or "")
    config = loads(source["config_json"], {})
    warning = str(config.get("warning", ""))
    text = f"{title} {subject} {warning}"
    return any(marker in text for marker in ("待重新生成", "编码损坏", "????"))


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
        if subject == "数学":
            return "math_preview"
        if subject == "语文":
            return "chinese_preview"
        if subject == "英语":
            return "english_preview"
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


def _weekday(today: str) -> int:
    try:
        return datetime.strptime(today, "%Y-%m-%d").date().weekday()
    except ValueError:
        return 0


def _pick_rotating(candidates: list[Row], day_index: int, used_ids: set[int]) -> Row | None:
    available = [source for source in candidates if int(source["id"]) not in used_ids]
    if not available:
        return None
    return available[day_index % len(available)]


def _ket_level(settings: dict[str, Any]) -> str:
    level = str(settings.get("ket_plan", {}).get("level") or "standard").lower()
    return level if level in {"light", "standard", "advanced"} else "standard"


def _ket_plan_for_day(today: str, settings: dict[str, Any], low_score: bool = False) -> dict[str, Any]:
    ket_settings = settings.get("ket_plan", {})
    level = _ket_level(settings)
    weekday = _weekday(today)
    if low_score:
        minutes = int(ket_settings.get("low_score_remedial_minutes") or 20)
        if level == "advanced":
            minutes += 10
        return {
            "module": "错词错题补救",
            "minutes": minutes,
            "steps": ["复盘昨天错词/错题", "重做 1 组同类题", "朗读正确句子", "记录还不稳的点"],
            "standard": "能说出错因，并把同类题正确完成到 80% 以上。",
        }
    base_week = [
        {
            "module": "词汇 + 听力",
            "steps": ["复习 10 个词", "听 1 段材料抓关键词", "跟读 3 句", "记录 2 个没听清的词"],
            "standard": "能听出场景和关键词，错词已记录。",
        },
        {
            "module": "词汇 + 阅读",
            "steps": ["复习 10 个词", "读 1 篇短文", "圈定位句", "说出 2 个答案依据"],
            "standard": "能用原文依据说明答案，不靠猜。",
        },
        {
            "module": "写作短练",
            "steps": ["复习 8 个可用于写作的词", "写 3–5 句", "检查时态/单复数", "朗读一遍"],
            "standard": "句子完整，至少 3 句无明显语法错误。",
        },
        {
            "module": "听力 + 跟读",
            "steps": ["听 1 段材料", "跟读重点句", "模仿语音语调", "复述 1 句意思"],
            "standard": "能跟读清楚，并说出材料主要内容。",
        },
        {
            "module": "口语表达",
            "steps": ["准备 1 个小话题", "用完整句回答", "补充 1 个理由", "录音回听一次"],
            "standard": "能用完整句说 1–2 分钟，声音清楚。",
        },
        {
            "module": "周末小模拟",
            "steps": ["完成一组听力/阅读小模拟", "核对错题", "整理错词", "选 1 题讲清错因"],
            "standard": "完成阶段检测，并产出错题/错词清单。",
        },
        {
            "module": "轻复盘",
            "steps": ["复习本周错词", "重读 1 篇做过的材料", "口头总结本周进步", "整理下周目标"],
            "standard": "说清本周最不稳的 1 个点和下周改法。",
        },
    ]
    plan = dict(base_week[weekday])
    if level == "light":
        plan["minutes"] = 25 if weekday != 5 else 45
        plan["steps"] = plan["steps"][:3]
    elif level == "advanced":
        advanced_extra = {
            0: "加做 5 个拼写/听写词",
            1: "加读 1 段同主题短文",
            2: "扩展到 5–7 句并使用 because/also",
            3: "增加 1 句口头复述",
            4: "补充 1 个追问回答",
            5: "模拟后做 10 分钟错题复盘",
            6: "选 1 个薄弱点做 10 分钟补强",
        }[weekday]
        plan["steps"] = [*plan["steps"], advanced_extra]
        plan["minutes"] = 45 if weekday != 5 else int(ket_settings.get("mock_minutes") or 75)
    else:
        plan["minutes"] = int(ket_settings.get("weekday_minutes") or 35) if weekday != 5 else int(ket_settings.get("mock_minutes") or 60)
    return plan


def _ket_recent_low_score(conn: Connection, student_id: int, source_id: int, pass_score: float) -> bool:
    row = conn.execute(
        """
        SELECT qr.correct, qr.total
        FROM quiz_results qr
        JOIN daily_tasks dt ON dt.id = qr.daily_task_id
        WHERE dt.student_id = ? AND dt.source_id = ? AND qr.total > 0
        ORDER BY qr.id DESC
        LIMIT 1
        """,
        (student_id, source_id),
    ).fetchone()
    if not row:
        return False
    return (int(row["correct"]) / max(int(row["total"]), 1)) < pass_score


def _select_balanced_sources(sources: list[Row], slots: int, today: str, settings: dict[str, Any] | None = None) -> list[Row]:
    if slots <= 0:
        return []
    day_index = _day_index(today)
    buckets: dict[str, list[Row]] = {}
    for source in sources:
        buckets.setdefault(_source_bucket(source), []).append(source)

    for bucket_sources in buckets.values():
        bucket_sources.sort(key=lambda source: (source["deadline"] is None, source["deadline"] or "", int(source["id"])))

    if slots >= 10:
        desired = [
            "math_core",
            "math_light",
            "chinese_homework",
            "english_homework",
            "chinese_preview",
            "math_preview",
            "english_preview",
            "ket",
            "reading",
            "movement",
        ]
    elif slots >= 8:
        desired = ["math_core", "math_light", "chinese_homework", "english_homework", "math_preview", "english_preview", "ket", "movement"]
    elif slots == 7:
        desired = ["math_core", "math_light", "chinese_homework", "english_homework", "math_preview", "ket", "movement"]
    elif slots == 6:
        desired = ["math_core", "math_light", "chinese_homework", "english_homework", "math_preview", "movement"]
    else:
        desired = ["math_core", "chinese_homework", "english_homework", "math_preview", "movement"][:slots]

    weekend_light_mode = bool((settings or {}).get("path_rules", {}).get("weekend_light_mode", False))
    if weekend_light_mode and _is_weekend(today) and buckets.get("leisure") and "reading" in desired:
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
            0 if _source_bucket(source) in {"movement", "reading", "ket", "chinese_preview", "math_preview", "english_preview", "preview"} else 1,
            source["deadline"] is None,
            source["deadline"] or "",
            int(source["id"]),
        )
    )
    for source in remaining:
        add_source(source)
    return selected


def _build_daily_task(source: Row, today: str, settings: dict[str, Any] | None = None, ket_low_score: bool = False) -> dict[str, Any]:
    category = source["category"]
    config = loads(source["config_json"], {})
    settings = settings or {}
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

    if _source_bucket(source) == "movement":
        description = f"完成 {source['title']}：按计划热身、运动、拉伸，注意安全和补水。"
        minutes = int(config.get("estimated_minutes", 60))
        standard = "完成运动并做拉伸，由孩子或家长打卡确认。"
        check_method = "checkin"
    elif category == "summer_homework":
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
        plan = _ket_plan_for_day(today, settings, low_score=ket_low_score)
        module = plan["module"]
        level_text = {"light": "轻量", "standard": "标准", "advanced": "进阶"}[_ket_level(settings)]
        title = f"KET：{module}"
        description = f"{level_text}版 KET 训练：{'；'.join(plan['steps'])}。"
        minutes = int(plan["minutes"])
        standard = plan["standard"]
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
    clean_sources = [source for source in sources if not _is_invalid_source(source)]
    if not force_all_sources:
        sources = _select_balanced_sources(clean_sources, remaining_slots, today, settings)
    else:
        sources = clean_sources

    now = utc_now()
    for source in sources:
        if int(source["id"]) in existing_source_ids:
            continue
        pass_score = float(rules.get("quiz_pass_score", 0.8))
        ket_low_score = source["category"] == "ket" and _ket_recent_low_score(conn, student_id, int(source["id"]), pass_score)
        task = _build_daily_task(source, today, settings, ket_low_score=ket_low_score)
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
