from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from sqlite3 import Connection
from typing import Any

from .db import BASE_DIR, dumps, loads, utc_now
from .notifier import notify
from .rewards import add_reward
from .review import create_review_item


DONE_STATUSES = ("completed",)
PROBLEM_STATUSES = ("stuck", "needs_revision")
REPORTS_DIR = BASE_DIR / "reports"
DAILY_DIR = REPORTS_DIR / "daily"
WEEKLY_DIR = REPORTS_DIR / "weekly"


def _ensure_review_for_problem(conn: Connection, task: dict[str, Any], reason: str) -> None:
    exists = conn.execute(
        """
        SELECT id FROM review_items
        WHERE student_id = ? AND source_task_id = ? AND status IN ('pending', 'scheduled')
        LIMIT 1
        """,
        (task["student_id"], task["id"]),
    ).fetchone()
    if exists:
        return
    create_review_item(
        conn,
        int(task["student_id"]),
        int(task["id"]),
        task["title"],
        task.get("completion_standard", ""),
        task.get("description", ""),
        reason,
        1,
    )


def _write_daily_markdown(report: dict[str, Any], tasks: list[dict[str, Any]]) -> str:
    DAILY_DIR.mkdir(parents=True, exist_ok=True)
    path = DAILY_DIR / f"{report['date']}.md"
    lines = [
        f"# 学习日报 {report['date']}",
        "",
        f"- 完成情况：{report['completed_count']} / {report['total_count']}",
        f"- 总结：{report['summary']}",
        f"- 问题：{report['problems']}",
        f"- 明天第一步：{report['tomorrow_first_step']}",
        f"- 最薄弱点：{report.get('weakest_point', '暂无')}",
        f"- 家长是否介入：{report.get('parent_attention', '暂不需要')}",
        f"- 10 分钟陪伴建议：{report.get('ten_minute_action', '听孩子复述今天学会了什么')}",
        "",
        "## 今日任务",
    ]
    for task in tasks:
        lines.append(f"- [{task['status']}] {task['priority']} {task['title']}（{task['estimated_minutes']} 分钟）")
    lines.extend(["", "## 小测结果"])
    if report["quiz_results"]:
        for result in report["quiz_results"]:
            error_text = "、".join(f"{key}×{value}" for key, value in result.get("error_types", {}).items()) or "无错因"
            lines.append(f"- {result['title']}：{result['correct']}/{result['total']}（{result['status']}，{error_text}）")
    else:
        lines.append("- 暂无小测记录")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


def build_daily_report(conn: Connection, student_id: int = 1, target_date: str | None = None) -> dict[str, Any]:
    today = target_date or date.today().isoformat()
    task_rows = conn.execute(
        "SELECT * FROM daily_tasks WHERE student_id = ? AND date = ? ORDER BY priority, id",
        (student_id, today),
    ).fetchall()
    tasks = [dict(row) for row in task_rows]
    total = len(tasks)
    completed = sum(1 for task in tasks if task["status"] in DONE_STATUSES)
    unfinished = [task for task in tasks if task["status"] not in DONE_STATUSES]
    problems = [task for task in tasks if task["status"] in PROBLEM_STATUSES]

    for task in problems:
        _ensure_review_for_problem(conn, task, task["status"])

    quiz_rows = conn.execute(
        """
        SELECT qr.*, dt.title
        FROM quiz_results qr
        JOIN daily_tasks dt ON dt.id = qr.daily_task_id
        WHERE dt.student_id = ? AND dt.date = ?
        ORDER BY qr.id DESC
        """,
        (student_id, today),
    ).fetchall()
    quiz_details: list[dict[str, Any]] = []
    error_totals: dict[str, int] = {}
    failed_titles: list[str] = []
    passed_titles: list[str] = []
    for row in quiz_rows:
        detail = dict(row)
        detail["wrong_items"] = loads(row["wrong_items_json"], [])
        detail["score"] = loads(row["score_json"] if "score_json" in row.keys() else None, {})
        detail["error_types"] = loads(row["error_types_json"] if "error_types_json" in row.keys() else None, {})
        detail["mastery"] = loads(row["mastery_json"] if "mastery_json" in row.keys() else None, {})
        quiz_details.append(detail)
        if detail["status"] == "completed":
            passed_titles.append(detail["title"])
        else:
            failed_titles.append(detail["title"])
        for key, value in detail["error_types"].items():
            error_totals[key] = error_totals.get(key, 0) + int(value)
    quiz_summary = [f"{row['title']}：{row['correct']}/{row['total']}" for row in quiz_rows]

    summary = f"今日完成 {completed}/{total}。"
    if quiz_summary:
        summary += " 小测：" + "；".join(quiz_summary[:5]) + "。"
    weakest_point = max(error_totals.items(), key=lambda item: item[1])[0] if error_totals else "暂无明显薄弱点"
    error_text = "；".join(f"{key}×{value}" for key, value in error_totals.items())
    problem_parts = [task["title"] for task in problems]
    if error_text:
        problem_parts.append(f"错因：{error_text}")
    problem_text = "；".join(problem_parts) if problem_parts else "暂无明显卡点。"
    if unfinished:
        tomorrow_first_step = f"先完成或订正：{unfinished[0]['title']}"
    elif failed_titles:
        tomorrow_first_step = f"先补漏：{failed_titles[0]}"
    elif error_totals:
        tomorrow_first_step = f"先做 10 分钟{weakest_point}复盘。"
    else:
        tomorrow_first_step = "先从新的 P0 任务开始，保持短时专注。"
        if total:
            add_reward(conn, student_id, 20, "今日全清", "今日任务全部完成", today)
    if error_totals or problems:
        parent_attention = "需要介入"
        ten_minute_action = f"用 10 分钟陪孩子订正「{weakest_point}」，让孩子说出错因和改法。"
    elif completed == total and total:
        parent_attention = "暂不需要"
        ten_minute_action = "听孩子用 2 分钟复述今天最有把握的一点，再鼓励收尾。"
    else:
        parent_attention = "轻度关注"
        ten_minute_action = "只确认是否开始、是否知道第一步，不直接代做。"
    if quiz_details:
        summary += f" 通过项：{('、'.join(passed_titles[:3]) or '暂无')}；需补漏：{('、'.join(failed_titles[:3]) or '暂无')}。"

    now = utc_now()
    conn.execute(
        """
        INSERT INTO daily_reports (
            student_id, date, completed_count, total_count, summary,
            problems, tomorrow_first_step, weakest_point, parent_attention,
            ten_minute_action, passed_points_json, failed_points_json, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(student_id, date) DO UPDATE SET
            completed_count = excluded.completed_count,
            total_count = excluded.total_count,
            summary = excluded.summary,
            problems = excluded.problems,
            tomorrow_first_step = excluded.tomorrow_first_step,
            weakest_point = excluded.weakest_point,
            parent_attention = excluded.parent_attention,
            ten_minute_action = excluded.ten_minute_action,
            passed_points_json = excluded.passed_points_json,
            failed_points_json = excluded.failed_points_json,
            created_at = excluded.created_at
        """,
        (
            student_id,
            today,
            completed,
            total,
            summary,
            problem_text,
            tomorrow_first_step,
            weakest_point,
            parent_attention,
            ten_minute_action,
            dumps(passed_titles),
            dumps(failed_titles),
            now,
        ),
    )
    report = {
        "student_id": student_id,
        "date": today,
        "completed_count": completed,
        "total_count": total,
        "summary": summary,
        "problems": problem_text,
        "tomorrow_first_step": tomorrow_first_step,
        "weakest_point": weakest_point,
        "passed_points": passed_titles,
        "failed_points": failed_titles,
        "parent_attention": parent_attention,
        "ten_minute_action": ten_minute_action,
        "quiz_results": quiz_details,
    }
    report["file_path"] = _write_daily_markdown(report, tasks)
    notify(
        conn,
        student_id,
        "daily_report",
        f"学习日报 {today}",
        f"{summary}\n\n问题：{problem_text}\n\n明天第一步：{tomorrow_first_step}\n\n家长建议：{ten_minute_action}",
    )
    return report


def _week_range(target_date: str | None = None) -> tuple[str, str]:
    current = datetime.strptime(target_date or date.today().isoformat(), "%Y-%m-%d").date()
    start = current - timedelta(days=current.weekday())
    end = start + timedelta(days=6)
    return start.isoformat(), end.isoformat()


def _write_weekly_markdown(report: dict[str, Any], daily_rows: list[dict[str, Any]]) -> str:
    WEEKLY_DIR.mkdir(parents=True, exist_ok=True)
    path = WEEKLY_DIR / f"{report['week_start']}_{report['week_end']}.md"
    lines = [
        f"# 学习周报 {report['week_start']} 至 {report['week_end']}",
        "",
        f"- 总结：{report['summary']}",
        f"- 问题：{report['problems']}",
        f"- 下周重点：{report['next_week_focus']}",
        "",
        "## 每日记录",
    ]
    if daily_rows:
        for row in daily_rows:
            lines.append(f"- {row['date']}：{row['completed_count']}/{row['total_count']}，{row['problems']}")
    else:
        lines.append("- 暂无日报")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


def build_weekly_report(conn: Connection, student_id: int = 1, target_date: str | None = None) -> dict[str, Any]:
    week_start, week_end = _week_range(target_date)
    daily_rows = [
        dict(row)
        for row in conn.execute(
            """
            SELECT * FROM daily_reports
            WHERE student_id = ? AND date BETWEEN ? AND ?
            ORDER BY date
            """,
            (student_id, week_start, week_end),
        ).fetchall()
    ]
    total_days = len(daily_rows)
    total_tasks = sum(row["total_count"] for row in daily_rows)
    completed_tasks = sum(row["completed_count"] for row in daily_rows)
    problem_days = [row for row in daily_rows if row["problems"] and row["problems"] != "暂无明显卡点。"]
    completion_rate = int((completed_tasks / total_tasks) * 100) if total_tasks else 0
    summary = f"本周记录 {total_days} 天，任务完成率 {completion_rate}%（{completed_tasks}/{total_tasks}）。"
    problems = "；".join(row["problems"] for row in problem_days) if problem_days else "本周暂无集中卡点。"
    trend = "有卡点需要优先补漏。" if problem_days else "整体推进稳定。"
    next_week_focus = "优先复习本周错题/卡点，再推进新任务。" if problem_days else "保持每天先完成 P0，再做 KET 短练。"
    suggestions = [
        next_week_focus,
        "每天学习结束后先做小测，低于通过线就进入第二天补漏。",
    ]
    now = utc_now()
    conn.execute(
        """
        INSERT INTO weekly_reports (
            student_id, week_start, week_end, summary, problems, next_week_focus, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(student_id, week_start) DO UPDATE SET
            week_end = excluded.week_end,
            summary = excluded.summary,
            problems = excluded.problems,
            next_week_focus = excluded.next_week_focus,
            created_at = excluded.created_at
        """,
        (student_id, week_start, week_end, summary, problems, next_week_focus, now),
    )
    report = {
        "student_id": student_id,
        "week_start": week_start,
        "week_end": week_end,
        "summary": summary,
        "problems": problems,
        "trend": trend,
        "next_week_focus": next_week_focus,
        "suggestions": suggestions,
        "daily_reports": daily_rows,
    }
    report["file_path"] = _write_weekly_markdown(report, daily_rows)
    notify(conn, student_id, "weekly_report", f"学习周报 {week_start}", f"{summary}\n\n下周重点：{next_week_focus}")
    return report
