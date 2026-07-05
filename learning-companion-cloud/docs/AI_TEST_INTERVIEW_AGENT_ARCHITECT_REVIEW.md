# AI 测试开发面试项目 Agent 架构评估

评估日期：2026-07-05  
项目：11 岁孩子暑假自主学习陪跑系统  
定位：受控自主学习 Agent / AI 测试开发展示项目

## 1. 架构师一句话结论

这个项目可以作为“AI 测试开发”面试项目，而且比普通 Demo 更有说服力：它不是简单 ChatBot，而是包含目标规划、RAG、长期记忆、工具化 API、状态机、质量评估、E2E 测试和本地可部署的完整 Agent 应用。

但它目前更像“规则编排 + LLM/RAG 增强 + 受控 Agent Runtime”，还不是完全自主 Agent。面试时不要吹成“全自主 Agent”，更准确的说法是：

> 我做的是一个面向小学生自主学习场景的受控 Agent 系统。核心不是让模型随便发挥，而是通过目标约束、RAG 资料底座、任务状态机、工具 API、质量门禁和测试体系，让 Agent 在安全边界内完成计划、陪学、出题、诊断和报告。

## 2. 当前 Agent 架构拆解

| Agent 组件 | 当前实现 | 代码/接口 |
| --- | --- | --- |
| Goal / 目标 | 五年级上册语数英 95+，每日时长和能力点目标 | `backend/agent_core.py`、`/api/learning-targets` |
| Planning / 规划 | 自然语言计划解析、每日任务生成、弱项调整 | `backend/plan_generator.py`、`backend/planner.py`、`/api/study-plan/generate` |
| Tools / 工具 | 资料导入、RAG 检索、小测生成、评分、报告、提醒 | `backend/app.py` API |
| Memory / 记忆 | 能力掌握、卡住记录、tutor session、错题复习 | `skill_mastery`、`memory_records`、`tutor_sessions`、`review_items` |
| RAG / 知识库 | 语文/数学/英语资料导入、OCR、切片、覆盖矩阵、来源绑定 | `backend/material_importer.py`、`material_chunks` |
| State Machine / 状态机 | not_started、in_progress、paused、stuck、checking、needs_revision、completed | `/api/daily-tasks/{id}/event` |
| Evaluation / 评估 | 小测质量分、source_ref、答案泄露防护、95+ readiness | `quiz_quality_results`、`senior_qa_gate.py` |
| Observability / 可观测 | Agent 运行日志、日报、周报、家长看板 | `agent_runs`、`daily_reports`、`weekly_reports` |
| Safety / 安全边界 | 年级范围、资料来源、密钥不提交、状态机阻断 | prompts、`.gitignore`、测试门禁 |

## 3. 和 `agent相关` 学习资料的一一对照

| 学习资料主题 | 当前项目匹配度 | 说明 |
| --- | ---: | --- |
| Agent = LLM + Memory + Planning + Tools | 85% | 四要素都有，但 LLM 不是唯一大脑，更多是受控编排 |
| Workflow vs Agent | 90% | 当前是混合架构：确定性 Workflow 承载主链路，Agent 用于动态计划/出题/辅导 |
| ReAct / 工具循环 | 65% | 有工具 API 和观察结果，但没有显式 Thought-Action-Observation trace |
| Plan-and-Execute | 88% | 管理端输入目标 → 生成长期计划 → 生成今日任务 → 执行检查 |
| Memory / 长期记忆 | 82% | 有 mastery、memory、tutor、review，但缺记忆压缩/冲突治理 UI |
| RAG 与上下文工程 | 90% | 三科资料、OCR、覆盖矩阵、source_ref 绑定，较适合面试展示 |
| Tools / Function Calling | 75% | 工具以 FastAPI 形式存在，尚未封装成标准 function schema/MCP |
| MCP | 35% | 暂未实现 MCP Server，只能讲“未来可接入” |
| Agent Runtime | 80% | 有状态机、DB checkpoint、任务恢复、日志；但缺独立 runtime loop |
| 长任务 Checkpoint | 75% | DB 保存任务状态/进度/计时；缺任务中断恢复队列和重试策略 |
| Validator / Guardrail | 85% | 小测质量、RAG 覆盖、状态机阻断、安全门禁都已实现 |
| Evals / 轨迹评估 | 72% | 有自动化门禁和质量分；缺 LLM-as-judge 对轨迹的系统评测 |
| Multi-Agent | 20% | 当前不是多 Agent，没必要硬说 |
| Agent CLI | 40% | 项目有脚本化测试和启动命令，但没有独立 Agent-friendly CLI 产品层 |
| AI 测试开发测试点 | 92% | 已有 `senior_qa_gate.py`、E2E、UI、状态机、RAG、密钥门禁 |

总体匹配度：**78/100**。  
如果作为“学习 agent 概念 + AI 测试开发面试项目”，匹配度是 **88/100**；如果作为“完整通用 Agent Runtime 框架”，匹配度是 **70/100**。

## 4. 是否适合作为 AI 测试开发面试项目

### 4.1 适合，理由

1. **场景真实**：不是 Todo List 或聊天机器人，而是孩子学习陪跑，有明确目标和用户。
2. **AI 测试开发特征明显**：RAG、OCR、LLM fallback、状态机、质量门禁、E2E 测试都有。
3. **可演示闭环完整**：家长输入目标 → Agent 生成任务 → 孩子学习 → 卡住辅导 → 小测 → 诊断 → 家长报告。
4. **测试资产扎实**：有 `self_test.py`、`child_flow_integration_test.py`、`ui_click_test.py`、`senior_qa_gate.py`。
5. **能讲质量工程**：不只是“我调了模型”，还能讲防答案泄露、source_ref、覆盖矩阵、密钥治理、状态幂等。
6. **能讲架构取舍**：为什么不用完全自主 Agent，而采用受控 Agent；这点面试加分。

### 4.2 面试时最亮点的讲法

> 我把它设计成受控 Agent，而不是完全自主 Agent。因为孩子学习是高风险场景，不能让模型随意安排超纲内容或直接给答案。所以我把确定性状态机、RAG 覆盖矩阵、题目质量校验、错题记忆、家长报告和安全门禁放在工程层，把 AI 用在最需要动态能力的地方：计划生成、卡住辅导、题目生成和诊断总结。

## 5. 当前项目分数

| 维度 | 分数 | 说明 |
| --- | ---: | --- |
| Agent 架构完整度 | 8.4 | 四大组件具备，但缺显式 runtime loop / trace |
| AI 测试开发展示价值 | 9.1 | 测试工程能力很突出，适合面试 |
| 工程可运行性 | 9.0 | 本地服务、数据库、页面、脚本、GitHub 都可跑 |
| RAG 与知识库 | 9.2 | 三科资料底座、OCR、coverage、source_ref 亮点明显 |
| 状态机与业务闭环 | 9.3 | 孩子端链路和幂等控制已经比较强 |
| 生产化程度 | 7.8 | 缺 CI、Docker 完整验收、观测面板、权限细粒度 |
| 面试表达清晰度 | 8.2 | 还需要整理 STAR、架构图、演示脚本 |

作为“AI 测试开发面试项目”：**8.8/10**。  
作为“Agent 架构项目”：**8.2/10**。  
如果补齐下面路线，可到 **9.3–9.5/10**。

## 6. 和 9.5 分面试项目的差距

### 差距 1：缺显式 Agent Runtime Loop

现在的链路更像 API 编排：

```text
HTTP API -> planner/agent/quiz/report -> DB
```

面试里如果被问“你的 Agent loop 在哪里”，需要回答：

> 当前是受控 Agent，不做无限循环；每次用户事件触发一次短 Agent run。agent_runs 记录 run_type/input/output，是轻量 runtime trace。

提升方向：

- 新增 `agent_runtime.py`
- 定义 `RunContext`
- 定义 `Plan -> Act -> Observe -> Validate -> Persist`
- 每次生成计划/卡住/出题/评分都走同一 runtime wrapper
- 写入统一 trace

### 差距 2：工具没有标准 Function Schema / MCP

当前工具是 FastAPI endpoint，不是标准 tool registry。

提升方向：

- 新增 `backend/agent_tools_registry.py`
- 每个工具定义：
  - name
  - description
  - input_schema
  - permission
  - idempotency_key
  - side_effect
- 可选实现 MCP Server，把资料检索、生成任务、小测评分暴露成 MCP 工具。

### 差距 3：缺 Agent 轨迹评估

现在能测结果，但对“Agent 中间过程好不好”测得还不够。

提升方向：

- 每次 Agent run 写入：
  - plan
  - selected_tools
  - observations
  - validation_result
  - confidence
- 新增 `agent_trace_eval.py`
- 评估：
  - 是否使用 RAG
  - 是否引用 source_ref
  - 是否越级
  - 是否给直接答案
  - 是否重复调用工具

### 差距 4：缺 CI/CD 质量门禁

本地脚本已强，但面试项目最好有 GitHub Actions。

提升方向：

- `.github/workflows/qa.yml`
- 每次 push 跑：
  - `senior_qa_gate.py`
  - `self_test.py`
  - `child_flow_integration_test.py`
  - 静态密钥扫描

### 差距 5：缺面试演示材料

现在功能有了，但面试官需要 3–5 分钟看懂。

提升方向：

- `docs/INTERVIEW_README.md`
- `docs/ARCHITECTURE_DIAGRAM.md`
- `docs/DEMO_SCRIPT_5_MIN.md`
- `docs/QA_STRATEGY.md`
- `docs/STAR_STORY.md`

## 7. 推荐面试包装方式

### 项目名称

**面向小学生 95+ 学习目标的受控自主学习 Agent 与 AI 测试质量门禁系统**

### 项目一句话

基于 RAG、任务状态机、长期记忆和质量评估，构建一个能自动生成学习计划、陪伴执行、卡住辅导、小测诊断和家长报告的受控 Agent，并配套 AI 测试开发全链路质量门禁。

### 技术栈

- Backend：FastAPI + SQLite
- Agent：OpenAI-compatible LLM + 规则编排 + RAG + Memory
- RAG：PDF/TXT/URL 导入 + OCR + chunk + source_ref
- Frontend：HTML/CSS/JS 三端页面
- QA：API test + state machine test + UI click test + senior QA gate

### STAR 表达

**S**：孩子暑假学习任务多，手工安排计划、监督、出题、诊断成本高。  
**T**：设计一个能围绕 95+ 目标自动规划、陪学、检查和反馈的 Agent，并保证质量可测。  
**A**：我设计了 RAG 资料底座、任务状态机、卡住辅导、测验生成、长期记忆、家长报告和全链路测试门禁。  
**R**：实现三科五上资料覆盖、孩子端完整学习闭环、P0 自动化门禁全绿，项目可本地部署和 GitHub 迁移。

## 8. 下一步提升优先级

| 优先级 | 任务 | 面试价值 |
| --- | --- | --- |
| P0 | 补 `agent_runtime.py` 统一 runtime loop | 极高 |
| P0 | 补 GitHub Actions CI | 极高 |
| P0 | 补架构图和 5 分钟演示稿 | 极高 |
| P1 | 工具 registry + JSON schema | 高 |
| P1 | Agent trace eval | 高 |
| P1 | Playwright 真浏览器回归 | 高 |
| P2 | MCP Server demo | 中高 |
| P2 | 多 Agent supervisor demo | 中 |

## 9. 最终建议

这个项目适合作为你从测试开发转 AI 测试开发的主项目，但面试时要强调“测试开发视角的 Agent 工程化”，不要只讲模型。

最强卖点不是“我用了 AI”，而是：

1. 我知道什么时候该用 Agent，什么时候该用 Workflow。
2. 我把 AI 不确定性关进了工程边界里。
3. 我设计了 RAG、Memory、状态机、质量评估和 E2E 门禁。
4. 我能从测试开发视角验证 Agent 是否真的可靠。

当前可用于面试：**可以**。  
当前面试竞争力：**8.8/10**。  
补齐 runtime loop、CI、面试材料后：**9.4/10**。
