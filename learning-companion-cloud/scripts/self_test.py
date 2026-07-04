from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
TEMP_DIR = Path(tempfile.mkdtemp(prefix="learning-companion-self-test-"))
TEMP_DB = TEMP_DIR / "learning.db"


ENGLISH_PLAN_PROMPT = """
请基于外研社/刘兆义版五年级上册英语，为孩子生成暑假英语预习计划。
教材包含 Unit 1 My school is cool、Unit 2 School activities are fun!、Unit 3 The ice world、
Unit 4 I love the sea!、Unit 5 Work it out!、Unit 6 Big days。
现有资料包括五上课本 PDF、Unit 1–6 单词字帖、Unit 1–6 中译英默写练习，以及 Unit 1–3 音频。
每天学习 25–35 分钟，每个 Unit 用 4–5 天，按听读课文、理解课文、单词认读、字帖书写、单词默写、小测检查推进。
Unit 1–3 使用音频跟读，Unit 4–6 暂无音频则用课本朗读和重点句跟读替代。
不要超五年级上册范围，不安排初中语法和竞赛题。
每天任务要包含怎么学、怎么练、怎么检查；错词、不会读、小测错误进入第二天补漏；小测低于 80% 时第二天先补漏再继续新内容。
""".strip()


def configure_env() -> None:
    os.environ["DATABASE_PATH"] = str(TEMP_DB)
    os.environ["ENABLE_SCHEDULER"] = "false"
    os.environ["AI_ENABLED"] = "false"
    os.environ["NOTIFY_CHANNEL"] = "none"
    os.environ["CHILD_PASSWORD"] = ""
    os.environ["PARENT_PASSWORD"] = ""
    os.environ["ADMIN_PASSWORD"] = ""


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def assert_status(response: Any, status_code: int = 200) -> Any:
    assert_true(response.status_code == status_code, f"{response.request.method} {response.request.url} -> {response.status_code}: {response.text[:500]}")
    if response.headers.get("content-type", "").startswith("application/json"):
        return response.json()
    return response.text


def extract_progress(html: str) -> tuple[str, str]:
    done = re.search(r'<span id="doneCount">([^<]*)</span>', html)
    total = re.search(r'<span id="totalCount">([^<]*)</span>', html)
    assert_true(done is not None and total is not None, "孩子端 HTML 缺少进度节点")
    return done.group(1), total.group(1)


def run_static_encoding_check() -> None:
    suspicious = ("锛", "鏈", "浠", "鈥", "�", "????")
    files = [
        ROOT / "backend" / "app.py",
        ROOT / "backend" / "agent.py",
        ROOT / "backend" / "ai_provider.py",
        ROOT / "backend" / "notifier.py",
        ROOT / "backend" / "scheduler.py",
        ROOT / "backend" / "plan_generator.py",
        ROOT / "backend" / "curriculum.py",
        ROOT / "frontend" / "child.html",
        ROOT / "frontend" / "admin.html",
        ROOT / "frontend" / "parent.html",
        ROOT / "frontend" / "static" / "app.js",
    ]
    offenders: list[str] = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        for marker in suspicious:
            if marker in text:
                offenders.append(f"{path.relative_to(ROOT)} contains {marker!r}")
                break
    assert_true(not offenders, "发现疑似中文乱码：\n" + "\n".join(offenders))


def run_e2e() -> None:
    configure_env()
    sys.path.insert(0, str(ROOT))

    from fastapi.testclient import TestClient
    from backend.app import app
    from backend.db import get_conn

    with TestClient(app) as client:
        health = assert_status(client.get("/api/health"))
        assert_true(health["status"] == "ok", "health status should be ok")
        assert_true("date" in health, "health should return current date")

        for path in ("/admin", "/child", "/parent"):
            html = assert_status(client.get(path))
            assert_true("<html" in html.lower(), f"{path} should return HTML")

        plan = assert_status(client.post("/api/study-plan/generate", data={"raw_text": ENGLISH_PLAN_PROMPT, "student_id": "1"}))
        assert_true(plan["created"] == 1, f"英语计划应创建 1 条，实际 {plan}")
        item = plan["items"][0]
        assert_true(item["title"] == "外研社刘兆义版五年级上册英语暑假预习", "英语计划标题不正确")
        assert_true(item["subject"] == "英语", "英语计划 subject 不正确")
        assert_true(item["total_units"] == 30, "英语计划应为 30 天")

        sources = assert_status(client.get("/api/task-sources"))
        assert_true(len(sources) == 1, "task_sources 应有 1 条")

        # 验证孩子端 GET /api/daily-tasks 在无今日任务时自动兜底生成。
        with get_conn() as conn:
            conn.execute("DELETE FROM daily_tasks")
        tasks = assert_status(client.get("/api/daily-tasks"))
        assert_true(len(tasks) == 1, f"今日任务应自动生成 1 条，实际 {tasks}")
        task = tasks[0]
        task_id = task["id"]
        assert_true("Unit 1 My school is cool" in task["title"], "今日任务标题应进入 Unit 1")
        assert_true(task["check_method"] == "quiz", "内部检查方式应为 quiz")

        child_html = assert_status(client.get("/child"))
        done, total = extract_progress(child_html)
        assert_true((done, total) == ("0", "1"), f"孩子端进度应为 0/1，实际 {done}/{total}")
        assert_true("Unit 1 My school is cool" in child_html, "孩子端 HTML 应服务端直出任务标题")
        assert_true("完成后做小测" in child_html, "孩子端应显示中文检查方式")
        assert_true('<span class="tag">quiz</span>' not in child_html, "孩子端不应裸露 quiz 标签")
        assert_true("window.__INITIAL_TASKS__" in child_html, "孩子端应注入初始任务数据")

        start = assert_status(client.post(f"/api/daily-tasks/{task_id}/event", json={"event_type": "start"}))
        assert_true(start["status"] == "in_progress", "start 后状态应为 in_progress")
        pause = assert_status(client.post(f"/api/daily-tasks/{task_id}/event", json={"event_type": "pause"}))
        assert_true(pause["status"] == "paused", "pause 后状态应为 paused")

        stuck = assert_status(client.post(f"/api/daily-tasks/{task_id}/event", json={"event_type": "stuck", "note": "不会读 school"}))
        assert_true(stuck["status"] == "stuck", "stuck 后状态应为 stuck")
        assistance = stuck.get("assistance", {})
        for key in ("encouragement", "hint_1", "guiding_question", "try_again", "review_focus"):
            assert_true(bool(assistance.get(key)), f"卡住辅导缺少 {key}")

        complete = assert_status(client.post(f"/api/daily-tasks/{task_id}/event", json={"event_type": "complete"}))
        assert_true(complete["status"] == "checking", "complete 后状态应为 checking")

        quiz = assert_status(client.get(f"/api/daily-tasks/{task_id}/quiz"))
        assert_true(len(quiz["items"]) >= 3, "小测题应至少 3 道")
        assert_true(all("answer" not in item for item in quiz["items"]), "孩子端小测不应暴露标准答案")

        answers = {str(item["id"]): "" for item in quiz["items"]}
        grade = assert_status(client.post(f"/api/daily-tasks/{task_id}/quiz", json={"answers": answers}))
        assert_true(grade["total"] == len(quiz["items"]), "批改总题数应等于小测题数")
        assert_true("diagnosis" in grade, "批改应返回诊断")

        dashboard = assert_status(client.get("/api/parent/dashboard"))
        for key in ("tasks", "quiz_results", "stuck_tasks", "notifications", "mastery", "agent_runs"):
            assert_true(key in dashboard, f"家长端 dashboard 缺少 {key}")
        assert_true(len(dashboard["tasks"]) >= 1, "dashboard 应包含任务")
        assert_true(len(dashboard["quiz_results"]) >= 1, "dashboard 应包含小测结果")

        report = assert_status(client.post("/api/day/end"))
        for key in ("summary", "problems", "tomorrow_first_step"):
            assert_true(key in report, f"日报缺少 {key}")

        with get_conn() as conn:
            review_count = conn.execute("SELECT COUNT(*) FROM review_items").fetchone()[0]
            run_count = conn.execute("SELECT COUNT(*) FROM agent_runs WHERE run_type = 'stuck_assist'").fetchone()[0]
            log_count = conn.execute("SELECT COUNT(*) FROM notification_logs").fetchone()[0]
        assert_true(review_count >= 1, "卡住/错题应进入补漏队列")
        assert_true(run_count >= 1, "卡住应记录 Agent stuck_assist 日志")
        assert_true(log_count >= 1, "提醒日志应写入 notification_logs")


def main() -> None:
    try:
        run_static_encoding_check()
        run_e2e()
    finally:
        # 临时目录可保留给失败排查；成功时删除数据库文件即可。
        if TEMP_DB.exists():
            TEMP_DB.unlink()
        try:
            TEMP_DIR.rmdir()
        except OSError:
            pass
    print("SELF_TEST_OK")


if __name__ == "__main__":
    main()
