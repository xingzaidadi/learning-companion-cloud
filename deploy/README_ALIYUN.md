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
PUSHPLUS_TOKEN=你的PushPlusToken
```

如需 AI 出题，填写：

```text
AI_API_KEY=你的API Key
AI_API_URL=https://你的OpenAI兼容接口/v1/chat/completions
AI_MODEL=你的模型名
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
