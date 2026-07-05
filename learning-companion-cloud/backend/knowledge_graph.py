from __future__ import annotations

import re
from sqlite3 import Connection
from typing import Any

from .agent_core import infer_skill, infer_subject
from .db import utc_now


def _points_from_text(text: str) -> list[str]:
    candidates = re.findall(r"[A-Za-z][A-Za-z ]{2,24}|[\u4e00-\u9fff]{2,12}", text)
    stop = {"学习任务", "完成标准", "今日任务", "课文", "练习", "知识点", "资料", "小学", "五年级", "上册"}
    points: list[str] = []
    for item in candidates:
        item = item.strip(" ：:，,。.；;")
        if len(item) < 2 or item in stop:
            continue
        if item not in points:
            points.append(item)
        if len(points) >= 8:
            break
    return points


def rebuild_knowledge_points(conn: Connection, student_id: int = 1) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT *
        FROM material_chunks
        WHERE student_id = ?
        ORDER BY id
        """,
        (student_id,),
    ).fetchall()
    now = utc_now()
    inserted = 0
    for row in rows:
        subject = row["subject"] or infer_subject(row["chunk_text"])
        skill = row["knowledge_type"] or infer_skill(subject, row["chunk_text"])
        for point in _points_from_text(row["chunk_text"]):
            conn.execute(
                """
                INSERT INTO knowledge_points (
                    student_id, subject, unit, lesson, section, knowledge_point, skill,
                    source_ref, difficulty, exam_weight, must_master, mastery_score,
                    confidence, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0.5, 0.5, ?, ?)
                ON CONFLICT(student_id, subject, unit, lesson, knowledge_point)
                DO UPDATE SET
                    section = excluded.section,
                    skill = excluded.skill,
                    source_ref = excluded.source_ref,
                    exam_weight = excluded.exam_weight,
                    must_master = excluded.must_master,
                    updated_at = excluded.updated_at
                """,
                (
                    student_id,
                    subject,
                    row["unit"] or "",
                    row["lesson"] or "",
                    row["section"] or "",
                    point,
                    skill,
                    row["source_ref"] or "",
                    "basic" if row["exam_weight"] != "high" else "core",
                    row["exam_weight"] or "medium",
                    int(row["must_master"] or 1),
                    now,
                    now,
                ),
            )
            inserted += 1
    return {"student_id": student_id, "source_chunks": len(rows), "upserted": inserted}


def weakest_knowledge_points(conn: Connection, student_id: int = 1, limit: int = 8) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT *
        FROM knowledge_points
        WHERE student_id = ?
        ORDER BY must_master DESC, mastery_score ASC, exam_weight DESC, updated_at DESC
        LIMIT ?
        """,
        (student_id, limit),
    ).fetchall()
    return [dict(row) for row in rows]
