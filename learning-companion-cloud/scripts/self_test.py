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


def run_static_encoding_check() -> None:
    suspicious = tuple(chr(codepoint) for codepoint in (0x951B, 0x93C8, 0x6D60, 0x9225, 0xFFFD)) + ("?" * 4,)
    files = [
        ROOT / "backend" / "app.py",
        ROOT / "backend" / "agent.py",
        ROOT / "backend" / "agent_core.py",
        ROOT / "backend" / "agent_tool_registry.py",
        ROOT / "backend" / "db.py",
        ROOT / "frontend" / "child.html",
        ROOT / "frontend" / "admin.html",
        ROOT / "frontend" / "parent.html",
        ROOT / "eval_harness" / "datasets" / "learning_agent" / "golden_set.json",
    ]
    offenders: list[str] = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        if path.name == "child.html" and any(entity in text for entity in ("&#26816;", "&#27491;", "&#21518;")):
            offenders.append(f"{path.relative_to(ROOT)} contains visible numeric HTML entities")
        for marker in suspicious:
            if marker in text:
                offenders.append(f"{path.relative_to(ROOT)} contains {marker!r}")
                break
    assert_true(not offenders, "发现疑似乱码/实体编码：\n" + "\n".join(offenders))


def run_static_button_inventory_check() -> None:
    pages = {
        "admin.html": ["一句话安排学习", "生成计划并生成今日任务", "补齐/同步今日任务", "检查 AI", "学习资料库"],
        "child.html": ["学习驾驶舱", "今日进度", "当前任务", "检查与求助", "后续任务队列", "我卡住了"],
        "parent.html": ["你现在只需要看这里", "生成今天日报", "生成本周周报", "明天第一步"],
    }
    for page_name, needles in pages.items():
        text = (ROOT / "frontend" / page_name).read_text(encoding="utf-8")
        missing = [needle for needle in needles if needle not in text]
        assert_true(not missing, f"{page_name} 缺少关键文案/按钮：{missing}")


def run_e2e() -> None:
    configure_env()
    sys.path.insert(0, str(ROOT))

    from fastapi.testclient import TestClient
    from backend.agent import _targeted_stuck_help
    from backend.app import app
    from backend.db import get_conn
    from backend.knowledge_schema import coverage_summary

    with TestClient(app) as client:
        assert_true(assert_status(client.get("/api/health"))["status"] == "ok", "health should be ok")
        for path in ("/admin", "/child", "/parent"):
            html = assert_status(client.get(path))
            assert_true("<html" in html.lower(), f"{path} should return HTML")

        settings = assert_status(client.get("/api/settings"))
        assert_true(settings["region"]["city"] == "武汉", "默认城市应为武汉")
        saved_settings = assert_status(client.post("/api/settings", json={"daily_limits": {"max_total_minutes": 100}, "ai": {"enabled": False}}))
        assert_true(saved_settings["daily_limits"]["max_total_minutes"] == 100, "设置保存失败")
        core_coverage = coverage_summary()
        assert_true(core_coverage["total"] >= 300 and all(core_coverage["by_subject"].get(subject, 0) >= 60 for subject in ("语文", "数学", "英语")), f"结构化知识库覆盖不足：{core_coverage}")
        english_stuck = _targeted_stuck_help("英语", "不认识这个单词", "英语预习 Unit 1")
        assert_true(
            english_stuck and "英语单词" in english_stuck["review_focus"] and "生字" not in english_stuck["review_focus"],
            f"英语卡住不能误判成中文生字：{english_stuck}",
        )

        plan = assert_status(client.post("/api/study-plan/generate", data={"raw_text": "暑假作业本每日一小节；语文书每日一篇课文；数学书每日一节；英语 Unit 1 每天听写 5 个单词", "student_id": "1"}))
        subjects = {item.get("subject") for item in plan.get("items", [])}
        categories = {item.get("category") for item in plan.get("items", [])}
        assert_true(plan["created"] >= 4 and {"语文", "数学", "英语"}.issubset(subjects) and "summer_homework" in categories, f"多来源计划生成失败：{plan}")
        full_prompt = "暑假作业、KET备考、预习五年级上册语文数学英语。数学暑假作业本22小节已完成3，数学口算29页，数学每日一练48页。英语暑假作业本14 Day已完成3。语文诵读一夏12个已完成3，妙笔一下37个已完成3每天4个，阅读7本书，一本7个，电影寻梦环游记，每天运动1小时。数学目录：观察简单组合体、小数乘法、小数除法、图形的运动、用字母表示数和数量关系、多边形的面积、有趣的密铺。"
        full_plan = assert_status(client.post("/api/study-plan/generate", data={"raw_text": full_prompt, "student_id": "1"}))
        full_titles = [item.get("title", "") for item in full_plan.get("items", [])]
        assert_true(full_plan["created"] >= 13, f"完整暑假规划应提取出作业/KET/预习/阅读/运动等任务源：{full_plan}")
        assert_true(all("?" not in title for title in full_titles), f"完整规划不能生成问号标题：{full_titles}")
        generated = assert_status(client.post("/api/daily-tasks/generate"))
        assert_true(generated["count"] >= 1, f"今日任务生成失败：{generated}")
        assert_true(all(task.get("planned_start") and task.get("planned_end") for task in generated["tasks"]), "任务应有学习时间段")
        task_text = "\n".join(f"{task.get('title', '')} {task.get('description', '')}" for task in generated["tasks"])
        mixed_markers = {
            "数学": any(word in task_text for word in ("数学", "口算", "小数")),
            "语文": any(word in task_text for word in ("语文", "诵读", "妙笔", "阅读", "一本")),
            "英语": any(word in task_text for word in ("英语", "KET", "Unit")),
            "运动": any(word in task_text for word in ("运动", "跳绳")),
        }
        assert_true(sum(1 for ok in mixed_markers.values() if ok) >= 4, f"完整长提示词生成的今日任务必须语数英运动穿插：{mixed_markers} {generated['tasks']}")
        math_count = sum(1 for task in generated["tasks"] if any(word in f"{task.get('title', '')} {task.get('description', '')}" for word in ("数学", "口算", "小数")))
        assert_true(math_count <= 3, f"数学任务不能过重堆叠：math_count={math_count} tasks={generated['tasks']}")
        ket_tasks = [task for task in generated["tasks"] if "KET" in task.get("title", "")]
        assert_true(ket_tasks and any("词汇 + 听力" in task.get("title", "") for task in ket_tasks), f"KET 周一应生成具体技能轮换任务，而不是泛泛备考：{ket_tasks}")
        assert_true(any("复习 10 个词" in task.get("description", "") and "听" in task.get("description", "") for task in ket_tasks), f"KET 今日任务应包含可执行步骤：{ket_tasks}")
        ket_quiz = assert_status(client.get(f"/api/daily-tasks/{ket_tasks[0]['id']}/quiz"))
        ket_quiz_text = "\n".join(item.get("question", "") for item in ket_quiz.get("items", []))
        assert_true("KET" in ket_quiz_text or "听力" in ket_quiz_text or "英文" in ket_quiz_text, f"KET 小测应围绕 KET/英语能力：{ket_quiz_text}")
        assert_true("精确计算" not in ket_quiz_text and "小数" not in ket_quiz_text, f"KET 小测不能被数学资料带偏：{ket_quiz_text}")
        timeline = assert_status(client.get("/api/day-timeline"))
        blocks = timeline.get("blocks", [])
        block_text = "\n".join(f"{block.get('start')}-{block.get('end')} {block.get('kind')} {block.get('title')}" for block in blocks)
        assert_true(blocks and blocks[0]["start"] == "08:30" and blocks[-1]["end"] == "21:00", f"全天动态安排应覆盖 08:30-21:00：{blocks}")
        assert_true(any(block.get("kind") == "break" for block in blocks), f"全天安排应显式展示休息块：{block_text}")
        assert_true(any("午餐" in block.get("title", "") for block in blocks), f"全天安排应展示午餐午休：{block_text}")
        assert_true(any("晚餐" in block.get("title", "") for block in blocks), f"全天安排应展示晚餐放松：{block_text}")
        assert_true(any(block.get("kind") == "movement" for block in blocks), f"全天安排应展示运动块：{block_text}")
        ket_difficulty = assert_status(client.get("/api/ket/difficulty"))
        assert_true(ket_difficulty.get("suggested_level") in {"light", "standard", "advanced"}, f"KET 难度建议应可用：{ket_difficulty}")
        adjusted = assert_status(client.post("/api/day/adjust", json={"mode": "lighter", "student_id": 1}))
        assert_true(adjusted.get("timeline", {}).get("blocks"), f"一键调整后应返回新的全天表：{adjusted}")
        assert_true(adjusted.get("mode") == "lighter", f"一键调整模式应生效：{adjusted}")

        material = assert_status(client.post("/api/materials", data={
            "student_id": "1",
            "subject": "语文",
            "material_type": "notes",
            "title": "五上语文白鹭考点",
            "content_text": "白鹭：精巧、适宜、色素、身段是生字听写重点。语文园地包含日积月累和交流平台。",
        }))
        assert_true(material["rag_index"]["count"] >= 1, f"资料应建立 RAG 切片：{material}")
        with get_conn() as conn:
            embedding_count = conn.execute("SELECT COUNT(*) AS count FROM material_embeddings").fetchone()["count"]
        assert_true(embedding_count >= 1, "资料索引应同步写入 embedding 表")
        hits = assert_status(client.get("/api/materials/search?q=白鹭 精巧&subject=语文"))
        assert_true(any("白鹭" in hit["chunk_text"] for hit in hits), f"中文 RAG 应命中白鹭资料：{hits}")
        assert_true(any(hit.get("retrieval_method") == "hybrid_bm25_semantic_embedding" for hit in hits), f"RAG 应使用 BM25 + 语义 embedding 融合评分：{hits}")
        assert_true(any(hit.get("embedding_model") for hit in hits), f"RAG 应返回实际 embedding 模型：{hits}")

        tasks = assert_status(client.get("/api/daily-tasks"))
        task = tasks[0]
        task_id = task["id"]
        started = assert_status(client.post(f"/api/daily-tasks/{task_id}/event", json={"event_type": "start"}))
        assert_true(started["status"] in {"in_progress", task.get("status")}, f"开始任务状态异常：{started}")
        paused = assert_status(client.post(f"/api/daily-tasks/{task_id}/event", json={"event_type": "pause"}))
        assert_true("elapsed_seconds" in paused, f"暂停应返回计时信息：{paused}")
        stuck = assert_status(client.post(f"/api/daily-tasks/{task_id}/event", json={"event_type": "stuck", "note": "不理解题目第一步"}))
        assert_true("assistance" in stuck and "tool_validation" in stuck, f"卡住应返回辅导和工具校验：{stuck}")
        assert_true(stuck.get("tool_loop", {}).get("mode") == "controlled_tool_loop", f"卡住辅导应经过受控 Tool Loop：{stuck}")

        quiz = assert_status(client.get(f"/api/daily-tasks/{task_id}/quiz"))
        assert_true(quiz["items"], "小测不能为空")
        assert_true(all("answer" not in item and "explanation" not in item for item in quiz["items"]), "孩子端小测不能泄露答案")
        blank_answers = {str(item["id"]): "" for item in quiz["items"]}
        blank_result = assert_status(client.post(f"/api/daily-tasks/{task_id}/quiz", json={"answers": blank_answers}), 400)
        assert_true("missing" in blank_result["detail"], f"空答案必须被拒绝，不能进入批改：{blank_result}")
        with get_conn() as conn:
            rubric_rows = conn.execute("SELECT grading_rubric_json FROM quiz_items WHERE daily_task_id = ?", (task_id,)).fetchall()
            standard_answers = {
                str(row["id"]): row["answer"]
                for row in conn.execute("SELECT id, answer FROM quiz_items WHERE daily_task_id = ?", (task_id,)).fetchall()
            }
        assert_true(all(row["grading_rubric_json"] and row["grading_rubric_json"] != "{}" for row in rubric_rows), "每道题应有评分 rubric")
        graded = assert_status(client.post(f"/api/daily-tasks/{task_id}/quiz", json={"answers": standard_answers}))
        assert_true(graded["correct"] == graded["total"], f"提交题库标准答案必须全对，不能出现答案与判分规则打架：{graded}")
        assert_true("tool_validation" in graded and "target_95_mastery_update" in graded, f"批改应写入工具校验和掌握度：{graded}")

        report = assert_status(client.post("/api/day/end"))
        assert_true("summary" in report and "tomorrow_first_step" in report, f"日报生成失败：{report}")
        parent = assert_status(client.get("/api/parent/dashboard"))
        visible = str(parent.get("report", {})) + str(parent.get("tasks", [])[:3])
        assert_true("联调验证" not in visible and "135442" not in visible, "家长端不应暴露历史联调脏数据")

        with get_conn() as conn:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        assert_true(timeout >= 5000, "SQLite busy_timeout 应覆盖并发写")
        assert_true(mode.lower() in {"wal", "memory", "delete"}, f"SQLite journal_mode 异常：{mode}")


def main() -> None:
    run_static_encoding_check()
    run_static_button_inventory_check()
    run_e2e()
    print("SELF_TEST_OK")


if __name__ == "__main__":
    main()
