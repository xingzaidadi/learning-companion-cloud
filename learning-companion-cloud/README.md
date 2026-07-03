# 11岁孩子暑假自主学习陪跑系统 MVP

这是根据当前目录方案文档直接落地的云端 Web MVP，可本地运行，也可用 Docker 部署到阿里云轻量服务器。

## 已实现内容

- 孩子端 `/child`：今日进度、开始下一个任务、暂停、完成检查、卡住提醒、结束今天。
- 家长端 `/parent`：今日完成数、未完成任务、卡住任务、小测结果、日报、提醒记录。
- 管理端 `/admin`：录入/批量导入暑假作业、五年级预习、KET 学习目标，生成今日任务。
- 后端 API：FastAPI + SQLite，包含任务源、每日任务、进度事件、小测、日报、周报、提醒日志。
- 题库化小测：按暑假作业、五年级预习、KET 词汇/听力/口语、复习任务生成不同检查题。
- 内容驱动出题：管理端录入“本节学习内容 / 知识点 / KET 词表”后，小测会根据当天学习内容动态生成检查题。
- 五年级上册语数英知识库：默认按武汉使用场景配置统编语文、北师大数学、外研社三起英语，同时可切换人教数学/人教 PEP 英语。
- 家长配置中心：可配置教材版本、每日时长、小测通过线、AI 出题开关。
- 孩子激励：小测通过和今日全清会产生积分和徽章。
- 复习闭环：错题、卡住、未完成任务会进入复习队列，次日优先生成补漏任务。
- 报告落盘：日报和周报会同时入库并生成 Markdown 文件。
- 提醒：默认使用本机系统通知，支持 macOS / Windows / Linux；PushPlus、控制台日志和关闭外部提醒均可配置。
- 定时任务：09:00 生成任务、09:30/10:00 检查 P0 未开始、13:00 检查 P0 未完成、19:30 提醒未完成、20:30 生成日报、21:00 未完成转明日补漏。

## 本地运行

```powershell
cd learning-companion-cloud
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
uvicorn backend.app:app --reload --host 0.0.0.0 --port 8000
```

默认 `.env` 不设置密码，便于本地首次试用；部署到公网前请填写 `CHILD_PASSWORD`、`PARENT_PASSWORD` 和 `ADMIN_PASSWORD`。

打开：

- 孩子端：http://127.0.0.1:8000/child
- 家长端：http://127.0.0.1:8000/parent
- 管理端：http://127.0.0.1:8000/admin

## Docker 运行

```powershell
cd learning-companion-cloud
copy .env.example .env
docker compose up -d --build
```

## 本地一键启动

```powershell
.\scripts\start_local.ps1
```

## 第一次使用流程

1. 打开 `/admin`。
2. 点击“生成示例任务源”，或按真实作业录入三类任务；预习任务建议填写“本节学习内容 / 知识点”。
3. 如果有真实清单，可在“批量导入真实任务”里直接粘贴。
4. 点击“生成今日任务”。
5. 打开 `/child`，让孩子点击“开始下一个任务”。
6. 完成任务后提交小测。
7. 打开 `/parent` 查看看板，或点击“生成今天日报 / 生成本周周报”。

## 提醒配置

默认配置：

```text
NOTIFY_CHANNEL=local
```

`local` 会按运行机器自动选择本机通知：
- macOS：调用系统通知中心，适合苹果电脑本地使用。
- Windows：调用系统托盘气泡通知，适合家里 Windows 电脑使用。
- Linux：调用 `notify-send`，需要桌面环境支持。

可选通道：

```text
NOTIFY_CHANNEL=auto        # 优先本机通知；如果配置了 PUSHPLUS_TOKEN，也会同时发 PushPlus
NOTIFY_CHANNEL=pushplus    # 只发 PushPlus
NOTIFY_CHANNEL=console     # 只输出到服务控制台
NOTIFY_CHANNEL=none        # 不发外部通知，只写提醒日志
NOTIFY_CHANNEL=local,pushplus
PUSHPLUS_TOKEN=你的PushPlusToken
```

PushPlus 只是可选项；不填写 `PUSHPLUS_TOKEN` 也不影响本机通知和家长端提醒记录。所有提醒都会写入 `notification_logs`，家长端仍能看到记录。

## AI 出题配置

系统默认使用本地规则出题，不需要外部服务。若要启用 AI 出题：

1. 在 `.env` 填写 `AI_API_KEY`、`AI_API_URL`、`AI_MODEL`；也兼容系统环境变量 `OPENAI_API_KEY`。
2. 在管理端“家长配置中心”将“启用 AI 出题”改为“是”。
3. AI 失败时会自动回退到本地五年级上册知识库出题。

系统不会全盘扫描本机查找 API Key；只读取当前项目 `.env` 或系统环境变量，避免敏感凭据泄漏。

## Agent 工作流

已实现学习陪跑 Agent 基础闭环：

- `POST /api/agent/plan`：理解自然语言学习目标，生成学习计划并落库。
- `POST /api/agent/daily-tasks`：基于计划、错题和规则生成今日任务。
- `GET /api/agent/task-guidance/{task_id}`：生成/读取任务学习步骤。
- `GET /api/daily-tasks/{task_id}/quiz`：根据当天任务生成测验。
- `POST /api/agent/grade/{task_id}`：保存孩子答案、批改、诊断掌握等级。
- `GET /api/agent/overview`：查看掌握记录和 Agent 决策日志。
- `POST /api/agent/daily-report`：生成带 Agent 结论的日报。

## 家长端 / 管理端密码

`.env` 中可配置 HTTP Basic 认证：

```text
CHILD_USER=child
CHILD_PASSWORD=孩子端密码
PARENT_USER=parent
PARENT_PASSWORD=家长端密码
ADMIN_USER=admin
ADMIN_PASSWORD=管理端密码
```

密码为空时不启用认证，只建议本地试用。

## 数据位置

- SQLite 数据库：`data/learning.db`
- 日报 Markdown：`reports/daily`
- 周报 Markdown：`reports/weekly`

## 备份数据库

```powershell
.\scripts\backup_db.ps1
```

备份文件会生成到 `backups` 目录。

## 生产部署提醒

- 上线前必须设置 `CHILD_PASSWORD`、`PARENT_PASSWORD` 和 `ADMIN_PASSWORD`，或放到反向代理鉴权后。
- Nginx HTTPS 示例在 `deploy/nginx.conf.example`。
- 阿里云详细步骤在 `deploy/README_ALIYUN.md`。
- 阿里云安全组只开放 80、443 和必要 SSH。
- `.env` 不要提交到仓库。
- 建议每天备份 `data/learning.db`。
