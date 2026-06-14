# kiro-reversed-gateway

`kiro-reversed-gateway` 是一个给 Kiro IDE 使用的本地反向代理。它把 Kiro 请求转成 OpenAI 兼容请求，发给你自己的后端，再把响应转回 Kiro。

## 怎么用

### 1. 配置 `.env`

```bash
cp .env.example .env
```

编辑 `.env`，至少填好：

```env
BACKEND_API_URL=http://<host>:<port>/v1
BACKEND_API_KEY=<your-api-key>
```

### 2. 本地启动

```bash
./scripts/start.sh
```

如果需要参数：

```bash
./scripts/start.sh --help
```

### 3. Docker 启动

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

### 4. 配置网络劫持

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

### 5. 信任证书

首次生成证书后，在 macOS 上信任一次：

```bash
sudo security add-trusted-cert -d -r trustRoot \
  -k /Library/Keychains/System.keychain certs/cert.pem
```

### 6. 重启 Kiro

```bash
osascript -e 'quit app "Kiro"'
open -a Kiro
```

## 提示

- `./scripts/start.sh` 会在 TLS 模式下自动生成一次证书（仅首次缺失时）
- Docker 场景下，后端如果跑在宿主机，请用 `host.docker.internal`
- 容器日志直接看 `docker compose logs -f`
- 如果你的系统开了 Clash fake-ip，务必把 Kiro 域名加入 `fake-ip-filter`

## 其他文档

- 技术细节：[`docs/TECHNICAL_DETAILS.md`](docs/TECHNICAL_DETAILS.md)
