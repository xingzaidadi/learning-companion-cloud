# 5 分钟 Demo 讲稿

## 0:00-0:40 背景

孩子暑假学习任务多，家长手工拆计划、监督、出题和复盘成本高。我做的是一个受控学习 Agent，目标是五年级上册语数英 95+。

## 0:40-1:40 Agent 本体

管理端输入自然语言目标，系统生成长期计划和今日任务。资料通过 PDF/OCR/URL 导入 RAG，系统检查语文、数学、英语覆盖矩阵。

## 1:40-2:40 孩子端闭环

孩子端显示当前任务、建议时段和学习计时。开始、暂停、卡住、resume、检查、小测形成状态机。卡住时返回 steps 和 micro practice，不直接给答案。

## 2:40-3:30 家长端

家长端看 95+ readiness、薄弱点、明天优先动作、日报和周报。

## 3:30-4:30 Agent Eval

我抽象了 Eval Harness，可以测 learning_agent 和 demo_agent。Golden Set 覆盖 RAG、Planning、Stuck Assist、Quiz Quality、Safety Redteam、Tool Use。

## 4:30-5:00 质量门禁

CI 跑 senior QA、全链路测试和 Agent Eval。重点不是“模型看起来能答”，而是用测试工程把 AI 不确定性变成可量化、可回归的质量门禁。
