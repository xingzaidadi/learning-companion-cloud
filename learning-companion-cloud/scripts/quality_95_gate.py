
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def score_items(items: list[tuple[str, bool]]) -> tuple[float, list[str]]:
    passed = sum(1 for _name, ok in items if ok)
    failed = [name for name, ok in items if not ok]
    return round(passed / max(len(items), 1) * 10, 2), failed


def count_cases(path: str) -> int:
    data = json.loads(read(path))
    return len(data.get("cases", []))


def has_quality(html: str, token: str) -> bool:
    return f"data-quality" in html and token in html


def main() -> None:
    child = read("frontend/child.html")
    parent = read("frontend/parent.html")
    admin = read("frontend/admin.html")
    css = read("frontend/static/styles.css")
    agent_tools = read("backend/agent_tools.py")
    tool_registry = read("backend/agent_tool_registry.py")
    agent_runtime = read("backend/agent_runtime.py")
    agent_core = read("backend/agent_core.py")
    rag_engine = read("backend/rag_engine.py")
    knowledge_schema = read("backend/knowledge_schema.py")
    grading_rubrics = read("backend/grading_rubrics.py")
    eval_runner = read("eval_harness/runners/eval_runner.py")
    backend_report = read("backend/report.py")
    backend_app = read("backend/app.py")
    backend_agent = read("backend/agent.py")

    double_question = "?" * 2
    four_questions = "?" * 4
    visible_question_mark_noise = [
        f'content: "{double_question}"',
        f"content: '{double_question}'",
        f">{double_question}<",
        f"{double_question}</span>",
        f"{double_question}</small>",
        f"{double_question}</p>",
        four_questions,
    ]

    checks: dict[str, list[tuple[str, bool]]] = {
        "child_ui": [
            ("one_current_focus", has_quality(child, "child-one-focus") and "currentTask" in child),
            ("light_progress", has_quality(child, "child-thin-progress") and "thin-progress" in child and "progress-orb" not in child),
            ("collapsible_workspace", has_quality(child, "child-collapsible-workspace") and "workspace.open = true" in child),
            ("collapsible_queue", has_quality(child, "child-collapsible-queue")),
            ("progressive_disclosure", has_quality(child, "child-progressive-disclosure") and child.count("<details") >= 2),
            ("reduced_button_noise", "secondaryButtons" in child and "primaryButton" in child),
            ("test_artifacts_hidden", "135442" not in child and four_questions not in child),
            ("child_no_html_entities", "&#26816;" not in child and "&#27491;" not in child),
        ],
        "parent_ui": [
            ("three_question_model", has_quality(parent, "parent-three-questions")),
            ("summary_first", has_quality(parent, "parent-summary-first") and "parentSummary" in parent),
            ("action_focus", has_quality(parent, "parent-action-focus") and "parentActions" in parent),
            ("progressive_details", has_quality(parent, "parent-progressive-details") and parent.count("<details") >= 4),
            ("compact_report_cards", has_quality(parent, "parent-compact-report") and "parent-report-mini" in parent and "parent-report-mini" in css),
            ("not_flat_dump", ("?" * 6) not in parent and f"Agent {four_questions}" not in parent),
        ],
        "admin_ui": [
            ("natural_plan_primary", has_quality(admin, "admin-natural-plan") and "quickPlanForm" in admin),
            ("primary_plan_card", has_quality(admin, "admin-primary-plan-card")),
            ("advanced_collapsed", has_quality(admin, "admin-advanced-collapsed") and "admin-advanced-area" in admin and "<details" in admin),
            ("agent_audit", has_quality(admin, "admin-agent-audit") and "showTrace" in admin),
            ("rag_quality_visible", has_quality(admin, "admin-rag-quality") and "coverage" in admin),
            ("three_core_actions", has_quality(admin, "admin-three-core-actions") and all(key in admin for key in ("quickPlanSubmit", "generateToday", "refresh"))),
        ],
        "agent_design": [
            ("explainable_run_summary", all(key in agent_tools for key in ("reason", "result", "impact", "next_action", "metrics"))),
            ("function_schema", all(key in tool_registry for key in ("parameters", "required", "output_schema", "side_effect", "idempotent"))),
            ("tool_validation_consumed", "validate_tool_call" in tool_registry and "tool_validation" in backend_agent),
            ("controlled_tool_loop", "run_controlled_tool_loop" in agent_runtime and "select_tool" in agent_runtime and "controlled_tool_loop" in backend_agent),
            ("hybrid_rag_scoring", "retrieval_method" in agent_core and "hybrid_keyword_vector_embedding" in agent_core and "embedding_score_for_chunk" in agent_core),
            ("persistent_embedding_rag", "material_embeddings" in read("backend/db.py") and "local_embedding" in rag_engine and "upsert_chunk_embedding" in rag_engine),
            ("structured_knowledge_base", "iter_core_knowledge" in knowledge_schema and "CHINESE_UNITS" in knowledge_schema and "MATH_UNITS" in knowledge_schema and "ENGLISH_UNITS" in knowledge_schema),
            ("grading_rubrics", "rubric_for_item" in grading_rubrics and "grading_rubric_json" in read("backend/quiz.py")),
            ("trajectory_trace", "agent_trace_steps" in agent_tools and "trace_id" in agent_tools),
            ("multi_agent_eval", "LearningAgentAdapter" in eval_runner and "DemoAgentAdapter" in eval_runner),
            ("eval_known_gaps", "known_gap_cases" in eval_runner and "unexpected_failed_cases" in eval_runner),
            ("redteam_cases", count_cases("eval_harness/datasets/learning_agent/golden_set.json") >= 200),
            ("daily_report_compaction", "def _short_title" in backend_report and "def _count_line" in backend_report and "quiz_summary" not in backend_report and four_questions not in backend_report),
            ("display_sanitizer", all(key in backend_app for key in ("_clean_display_text", "_sanitize_task_for_display", "_sanitize_report_for_display"))),
        ],
        "tests": [
            ("senior_qa_gate", (ROOT / "scripts/senior_qa_gate.py").exists()),
            ("ui_click_test", (ROOT / "scripts/ui_click_test.py").exists()),
            ("full_ui_audit", (ROOT / "scripts/full_ui_audit.py").exists()),
            ("ui_design_rubric", (ROOT / "scripts/ui_design_rubric.py").exists()),
            ("child_flow_test", (ROOT / "scripts/child_flow_integration_test.py").exists()),
            ("db_concurrency_test", (ROOT / "scripts/db_concurrency_test.py").exists()),
            ("seven_day_simulation", (ROOT / "scripts/simulate_7_day_learning.py").exists()),
            ("knowledge_seed_script", (ROOT / "scripts/seed_core_materials.py").exists() and (ROOT / "data/knowledge/coverage_summary.json").exists()),
            ("eval_cases_80_plus", count_cases("eval_harness/datasets/learning_agent/golden_set.json") + count_cases("eval_harness/datasets/demo_agent/golden_set.json") >= 80),
            ("github_actions", (ROOT.parent / ".github/workflows/qa.yml").exists() and (ROOT.parent / ".github/workflows/agent-eval.yml").exists()),
        ],
        "visual_system": [
            ("design_tokens", all(token in css for token in ("--primary", "--muted", "--line", "--radius"))),
            ("responsive", "@media (max-width: 820px)" in css),
            ("collapsible_styles", "child-detail-card" in css and "details.card" in css),
            ("parent_layout", "parent-layout" in css and "parent-detail-grid" in css),
            ("agent_audit_styles", "agent-run-card" in css and "agent-trace-panel" in css),
            ("no_visible_question_mark_noise", not any(noise in child + parent + admin + css for noise in visible_question_mark_noise)),
            ("css_collapsible_labels_not_garbled", f'content: "{double_question}"' not in css and "\\5c55\\5f00" in css and "\\6536\\8d77" in css),
        ],
    }

    report = {"sections": {}, "overall_score": 0.0, "failed": []}
    scores = []
    for section, items in checks.items():
        score, failed = score_items(items)
        scores.append(score)
        report["sections"][section] = {"score": score, "failed": failed, "total": len(items)}
        report["failed"].extend([f"{section}.{name}" for name in failed])
    report["overall_score"] = round(sum(scores) / len(scores), 2)

    output_dir = ROOT / "reports" / "quality"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "quality_95_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# 9.5 Quality Gate", "", f"- Overall score: `{report['overall_score']}`", ""]
    for section, item in report["sections"].items():
        status = "passed" if not item["failed"] else "failed: " + ", ".join(item["failed"])
        lines.append(f"- `{section}`: `{item['score']}` / 10; {status}")
    (output_dir / "quality_95_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(json.dumps(report, ensure_ascii=False))
    assert_true(report["overall_score"] >= 9.5, f"overall score below 9.5: {report}")
    assert_true(not report["failed"], f"quality gate failures: {report['failed']}")


if __name__ == "__main__":
    main()
