# 学习陪跑系统测试用例摘要

## 范围

本测试集覆盖管理端生成计划、今日任务生成、孩子端任务展示、任务状态流转、卡住 AI 辅导、小测批改、家长端聚合、报告、通知和中文编码风险。

结构化源文件：`tests/cases.yaml`

自动化自测脚本：`scripts/self_test.py`

真实浏览器点击脚本：`scripts/ui_click_test.py`

## P0 回归链路

1. 健康检查和三端页面可访问。
2. 管理端长提示生成外研社/刘兆义五上英语 30 天计划。
3. 今日任务生成 Unit 1 第 1 天任务。
4. 孩子端服务端直出任务、进度 `0/1`、中文检查方式“完成后做小测”。
5. 任务开始、暂停、卡住、完成检查状态流转。
6. 卡住返回分层提示并进入补漏。
7. 完成后生成小测，提交后生成批改和家长端数据。

## 已知重点风险

- `RISK-CACHE-001`：孩子端不能只依赖 JS 渲染，否则浏览器缓存或脚本失败会空白。
- `RISK-DB-001`：空数据库必须自动初始化，不能出现 `no such table`。
- `RISK-ENC-001`：中文文案不能出现乱码标记。

## 执行方式

```powershell
cd learning-companion-cloud
python .\scripts\self_test.py
python .\scripts\ui_click_test.py
```

脚本会创建临时 SQLite 数据库，设置 `AI_ENABLED=false`、`NOTIFY_CHANNEL=none`，不会污染正式 `data/learning.db`。
`ui_click_test.py` 会用 Playwright 启动临时服务并逐个点击管理端、孩子端、家长端按钮，验证前端事件绑定没有失效。
