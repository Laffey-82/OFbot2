# Changelog

## 未发布 — 文档与 GitHub 仓库专业化

- README 重构：徽章行、界面截图（登录/仪表盘/连接中心/监听环境/插件市场/流程）、
  mermaid 架构图、TOC、安全提示与贡献/License 区块。
- 新增文档中枢 [docs/README.md](README.md)、[docs/GLOSSARY.md](GLOSSARY.md) 与
  [docs/MAINTAINERS.md](MAINTAINERS.md)；ARCHITECTURE/FAQ/SECURITY 增强。
- 英文关键页：Overview 重写 + QuickStart / Install / Connections（中英互链）。
- 贡献指南、Issue/PR 模板增强；PR 按路径自动打标签（labeler）。
- CI 新增 `docs-check`：校验文档链接、锚点与截图资产（`scripts/check_docs_links.py`）。
- 仓库元数据与标签由 `scripts/repo_setup.py` 一键应用（description/topics/homepage/标签）。

## v1.3.0（2026-09）— 插件子进程沙箱

- `plugin.json` 新增 `sandbox: "inline" | "process"`（默认 inline）与
  `sandbox_policy.allow_services` 能力白名单。
- process 模式：插件在独立子进程加载执行，命令/任务/监听仍按声明式注册，
  能力访问经 JSON-RPC 代理并受白名单约束（`files/export/backup/webhook/ai`
  默认拒绝）；子进程崩溃不影响主进程。
- 限制：process 插件不支持 `models` 与运行时 `ctx.subscribe`（文档已同步）。

## v1.2.0（2026-09）— 插件审计加固 + Web E2E

- 插件安装审计扩展：文件系统变更扫描（`os.remove/shutil.move` 等）、
  `ctypes/os.popen/pty.spawn/marshal` 等高危执行模式、依赖白名单（未知第三方库告警）、
  `low/medium/high` 风险分级；`plugin check` 对已安装插件执行同源目录级静态扫描。
- 新增 Playwright 浏览器端 E2E（`tests/e2e`）：登录 → 仪表盘 → 连接中心 →
  监听环境 → 插件 → 任务 → 流程，默认被 `-m "not e2e"` 跳过，CI 独立 job 运行。

## v1.1.0（2026-09）— 自研事件总线替换 bubus

- 用轻量异步 pub/sub 替换 bubus：`isinstance` 类型匹配（父类订阅兼容）、
  每 handler 独立任务、异常隔离、`stop(timeout)` 优雅排空 + 超时取消。
- 移除 `arm_hard_exit()` 与 `os._exit` 强制退出兜底；bubus 依赖从 requirements/pyproject 移除。
- `BaseEvent` 改为继承 pydantic `BaseModel`，插件与订阅代码零改动。
- 新增高负载测试：数千事件 + 慢 handler 下关闭不阻塞、任务不泄漏。

## v1.0.8（2026-09）— 稳定与运维卫生

- 数据库引擎/事件总线重置显式释放：`reset_db_engine()` 异步 `dispose()`、
  `reset_bus()` 先停旧实例再重建，消除 GC 连接警告与 bubus 同名告警（测试警告清零）。
- 修复真实连接泄漏：`/tasks` 与 `/stats` 页面在 `async with` 块外使用 session，
  每次访问泄漏一条数据库连接（SQLAlchemy 池耗尽风险）。
- 日志轮转清理覆盖 `ofbot2-*.log*` 轮转后缀与历史遗留格式
  （`bot*.log*`、`web-*.log*`、`diag_fh.log*`），文件日志默认级别 DEBUG → INFO。
- `transport.connections` 收敛为唯一事实来源：保存配置时不再写回旧 `red/onebot`
  播种键，`config.example.yaml` 同步更新。
- 新增 `docs/ROADMAP.md`，GOALS 测试数更新为 271。

## v1.0.7（2026-08）— 审查修复（API 鉴权收紧 / 事件入口校验）

- `/api/v1/*` 默认不再裸奔：未配置 `web.api_keys` 时改为要求后台管理员登录会话；配置后维持 `X-API-Key` 鉴权（恒定时间比较）。
- 反向 HTTP 事件入口（`/onebot/v11/http`、`/onebot/v12/http`）与反向 WS 一致，配置 `access_token` 时校验 `Authorization: Bearer`。
- Webhook 接收端点新增可选共享密钥 `web.webhook_secret`：配置后 `POST /webhook/{name}` 需携带 `X-Webhook-Secret` 请求头（恒定时间比较）。
- 配置页新增「Webhook 共享密钥」项；FAQ 公网部署建议同步更新。

## v1.0.6（2026-08）— 审查修复（测试隔离 / 导出 404 / 死配置清理）

- 修复 `test_patch_103/104/105` 的 Web 流程测试未隔离 `config_path`：运行测试会改写工作区真实 `config.yaml`（数据库指向已删除的临时目录），现在统一写入临时目录。
- `/exports/{name}/download` 对非法/逃逸路径返回 404 而非 500。
- 移除未使用的 `web.secret` 配置项，FAQ 公网部署建议改为强调配置 `web.api_keys`。
- Web 绑定非本机地址且未配置 API Key 时输出启动告警。
- 本地 `config.yaml` 恢复 `data/ofbot2.db` 并清理测试残留（该文件不入库）。

## v1.0.5（2026-08）— 工程与文档收尾

- 测试补齐：roles 路由 Web 流程、`plugin_state` 读写、`capability_setup` 内置能力注册、`example_ai` 声明式加载。
- `scripts/benchmark.py` 接入 CI（仅输出报告，不设硬性门槛）。
- `docs/API.md` 重新生成，路径数对齐实际（171 路径 / 184 操作）。
- `scripts/dev.ps1` 门禁与 CI 对齐（compileall/ruff 纳入 `ofbot2` 包）。
- `docs/PRESETS.md` 重写：明确 15 个示例已转正为官方插件，examples 仅作脚手架。
- `plugins/example_ai` 改写为声明式（features + handlers.py），保持 `/ask` 行为。

## v1.0.4（2026-08）— 适配器与 Web 边界

- 反向 WS 热更新生效：WebSocket 路由改为动态查找当前适配器 handler，连接热重载后新连接可用。
- QQ 官方机器人心跳任务纳入管理：单任务、重复 hello 取消旧任务、断线/停止时取消（修复 `heartbeat_task` 未使用与任务泄漏）。
- OneBot v11 收包 CQ 转义解码（`&#91;/&#93;/&#44;/&amp;`）。
- Mirai At 目标非数字时回退 0，不再抛错。
- `/files` 路径穿越返回 404；`files_preview` 不再向客户端回显异常详情。
- 登录失败状态内存设上限（10k，超限淘汰最早项）。
- 监听环境群号格式校验（数字 1-20 位）与数量上限（1000）。
- 批量下载 zip 归档名消毒，防 zip-slip。

## v1.0.3（2026-08）— 定时任务与 Web 一致性

- 定时流程「自动停用」生效：`WorkflowEngine.execute()` 增加 `enabled` 检查，禁用时运行记录标记 `skipped`，不再继续执行。
- Web 新建「定时」流程时注册 cron 调度任务（此前需重启）；「重新启用」流程时同步恢复 cron；删除时移除任务。
- 配置页保存时重建运行中的 `SecurityPolicy`，敏感词/消息长度/限流默认值保存后即时生效。

## v1.0.2（2026-08）— 解析与命令健壮性

- 参数分词保留反斜杠（Windows 路径不再被吞），引号分组语义不变，未闭合引号降级与旧行为一致。
- 子命令支持点分 token（`/order.add.info` → 子命令 `add` + 参数 `info`）。
- 命令冲突检测：加载时命令名/别名被其他插件占用即 `PluginFailed` 并给出冲突插件名；`plugin check` 增加跨插件冲突检查。
- help 长消息改用 `split_message` 分片（换行感知）。
- 框架回复兜底 `_safe_reply`：`event.reply` 未绑定/未实现时记录警告而非抛 TypeError。

## v1.0.1（2026-08）— 安全与关闭健壮性

- 事件总线关闭兜底：bubus `stop()` 在高 pending 事件时可能同步阻塞事件循环（asyncio 超时无效），新增独立线程定时器强制退出，保证进程必然结束。
- 备份路径校验改用 `is_relative_to`，修复前缀混淆路径穿越（可误删备份目录外兄弟目录）。
- 导出文件名对记录类型消毒（防路径穿越）；记录类型名/字段名禁止 `/ \ ..` 与空名。
- API Key 校验改为恒定时间比较（`hmac.compare_digest`）。
- 移除无鉴权且无引用的 `/docs/{name}` 明文端点（保留需登录的 `/docs/index` 与 `/docs/view/*`）。
- 密码哈希迭代 200k → 600k（OWASP 建议），存量哈希登录成功时惰性升级重存。
- 会话 Cookie 新增 `cookie_secure` 配置项（默认 False，兼容本地 HTTP）。

## v1.0.0（2026-08）— 首个正式发布

首个公开发行版本：版本号重整（3.x 阶段归入预发布演进），支持 `pip install ofbot2` 与 `python -m ofbot2`，仓库公开、CI 全绿、i18n 覆盖全部后台页面、15 个示例插件转正为官方插件。

核心能力一览：

- 多协议多账号并存：OneBot v11/v12、Red、Satori、Mirai、QQ 官方机器人，连接独立启停、按群绑定账号路由出站。
- 监听环境作用域：逐群/私聊三态功能开关、权限覆盖、黑名单、静默模式，与群内 `/功能启用|禁用` 命令同源生效。
- 声明式插件模型：`plugin.json` 声明 features / commands / rules / session / tasks / listeners，handler 点分符号加载期校验，配套 `plugin check / dev / test` 工作流。
- 通用能力组件：记录中心、状态机、聚合、导出、审计、文件、备份；Agent 工具循环与流程引擎可组合业务。
- 一体化 Web 后台：22 个管理域（连接 / 作用域 / 角色 / 插件 / 插件市场 / 流程 / AI / 任务 / 审计 / 备份…），服务端渲染 + 原生 JS。
- 可观测与安全：trace_id 链路贯穿、Prometheus 指标、审计日志、告警模板、登录锁定与 CSRF、命令三级限流、插件安装安全审计（静态检查 + SHA-256 校验）。
- 插件生态：官方插件 25 个（含本版本由示例转正的 15 个），插件市场支持 URL / 本地双数据源。

3.x 阶段（v3.0.0–v3.6.0）为预发布演进，详细条目已归档至 `docs/archive/CHANGELOG_v3.md`。

## 历史归档

- v3 预发布演进（v3.0.0–v3.6.0）：[archive/CHANGELOG_v3.md](archive/CHANGELOG_v3.md)
- v2 早期历史（v2.0.0–v2.140.0）：[archive/CHANGELOG_v2.md](archive/CHANGELOG_v2.md)

