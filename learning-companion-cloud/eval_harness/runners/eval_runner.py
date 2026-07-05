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


def load_cases(agent: str) -> list[dict[str, Any]]:
    path = ROOT / "eval_harness" / "datasets" / agent / "golden_set.yaml"
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["cases"]


def summarize(agent: str, results: list[Any]) -> dict[str, Any]:
    scores = [result.score for result in results]
    passed = [result for result in results if result.passed]
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
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Agent Eval Report",
        "",
        f"- Generated at: `{report['generated_at']}`",
        f"- Agents: `{', '.join(report['agents'])}`",
        "",
        "## Summary",
        "",
        "| Agent | Total | Passed | Pass Rate | Avg Score | Failed |",
        "| --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for summary in report["summaries"]:
        lines.append(
            f"| {summary['agent']} | {summary['total']} | {summary['passed']} | {summary['pass_rate']} | {summary['avg_score']} | {', '.join(summary['failed_cases']) or '-'} |"
        )
    lines.extend(["", "## Metrics", ""])
    for summary in report["summaries"]:
        lines.append(f"### {summary['agent']}")
        for name, value in summary["metrics"].items():
            lines.append(f"- `{name}`: {value}")
        lines.append("")
    return "\n".join(lines)


def run(agent_names: list[str]) -> dict[str, Any]:
    summaries = []
    all_results = {}
    for agent in agent_names:
        adapter = ADAPTERS[agent]()
        adapter.reset()
        results = [adapter.run_case(case) for case in load_cases(agent)]
        summaries.append(summarize(agent, results))
        all_results[agent] = [result.__dict__ for result in results]
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
    failed = sum(summary["total"] - summary["passed"] for summary in report["summaries"])
    print(json.dumps({"agents": agents, "failed": failed, "summaries": report["summaries"]}, ensure_ascii=False))
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
