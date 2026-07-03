# 阿里云部署步骤

## 1. 上传代码

将 `learning-companion-cloud` 上传到服务器，例如 `/opt/learning-companion-cloud`。

## 2. 配置环境变量

```bash
cd /opt/learning-companion-cloud
cp .env.example .env
```

必须修改：

```text
CHILD_PASSWORD=孩子端密码
PARENT_PASSWORD=家长端密码
ADMIN_PASSWORD=管理端密码
```

提醒通道按部署方式选择：

```text
NOTIFY_CHANNEL=console     # 云服务器推荐：只写控制台和家长端提醒记录
NOTIFY_CHANNEL=none        # 不发外部通知，只写家长端提醒记录
NOTIFY_CHANNEL=pushplus    # 如果已开通 PushPlus，再填写 PUSHPLUS_TOKEN
PUSHPLUS_TOKEN=你的PushPlusToken
```

`local` 本机通知适合 Mac / Windows 本地运行；部署到阿里云服务器时通常没有桌面通知环境，不建议使用。

如需 AI 出题，填写：

```text
AI_ENABLED=true
OPENAI_API_KEY=你的API Key
OPENAI_BASE_URL=https://你的OpenAI兼容接口/v1
OPENAI_MODEL=你的模型名
```

## 3. 启动

```bash
docker compose up -d --build
```

## 4. HTTPS

参考 `deploy/nginx.conf.example` 配置 Nginx 和证书。

## 5. 备份

每天备份：

```bash
cp data/learning.db backups/learning_$(date +%Y%m%d_%H%M%S).db
```
