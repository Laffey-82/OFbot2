# Chronocat Red 接入指南

> **兼容保留说明**：Chronocat 项目已停止更新，Red 协议仅作兼容保留；新版 Chronocat 仅支持 Satori 协议。新部署建议改用 NapCat（OneBot v11，见 [CONNECTIONS.md](CONNECTIONS.md)）。

## 1. 安装 Chronocat

在 QQNT 客户端中安装 Chronocat 插件（推荐版本 v0.0.51 以上），并确保其 Red 服务已启用。

## 2. 确认配置

Chronocat 的配置文件一般位于：

```text
~/.chronocat/config/chronocat.yml
```

其中应包含 Red 服务信息：

```yaml
servers:
  - type: red
    token: YOUR_TOKEN
    port: 16530
    listen: localhost
```

## 3. 配置 OFbot 2

编辑 `config.yaml`：

```yaml
transport:
  protocol: red
  red:
    enabled: true
    host: 127.0.0.1
    port: 16530
    token: YOUR_TOKEN
    api_base: http://127.0.0.1:16530
```

## 4. 启动

```powershell
py main.py
```

启动日志出现 `red adapter connected` 即表示接入成功。

## 5. 验证

无真实 QQ 环境时，可先运行：

```powershell
py scripts/e2e_smoke.py
```

输出 `PASS: bot replied with pong` 表示完整链路正常。
