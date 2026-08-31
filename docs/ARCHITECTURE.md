# 架构说明

OFbot 2 采用四层架构，职责清晰、可独立演进：

```mermaid
flowchart TB
    subgraph WEB[Web 后台 app/web]
        W1[FastAPI + Jinja2 + 原生 JS]
        W2[仪表盘/配置/插件/连接/监听环境/任务/流程/审计]
    end
    subgraph CORE[核心层 app/core]
        C1[配置 · 日志 · 事件总线]
        C2[命令路由 · 作用域策略 · 权限 · 限流]
        C3[调度器 · 插件管理 · 缓存 · 安全]
    end
    subgraph DATA[数据层 app/db + app/services]
        D1[SQLAlchemy 异步模型 · 迁移]
        D2[记录/状态机/聚合 · AI · 流程]
        D3[Webhook · 告警 · 导出 · 文件 · 备份]
    end
    subgraph ADAPTER[协议层 app/adapters]
        A1[ConnectionManager]
        A2[OneBot v11/v12 · Red · Satori · Mirai · QQ 官方]
        A3[统一 BotEvent / MessageSegment]
    end
    ADAPTER --> CORE --> DATA
    CORE --> WEB
    WEB --> CORE
```

## 消息流

```mermaid
sequenceDiagram
    participant P as 协议端（NapCat/Chronocat）
    participant A as 适配器（ConnectionManager）
    participant B as BotClient
    participant E as 事件总线
    participant R as CommandRegistry
    participant H as 插件 Handler
    P->>A: 原始事件/消息
    A->>B: BotEvent + MessageSegment（归一化）
    B->>E: 群白名单过滤后广播
    E->>R: 派发消息事件
    R->>R: 解析 → 黑名单 → 文本校验 → 功能开关 → 冷却/限流 → 权限
    R->>H: 执行 handler
    H-->>R: event.reply
    R-->>A: 按环境账号绑定路由出站
    A-->>P: 协议端发送
```

## 监听环境与作用域

每条消息都会推导出所在环境：群消息 → `group:<id>`，私聊 → `private:*`（单一私聊环境）。`ScopePolicyService` 按环境裁决：

- 功能开关优先级：`group:<id>` 覆盖 > `group:*` 覆盖 > `enable_on_default`；私聊只看 `private:*`。
- 权限：环境的 `permissions[perm]` 存在则覆盖全局权限。
- 黑名单：环境 `blocked_users` 叠加全局 `security.blocked_users`。
- 出站路由：环境 `connection` 绑定连接 ID，未绑定走第一个已连接适配器。

所有配置存于 `config.yaml` 的 `runtime.scopes`，Web / CLI 修改后即时同步内存策略。

## 插件生命周期

```text
PluginManager.discover() → 解析 plugin.json（api_version / name / dependencies）
  → 依赖拓扑排序 → load_plugin：
      执行模块 → create_plugin() → setup(ctx)
      → 按 features 自动注册命令 / 登记任务 / 包装监听器（handler 符号校验）
  → start_plugin()（异步启动）
  → unload_plugin()：停止实例、清理命令/订阅/调度任务/Web 路由引用
```

- 插件只能通过 `PluginContext` 访问框架能力，禁止直接依赖全局单例。
- 插件模型表结构不支持热更新：改 `models.py` 后需重启执行 `create_all` / 迁移。
- 插件启停为声明式优先；运行时 `ctx.commands` / `ctx.subscribe` / `ctx.scheduler` 作为动态逃生通道（不入功能矩阵）。

## 多连接与账号绑定

`transport.connections` 是连接配置的唯一来源，`ConnectionManager` 统一管理适配器生命周期（连接/重连/启停/状态），单连接故障不影响其他。每个连接有独立 `bot_id` 与事件命名空间；出站消息按监听环境绑定的连接路由，入站事件天然来自实际收到消息的连接。

## 调度与任务

- DB 定时任务（`tasks` 表）：唯一事实来源，启动时恢复 `enabled=True` 的任务。
- 插件任务（manifest `tasks`）：登记进内存 `PluginTaskRegistry`，网页只读展示 + 启停；执行前按目标环境功能开关门控。
- 后台任务：有界 `asyncio.Queue` + worker pool，导出/备份/媒体下载等重任务不阻塞消息循环。
