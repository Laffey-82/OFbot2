# Changelog

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

