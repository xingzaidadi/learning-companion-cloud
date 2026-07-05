# 受控自主学习 Agent 详细设计

## 1. 架构总览

```text
Frontend
├── Child Learning Cockpit
├── Admin Plan Workspace
└── Parent Insight Dashboard

Backend API
├── LearningManagerAgent
├── Tool Registry
├── Agent Runtime
├── Memory Service
├── Material/RAG Service
├── Quiz/Grading Service
├── Tutor Service
├── Review Service
└── Report/Insight Service

Storage
├── SQLite
├── learning_materials / material_chunks
├── daily_tasks / task_progress
├── quiz_items / quiz_results
├── skill_mastery / memory_records
├── tutor_sessions / tutor_messages
├── agent_runs / trace_events / checkpoints
└── review_items / reports
```

## 2. AgentResult 标准输出

所有 Agent 和工具统一返回：

```json
{
  "ok": true,
  "output": {},
  "source": "ai | rule | rag | mixed",
  "confidence": 0.86,
  "evidence": [],
  "warnings": [],
  "next_actions": [],
  "model": "ppio/pa/gpt-5.5",
  "latency_ms": 1234,
  "fallback_reason": "",
  "quality_score": 0.92,
  "trace_id": "..."
}
```

用途：

- 页面展示来源。
- 家长查看证据。
- 测试断言置信度和质量分。
- 日志审计。
- AI 失败时可 fallback。

## 3. Tool Registry

### 3.1 ToolSpec

```python
@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict
    output_schema: dict
    side_effect: Literal["read", "write", "notify", "ai_call"]
    required_role: Literal["child", "parent", "admin", "system"]
    timeout_seconds: int
    retry_policy: dict
    guardrails: list[str]
```

### 3.2 首批工具

| 工具 | side_effect | 使用者 | 说明 |
|---|---|---|---|
| `parse_learning_goal` | ai_call/write | admin | 解析家长自然语言目标 |
| `preview_plan` | ai_call/read | admin | 生成计划预览 |
| `publish_daily_tasks` | write | admin/system | 发布今日任务 |
| `get_current_task` | read | child | 获取当前任务 |
| `start_task` | write | child | 开始计时 |
| `pause_task` | write | child | 暂停计时 |
| `open_tutor_session` | ai_call/write | child | 卡住辅导 |
| `send_tutor_message` | ai_call/write | child | 多轮辅导消息 |
| `generate_quiz` | ai_call/write | child/system | 生成小测 |
| `evaluate_quiz_quality` | ai_call/read | system | 题目质量评估 |
| `submit_quiz` | write | child | 提交答案 |
| `grade_submission` | ai_call/write | child/system | 批改和诊断 |
| `update_memory` | write | system | 更新学生画像 |
| `schedule_review` | write | system | 安排补漏 |
| `build_parent_insight` | ai_call/read | parent | 生成家长结论 |

## 4. Agent Runtime

### 4.1 AgentSession

用于跟踪一次长期目标或一次孩子学习会话。

```text
id
student_id
session_type: plan | daily_learning | tutor | quiz | report
status: active | paused | completed | failed | recovered
current_step
goal_json
state_json
created_at
updated_at
```

### 4.2 Checkpoint

每个关键步骤写 checkpoint：

```text
session_id
step_name
state_json
input_json
output_json
created_at
```

使用场景：

- 服务重启恢复。
- AI 调用失败后重试。
- 防重复提交。
- 审计 Agent 为什么这样做。

### 4.3 TraceEvent

记录每一次工具调用：

```text
trace_id
session_id
tool_name
input_json
output_json
source
model
latency_ms
status
error
created_at
```

## 5. 学生画像 Memory 设计

### 5.1 能力点体系

#### 语文

```text
生字认读
生字书写
词义理解
课文理解
句子赏析
仿写表达
朗读复述
```

#### 数学

```text
概念理解
计算准确
步骤表达
应用建模
易错辨析
估算与检查
```

#### 英语

```text
听音辨词
单词拼写
中译英
句型替换
课文理解
朗读跟读
词义匹配
```

### 5.2 skill_mastery

```text
id
student_id
subject
skill
grade
book
unit
lesson
mastery_score 0-1
confidence 0-1
evidence_json
last_task_id
last_quiz_result_id
updated_at
```

### 5.3 memory_records

```text
id
student_id
memory_type: episodic | semantic | procedural | preference | risk
subject
skill
content
source_type: quiz | stuck | parent_goal | system
source_id
confidence
expires_at
status: active | deprecated | rejected
created_at
updated_at
```

### 5.4 记忆写入策略

不能把所有输入都写入长期记忆。

可写入：

```text
反复错的知识点
明确卡住点
小测结果
家长长期目标
稳定偏好和约束
已验证的掌握情况
```

不可直接写入：

```text
孩子随口说的错误事实
AI 未验证的推测
一次性情绪表达
恶意提示词
超纲内容
```

## 6. RAG 资料库设计

### 6.1 material_chunks

```text
id
material_id
subject
grade
book
unit
lesson
chunk_text
keywords_json
source_ref
page_no
created_at
```

### 6.2 检索策略

```text
当前任务标题 + 学科 + 单元 + 今日学习步骤 + 错因
→ 生成检索 query
→ 检索相关资料片段
→ 过滤五年级上册范围
→ 返回给 Quiz/Tutor/Planner
```

### 6.3 出题来源绑定

每道题必须保存：

```text
source_ref
material_chunk_id
subject
skill
unit
lesson
```

## 7. Planner / ScheduleAgent

输入：

```text
家长长期目标
今日日期
昨日任务结果
skill_mastery
review_items
materials
每日时长上限
学科优先级
```

输出：

```json
{
  "tasks": [],
  "reasoning_summary": "先补英语拼写，再推进语文和数学",
  "time_budget": 90,
  "warnings": [],
  "requires_parent_confirm": false
}
```

规则：

```text
复习优先级高于新课
低分任务次日先补漏
未完成任务要滚动或重排
每日总时长不超过上限
不得跳过家长指定主线
不得超五上范围
重大调整需要家长确认
```

## 8. QuizAgent + Evaluator

### 8.1 出题输入

```text
当前任务
学习资料片段
学生画像
今日卡住点
题型策略
难度要求
```

### 8.2 题目结构

```json
{
  "question_type": "choice | blank | dictation | short_answer | calculation | word_problem | rewrite",
  "subject": "英语",
  "skill": "单词拼写",
  "difficulty": "basic",
  "question": "...",
  "options": [],
  "answer": "...",
  "answer_aliases": [],
  "rubric": {},
  "source_ref": "Unit 1 My school is cool",
  "quality_score": 0.94
}
```

### 8.3 质量评估维度

```text
是否基于当天内容
是否超纲
题干是否泄答案
选项是否泄答案
答案是否唯一
难度是否适合
是否覆盖能力点
是否太幼稚
是否可自动批改或有 rubric
```

不合格处理：

```text
quality_score < 0.8 → 重生成
连续 2 次失败 → 本地规则兜底 + 标记低置信度
```

## 9. GradingAgent

### 9.1 批改结果

```json
{
  "score": 0.8,
  "passed": true,
  "items": [
    {
      "item_id": 1,
      "is_correct": false,
      "score": 0.5,
      "error_type": "拼写错误",
      "skill": "英语.单词拼写",
      "feedback": "library 少写了 r",
      "next_practice": "再默写 library/classroom"
    }
  ],
  "mastery_updates": []
}
```

### 9.2 批改策略

| 题型 | 策略 |
|---|---|
| 选择题 | 规则精确匹配 |
| 填空题 | 标准化大小写、空格、标点、别名 |
| 数学计算 | 数值等价、分数/小数等价 |
| 数学步骤 | AI + rubric |
| 语文理解 | AI + 关键词 + rubric |
| 英语句型 | AI + 关键结构 |
| 听写 | 标准答案 + 拼写差异分析 |

## 10. TutorAgent 多轮卡住辅导

### 10.1 状态

```text
opened
classifying
hinting
micro_practice
verified
resolved
needs_parent
```

### 10.2 流程

```text
孩子说卡住
→ 判断卡点类型
→ 如果太模糊，追问
→ 给一步提示
→ 出微练习
→ 孩子回答
→ 判断是否学会
→ 学会则回到学习中
→ 仍不会则给下一步或建议家长介入
```

### 10.3 输出原则

```text
短
具体
只给下一步
不直接给作业完整答案
尽量让孩子自己说/算/选
必要时升级给家长
```

## 11. ReviewAgent

复习策略：

```text
D1：同题订正
D2：同类变式
D4：混合复习
D7：综合检测
```

插入规则：

```text
P0 错题优先
每日复习不超过 20 分钟
复习和新课冲突时，低掌握度优先
连续通过后标记 done
```

## 12. ParentInsightAgent

输入：

```text
今日任务
计时
小测
卡住记录
skill_mastery
review_items
agent trace
```

输出：

```json
{
  "headline": "整体完成良好，但英语拼写需要补漏",
  "status": "attention",
  "evidence": [],
  "weak_points": [],
  "tomorrow_plan": [],
  "parent_actions": []
}
```

原则：

```text
先结论
再证据
再建议
不要让家长自己分析数据
```

## 13. Guardrails

### 13.1 计划护栏

```text
不超五年级上册
不超每日时长
不跳过家长指定内容
重大调整需要确认
重复生成不产生重复任务
```

### 13.2 出题护栏

```text
不泄答案
不超纲
答案唯一
题目清楚
不直接给孩子答案
```

### 13.3 Tutor 护栏

```text
不给完整作业答案
先提示再练习
不使用打击孩子的话
不会就升级家长
```

### 13.4 记忆护栏

```text
错误事实不写入长期记忆
恶意提示不写入记忆
记忆有来源和置信度
过期记忆降权
```

## 14. API 设计

新增 API：

```text
GET  /api/agent/status
POST /api/agent/plan/preview
POST /api/agent/plan/publish
GET  /api/student/mastery
GET  /api/student/memory
POST /api/materials/parse
GET  /api/materials/search
POST /api/tutor/session
POST /api/tutor/session/{id}/message
POST /api/quiz/{task_id}/evaluate-quality
GET  /api/parent/insights
GET  /api/parent/tomorrow-plan
```

保留并增强：

```text
/api/daily-tasks
/api/daily-tasks/{task_id}/event
/api/daily-tasks/{task_id}/quiz
/api/day/end
/api/week/report
```

## 15. 前端状态机

孩子端状态：

```text
empty
ready
studying
paused
stuck_tutoring
checking
revising
passed
all_done
```

每个状态只渲染一个主行动区。

## 16. 可观测性

每次 Agent 行为必须能回答：

```text
为什么生成这个任务？
参考了哪些资料？
用了 AI 还是规则？
质量评分多少？
置信度多少？
失败后怎么兜底？
这条结论证据是什么？
```
