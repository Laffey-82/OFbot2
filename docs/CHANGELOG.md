# Changelog

## v3.5.0（2026-08）— 稳定与性能（OneBot 生态 / 沙箱审计参照）

### 协议契约测试矩阵

- 新增 `tests/test_protocol_matrix.py`：OneBot v11/v12、Red、Satori、Mirai、官方机器人的假服务端参数化测试，覆盖握手、收发、消息归一化、鉴权失败、notice 分发（GroupPoke）与媒体段。
- `docs/CONNECTIONS.md` 升级为「能力 × 实现」矩阵，标注各协议的能力差异。

### 性能基准

- 新增 `scripts/benchmark.py`：全链路（解析 → 作用域 → 规则 → 参数绑定 → handler → 回复）吞吐与 P50/P95、长消息分片、后台任务队列饱和；报告归档 `docs/benchmarks/v3.5.0.md`。
- 新增 `split_message()` 通用长消息分片工具（1800 字符阈值、优先换行切分）。
- 已知约束：bubus 事件总线在大量 pending 事件（约 30-50 个并发突发）时存在库级竞态，且 `stop()` 在高积压时会挂起；基准已隔离总线测量框架链路，生产路径适配器收包天然串行（每次消息 2-4 个事件）。

### 可观测与部署

- trace_id 链路贯穿：`BotClient.handle_bot_event` 生成并注入异步上下文，日志增加 `trace=...` 字段，`CommandContext.trace_id` 供插件读取；AI 调用与出站发送自动继承。
- 告警模板库：内置 6 个标准模板（连接断开 / 任务失败 / 流程失败 / CPU / 内存 / Agent 工具失败），Web 告警页一键安装，自愈中心联动保留。
- Docker 多架构构建支持（amd64/arm64）、非 root 运行、健康检查；compose 增加命名卷、日志轮转、仅本机端口；新增 `deploy/ofbot2.service` systemd 单元示例。

### 插件安全审计

- `PluginInstaller.audit_zip()`：安装前静态检查文件白名单 / 数量 / 体积、网络库引用、代码执行模式、secret 直赋、循环发送风控；审计记录持久化到 `plugins/.audit/`。
- CLI：`ofbot2 plugin install` 安装前打印审计摘要；新增 `ofbot2 plugin audit [zip] [--name]`。

## v3.4.0（2026-08）— 能力深化（NoneBot2 / Koishi / LangBot 参照）

### 响应规则（NoneBot2 Rule 轻量版）

- 声明式规则：`plugin.json` 的 `commands[].rules` / `listeners[].rules` 支持 `to_me`、`keyword`、`regex`、`group_only`、`private_only`、`in_group`；加载期校验未注册规则。
- `ctx.rules.register(name, checker)` 支持插件自定义规则；命令分发顺序：作用域门控 → 规则匹配 → 参数解析 → 执行；监听器在功能开关之后、处理器之前匹配规则。

### 多轮会话（Koishi / ZeroBot 式交互）

- 新增 `ctx.session`（`SessionManager`）：以 bot+群+用户 为键，TTL 过期 + 容量上限淘汰；`pending(question)` / `confirm()` / `cancel()` / `clear()`。
- 命令声明 `session: true` 后，`CommandContext.session` 提供该会话上下文；`plugins/template` 新增 `/ask` 确认流示例。

### Agent 工具调用循环（LangBot 式）

- `AgentRunner` 升级：会话记忆（每会话最近 N 轮）、工具 schema 自动生成（inspect 签名）、最大轮次与工具超时、敏感工具权限点授权。
- function-calling Provider（OpenAI 兼容）自动走工具调用；不支持的原生 Provider 自动降级 ReAct 文本解析。
- 框架注册 5 个内置工具（send_group / send_private / records_create / records_list / ai_chat）；AI 页新增工具清单与「会话运行日志」，支持 Web 直接试跑 Agent。
- 修复 `AIService._provider` 在无 mock Provider 注册时 `dict.get` 急切求值导致的 KeyError。

### 流程引擎增强

- `WorkflowEngine.dry_run()` 与 Web「干跑测试」：校验触发器/条件/步骤动作是否注册，不实际执行。
- 运行步骤记录每步耗时（`elapsed_ms`），运行详情页展示步骤级回放。
- 流程模板库：内置 4 个模板（消息回复 / AI 对话 / 定时写记录 / Webhook 转发），Web 一键导入，支持本地 JSON 模板目录扩展。

### 多账号运维

- `BotClient.health()`：连接健康度评分（连接状态 + 心跳新鲜度 + 消息吞吐），连接中心新增健康度卡片。
- 连接中心支持 CSV 批量导入群-账号绑定（`group_id,connection_id`）。
- 重连计数并入 `BotClient` 计数器，审计按连接 ID 区分。

## v3.3.0（2026-08）— 承重墙补课

### P0 数据与消息

- 迁移持久化：新增 `MigrationRecord` 表，迁移执行成功后落库，重启不重复执行；失败不记录。
- 消息段工厂：`MessageSegment.text/at/image/voice/video/record/file/face/reply/forward/markdown/json`，`Message` 支持拼接；发送侧补齐全段透传。
- OneBot v11 发送改用消息数组（规避 CQ 码转义）；v12 / Red / Satori / Mirai 同步补齐 voice/video/file/face/markdown/json 等映射。

### P1 连接与事件

- 统一指数退避 + 抖动重连（`BaseAdapter`）：基础 3s、×2、上限 60s、±20% 抖动、可配置 `reconnect_max_attempts` 熔断；收包超时视为心跳过期触发重连。
- 事件细分：`GroupPoke`（戳一戳）、`FileUploaded`（群文件上传）；`MessageRecalled` 补齐字段；OneBot v11/v12 按 notice_type 分发，Red 做 best-effort 映射。

### P2 能力诚实化与生态

- AI：OpenAI 兼容 Provider 实现 embeddings / image / speech_to_text / text_to_speech；Ollama 实现 embeddings；不支持的 Provider/OCR 明确报 `AIServiceError`；Mock 不再伪造多模态返回值；AI 页新增能力支持矩阵。
- 插件仓库扩充 4 个官方插件：announcement、points、poll、random_choice（共 10 个）。

## v3.2.0（2026-08）— 公开准备 + 插件生态

### 社区设施

- Issue 模板（Bug / 功能建议 / 插件投稿）、PR 模板、Dependabot 依赖更新。
- Release 工作流：推送 `v*` tag 自动生成 GitHub Release。
- CI 增加 `pip-audit` 依赖漏洞扫描；插件仓库校验保持内容级比对。

### 插件市场升级

- 市场页支持搜索与分类筛选、插件详情展开、已安装版本与可更新标记。
- 支持覆盖更新安装（保留旧包备份），Web 与 CLI 均可执行。
- 插件仓库扩充官方插件：keyword_reply、schedule_message、signin、todo。

### 文档

- 新增英文概览 `docs/README.en.md` 与 3 分钟上手 `docs/QUICKSTART.md`；readme 与 Web 文档导航增加入口。

### 新手引导与国际化骨架

- 设置向导重构为三步走：连接机器人 → 安装插件 → 开启功能，保留环境自检；各页面空状态给出下一步指引。
- 仪表盘新增「新手上路」入口卡片。
- Web i18n 骨架：`app/core/i18n.py` 翻译表 + `basic.language`（zh-CN / en）配置，侧边栏导航接入；配置页可切换语言。

## v3.1.0（2026-08）— 监听环境化重构 + 多连接接入

### 监听环境（逐群/私聊独立控制）

- 新增作用域策略 `ScopePolicyService`：每个监听环境独立控制功能开关、权限覆盖、黑名单、静默模式与账号绑定；优先级为 `group:<id>` > `group:*` > 功能默认值。
- 新增 Web「监听环境」页 `/scopes`：功能三态开关矩阵（开启/关闭/跟随默认）+ 批量操作 + 逐环境黑名单/权限覆盖/账号绑定/静默开关。
- 命令分发接入作用域：黑名单 → 文本校验 → 功能开关（友好提示或静默）→ 冷却/限流 → 权限覆盖 → 执行；未找到命令给出相近建议；支持 `@bot /命令` 触发。
- `/help` 按当前环境过滤未开启功能，展示用法与示例，长帮助自动分片。

### 多连接接入

- `transport.connections` 连接配置列表，支持 OneBot v11（正/反向 WS + HTTP）、OneBot v12、Red（legacy）、Satori、Mirai、QQ 官方机器人并存；`ConnectionManager` 统一生命周期，单连接故障不影响其他。
- Web「连接中心」新增/启停/删除连接即时生效；按监听环境绑定账号路由出站消息。
- 新增 `docs/CONNECTIONS.md` 各方案能力矩阵与接入步骤。

### 声明式插件模型

- `plugin.json` 新增 `features`（功能分组）：命令/定时任务/监听器全声明式注册，handler 为包内点分符号，加载期自动校验；命令新增 `usage` / `examples` 字段。
- 插件任务登记表 `PluginTaskRegistry`：manifest 任务自动登记，Web 任务页只读展示 + 启停（即时生效并持久化），执行前按目标环境功能开关门控。
- system 插件与 template 模板重构为声明式；`ofbot2 plugin new --with-task/--with-listener/--with-web/--with-model`、`plugin features`、`plugin check`、`plugin dev`、`plugin test` 开发工作流。

### Web 与账户

- 移除 `/users` 页面与 QQ 用户管理（数据模型保留）；Web 后台账户管理移入「账户」页；仪表盘新增「监听环境」卡。
- 适配器 HTTP 客户端懒加载，降低启动开销。

### 文档与版本

- 新增 `docs/PLUGIN_MANIFEST.md`；dev_guide 增加功能清单声明规范、监听环境、多连接与三角色指南；`API.md` 重新生成。
- 工程化：新增 MIT `LICENSE`、`SECURITY.md`、`CONTRIBUTING.md`、`CODE_OF_CONDUCT.md`；文档统一收纳至 `docs/`（DEVELOPMENT / API / CHRONOCAT / GOALS），Web 内置文档同步更新。

## v3.0.0（2026-08）— 全面成熟化里程碑

本版本合并了 v2.110.0 ~ v2.140.0 的 31 次小版本增量，按主题归并如下。逐条原始记录见 `docs/CHANGELOG_FULL.md`。

### 前端与主题体验

- 受限环境（沙箱 iframe / 应用内浏览器）健壮性：`safeStorage` 安全存储封装（localStorage 失败内存兜底）与 `safeInit` 分块错误隔离，快速跳转 / 快捷键 / 主题持久化 / 适配器轮询不再被单个异常拖垮；`history.replaceState` 异常防护。
- 主题：`<head>` 首帧预应用已保存主题、登录页悬浮主题按钮、子页面菜单高亮（`nav_active`）、静态资源版本号防缓存、暗色样式补齐（环境自检卡 / 表格 hover）。
- canvas 图表随深浅色主题自动重绘（仪表盘命令趋势、监控历史、统计环形图、命令详情按日/按小时），暗色下不再失去对比度。

### Web 后台与页面体验

- 错误反馈修复（不再静默失败）：账户页密码修改原因展示、插件加载失败具体原因、禁用任务「立即运行/重试」明确提示、告警页错误提示条、`/api-keys` 未登录正确跳转登录页。
- 一键操作：告警规则「测试通知」、Webhook 历史「重放」、文件中心「批量下载」、Web 插件 zip 安装表单。
- 配置页深化：新增安全/日志/调度/限流等 18+ 可编辑字段（即时/需重启标注）、命令参数分隔符 `command_sep`（如 `/ping.x`）接线并即时生效。

### 代码结构拆分（可维护性）

- 路由按域拆分为 21 个单一职责模块（core / auth / stats / config_pages / docs_pages / data / users / tasks / plugins / connections / exports / files / backups / webhooks / alerts / monitoring / audit_ops / executions_ops / ai_workflow / api 等），全部页面路由 ≤ 20KB。
- `helpers.py` 导出任务编排拆至 `export_jobs.py`；设置持久化助手归位 `services/records.py` / `services/alerts.py`；任务执行 Web/调度器双路径去重统一。

### 运维与自愈

- 自愈中心：自动停用/恢复事件聚合、恢复率、「停用-恢复」周期统计与平均停用时长；自动停用/恢复闭环（任务与流程对称）。
- 执行历史统一视图（任务 + 流程合并、自动停用标识、失败重试）；环境自检深化（磁盘空间、插件目录、插件依赖可见性）。

### 安全

- 登录失败锁定（阈值/时长/延迟可配）与 `web.login_locked` 审计；审计日志按保留期自动清理。
- 插件生态加固：插件名路径穿越修复（`validate_plugin_name`）、安装期清单校验（api_version/version/dependencies）、加载错误可见、插件状态持久化（`PluginState`）。

### REST API

- `/api/v1/records` 与 `/api/v1/tasks` 分页契约：`limit`（1-500）/ `offset` + `total` 元数据；records 支持 `record_type` / `status` 过滤；`API.md` 自动生成（151 路径 / 164 端点）。

### 内置功能与文档

- 内置命令：`/about`（版本与能力清单）、`/status` 深化（版本/插件/任务/适配器）；`ofbot2 version` CLI。
- 文档校准：dev_guide（CLI 速查 / 插件生命周期 / 能力清单 / 前端约定）、README 目录结构同步、FAQ 修正。

### 版本与工程化

- 版本号单一来源：`app/__init__.py::__version__` + `scripts/sync_version.py` 一键同步 + `ofbot2 version`；FastAPI 与静态资源版本派生。
- 测试基建加固（Windows 文件锁清理）、114 项测试全绿、`scripts/dev.ps1` 完整门禁（compile / ruff / pytest / e2e）。

## v2.x — 早期里程碑（v2.0.0 ~ v2.109.0）

> 完整逐条记录已归档至 `docs/CHANGELOG_FULL.md`，此处仅保留阶段摘要。

- **v2.109 ~ v2.101 · 运维闭环**：自愈中心、任务/流程连续失败自动停用与冷却恢复、自动停用/恢复通知告警、告警去抖（全局 + 按规则）、执行历史自动停用标识、自愈阈值在线配置。
- **v2.100 ~ v2.90 · 模块互联与文档**：环境自检（Python/数据库/适配器/近 24h 失败执行）、仪表盘失败入口、FAQ 与 API 文档同步。
- **v2.89 ~ v2.0 · 平台建设**：Red / OneBot 适配器与统一消息模型、包式插件体系与配置 Schema 表单、流程引擎（可视化编辑/触发器/动作）、通用记录/状态机/聚合组件、AI 多 Provider（OpenAI 兼容 / Anthropic / Gemini / Ollama）、Web 后台（侧边栏/搜索/Toast/快捷键/徽章体系）、导出（CSV/JSON/Excel/DOCX）、备份与恢复、监控图表、群白名单与权限。

## 归档说明

- 完整逐条变更记录（141 个历史小版本）：[CHANGELOG_FULL.md](CHANGELOG_FULL.md)
