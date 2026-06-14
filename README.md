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

## macOS 菜单栏工具

可以构建一个本地菜单栏 App，一键切换 OpenAI 代理模式和官方直连模式。第一版默认使用 Docker 重启服务。

```bash
./scripts/build-menubar-app.sh
open "tools/macos-menubar/build/Kiro Gateway Menu.app"
```

菜单功能：

- 切换到 OpenAI 代理模式：写入 `MODE=openai`，然后重启 Docker 服务
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
