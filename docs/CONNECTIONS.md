# QQ 连接方案指南

OFbot 2 支持多连接并存：一个实例可同时接入多套协议 / 多个账号，每个连接独立启停、独立状态，互不影响。出站消息默认走第一个可用的连接，也可以在「监听环境」页为每个群/私聊绑定指定账号。

## 方案总览

| 方案 | 协议 | 传输 | 推荐度 | 说明 |
| --- | --- | --- | --- | --- |
| NapCat | OneBot v11 | 反向 WS（推荐）/ 正向 WS / HTTP | ★★★★★ | NTQQ 无头端，当前最活跃，占用低（50~100MB） |
| LLOneBot | OneBot v11 | WS / HTTP | ★★★★ | NTQQ 插件，与 NapCat 同一适配器 |
| Lagrange.OneBot | OneBot v11 / v12 | WS / HTTP | ★★★★ | 基于 Lagrange.Core，跨平台 |
| OpenShamrock | OneBot v11 | WS / HTTP | ★★★ | Android + LSPosed，需要安卓环境 |
| Chronocat（新版） | Satori | 正向 WS | ★★★ | 项目已停更，现版本仅支持 Satori |
| Chronocat（旧版） | Red | WS + HTTP API | ★★（兼容保留） | Red 协议已停止演进，不推荐新部署 |
| Lagrange.Satori | Satori | 正向 WS | ★★★ | 通过 Satori 协议接入 Lagrange |
| Mirai + mirai-api-http | Mirai HTTP | HTTP / WS / 反向 WS | ★★★ | 老牌方案，verifyKey + session 认证 |
| QQ 官方机器人 | 官方 API v2 | WS Gateway + REST | ★★（受限） | 群内仅接收 @ 机器人消息，存在频控，需官方申请 |

> **媒体能力**：除官方机器人外，各协议发送均透传完整消息段（文本 / @ / 图片 / 语音 / 视频 / 文件 / 表情 / 引用 / 合并转发 / JSON）；官方机器人当前仅支持文本（官方 API 限制）。

## 快速开始（推荐：NapCat OneBot v11 反向 WS）

1. 部署 NapCat（Windows / Linux / macOS），登录一个 QQ 号。
2. NapCat 配置网络：开启「反向 WebSocket」，监听地址 `ws://127.0.0.1:8080/onebot/v11/ws`。
3. 在 OFbot 的「连接中心」确认存在 `napcat_main` 连接（默认配置已内置）：
   - 协议 `onebot` / 版本 `v11` / 模式 `reverse_ws`
   - 地址 `127.0.0.1:8080`，路径 `/onebot/v11/ws`
4. 点击「测试连接」验证；NapCat 连接后连接状态变为「已连接」。

> 反向 WS 模式由 NapCat 主动连入 OFbot，因此「测试连接」不可用是正常的——请确认 NapCat 已启动并正确配置了反向 WS 地址。

## 其他方案要点

### OneBot v12（Lagrange.OneBot）

新增连接：协议 `onebot`、版本 `v12`、模式 `reverse_ws`（推荐）或 `forward_ws`。事件与消息格式按 v12 规范归一化，命令、权限、作用域完全一致。

### Satori（Chronocat 新版 / Lagrange.Satori）

新增连接：协议 `satori`、模式 `forward_ws`，地址为网关的 WebSocket 地址，`token` 填网关鉴权令牌（可选）。发消息走 `{api_base}/v1/message.create`。

### Red（Chronocat 旧版）

协议 `red`、模式 `forward_ws`，填写 `host/port/token/api_base`。该项目已停更，仅作兼容保留；配置页会标注 legacy。

### Mirai

协议 `mirai`、模式 `http`，`token` 填 verifyKey，`api_base` 填 mirai-api-http 地址（默认 `http://host:port`），`self_id` 填机器人 QQ。适配器自动 verify/bind 并轮询 `fetchMessage`。

### QQ 官方机器人（受限）

协议 `qq_official`、模式 `ws_gateway`，填写 `app_id`、`token`（机器人密钥）、`api_base`（默认 `https://api.sgroup.qq.com`）。注意：

- 群聊仅接收 **@ 机器人** 的消息（`GROUP_AT_MESSAGE_CREATE`），与第三方协议能力不对等；
- 存在官方频控，不适合高频自动回复；
- 私聊走 C2C（`C2C_MESSAGE_CREATE`）。

## 连接配置（config.yaml）

```yaml
transport:
  connections:
    - id: napcat_main
      protocol: onebot        # onebot | red | satori | mirai | qq_official
      version: v11            # onebot: v11 | v12
      mode: reverse_ws        # forward_ws | reverse_ws | http | ws_gateway
      enabled: true
      host: 127.0.0.1
      port: 8080
      path: /onebot/v11/ws
      access_token: ""
      token: ""
      api_base: ""
      app_id: ""
      secret: ""
      self_id: ""
      reconnect_interval: 3.0
```

- 旧版 `transport.red` / `transport.onebot` 配置会在首次加载时自动播种为连接列表，随后以 `connections` 为准。
- 连接增删与启停通过 Web「连接中心」或 CLI `ofbot2 connections add` 即时生效。

## 账号绑定（按群路由）

「监听环境」页可为每个群或私聊环境绑定账号（连接 ID）。绑定后：

- 出站消息（定时任务播报、流程动作、插件发送）走绑定连接；
- 入站事件天然来自实际收到消息的连接，不受绑定影响；
- 未绑定时自动选择第一个处于「已连接」状态的连接。
