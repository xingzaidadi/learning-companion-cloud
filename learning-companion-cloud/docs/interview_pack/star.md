# STAR 项目描述

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
- 7 天仿真状态：`SIMULATE_7_DAY_OK`。
- Agent eval 意外失败数：`0`。
- 学习 Agent case 数：`210`。
- 可演示能力：孩子端学习闭环、家长端结论看板、管理端 Agent Trace 和 eval 报告。
