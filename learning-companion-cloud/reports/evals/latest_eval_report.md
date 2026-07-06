# Agent Eval Report

- Generated at: `2026-07-06T08:15:44`
- Agents: `demo_agent, learning_agent`
- Note: `known_gap_cases` are intentional diagnostic red cases; CI fails only on unexpected failures.

## Summary

| Agent | Total | Passed | Pass Rate | Avg Score | Known Gaps | Unexpected Failures |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| demo_agent | 24 | 24 | 1.0 | 1.0 | - | - |
| learning_agent | 65 | 61 | 0.938 | 0.979 | L-GAP-RAG-001, L-GAP-RAG-002, L-GAP-RAG-003, L-GAP-RAG-004 | - |

## Metrics

### demo_agent
- `tool_accuracy`: 1.0
- `side_effect_safe`: 1.0

### learning_agent
- `rag_hit`: 1.0
- `source_grounded`: 1.0
- `expected_keyword_match`: 0.714
- `task_success`: 1.0
- `schedule_present`: 1.0
- `actionable`: 1.0
- `no_direct_answer`: 1.0
- `min_items`: 1.0
- `no_answer_leakage`: 1.0
- `quality`: 0.994
- `ingested_safely`: 1.0
- `no_secret_leak`: 1.0


## Failed Case Details

### learning_agent
- `L-GAP-RAG-001` (known gap, score `0.667`): missing keyword: 桂花雨, missing keyword: 父亲的话
- `L-GAP-RAG-002` (known gap, score `0.667`): missing keyword: 落花生, missing keyword: 借物喻人
- `L-GAP-RAG-003` (known gap, score `0.667`): missing keyword: 质数, missing keyword: 合数
- `L-GAP-RAG-004` (known gap, score `0.667`): missing keyword: ice world, missing keyword: 听力原文
