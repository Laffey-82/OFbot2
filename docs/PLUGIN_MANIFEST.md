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
| `permissions` | string[] | 否 | 插件声明/消费的权限点 |
| `config_schema` | object | 否 | JSON Schema，Web 自动生成配置表单 |
| `web` | bool | 否 | 是否注册 Web 路由 |
| `models` | string[] | 否 | 插件模型模块（启动前建表） |
| `migrations` | string[] | 否 | 迁移脚本路径 |
| `entry` | string | 否 | 入口函数名，默认 `create_plugin` |
| `features` | object[] | 否 | 功能分组（见下） |
| `commands` / `tasks` / `listeners` | object[] | 否 | 顶层声明，无 `features` 时回落 `<plugin>.default` |

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
| `cooldown` / `rate_limit` | 冷却秒数 / 限流规格 |
| `priority` / `block` | 优先级 / 命中后是否阻断其他处理器 |

### tasks

| 字段 | 说明 |
| --- | --- |
| `id` | 任务 ID（插件内唯一） |
| `kind` | `interval` / `cron` / `date` |
| `params` | 参数：interval 用 `seconds`，cron 用 `cron`（crontab 表达式），date 用 `run_date` |
| `handler` | 处理器符号路径，`async def handler()` |
| `target` | `all` / `group:<id>` / `private:*`，决定按哪些环境的功能开关门控 |
| `description` | 展示说明 |

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
