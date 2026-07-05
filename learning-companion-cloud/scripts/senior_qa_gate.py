from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
TEMP_DIR = Path(tempfile.mkdtemp(prefix="learning-companion-senior-qa-"))
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
    assert_true(
        response.status_code == status_code,
        f"{response.request.method} {response.request.url} -> {response.status_code}: {response.text[:500]}",
    )
    if response.headers.get("content-type", "").startswith("application/json"):
        return response.json()
    return response.text


def post_form(client: Any, path: str, data: dict[str, str]) -> Any:
    return assert_status(client.post(path, data=data))


def seed_materials(client: Any) -> None:
    chinese_text = """
五年级上册语文 第一单元
课文 白鹭 落花生 桂花雨 少年中国说
生字词：白鹭、精巧、配合、适宜、恩惠、播种、浇水、吩咐、爱慕
课后题：朗读课文，概括主要内容，体会关键语句表达效果。
语文园地：交流平台，词句段运用。
日积月累：不饱食以终日，不弃功于寸阴。
习作：我的心爱之物，写清楚样子和喜爱原因。
""".strip()
    math_text = """
五年级上册数学 单元目录：观察简单组合体，小数乘法，小数除法，用字母表示数，多边形的面积，可能性。
概念例题：3.6×10=36；4.8÷10=0.48；2.4×0.3=0.72。
计算练习：小数乘法先按整数算，再确定小数点位置；小数除法商的小数点和被除数对齐。
应用题：买 4 千克苹果，每千克 6.8 元，一共 27.2 元。
易错验算：用估算、逆运算检查，避免小数点位置错误。
""".strip()
    english_text = """
Unit 1 My school is cool.
Words: school 学校, classroom 教室, library 图书馆, teacher 老师, playground 操场.
Listen and read: Where is the library? It is next to the classroom.
Sentence: This is our school. I can read books in the library.
Dictation: school, library, classroom, teacher.
""".strip()
    fixtures = [
        ("语文 P0 全覆盖资料", "语文", chinese_text),
        ("数学 P0 全覆盖资料", "数学", math_text),
        ("英语 P0 全覆盖资料", "英语", english_text),
    ]
    for title, subject, content_text in fixtures:
        post_form(
            client,
            "/api/materials",
            {
                "title": title,
                "subject": subject,
                "material_type": "notes",
                "content_text": content_text,
                "source_id": "0",
                "student_id": "1",
            },
        )


def assert_rag_quality(client: Any, get_conn: Any) -> None:
    coverage = assert_status(client.get("/api/materials/coverage"))
    assert_true(coverage["overall_ratio"] >= 0.95, f"RAG 总覆盖不足：{coverage}")
    ratios = {item["subject"]: item["coverage_ratio"] for item in coverage["subjects"]}
    for subject in ("语文", "数学", "英语"):
        assert_true(ratios.get(subject, 0) >= 0.95, f"{subject} 覆盖不足：{coverage}")

    required_queries = {
        "语文": ["日积月累", "白鹭", "少年中国说", "语文园地"],
        "数学": ["小数乘法", "小数除法", "多边形的面积", "验算"],
        "英语": ["Unit", "Words", "Listen", "school"],
    }
    for subject, queries in required_queries.items():
        for query in queries:
            hits = assert_status(client.get(f"/api/materials/search?q={query}&subject={subject}"))
            assert_true(hits, f"{subject} RAG 应命中 {query}")
            assert_true(any(row["source_ref"] for row in hits), f"{subject} RAG 命中应有 source_ref：{query}")

    with get_conn() as conn:
        empty_source_count = conn.execute(
            "SELECT COUNT(*) FROM material_chunks WHERE source_ref = '' OR chunk_text = ''"
        ).fetchone()[0]
    assert_true(empty_source_count == 0, f"RAG chunk 不应有空 source_ref/chunk_text：{empty_source_count}")


def assert_plan_to_child_flow(client: Any, get_conn: Any) -> int:
    plan = post_form(
        client,
        "/api/study-plan/generate",
        {
            "raw_text": "语文书每日一篇课文；数学书每日一节；英语书每日一个 Unit 小节；目标五上语数英 95+",
            "student_id": "1",
        },
    )
    assert_true(plan["created"] >= 1, f"自然语言计划应至少创建 1 条：{plan}")
    today = assert_status(client.post("/api/daily-tasks/generate"))
    assert_true(today["count"] >= 3, f"今日任务应覆盖多科：{today}")
    tasks = assert_status(client.get("/api/daily-tasks"))
    assert_true(len(tasks) >= 3, f"孩子端应能看到今日任务：{tasks}")
    assert_true(all(task.get("planned_start") and task.get("planned_end") for task in tasks), f"每个任务都必须有科学时间段：{tasks}")
    assert_true(all(task.get("schedule_reason") for task in tasks), f"每个任务都必须说明排程理由：{tasks}")
    schedule = assert_status(client.post("/api/daily-tasks/schedule", json={"student_id": 1}))
    assert_true(schedule["count"] == len(tasks), f"重新排程不应丢任务：{schedule}")

    task_id = int(tasks[0]["id"])
    started = assert_status(client.post(f"/api/daily-tasks/{task_id}/event", json={"event_type": "start"}))
    assert_true(started["status"] == "in_progress", f"开始后状态不正确：{started}")
    paused = assert_status(client.post(f"/api/daily-tasks/{task_id}/event", json={"event_type": "pause"}))
    assert_true(paused["timer_state"] == "stopped", f"暂停后计时应停止：{paused}")
    stuck = assert_status(client.post(f"/api/daily-tasks/{task_id}/event", json={"event_type": "stuck", "note": "我不会这个知识点"}))
    assert_true(stuck["status"] == "stuck", f"卡住状态不正确：{stuck}")
    assistance = stuck.get("assistance", {})
    steps = assistance.get("steps", [])
    assert_true(isinstance(steps, list) and len(steps) >= 3, f"卡住必须返回统一 steps[]：{stuck}")
    assert_true(all(step.get("action") and step.get("success_rule") for step in steps), f"每一步必须可执行且有完成标准：{steps}")
    resumed = assert_status(client.post(f"/api/daily-tasks/{task_id}/event", json={"event_type": "resume"}))
    assert_true(resumed["status"] == "in_progress", f"继续后状态不正确：{resumed}")
    completed = assert_status(client.post(f"/api/daily-tasks/{task_id}/event", json={"event_type": "complete"}))
    assert_true(completed["status"] == "checking", f"做完后应进入检查：{completed}")
    duplicate = assert_status(client.post(f"/api/daily-tasks/{task_id}/event", json={"event_type": "complete"}))
    assert_true(duplicate.get("already_applied") is True, f"做完按钮应幂等：{duplicate}")

    with get_conn() as conn:
        complete_count = conn.execute(
            "SELECT COUNT(*) FROM task_progress WHERE daily_task_id = ? AND event_type = 'complete'",
            (task_id,),
        ).fetchone()[0]
    assert_true(complete_count == 1, f"重复完成不应重复写事件：{complete_count}")
    return task_id


def assert_quiz_quality(client: Any, get_conn: Any, task_id: int) -> None:
    quiz = assert_status(client.get(f"/api/daily-tasks/{task_id}/quiz"))
    assert_true(len(quiz["items"]) >= 3, f"小测至少 3 题：{quiz}")
    assert_true(all("answer" not in item for item in quiz["items"]), "孩子端小测不应暴露答案")
    assert_true(all("explanation" not in item for item in quiz["items"]), "孩子端小测不应暴露解析")
    assert_true(quiz.get("quality", {}).get("score", 0) >= 0.8, f"小测质量分不足：{quiz.get('quality')}")
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT question, answer, source_ref, quality_score FROM quiz_items WHERE daily_task_id = ?",
            (task_id,),
        ).fetchall()
        assert_true(rows, "数据库应有小测题")
        assert_true(all(row["source_ref"] for row in rows), f"小测题 source_ref 不能为空：{[dict(row) for row in rows]}")
        for row in rows:
            answer = str(row["answer"]).strip()
            question = str(row["question"]).strip()
            if answer and len(answer) >= 2:
                assert_true(answer.lower() not in question.lower(), f"题干疑似泄露答案：{dict(row)}")


def assert_parent_and_reports(client: Any) -> None:
    dashboard = assert_status(client.get("/api/parent/dashboard"))
    assert_true("target_95" in dashboard, f"家长端必须有 95+ 看板：{dashboard.keys()}")
    assert_true("daily_adjustment" in dashboard, f"家长端必须有每日调整：{dashboard.keys()}")
    insights = assert_status(client.get("/api/parent/insights"))
    assert_true("readiness_score" in insights and "weak_points" in insights, f"洞察结构不完整：{insights}")
    report = assert_status(client.post("/api/day/end"))
    assert_true("summary" in report and "tomorrow_first_step" in report, f"日报结构不完整：{report}")


def assert_security_hygiene() -> None:
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert_true(".env" in gitignore and "data/*.db" in gitignore, ".gitignore 必须忽略 .env 和 data/*.db")
    tracked = os.popen("git ls-files").read().splitlines()
    forbidden = [path for path in tracked if path.endswith(".env") or path.endswith("learning.db") or path.endswith(".db")]
    assert_true(not forbidden, f"禁止提交密钥/数据库文件：{forbidden}")
    cached = subprocess.run(["git", "diff", "--cached", "--", "."], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="ignore", check=False)
    working = subprocess.run(["git", "diff", "--", "."], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="ignore", check=False)
    diff_text = f"{cached.stdout}\n{working.stdout}"
    assert_true(not re.search(r"sk-[A-Za-z0-9_-]{20,}", diff_text), "diff 中疑似包含真实 API Key")


def main() -> None:
    configure_env()
    sys.path.insert(0, str(ROOT))
    from fastapi.testclient import TestClient
    from backend.app import app
    from backend.db import get_conn, init_db

    init_db()
    with TestClient(app) as client:
        assert_status(client.get("/api/health"))
        seed_materials(client)
        assert_rag_quality(client, get_conn)
        task_id = assert_plan_to_child_flow(client, get_conn)
        assert_quiz_quality(client, get_conn, task_id)
        assert_parent_and_reports(client)
        assert_security_hygiene()
    print("SENIOR_QA_GATE_OK")


if __name__ == "__main__":
    main()
