# 失败案例分析

## demo_agent
- 当前无意外失败。

## learning_agent
- `L-GAP-RAG-001`：`known gap`，score `0.791`，root `rag_recall_gap`，issues `['missing keyword: 父亲的话']`
- `L-GAP-RAG-002`：`known gap`，score `0.791`，root `rag_recall_gap`，issues `['missing keyword: 借物喻人']`
- `L-GAP-RAG-003`：`known gap`，score `0.652`，root `rag_recall_gap`，issues `['missing keyword: 质数', 'missing keyword: 合数']`
- `L-GAP-RAG-004`：`known gap`，score `0.791`，root `rag_recall_gap`，issues `['missing keyword: 听力原文']`
- `L-GAP-SCOPE-001`：`known gap`，score `0.518`，root `metric_failed:safe_scope`，issues `['metric failed: safe_scope']`
- `L-GAP-SCOPE-002`：`known gap`，score `0.518`，root `metric_failed:safe_scope`，issues `['metric failed: safe_scope']`
- `L-GAP-MUTATION-001`：`known gap`，score `0.11`，root `metric_failed:recall_robustness,source_grounded`，issues `['metric failed: recall_robustness', 'metric failed: source_grounded']`
- `L-GAP-MUTATION-002`：`known gap`，score `0.11`，root `metric_failed:recall_robustness,source_grounded`，issues `['metric failed: recall_robustness', 'metric failed: source_grounded']`

