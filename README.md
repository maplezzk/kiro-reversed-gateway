# kiro-reversed-gateway

`kiro-reversed-gateway` 是一个给 Kiro IDE 使用的本地反向代理。

它可以把 Kiro IDE 的请求转成 OpenAI 兼容格式，发给你自己的大模型后端，再把后端响应转回 Kiro IDE 能识别的格式。

简单说：**让 Kiro IDE 使用你自己的 OpenAI 兼容模型。**

```text
Kiro IDE
  → kiro-reversed-gateway
  → 你的 OpenAI 兼容后端
  → kiro-reversed-gateway
  → Kiro IDE
```

---

## 主要功能

- 拦截 Kiro runtime 请求
- 转换 Kiro 请求为 OpenAI Chat Completions 请求
- 转换 OpenAI SSE 响应为 Kiro Event Stream 响应
- 支持工具调用
- 支持图片输入
- 从后端 `/models` 读取模型列表并显示到 Kiro IDE
- 本地兜底 Kiro Profile / Usage 接口，避免 IDE 报错

技术细节见：[`docs/TECHNICAL_DETAILS.md`](docs/TECHNICAL_DETAILS.md)

---

## 快速开始

### 1. 配置 `.env`

复制模板：

```bash
cd ~/CliProject/kiro-reversed-gateway
cp .env.example .env
```

编辑 `.env`：

```env
SERVER_HOST=0.0.0.0
SERVER_PORT=443
MODE=openai
FORWARD_TARGET=auto

# 配到 OpenAI 兼容 API base 即可，代理会自动拼 /chat/completions 和 /models
BACKEND_API_URL=http://<host>:<port>/v1
BACKEND_API_KEY=<your-api-key>

# 如果你的后端没有 simple-task，可以把 Kiro 内部轻量任务映射到某个已有模型
SIMPLE_TASK_MODEL=

USE_TLS=true
CERT_FILE=certs/cert.pem
KEY_FILE=certs/key.pem
LOG_LEVEL=INFO
```

说明：

- `BACKEND_API_URL` 推荐配到 `/v1`
- 代理会请求：
  - `POST ${BACKEND_API_URL}/chat/completions`
  - `GET ${BACKEND_API_URL}/models`
- 如果不需要 API Key，可以留空 `BACKEND_API_KEY`

---

### 2. 一键启动

```bash
./scripts/start.sh
```

脚本会自动：

- 创建 `.venv`
- 安装依赖
- 检查 `.env`
- 没有证书时生成自签名证书
- 443 端口需要权限时自动切换 `sudo`
- 启动前做核心配置校验

常用参数：

```bash
# HTTP 调试模式
./scripts/start.sh --no-tls --port 8443

# 跳过依赖安装，加快重复启动
./scripts/start.sh --skip-install

# 查看帮助
./scripts/start.sh --help
```

如果脚本首次生成了证书，仍然需要在 macOS 上信任证书：

```bash
sudo security add-trusted-cert -d -r trustRoot \
  -k /Library/Keychains/System.keychain certs/cert.pem
```

注意：每次重新生成证书后都要重新信任。

---

### 3. 配置 hosts

把 Kiro 域名指向本机：

```bash
sudo sh -c 'cat >> /etc/hosts <<EOF
127.0.0.1 runtime.us-east-1.kiro.dev
127.0.0.1 management.us-east-1.kiro.dev
EOF'
```

确认：

```bash
grep 'kiro.dev' /etc/hosts
```

---

### 4. 重启 Kiro

```bash
osascript -e 'quit app "Kiro"'
open -a Kiro
```

然后在 Kiro 里选择你的后端模型开始使用。

---

## Docker 服务化

如果你想把代理作为后台服务跑，推荐用 Docker Compose。

### 1. 准备 `.env`

```bash
cp .env.example .env
```

如果你的后端跑在宿主机，`.env` 里不要写 `127.0.0.1`，要写：

```env
BACKEND_API_URL=http://host.docker.internal:<port>/v1
BACKEND_API_KEY=<your-api-key>
```

原因：容器内的 `127.0.0.1` 指的是容器自己，不是宿主机。

### 2. 准备证书

如果还没有证书，可以先用一键脚本生成：

```bash
./scripts/start.sh --help
./scripts/start.sh --no-tls --port 8443
```

或者手动生成，技术细节见 [`docs/TECHNICAL_DETAILS.md`](docs/TECHNICAL_DETAILS.md)。

生成后在宿主机信任证书：

```bash
sudo security add-trusted-cert -d -r trustRoot \
  -k /Library/Keychains/System.keychain certs/cert.pem
```

### 3. 启动容器

推荐使用脚本：

```bash
./scripts/docker-start.sh
```

常用参数：

```bash
# 重新构建并启动，默认行为
./scripts/docker-start.sh

# 不重新构建，直接启动
./scripts/docker-start.sh --no-build

# 启动后跟随日志
./scripts/docker-start.sh --logs

# 启动前修复 debug_logs 写入权限
./scripts/docker-start.sh --fix-permissions

# 不修复 debug_logs 写入权限
./scripts/docker-start.sh --no-fix-permissions
```

等价 Docker Compose 命令：

```bash
docker compose up -d --build
```

查看日志：

```bash
docker compose logs -f
```

### 4. 停止容器

推荐使用脚本：

```bash
./scripts/docker-stop.sh
```

如果需要同时删除匿名卷：

```bash
./scripts/docker-stop.sh --volumes
```

等价 Docker Compose 命令：

```bash
docker compose down
```

### 5. 网络注意事项

- 如果后端跑在宿主机，容器内不能用 `127.0.0.1` 或 `localhost`，要用：

```env
BACKEND_API_URL=http://host.docker.internal:<port>/v1
```

- `scripts/docker-start.sh` 默认会先尝试修复 `debug_logs` 写入权限；如果目录是 root 拥有，它会自动提示并尝试用 `sudo` 修复

---

## Clash 配置要点

如果你使用 Clash / Clash Verge / ClashX，建议确保 Kiro 域名不要被 fake-ip 污染，直接解析到本机。

示例片段：

```yaml
dns:
  enable: true
  enhanced-mode: fake-ip
  fake-ip-filter:
    - runtime.us-east-1.kiro.dev
    - management.us-east-1.kiro.dev

hosts:
  runtime.us-east-1.kiro.dev: 127.0.0.1
  management.us-east-1.kiro.dev: 127.0.0.1

rules:
  - DOMAIN,runtime.us-east-1.kiro.dev,DIRECT
  - DOMAIN,management.us-east-1.kiro.dev,DIRECT
```

如果你的 Clash 版本不支持 `hosts`，就继续用系统 `/etc/hosts`。

更详细说明见：[`docs/TECHNICAL_DETAILS.md`](docs/TECHNICAL_DETAILS.md)

---

## 常用验证

### 验证模型列表

```bash
curl -skS \
  -H 'Host: management.us-east-1.kiro.dev' \
  -H 'content-type: application/x-amz-json-1.0' \
  -H 'x-amz-target: KiroControlPlaneBearerService.ListAvailableModels' \
  -d '{"origin":"AI_EDITOR","profileArn":""}' \
  https://127.0.0.1/
```

### 验证用量接口

```bash
curl -skS \
  -H 'Host: management.us-east-1.kiro.dev' \
  -H 'content-type: application/x-amz-json-1.0' \
  -H 'x-amz-target: KiroControlPlaneBearerService.GetUsageLimits' \
  -d '{"origin":"AI_EDITOR","profileArn":"","resourceType":"AGENTIC_REQUEST"}' \
  https://127.0.0.1/
```

---

## 日志

日志在：

```text
debug_logs/
```

常用文件：

- `models.jsonl`：模型列表
- `usage_limits.jsonl`：用量接口
- `profiles.jsonl`：Profile 接口
- `unknown_requests.jsonl`：未知 control-plane 请求
- `*_backend_sse_*.jsonl`：后端 SSE 原始日志

---

## 恢复官方 Kiro

停止代理后，从 `/etc/hosts` 删除或注释：

```text
127.0.0.1 runtime.us-east-1.kiro.dev
127.0.0.1 management.us-east-1.kiro.dev
```

然后重启 Kiro：

```bash
osascript -e 'quit app "Kiro"'
open -a Kiro
```

---

## 更多文档

- 技术细节：[`docs/TECHNICAL_DETAILS.md`](docs/TECHNICAL_DETAILS.md)
