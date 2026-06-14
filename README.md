# kiro-reversed-gateway

`kiro-reversed-gateway` 是一个给 Kiro IDE 使用的本地反向代理。它把 Kiro 请求转成 OpenAI 兼容请求，发给你自己的后端，再把响应转回 Kiro。

## 准备工作

### 1. 配置 `.env`

```bash
cp .env.example .env
```

编辑 `.env`。

走自定义 OpenAI 后端：

```env
MODE=openai
BACKEND_API_URL=http://<host>:<port>/v1
BACKEND_API_KEY=<your-api-key>
```

走混合模式：官方模型走 Kiro，自定义模型走 OpenAI 后端。自定义模型会在列表里显示成 `custom/<backend_model_id>`。

```env
MODE=hybrid
BACKEND_API_URL=http://<host>:<port>/v1
BACKEND_API_KEY=<your-api-key>
FORWARD_TARGET=auto
KIRO_RUNTIME_IP=<runtime-ip>
KIRO_MANAGEMENT_IP=<management-ip>
```

纯官方转发：

```env
MODE=forward
FORWARD_TARGET=auto
KIRO_RUNTIME_IP=<runtime-ip>
KIRO_MANAGEMENT_IP=<management-ip>
# 如果 FORWARD_TARGET=q 或 random，还需要：
KIRO_Q_IP=<q-ip>
```

### 2. 配置网络劫持

把 Kiro 域名指到本机：

```bash
sudo sh -c 'cat >> /etc/hosts <<EOF
127.0.0.1 runtime.us-east-1.kiro.dev
127.0.0.1 management.us-east-1.kiro.dev
EOF'
```

如果你使用 Clash / Clash Verge / ClashX，并且开启了 `fake-ip`，还需要加：

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

如果你的 Clash 支持 `hosts`，也可以直接加：

```yaml
hosts:
  runtime.us-east-1.kiro.dev: 127.0.0.1
  management.us-east-1.kiro.dev: 127.0.0.1
```

### 3. 证书

TLS 模式下，启动脚本会自动处理证书：缺失时生成，macOS 上自动信任。已存在证书不会重建。

## 本地启动

```bash
./scripts/start.sh
```

查看参数：

```bash
./scripts/start.sh --help
```

## Docker 启动

```bash
./scripts/docker-start.sh
./scripts/docker-stop.sh
```

常用命令：

```bash
./scripts/docker-start.sh --logs
./scripts/docker-start.sh --no-build
./scripts/docker-stop.sh --volumes
```

如果你的后端跑在宿主机，Docker 场景下要用：

```env
BACKEND_API_URL=http://host.docker.internal:<port>/v1
```

## Clash 代理模式（不改 hosts）

如果不想改 `/etc/hosts`，可以让 Clash 把 Kiro 域名转到本地 CONNECT proxy。

默认启动会同时暴露：

```text
127.0.0.1:443                   -> HTTPS 网关
127.0.0.1:${CONNECT_PROXY_PORT}  -> Clash 用的 HTTP CONNECT 代理
```

端口可在 `.env` 配置，默认是：

```env
CONNECT_PROXY_PORT=7898
```

启动方式不变：

```bash
./scripts/start.sh
```

或 Docker：

```bash
./scripts/docker-start.sh
```

不需要单独启动 proxy。确实不想启动 CONNECT proxy 时，本地模式可以用：

```bash
./scripts/start.sh --no-connect-proxy
```

Clash 配置示例：

```yaml
proxies:
  - name: KiroGateway
    type: http
    server: 127.0.0.1
    port: 7898  # 跟 .env 的 CONNECT_PROXY_PORT 保持一致

rules:
  - DOMAIN,runtime.us-east-1.kiro.dev,KiroGateway
  - DOMAIN,management.us-east-1.kiro.dev,KiroGateway
  - DOMAIN,q.us-east-1.amazonaws.com,KiroGateway
```

注意：不要把 Clash 的 `proxy` 直接指到 `443`，`443` 是 HTTPS 网关端口，不是 HTTP 代理端口。

## macOS 菜单栏工具

可以构建一个本地菜单栏 App，一键切换 OpenAI 代理模式和官方直连模式。第一版默认使用 Docker 重启服务。

```bash
./scripts/build-menubar-app.sh
open "tools/macos-menubar/build/Kiro Gateway Menu.app"
```

菜单栏标题会直接显示当前状态：

- `Kiro：OpenAI`
- `Kiro：混合`
- `Kiro：直连`
- `Kiro：异常`

菜单功能：

- 切换到 OpenAI 代理模式：写入 `MODE=openai`，然后重启 Docker 服务
- 切换到混合模式：写入 `MODE=hybrid`，然后重启 Docker 服务
- 切换到官方直连模式：写入 `MODE=forward`，校验 `KIRO_*_IP`，然后重启 Docker 服务
- 重启 Docker 服务
- 查看 Docker 日志
- 打开项目目录

菜单栏工具默认项目路径：

```text
~/CliProject/kiro-reversed-gateway
```

## 提示

- 本地启动和 Docker 启动是两条独立路径
- 容器日志直接看 `docker compose logs -f`
- 更详细的技术细节见：[`docs/TECHNICAL_DETAILS.md`](docs/TECHNICAL_DETAILS.md)
