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
    matches = re.findall(r"(\d+)\s*(?:节|课|篇|页|小节|单元|天)", text)
    if not matches:
        return default
    numbers = [int(value) for value in matches]
    useful = [value for value in numbers if value >= 6]
    return useful[0] if useful else default


def _homework_source(text: str) -> dict[str, Any]:
    subject = ""
    lowered = text.lower()
    for candidate in ("语文", "数学", "英语"):
        if candidate in text:
            subject = candidate
            break
    if not subject:
        if "math" in lowered:
            subject = "数学"
        elif "english" in lowered:
            subject = "英语"
        elif "chinese" in lowered or "reading" in lowered:
            subject = "语文"
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
    if subject == "英语" and _looks_like_fltrp_english_plan(text):
        return _fltrp_english_source(text)

    region = settings.get("region", {})
    version = (
        region.get("chinese_version")
        if subject == "语文"
        else region.get("math_version")
        if subject == "数学"
        else region.get("english_version")
    )
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


def _looks_like_fltrp_english_plan(text: str) -> bool:
    normalized = text.lower()
    return any(
        keyword in normalized
        for keyword in (
            "外研社",
            "刘兆义",
            "unit 1",
            "unit1",
            "my school is cool",
            "school activities are fun",
            "the ice world",
            "i love the sea",
            "work it out",
            "big days",
            "音频",
            "默写",
            "字帖",
        )
    )


def _fltrp_english_source(text: str) -> dict[str, Any]:
    sequence = _fltrp_english_sequence()
    return {
        "category": "preview",
        "title": "外研社刘兆义版五年级上册英语暑假预习",
        "subject": "英语",
        "total_units": len(sequence),
        "completed_units": 0,
        "deadline": _deadline(38),
        "config": {
            "display_label": "英语预习",
            "estimated_minutes": 30,
            "pacing": "每日 25–35 分钟",
            "unit_label": "天",
            "lesson_sequence": sequence,
            "lesson_content": "基于五上英语课本、Unit 1–6 单词字帖、Unit 1–6 中译英默写练习和 Unit 1–3 音频推进。",
            "knowledge_points": "听读课文；理解课文；单词认读；字帖书写；中译英默写；小测检查",
            "resources": {
                "textbook": "2026新五上定稿课本.pdf",
                "copybook": "五上单词英语字帖.pdf",
                "dictation": "单词默写练习-Unit 1 至 Unit 6",
                "audio": "Unit 1–3 已有音频；Unit 4–6 暂无音频，用课本朗读和重点句跟读替代",
            },
            "study_steps": [
                "先听音频或朗读课本 5–8 分钟，圈出不会读的词。",
                "看课本图片和 Story/活动内容，说出今天主要讲什么。",
                "认读并书写 3–6 个重点词，优先处理错词。",
                "用本课重点句型说或写 1–2 个短句。",
                "完成小测或中译英默写，低于 80% 次日先补漏。",
            ],
        },
    }


def _fltrp_english_sequence() -> list[str]:
    units = [
        ("Unit 1 My school is cool", True),
        ("Unit 2 School activities are fun!", True),
        ("Unit 3 The ice world", True),
        ("Unit 4 I love the sea!", False),
        ("Unit 5 Work it out!", False),
        ("Unit 6 Big days", False),
    ]
    sequence: list[str] = []
    for unit, has_audio in units:
        audio_step = "听音频跟读" if has_audio else "课本朗读和重点句跟读"
        sequence.extend(
            [
                f"{unit} 第1天：{audio_step}，整体理解单元主题",
                f"{unit} 第2天：Story/课文精读，理解人物、场景和主要句子",
                f"{unit} 第3天：单词认读与字帖书写，整理不会读/不会拼的词",
                f"{unit} 第4天：中译英默写练习，订正错词并复读重点句",
                f"{unit} 第5天：单元复习和小测，未达 80% 次日补漏",
            ]
        )
    return sequence


def _study_steps(subject: str) -> list[str]:
    if subject == "语文":
        return [
            "通读课文，圈出生字词和不理解的句子。",
            "用 2–3 句话概括主要内容。",
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
        "抄写并记住 3–5 个关键词。",
        "用本课句型说或写 2 个短句。",
        "标记不会读或不会用的词。",
    ]


def generate_plan_from_text(conn: Connection, raw_text: str, student_id: int = 1) -> dict[str, Any]:
    settings = get_settings(conn)
    chunks = [chunk.strip() for chunk in re.split(r"[;\n；。]", raw_text) if chunk.strip()]
    if _looks_like_english_request(raw_text):
        chunks.insert(0, raw_text.strip())

    now = utc_now()
    created: list[dict[str, Any]] = []
    created_keys: set[tuple[str, str]] = set()
    for chunk in chunks:
        source = _source_from_chunk(chunk, settings)
        if not source:
            continue
        key = (source["category"], source["subject"] or source["title"])
        if key in created_keys:
            continue
        created_keys.add(key)
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


def _source_from_chunk(chunk: str, settings: dict[str, Any]) -> dict[str, Any] | None:
    lowered = chunk.lower()
    if "作业" in chunk or "作业本" in chunk or "homework" in lowered or "workbook" in lowered:
        return _homework_source(chunk)
    if _looks_like_subject_request(chunk, "语文", extra_keywords=("课文", "语文书")) or _looks_like_english_alias_request(lowered, ("chinese", "reading"), ("book", "textbook", "daily", "preview", "lesson")):
        return _book_source("语文", chunk, settings)
    if _looks_like_subject_request(chunk, "数学", extra_keywords=("一节", "数学书", "例题")) or _looks_like_english_alias_request(lowered, ("math", "mathematics"), ("book", "textbook", "daily", "preview", "lesson", "decimal")):
        return _book_source("数学", chunk, settings)
    if _looks_like_english_request(chunk):
        return _book_source("英语", chunk, settings)
    return None


def _looks_like_english_alias_request(lowered: str, subjects: tuple[str, ...], intent_words: tuple[str, ...]) -> bool:
    return any(subject in lowered for subject in subjects) and any(word in lowered for word in intent_words)


def _looks_like_subject_request(text: str, subject: str, extra_keywords: tuple[str, ...]) -> bool:
    if subject not in text:
        return False
    pacing_words = ("每日", "每天", "预习", "学习", "暑假", "寒假", "一篇", "一节", "一课")
    return any(word in text for word in pacing_words + extra_keywords)


def _looks_like_english_request(text: str) -> bool:
    if not any(keyword in text for keyword in ("英语", "English", "Unit", "外研社", "刘兆义")):
        return False
    return any(
        keyword in text
        for keyword in (
            "每日",
            "每天",
            "预习",
            "学习",
            "暑假",
            "一课",
            "课本",
            "音频",
            "默写",
            "字帖",
            "Unit",
        )
    )
