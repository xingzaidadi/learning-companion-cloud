from __future__ import annotations

from sqlite3 import Connection
from decimal import Decimal, InvalidOperation
from typing import Any

from .db import dumps, loads, utc_now
from .ai_provider import generate_ai_questions
from .curriculum import find_curriculum_context
from .question_engine import build_content_quiz
from .review import create_review_item
from .rewards import add_reward
from .settings import get_settings


def _source_context(conn: Connection, task: dict[str, Any]) -> dict[str, Any]:
    source_id = task.get("source_id")
    if not source_id:
        return {"category": "review", "subject": "", "config": {}}
    row = conn.execute("SELECT * FROM task_sources WHERE id = ?", (source_id,)).fetchone()
    if not row:
        return {"category": "unknown", "subject": "", "config": {}}
    return {
        "category": row["category"],
        "subject": row["subject"],
        "config": loads(row["config_json"], {}),
    }


def _short(question: str, answer: str, explanation: str = "回答不为空即可，重点是说清楚思路。") -> dict[str, Any]:
    return {
        "question_type": "short",
        "question": question,
        "answer": answer,
        "explanation": explanation,
    }


def _choice(question: str, options: list[str], answer: str, explanation: str) -> dict[str, Any]:
    return {
        "question_type": "choice",
        "question": question,
        "options_json": dumps(options),
        "answer": answer,
        "explanation": explanation,
    }


def _templates(conn: Connection, task: dict[str, Any]) -> list[dict[str, Any]]:
    title = task.get("title", "今天任务")
    standard = task.get("completion_standard", "完成任务")
    context = _source_context(conn, task)
    category = context["category"]
    subject = context["subject"]
    config = context["config"]
    settings = get_settings(conn)
    region = settings.get("region", {})
    version = (
        region.get("chinese_version")
        if "语文" in subject
        else region.get("math_version")
        if "数学" in subject
        else region.get("english_version")
    )
    content_text = "\n".join(
        str(value)
        for value in (
            title,
            task.get("description", ""),
            standard,
            config.get("lesson_content", ""),
            config.get("knowledge_points", ""),
            config.get("vocabulary", ""),
            config.get("raw", ""),
        )
        if value
    )
    curriculum_context = find_curriculum_context(
        "chinese" if "语文" in subject else "math" if "数学" in subject else "english" if "英语" in subject else "",
        content_text,
        version,
    )
    scope = ""
    if curriculum_context:
        scope = f"{curriculum_context.get('unit')}；知识点：{'、'.join(curriculum_context.get('points', []))}；范围限制：{curriculum_context.get('scope_note')}"
    ai_items = generate_ai_questions(settings, scope, content_text)
    if ai_items:
        return ai_items

    content_items = build_content_quiz(
        category=category,
        subject=subject,
        title=title,
        description=task.get("description", ""),
        standard=standard,
        config=config,
        version=version,
    )
    if content_items:
        return content_items

    if task.get("check_method") == "review_quiz":
        return [
            _short(f"请重新回答或重做这个问题：{title}", "已订正", "复习任务需要把正确过程说出来。"),
            _short("这次你打算怎样避免同类错误？", "说出避免方法", "能说出一个具体方法即可。"),
            _choice("订正后还不确定怎么办？", ["先跳过", "标记并请家长协助", "直接完成"], "标记并请家长协助", "复习任务不能糊弄，需要留下线索。"),
        ]

    if category == "summer_homework":
        return [
            _short(f"从「{title}」中选 1 道你觉得最难的题，写出解题思路。", "写出思路"),
            _choice("遇到不会的暑假作业题，最合适的处理方式是？", ["空着不管", "标记题号并写出卡点", "抄答案"], "标记题号并写出卡点", "标记卡点方便晚间订正。"),
            _short("请写出今天检查后发现的 1 个易错点；如果没有，就写“暂无”。", "暂无"),
            _choice("暑假作业完成标准是哪一个？", ["写完就行", "完成并自行检查一遍", "只做简单题"], "完成并自行检查一遍", standard),
        ]

    if category == "preview":
        topic = config.get("topic") or title
        if "小数" in topic or subject == "数学":
            return [
                _choice("3.6 × 10 的结果是？", ["0.36", "36", "360"], "36", "小数乘 10，小数点向右移动一位。"),
                _choice("4.8 ÷ 10 的结果是？", ["48", "0.48", "4.08"], "0.48", "小数除以 10，小数点向左移动一位。"),
                _short(f"请用一句话说明今天预习的知识点「{topic}」。", "说清知识点"),
                _short("写出一道你能独立完成的例题或同类题。", "写出题目和答案"),
            ]
        return [
            _short(f"请概括今天预习的知识点「{topic}」。", "说清知识点"),
            _short("写出一个例题或例句。", "写出例子"),
            _choice("预习后最重要的是？", ["只看不练", "做少量练习确认会用", "马上学下一章"], "做少量练习确认会用", "预习要形成可检查的掌握。"),
        ]

    if category == "ket":
        module = (config.get("module") or subject or title).lower()
        if "听" in module or "listening" in module:
            return [
                _short("请写出今天听力中听到的 2 个关键词。", "写出关键词"),
                _choice("听力没听清时第一反应应该是？", ["停住不做", "抓关键词继续听", "乱选"], "抓关键词继续听", "KET 听力先抓关键词和场景。"),
                _short("请写出 1 个今天需要复习的英文词或短语。", "写出词汇"),
            ]
        if "口" in module or "speaking" in module:
            return [
                _short("请写出今天口语回答的主题。", "写出主题"),
                _short("请写出一句完整英文回答。", "写出英文句子"),
                _choice("KET 口语回答最重要的是？", ["只说一个词", "完整句 + 声音清楚", "完全不回答"], "完整句 + 声音清楚", "口语训练要敢说完整句。"),
            ]
        return [
            _short("请写出今天记住的 3 个 KET 单词。", "写出单词"),
            _short("任选 1 个单词造一个英文短句。", "写出短句"),
            _choice("复习 KET 词汇最适合的方式是？", ["一天背很多不复习", "每天短练并重复", "只看中文"], "每天短练并重复", "KET 更适合高频短练。"),
        ]

    return [
        _short(f"请写出你完成「{title}」后最有把握的一点。", "已完成"),
        _short(f"「{title}」的完成标准是什么？", standard, "对照任务卡上的完成标准检查。"),
        _choice("如果遇到不会的题，正确做法是哪一个？", ["跳过不管", "标记并说明卡在哪里", "直接点完成"], "标记并说明卡在哪里", "不会时要留下线索，方便订正和家长协助。"),
    ]


def ensure_quiz_for_task(conn: Connection, task: dict[str, Any]) -> list[dict[str, Any]]:
    existing = conn.execute(
        "SELECT * FROM quiz_items WHERE daily_task_id = ? ORDER BY id",
        (task["id"],),
    ).fetchall()
    if existing:
        return [dict(row) for row in existing]

    now = utc_now()
    items = _templates(conn, task)
    for item in items:
        conn.execute(
            """
            INSERT INTO quiz_items (
                daily_task_id, question_type, question, options_json,
                answer, explanation, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task["id"],
                item["question_type"],
                item["question"],
                item.get("options_json", "[]"),
                item["answer"],
                item["explanation"],
                now,
            ),
        )
    rows = conn.execute(
        "SELECT * FROM quiz_items WHERE daily_task_id = ? ORDER BY id",
        (task["id"],),
    ).fetchall()
    return [dict(row) for row in rows]


def regenerate_quiz_for_task(conn: Connection, task_id: int) -> list[dict[str, Any]]:
    task = conn.execute("SELECT * FROM daily_tasks WHERE id = ?", (task_id,)).fetchone()
    if not task:
        return []
    conn.execute("DELETE FROM quiz_items WHERE daily_task_id = ?", (task_id,))
    return ensure_quiz_for_task(conn, dict(task))


def _exact_match(user_answer: str, expected: str) -> bool:
    normalized_user = user_answer.lower().replace(" ", "")
    for value in expected.split("|"):
        normalized_expected = value.strip().lower().replace(" ", "")
        if normalized_user == normalized_expected:
            return True
        try:
            if Decimal(normalized_user) == Decimal(normalized_expected):
                return True
        except InvalidOperation:
            pass
    return False


def grade_quiz(conn: Connection, task_id: int, answers: dict[str, str]) -> dict[str, Any]:
    task = conn.execute("SELECT * FROM daily_tasks WHERE id = ?", (task_id,)).fetchone()
    if not task:
        raise ValueError("任务不存在")
    items = conn.execute(
        "SELECT * FROM quiz_items WHERE daily_task_id = ? ORDER BY id",
        (task_id,),
    ).fetchall()
    wrong_items: list[dict[str, str]] = []
    correct = 0
    for item in items:
        user_answer = answers.get(str(item["id"]), "").strip()
        expected = item["answer"].strip()
        if item["question_type"] == "short":
            is_correct = bool(user_answer)
        elif item["question_type"] == "exact":
            is_correct = _exact_match(user_answer, expected)
        else:
            is_correct = user_answer == expected
        if is_correct:
            correct += 1
        else:
            wrong_items.append(
                {
                    "question": item["question"],
                    "your_answer": user_answer,
                    "answer": expected,
                    "explanation": item["explanation"],
                }
            )
            create_review_item(
                conn,
                int(task["student_id"]),
                task_id,
                item["question"],
                expected,
                item["explanation"],
                "wrong_quiz",
                1,
            )

    total = len(items)
    ratio = correct / total if total else 0
    status = "completed" if ratio >= 0.8 else "needs_revision"
    now = utc_now()
    conn.execute(
        """
        INSERT INTO quiz_results (daily_task_id, total, correct, wrong_items_json, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (task_id, total, correct, dumps(wrong_items), status, now),
    )
    conn.execute(
        "UPDATE daily_tasks SET status = ?, updated_at = ? WHERE id = ?",
        (status, now, task_id),
    )
    if status == "completed" and task["source_id"]:
        conn.execute(
            """
            UPDATE task_sources
            SET completed_units = MIN(total_units, completed_units + 1), updated_at = ?
            WHERE id = ?
            """,
            (now, task["source_id"]),
        )
    if status == "completed" and task["check_method"] == "review_quiz":
        link = conn.execute(
            """
            SELECT note FROM task_progress
            WHERE daily_task_id = ? AND event_type = 'review_item'
            ORDER BY id DESC LIMIT 1
            """,
            (task_id,),
        ).fetchone()
        if link and link["note"].isdigit():
            conn.execute(
                "UPDATE review_items SET status = 'done', updated_at = ? WHERE id = ?",
                (now, int(link["note"])),
            )
    if status == "completed":
        add_reward(conn, int(task["student_id"]), 10, "小测通过", f"{task['title']} 小测 {correct}/{total}")
    conn.execute(
        "INSERT INTO task_progress (daily_task_id, event_type, note, created_at) VALUES (?, 'check', ?, ?)",
        (task_id, f"小测 {correct}/{total}", now),
    )
    return {
        "task_id": task_id,
        "total": total,
        "correct": correct,
        "status": status,
        "wrong_items": wrong_items,
    }
