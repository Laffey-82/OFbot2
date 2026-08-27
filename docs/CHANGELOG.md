# Changelog

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

- v3 预发布演进（v3.0.0–v3.6.0）：[docs/archive/CHANGELOG_v3.md](docs/archive/CHANGELOG_v3.md)
- v2 早期历史（v2.0.0–v2.140.0）：[docs/archive/CHANGELOG_v2.md](docs/archive/CHANGELOG_v2.md)

