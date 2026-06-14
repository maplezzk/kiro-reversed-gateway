# kiro-reversed-gateway 中文教程

`kiro-reversed-gateway` 是一个给 Kiro IDE 使用的本地反向代理。它把 Kiro IDE 发出的专有请求转换成 OpenAI 兼容请求，转发到你自己的后端大模型 API，再把 OpenAI SSE 响应转换回 Kiro 期望的 AWS Event Stream 格式。

当前目标：让 Kiro IDE 使用你自己的 OpenAI 兼容模型，同时尽量保留 IDE 里的模型选择、用量、Profile 等 UI 不报错。

---

## 1. 工作原理

```text
Kiro IDE
  │
  ├─ runtime.us-east-1.kiro.dev
  │    └─ 聊天/工具调用请求
  │       Kiro 格式 → OpenAI Chat Completions → 你的后端 → OpenAI SSE → Kiro Event Stream
  │
  └─ management.us-east-1.kiro.dev
       └─ 模型列表 / 用量 / Profile 等控制面请求
          本地返回自定义模型与伪造用量，避免 IDE 报错
```

核心方向：

```text
Kiro 请求格式
  → OpenAI Chat Completions 格式
  → 你的后端 OpenAI 兼容 API
  → OpenAI SSE 响应
  → Kiro AWS Event Stream 二进制格式
  → Kiro IDE
```

---

## 2. 当前已支持的能力

### Runtime 聊天请求

域名：

```text
runtime.us-east-1.kiro.dev
```

主要接口：

```text
POST /generateAssistantResponse
```

支持：

- Kiro 消息格式转 OpenAI messages
- Kiro tools 转 OpenAI tools
- OpenAI SSE 转 Kiro Event Stream
- tool call 缓冲与回传
- `list_directory` 的 home 路径修正：`/Users/xxx/...` → `~/...`
- `reasoning_content` 不直接回传给 Kiro 正文

### Management 控制面请求

域名：

```text
management.us-east-1.kiro.dev
```

Kiro 实际会用 AWS JSON RPC 风格请求，比如：

```http
POST /
x-amz-target: KiroControlPlaneBearerService.ListAvailableModels
content-type: application/x-amz-json-1.0
```

本代理会按 `x-amz-target` 分流：

| `x-amz-target` | 行为 |
|---|---|
| `KiroControlPlaneBearerService.ListAvailableModels` | 返回你的后端 `/models` 转换出的模型列表 |
| `KiroControlPlaneBearerService.GetUsageLimits` | 返回本地伪造用量 |
| `KiroControlPlaneBearerService.ListAvailableProfiles` | 返回本地 Profile |
| `KiroControlPlaneBearerService.GetProfile` | 返回本地 Profile |

也保留了路径形式的兼容接口：

```text
/ListAvailableModels
/getUsageLimits
/ListAvailableProfiles
/GetProfile
```

---

## 3. 环境要求

- macOS
- Python 3.10+
- Kiro IDE
- 一个 OpenAI 兼容后端 API

示例后端：

```text
<BACKEND_API_URL>
```

示例 API Key：

```text
<BACKEND_API_KEY>
```

后端需要支持 OpenAI 兼容接口：

```text
POST <BACKEND_API_URL>/chat/completions
GET  <BACKEND_API_URL>/models
```

`BACKEND_API_URL` 配到 OpenAI API base 即可，例如：

```text
http://<host>:<port>/v1
```

代理会自动拼接：

```text
聊天接口：<BACKEND_API_URL>/chat/completions
模型接口：<BACKEND_API_URL>/models
```

---

## 4. 安装依赖

```bash
cd ~/CliProject/kiro-reversed-gateway
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

---

## 5. 配置 `.env`

编辑：

```bash
cd ~/CliProject/kiro-reversed-gateway
vim .env
```

推荐配置：

```env
SERVER_HOST=0.0.0.0
SERVER_PORT=443
MODE=openai
FORWARD_TARGET=auto

BACKEND_API_URL=http://<host>:<port>/v1
BACKEND_API_KEY=<your-api-key>

# 可选：Kiro 内部轻量任务模型 simple-task 的映射。
# 不配置则原样透传 simple-task；如果你的后端没有 simple-task，改成后端实际存在的模型。
SIMPLE_TASK_MODEL=

USE_TLS=true
CERT_FILE=certs/cert.pem
KEY_FILE=certs/key.pem
LOG_LEVEL=INFO
```

字段说明：

| 配置 | 说明 |
|---|---|
| `MODE=openai` | 启用 Kiro → OpenAI 转换模式 |
| `MODE=forward` | 纯转发到官方 Kiro，用于调试 |
| `FORWARD_TARGET=auto` | 按请求 Host 自动判断 runtime/management/q |
| `BACKEND_API_URL` | OpenAI 兼容 API base，推荐配到 `/v1`，代理自动拼 `/chat/completions` 和 `/models` |
| `BACKEND_API_KEY` | 你的后端 API Key |
| `SIMPLE_TASK_MODEL` | 可选，Kiro 内部 `simple-task` 映射；不配置则原样透传 |
| `USE_TLS=true` | 监听 HTTPS，配合 hosts 劫持 |
| `CERT_FILE` | 本地证书路径 |
| `KEY_FILE` | 本地证书私钥路径 |

---

## 6. 生成并信任 TLS 证书

Kiro IDE 请求的是 HTTPS，所以本地代理需要证书。

### 6.1 生成证书

```bash
cd ~/CliProject/kiro-reversed-gateway
mkdir -p certs

openssl req -x509 -newkey rsa:4096 \
  -keyout certs/key.pem \
  -out certs/cert.pem \
  -days 365 -nodes \
  -subj "/CN=runtime.us-east-1.kiro.dev" \
  -addext "subjectAltName=DNS:runtime.us-east-1.kiro.dev,DNS:management.us-east-1.kiro.dev,DNS:*.kiro.dev"
```

### 6.2 信任证书

```bash
cd ~/CliProject/kiro-reversed-gateway
sudo security add-trusted-cert -d -r trustRoot \
  -k /Library/Keychains/System.keychain certs/cert.pem
```

注意：每次重新生成 `certs/cert.pem` 后都要重新信任一次，因为证书指纹变了。

### 6.3 验证 SAN

```bash
openssl x509 -in certs/cert.pem -noout -text | grep -A1 "Subject Alternative Name"
```

应该能看到：

```text
DNS:runtime.us-east-1.kiro.dev
DNS:management.us-east-1.kiro.dev
DNS:*.kiro.dev
```

---

## 7. 配置 hosts 劫持

把 Kiro 的 runtime 和 management 域名指向本地：

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

应该包含：

```text
127.0.0.1 runtime.us-east-1.kiro.dev
127.0.0.1 management.us-east-1.kiro.dev
```

---

## 8. 启动代理

443 端口需要 sudo：

```bash
cd ~/CliProject/kiro-reversed-gateway
sudo .venv/bin/python main.py --port 443
```

如果没用虚拟环境：

```bash
cd ~/CliProject/kiro-reversed-gateway
sudo python3 main.py --port 443
```

看到类似日志即为启动成功：

```text
Uvicorn running on https://0.0.0.0:443
```

---

## 9. 重启 Kiro IDE

修改 hosts 或代理后，建议完整重启 Kiro：

```bash
osascript -e 'quit app "Kiro"'
open -a Kiro
```

---

## 10. 验证接口

### 10.1 验证模型列表

Kiro 实际模型列表请求走 management 域名的 `POST /` + `x-amz-target`。

```bash
cd ~/CliProject/kiro-reversed-gateway

curl -skS \
  -H 'Host: management.us-east-1.kiro.dev' \
  -H 'content-type: application/x-amz-json-1.0' \
  -H 'x-amz-target: KiroControlPlaneBearerService.ListAvailableModels' \
  -d '{"origin":"AI_EDITOR","profileArn":""}' \
  https://127.0.0.1/
```

正常返回示例：

```json
{
  "models": [
    {
      "modelId": "model-id",
      "modelName": "model-id",
      "description": "Custom backend model: model-id",
      "modelProvider": "DEFAULT",
      "rateMultiplier": 1,
      "rateUnit": "request",
      "tokenLimits": {
        "maxInputTokens": 200000,
        "maxOutputTokens": 8192
      }
    }
  ]
}
```

### 10.2 验证用量

```bash
curl -skS \
  -H 'Host: management.us-east-1.kiro.dev' \
  -H 'content-type: application/x-amz-json-1.0' \
  -H 'x-amz-target: KiroControlPlaneBearerService.GetUsageLimits' \
  -d '{"origin":"AI_EDITOR","profileArn":"","resourceType":"AGENTIC_REQUEST"}' \
  https://127.0.0.1/
```

当前本地伪造用量：

```text
Custom Backend Plan 12 / 100000
```

`nextDateReset` 使用“下月 1 日 00:00 UTC”的稳定时间，避免 Kiro 反复弹出 `Your usage is reset`。

### 10.3 验证 Profile

```bash
curl -skS \
  -H 'Host: management.us-east-1.kiro.dev' \
  -H 'content-type: application/x-amz-json-1.0' \
  -H 'x-amz-target: KiroControlPlaneBearerService.ListAvailableProfiles' \
  -d '{}' \
  https://127.0.0.1/
```

---

## 11. 日志位置

调试日志在：

```text
debug_logs/
```

常用文件：

| 文件 | 说明 |
|---|---|
| `models.jsonl` | 模型列表返回日志 |
| `usage_limits.jsonl` | 用量接口返回日志 |
| `profiles.jsonl` | Profile 接口返回日志 |
| `unknown_requests.jsonl` | 未知请求与 `x-amz-target` 记录 |
| `*_backend_sse_*.jsonl` | 后端 SSE 原始日志 |
| `*_kiro_out_*.bin` | 输出给 Kiro 的二进制流 |

如果用普通用户测试时看到：

```text
Permission denied: debug_logs/xxx.jsonl
```

通常是因为之前用 `sudo` 启动代理，日志文件变成 root 所有。可以修复权限：

```bash
cd ~/CliProject/kiro-reversed-gateway
sudo chown -R "$USER":staff debug_logs
```

---

## 12. 常见问题

### 12.1 模型列表为空

先确认是否拦截到了 management 域名：

```bash
grep 'management.us-east-1.kiro.dev' /etc/hosts
```

再看日志：

```bash
cd ~/CliProject/kiro-reversed-gateway
tail -50 debug_logs/unknown_requests.jsonl
tail -20 debug_logs/models.jsonl
```

关键请求应该是：

```text
POST /
x-amz-target: KiroControlPlaneBearerService.ListAvailableModels
host: management.us-east-1.kiro.dev
```

如果只请求了 `/ListAvailableProfiles`，说明 Kiro 还没触发模型拉取，重启 Kiro 或打开模型选择器。

### 12.2 用量不显示

当前用量是本地伪造的，不是真实 Kiro 官方用量。正常应该显示类似：

```text
Custom Backend Plan 12 / 100000 updated just now
```

如果完全不显示，检查：

```bash
tail -20 debug_logs/usage_limits.jsonl
```

### 12.3 出现 `Your usage is reset` 弹窗

旧版本代理使用 `now + 30天` 作为重置时间，每次请求都会变化，Kiro 会误判为“新月重置”。

现在已改成稳定的“下月 1 日 00:00 UTC”。如果只弹一次，可以忽略；如果反复弹，确认你已经重启了代理并使用最新代码。

### 12.4 证书报错

典型错误：

```text
self signed certificate
```

解决：

```bash
cd ~/CliProject/kiro-reversed-gateway
sudo security add-trusted-cert -d -r trustRoot \
  -k /Library/Keychains/System.keychain certs/cert.pem
```

如果刚重新生成过证书，必须重新执行信任命令。

### 12.5 端口 443 被占用

查看占用：

```bash
sudo lsof -i :443
```

停止旧代理后重新启动。

### 12.6 后端模型列表不对

直接检查后端：

```bash
curl -sS -H 'Authorization: Bearer <BACKEND_API_KEY>' \
  <BACKEND_MODELS_URL>
```

代理会读取这里的 `data[].id`，转换成 Kiro 模型列表。

### 12.7 启动时配置校验失败

代理启动前会检查核心配置，不完整会直接退出，不会半启动。

常见错误：

```text
MODE=openai 时必须配置 BACKEND_API_URL
BACKEND_API_URL 仍包含占位符，请替换成真实地址
TLS 证书不存在
FORWARD_TARGET 只能是 auto/runtime/management/q/random
```

处理方式：

- `MODE=openai`：必须配置 `BACKEND_API_URL`，推荐格式 `http://<host>:<port>/v1`
- `USE_TLS=true`：必须保证 `CERT_FILE` 和 `KEY_FILE` 指向存在的文件
- `FORWARD_TARGET`：只能填 `auto`、`runtime`、`management`、`q`、`random`
- 不要把 `<host>`、`<port>`、`<your-api-key>` 这类占位符原样留在 `.env`

---

## 13. 关闭代理 / 恢复官方 Kiro

停止代理进程后，还需要从 `/etc/hosts` 删除或注释这两行：

```text
127.0.0.1 runtime.us-east-1.kiro.dev
127.0.0.1 management.us-east-1.kiro.dev
```

编辑：

```bash
sudo vim /etc/hosts
```

然后重启 Kiro：

```bash
osascript -e 'quit app "Kiro"'
open -a Kiro
```

---

## 14. 项目结构

```text
kiro-reversed-gateway/
├── main.py                         # FastAPI/uvicorn 入口
├── kiro_reversed/
│   ├── config.py                   # 环境变量配置
│   ├── routes.py                   # runtime/management 路由与本地兜底
│   ├── models.py                   # Kiro 请求模型
│   ├── kiro_to_openai.py           # Kiro 请求 → OpenAI 请求
│   ├── openai_to_kiro.py           # OpenAI SSE → Kiro Event Stream
│   ├── http_client.py              # 后端请求与 /models 拉取
│   └── forward.py                  # 官方 Kiro 转发目标配置
├── certs/
│   ├── cert.pem                    # 本地 TLS 证书
│   └── key.pem                     # 本地 TLS 私钥
├── debug_logs/                     # 调试日志
├── .env                            # 本地配置
├── .env.example                    # 配置模板
├── requirements.txt
└── README.md
```

---

## 15. 当前限制

- 用量、Profile 是本地伪造数据，不代表真实 Kiro 官方账号状态。
- management 控制面只对已知接口做本地兜底，未知接口会记录到 `debug_logs/unknown_requests.jsonl`。
- 如果 Kiro IDE 后续修改接口名或字段结构，需要根据日志补 handler。
- 该项目用于本地研究与调试，请不要用于未授权场景。

---

## 16. Clash / fake-ip 配置说明

如果系统里启用了 Clash、Clash Verge、ClashX 或类似代理，并且 DNS 使用 `fake-ip` 模式，需要特别处理 Kiro 域名。

原因：

- Kiro IDE 请求的是 HTTPS 域名：
  - `runtime.us-east-1.kiro.dev`
  - `management.us-east-1.kiro.dev`
- 本项目依赖这些域名解析到本机 `127.0.0.1`
- 如果 Clash fake-ip 给这些域名分配了 fake IP，流量可能不会进入本地 443 代理
- 结果可能表现为：证书不匹配、连接失败、模型列表为空、请求没有进 `debug_logs`

推荐配置：

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

各字段作用：

| 字段 | 作用 |
|---|---|
| `fake-ip-filter` | 让这些域名不要分配 fake-ip，避免覆盖本地劫持 |
| `hosts` | 在 Clash 内部直接把域名解析到 `127.0.0.1` |
| `rules DIRECT` | 确保流量直连本机，不走远端代理节点 |

如果你的 Clash 客户端不支持 `hosts` 字段，可以只保留：

```yaml
dns:
  enhanced-mode: fake-ip
  fake-ip-filter:
    - runtime.us-east-1.kiro.dev
    - management.us-east-1.kiro.dev

rules:
  - DOMAIN,runtime.us-east-1.kiro.dev,DIRECT
  - DOMAIN,management.us-east-1.kiro.dev,DIRECT
```

然后继续使用系统 `/etc/hosts`：

```text
127.0.0.1 runtime.us-east-1.kiro.dev
127.0.0.1 management.us-east-1.kiro.dev
```

验证方式：

```bash
scutil --dns | grep -i kiro -A2
curl -vk https://runtime.us-east-1.kiro.dev/health
```

更直接的验证是看代理日志：如果 Kiro 操作后 `debug_logs/` 完全没有新增请求，通常就是域名没有正确打到本地代理。

---

## 17. 一键启动脚本

项目提供：

```bash
./scripts/start.sh
```

脚本职责：

- 检查 `.env` 是否存在；不存在时从 `.env.example` 复制并退出，要求用户先编辑配置
- 自动创建 `.venv`
- 安装 `requirements.txt`
- TLS 模式下检查 `certs/cert.pem` 和 `certs/key.pem`
- 没有证书时自动生成覆盖 runtime / management 的自签名证书
- 443 端口需要 root 权限时自动用 `sudo -E` 重启
- 最终调用 `main.py`，由应用执行启动前配置校验

常用参数：

```bash
./scripts/start.sh
./scripts/start.sh --no-tls --port 8443
./scripts/start.sh --skip-install
./scripts/start.sh --host 127.0.0.1 --port 8443 --no-tls
./scripts/start.sh --help
```

环境变量覆盖：

```bash
PYTHON_BIN=python3.12 ./scripts/start.sh
VENV_DIR=.venv ./scripts/start.sh
SKIP_INSTALL=true ./scripts/start.sh
NO_TLS=true PORT=8443 ./scripts/start.sh
```

注意：脚本可以生成证书，但不能替用户信任证书。macOS 上仍需执行：

```bash
sudo security add-trusted-cert -d -r trustRoot \
  -k /Library/Keychains/System.keychain certs/cert.pem
```

---

## 18. Docker 服务化部署

项目包含：

```text
Dockerfile
docker-compose.yml
.dockerignore
```

### 18.1 镜像行为

`Dockerfile` 使用 `python:3.12-slim`：

- 工作目录：`/app`
- 安装 `requirements.txt`
- 暴露端口：`443`、`8443`
- 默认命令：`python main.py --port 443`
- 使用非 root 用户 `kiro` 运行应用

### 18.2 Compose 行为

`docker-compose.yml` 默认：

```yaml
ports:
  - "443:8443"
volumes:
  - ./certs:/app/certs:ro
  - ./debug_logs:/app/debug_logs
```

也就是说：

- 宿主机 `443` 会转到容器 `8443`
- TLS 证书从宿主机只读挂载
- debug 日志写回宿主机目录

### 18.3 后端在宿主机时的 URL

容器里的 `127.0.0.1` 是容器自身，不是 macOS 宿主机。

所以如果后端跑在宿主机，应配置：

```env
BACKEND_API_URL=http://host.docker.internal:<port>/v1
```

不要配置：

```env
BACKEND_API_URL=http://127.0.0.1:<port>/v1
```

### 18.4 hosts 仍然改宿主机

Kiro IDE 运行在宿主机，所以 DNS 劫持仍然发生在宿主机：

```text
127.0.0.1 runtime.us-east-1.kiro.dev
127.0.0.1 management.us-east-1.kiro.dev
```

请求路径是：

```text
Kiro IDE -> 宿主机 127.0.0.1:443 -> Docker 端口映射 -> 容器 8443
```

### 18.5 证书信任仍然在宿主机

容器只负责提供 HTTPS 服务，macOS 信任证书仍然要在宿主机执行：

```bash
sudo security add-trusted-cert -d -r trustRoot \
  -k /Library/Keychains/System.keychain certs/cert.pem
```

### 18.6 常用命令

构建并启动：

```bash
docker compose up -d --build
```

查看日志：

```bash
docker compose logs -f
```

重启：

```bash
docker compose restart
```

停止：

```bash
docker compose down
```

进入容器：

```bash
docker compose exec kiro-reversed-gateway sh
```

### 18.7 常见问题

#### 容器启动后 Kiro 连不上

检查：

```bash
docker compose ps
docker compose logs -f
sudo lsof -i :443
```

确认宿主机 `/etc/hosts` 已配置 Kiro 域名。

#### 后端连接失败

如果后端跑在宿主机，确认使用：

```env
BACKEND_API_URL=http://host.docker.internal:<port>/v1
```

#### 证书报错

确认：

- `./certs/cert.pem` 存在
- `./certs/key.pem` 存在
- `cert.pem` 已在 macOS 系统钥匙串信任

#### debug_logs 权限问题

Compose 会把 `./debug_logs` 挂载到容器。若出现权限问题，可在宿主机执行：

```bash
mkdir -p debug_logs
chmod 777 debug_logs
```
