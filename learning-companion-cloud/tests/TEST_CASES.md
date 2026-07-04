# 学习陪跑系统测试用例摘要

## 范围

本测试集覆盖管理端生成计划、今日任务生成、孩子端任务展示、任务状态流转、卡住 AI 辅导、小测批改、家长端聚合、报告、通知、资料库、三科 Agent 内核和中文编码风险。

- 基础结构化源文件：`tests/cases.yaml`
- Agent Core 完整结构化源文件：`tests/agent_core_full_cases.yaml`
- Agent Core 可读验收清单：`tests/AGENT_CORE_FULL_CASES.md`
- 自动化自测脚本：`scripts/self_test.py`
- 真实浏览器点击脚本：`scripts/ui_click_test.py`
- 用例结构校验脚本：`scripts/validate_agent_core_cases.py`
- 孩子端四按钮验收用例：`tests/BUTTON_CASES.md`

## P0 回归链路

1. 健康检查和三端页面可访问。
2. 管理端长提示生成外研社/刘兆义五上英语 30 天计划。
3. 管理端资料库可录入单词表/听写词/音频清单，并参与小测生成。
4. 今日任务生成 Unit 1 第 1 天任务，孩子端进度不是 `0/0`。
5. 孩子端服务端直出任务、中文检查方式“完成后做小测”。
6. 任务开始、暂停、卡住、完成检查状态流转。
7. 卡住返回分层提示并只影响当前任务。
8. 语文/英语/数学三科生成对应硬核题型。
9. 小测提交后生成分数、错因、掌握度、D1/D3/D7 补漏。
10. 家长端展示错因、补漏队列、日报、周报和 10 分钟介入建议。

## Agent Core 完整用例集

完整用例集覆盖管理端计划/资料、今日任务、孩子端四按钮、三科小测内核、AI 兜底、批改错因、D1/D3/D7 补漏、家长报告、数据迁移、敏感信息和中文编码。

执行顺序：

```powershell
python .\scripts\validate_agent_core_cases.py
python .\scripts\self_test.py
python .\scripts\ui_click_test.py
```

## 已知重点风险

- `RISK-CACHE-001`：孩子端不能只依赖 JS 渲染，否则浏览器缓存或脚本失败会空白。
- `RISK-DB-001`：空数据库必须自动初始化，不能出现 `no such table`。
- `RISK-ENC-001`：中文文案不能出现乱码标记。
- `RISK-QUIZ-LEAK-001`：孩子端小测不能暴露标准答案。
- `RISK-MATERIAL-001`：资料录入后必须真的参与出题。
- `RISK-SECRET-001`：`.env`、`data/learning.db`、报告和真实 API Key 不能提交。

## 执行方式

```powershell
cd learning-companion-cloud
python .\scripts\validate_agent_core_cases.py
python .\scripts\self_test.py
python .\scripts\ui_click_test.py
```

脚本会创建临时 SQLite 数据库，设置 `AI_ENABLED=false`、`NOTIFY_CHANNEL=none`，不会污染正式 `data/learning.db`。
`ui_click_test.py` 会用 Playwright 启动临时服务并逐个点击管理端、孩子端、家长端按钮，验证前端事件绑定没有失效。
