from __future__ import annotations

import re
from sqlite3 import Connection
from typing import Any

from .db import dumps, utc_now


CATEGORY_ALIASES = {
    "暑假作业": "summer_homework",
    "作业": "summer_homework",
    "homework": "summer_homework",
    "预习": "preview",
    "五年级": "preview",
    "preview": "preview",
    "ket": "ket",
    "KET": "ket",
    "英语": "ket",
}


def _detect_category(text: str) -> str:
    for key, category in CATEGORY_ALIASES.items():
        if key in text:
            return category
    return "summer_homework"


def _detect_subject(text: str, category: str) -> str:
    for subject in ("数学", "语文", "英语", "科学", "阅读", "口语", "听力", "写作"):
        if subject in text:
            return "英语" if subject in ("口语", "听力", "写作") else subject
    return "英语" if category == "ket" else ""


def _first_int(text: str, default: int) -> int:
    match = re.search(r"(\d+)", text)
    return int(match.group(1)) if match else default


def _date(text: str, fallback: str | None) -> str | None:
    match = re.search(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})", text)
    if not match:
        return fallback
    return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"


def _parse_line(line: str, default_deadline: str | None) -> dict[str, Any] | None:
    text = line.strip(" -\t")
    if not text or text.startswith("#"):
        return None

    parts = [part.strip() for part in re.split(r"[|,，]", text) if part.strip()]
    if len(parts) >= 3 and parts[0] in {"summer_homework", "preview", "ket", "暑假作业", "预习", "KET", "ket"}:
        category = CATEGORY_ALIASES.get(parts[0], parts[0])
        title = parts[1]
        subject = parts[2] if len(parts) > 2 else _detect_subject(text, category)
        total_units = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else _first_int(text, 10)
        completed_units = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 0
        deadline = parts[5] if len(parts) > 5 and re.match(r"\d{4}-\d{1,2}-\d{1,2}", parts[5]) else _date(text, default_deadline)
        extra = parts[6] if len(parts) > 6 else ""
    else:
        category = _detect_category(text)
        subject = _detect_subject(text, category)
        title = re.sub(r"^\d+[.、]\s*", "", text)
        total_units = _first_int(text, 10 if category != "ket" else 20)
        completed_units = 0
        deadline = _date(text, default_deadline)
        extra = title

    estimated = 35 if category == "summer_homework" else 30 if category == "preview" else 20
    return {
        "category": category,
        "title": title[:80],
        "subject": subject,
        "total_units": max(total_units, 1),
        "completed_units": min(max(completed_units, 0), max(total_units, 1)),
        "deadline": deadline,
        "config": {
            "topic": extra if category == "preview" else "",
            "module": extra if category == "ket" else "",
            "lesson_content": extra if category == "preview" else text,
            "knowledge_points": extra,
            "vocabulary": extra if category == "ket" else "",
            "estimated_minutes": estimated,
            "raw": text,
        },
    }


def import_task_sources(
    conn: Connection,
    raw_text: str,
    student_id: int = 1,
    default_deadline: str | None = None,
) -> dict[str, Any]:
    now = utc_now()
    created = 0
    skipped = 0
    items: list[dict[str, Any]] = []
    for line in raw_text.splitlines():
        parsed = _parse_line(line, default_deadline)
        if not parsed:
            skipped += 1
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
                parsed["category"],
                parsed["title"],
                parsed["subject"],
                parsed["total_units"],
                parsed["completed_units"],
                parsed["deadline"],
                dumps(parsed["config"]),
                now,
                now,
            ),
        )
        parsed["id"] = cursor.lastrowid
        items.append(parsed)
        created += 1

    conn.execute(
        """
        INSERT INTO import_batches (student_id, raw_text, created_count, skipped_count, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (student_id, raw_text, created, skipped, now),
    )
    return {"created": created, "skipped": skipped, "items": items}
