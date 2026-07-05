from __future__ import annotations

from sqlite3 import Connection
from typing import Any

from .db import loads
from .knowledge_graph import weakest_knowledge_points


def build_dynamic_strategy(conn: Connection, student_id: int = 1, target_date: str = "") -> dict[str, Any]:
    weak_points = weakest_knowledge_points(conn, student_id, 6)
    stuck_count = conn.execute(
        """
        SELECT COUNT(*)
        FROM daily_tasks dt
        JOIN task_progress tp ON tp.daily_task_id = dt.id
        WHERE dt.student_id = ? AND (? = '' OR dt.date = ?) AND tp.event_type = 'stuck'
        """,
        (student_id, target_date, target_date),
    ).fetchone()[0]
    latest_results = [
        dict(row)
        for row in conn.execute(
            """
            SELECT qr.*
            FROM quiz_results qr
            JOIN daily_tasks dt ON dt.id = qr.daily_task_id
            WHERE dt.student_id = ?
            ORDER BY qr.id DESC
            LIMIT 8
            """,
            (student_id,),
        ).fetchall()
    ]
    low_scores = [row for row in latest_results if row["total"] and row["correct"] / row["total"] < 0.8]
    should_slow_down = bool(low_scores) or stuck_count >= 2
    actions = []
    for point in weak_points[:3]:
        actions.append(
            {
                "subject": point["subject"],
                "knowledge_point": point["knowledge_point"],
                "skill": point["skill"],
                "action": f"先补 {point['subject']}「{point['knowledge_point']}」再推进新课",
                "reason": "该知识点掌握度或置信度较低，影响 95+ 目标。",
            }
        )
    return {
        "target_date": target_date,
        "strategy": "remediate_first" if should_slow_down else "balanced_new_and_review",
        "mode": "补漏优先" if should_slow_down else "新课+补漏均衡",
        "should_slow_down": should_slow_down,
        "stuck_count_today": stuck_count,
        "recent_low_score_count": len(low_scores),
        "weak_points": weak_points,
        "actions": actions,
        "recommended_actions": actions,
        "rules": [
            "小测低于 80%：第二天先补漏再推进新课。",
            "同一任务卡住 2 次以上：降低难度并安排微练习。",
            "D1/D3/D7/D14 复习优先进入上午时段。",
        ],
    }


def quiz_result_to_review_plan(result: dict[str, Any]) -> dict[str, Any]:
    wrong_items = result.get("wrong_items", [])
    if isinstance(wrong_items, str):
        wrong_items = loads(wrong_items, [])
    return {
        "review_stages": ["D1", "D3", "D7", "D14"],
        "wrong_count": len(wrong_items or []),
        "next_action": "错题进入 D1/D3/D7/D14 间隔复习，复测通过后再推进同类新题。",
    }
