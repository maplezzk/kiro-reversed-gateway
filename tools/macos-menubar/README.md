# Kiro Gateway Menu

macOS 菜单栏工具，用于一键切换 `kiro-reversed-gateway` 的运行模式。

## 构建

在项目根目录运行：

```bash
./scripts/build-menubar-app.sh
```

生成结果：

```text
tools/macos-menubar/build/Kiro Gateway Menu.app
```

启动：

```bash
open "tools/macos-menubar/build/Kiro Gateway Menu.app"
```

## 显示

菜单栏标题直接显示当前状态：

```text
Kiro：OpenAI
Kiro：混合
Kiro：直连
Kiro：异常
```

## 功能

- 切换到 OpenAI 代理模式
- 切换到混合模式
- 切换到官方直连模式
- 重启 Docker 服务
- 查看 Docker 日志
- 打开项目目录
- 刷新当前状态

## 约定

当前第一版默认项目路径为：

```text
~/CliProject/kiro-reversed-gateway
```

切换模式后默认调用 Docker：

```bash
./scripts/restart-docker.sh
```

因此推荐搭配 Docker 方式启动网关。
