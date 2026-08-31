# 插件清单（plugin.json）参考

包式插件的 `plugin.json` 是插件的唯一事实来源：命令、定时任务、监听器、功能分组、配置 schema 全部在此声明。框架加载插件时自动注册并校验，无需在代码里重复装饰。

## 字段总览

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `name` | string | 是 | 与插件目录名一致 |
| `api_version` | int | 是 | 当前为 `1` |
| `version` | string | 是 | SemVer |
| `description` / `author` | string | 否 | 展示信息 |
| `dependencies` | object | 否 | 依赖插件及版本范围 |
| `sandbox` | string | 否 | 运行模式：`inline`（默认，进程内）或 `process`（子进程隔离） |
| `sandbox_policy` | object | 否 | 沙箱能力白名单，见「沙箱模式（sandbox）」 |
| `permissions` | string[] | 否 | 插件声明/消费的权限点 |
| `permission_roles` | object | 否 | 权限点 → 角色数组；声明后该权限只授予指定角色（默认授予 user） |
| `conflicts` | object | 否 | 命令冲突覆盖：`{"命令名": "rename" | "skip"}` |
| `config_schema` | object | 否 | JSON Schema，Web 自动生成配置表单 |
| `web` | bool | 否 | 是否注册 Web 路由 |
| `models` | string[] | 否 | 插件模型模块（启动前建表） |
| `migrations` | string[] | 否 | 迁移脚本路径 |
| `entry` | string | 否 | 入口函数名，默认 `create_plugin` |
| `features` | object[] | 否 | 功能分组（见下） |
| `commands` / `tasks` / `listeners` | object[] | 否 | 顶层声明，无 `features` 时回落 `<plugin>.default` |

## 沙箱模式（sandbox）

`sandbox` 默认 `inline`：插件在机器人进程内加载，适合官方/可信插件。
设置为 `process` 时，插件在**独立子进程**中加载执行，通过 JSON-RPC 与主进程通信：

- 命令、定时任务、监听器仍按 features 声明式注册，handler 由主进程代理到子进程执行；
- 插件内对框架能力的访问（如 `ctx.records`、`ctx.ai`）反向 RPC 到主进程执行；
- `sandbox_policy.allow_services` 白名单之外的敏感能力（`files` / `export` /
  `backup` / `webhook` / `ai`）会被直接拒绝，插件侧收到 `PermissionError`。

```json
{
  "name": "my_plugin",
  "api_version": 1,
  "sandbox": "process",
  "sandbox_policy": {
    "allow_services": ["records", "state_machine", "audit"]
  },
  "features": []
}
```

限制：
- `process` 插件不支持 `models`（无法注册 SQLAlchemy 模型）与运行时 `ctx.subscribe`；
- 子进程崩溃不影响主进程，但插件数据会随子进程重启丢失，请通过框架能力读写；
- 文件系统/网络仍以操作系统权限为界，严格隔离请配合容器/系统级沙箱部署。

## features（功能分组）

```json
{
  "id": "roll",
  "label": "掷骰子",
  "description": "随机点数",
  "enable_on_default": true,
  "manage_permission": "dice.admin",
  "commands": [ ... ],
  "tasks": [ ... ],
  "listeners": [ ... ]
}
```

- 每个功能在「监听环境」页可被逐群/私聊独立开关（三态：开启 / 关闭 / 跟随默认）。
- 命令、任务、监听器**唯一归属一个功能**；未声明的回落 `<plugin>.default`。
- 功能未开启时：命令被静默/友好提示拦截（按环境配置），任务与监听器不执行，帮助列表不展示。

### commands

| 字段 | 说明 |
| --- | --- |
| `name` | 命令名（不含前缀） |
| `aliases` | 别名数组 |
| `handler` | 包内点分符号路径，如 `handlers.roll_command` |
| `permission` | 权限点 |
| `description` | 帮助展示说明 |
| `usage` | 用法示例文案 |
| `examples` | 示例数组，帮助详情展示 |
| `params` | 参数声明数组（见下），框架自动解析与校验 |
| `subcommands` | 子命令声明数组（见下），支持分段命令 |
| `cooldown` / `rate_limit` | 冷却秒数 / 限流规格 |
| `priority` / `block` | 优先级 / 命中后是否阻断其他处理器 |
| `max_arg_length` | int | 命令参数长度上限（默认继承全局 `security.max_arg_length`） |

#### params（参数声明）

```json
{
  "name": "count",
  "type": "int",              // string | int | float | bool
  "required": false,
  "default": 1,
  "description": "重复次数",
  "choices": ["a", "b"]
}
```

- 支持位置参数与 `key=value` 命名参数；值可用引号包裹含空格的字符串。
- `type: "rest"`（别名 `greedy_string`）：位置模式下吞掉剩余全部参数合并为一个字符串，
  必须位于参数列表末尾。
- 类型转换失败、缺少必填参数、多余参数或超出 `choices` 时，框架自动回复「参数错误 + 用法」。
- 未提供 `usage` 时，用法由声明自动生成（如 `/greet world [count=1]`）。

#### subcommands（子命令 / 分段命令）

```json
{
  "name": "hello",
  "aliases": ["你好"],
  "description": "中文问候",
  "params": [ ... ]
}
```

- 声明子命令后，第一段参数作为子命令名匹配（支持别名），其余参数绑定到该子命令的 `params`。
- 未知子命令或缺失子命令时自动回复可用列表与用法。
- 处理器通过 `command_ctx.subcommand` 与 `command_ctx.params` 读取解析结果。

### tasks

| 字段 | 说明 |
| --- | --- |
| `id` | 任务 ID（插件内唯一） |
| `kind` | `interval` / `cron` / `date` |
| `params` | 参数：interval 用 `seconds`，cron 用 `cron`（crontab 表达式），date 用 `run_date` |
| `handler` | 处理器符号路径，`async def handler()` |
| `target` | `all` / `group:<id>` / `private:*`，或上述的列表；决定按哪些环境的功能开关门控 |
| `description` | 展示说明 |

- `params` 中的字符串值支持配置模板：`"cron": "${tasks.daily_commission.cron}"`
  会在注册时从插件配置（`plugin_configs.<name>`）按点分路径取值，缺失回退静态值。
- 运行时注册的任务可用 `ctx.register_managed_task(...)` 进入 Web「定时任务」页。

## 指令冲突解决

- 加载期不再因命令名/别名与其他插件冲突而失败；解决策略：
  先加载者（依赖拓扑 + 字母序）保留原名，后加载插件的冲突主命令自动注册为
  `<插件名>.<命令>`（如 `order_ledger.分账`），冲突别名丢弃并告警；`system` 插件命令保留。
- 插件可用 `conflicts` 显式覆盖：`"rename"` 强制命名空间化，`"skip"` 不注册该命令。
- `plugin check <name>` 会预览解决结果；`plugin conflicts` 全量扫描并列出策略；
  Web「插件」页显示冲突徽标，`GET /api/v1/plugins/conflicts` 返回详情。

任务注册进内存登记表，Web「定时任务」页只读展示并支持启停；启停状态持久化到 `runtime.plugin_tasks`。

### listeners

| 字段 | 说明 |
| --- | --- |
| `event` | `app.core.events` 中的事件类名，如 `GroupMessageReceived` |
| `handler` | 处理器符号路径，`async def handler(event)` |
| `description` | 展示说明 |

监听器执行前按事件所在环境（群消息 → `group:<id>`，私聊 → `private:*`）检查功能开关，关闭则跳过。

## 常见校验错误

| 错误 | 原因与修复 |
| --- | --- |
| `handler 符号 xxx 不存在于插件包中` | `handler` 路径写错，或 `__init__.py` 未 `from . import handlers` |
| `handler 符号 xxx 不是可调用对象` | 指向了非函数对象，检查拼写 |
| `listener 事件 xxx 不存在于 app.core.events` | 事件名不在事件模块中，检查拼写 |
| `plugin directory x does not match manifest name y` | 目录名与 `name` 不一致 |
| `incompatible plugin api version` | `api_version` 不是 `1` |
| `plugin dependency cycle detected` | 依赖形成环，调整 `dependencies` |

使用 `ofbot2 plugin check <name>` 静态校验；`ofbot2 plugin features <name>` 查看功能清单。
