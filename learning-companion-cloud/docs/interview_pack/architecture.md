# 受控学习 Agent 架构图

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
- `demo_agent`：case `24`，通过率 `1.0`，意外失败 `[]`。
- `learning_agent`：case `219`，通过率 `0.963`，意外失败 `[]`。
- 9.5 质量门禁：`10.0`。
