from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from eval_harness.adapters.demo_agent_adapter import DemoAgentAdapter
from eval_harness.adapters.learning_agent_adapter import LearningAgentAdapter


ADAPTERS = {
    "learning_agent": LearningAgentAdapter,
    "demo_agent": DemoAgentAdapter,
}


def dataset_path(agent: str) -> Path:
    base = ROOT / "eval_harness" / "datasets" / agent
    json_path = base / "golden_set.json"
    if json_path.exists():
        return json_path
    raise FileNotFoundError(f"missing golden set for {agent}")


def load_cases(agent: str) -> list[dict[str, Any]]:
    path = dataset_path(agent)
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["cases"]


def summarize(agent: str, case_results: list[tuple[dict[str, Any], Any]]) -> dict[str, Any]:
    results = [result for _case, result in case_results]
    scores = [result.score for result in results]
    passed = [result for result in results if result.passed]
    known_gaps = [result for case, result in case_results if case.get("expected_result") == "known_gap" and not result.passed]
    unexpected_failures = [result for case, result in case_results if case.get("expected_result") != "known_gap" and not result.passed]
    unexpected_passes = [result for case, result in case_results if case.get("expected_result") == "known_gap" and result.passed]
    metric_totals: dict[str, list[float]] = {}
    difficulty_totals: dict[str, list[float]] = {}
    lifecycle_totals: dict[str, int] = {}
    root_causes: dict[str, int] = {}
    for result in results:
        for name, value in result.metrics.items():
            metric_totals.setdefault(name, []).append(float(value))
        case = next(case for case, item in case_results if item.case_id == result.case_id)
        difficulty = str(case.get("difficulty") or "medium")
        difficulty_totals.setdefault(difficulty, []).append(float(result.score))
        lifecycle = result.output.get("case_lifecycle", {}) if isinstance(result.output, dict) else {}
        if lifecycle.get("closed"):
            lifecycle_totals["closed"] = lifecycle_totals.get("closed", 0) + 1
        else:
            lifecycle_totals["open"] = lifecycle_totals.get("open", 0) + 1
        root = result.output.get("failure_root_cause", "unknown") if isinstance(result.output, dict) else "unknown"
        root_causes[root] = root_causes.get(root, 0) + 1
    metrics = {name: round(sum(values) / len(values), 3) for name, values in metric_totals.items()}
    difficulty_scores = {name: round(sum(values) / len(values), 3) for name, values in difficulty_totals.items()}
    return {
        "agent": agent,
        "dataset_version": "v2026.07-controlled-learning-agent",
        "total": len(results),
        "passed": len(passed),
        "pass_rate": round(len(passed) / max(len(results), 1), 3),
        "avg_score": round(sum(scores) / max(len(scores), 1), 3),
        "score_stdev": round(statistics.pstdev(scores), 3) if len(scores) > 1 else 0,
        "metrics": metrics,
        "difficulty_scores": difficulty_scores,
        "case_lifecycle": lifecycle_totals,
        "failure_root_causes": root_causes,
        "failed_cases": [result.case_id for result in results if not result.passed],
        "known_gap_cases": [result.case_id for result in known_gaps],
        "unexpected_failed_cases": [result.case_id for result in unexpected_failures],
        "unexpected_pass_cases": [result.case_id for result in unexpected_passes],
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Agent Eval Report",
        "",
        f"- Generated at: `{report['generated_at']}`",
        f"- Agents: `{', '.join(report['agents'])}`",
        "- Note: `known_gap_cases` are intentional diagnostic red cases; CI fails only on unexpected failures.",
        "",
        "## Summary",
        "",
        "| Agent | Total | Passed | Pass Rate | Avg Score | Known Gaps | Unexpected Failures |",
        "| --- | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for summary in report["summaries"]:
        lines.append(
            f"| {summary['agent']} | {summary['total']} | {summary['passed']} | {summary['pass_rate']} | {summary['avg_score']} | {', '.join(summary['known_gap_cases']) or '-'} | {', '.join(summary['unexpected_failed_cases']) or '-'} |"
        )
    lines.extend(["", "## Metrics", ""])
    for summary in report["summaries"]:
        lines.append(f"### {summary['agent']}")
        for name, value in summary["metrics"].items():
            lines.append(f"- `{name}`: {value}")
        lines.append(f"- Difficulty scores: `{summary.get('difficulty_scores', {})}`")
        lines.append(f"- Lifecycle: `{summary.get('case_lifecycle', {})}`")
        lines.append(f"- Failure root causes: `{summary.get('failure_root_causes', {})}`")
        lines.append("")
    lines.extend(["", "## Regression Trend", ""])
    trend = report.get("trend", {})
    if trend:
        lines.append(f"- Previous avg score: `{trend.get('previous_avg_score', '-')}`")
        lines.append(f"- Current avg score: `{trend.get('current_avg_score', '-')}`")
        lines.append(f"- Delta: `{trend.get('delta', '-')}`")
    else:
        lines.append("- No previous run history.")
    lines.extend(["", "## Failed Case Details", ""])
    for agent, results in report["results"].items():
        failed = [item for item in results if not item["passed"]]
        if not failed:
            continue
        lines.append(f"### {agent}")
        for item in failed:
            gap = "known gap" if item.get("expected_result") == "known_gap" else "unexpected"
            lines.append(f"- `{item['case_id']}` ({gap}, score `{item['score']}`): {', '.join(item.get('issues', [])) or 'score below threshold'}")
        lines.append("")
    return "\n".join(lines)


def run(agent_names: list[str]) -> dict[str, Any]:
    summaries = []
    all_results = {}
    for agent in agent_names:
        adapter = ADAPTERS[agent]()
        adapter.reset()
        case_results = []
        for case in load_cases(agent):
            result = adapter.run_case(case)
            case_results.append((case, result))
        summaries.append(summarize(agent, case_results))
        all_results[agent] = [
            {
                **result.__dict__,
                "expected_result": case.get("expected_result", "pass"),
                "gap_reason": case.get("gap_reason", ""),
            }
            for case, result in case_results
        ]
    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "agents": agent_names,
        "summaries": summaries,
        "results": all_results,
    }
    report_dir = ROOT / "reports" / "evals"
    report_dir.mkdir(parents=True, exist_ok=True)
    report["trend"] = load_trend(report_dir, summaries)
    (report_dir / "latest_eval_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (report_dir / "latest_eval_report.md").write_text(render_markdown(report), encoding="utf-8")
    append_history(report_dir, report)
    return report


def load_trend(report_dir: Path, summaries: list[dict[str, Any]]) -> dict[str, Any]:
    history_path = report_dir / "eval_history.jsonl"
    current = round(sum(summary["avg_score"] for summary in summaries) / max(len(summaries), 1), 3)
    if not history_path.exists():
        return {"current_avg_score": current, "previous_avg_score": None, "delta": None}
    previous_lines = [line for line in history_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not previous_lines:
        return {"current_avg_score": current, "previous_avg_score": None, "delta": None}
    previous = json.loads(previous_lines[-1]).get("overall_avg_score")
    delta = round(current - float(previous), 3) if previous is not None else None
    return {"current_avg_score": current, "previous_avg_score": previous, "delta": delta}


def append_history(report_dir: Path, report: dict[str, Any]) -> None:
    overall = round(sum(summary["avg_score"] for summary in report["summaries"]) / max(len(report["summaries"]), 1), 3)
    record = {
        "generated_at": report["generated_at"],
        "agents": report["agents"],
        "overall_avg_score": overall,
        "unexpected_failed": sum(len(summary["unexpected_failed_cases"]) for summary in report["summaries"]),
        "known_gaps": sum(len(summary["known_gap_cases"]) for summary in report["summaries"]),
    }
    with (report_dir / "eval_history.jsonl").open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent", action="append", choices=sorted(ADAPTERS), help="Agent to evaluate. Repeatable.")
    args = parser.parse_args()
    agents = args.agent or sorted(ADAPTERS)
    report = run(agents)
    unexpected_failed = sum(len(summary["unexpected_failed_cases"]) for summary in report["summaries"])
    known_gaps = sum(len(summary["known_gap_cases"]) for summary in report["summaries"])
    print(json.dumps({"agents": agents, "unexpected_failed": unexpected_failed, "known_gaps": known_gaps, "summaries": report["summaries"]}, ensure_ascii=False))
    if unexpected_failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
