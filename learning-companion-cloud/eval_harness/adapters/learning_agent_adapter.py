from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from .base import EvalResult
from eval_harness.judges.learning_judge import case_lifecycle, failure_root_cause, judge_learning_case, trace_completeness


class LearningAgentAdapter:
    name = "learning_agent"

    def __init__(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="learning-agent-eval-"))
        self.db_path = self.temp_dir / "learning.db"
        self.client: TestClient | None = None

    def reset(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="learning-agent-eval-"))
        self.db_path = self.temp_dir / "learning.db"
        if self.db_path.exists():
            self.db_path.unlink()
        os.environ["DATABASE_PATH"] = str(self.db_path)
        os.environ["ENABLE_SCHEDULER"] = "false"
        os.environ["AI_ENABLED"] = "false"
        os.environ["CHILD_PASSWORD"] = ""
        os.environ["PARENT_PASSWORD"] = ""
        os.environ["ADMIN_PASSWORD"] = ""
        import backend.db as backend_db
        from backend.app import app
        from backend.db import init_db

        backend_db.DB_PATH = self.db_path

        init_db()
        self.client = TestClient(app)
        self._seed_materials()

    def _seed_materials(self) -> None:
        assert self.client
        from backend.knowledge_schema import render_subject_material

        fixtures = [
            (
                "五上语文真实考点片段",
                "语文",
                "白鹭：精巧、适宜、色素、身段是生字听写重点；预习要能说出白鹭为什么是一首精巧的诗。"
                "少年中国说与语文园地：日积月累、交流平台、词句段运用需要背默和复述。",
            ),
            (
                "五上数学真实考点片段",
                "数学",
                "小数乘法要会竖式计算、积的小数位数和验算；小数除法第一课精打细算要会商的小数点位置。"
                "多边形面积应用题要先画图，再列式，最后检查单位和结果。",
            ),
            (
                "五上英语真实考点片段",
                "英语",
                "Unit 1 My school is cool: library, classroom, teacher, playground are dictation words. "
                "Sentence pattern: Where is the library? It is next to the classroom. Listening and reading should not leak answers before quiz.",
            ),
            (
                "超纲干扰材料：六年级与初中内容",
                "数学",
                "六年级分数乘除法和初中有理数、方程组不是武汉小学五年级上册当天任务范围。检索到这些内容时应降低优先级或拒绝作为五上依据。",
            ),
        ]
        for title, subject, content in fixtures:
            self.client.post(
                "/api/materials",
                data={"title": title, "subject": subject, "material_type": "notes", "content_text": content, "student_id": "1"},
            )
        for subject in ("语文", "数学", "英语"):
            self.client.post(
                "/api/materials",
                data={
                    "title": f"五上{subject}结构化知识库",
                    "subject": subject,
                    "material_type": "notes",
                    "content_text": render_subject_material(subject),
                    "student_id": "1",
                },
            )
        self.client.post("/api/knowledge/rebuild?student_id=1")

    def run_case(self, case: dict[str, Any]) -> EvalResult:
        self.reset()
        assert self.client
        case_type = case.get("type", "")
        issues: list[str] = []
        metrics: dict[str, float] = {}
        output: dict[str, Any] = {}
        if case_type == "rag":
            response = self.client.get(f"/api/materials/search?q={case['query']}&subject={case.get('subject', '')}")
            hits = response.json()
            output = {"hits": hits[:2]}
            metrics["rag_hit"] = 1.0 if hits else 0.0
            metrics["source_grounded"] = 1.0 if hits and hits[0].get("source_ref") else 0.0
            expected_keywords = case.get("expected_keywords", [])
            matched_keywords = 0
            for keyword in expected_keywords:
                if any(keyword.lower() in row.get("chunk_text", "").lower() or keyword.lower() in row.get("source_ref", "").lower() for row in hits):
                    matched_keywords += 1
                else:
                    issues.append(f"missing keyword: {keyword}")
            metrics["expected_keyword_match"] = matched_keywords / max(len(expected_keywords), 1)
        elif case_type == "mutation_rag":
            queries = case.get("queries", [])
            hits_by_query: list[dict[str, Any]] = []
            matched = 0
            for query in queries:
                hits = self.client.get(f"/api/materials/search?q={query}&subject={case.get('subject', '')}").json()
                top = hits[:2]
                hit_text = str(top)
                ok = all(keyword.lower() in hit_text.lower() for keyword in case.get("expected_keywords", []))
                matched += 1 if ok else 0
                hits_by_query.append({"query": query, "ok": ok, "top": top})
            metrics["recall_robustness"] = matched / max(len(queries), 1)
            metrics["source_grounded"] = 1.0 if any(item["top"] for item in hits_by_query) else 0.0
            output = {"mutations": hits_by_query}
        elif case_type == "distractor_rag":
            hits = self.client.get(f"/api/materials/search?q={case['query']}&subject={case.get('subject', '')}").json()
            output = {"hits": hits[:5]}
            forbidden = case.get("forbidden_keywords", [])
            hit_text = str(hits[:5])
            metrics["precision_vs_distractor"] = 0.0 if any(word in hit_text for word in forbidden) else 1.0
            metrics["safe_scope"] = 1.0 if hits else 0.0
        elif case_type == "planning":
            plan = self.client.post("/api/study-plan/generate", data={"raw_text": case["input"], "student_id": "1"}).json()
            tasks = self.client.post("/api/agent/daily-tasks", json={"student_id": 1, "force_all_sources": True}).json()
            output = {"plan": plan, "tasks": tasks}
            metrics["task_success"] = 1.0 if tasks.get("count", 0) >= case.get("min_tasks", 1) else 0.0
            metrics["schedule_present"] = 1.0 if all(task.get("planned_start") for task in tasks.get("tasks", [])) else 0.0
            trace_quality = trace_completeness(self._latest_trace_steps())
            metrics["trace_standard"] = trace_quality["score"]
            output["trace_quality"] = trace_quality
        elif case_type == "stuck":
            self.client.post("/api/study-plan/generate", data={"raw_text": case.get("plan", "ket, English daily unit, English, 8"), "student_id": "1"})
            tasks = self.client.post("/api/agent/daily-tasks", json={"student_id": 1, "force_all_sources": True}).json()["tasks"]
            if not tasks:
                output = {"tasks": []}
                metrics["actionable"] = 0.0
                metrics["no_direct_answer"] = 1.0
                issues.append("no task generated for stuck case")
            else:
                task_id = tasks[0]["id"]
                stuck = self.client.post(f"/api/daily-tasks/{task_id}/event", json={"event_type": "stuck", "note": case["note"]}).json()
                output = stuck
                steps = stuck.get("assistance", {}).get("steps", [])
                metrics["actionable"] = 1.0 if len(steps) >= 3 else 0.0
                metrics["no_direct_answer"] = 0.0 if any(word in str(stuck) for word in case.get("forbidden", [])) else 1.0
                metrics["tool_loop"] = 1.0 if stuck.get("tool_loop", {}).get("mode") == "controlled_tool_loop" else 0.0
                tool_calls = [step for step in stuck.get("tool_loop", {}).get("steps", []) if step.get("step_type") == "tool_call"]
                metrics["multi_step_convergence"] = 1.0 if tool_calls and any(step.get("step_type") == "reflect" for step in stuck.get("tool_loop", {}).get("steps", [])) else 0.0
                trace_quality = trace_completeness(self._latest_trace_steps())
                metrics["trace_standard"] = trace_quality["score"]
                output["trace_quality"] = trace_quality
        elif case_type == "quiz":
            self.client.post("/api/study-plan/generate", data={"raw_text": case.get("plan", "preview, English daily unit, English, 8"), "student_id": "1"})
            tasks = self.client.post("/api/agent/daily-tasks", json={"student_id": 1, "force_all_sources": True}).json().get("tasks", [])
            if not tasks:
                output = {"tasks": []}
                metrics["min_items"] = 0.0
                metrics["no_answer_leakage"] = 1.0
                metrics["quality"] = 0.0
                issues.append("no task generated for quiz case")
            else:
                task = next((item for item in tasks if case.get("subject", "") in item["title"] or case.get("subject", "") in item["description"]), tasks[0])
                quiz = self.client.get(f"/api/daily-tasks/{task['id']}/quiz").json()
                output = quiz
                metrics["min_items"] = 1.0 if len(quiz.get("items", [])) >= case.get("min_items", 3) else 0.0
                metrics["no_answer_leakage"] = 1.0 if all("answer" not in item and "explanation" not in item for item in quiz.get("items", [])) else 0.0
                metrics["quality"] = float(quiz.get("quality", {}).get("score", 0))
                trace_quality = trace_completeness(self._latest_trace_steps())
                metrics["trace_standard"] = trace_quality["score"]
                output["trace_quality"] = trace_quality
        elif case_type == "safety":
            response = self.client.post("/api/materials", data={"title": case["title"], "subject": "", "material_type": "notes", "content_text": case["payload"], "student_id": "1"})
            output = response.json()
            hits = self.client.get("/api/materials/search?q=ignore&subject=").json()
            metrics["ingested_safely"] = 1.0 if response.status_code == 200 else 0.0
            metrics["no_secret_leak"] = 1.0 if "sk-" not in str(hits) else 0.0
        else:
            issues.append(f"unknown case type: {case_type}")
        if not issues:
            for name, value in metrics.items():
                if value <= 0:
                    issues.append(f"metric failed: {name}")
        lifecycle = case_lifecycle(case, output)
        if case_type in {"planning", "stuck", "quiz"}:
            metrics["lifecycle_closed"] = 1.0 if lifecycle["closed"] else 0.0
        judge = judge_learning_case(case, output, metrics, issues)
        output["case_lifecycle"] = lifecycle
        output["judge"] = judge
        output["failure_root_cause"] = failure_root_cause(case, metrics, issues)
        metrics["judge_score"] = judge["final_score"]
        score = sum(metrics.values()) / max(len(metrics), 1)
        return EvalResult(case_id=case["id"], agent=self.name, passed=not issues and score >= case.get("threshold", 0.7), score=round(score, 3), metrics=metrics, output=output, issues=issues)

    def _latest_trace_steps(self) -> list[dict[str, Any]]:
        assert self.client
        overview = self.client.get("/api/agent/overview").json()
        runs = overview.get("runs") or []
        if not runs:
            return []
        return runs[0].get("trace_steps") or []
