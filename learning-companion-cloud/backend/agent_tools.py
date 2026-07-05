from __future__ import annotations

from datetime import datetime, timedelta, timezone
from sqlite3 import Connection
from typing import Any
import uuid

from .db import dumps, loads, utc_now


def log_agent_run(
    conn: Connection,
    student_id: int,
    run_type: str,
    input_data: dict[str, Any],
    output_data: dict[str, Any] | list[Any],
    model: str = "rule",
    status: str = "ok",
    error: str = "",
) -> int:
    trace_id = uuid.uuid4().hex
    cursor = conn.execute(
        """
        INSERT INTO agent_runs (
            student_id, run_type, input_json, output_json, model, status, error,
            confidence, evidence_json, warnings_json, latency_ms, quality_score, trace_id, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, 0.8, '[]', '[]', 0, 0.8, ?, ?)
        """,
        (student_id, run_type, dumps(input_data), dumps(output_data), model, status, error, trace_id, utc_now()),
    )
    run_id = int(cursor.lastrowid)
    conn.execute(
        """
        INSERT INTO agent_trace_steps (
            run_id, trace_id, step_index, step_type, tool_name,
            args_json, observation_json, validation_json, latency_ms, status, created_at
        )
        VALUES (?, ?, 1, 'execute', ?, ?, ?, ?, 0, ?, ?)
        """,
        (
            run_id,
            trace_id,
            run_type,
            dumps(input_data),
            dumps({"output_preview": output_data if isinstance(output_data, dict) else {"items": len(output_data)}}),
            dumps({"status": status, "error": error}),
            status,
            utc_now(),
        ),
    )
    return run_id


def save_learning_plan(conn: Connection, student_id: int, raw_goal: str, parsed: dict[str, Any]) -> int:
    now = utc_now()
    cursor = conn.execute(
        """
        INSERT INTO learning_plans (student_id, raw_goal, parsed_json, status, created_at, updated_at)
        VALUES (?, ?, ?, 'active', ?, ?)
        """,
        (student_id, raw_goal, dumps(parsed), now, now),
    )
    return int(cursor.lastrowid)


def get_task(conn: Connection, task_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM daily_tasks WHERE id = ?", (task_id,)).fetchone()
    return dict(row) if row else None


def get_task_source(conn: Connection, source_id: int | None) -> dict[str, Any] | None:
    if not source_id:
        return None
    row = conn.execute("SELECT * FROM task_sources WHERE id = ?", (source_id,)).fetchone()
    if not row:
        return None
    data = dict(row)
    data["config"] = loads(data.pop("config_json"), {})
    return data


def save_task_guidance(
    conn: Connection,
    daily_task_id: int,
    guidance: list[str],
    completion_standard: str,
    created_by: str,
) -> None:
    conn.execute(
        """
        INSERT INTO task_guidance (daily_task_id, guidance_json, completion_standard, created_by, created_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(daily_task_id) DO UPDATE SET
            guidance_json = excluded.guidance_json,
            completion_standard = excluded.completion_standard,
            created_by = excluded.created_by,
            created_at = excluded.created_at
        """,
        (daily_task_id, dumps(guidance), completion_standard, created_by, utc_now()),
    )


def get_task_guidance(conn: Connection, daily_task_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM task_guidance WHERE daily_task_id = ?", (daily_task_id,)).fetchone()
    if not row:
        return None
    data = dict(row)
    data["guidance"] = loads(data.pop("guidance_json"), [])
    return data


def save_submissions(conn: Connection, daily_task_id: int, answers: dict[str, str]) -> None:
    now = utc_now()
    valid_item_ids = {
        int(row["id"])
        for row in conn.execute(
            "SELECT id FROM quiz_items WHERE daily_task_id = ?",
            (daily_task_id,),
        ).fetchall()
    }
    conn.execute("DELETE FROM submissions WHERE daily_task_id = ?", (daily_task_id,))
    for quiz_item_id, answer in answers.items():
        item_id = int(quiz_item_id) if str(quiz_item_id).isdigit() else None
        if item_id not in valid_item_ids:
            item_id = None
        conn.execute(
            """
            INSERT INTO submissions (daily_task_id, quiz_item_id, answer, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (daily_task_id, item_id, str(answer), now),
        )


def save_mastery_record(
    conn: Connection,
    student_id: int,
    daily_task_id: int,
    subject: str,
    knowledge_point: str,
    mastery_level: str,
    score: float,
    diagnosis: str,
    next_action: str,
) -> None:
    conn.execute(
        """
        INSERT INTO mastery_records (
            student_id, daily_task_id, subject, knowledge_point,
            mastery_level, score, diagnosis, next_action, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            student_id,
            daily_task_id,
            subject,
            knowledge_point,
            mastery_level,
            score,
            diagnosis,
            next_action,
            utc_now(),
        ),
    )


def latest_mastery(conn: Connection, student_id: int, limit: int = 20) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT mr.*, dt.title
        FROM mastery_records mr
        JOIN daily_tasks dt ON dt.id = mr.daily_task_id
        WHERE mr.student_id = ?
        ORDER BY mr.id DESC LIMIT ?
        """,
        (student_id, limit),
    ).fetchall()
    return [dict(row) for row in rows]


def agent_runs(conn: Connection, student_id: int, limit: int = 50) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM agent_runs WHERE student_id = ? ORDER BY id DESC LIMIT ?",
        (student_id, limit),
    ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        data = dict(row)
        data["input"] = loads(data.pop("input_json"), {})
        data["output"] = loads(data.pop("output_json"), {})
        data["display"] = explain_agent_run(data)
        result.append(data)
    return result


def explain_agent_run(run: dict[str, Any]) -> dict[str, Any]:
    run_type = str(run.get("run_type") or "")
    output = run.get("output") if isinstance(run.get("output"), dict) else {}
    input_data = run.get("input") if isinstance(run.get("input"), dict) else {}
    model = run.get("model") or "rule"
    status = run.get("status") or "ok"
    title_map = {
        "plan": "理解学习目标并生成长期计划",
        "daily_tasks": "生成今日学习任务",
        "task_guidance": "生成任务学习步骤",
        "quiz": "生成小测题",
        "grade": "批改小测并判断是否通过",
        "diagnose": "诊断掌握度与薄弱点",
        "stuck_assist": "孩子卡住时给出针对性辅导",
        "daily_report": "生成当天学习结论",
    }
    title = title_map.get(run_type, f"执行 {run_type}")
    reason = "根据任务状态、资料库、错题/卡点和 95+ 目标自动触发。"
    result = "已完成。"
    impact = "用于后续任务安排、复习和家长查看。"
    metrics: list[dict[str, str]] = []
    next_action = ""

    if run_type == "plan":
        created = int(output.get("created") or 0)
        items = output.get("items") or []
        result = f"识别出 {created} 条长期学习计划。"
        if items:
            names = "；".join(str(item.get("title", "")) for item in items[:3] if isinstance(item, dict))
            impact = f"后续会按这些计划生成每日任务：{names}"
        reason = "家长输入了学习目标，Agent 把自然语言拆成可执行的任务源。"
        metrics = [{"label": "计划数", "value": str(created)}]
        next_action = "点击“生成今日任务”，让计划落到今天。"
    elif run_type == "daily_tasks":
        count = int(output.get("count") or len(output.get("tasks") or []))
        tasks = output.get("tasks") or []
        result = f"生成 {count} 个今日任务。"
        if tasks:
            impact = "孩子端会按科学时间段展示这些任务。"
            first_task = tasks[0] if isinstance(tasks[0], dict) else {}
            next_action = f"孩子端从「{first_task.get('title', '第一个任务')}」开始。"
        reason = "综合长期计划、复习任务、未完成项和每日时长限制。"
        metrics = [{"label": "今日任务", "value": str(count)}]
    elif run_type == "task_guidance":
        guidance = output.get("guidance") or []
        result = f"生成 {len(guidance)} 步学习指引。"
        reason = "孩子开始任务前，需要知道先学什么、怎么练、怎样算完成。"
        impact = "孩子端任务卡会展示具体学习步骤。"
        metrics = [{"label": "步骤数", "value": str(len(guidance))}]
    elif run_type == "quiz":
        items = output.get("items") or []
        quality = output.get("quality") or {}
        score = quality.get("score")
        result = f"生成 {len(items)} 道小测题。"
        if score is not None:
            metrics = [{"label": "题目数", "value": str(len(items))}, {"label": "质量分", "value": f"{float(score):.2f}"}]
        else:
            metrics = [{"label": "题目数", "value": str(len(items))}]
        reason = "任务进入检查阶段，需要用小测验证是否真的学会。"
        impact = "题目不会在孩子端暴露答案；批改后进入掌握度和复习闭环。"
        next_action = "孩子提交答案后，系统会给出是否通过和错因。"
    elif run_type == "grade":
        total = int(output.get("total") or 0)
        correct = int(output.get("correct") or 0)
        passed = output.get("status") in {"passed", "completed"}
        result = f"批改结果：{correct}/{total}，{'通过' if passed else '需要订正'}。"
        reason = "孩子提交了小测答案，Agent 用标准答案和规则进行批改。"
        impact = "未掌握内容会进入错题、掌握度和间隔复习。"
        metrics = [{"label": "正确率", "value": f"{round(correct / total * 100) if total else 0}%"}]
        next_action = "未通过则先订正并复测，通过后再进入下一个任务。"
    elif run_type == "diagnose":
        level = output.get("mastery_level") or "-"
        diagnosis = output.get("diagnosis") or "已记录掌握情况。"
        result = f"掌握等级：{level}。"
        reason = "根据小测得分、错题类型和任务知识点判断掌握度。"
        impact = diagnosis
        next_action = output.get("next_action") or "按系统建议安排补漏。"
        metrics = [{"label": "掌握等级", "value": str(level)}]
    elif run_type == "stuck_assist":
        assistance = output.get("assistance") or {}
        focus = assistance.get("review_focus") or "当前卡点"
        result = f"定位卡点：{focus}。"
        reason = f"孩子反馈：{input_data.get('note') or output.get('child_note') or '未填写具体卡点'}"
        impact = assistance.get("likely_blocker") or "系统已给出分步提示，并把卡点纳入后续补漏。"
        next_action = assistance.get("try_again") or "孩子学会后点“我会了，继续学”。"
        metrics = [{"label": "提示步数", "value": str(len(assistance.get("steps") or []))}]
    elif run_type == "daily_report":
        result = output.get("summary") or "已生成当天报告。"
        reason = "当天学习结束后，汇总任务、卡点、小测和复习建议。"
        impact = output.get("tomorrow_first_step") or "用于明天优先安排。"
        metrics = [{"label": "完成任务", "value": str(output.get("completed_tasks", "-"))}]

    severity = "ok"
    if status not in {"ok", "rule_fallback", "disabled_or_missing_key"}:
        severity = "warn"
    if run.get("error"):
        severity = "warn"

    return {
        "title": title,
        "reason": reason,
        "result": result,
        "impact": impact,
        "next_action": next_action,
        "metrics": metrics,
        "engine": "AI" if model and model != "rule" and status not in {"rule", "rule_fallback", "disabled_or_missing_key"} else "规则兜底",
        "severity": severity,
        "created_at_local": _to_local_time(str(run.get("created_at") or "")),
    }


def _to_local_time(value: str) -> str:
    if not value:
        return ""
    try:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return (parsed.astimezone(timezone(timedelta(hours=8)))).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return value
