from __future__ import annotations

from datetime import date, datetime, timedelta
from sqlite3 import Connection
from typing import Any

from .db import loads
from .settings import get_settings


def _date_range(end_date: str, days: int) -> tuple[str, str]:
    try:
        end = datetime.strptime(end_date, "%Y-%m-%d").date()
    except ValueError:
        end = date.today()
    start = end - timedelta(days=max(days - 1, 0))
    return start.isoformat(), end.isoformat()


def _source_material_count(conn: Connection, student_id: int, source_id: int | None, subject: str) -> int:
    if source_id:
        row = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM learning_materials
            WHERE student_id = ? AND source_id = ?
              AND (content_text != '' OR file_path != '')
            """,
            (student_id, source_id),
        ).fetchone()
        if row and int(row["count"]) > 0:
            return int(row["count"])
    row = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM learning_materials
        WHERE student_id = ?
          AND (? = '' OR subject = ?)
          AND (content_text != '' OR file_path != '')
        """,
        (student_id, subject, subject),
    ).fetchone()
    return int(row["count"] if row else 0)


def _task_subject(task: dict[str, Any]) -> str:
    text = f"{task.get('title', '')} {task.get('description', '')}"
    if "KET" in text:
        return "英语"
    if any(word in text for word in ("英语", "Unit", "单词")):
        return "英语"
    if any(word in text for word in ("数学", "小数", "口算", "计算", "面积")):
        return "数学"
    if any(word in text for word in ("语文", "阅读", "诵读", "妙笔", "一本", "课文")):
        return "语文"
    return ""


def material_trust_guard(conn: Connection, student_id: int = 1, target_date: str | None = None) -> dict[str, Any]:
    today = target_date or date.today().isoformat()
    rows = conn.execute(
        """
        SELECT dt.*, ts.category, ts.config_json
        FROM daily_tasks dt
        LEFT JOIN task_sources ts ON ts.id = dt.source_id
        WHERE dt.student_id = ? AND dt.date = ?
        ORDER BY CASE WHEN dt.sort_order = 0 THEN 999999 ELSE dt.sort_order END, dt.id
        """,
        (student_id, today),
    ).fetchall()
    items: list[dict[str, Any]] = []
    counts = {"precise": 0, "semi": 0, "temporary": 0}
    for row in rows:
        task = dict(row)
        subject = _task_subject(task)
        material_count = _source_material_count(conn, student_id, task.get("source_id"), subject)
        if material_count and task.get("source_id"):
            level = "precise"
            reason = "已绑定任务源资料，可按书本/资料出题。"
        elif material_count:
            level = "semi"
            reason = "有同科资料或知识覆盖，但未精确到本任务页码。"
        else:
            level = "temporary"
            reason = "未绑定真实教材/书本/作业资料，只能按临时计划执行。"
        counts[level] += 1
        items.append(
            {
                "task_id": task.get("id"),
                "title": task.get("title"),
                "subject": subject or "综合",
                "trust_level": level,
                "material_count": material_count,
                "reason": reason,
            }
        )
    total = max(len(items), 1)
    precise_ratio = counts["precise"] / total
    temporary_ratio = counts["temporary"] / total
    if temporary_ratio >= 0.5:
        status = "warn"
        headline = "不少任务仍是临时计划，建议尽快补教材/书本资料。"
    elif precise_ratio >= 0.6:
        status = "ok"
        headline = "多数任务已有资料证据，可以进入更精准学习。"
    else:
        status = "watch"
        headline = "资料证据部分具备，还需要继续补页码/单元。"
    return {"status": status, "headline": headline, "counts": counts, "items": items}


def workload_guard(conn: Connection, student_id: int = 1, target_date: str | None = None) -> dict[str, Any]:
    today = target_date or date.today().isoformat()
    settings = get_settings(conn)
    max_minutes = int(settings.get("daily_limits", {}).get("max_total_minutes") or 120)
    rows = conn.execute(
        "SELECT title, estimated_minutes, status FROM daily_tasks WHERE student_id = ? AND date = ?",
        (student_id, today),
    ).fetchall()
    total_minutes = sum(int(row["estimated_minutes"] or 0) for row in rows)
    remaining_minutes = sum(int(row["estimated_minutes"] or 0) for row in rows if row["status"] != "completed")
    if total_minutes > max_minutes * 1.15:
        status = "danger"
        action = "今天偏重，优先替换/延期低优先级任务，不建议继续新增。"
    elif total_minutes > max_minutes:
        status = "warn"
        action = "今天略重，建议只替换任务，不叠加任务。"
    else:
        status = "ok"
        action = "今日负荷正常，保持按当前节奏推进。"
    return {
        "status": status,
        "headline": action,
        "total_minutes": total_minutes,
        "remaining_minutes": remaining_minutes,
        "max_minutes": max_minutes,
        "action": action,
        "task_count": len(rows),
    }


def calibration_guard(conn: Connection, student_id: int = 1, target_date: str | None = None) -> dict[str, Any]:
    today = target_date or date.today().isoformat()
    start, end = _date_range(today, 3)
    task_rows = conn.execute(
        """
        SELECT date, status, estimated_minutes
        FROM daily_tasks
        WHERE student_id = ? AND date BETWEEN ? AND ?
        """,
        (student_id, start, end),
    ).fetchall()
    quiz_rows = conn.execute(
        """
        SELECT qr.correct, qr.total, qr.status
        FROM quiz_results qr
        JOIN daily_tasks dt ON dt.id = qr.daily_task_id
        WHERE dt.student_id = ? AND dt.date BETWEEN ? AND ? AND qr.total > 0
        """,
        (student_id, start, end),
    ).fetchall()
    days = {row["date"] for row in task_rows}
    total_tasks = len(task_rows)
    completed = sum(1 for row in task_rows if row["status"] == "completed")
    stuck_or_revision = sum(1 for row in task_rows if row["status"] in {"stuck", "needs_revision", "checking"})
    quiz_pass = sum(1 for row in quiz_rows if row["status"] == "completed")
    quiz_total = len(quiz_rows)
    if len(days) < 3:
        status = "initial"
        headline = "真实使用未满 3 天，暂时只能算初始计划。"
    elif stuck_or_revision >= 2 or (quiz_total and quiz_pass / quiz_total < 0.75):
        status = "needs_adjustment"
        headline = "近 3 天有明显卡点/小测未稳，建议先补救再加新任务。"
    elif total_tasks and completed / total_tasks >= 0.85:
        status = "stable"
        headline = "近 3 天执行稳定，可以微调难度或继续观察。"
    else:
        status = "watch"
        headline = "近 3 天数据一般，建议观察耗时和错因。"
    return {
        "status": status,
        "headline": headline,
        "window": {"start": start, "end": end, "days_with_data": len(days)},
        "task_completion_rate": round(completed / max(total_tasks, 1), 3),
        "quiz_pass_rate": round(quiz_pass / max(quiz_total, 1), 3) if quiz_total else None,
        "stuck_or_revision": stuck_or_revision,
    }


def review_loop_guard(conn: Connection, student_id: int = 1, target_date: str | None = None) -> dict[str, Any]:
    today = target_date or date.today().isoformat()
    rows = conn.execute(
        """
        SELECT review_stage, status, due_date, COUNT(*) AS count
        FROM review_items
        WHERE student_id = ?
        GROUP BY review_stage, status, due_date
        """,
        (student_id,),
    ).fetchall()
    by_stage = {"D1": 0, "D3": 0, "D7": 0, "other": 0}
    due_today = 0
    overdue = 0
    pending_total = 0
    for row in rows:
        count = int(row["count"])
        stage = row["review_stage"] if row["review_stage"] in by_stage else "other"
        if row["status"] in {"pending", "scheduled"}:
            by_stage[stage] += count
            pending_total += count
            if row["due_date"] <= today:
                due_today += count
            if row["due_date"] < today:
                overdue += count
    if overdue:
        status = "danger"
        headline = f"有 {overdue} 个补漏已逾期，先补救再推进新内容。"
    elif due_today:
        status = "warn"
        headline = f"今天有 {due_today} 个 D1/D3/D7 补漏要完成。"
    elif pending_total:
        status = "watch"
        headline = "复习队列正常，按到期日推进。"
    else:
        status = "ok"
        headline = "暂无待补漏项。"
    return {"status": status, "headline": headline, "by_stage": by_stage, "due_today": due_today, "overdue": overdue, "pending_total": pending_total}


def parent_intervention_guard(conn: Connection, student_id: int = 1, target_date: str | None = None) -> dict[str, Any]:
    today = target_date or date.today().isoformat()
    start, end = _date_range(today, 3)
    rows = conn.execute(
        """
        SELECT event_type, COUNT(*) AS count
        FROM notification_logs
        WHERE student_id = ?
          AND date(created_at) BETWEEN ? AND ?
          AND event_type IN ('parent_adjust', 'stuck', 'unfinished_evening', 'unfinished_rollover')
        GROUP BY event_type
        """,
        (student_id, start, end),
    ).fetchall()
    counts = {row["event_type"]: int(row["count"]) for row in rows}
    parent_adjust_count = counts.get("parent_adjust", 0)
    total_interventions = sum(counts.values())
    if parent_adjust_count >= 3 or total_interventions >= 6:
        status = "warn"
        headline = "近 3 天家长介入偏多，建议多用提问式陪跑，少直接改计划。"
    elif total_interventions:
        status = "watch"
        headline = "已有少量介入，注意不要替孩子完成思考。"
    else:
        status = "ok"
        headline = "家长介入强度正常。"
    return {"status": status, "headline": headline, "window": {"start": start, "end": end}, "counts": counts, "total_interventions": total_interventions}


def build_system_constraints(conn: Connection, student_id: int = 1, target_date: str | None = None) -> dict[str, Any]:
    today = target_date or date.today().isoformat()
    guards = {
        "material_trust": material_trust_guard(conn, student_id, today),
        "workload": workload_guard(conn, student_id, today),
        "calibration": calibration_guard(conn, student_id, today),
        "review_loop": review_loop_guard(conn, student_id, today),
        "parent_intervention": parent_intervention_guard(conn, student_id, today),
    }
    risk_order = {"ok": 0, "stable": 0, "watch": 1, "initial": 1, "warn": 2, "needs_adjustment": 2, "danger": 3}
    worst_key, worst_value = max(guards.items(), key=lambda item: risk_order.get(str(item[1].get("status")), 1))
    return {
        "date": today,
        "overall_status": worst_value.get("status", "watch"),
        "headline": worst_value.get("headline", "系统约束正常。"),
        "top_guard": worst_key,
        **guards,
    }
