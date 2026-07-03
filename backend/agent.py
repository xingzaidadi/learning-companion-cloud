from __future__ import annotations

from sqlite3 import Connection
from typing import Any

from .agent_tools import (
    agent_runs,
    get_task,
    get_task_source,
    get_task_guidance,
    latest_mastery,
    log_agent_run,
    save_learning_plan,
    save_mastery_record,
    save_submissions,
    save_task_guidance,
)
from .ai_provider import call_ai_json
from .db import loads
from .plan_generator import generate_plan_from_text
from .planner import generate_daily_tasks as rule_generate_daily_tasks
from .prompts import COMMON_GUARDRAILS, DIAGNOSIS_PROMPT, GRADE_PROMPT, PLAN_PROMPT, QUIZ_PROMPT, REPORT_PROMPT
from .quiz import ensure_quiz_for_task, grade_quiz, regenerate_quiz_for_task
from .report import build_daily_report
from .review import create_review_item
from .settings import get_settings


def generate_study_plan(conn: Connection, raw_goal: str, student_id: int = 1) -> dict[str, Any]:
    settings = get_settings(conn)
    ai_plan = call_ai_json(
        settings,
        PLAN_PROMPT.format(guardrails=COMMON_GUARDRAILS, goal=raw_goal),
        {},
    )
    rule_plan = generate_plan_from_text(conn, raw_goal, student_id)
    parsed = ai_plan if isinstance(ai_plan, dict) and ai_plan else {"rule_result": rule_plan}
    plan_id = save_learning_plan(conn, student_id, raw_goal, parsed)
    output = {"plan_id": plan_id, **rule_plan, "agent_parsed": parsed}
    log_agent_run(conn, student_id, "plan", {"goal": raw_goal}, output, _model_name(settings))
    return output


def generate_daily_tasks(conn: Connection, student_id: int = 1, target_date: str | None = None) -> dict[str, Any]:
    tasks = rule_generate_daily_tasks(conn, student_id, target_date)
    for task in tasks:
        ensure_task_guidance(conn, task["id"])
    output = {"count": len(tasks), "tasks": tasks}
    log_agent_run(conn, student_id, "daily_tasks", {"target_date": target_date}, output)
    return output


def ensure_task_guidance(conn: Connection, task_id: int) -> dict[str, Any]:
    existing = get_task_guidance(conn, task_id)
    if existing:
        return existing
    task = get_task(conn, task_id)
    if not task:
        return {"guidance": []}
    source = get_task_source(conn, task.get("source_id"))
    config = source.get("config", {}) if source else {}
    guidance = config.get("study_steps") or _fallback_guidance(task)
    save_task_guidance(conn, task_id, guidance, task.get("completion_standard", ""), "rule")
    output = {"task_id": task_id, "guidance": guidance, "completion_standard": task.get("completion_standard", "")}
    log_agent_run(conn, int(task["student_id"]), "task_guidance", {"task_id": task_id}, output)
    return output


def generate_quiz(conn: Connection, task_id: int, force: bool = False) -> dict[str, Any]:
    task = get_task(conn, task_id)
    if not task:
        return {"task_id": task_id, "items": []}
    items = regenerate_quiz_for_task(conn, task_id) if force else ensure_quiz_for_task(conn, task)
    output = {"task_id": task_id, "items": [_public_quiz_item(item) for item in items]}
    log_agent_run(conn, int(task["student_id"]), "quiz", {"task_id": task_id, "force": force}, output)
    return output


def grade_submission(conn: Connection, task_id: int, answers: dict[str, str]) -> dict[str, Any]:
    task = get_task(conn, task_id)
    if not task:
        return {"task_id": task_id, "status": "not_found", "wrong_items": []}
    save_submissions(conn, task_id, answers)
    rule_result = grade_quiz(conn, task_id, answers)
    diagnosis = diagnose_learning(conn, task_id, rule_result)
    output = {**rule_result, "diagnosis": diagnosis}
    log_agent_run(conn, int(task["student_id"]), "grade", {"task_id": task_id, "answers": answers}, output)
    return output


def diagnose_learning(conn: Connection, task_id: int, quiz_result: dict[str, Any]) -> dict[str, Any]:
    task = get_task(conn, task_id)
    if not task:
        return {}
    source = get_task_source(conn, task.get("source_id"))
    subject = source.get("subject", "") if source else ""
    knowledge_point = _knowledge_point(source, task)
    score = quiz_result["correct"] / quiz_result["total"] if quiz_result.get("total") else 0
    fallback = _rule_diagnosis(score, quiz_result)
    settings = get_settings(conn)
    ai_result = call_ai_json(
        settings,
        DIAGNOSIS_PROMPT.format(
            guardrails=COMMON_GUARDRAILS,
            learning_context={
                "task": task,
                "subject": subject,
                "knowledge_point": knowledge_point,
                "quiz_result": quiz_result,
            },
        ),
        fallback,
    )
    result = ai_result if isinstance(ai_result, dict) and ai_result else fallback
    save_mastery_record(
        conn,
        int(task["student_id"]),
        task_id,
        subject,
        knowledge_point,
        result.get("mastery_level", fallback["mastery_level"]),
        float(score),
        result.get("diagnosis", fallback["diagnosis"]),
        result.get("next_action", fallback["next_action"]),
    )
    if result.get("mastery_level") in ("C", "D"):
        create_review_item(
            conn,
            int(task["student_id"]),
            task_id,
            task["title"],
            task.get("completion_standard", ""),
            result.get("diagnosis", ""),
            "mastery_low",
            1,
        )
    log_agent_run(conn, int(task["student_id"]), "diagnose", {"task_id": task_id, "quiz_result": quiz_result}, result, _model_name(settings))
    return result


def generate_daily_report(conn: Connection, student_id: int = 1, target_date: str | None = None) -> dict[str, Any]:
    report = build_daily_report(conn, student_id, target_date)
    mastery = latest_mastery(conn, student_id, 10)
    settings = get_settings(conn)
    ai_report = call_ai_json(
        settings,
        REPORT_PROMPT.format(guardrails=COMMON_GUARDRAILS, report_context={"report": report, "mastery": mastery}),
        {},
    )
    if isinstance(ai_report, dict) and ai_report:
        report.update({key: ai_report[key] for key in ("summary", "problems", "tomorrow_first_step") if key in ai_report})
    log_agent_run(conn, student_id, "daily_report", {"target_date": target_date}, report, _model_name(settings))
    return report


def get_agent_overview(conn: Connection, student_id: int = 1) -> dict[str, Any]:
    return {"mastery": latest_mastery(conn, student_id, 20), "runs": agent_runs(conn, student_id, 30)}


def _fallback_guidance(task: dict[str, Any]) -> list[str]:
    title = task.get("title", "")
    if "语文" in title:
        return ["通读课文", "圈出生字词", "概括主要内容", "找关键句说明理由"]
    if "数学" in title:
        return ["看例题", "讲清步骤", "做基础题", "整理易错点"]
    if "英语" in title or "KET" in title:
        return ["听读单词句子", "记 3-5 个关键词", "用句型造句", "标记不会的词"]
    return ["读清要求", "独立完成", "检查一遍", "标记卡点"]


def _public_quiz_item(item: dict[str, Any]) -> dict[str, Any]:
    data = dict(item)
    data["options"] = loads(data.pop("options_json", "[]"), [])
    data.pop("answer", None)
    return data


def _rule_diagnosis(score: float, quiz_result: dict[str, Any]) -> dict[str, Any]:
    if score >= 0.9:
        level = "A"
        next_action = "明天可以继续新课。"
        diagnosis = "掌握较好，能继续推进。"
    elif score >= 0.8:
        level = "B"
        next_action = "明天先短复习 10 分钟，再继续新课。"
        diagnosis = "基本掌握，但还需要巩固表达或步骤。"
    elif score >= 0.6:
        level = "C"
        next_action = "明天先补当前知识点，暂缓新课。"
        diagnosis = "部分掌握，存在明显薄弱点。"
    else:
        level = "D"
        next_action = "需要家长介入，先重讲再练。"
        diagnosis = "当前任务未掌握，需要帮助。"
    if quiz_result.get("wrong_items"):
        diagnosis += f" 错题/问题 {len(quiz_result['wrong_items'])} 个。"
    return {
        "mastery_level": level,
        "diagnosis": diagnosis,
        "next_action": next_action,
        "parent_attention": "help" if level == "D" else "watch" if level == "C" else "none",
        "new_task_allowed": level in ("A", "B"),
    }


def _knowledge_point(source: dict[str, Any] | None, task: dict[str, Any]) -> str:
    if source:
        config = source.get("config", {})
        return config.get("topic") or config.get("knowledge_points") or source.get("title", "")
    return task.get("title", "")


def _model_name(settings: dict[str, Any]) -> str:
    ai = settings.get("ai", {})
    return ai.get("model") or "rule"
