# Agent Core 完整测试用例与执行清单

## 1. 测试模式

采用 `case-gen` 的完整用例生成模式：覆盖 API、集成、E2E、回归、安全/韧性、探索性用例。结构化源文件是 `tests/agent_core_full_cases.yaml`，本文件是人工验收可读版。

## 2. 覆盖范围

- 管理端：自然语言计划、手动录入、批量导入、资料库、AI 检查、今日任务同步、重生成小测。
- 孩子端：开始、暂停、完成检查、卡住、计时、小测渲染、小测提交、订正展示。
- 三科内核：语文听写/拼音/组词/理解/概括/表达；英语默写/互译/填空/翻译/造句；数学计算/概念/步骤/应用/错因/变式。
- Agent 闭环：计划、任务、出题、批改、错因、D1/D3/D7 补漏、家长日报/周报。
- 稳定性：空库初始化、老库迁移、AI 失败兜底、中文编码、答案不泄露、敏感信息不提交。

## 3. 执行门禁

每次上线或推送前必须跑：

```powershell
cd learning-companion-cloud
python .\scripts\validate_agent_core_cases.py
python .\scripts\self_test.py
python .\scripts\ui_click_test.py
git diff --cached | Select-String -Pattern "sk-[A-Za-z0-9]{20,}"
```

期望：前三个命令分别输出 `AGENT_CORE_CASES_OK`、`SELF_TEST_OK`、`UI_CLICK_TEST_OK`；敏感信息扫描无输出。

## 4. P0 必测清单

- `AC-ADM-001` 管理端自然语言生成语文和作业长期计划
- `AC-ADM-002` 英语资料型长提示生成 30 天五上英语计划
- `AC-ADM-005` 今日已满后手动同步仍追加新增任务源
- `AC-MAT-001` 管理端保存学习资料库单词表
- `AC-MAT-002` 学习资料库单词表参与英语小测生成
- `AC-TASK-001` 无今日任务时自动兜底生成
- `AC-TASK-003` 小测未通过后第二天优先生成 P0 补漏任务
- `AC-CHILD-001` 孩子端 HTML 服务端直出任务和初始数据
- `AC-CHILD-002` 开始按钮启动当前任务并开始计时
- `AC-CHILD-003` 暂停按钮停止计时并保留 elapsed_seconds
- `AC-CHILD-004` 完成检查按钮停止计时并展示小测
- `AC-CHILD-005` 提交小测后孩子端展示订正详情
- `AC-STUCK-001` 卡住按钮只影响当前任务
- `AC-STUCK-002` 语文不认识字卡住返回读音和下一步
- `AC-QUIZ-CN-001` 语文生成听写、拼音、组词、理解题
- `AC-QUIZ-CN-002` 语文听写严格匹配汉字
- `AC-QUIZ-EN-001` 英语 Unit 1 生成默写、互译、句型题
- `AC-QUIZ-EN-002` 英语拼写忽略大小写但不忽略漏字母
- `AC-QUIZ-MA-001` 数学生成计算、概念、步骤、应用、错因、变式题
- `AC-QUIZ-MA-002` 数学精确计算支持数值等价判断
- `AC-QUIZ-SCOPE-001` 三科出题不超武汉五年级上册范围
- `AC-GRADE-001` 小测提交返回分数、错因、掌握度、诊断
- `AC-GRADE-003` 通过率低于 80% 标记 needs_revision
- `AC-REVIEW-001` 错题生成 D1/D3/D7 复习节奏
- `AC-REPORT-001` 家长日报包含完成情况、错因、明天第一步、10 分钟建议
- `AC-REPORT-002` 家长看板展示小测错因和补漏阶段
- `AC-AI-001` AI 未启用时检查接口明确提示规则兜底
- `AC-AI-003` AI 出题失败不阻断小测生成
- `AC-AI-004` 开放题批改 AI 不通时规则兜底
- `AC-DATA-001` 空库自动初始化全部表和默认学生
- `AC-DATA-002` 老库自动迁移新增字段
- `AC-DATA-003` API Key 和本地数据库不进入 Git
- `AC-REG-001` 三端核心按钮静态库存完整
- `AC-REG-002` 真实浏览器点击三端主要按钮
- `AC-REG-004` 公开小测接口不泄露 answer 字段

## 5. 用例总览

完整结构化用例共 `53` 条，覆盖管理端、孩子端、家长端、AI 兜底、三科题库、批改补漏、报告、安全和数据迁移。所有用例均包含优先级、层级、类型、需求/代码/风险追踪、前置条件、步骤、期望结果和自动化状态。

## 6. 当前执行结论

- `scripts/validate_agent_core_cases.py` 校验结构化用例数量、重复 ID、必需章节和 P0 自动化候选标记。
- `scripts/self_test.py` 已覆盖：计划、资料库、今日任务、三科题型、四按钮 API、错因、D1/D3/D7、家长报告、静态按钮库存、中文编码。
- `scripts/ui_click_test.py` 已覆盖：管理端真实点击、资料保存、任务生成、孩子端按钮、小测提交、家长端日报/周报。
- 未全自动的用例已在 YAML 中标记 `designed` 或 `partially_automated`，主要是 AI 真连接、超纲人工抽查、生产密码鉴权和跨日补漏专项。
