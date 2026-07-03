from __future__ import annotations

import re
from datetime import date, timedelta
from sqlite3 import Connection
from typing import Any

from .curriculum import get_subject_units
from .db import dumps, utc_now
from .settings import get_settings


def _flatten_lessons(units: list[dict[str, Any]]) -> list[str]:
    lessons: list[str] = []
    for unit in units:
        for lesson in unit.get("lessons", []):
            lessons.append(f"{unit['unit']}：{lesson}")
    return lessons


def _deadline(default_days: int = 30) -> str:
    return (date.today() + timedelta(days=default_days)).isoformat()


def _detect_total_units(text: str, default: int) -> int:
    match = re.search(r"(\d+)\s*(节|课|篇|页|小节|单元|天)", text)
    if match:
        return int(match.group(1))
    return default


def _homework_source(text: str) -> dict[str, Any]:
    subject = ""
    for candidate in ("语文", "数学", "英语"):
        if candidate in text:
            subject = candidate
            break
    title = "寒假作业本" if "寒假" in text else "暑假作业本" if "暑假" in text else "作业本"
    return {
        "category": "summer_homework",
        "title": title if not subject else f"{subject}{title}",
        "subject": subject,
        "total_units": _detect_total_units(text, 30),
        "completed_units": 0,
        "deadline": _deadline(35),
        "config": {
            "display_label": "寒假作业" if "寒假" in text else "暑假作业" if "暑假" in text else "作业",
            "estimated_minutes": 30,
            "pacing": "每日一小节",
            "unit_label": "小节",
            "lesson_content": "按作业本顺序每日完成一小节，先独立完成，再检查订正。",
            "knowledge_points": "读题；独立完成；检查；订正",
            "study_steps": [
                "先看清今天这一小节的题目要求。",
                "独立完成会做的题，难题先做标记。",
                "完成后用 5 分钟检查计算、错别字或漏题。",
                "把不会的题写入卡点说明。",
            ],
        },
    }


def _book_source(subject: str, text: str, settings: dict[str, Any]) -> dict[str, Any]:
    region = settings.get("region", {})
    version = region.get("chinese_version") if subject == "语文" else region.get("math_version") if subject == "数学" else region.get("english_version")
    key = "chinese" if subject == "语文" else "math" if subject == "数学" else "english"
    lessons = _flatten_lessons(get_subject_units(key, version))
    unit_label = "篇课文" if subject == "语文" else "节" if subject == "数学" else "课"
    default_total = len(lessons) or 20
    return {
        "category": "preview",
        "title": f"五年级上册{subject}每日学习",
        "subject": subject,
        "total_units": _detect_total_units(text, default_total),
        "completed_units": 0,
        "deadline": _deadline(45),
        "config": {
            "estimated_minutes": 30 if subject != "数学" else 35,
            "pacing": f"每日一{unit_label}",
            "unit_label": unit_label,
            "lesson_sequence": lessons,
            "lesson_content": f"按五年级上册{subject}课本顺序每日学习一{unit_label}。",
            "knowledge_points": "课本核心知识点；当天例题/课文；易错点；复述或讲解",
            "study_steps": _study_steps(subject),
        },
    }


def _study_steps(subject: str) -> list[str]:
    if subject == "语文":
        return [
            "通读课文，圈出生字词和不理解的句子。",
            "用 2-3 句话概括主要内容。",
            "找 1 个关键句，说明它好在哪里。",
            "完成一段仿写或口头复述。",
        ]
    if subject == "数学":
        return [
            "先看课本例题，讲清每一步为什么这样做。",
            "独立完成 3 道基础题。",
            "完成 1 道应用题或变式题。",
            "整理一个易错点。",
        ]
    return [
        "听读或朗读本课单词和句子。",
        "抄写并记住 3-5 个关键词。",
        "用本课句型说或写 2 个短句。",
        "标记不会读或不会用的词。",
    ]


def generate_plan_from_text(conn: Connection, raw_text: str, student_id: int = 1) -> dict[str, Any]:
    settings = get_settings(conn)
    chunks = [chunk.strip() for chunk in re.split(r"[;\n；。]", raw_text) if chunk.strip()]
    now = utc_now()
    created: list[dict[str, Any]] = []
    for chunk in chunks:
        source: dict[str, Any] | None = None
        if "作业" in chunk or "作业本" in chunk:
            source = _homework_source(chunk)
        elif "语文书" in chunk or ("语文" in chunk and ("每日" in chunk or "课文" in chunk)):
            source = _book_source("语文", chunk, settings)
        elif "数学书" in chunk or ("数学" in chunk and ("每日" in chunk or "一节" in chunk)):
            source = _book_source("数学", chunk, settings)
        elif "英语书" in chunk or ("英语" in chunk and ("每日" in chunk or "一课" in chunk)):
            source = _book_source("英语", chunk, settings)
        if not source:
            continue
        cursor = conn.execute(
            """
            INSERT INTO task_sources (
                student_id, category, title, subject, total_units, completed_units,
                deadline, config_json, status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
            """,
            (
                student_id,
                source["category"],
                source["title"],
                source["subject"],
                source["total_units"],
                source["completed_units"],
                source["deadline"],
                dumps(source["config"]),
                now,
                now,
            ),
        )
        source["id"] = cursor.lastrowid
        created.append(source)
    return {"created": len(created), "items": created}
