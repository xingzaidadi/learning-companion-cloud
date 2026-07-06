from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    output_dir = ROOT / "docs" / "interview_pack"
    output_dir.mkdir(parents=True, exist_ok=True)
    eval_report = _load_json(ROOT / "reports" / "evals" / "latest_eval_report.json", {})
    quality_report = _load_json(ROOT / "reports" / "quality" / "quality_95_report.json", {})
    simulation = _load_json(ROOT / "reports" / "simulation" / "seven_day_learning_report.json", {})
    write_architecture(output_dir, eval_report, quality_report)
    write_star(output_dir, eval_report, simulation)
    write_demo(output_dir)
    write_failure_cases(output_dir, eval_report)
    print(json.dumps({"status": "INTERVIEW_PACK_OK", "dir": str(output_dir)}, ensure_ascii=False))


def write_architecture(output_dir: Path, eval_report: dict, quality_report: dict) -> None:
    text = """# 受控学习 Agent 架构图

```mermaid
flowchart LR
  User["家长/孩子输入"] --> Planner["Planner 目标拆解"]
  Planner --> Registry["Tool Registry / Schema"]
  Registry --> Executor["Executor 受控工具执行"]
  Executor --> RAG["RAG 教材检索"]
  Executor --> Quiz["Quiz Engine 出题/批改"]
  Executor --> Remediation["补救队列"]
  RAG --> Evaluator["Evaluator 规则 + Judge"]
  Quiz --> Evaluator
  Remediation --> Scheduler["次日任务调度"]
  Evaluator --> Supervisor["Supervisor 继续/补救/家长关注"]
  Supervisor --> Trace["标准 Trace: goal/plan/decision/tool/observation/evaluate/supervise/final"]
  Trace --> Eval["Agent Eval Harness"]
  Eval --> Report["报告/CI/面试材料"]
```

## 面试定位
- 不是吹成全自主 Agent，而是儿童学习场景下更安全的“受控自主 Agent”。
- 核心价值是把学习目标、教材证据、小测结果、补救任务和评测报告闭环起来。
- 适合 AI 测试开发岗位讲：Agent 轨迹评测、RAG 召回、出题泄露、安全红队、回归趋势。

## 当前评测摘要
"""
    for summary in eval_report.get("summaries", []):
        text += f"- `{summary.get('agent')}`：case `{summary.get('total')}`，通过率 `{summary.get('pass_rate')}`，意外失败 `{summary.get('unexpected_failed_cases')}`。\n"
    text += f"- 9.5 质量门禁：`{quality_report.get('overall_score', '-')}`。\n"
    (output_dir / "architecture.md").write_text(text, encoding="utf-8")


def write_star(output_dir: Path, eval_report: dict, simulation: dict) -> None:
    text = f"""# STAR 项目描述

## S - Situation
孩子暑假学习需要覆盖五年级上册语文、数学、英语，目标不是完成形式任务，而是阶段性考试稳定 95+。普通任务清单无法根据卡点、小测和错题自动调整。

## T - Task
设计一个受控学习 Agent：能理解家长自然语言计划，生成每日任务，孩子学习中卡住时给针对性提示，完成后自动出题/批改，并把薄弱点放入次日补救。

## A - Action
- 建立五上语数英结构化知识库和本地持久化 RAG。
- 设计 Planner、Tool Registry、Executor、Evaluator、Supervisor 的受控 Runtime。
- 记录标准 Trace，支持 Agent Eval Harness 做轨迹评分和失败归因。
- 构建规则断言 + LLM-as-Judge 接口 + 人工抽检 Rubric 的三层测评。
- 用 7 天仿真验证发布任务、卡住、测验、错题、日报和补救闭环。

## R - Result
- 7 天仿真状态：`{simulation.get('status', '-')}`。
- Agent eval 意外失败数：`{sum(len(s.get('unexpected_failed_cases', [])) for s in eval_report.get('summaries', []))}`。
- 学习 Agent case 数：`{next((s.get('total') for s in eval_report.get('summaries', []) if s.get('agent') == 'learning_agent'), '-')}`。
- 可演示能力：孩子端学习闭环、家长端结论看板、管理端 Agent Trace 和 eval 报告。
"""
    (output_dir / "star.md").write_text(text, encoding="utf-8")


def write_demo(output_dir: Path) -> None:
    text = """# 5 分钟 Demo 讲稿

1. **30 秒：业务目标**  
   这是一个 11 岁孩子五上预习陪跑系统，目标是 95+，不是简单打卡。

2. **60 秒：Agent 架构**  
   展示 Planner、Tool Registry、Executor、Evaluator、Supervisor，以及标准 Trace。

3. **90 秒：核心链路**  
   管理端输入“语文每日一篇、数学每日一节、英语每天听写 5 个词”，生成今日任务；孩子端开始、卡住、继续、完成检查。

4. **60 秒：测评能力**  
   展示 Agent Eval Harness：RAG 命中、小测不泄题、卡住提示是否可执行、Trace 是否完整、known gap 是否保留。

5. **60 秒：测试开发亮点**  
   讲 case 生命周期、失败归因、趋势报告、并发测试、UI 审计、7 天仿真和 CI 门禁。

6. **20 秒：边界诚实**  
   它是受控自主 Agent，不是无限权限的全自主 Agent；儿童学习场景必须安全可控。
"""
    (output_dir / "demo_script.md").write_text(text, encoding="utf-8")


def write_failure_cases(output_dir: Path, eval_report: dict) -> None:
    lines = ["# 失败案例分析", ""]
    for agent, results in eval_report.get("results", {}).items():
        failed = [item for item in results if not item.get("passed")]
        if not failed:
            lines.append(f"## {agent}")
            lines.append("- 当前无意外失败。")
            lines.append("")
            continue
        lines.append(f"## {agent}")
        for item in failed[:20]:
            gap = "known gap" if item.get("expected_result") == "known_gap" else "unexpected"
            root = (item.get("output") or {}).get("failure_root_cause", "-") if isinstance(item.get("output"), dict) else "-"
            lines.append(f"- `{item.get('case_id')}`：`{gap}`，score `{item.get('score')}`，root `{root}`，issues `{item.get('issues')}`")
        lines.append("")
    (output_dir / "failure_cases.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _load_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
