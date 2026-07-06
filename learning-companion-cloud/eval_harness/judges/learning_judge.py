from __future__ import annotations

from typing import Any


TRACE_REQUIRED_TYPES = {"goal", "plan", "decision", "tool_call", "observation", "evaluate", "supervise", "final"}


def judge_learning_case(case: dict[str, Any], output: dict[str, Any], metrics: dict[str, float], issues: list[str]) -> dict[str, Any]:
    """Three-layer judge result for learning Agent evals.

    The first layer is deterministic rule assertions, the second layer is an
    LLM-as-Judge compatible rubric interface with deterministic fallback, and
    the third layer is a human-audit rubric summary for sampling.
    """

    rule_score = _rule_score(metrics, issues)
    llm_judge = _llm_judge_fallback(case, output, metrics)
    human_rubric = _human_rubric(case, output, issues)
    final_score = round(rule_score * 0.55 + llm_judge["score"] * 0.3 + human_rubric["score"] * 0.15, 3)
    return {
        "version": "learning-judge-v1",
        "rule_score": round(rule_score, 3),
        "llm_judge": llm_judge,
        "human_rubric": human_rubric,
        "final_score": final_score,
        "passed": final_score >= float(case.get("threshold", 0.7)) and not issues,
    }


def trace_completeness(trace_steps: list[dict[str, Any]]) -> dict[str, Any]:
    observed = {str(step.get("step_type") or "") for step in trace_steps}
    missing = sorted(TRACE_REQUIRED_TYPES - observed)
    typed = len(observed & TRACE_REQUIRED_TYPES)
    score = typed / len(TRACE_REQUIRED_TYPES)
    has_reasoning = all(str(step.get("thought") or step.get("reason") or "").strip() for step in trace_steps[:3]) if trace_steps else False
    if has_reasoning:
        score = min(1.0, score + 0.1)
    return {"score": round(score, 3), "missing": missing, "observed": sorted(observed), "has_reasoning": has_reasoning}


def case_lifecycle(case: dict[str, Any], output: dict[str, Any]) -> dict[str, Any]:
    case_type = case.get("type", "")
    stages = ["setup", "execute", "assert", "diagnose"]
    if case_type in {"stuck", "quiz", "planning"}:
        stages.append("trace")
    if case_type in {"quiz", "stuck"}:
        stages.append("remediate")
    closed = bool(output) and not output.get("tasks") == []
    return {"stages": stages, "closed": closed, "case_type": case_type}


def failure_root_cause(case: dict[str, Any], metrics: dict[str, float], issues: list[str]) -> str:
    if not issues:
        return "pass"
    if any("missing keyword" in issue for issue in issues):
        return "rag_recall_gap"
    if any("no task generated" in issue for issue in issues):
        return "planning_gap"
    failed_metrics = [name for name, value in metrics.items() if value <= 0]
    if failed_metrics:
        return "metric_failed:" + ",".join(failed_metrics[:3])
    if case.get("expected_result") == "known_gap":
        return "known_gap"
    return "unknown"


def _rule_score(metrics: dict[str, float], issues: list[str]) -> float:
    if not metrics:
        return 0.0 if issues else 0.7
    score = sum(float(value) for value in metrics.values()) / len(metrics)
    if issues:
        score *= 0.6
    return max(0.0, min(1.0, score))


def _llm_judge_fallback(case: dict[str, Any], output: dict[str, Any], metrics: dict[str, float]) -> dict[str, Any]:
    text = str(output)
    no_answer_leak = "answer" not in text.lower() or case.get("type") not in {"quiz", "stuck"}
    grounded = bool(metrics.get("source_grounded", 1.0)) and bool(output)
    actionable = bool(metrics.get("actionable", 1.0))
    score = 0.4 + (0.25 if no_answer_leak else 0) + (0.2 if grounded else 0) + (0.15 if actionable else 0)
    return {
        "mode": "deterministic_llm_judge_fallback",
        "score": round(min(score, 1.0), 3),
        "rubric": {
            "no_answer_leak": no_answer_leak,
            "grounded": grounded,
            "actionable": actionable,
        },
        "note": "生产环境可打开真实 LLM-as-Judge；离线 CI 使用同一 Rubric 的确定性 fallback。",
    }


def _human_rubric(case: dict[str, Any], output: dict[str, Any], issues: list[str]) -> dict[str, Any]:
    checklist = {
        "input_reproducible": bool(case.get("id")),
        "output_auditable": bool(output),
        "needs_human_sample": case.get("difficulty") in {"hard", "redteam"} or bool(issues),
    }
    score = 0.9 if checklist["input_reproducible"] and checklist["output_auditable"] else 0.5
    if issues:
        score = min(score, 0.6)
    return {"score": score, "checklist": checklist}
