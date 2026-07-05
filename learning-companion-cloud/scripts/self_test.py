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


def assert_contains_all(text: str, needles: list[str], context: str) -> None:
    missing = [needle for needle in needles if needle not in text]
    assert_true(not missing, f"{context} 缺少页面动作/文案：{missing}")


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
        ROOT / "backend" / "question_engine.py",
        ROOT / "backend" / "report.py",
        ROOT / "backend" / "review.py",
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


def run_static_button_inventory_check() -> None:
    pages = {
        "admin.html": [
            'id="quickPlanForm"',
            'id="quickPlanSubmit"',
            "生成计划并生成今日任务",
            'id="generateToday"',
            "补齐/同步今日任务",
            'id="refresh"',
            "刷新",
            'id="settingsForm"',
            "保存配置",
            'id="checkAi"',
            "检查 AI",
            'id="sourceForm"',
            "保存任务源",
            'id="seedDemo"',
            "生成示例",
            'id="importForm"',
            "批量导入",
            'id="materialForm"',
            "学习资料库",
            'data-action="regenerateQuiz"',
            "重生成小测",
        ],
        "child.html": [
            'id="startNext"',
            "开始下一个任务",
            "继续当前检查",
            "先订正当前小测",
            "先处理卡住任务",
            'data-action="start"',
            "开始",
            "timer-tag",
            'data-action="pause"',
            "暂停",
            'data-action="${doneAction}"',
            'showQuiz',
            "我学会了，继续学",
            "学完了，开始检查",
            "学会以后",
            "继续检查",
            "先点开始",
            "订正后重新检查",
            "我做完了，开始检查",
            'data-action="stuck"',
            "我卡住了",
            "form.addEventListener",
        ],
        "parent.html": [
            'id="endDay"',
            "生成今天日报",
            'id="weekReport"',
            "生成本周周报",
        ],
    }
    for page_name, needles in pages.items():
        text = (ROOT / "frontend" / page_name).read_text(encoding="utf-8")
        assert_contains_all(text, needles, page_name)


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

        settings_before = assert_status(client.get("/api/settings"))
        assert_true(settings_before["region"]["city"] == "武汉", "默认城市应为武汉")
        saved_settings = assert_status(
            client.post(
                "/api/settings",
                json={
                    "region": {
                        "city": "武汉",
                        "grade": "五年级",
                        "semester": "上册",
                        "chinese_version": "统编版/人民教育出版社",
                        "math_version": "北师大版/北京师范大学出版社",
                        "english_version": "外研社三年级起点/刘兆义",
                    },
                    "daily_limits": {"max_total_minutes": 110},
                    "path_rules": {"quiz_pass_score": 0.8},
                    "ai": {"enabled": False, "api_url": "", "model": ""},
                },
            )
        )
        assert_true(saved_settings["daily_limits"]["max_total_minutes"] == 110, "保存配置按钮应写入每日时长")
        ai_status = assert_status(client.get("/api/ai/check"))
        for key in ("ok", "enabled", "message"):
            assert_true(key in ai_status, f"检查 AI 返回缺少 {key}")

        seeded_empty = assert_status(client.post("/api/task-sources/seed"))
        assert_true(seeded_empty["created"] >= 3, "空库点击生成示例应创建示例任务源")
        with get_conn() as conn:
            conn.execute(
                "DELETE FROM task_sources WHERE title IN (?, ?, ?)",
                ("数学暑假作业", "五年级数学第一节：小数乘整数", "KET 词汇与听力"),
            )

        manual_source = assert_status(
            client.post(
                "/api/task-sources",
                data={
                    "category": "preview",
                    "title": "语文五年级上册第一课预习",
                    "subject": "语文",
                    "total_units": "3",
                    "completed_units": "0",
                    "deadline": "2026-08-31",
                    "module": "第一单元",
                    "topic": "第一课",
                    "lesson_content": "读课文、圈生字、说主要内容",
                    "knowledge_points": "生字词、课文理解",
                    "vocabulary": "",
                    "estimated_minutes": "25",
                    "student_id": "1",
                },
            )
        )
        assert_true(manual_source["status"] == "created", "保存任务源按钮应创建任务源")

        imported = assert_status(
            client.post(
                "/api/task-sources/import",
                data={
                    "raw_text": "preview,数学五年级上册小数乘法,数学,2,0,2026-08-31,小数乘整数\n暑假作业本每日一小节 5",
                    "default_deadline": "2026-08-31",
                    "student_id": "1",
                },
            )
        )
        assert_true(imported["created"] == 2, f"批量导入按钮应创建 2 条，实际 {imported}")

        plan = assert_status(client.post("/api/study-plan/generate", data={"raw_text": ENGLISH_PLAN_PROMPT, "student_id": "1"}))
        assert_true(plan["created"] == 1, f"英语计划应创建 1 条，实际 {plan}")
        item = plan["items"][0]
        assert_true(item["title"] == "外研社刘兆义版五年级上册英语暑假预习", "英语计划标题不正确")
        assert_true(item["subject"] == "英语", "英语计划 subject 不正确")
        assert_true(item["total_units"] == 30, "英语计划应为 30 天")

        sources = assert_status(client.get("/api/task-sources"))
        assert_true(len(sources) == 4, f"task_sources 应有 4 条，实际 {len(sources)}")
        material = assert_status(
            client.post(
                "/api/materials",
                data={
                    "title": "Unit 1 单词表测试资料",
                    "subject": "英语",
                    "material_type": "word_list",
                    "content_text": "teacher=老师\nlibrary=图书馆\nclassroom=教室",
                    "source_id": str(item["id"]),
                    "student_id": "1",
                },
            )
        )
        assert_true(material["status"] == "created", "管理端应能保存学习资料")
        materials = assert_status(client.get("/api/materials"))
        assert_true(any(row["title"] == "Unit 1 单词表测试资料" for row in materials), "资料库应能查到刚保存的资料")

        # 验证孩子端 GET /api/daily-tasks 在无今日任务时自动兜底生成。
        with get_conn() as conn:
            conn.execute("DELETE FROM daily_tasks")
        tasks = assert_status(client.get("/api/daily-tasks"))
        assert_true(len(tasks) == 4, f"今日任务应自动生成 4 条，实际 {tasks}")
        task = next(task for task in tasks if "Unit 1 My school is cool" in task["title"])
        task_id = task["id"]
        assert_true("Unit 1 My school is cool" in task["title"], "今日任务标题应进入 Unit 1")
        assert_true(task["check_method"] == "quiz", "内部检查方式应为 quiz")

        math_plan = assert_status(client.post("/api/study-plan/generate", data={"raw_text": "数学书每日一节，五年级上册预习", "student_id": "1"}))
        assert_true(math_plan["created"] == 1, f"数学计划应创建 1 条，实际 {math_plan}")
        synced = assert_status(client.post("/api/daily-tasks/generate"))
        synced_titles = [task["title"] for task in synced["tasks"]]
        assert_true(synced["count"] == 5, f"补齐今日任务后应为 5 条，实际 {synced_titles}")
        assert_true(sum("Unit 1 My school is cool" in title for title in synced_titles) == 1, "英语任务不应重复")
        assert_true(any("数学" in title or "小数" in title for title in synced_titles), f"应补齐数学任务，实际 {synced_titles}")

        extra_source = assert_status(
            client.post(
                "/api/task-sources",
                data={
                    "category": "summer_homework",
                    "title": "管理员新增同步验证任务",
                    "subject": "综合",
                    "total_units": "1",
                    "completed_units": "0",
                    "estimated_minutes": "10",
                    "student_id": "1",
                },
            )
        )
        assert_true(extra_source["status"] == "created", "管理员新增任务源应创建成功")
        synced_after_extra = assert_status(client.post("/api/daily-tasks/generate"))
        synced_after_extra_titles = [task["title"] for task in synced_after_extra["tasks"]]
        assert_true(synced_after_extra["count"] == 6, f"今日已满后手动同步应追加新增任务，实际 {synced_after_extra_titles}")
        assert_true(any("管理员新增同步验证任务" in title for title in synced_after_extra_titles), "新增任务源应出现在今日任务中")

        child_html = assert_status(client.get("/child"))
        done, total = extract_progress(child_html)
        assert_true((done, total) == ("0", "6"), f"孩子端进度应为 0/6，实际 {done}/{total}")
        assert_true("Unit 1 My school is cool" in child_html, "孩子端 HTML 应服务端直出任务标题")
        assert_true("数学" in child_html or "小数" in child_html, "孩子端 HTML 应显示新增数学任务")
        assert_true("语文" in child_html or "生字词" in child_html, "孩子端 HTML 应显示手动录入语文任务")
        assert_true("管理员新增同步验证任务" in child_html, "孩子端 HTML 应显示今日已满后手动同步追加的任务")
        assert_true("完成后做小测" in child_html, "孩子端应显示中文检查方式")
        assert_true('<span class="tag">quiz</span>' not in child_html, "孩子端不应裸露 quiz 标签")
        assert_true("window.__INITIAL_TASKS__" in child_html, "孩子端应注入初始任务数据")

        current_tasks = assert_status(client.get("/api/daily-tasks"))
        with get_conn() as conn:
            conn.execute("UPDATE daily_tasks SET priority = 'P3' WHERE id != ?", (task_id,))
            conn.execute("UPDATE daily_tasks SET priority = 'P0' WHERE id = ?", (task_id,))
        current_tasks = assert_status(client.get("/api/daily-tasks"))
        not_started = [item for item in current_tasks if item["status"] == "not_started"]
        assert_true(len(not_started) >= 1, "开始下一个任务按钮需要至少一个未开始任务")
        start_next_id = not_started[0]["id"]
        assert_true(start_next_id == task_id, "孩子端只能按当前第一任务开始，不能跳任务")
        start_next = assert_status(client.post(f"/api/daily-tasks/{start_next_id}/event", json={"event_type": "start"}))
        assert_true(start_next["status"] == "in_progress", "开始下一个任务按钮应启动首个未开始任务")
        assert_true(start_next["timer_state"] == "running", "开始下一个任务后计时器应运行")
        assert_true("elapsed_seconds" in start_next, "开始响应应返回已学秒数")

        start = assert_status(client.post(f"/api/daily-tasks/{task_id}/event", json={"event_type": "start"}))
        assert_true(start["status"] == "in_progress", "start 后状态应为 in_progress")
        assert_true(start["timer_state"] == "running", "start 后计时器应运行")
        assert_true(bool(start["last_started_at"]), "start 后应返回开始时间")
        with get_conn() as conn:
            conn.execute(
                """
                UPDATE task_progress
                SET created_at = datetime('now', '-125 seconds') || 'Z'
                WHERE daily_task_id = ? AND event_type = 'start'
                """,
                (task_id,),
            )
        pause = assert_status(client.post(f"/api/daily-tasks/{task_id}/event", json={"event_type": "pause"}))
        assert_true(pause["status"] == "paused", "pause 后状态应为 paused")
        assert_true(pause["timer_state"] == "stopped", "pause 后计时器应停止")
        assert_true(pause["elapsed_seconds"] >= 120, f"pause 后应累计已学时间，实际 {pause}")

        blank_stuck = assert_status(client.post(f"/api/daily-tasks/{task_id}/event", json={"event_type": "stuck", "note": ""}))
        blank_assistance_text = " ".join(str(value) for value in blank_stuck.get("assistance", {}).values())
        assert_true(blank_stuck["task_id"] == task_id, "空卡住响应也必须绑定当前英语任务")
        assert_true("白鹭" not in blank_assistance_text and "鹭" not in blank_assistance_text, f"英语空卡住不应串到语文白鹭提示，实际 {blank_assistance_text}")
        assert_true("具体" in blank_assistance_text and ("英语" in blank_assistance_text or "school" in blank_assistance_text.lower() or "单词" in blank_assistance_text), "空卡住应要求孩子补充具体英语卡点")

        stuck = assert_status(client.post(f"/api/daily-tasks/{task_id}/event", json={"event_type": "stuck", "note": "不会读 school"}))
        assert_true(stuck["status"] == "stuck", "stuck 后状态应为 stuck")
        assert_true(stuck["timer_state"] == "stopped", "stuck 后计时器应停止")
        assert_true(stuck["task_id"] == task_id, "卡住响应应返回当前任务 id")
        assert_true(stuck["task_title"] == task["title"], "卡住响应应返回当前任务标题")
        assert_true(stuck["child_note"] == "不会读 school", "卡住响应应返回孩子填写的问题")
        assert_true(stuck["assistant_source"] in ("ai", "rule"), "卡住响应应标明辅导来源")
        assistance = stuck.get("assistance", {})
        for key in ("encouragement", "hint_1", "guiding_question", "try_again", "review_focus"):
            assert_true(bool(assistance.get(key)), f"卡住辅导缺少 {key}")
        assert_true("1." in assistance.get("hint_1", "") or "1．" in assistance.get("hint_1", ""), f"卡住辅导应直接给步骤，实际 {assistance}")
        generic_words = ("卡住很正常", "可能卡在", "想一想", "同类小例子")
        assert_true(not any(word in assistance.get("encouragement", "") for word in generic_words), f"卡住辅导不应是统一废话，实际 {assistance}")

        current_task_rows = assert_status(client.get("/api/daily-tasks"))
        stuck_rows = [item for item in current_task_rows if item["status"] == "stuck"]
        assert_true([item["id"] for item in stuck_rows] == [task_id], f"只应当前任务卡住，实际 {stuck_rows}")
        resume_after_stuck = assert_status(client.post(f"/api/daily-tasks/{task_id}/event", json={"event_type": "start"}))
        assert_true(resume_after_stuck["status"] == "in_progress", "卡住学会后点继续应回到进行中")
        assert_true(resume_after_stuck["timer_state"] == "running", "卡住学会后继续应重新计时")

        chinese_task = next(item for item in current_task_rows if "白鹭" in item["title"] or "语文" in item["title"])
        chinese_stuck = assert_status(
            client.post(
                f"/api/daily-tasks/{chinese_task['id']}/event",
                json={"event_type": "stuck", "note": "不认识鹭这个字"},
            )
        )
        chinese_assistance = chinese_stuck.get("assistance", {})
        assert_true(chinese_stuck["task_id"] == chinese_task["id"], "语文卡住响应应绑定语文任务")
        assert_true("鹭" in chinese_assistance.get("likely_blocker", ""), "应针对不认识的鹭字解释")
        assert_true("lù" in chinese_assistance.get("likely_blocker", ""), "应给出鹭字读音")

        complete = assert_status(client.post(f"/api/daily-tasks/{task_id}/event", json={"event_type": "complete"}))
        assert_true(complete["status"] == "checking", "complete 后状态应为 checking")
        assert_true(complete["timer_state"] == "stopped", "complete 后计时器应停止")
        start_while_checking = assert_status(client.post(f"/api/daily-tasks/{task_id}/event", json={"event_type": "start"}))
        assert_true(start_while_checking["blocked"] is True, "检查中不能被开始按钮重新启动")
        assert_true(start_while_checking["status"] == "checking", "检查中误点开始后仍应保持 checking")
        duplicate_complete = assert_status(client.post(f"/api/daily-tasks/{task_id}/event", json={"event_type": "complete"}))
        assert_true(duplicate_complete["already_applied"] is True, "complete 连点应返回幂等结果")
        with get_conn() as conn:
            complete_events = conn.execute(
                "SELECT COUNT(*) FROM task_progress WHERE daily_task_id = ? AND event_type = 'complete'",
                (task_id,),
            ).fetchone()[0]
        assert_true(complete_events == 1, f"complete 连点不应重复写进度，实际 {complete_events}")

        quiz = assert_status(client.get(f"/api/daily-tasks/{task_id}/quiz"))
        assert_true(len(quiz["items"]) >= 3, "小测题应至少 3 道")
        assert_true(all("answer" not in item for item in quiz["items"]), "孩子端小测不应暴露标准答案")
        english_types = {item["question_type"] for item in quiz["items"]}
        assert_true(
            {"english_spelling", "english_word_cn_to_en", "english_sentence_fill"} & english_types == {"english_spelling", "english_word_cn_to_en", "english_sentence_fill"},
            f"英语小测应包含默写/中译英/句型填空，实际 {english_types}",
        )
        assert_true(any("老师" in item["question"] or "teacher" in item["question"] for item in quiz["items"]), "英语小测应引用资料库单词表")

        chinese_quiz = assert_status(client.get(f"/api/daily-tasks/{chinese_task['id']}/quiz"))
        chinese_types = {item["question_type"] for item in chinese_quiz["items"]}
        assert_true(
            {"chinese_word_dictation", "chinese_pinyin", "chinese_char_group"}.issubset(chinese_types),
            f"语文小测应包含听写/拼音/组词，实际 {chinese_types}",
        )
        math_task = next(item for item in current_task_rows if "数学" in item["title"] or "小数" in item["title"])
        math_quiz = assert_status(client.get(f"/api/daily-tasks/{math_task['id']}/quiz"))
        math_types = {item["question_type"] for item in math_quiz["items"]}
        assert_true(
            {"math_exact", "math_concept_choice", "math_step_explain"}.issubset(math_types),
            f"数学小测应包含计算/概念/步骤，实际 {math_types}",
        )

        regenerated = assert_status(client.post(f"/api/daily-tasks/{task_id}/quiz/regenerate"))
        assert_true(len(regenerated["items"]) >= 3, "重生成小测按钮应返回至少 3 道题")

        guidance = assert_status(client.get(f"/api/agent/task-guidance/{task_id}"))
        assert_true("guidance" in guidance or "steps" in guidance, f"任务指导应返回可读内容，实际 {guidance}")

        answers = {str(item["id"]): "" for item in quiz["items"]}
        grade = assert_status(client.post(f"/api/daily-tasks/{task_id}/quiz", json={"answers": answers}))
        assert_true(grade["total"] == len(quiz["items"]), "批改总题数应等于小测题数")
        assert_true(grade["score_json"]["pass_score"] == 80, f"小测通过线应读取管理端 80% 配置，实际 {grade['score_json']}")
        assert_true("diagnosis" in grade, "批改应返回诊断")
        assert_true("error_types" in grade and grade["error_types"], "批改应返回错因统计")
        assert_true(all("error_type" in item for item in grade["wrong_items"]), "每道错题应有错因")
        assert_true("mastery" in grade and "mastery_level" in grade["mastery"], "批改应返回掌握度")
        start_while_revision = assert_status(client.post(f"/api/daily-tasks/{task_id}/event", json={"event_type": "start"}))
        assert_true(start_while_revision["blocked"] is True, "需订正不能被开始按钮重新启动")
        assert_true(start_while_revision["status"] == "needs_revision", "需订正误点开始后仍应保持 needs_revision")
        agent_grade_result = assert_status(client.post(f"/api/agent/grade/{task_id}", json={"answers": answers}))
        assert_true(agent_grade_result["total"] == len(quiz["items"]), "Agent 批改接口应可用")
        with get_conn() as conn:
            correct_answers = {
                str(row["id"]): row["answer"]
                for row in conn.execute(
                    "SELECT id, answer FROM quiz_items WHERE daily_task_id = ?",
                    (task_id,),
                ).fetchall()
            }
        passed_grade = assert_status(client.post(f"/api/daily-tasks/{task_id}/quiz", json={"answers": correct_answers}))
        assert_true(passed_grade["status"] == "completed", f"正确答案应通过小测，实际 {passed_grade}")
        with get_conn() as conn:
            task_row = conn.execute("SELECT source_id FROM daily_tasks WHERE id = ?", (task_id,)).fetchone()
            source_units_before_duplicate = conn.execute(
                "SELECT completed_units FROM task_sources WHERE id = ?",
                (task_row["source_id"],),
            ).fetchone()[0]
            quiz_results_before_duplicate = conn.execute(
                "SELECT COUNT(*) FROM quiz_results WHERE daily_task_id = ?",
                (task_id,),
            ).fetchone()[0]
        duplicate_grade = assert_status(client.post(f"/api/daily-tasks/{task_id}/quiz", json={"answers": correct_answers}))
        assert_true(duplicate_grade["already_checked"] is True, "已完成小测重复提交应返回最近结果")
        with get_conn() as conn:
            source_units_after_duplicate = conn.execute(
                "SELECT completed_units FROM task_sources WHERE id = ?",
                (task_row["source_id"],),
            ).fetchone()[0]
            quiz_results_after_duplicate = conn.execute(
                "SELECT COUNT(*) FROM quiz_results WHERE daily_task_id = ?",
                (task_id,),
            ).fetchone()[0]
        assert_true(source_units_after_duplicate == source_units_before_duplicate, "重复提交不应重复推进学习进度")
        assert_true(quiz_results_after_duplicate == quiz_results_before_duplicate, "重复提交不应新增批改记录")

        dashboard = assert_status(client.get("/api/parent/dashboard"))
        for key in ("tasks", "quiz_results", "stuck_tasks", "notifications", "mastery", "agent_runs"):
            assert_true(key in dashboard, f"家长端 dashboard 缺少 {key}")
        assert_true(len(dashboard["tasks"]) >= 1, "dashboard 应包含任务")
        assert_true(len(dashboard["quiz_results"]) >= 1, "dashboard 应包含小测结果")

        report = assert_status(client.post("/api/day/end"))
        for key in ("summary", "problems", "tomorrow_first_step", "weakest_point", "parent_attention", "ten_minute_action"):
            assert_true(key in report, f"日报缺少 {key}")
        agent_report_result = assert_status(client.post("/api/agent/daily-report", json={"student_id": 1}))
        for key in ("summary", "problems", "tomorrow_first_step"):
            assert_true(key in agent_report_result, f"Agent 日报缺少 {key}")
        weekly_report = assert_status(client.post("/api/week/report"))
        for key in ("summary", "trend", "suggestions"):
            assert_true(key in weekly_report, f"周报缺少 {key}")
        reviews = assert_status(client.get("/api/review-items"))
        assert_true(isinstance(reviews, list), "补漏列表应返回数组")
        review_book_payload = assert_status(client.get("/api/review-book"))
        assert_true("items" in review_book_payload, "补漏本应返回 items")
        overview = assert_status(client.get("/api/agent/overview"))
        assert_true("runs" in overview, "Agent 总览应返回 runs")

        agent_plan_result = assert_status(client.post("/api/agent/plan", json={"goal": "语文书每日一篇课文，五年级上册", "student_id": 1}))
        assert_true(agent_plan_result["created"] >= 1, "Agent 规划接口应创建计划")
        agent_daily_tasks_result = assert_status(client.post("/api/agent/daily-tasks", json={"student_id": 1}))
        assert_true("tasks" in agent_daily_tasks_result, "Agent 今日任务接口应返回 tasks")

        curriculum = assert_status(client.get("/api/curriculum"))
        assert_true("subjects" in curriculum and "defaults" in curriculum, "教材接口应返回 subjects/defaults")

        with get_conn() as conn:
            review_count = conn.execute("SELECT COUNT(*) FROM review_items").fetchone()[0]
            review_stages = {row[0] for row in conn.execute("SELECT DISTINCT review_stage FROM review_items").fetchall()}
            run_count = conn.execute("SELECT COUNT(*) FROM agent_runs WHERE run_type = 'stuck_assist'").fetchone()[0]
            log_count = conn.execute("SELECT COUNT(*) FROM notification_logs").fetchone()[0]
        seeded_existing = assert_status(client.post("/api/task-sources/seed"))
        assert_true(seeded_existing["created"] == 0, "已有计划时生成示例按钮应安全跳过重复创建")
        assert_true(review_count >= 1, "卡住/错题应进入补漏队列")
        assert_true({"D1", "D3", "D7"}.issubset(review_stages), f"错题应生成 D1/D3/D7 复习节奏，实际 {review_stages}")
        assert_true(run_count >= 1, "卡住应记录 Agent stuck_assist 日志")
        assert_true(log_count >= 1, "提醒日志应写入 notification_logs")


def main() -> None:
    try:
        run_static_encoding_check()
        run_static_button_inventory_check()
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
