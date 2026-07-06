from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def configure_env() -> None:
    temp_dir = Path(tempfile.mkdtemp(prefix="learning-companion-7day-"))
    os.environ["DATABASE_PATH"] = str(temp_dir / "learning.db")
    os.environ["AI_ENABLED"] = "false"
    os.environ["ENABLE_SCHEDULER"] = "false"
    os.environ["NOTIFY_CHANNEL"] = "none"
    os.environ["CHILD_PASSWORD"] = ""
    os.environ["PARENT_PASSWORD"] = ""
    os.environ["ADMIN_PASSWORD"] = ""


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    configure_env()
    from fastapi.testclient import TestClient

    from backend.app import app
    from backend.db import get_conn, init_db
    from backend.knowledge_schema import coverage_summary
    from scripts.seed_core_materials import main as seed_core_materials

    init_db()
    seed_core_materials()
    client = TestClient(app)

    raw_plan = "暑假作业本每日一小节；语文书每日一篇课文；数学书每日一节；英语 Unit 1 每天听写 5 个单词"
    plan = client.post("/api/study-plan/generate", data={"raw_text": raw_plan, "student_id": "1"}).json()
    assert_true(plan.get("created", 0) >= 4, f"plan should create multiple sources: {plan}")

    start = date.today()
    daily_reports = []
    for offset in range(7):
        day = (start + timedelta(days=offset)).isoformat()
        generated = client.post("/api/agent/daily-tasks", json={"target_date": day, "force_all_sources": True}).json()
        tasks = generated.get("tasks", [])
        assert_true(tasks, f"day {day} should have tasks")
        task = tasks[0]
        task_id = int(task["id"])
        client.post(f"/api/daily-tasks/{task_id}/event", json={"event_type": "start"})
        if offset in {1, 3, 5}:
            stuck = client.post(f"/api/daily-tasks/{task_id}/event", json={"event_type": "stuck", "note": "不理解第一步"}).json()
            assert_true(stuck.get("tool_loop", {}).get("mode") == "controlled_tool_loop", f"stuck should use tool loop: {stuck}")
            client.post(f"/api/daily-tasks/{task_id}/event", json={"event_type": "start"})
        quiz = client.get(f"/api/daily-tasks/{task_id}/quiz").json()
        items = quiz.get("items", [])
        assert_true(len(items) >= 3, f"quiz should have items: {quiz}")
        with get_conn() as conn:
            answer_rows = conn.execute("SELECT id, answer FROM quiz_items WHERE daily_task_id = ? ORDER BY id", (task_id,)).fetchall()
        if offset in {2, 4}:
            answers = {str(row["id"]): "故意错误" for row in answer_rows}
        else:
            answers = {str(row["id"]): row["answer"] for row in answer_rows}
        graded = client.post(f"/api/daily-tasks/{task_id}/quiz", json={"answers": answers}).json()
        assert_true("target_95_mastery_update" in graded, f"grading should update mastery: {graded}")
        report = client.post("/api/agent/daily-report", json={"student_id": 1, "target_date": day}).json()
        assert_true(report.get("summary") or report.get("tasks"), f"daily report should summarize: {report}")
        daily_reports.append({"date": day, "task_count": len(tasks), "graded_status": graded.get("status"), "score": graded.get("score", {})})

    with get_conn() as conn:
        review_count = conn.execute("SELECT COUNT(*) AS count FROM review_items").fetchone()["count"]
        trace_count = conn.execute("SELECT COUNT(*) AS count FROM agent_trace_steps").fetchone()["count"]
        mastery_count = conn.execute("SELECT COUNT(*) AS count FROM skill_mastery").fetchone()["count"]
        knowledge_count = conn.execute("SELECT COUNT(*) AS count FROM knowledge_points").fetchone()["count"]
    result = {
        "status": "SIMULATE_7_DAY_OK",
        "days": daily_reports,
        "review_count": review_count,
        "trace_count": trace_count,
        "mastery_count": mastery_count,
        "knowledge_count": knowledge_count,
        "core_coverage": coverage_summary(),
    }
    assert_true(review_count >= 1, f"low-score days should create review items: {result}")
    assert_true(trace_count >= 7, f"agent traces should be recorded: {result}")
    assert_true(mastery_count >= 1, f"mastery should be updated: {result}")
    assert_true(knowledge_count >= 80, f"knowledge graph should be populated: {result}")

    report_dir = ROOT / "reports" / "simulation"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "seven_day_learning_report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# Seven Day Learning Simulation", "", f"- Status: `{result['status']}`", f"- Review items: `{review_count}`", f"- Trace steps: `{trace_count}`", f"- Mastery records: `{mastery_count}`", f"- Knowledge points: `{knowledge_count}`", ""]
    for day in daily_reports:
        lines.append(f"- `{day['date']}`: tasks `{day['task_count']}`, graded `{day['graded_status']}`")
    (report_dir / "seven_day_learning_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
