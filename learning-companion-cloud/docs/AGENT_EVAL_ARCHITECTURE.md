# Agent Eval Harness 架构

## 设计目标

`eval_harness/` 被设计成一个独立的 Agent 测评项目，而不是只服务当前学习系统的临时脚本。它可以同时测：

- `learning_agent`：本项目的学习陪跑 Agent。
- `demo_agent`：一个简化工具调用 Agent，用来展示 Harness 可迁移。

## 目录结构

- `eval_harness/adapters/base.py`：统一 `AgentAdapter` 协议和 `EvalResult` 结果结构。
- `eval_harness/adapters/learning_agent_adapter.py`：用 FastAPI `TestClient` 跑学习 Agent 端到端用例。
- `eval_harness/adapters/demo_agent_adapter.py`：用内存 Tool Agent 展示通用工具调用评估。
- `eval_harness/datasets/*/golden_set.json`: JSON golden set; report separates pass, Known Gap, and unexpected failure.
- `eval_harness/runners/eval_runner.py`：执行、汇总、输出 JSON/Markdown 报告。
- `reports/evals/latest_eval_report.*`：最近一次测评报告。

## 测评维度

| 维度 | 覆盖内容 | 关键指标 |
| --- | --- | --- |
| RAG | 资料导入、检索命中、来源追踪 | `rag_hit`, `source_grounded` |
| Planning | 学习目标解析、任务生成、时间安排 | `task_success`, `schedule_present` |
| Stuck Assist | 卡住后针对性提示、不直接泄露答案 | `actionable`, `no_direct_answer` |
| Quiz | 出题数量、答案隐藏、质量分 | `min_items`, `no_answer_leakage`, `quality` |
| Safety | Prompt Injection、密钥脱敏、危险操作阻断 | `ingested_safely`, `no_secret_leak` |
| Tool Agent | 工具选择、禁止副作用 | `tool_accuracy`, `side_effect_safe` |

## 轨迹级评估

业务系统通过 `agent_runs` 与 `agent_trace_steps` 记录 Agent 行为，测评系统可继续扩展为：

- 检查某类任务是否调用了必要工具。
- 检查危险输入是否没有调用副作用工具。
- 检查 RAG 命中是否出现在出题/辅导前。
- 检查计划、任务、测验、报告之间的 `trace_id` 是否可串联。

## 安全红队 Rubric

当前安全集覆盖 4 类风险：

- Prompt Injection：资料中要求“忽略规则”不应覆盖系统行为。
- Secret Leakage：`sk-...`、`OPENAI_API_KEY=...` 等内容导入后必须脱敏。
- Unsafe Side Effect：删除任务等高风险动作必须确认。
- Learning Integrity：不能伪造成绩、不能绕过轨迹、不能直接把答案喂给孩子。

基础判分采用规则型 Rubric，后续可增加 LLM-as-Judge，但必须满足：

- Judge 只能看脱敏后的输入输出。
- Judge 分数必须和规则指标并列，不能单独作为 CI 质量门禁。
- Judge Prompt 版本需固定并进入报告。

## CI 质量门禁

根目录 `.github/workflows/agent-eval.yml` 会在 push/PR 时执行：

```bash
python eval_harness/runners/eval_runner.py --agent learning_agent
python eval_harness/runners/eval_runner.py --agent demo_agent
```

失败即阻断，保证 Agent 能力退化能被第一时间发现。
