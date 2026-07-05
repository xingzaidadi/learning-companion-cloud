# 资料与当前 Agent 一一对照

## 1. 对照结论

`C:\Users\MI\Desktop\AI学习任务\agent相关` 下资料对当前项目非常有价值，但当前项目只吸收了其中一部分思想。

| 资料方向 | 资料核心观点 | 当前系统对应 | 当前匹配 | 后续目标 |
|---|---|---|---:|---:|
| Agent 完全指南 v4/v5 | Agent = Model + Tools + Context + State + Control Flow + Guardrails | 有 AI provider、agent.py、DB 状态、部分日志 | 45% | 85% |
| ReAct / Plan-and-Execute | 观察、思考、调用工具、观察结果、继续执行 | 当前更多是固定函数编排 | 35% | 80% |
| Tools / Function Calling | 工具要有 schema、权限、错误处理、幂等、日志 | 当前工具是 Python 函数，不是标准工具注册表 | 40% | 90% |
| Guardrails | 输入、输出、工具调用前后都要有护栏 | 有部分题目防泄露和范围规则，未系统化 | 40% | 90% |
| Evaluator / Validator | 生成后必须评估，不合格重试 | 有零散质量检查，无统一评估器 | 35% | 92% |
| Memory | 短期、长期、情节、语义、程序记忆 | 有 task_progress、quiz_results、review_items、mastery_records，但不是完整记忆系统 | 38% | 88% |
| RAG | 资料检索作为 Agent 知识来源 | 有 learning_materials，但没有文档切片、索引、来源绑定 | 25% | 85% |
| Long-lived Runtime | 状态、checkpoint、trace、恢复、长期运行 | 有 daily_tasks.status 和 agent_runs，但 Runtime 不统一 | 42% | 82% |
| AI 测试开发 | 测记忆、状态、工具、安全、恢复、隔离 | 有自测和 E2E，但还缺长期 Agent 测试 | 45% | 90% |
| CLI 相关 | Agent-friendly CLI、结构化输出、工具调试 | 对产品主链路帮助较少，可借鉴调试工具 | 20% | 35% |

综合判断：

```text
当前匹配度：40% - 45%
可利用价值：75% - 80%
改造后目标匹配：82% - 88%
```

## 2. 与当前代码的对应关系

| 当前模块 | 已具备能力 | 与资料差距 | 改造动作 |
|---|---|---|---|
| `backend/agent.py` | 计划、任务、题目、批改、卡住、报告入口 | 缺统一 AgentResult、工具链、置信度、证据、反思 | 改成 LearningManager + 专家工具 Agent |
| `backend/ai_provider.py` | OpenAI-compatible 调用、fallback | 缺重试、超时分类、结构化输出强校验、trace | 增加 AI client wrapper、错误分类、质量元数据 |
| `backend/agent_tools.py` | agent_runs、任务、指导、提交、掌握记录 | 缺 Tool Registry 和标准 tool schema | 引入 ToolSpec、ToolResult、side_effect、guardrail |
| `backend/planner.py` | 规则生成每日任务 | 不够动态，不读学生画像和昨日表现 | 升级为 ScheduleAgent |
| `backend/plan_generator.py` | 从自然语言生成任务源 | 目标解析有规则，AI 结果未充分落地 | 增加计划预览、家长确认、边界检查 |
| `backend/question_engine.py` | 学科题目生成、基础质量控制 | 缺独立 QuizEvaluator、来源绑定、能力点 | 每题增加 subject/skill/difficulty/source/quality_score |
| `backend/quiz.py` | 出题、批改、错题、复习触发 | 开放题批改和错因诊断不够强 | 增加 GradingAgent 和 error_type |
| `backend/review.py` | D1 复习任务 | 复习策略简单 | 改为 D1/D2/D4/D7 变式复习 |
| `backend/report.py` | 日报/周报 | 家长洞察不够证据化 | 增加 ParentInsightAgent |
| `frontend/child.html` | 学习驾驶舱、当前任务、计时、卡住、检查 | 状态模式还可以更强 | 改成状态机 UI：学习、卡住、检查、订正、通过 |
| `frontend/admin.html` | 一句话计划、配置、资料、任务源 | 功能堆叠，日常路径不够清晰 | 改为三步工作台：输入 → 预览 → 发布 |
| `frontend/parent.html` | 完成、卡住、小测、日报、周报 | 缺第一结论和明日建议 | 改为学习结论看板 |
| `scripts/*` | 主链路自动化测试 | 缺多日、记忆、AI 异常、权限、安全、质量评估 | 重构 tests 分层体系 |

## 3. 逐资料类型落地方式

### 3.1 Agent 完全指南 v4/v5

可落地为：

- `LearningManagerAgent`：主控 Agent。
- `Tool Registry`：统一工具注册。
- `AgentResult`：统一输出。
- `Guardrails`：输入/输出/工具护栏。
- `Evaluator`：题目、提示、报告质量评估。
- `Trace`：完整执行轨迹。

当前缺口：不是没有 AI，而是 AI 调用没有形成标准 Agent 运行时。

### 3.2 Agent 记忆系统

可落地为：

- `skill_mastery`：学生能力点掌握度。
- `memory_records`：可治理的长期记忆。
- `memory_write_policy`：哪些内容可写入长期记忆。
- `memory_retrieval`：按任务和学科召回。
- `memory_conflict_policy`：冲突和过期处理。

当前缺口：现在是“记录”，不是“记忆”。

### 3.3 长期存活 Agent Runtime

可落地为：

- `agent_sessions`：一次长期学习任务的运行实例。
- `checkpoints`：任务状态快照。
- `tutor_sessions`：卡住多轮辅导状态。
- `trace_events`：工具调用、AI 调用、验证结果。
- `validators`：每个阶段的合法性检查。

当前缺口：有 daily_tasks.status，但没有统一 Runtime。

### 3.4 AI 测试开发资料

可落地为：

- 记忆污染测试。
- 跨天恢复测试。
- 工具失败测试。
- AI fallback 测试。
- 题目质量测试。
- 状态机非法转移测试。
- 多日学习计划测试。

当前缺口：主流程测试有，长期 Agent 测试不足。

### 3.5 CLI 相关资料

可借鉴为：

- 本地调试命令。
- Agent 工具执行日志。
- 结构化输出。
- 开发/测试辅助 CLI。

不作为产品主线。

## 4. 当前 Agent 能力雷达

| 能力 | 当前分 | 目标分 |
|---|---:|---:|
| 目标理解 | 7.2 | 9.4 |
| 任务规划 | 7.5 | 9.5 |
| 工具调用 | 6.5 | 9.3 |
| 长期记忆 | 5.8 | 9.5 |
| 上下文工程 | 6.2 | 9.2 |
| AI 出题 | 7.0 | 9.5 |
| AI 批改 | 6.3 | 9.2 |
| 卡住辅导 | 6.8 | 9.4 |
| 质量评估 | 5.5 | 9.5 |
| 可解释性 | 7.0 | 9.4 |
| 安全护栏 | 6.2 | 9.3 |
| 长期运行 | 6.0 | 9.2 |

## 5. 对照后的核心判断

本地资料不是单纯学习材料，而是可以直接变成当前项目的升级蓝图：

```text
Agent 完全指南 → Agent 架构
记忆系统 → 学生画像
Runtime → 长期陪跑状态机
测试开发 → 9.5 测试体系
CLI → 调试工具和可观测性
```

当前项目最大缺口：

```text
没有统一 Agent Runtime
没有标准 Tool Registry
没有完整学生记忆
没有质量评估器
没有 RAG 化课本资料库
没有多轮 Tutor
测试体系没有覆盖长期 Agent 风险
```
