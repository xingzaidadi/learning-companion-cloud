from __future__ import annotations

from datetime import date
from sqlite3 import Connection
from typing import Any

from .db import dumps, loads, utc_now
from .settings import get_settings, save_settings
from .study_schedule import arrange_daily_schedule


ADJUSTABLE_STATUSES = ("not_started", "paused")


def _today(target_date: str | None = None) -> str:
    return target_date or date.today().isoformat()


def _ket_recent_results(conn: Connection, student_id: int, limit: int = 5) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT qr.correct, qr.total, qr.status, dt.estimated_minutes, dt.title
        FROM quiz_results qr
        JOIN daily_tasks dt ON dt.id = qr.daily_task_id
        JOIN task_sources ts ON ts.id = dt.source_id
        WHERE dt.student_id = ? AND ts.category = 'ket' AND qr.total > 0
        ORDER BY qr.id DESC
        LIMIT ?
        """,
        (student_id, limit),
    ).fetchall()
    return [dict(row) for row in rows]


def ket_difficulty_suggestion(conn: Connection, student_id: int = 1) -> dict[str, Any]:
    settings = get_settings(conn)
    ket_plan = settings.get("ket_plan", {})
    current_level = str(ket_plan.get("level") or "standard")
    pass_score = float(settings.get("path_rules", {}).get("quiz_pass_score", 0.8))
    results = _ket_recent_results(conn, student_id, 5)
    if len(results) < 3:
        return {
            "level": current_level,
            "suggested_level": current_level,
            "confidence": 0.35,
            "reason": "KET 小测样本还不够，先按当前难度观察 3 次以上。",
            "action": "keep",
        }
    ratios = [int(row["correct"]) / max(int(row["total"]), 1) for row in results]
    avg_ratio = sum(ratios) / len(ratios)
    passed = sum(1 for ratio in ratios if ratio >= pass_score)
    failed = len(ratios) - passed
    if passed >= 4 and avg_ratio >= 0.92 and current_level != "advanced":
        return {
            "level": current_level,
            "suggested_level": "advanced",
            "confidence": 0.82,
            "reason": "最近 KET 通过率高，可以升到进阶模式，增加阅读/写作/口语挑战。",
            "action": "increase",
            "avg_score": round(avg_ratio, 3),
        }
    if failed >= 2 and current_level != "light":
        return {
            "level": current_level,
            "suggested_level": "light",
            "confidence": 0.78,
            "reason": "最近 KET 有多次未过关，建议临时降强度，先补错词和错题。",
            "action": "decrease",
            "avg_score": round(avg_ratio, 3),
        }
    return {
        "level": current_level,
        "suggested_level": current_level,
        "confidence": 0.7,
        "reason": "KET 难度与当前表现基本匹配，继续按当前节奏推进。",
        "action": "keep",
        "avg_score": round(avg_ratio, 3),
    }


def apply_ket_level(conn: Connection, level: str, student_id: int = 1) -> dict[str, Any]:
    normalized = level if level in {"light", "standard", "advanced"} else "standard"
    settings = get_settings(conn)
    ket_plan = dict(settings.get("ket_plan", {}))
    ket_plan["level"] = normalized
    if normalized == "light":
        ket_plan["weekday_minutes"] = min(int(ket_plan.get("weekday_minutes") or 35), 25)
        ket_plan["mock_minutes"] = min(int(ket_plan.get("mock_minutes") or 60), 45)
    elif normalized == "advanced":
        ket_plan["weekday_minutes"] = max(int(ket_plan.get("weekday_minutes") or 35), 45)
        ket_plan["mock_minutes"] = max(int(ket_plan.get("mock_minutes") or 60), 75)
    else:
        ket_plan["weekday_minutes"] = 35
        ket_plan["mock_minutes"] = 60
    updated = save_settings(conn, {"ket_plan": ket_plan, "daily_limits": {"ket_minutes": ket_plan["weekday_minutes"]}})
    return {"status": "updated", "ket_plan": updated.get("ket_plan", {}), "student_id": student_id}


def _task_subject(title: str, description: str = "") -> str:
    text = f"{title} {description}"
    if any(word in text for word in ("运动", "体育", "跳绳", "拉伸")):
        return "体育"
    if "KET" in text:
        return "KET"
    if any(word in text for word in ("英语", "Unit", "单词")):
        return "英语"
    if any(word in text for word in ("数学", "小数", "口算", "计算", "面积")):
        return "数学"
    if any(word in text for word in ("语文", "阅读", "诵读", "妙笔", "一本", "课文")):
        return "语文"
    return "综合"


def _adjust_minutes(conn: Connection, task_id: int, minutes: int, reason: str) -> None:
    conn.execute(
        """
        UPDATE daily_tasks
        SET estimated_minutes = ?, schedule_reason = ?, updated_at = datetime('now')
        WHERE id = ?
        """,
        (max(10, minutes), reason, task_id),
    )


def adjust_today_plan(conn: Connection, student_id: int = 1, target_date: str | None = None, mode: str = "rebalance") -> dict[str, Any]:
    today = _today(target_date)
    rows = conn.execute(
        """
        SELECT * FROM daily_tasks
        WHERE student_id = ? AND date = ?
        ORDER BY CASE WHEN sort_order = 0 THEN 999999 ELSE sort_order END, priority, id
        """,
        (student_id, today),
    ).fetchall()
    changed: list[str] = []
    now = utc_now()
    mode = mode if mode in {"rebalance", "lighter", "harder", "catch_up"} else "rebalance"
    for row in rows:
        status = str(row["status"])
        title = str(row["title"])
        subject = _task_subject(title, str(row["description"]))
        minutes = int(row["estimated_minutes"] or 20)
        if mode == "lighter" and status in ADJUSTABLE_STATUSES:
            if subject in {"KET", "英语", "数学", "语文"}:
                new_minutes = max(15, int(minutes * 0.8))
                _adjust_minutes(conn, int(row["id"]), new_minutes, "家长选择今天轻松一点；系统压缩未开始任务时长。")
                changed.append(f"{title} {minutes}->{new_minutes} 分钟")
        elif mode == "harder" and status in ADJUSTABLE_STATUSES:
            if subject in {"KET", "英语"}:
                new_minutes = min(60, minutes + 10)
                _adjust_minutes(conn, int(row["id"]), new_minutes, "家长选择加一点挑战；系统增加英语/KET任务时长。")
                changed.append(f"{title} {minutes}->{new_minutes} 分钟")
        elif mode == "catch_up" and status in {"stuck", "needs_revision", "checking"}:
            conn.execute(
                """
                UPDATE daily_tasks
                SET priority = 'P0', sort_order = 5, schedule_reason = ?, updated_at = ?
                WHERE id = ?
                """,
                ("家长选择先补救；卡住/订正任务置顶。", now, int(row["id"])),
            )
            changed.append(f"{title} 已置顶补救")
    tasks = arrange_daily_schedule(conn, student_id, today, respect_existing_order=(mode == "catch_up"))
    return {
        "date": today,
        "mode": mode,
        "changed": changed,
        "count": len(tasks),
        "message": "已动态重排今天时间。" if changed or mode == "rebalance" else "当前没有需要调整的未完成任务。",
        "tasks": [dict(task) for task in tasks],
    }


def auto_adjust_after_event(conn: Connection, task_id: int, event_type: str) -> dict[str, Any]:
    task = conn.execute("SELECT * FROM daily_tasks WHERE id = ?", (task_id,)).fetchone()
    if not task:
        return {"applied": False, "reason": "task_missing"}
    if event_type == "stuck":
        result = adjust_today_plan(conn, int(task["student_id"]), task["date"], "catch_up")
        return {"applied": True, "mode": "catch_up", "message": result["message"]}
    if event_type in {"pause", "complete"}:
        result = adjust_today_plan(conn, int(task["student_id"]), task["date"], "rebalance")
        return {"applied": True, "mode": "rebalance", "message": result["message"]}
    return {"applied": False, "reason": "no_adjustment_needed"}
