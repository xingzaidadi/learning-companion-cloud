from __future__ import annotations

import os
from datetime import date

from apscheduler.schedulers.background import BackgroundScheduler

from .db import get_conn
from .notifier import notify
from .planner import generate_daily_tasks
from .report import build_daily_report
from .review import create_review_item


def _student_id() -> int:
    return int(os.getenv("DEFAULT_STUDENT_ID", "1"))


def generate_today_job() -> None:
    with get_conn() as conn:
        tasks = generate_daily_tasks(conn, _student_id(), date.today().isoformat())
        notify(
            conn,
            _student_id(),
            "tasks_generated",
            "今日学习任务已生成",
            f"今天共有 {len(tasks)} 个任务，请从 P0 开始。",
        )


def p0_not_started_job() -> None:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT * FROM daily_tasks
            WHERE student_id = ? AND date = ? AND priority = 'P0' AND status = 'not_started'
            ORDER BY id LIMIT 1
            """,
            (_student_id(), date.today().isoformat()),
        ).fetchone()
        if row:
            notify(
                conn,
                _student_id(),
                "p0_not_started",
                "P0 任务还没开始",
                f"请提醒孩子先启动：{row['title']}",
            )


def p0_not_completed_job() -> None:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT * FROM daily_tasks
            WHERE student_id = ? AND date = ? AND priority = 'P0' AND status != 'completed'
            ORDER BY id LIMIT 1
            """,
            (_student_id(), date.today().isoformat()),
        ).fetchone()
        if row:
            notify(
                conn,
                _student_id(),
                "p0_not_completed",
                "P0 任务还没完成",
                f"建议先完成或订正：{row['title']}",
            )


def unfinished_evening_job() -> None:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM daily_tasks
            WHERE student_id = ? AND date = ? AND priority IN ('P0', 'P1') AND status != 'completed'
            ORDER BY priority, id
            """,
            (_student_id(), date.today().isoformat()),
        ).fetchall()
        if rows:
            names = "；".join(row["title"] for row in rows)
            notify(conn, _student_id(), "unfinished_evening", "今晚仍有任务未完成", names)


def rollover_unfinished_job() -> None:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM daily_tasks
            WHERE student_id = ? AND date = ? AND priority IN ('P0', 'P1') AND status != 'completed'
            ORDER BY priority, id
            """,
            (_student_id(), date.today().isoformat()),
        ).fetchall()
        for row in rows:
            exists = conn.execute(
                """
                SELECT id FROM review_items
                WHERE student_id = ? AND source_task_id = ? AND status IN ('pending', 'scheduled')
                LIMIT 1
                """,
                (_student_id(), row["id"]),
            ).fetchone()
            if not exists:
                create_review_item(
                    conn,
                    _student_id(),
                    row["id"],
                    row["title"],
                    row["completion_standard"],
                    row["description"],
                    "unfinished_rollover",
                    1,
                )
        if rows:
            notify(conn, _student_id(), "unfinished_rollover", "未完成任务已进入明日补漏", f"共 {len(rows)} 个。")


def daily_report_job() -> None:
    with get_conn() as conn:
        build_daily_report(conn, _student_id(), date.today().isoformat())


def start_scheduler() -> BackgroundScheduler | None:
    if os.getenv("ENABLE_SCHEDULER", "true").lower() not in ("1", "true", "yes", "on"):
        return None
    scheduler = BackgroundScheduler(timezone=os.getenv("TZ", "Asia/Shanghai"))
    scheduler.add_job(generate_today_job, "cron", hour=9, minute=0, id="generate_today", replace_existing=True)
    scheduler.add_job(p0_not_started_job, "cron", hour=9, minute=30, id="p0_not_started", replace_existing=True)
    scheduler.add_job(p0_not_started_job, "cron", hour=10, minute=0, id="p0_escalate", replace_existing=True)
    scheduler.add_job(p0_not_completed_job, "cron", hour=13, minute=0, id="p0_not_completed", replace_existing=True)
    scheduler.add_job(unfinished_evening_job, "cron", hour=19, minute=30, id="unfinished_evening", replace_existing=True)
    scheduler.add_job(daily_report_job, "cron", hour=20, minute=30, id="daily_report", replace_existing=True)
    scheduler.add_job(rollover_unfinished_job, "cron", hour=21, minute=0, id="unfinished_rollover", replace_existing=True)
    scheduler.start()
    return scheduler
