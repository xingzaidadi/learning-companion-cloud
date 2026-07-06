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
    legacy_path = base / "golden_set.yaml"
    if legacy_path.exists():
        return legacy_path
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
    for result in results:
        for name, value in result.metrics.items():
            metric_totals.setdefault(name, []).append(float(value))
    metrics = {name: round(sum(values) / len(values), 3) for name, values in metric_totals.items()}
    return {
        "agent": agent,
        "total": len(results),
        "passed": len(passed),
        "pass_rate": round(len(passed) / max(len(results), 1), 3),
        "avg_score": round(sum(scores) / max(len(scores), 1), 3),
        "score_stdev": round(statistics.pstdev(scores), 3) if len(scores) > 1 else 0,
        "metrics": metrics,
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
        lines.append("")
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
    (report_dir / "latest_eval_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (report_dir / "latest_eval_report.md").write_text(render_markdown(report), encoding="utf-8")
    return report


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
