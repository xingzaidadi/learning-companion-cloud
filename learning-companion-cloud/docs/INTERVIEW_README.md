# 面试项目总览

项目名：面向 95+ 学习目标的受控学习 Agent 与 Agent Eval Harness

## 一句话

我做了一个能围绕五年级上册语数英 95+ 目标进行计划、RAG、陪学、小测、补漏和家长报告的受控 Agent，并为它抽象了一套可测多个 Agent 的 Eval Harness。

## 两条主线

1. 学习 Agent 本体：RAG、知识图谱、动态策略、科学排程、小测、卡住辅导、间隔复习。
2. Agent 测评体系：Golden Set、Adapter、Eval Runner、Trace、红队、CI 门禁。

## 演示入口

- 孩子端：`http://127.0.0.1:8000/child`
- 家长端：`http://127.0.0.1:8000/parent`
- 管理端：`http://127.0.0.1:8000/admin`
- Eval：`python eval_harness/runners/eval_runner.py`

## 面试重点

- 我没有让模型无限自主，而是用状态机和质量门禁控制风险。
- RAG 题目必须有 `source_ref`，避免无依据出题。
- Agent 测评不只看最终结果，还看工具、轨迹、副作用和安全。
