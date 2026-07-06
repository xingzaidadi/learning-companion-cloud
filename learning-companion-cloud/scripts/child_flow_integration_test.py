from __future__ import annotations

import os
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
TEMP_DIR = Path(tempfile.mkdtemp(prefix="learning-companion-child-flow-"))
TEMP_DB = TEMP_DIR / "learning.db"


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


def cleanup() -> None:
    if TEMP_DIR.exists():
        for child in TEMP_DIR.iterdir():
            child.unlink()
        TEMP_DIR.rmdir()


def seed_task(conn: Any, title: str, priority: str = "P0") -> int:
    from backend.db import utc_now

    now = utc_now()
    conn.execute(
        """
        INSERT INTO daily_tasks (
            student_id, date, source_id, priority, title, description,
            estimated_minutes, completion_standard, check_method, status,
            created_at, updated_at
        )
        VALUES (?, ?, NULL, ?, ?, ?, ?, ?, 'quiz', 'not_started', ?, ?)
        """,
        (
            1,
            date.today().isoformat(),
            priority,
            title,
            f"{title}：按步骤学习，完成后检查。",
            15,
            "能说出今天学了什么，完成基础练习，并通过小测。",
            now,
            now,
        ),
    )
    return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])


def seed_quiz(conn: Any, task_id: int) -> list[int]:
    from backend.db import dumps, utc_now

    now = utc_now()
    items = [
        ("english_spelling", "拼写：老师", "[]", "teacher", "记住 teacher 的拼写。"),
        ("english_word_cn_to_en", "中译英：图书馆", "[]", "library", "library 是图书馆。"),
        ("english_sentence_fill", "句型：There __ a desk here.", "[]", "is", "There is 表示有。"),
        ("choice", "遇到不会的题应该怎么做？", dumps(["直接跳过", "说明卡在哪里", "直接点完成"]), "说明卡在哪里", "卡住要说明问题。"),
        ("math_exact", "计算：2+3", "[]", "5", "2+3=5。"),
    ]
    ids: list[int] = []
    for question_type, question, options_json, answer, explanation in items:
        conn.execute(
            """
            INSERT INTO quiz_items (daily_task_id, question_type, question, options_json, answer, explanation, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (task_id, question_type, question, options_json, answer, explanation, now),
        )
        ids.append(int(conn.execute("SELECT last_insert_rowid()").fetchone()[0]))
    return ids


def seed_quiz_for_task_if_empty(task_id: int) -> list[int]:
    from backend.db import get_conn

    with get_conn() as conn:
        existing = [
            int(row[0])
            for row in conn.execute("SELECT id FROM quiz_items WHERE daily_task_id = ? ORDER BY id", (task_id,)).fetchall()
        ]
        if existing:
            return existing
        return seed_quiz(conn, task_id)


def task_by_id(tasks: list[dict[str, Any]], task_id: int) -> dict[str, Any]:
    for task in tasks:
        if int(task["id"]) == task_id:
            return task
    raise AssertionError(f"任务不存在：{task_id}，实际 {tasks}")


def run_child_flow() -> None:
    configure_env()
    sys.path.insert(0, str(ROOT))

    from fastapi.testclient import TestClient
    from backend.app import app
    from backend.db import get_conn

    with TestClient(app) as client:
        with get_conn() as conn:
            task1 = seed_task(conn, "数学小数乘法")
            task2 = seed_task(conn, "语文预习 白鹭", "P1")
            task3 = seed_task(conn, "数学小数乘法", "P2")
            item_ids = seed_quiz(conn, task1)

        child_html = assert_status(client.get("/child"))
        for needle in ("学习驾驶舱", "今日进度", "开始下一个任务", "当前任务", "timer-tag", "window.__INITIAL_TASKS__"):
            assert_true(needle in child_html, f"孩子端页面缺少 {needle}")
        for marker in ("child-one-focus", "child-collapsible-workspace", "child-collapsible-queue"):
            assert_true(marker in child_html, f"child page missing quality marker {marker}")

        tasks = assert_status(client.get("/api/daily-tasks"))
        assert_true([task["status"] for task in tasks] == ["not_started", "not_started", "not_started"], f"初始状态错误：{tasks}")
        task1 = int(tasks[0]["id"])
        task2 = int(tasks[1]["id"])
        item_ids = seed_quiz_for_task_if_empty(task1)

        later_start = assert_status(client.post(f"/api/daily-tasks/{task2}/event", json={"event_type": "start"}))
        assert_true(later_start.get("blocked") is True, f"不能越过第一个任务启动第二个任务：{later_start}")

        start = assert_status(client.post(f"/api/daily-tasks/{task1}/event", json={"event_type": "start"}))
        assert_true(start["status"] == "in_progress" and start["timer_state"] == "running", f"开始任务失败：{start}")
        duplicate_start = assert_status(client.post(f"/api/daily-tasks/{task1}/event", json={"event_type": "start"}))
        assert_true(duplicate_start.get("already_applied") is True, f"开始连点应幂等：{duplicate_start}")

        start_task2_while_running = assert_status(client.post(f"/api/daily-tasks/{task2}/event", json={"event_type": "start"}))
        assert_true(start_task2_while_running.get("blocked") is True, "第一任务进行中时不能启动第二任务")

        pause = assert_status(client.post(f"/api/daily-tasks/{task1}/event", json={"event_type": "pause"}))
        assert_true(pause["status"] == "paused" and pause["timer_state"] == "stopped", f"暂停失败：{pause}")
        resume = assert_status(client.post(f"/api/daily-tasks/{task1}/event", json={"event_type": "start"}))
        assert_true(resume["status"] == "in_progress" and resume["timer_state"] == "running", f"继续学习失败：{resume}")

        stuck = assert_status(client.post(f"/api/daily-tasks/{task1}/event", json={"event_type": "stuck", "note": "不会判断小数点位置"}))
        assert_true(stuck["status"] == "stuck" and stuck["timer_state"] == "stopped", f"卡住状态错误：{stuck}")
        assistance = stuck.get("assistance", {})
        for key in ("encouragement", "hint_1", "try_again", "review_focus"):
            assert_true(bool(assistance.get(key)), f"卡住辅导缺少 {key}：{assistance}")
        steps = assistance.get("steps", [])
        assert_true(isinstance(steps, list) and len(steps) >= 3, f"卡住辅导应返回统一 steps[]：{assistance}")
        assert_true(all(step.get("action") and step.get("success_rule") for step in steps), f"steps 每一步都应可执行：{steps}")
        start_task2_while_stuck = assert_status(client.post(f"/api/daily-tasks/{task2}/event", json={"event_type": "start"}))
        assert_true(start_task2_while_stuck.get("blocked") is True, "第一任务卡住时不能启动第二任务")
        learned = assert_status(client.post(f"/api/daily-tasks/{task1}/event", json={"event_type": "resume"}))
        assert_true(learned["status"] == "in_progress", f"卡住后学会继续失败：{learned}")

        complete = assert_status(client.post(f"/api/daily-tasks/{task1}/event", json={"event_type": "complete"}))
        assert_true(complete["status"] == "checking" and complete["timer_state"] == "stopped", f"完成进入检查失败：{complete}")
        duplicate_complete = assert_status(client.post(f"/api/daily-tasks/{task1}/event", json={"event_type": "complete"}))
        assert_true(duplicate_complete.get("already_applied") is True, f"完成连点应幂等：{duplicate_complete}")
        start_while_checking = assert_status(client.post(f"/api/daily-tasks/{task1}/event", json={"event_type": "start"}))
        assert_true(start_while_checking.get("blocked") is True and start_while_checking["status"] == "checking", f"检查中不能重新开始：{start_while_checking}")
        start_task2_while_checking = assert_status(client.post(f"/api/daily-tasks/{task2}/event", json={"event_type": "start"}))
        assert_true(start_task2_while_checking.get("blocked") is True, "检查中不能启动第二任务")

        quiz = assert_status(client.get(f"/api/daily-tasks/{task1}/quiz"))
        assert_true(len(quiz["items"]) == len(item_ids), f"小测题数量错误：{quiz}")
        assert_true(all("answer" not in item for item in quiz["items"]), "孩子端小测不能暴露答案")
        assert_true(all("explanation" not in item for item in quiz["items"]), "孩子端小测不能暴露答案解释")
        quiz_text = "\n".join(item["question"].lower() for item in quiz["items"])
        assert_true("there __ a library" not in quiz_text and "there ___ a library" not in quiz_text, "小测题干不应用句型题泄露 library")

        blank_answers = {str(item_id): "" for item_id in item_ids}
        blank_response = assert_status(client.post(f"/api/daily-tasks/{task1}/quiz", json={"answers": blank_answers}), 400)
        assert_true("missing" in blank_response["detail"], f"空答案必须被拒绝，不能进入批改：{blank_response}")
        wrong_answers = {str(item_id): "不会" for item_id in item_ids}
        revision = assert_status(client.post(f"/api/daily-tasks/{task1}/quiz", json={"answers": wrong_answers}))
        assert_true(revision["status"] == "needs_revision" and revision["wrong_items"], f"低分应需订正：{revision}")
        start_while_revision = assert_status(client.post(f"/api/daily-tasks/{task1}/event", json={"event_type": "start"}))
        assert_true(start_while_revision.get("blocked") is True and start_while_revision["status"] == "needs_revision", f"需订正不能重新开始：{start_while_revision}")
        start_task2_while_revision = assert_status(client.post(f"/api/daily-tasks/{task2}/event", json={"event_type": "start"}))
        assert_true(start_task2_while_revision.get("blocked") is True, "需订正时不能启动第二任务")

        correct_answers = {
            str(item_ids[0]): "teacher",
            str(item_ids[1]): "library",
            str(item_ids[2]): "is",
            str(item_ids[3]): "说明卡在哪里",
            str(item_ids[4]): "5",
        }
        passed = assert_status(client.post(f"/api/daily-tasks/{task1}/quiz", json={"answers": correct_answers}))
        assert_true(passed["status"] == "completed" and passed["correct"] == passed["total"], f"订正后应通过：{passed}")
        duplicate_pass = assert_status(client.post(f"/api/daily-tasks/{task1}/quiz", json={"answers": correct_answers}))
        assert_true(duplicate_pass.get("already_checked") is True, f"通过后重复提交应返回最近结果：{duplicate_pass}")

        tasks_after_pass = assert_status(client.get("/api/daily-tasks"))
        assert_true(task_by_id(tasks_after_pass, task1)["status"] == "completed", f"第一任务应完成：{tasks_after_pass}")
        start_task2 = assert_status(client.post(f"/api/daily-tasks/{task2}/event", json={"event_type": "start"}))
        assert_true(start_task2["status"] == "in_progress" and start_task2["timer_state"] == "running", f"第一任务通过后应可启动第二任务：{start_task2}")

        child_html_after = assert_status(client.get("/child"))
        for needle in ("继续当前任务", "已完成", "window.__INITIAL_TASKS__"):
            assert_true(needle in child_html_after, f"刷新页面后状态应恢复，缺少 {needle}")

        with get_conn() as conn:
            from backend.db import utc_now

            review_id = conn.execute(
                """
                INSERT INTO review_items (
                    student_id, source_task_id, question, answer, explanation,
                    reason, due_date, status, review_stage, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', 'D1', ?, ?)
                """,
                (
                    1,
                    task1,
                    "拼写：中译英：错因/来源",
                    "stuck",
                    "孩子把卡住来源写错，需要复默 stuck。",
                    "wrong_english_spelling",
                    date.today().isoformat(),
                    utc_now(),
                    utc_now(),
                ),
            ).lastrowid
            duplicate_review_id = conn.execute(
                """
                INSERT INTO review_items (
                    student_id, source_task_id, question, answer, explanation,
                    reason, due_date, status, review_stage, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', 'D1', ?, ?)
                """,
                (
                    1,
                    task1,
                    "D1 补漏：拼写：中译英：错因/来源",
                    "stuck",
                    "同一个错点的重复补漏，不能继续卡住孩子。",
                    "wrong_english_spelling",
                    date.today().isoformat(),
                    utc_now(),
                    utc_now(),
                ),
            ).lastrowid
        review_tasks = assert_status(client.post("/api/daily-tasks/generate"))["tasks"]
        review_task = next(task for task in review_tasks if str(task["check_method"]) == "review_quiz")
        review_task_id = int(review_task["id"])
        review_quiz = assert_status(client.get(f"/api/daily-tasks/{review_task_id}/quiz"))
        review_text = "\n".join(item["question"] for item in review_quiz["items"])
        assert_true("请重新回答或重做这个问题" not in review_text, f"补漏复测不能再用空泛模板题：{review_text}")
        assert_true("这次你打算怎样避免同类错误" not in review_text, f"补漏复测不能再问空泛反思题：{review_text}")
        assert_true("标准答案" not in review_task["description"] and "stuck" not in review_task["description"], f"补漏任务卡不应暴露标准答案：{review_task}")
        assert_true(any(item["question_type"] == "english_spelling" for item in review_quiz["items"]), f"英文错词补漏应生成可判分默写题：{review_quiz}")
        assert_true(all(item["question_type"] != "english_sentence_make" for item in review_quiz["items"]), f"英文错词补漏不应用造句开放题卡孩子：{review_quiz}")
        with get_conn() as conn:
            review_answers = {
                str(row["id"]): row["answer"]
                for row in conn.execute("SELECT id, answer FROM quiz_items WHERE daily_task_id = ?", (review_task_id,)).fetchall()
            }
        review_pass = assert_status(client.post(f"/api/daily-tasks/{review_task_id}/quiz", json={"answers": review_answers}))
        assert_true(review_pass["status"] == "completed", f"补漏复测正确答案应能通过：{review_pass}")
        with get_conn() as conn:
            review_status = conn.execute("SELECT status FROM review_items WHERE id = ?", (review_id,)).fetchone()[0]
            duplicate_review_status = conn.execute("SELECT status FROM review_items WHERE id = ?", (duplicate_review_id,)).fetchone()[0]
            duplicate_open_tasks = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM daily_tasks dt
                JOIN task_progress tp ON tp.daily_task_id = dt.id AND tp.event_type = 'review_item'
                WHERE tp.note = ? AND dt.status != 'completed'
                """,
                (str(duplicate_review_id),),
            ).fetchone()["count"]
        assert_true(review_status == "done", f"补漏复测通过后 review_item 应完成，实际 {review_status}")
        assert_true(duplicate_review_status == "done", f"同源重复补漏应一起关闭，实际 {duplicate_review_status}")
        assert_true(duplicate_open_tasks == 0, "同源重复补漏通过后不应继续出现在今日待做队列")

        with get_conn() as conn:
            conn.execute("DELETE FROM daily_tasks")
            conn.execute("DELETE FROM task_sources")

        published = assert_status(
            client.post(
                "/api/task-sources",
                data={
                    "category": "preview",
                    "title": "后端发布联调：英语 Unit 1 预习",
                    "subject": "英语",
                    "total_units": "1",
                    "completed_units": "0",
                    "estimated_minutes": "20",
                    "deadline": "2026-08-31",
                    "topic": "Unit 1 My school is cool",
                    "lesson_content": "听音频跟读，认读 teacher/library/classroom，理解 There is 句型。",
                    "knowledge_points": "单词拼写、中译英、There is 句型填空",
                    "student_id": "1",
                },
            )
        )
        assert_true(published["status"] == "created", f"后端发布任务源失败：{published}")
        generated = assert_status(client.post("/api/daily-tasks/generate"))
        assert_true(generated["count"] >= 1, f"发布后应能生成今日任务：{generated}")
        published_task = next(task for task in generated["tasks"] if "后端发布联调" in task["title"] or "Unit 1" in task["title"])
        published_task_id = int(published_task["id"])

        child_after_publish = assert_status(client.get("/child"))
        assert_true("后端发布联调" in child_after_publish or "Unit 1" in child_after_publish, "孩子端应看到后端发布的今日任务")
        published_tasks = assert_status(client.get("/api/daily-tasks"))
        assert_true(task_by_id(published_tasks, published_task_id)["status"] == "not_started", f"发布后的任务应未开始：{published_tasks}")

        published_start = assert_status(client.post(f"/api/daily-tasks/{published_task_id}/event", json={"event_type": "start"}))
        assert_true(published_start["status"] == "in_progress" and published_start["timer_state"] == "running", f"孩子开始后端发布任务失败：{published_start}")
        published_stuck = assert_status(
            client.post(
                f"/api/daily-tasks/{published_task_id}/event",
                json={"event_type": "stuck", "note": "不会拼 library"},
            )
        )
        assert_true(published_stuck["status"] == "stuck" and published_stuck.get("assistance"), f"后端发布任务卡住辅导失败：{published_stuck}")
        published_resume = assert_status(client.post(f"/api/daily-tasks/{published_task_id}/event", json={"event_type": "start"}))
        assert_true(published_resume["status"] == "in_progress", f"后端发布任务卡住后继续失败：{published_resume}")
        published_complete = assert_status(client.post(f"/api/daily-tasks/{published_task_id}/event", json={"event_type": "complete"}))
        assert_true(published_complete["status"] == "checking", f"后端发布任务完成后应进入检查：{published_complete}")

        published_quiz = assert_status(client.get(f"/api/daily-tasks/{published_task_id}/quiz"))
        assert_true(len(published_quiz["items"]) >= 3, f"后端发布任务应生成小测：{published_quiz}")
        assert_true(all("answer" not in item for item in published_quiz["items"]), "后端发布任务的小测不能向孩子暴露答案")
        blank_published_answers = {str(item["id"]): "" for item in published_quiz["items"]}
        blank_published = assert_status(client.post(f"/api/daily-tasks/{published_task_id}/quiz", json={"answers": blank_published_answers}), 400)
        assert_true("missing" in blank_published["detail"], f"后端发布任务空答案必须被拒绝：{blank_published}")
        wrong_published_answers = {str(item["id"]): "不会" for item in published_quiz["items"]}
        published_revision = assert_status(client.post(f"/api/daily-tasks/{published_task_id}/quiz", json={"answers": wrong_published_answers}))
        assert_true(published_revision["status"] == "needs_revision", f"后端发布任务答错应进入订正：{published_revision}")

        with get_conn() as conn:
            correct_published_answers = {
                str(row["id"]): row["answer"]
                for row in conn.execute(
                    "SELECT id, answer FROM quiz_items WHERE daily_task_id = ?",
                    (published_task_id,),
                ).fetchall()
            }
            source_units_before = conn.execute(
                "SELECT completed_units FROM task_sources WHERE id = ?",
                (published_task["source_id"],),
            ).fetchone()[0]
        published_pass = assert_status(client.post(f"/api/daily-tasks/{published_task_id}/quiz", json={"answers": correct_published_answers}))
        assert_true(published_pass["status"] == "completed", f"后端发布任务订正后应完成：{published_pass}")
        with get_conn() as conn:
            source_units_after = conn.execute(
                "SELECT completed_units FROM task_sources WHERE id = ?",
                (published_task["source_id"],),
            ).fetchone()[0]
        assert_true(source_units_after == source_units_before + 1, "完成后应推进后端发布任务源进度")

        final_tasks = assert_status(client.get("/api/daily-tasks"))
        assert_true(task_by_id(final_tasks, published_task_id)["status"] == "completed", f"后端发布任务最终应完成：{final_tasks}")


def main() -> None:
    try:
        run_child_flow()
    finally:
        cleanup()
    print("CHILD_FLOW_INTEGRATION_OK")


if __name__ == "__main__":
    main()
