# 术语表

按字母/主题归类 OFbot 2 文档与代码中常用的术语。

## 连接与协议

- **OneBot v11 / v12**：QQ 机器人开放协议标准；v11 为广泛兼容的经典版本，v12 为社区演进版本。OFbot 通过 `protocol: onebot` + `version` 区分。
- **反向 WebSocket（reverse_ws）**：协议端（如 NapCat）主动连接本框架的 WS 端点（如 `/onebot/v11/ws`）。
- **正向 WebSocket（forward_ws）**：本框架主动连接协议端的 WS 地址。
- **HTTP 事件上报**：协议端以 HTTP POST 推送事件；本框架同时支持反向 HTTP 与轮询（Mirai）。
- **NapCat / LLOneBot / Lagrange / Chronocat / Mirai / QQ 官方**：常见协议端实现，详见 [CONNECTIONS.md](CONNECTIONS.md)。
- **access_token / token / verifyKey**：连接鉴权凭据，配置项名称因协议而异。

## 消息与事件

- **MessageSegment**：消息的最小组成单元（文本 / @ / 图片 / 语音 / 视频 / 文件 / 表情 / 引用等）。
- **BotEvent**：协议端归一化后的事件基类（消息、通知、请求、生命周期）。
- **事件总线（EventBus）**：自研异步发布/订阅总线，`dispatch` 广播事件、`on` 订阅事件；父类订阅可收到子类事件。
- **trace_id**：贯穿一次消息/任务处理的链路 ID，用于日志串联。

## 作用域与权限

- **监听环境（Scope）**：一条消息所属的环境，群消息为 `group:<id>`，私聊为 `private:*`。
- **功能开关（Feature）**：插件 `features` 中声明的最小功能单元，可在每个环境独立设为 开启/关闭/跟随默认。
- **权限点（Permission）**：命令或能力要求的权限标识（如 `bot.command`、`my_plugin.ping`），环境覆盖优先。
- **黑名单 / 静默模式**：环境级拦截配置；静默模式下被拦截的命令不返回提示。

## 插件

- **声明式插件**：命令/任务/监听器在 `plugin.json` 的 `features` 中声明，加载时自动注册校验。
- **plugin.json**：插件清单，唯一事实来源（`name`/`api_version`/`features`/`sandbox` 等）。
- **PluginContext（ctx）**：插件访问框架能力的入口（`ctx.commands`、`ctx.records`、`ctx.ai` 等）。
- **sandbox**：插件运行模式，`inline`（进程内）或 `process`（子进程隔离 + 能力白名单）。
- **插件市场（plugin-repo）**：官方插件仓库，支持 URL / 本地双数据源与 SHA-256 校验。

## 自动化

- **定时任务（Task）**：DB 持久化的 interval/cron/date 任务，启动时恢复。
- **流程引擎（Workflow）**：由触发器（消息/定时/Webhook/记录变更）驱动、动作可组合的自动化。
- **Webhook**：HTTP 回调接收端点，可触发流程并记录历史。
- **执行历史（Executions）**：定时任务与流程运行的统一历史视图，支持导出与重试。

## 数据与服务

- **记录中心（Records）**：类型化数据表，支持字段 schema、状态机与聚合。
- **状态机（State Machine）**：记录状态流转定义（如订单 pending → done）。
- **聚合（Aggregation）**：对记录按字段分组统计。
- **审计日志（Audit）**：敏感操作的结构化记录，支持保留期清理与导出。
- **备份 / 导出 / 文件**：数据备份与恢复、记录/审计导出、文件中心。

## 部署与安全

- **config.yaml**：主配置（`basic`/`transport`/`web`/`security`/`runtime` 等），修改即时生效。
- **作用域策略（runtime.scopes）**：按环境保存功能开关/权限/黑名单/账号绑定。
- **API Key**：REST 接口鉴权；未配置时 `/api/v1/*` 要求后台管理员登录会话。
- **CSRF / 登录锁定 / 限流**：Web 后台安全机制。
