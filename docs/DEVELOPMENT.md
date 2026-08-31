# OFbot 2 开发指南

## 核心约定

- 插件只能通过 `PluginContext` 访问框架能力，不要直接依赖全局单例。
- 包式插件目录名、`plugin.json` 中 `name`、Python 模块名三者一致。
- 插件的模型注册应在 `setup()` 内调用 `ctx.register_models(...)`；迁移脚本通过 `ctx.register_migrations(...)` 注册。
- 命令处理器应使用 `async def handler(event, args, command_ctx)` 签名。
- 所有耗时的操作（导出、AI、下载）应放入后台任务或流程动作，避免阻塞消息循环。

## plugin.json

```json
{
  "name": "my_plugin",
  "api_version": 1,
  "version": "1.0.0",
  "description": "示例插件",
  "author": "me",
  "dependencies": {},
  "permissions": ["my_plugin.ping"],
  "config_schema": {
    "type": "object",
    "properties": {
      "greeting": {"type": "string", "default": "hello"}
    }
  },
  "web": false,
  "models": [],
  "migrations": [],
  "entry": "create_plugin"
}
```

`config_schema` 使用 JSON Schema，配置会经过强类型校验，Web 后台可据此自动生成表单。

## 最小插件

```python
from app.core.plugin import Plugin, PluginContext


class MyPlugin(Plugin):
    def setup(self, ctx: PluginContext) -> None:
        ctx.logger.info("my_plugin setup")

    async def start(self) -> None:
        ctx.logger.info("my_plugin started")

    async def stop(self) -> None:
        ctx.logger.info("my_plugin stopped")


def create_plugin() -> Plugin:
    return MyPlugin()
```

## 注册命令

```python
from app.core.commands import CommandContext
from app.core.events import GroupMessageReceived


@ctx.commands.command(
    "ping",
    aliases={"p"},
    permission="my_plugin.ping",
    priority=10,
    block=True,
    cooldown=5,
    rate_limit="10/minute",
    description="连通性测试，返回 pong",
)
async def ping(event: GroupMessageReceived, args, command_ctx: CommandContext) -> None:
    await event.reply("pong")
```

命令支持参数解析、权限要求、冷却、限流、优先级与说明。`description` 会展示在 Web 后台「命令速查」页（`/commands`），建议每个命令都填写。`event.reply()` 自动回复到当前会话。

## 订阅事件

```python
from app.core.events import MemberJoined


async def on_member_joined(event: MemberJoined) -> None:
    await ctx.send_group(str(event.group_id), f"欢迎 {event.user_id} 入群！")


ctx.subscribe(MemberJoined, on_member_joined)
```

核心事件：`GroupMessageReceived`、`PrivateMessageReceived`、`MemberJoined`、`MessageRecalled`、`PluginLoaded`、`TaskCompleted` 等，完整列表见 `app/core/events.py`。

插件也可主动派发事件，供其他插件订阅联动：

```python
from app.core.events import BotConnected

ctx.dispatch(BotConnected(bot_id="self_1", detail={"note": "来自插件"})
```

## 通用记录（records）

框架不内置业务表，插件注册“记录类型”即可获得通用 CRUD：

```python
from app.services.records import FieldSchema, RecordTypeSchema


ctx.records.schemas.register(
    RecordTypeSchema(
        "order",
        [
            FieldSchema("title", "string", required=True),
            FieldSchema("amount", "number", default=0),
            FieldSchema("status", "string", default="pending"),
        ],
    )
)

# 创建
record = await ctx.records.create("order", {"title": "测试单", "amount": 99.5})
# 查询
item = await ctx.records.get(record.id)
items = await ctx.records.list(record_type="order", limit=50)
# 更新 / 删除
await ctx.records.update(record.id, {"status": "done"})
await ctx.records.delete(record.id)
```

记录变更（创建/更新/删除/状态流转）会通过事件总线广播，其他插件可订阅联动。

## 状态机（state_machine）

```python
from app.services.state_machine import StateMachine, Transition


machine = StateMachine("order_status", initial="pending")
machine.add(Transition("pending", "paid"))
machine.add(Transition("paid", "shipped", permission="staff.ship"))
machine.add(Transition("shipped", "done"))
ctx.state_machine.register(machine)

# 流转（非法流转抛出 ValueError）
new_status = ctx.state_machine.transition(
    "order_status", "pending", "paid", context={"record_id": record.id}
)
```

流转前后回调（`Transition.before/after`）、权限要求、事件广播均已内置。

## 聚合（aggregation）

```python
items = [r.data for r in await ctx.records.list(record_type="order")]

by_status = ctx.aggregation.group_by(items, "status")
total_amount = ctx.aggregation.sum(items, "amount")
average_amount = ctx.aggregation.avg(items, "amount")
today_items = ctx.aggregation.filter_by_date(items, "created_at", start, end)
```

排行、统计、报表都可由此组合实现。

## AI 调用

```python
# 聊天
answer = await ctx.ai.chat(
    [{"role": "user", "content": "用一句话介绍 OFbot 2"}],
    provider="openai",  # 可选，默认使用 active provider
)

# 嵌入向量
vectors = await ctx.ai.embeddings(["文本1", "文本2"])

# 图片生成、语音、OCR
image_path = await ctx.ai.image("一只猫")
text = await ctx.ai.ocr(image_bytes)
audio = await ctx.ai.text_to_speech("你好")
```

未配置 API Key 时自动降级到 Mock Provider，返回友好提示，不影响框架运行。

## 流程引擎（workflow）

```python
# 插件注册自定义动作
async def send_group_action(context, *, group_id, text):
    await ctx.send_group(str(group_id), text)
    return {"sent": True}


ctx.workflow.register_action("send_group", send_group_action)

# 通过 Web 或 API 创建流程：
# {"name": "定时播报", "trigger": {"type": "schedule"}, "steps": [{"action": "send_group", "params": {"group_id": "123", "text": "早安"}}]}
```

内置动作：`echo`、`send_group`、`ai_chat`。触发器支持 `schedule`、`message`、`webhook`，插件可扩展自定义 Trigger/Action。

## 审计

```python
await ctx.audit.record(
    "my_plugin.action",
    "user_qq_12345",
    target="order:1",
    success=True,
    detail={"amount": 99.5},
)
```

所有记录变更、状态流转、导出、AI 调用均会写入审计，可在 Web“审计日志”页查看。

## Web 路由

```python
from fastapi import APIRouter, Request


router = APIRouter(prefix="/my-plugin")


@router.get("/hello")
async def hello(request: Request):
    return {"message": "hello from my_plugin"}


ctx.register_router(router)
```

插件路由随插件加载/卸载自动挂载与清理。

## 后台任务与定时任务

```python
import asyncio


# 注册后台常驻任务（随插件启动）
async def my_worker() -> None:
    while True:
        await asyncio.sleep(60)
        ctx.logger.info("worker tick")


ctx.register_task(my_worker)

# 注册 APScheduler 定时任务
ctx.scheduler.add_interval_job(
    my_worker,
    job_id="my_plugin.tick",
    seconds=60,
)

# 一次性延迟任务（delay 秒后执行）
ctx.schedule_once(30, my_worker)
```

## 插件 Webhook

```python
# 复用框架 WebhookService：插件可声明自己的 Webhook 入口（运行时生效）
ctx.register_webhook("my_plugin.hook", {"event": "deploy"})
```

注册后通过 `POST /webhook/my_plugin.hook` 触发，载荷匹配过滤器时会广播 `WebhookReceived` 事件。

## 从示例生成插件

```powershell
py -m app.cli plugin new myplugin --preset dice
py -m app.cli plugin list
py -m app.cli plugin reload myplugin
```

示例源码位于 `examples/plugins/presets/`，每个示例都是可直接运行的插件，覆盖命令、事件、模型、定时任务、Web 路由等能力。

## CLI 命令速查

```text
ofbot2 run [--config PATH]         # 启动机器人（默认 main.py 等价）
ofbot2 doctor                      # 环境自检（与 Web 设置向导共用检查项）
ofbot2 status                      # 运行状态概览
ofbot2 logs [--tail N]             # 查看最近 N 行日志（默认 50）
ofbot2 backup                      # 立即创建备份
ofbot2 version                     # 显示框架版本
ofbot2 plugin new <name> [--preset] [--with-task] [--with-listener] [--with-web] [--with-model]
                                 # 生成声明式插件（可附带任务/监听/Web/模型示例）
ofbot2 plugin features <name>      # 查看插件功能清单（命令/任务/监听）
ofbot2 plugin check <name>         # 静态校验清单、handler 符号与依赖
ofbot2 plugin dev <name>           # 开发模式：文件变更自动重载
ofbot2 plugin test <name>          # 运行插件自带 tests/ 测试
ofbot2 plugin install <zip>        # 安装打包插件（zip 属于代码执行，确认来源可信）
ofbot2 plugin list                 # 列出已安装插件
ofbot2 plugin reload <name>        # 重载插件
ofbot2 plugin unload <name>        # 卸载插件
ofbot2 connections list            # 列出连接
ofbot2 connections add <id> [--protocol onebot] [--mode reverse_ws] ...
ofbot2 connections test <id>       # 测试连接
ofbot2 scopes list                 # 列出监听环境与功能开关
ofbot2 scopes set <plugin.feature> on|off|default [--scope group:123]
ofbot2 capabilities                # 列出框架能力
ofbot2 workflow list               # 列出流程
ofbot2 workflow run <id>           # 立即运行流程
```

## 插件生命周期与热更新

- 插件状态：`disabled / loaded / error / unloaded`。安装后默认禁用，需在 Web「插件」页或 `plugin list` 后启用。
- `reload` / `unload` 会清理该插件的命令、事件订阅、定时任务与 Web 路由引用；`PluginLoaded / PluginUnloaded / PluginReloaded / PluginFailed` 事件会广播，其他插件可订阅联动。
- **模型表结构不支持热更新**：插件注册了新模型或改动 `models.py` 后，必须重启服务（`create_all` 建表）并按需执行迁移。
- **process 沙箱模式**：`plugin.json` 声明 `"sandbox": "process"` 后插件在独立子进程运行，
  命令/任务/监听仍按声明式注册，能力访问经白名单（`sandbox_policy.allow_services`）代理；
  该模式不支持 `models` 与运行时 `ctx.subscribe`，详见 [PLUGIN_MANIFEST.md](PLUGIN_MANIFEST.md)。
- 插件配置通过 `plugin.json` 的 `config_schema` 强类型校验，Web「插件」页可自动生成表单。

## 功能清单声明规范（features）

命令、定时任务与监听器**首选在 `plugin.json` 中声明**（全声明式），加载时自动注册：

```json
{
  "features": [{
    "id": "roll",
    "label": "掷骰子",
    "description": "随机点数",
    "enable_on_default": true,
    "manage_permission": "dice.admin",
    "commands": [{
      "name": "roll",
      "handler": "handlers.roll_command",
      "permission": "user.roll",
      "description": "随机掷 1-100",
      "usage": "/roll [最大点数]",
      "examples": ["/roll", "/roll 6"]
    }],
    "tasks": [{
      "id": "daily_summary", "kind": "cron",
      "params": {"cron": "0 9 * * *"},
      "handler": "handlers.daily_summary",
      "target": "all"
    }],
    "listeners": [{
      "event": "MemberJoined",
      "handler": "handlers.on_join"
    }]
  }]
}
```

- `handler` 为插件包内点分符号（如 `handlers.roll_command`），`__init__.py` 需 `from . import handlers`。
- 无 `features` 时，顶层 `commands` / `tasks` / `listeners` 回落 `<plugin>.default` 功能。
- 每个功能可在「监听环境」页逐群/私聊三态开关；关闭后命令拦截、任务与监听跳过、帮助隐藏。
- 完整字段参考见 [PLUGIN_MANIFEST.md](PLUGIN_MANIFEST.md)；`ofbot2 plugin check <name>` 可在加载前校验。
- 运行时 `ctx.commands.command()` / `ctx.subscribe()` / `ctx.scheduler` 仍可用，作为动态注册逃生通道（不入功能矩阵）。

## 响应规则（rules）

命令与监听器可在 `plugin.json` 中声明规则，框架在作用域门控之后、参数解析/处理器执行之前统一匹配：

```json
{
  "name": "roll",
  "handler": "handlers.roll_command",
  "rules": [
    {"name": "group_only"},
    {"name": "in_group", "params": {"groups": ["123456789"]}}
  ]
}
```

内置规则：

| 规则 | 参数 | 说明 |
|---|---|---|
| `to_me` | — | 私聊或消息包含 @bot |
| `keyword` | `value`（字符串或列表） | 消息文本包含关键词 |
| `regex` | `value` / `pattern` | 消息文本匹配正则 |
| `group_only` | — | 仅群消息 |
| `private_only` | — | 仅私聊消息 |
| `in_group` | `groups`（群号列表） | 群号在白名单内 |

插件可用 `ctx.rules.register("rule_name", checker)` 注册自定义规则，`checker(event, params)` 返回 `bool` 或协程；`ofbot2 plugin check` 会校验声明中未注册的规则。

## 会话上下文（session）

命令声明 `"session": true` 后，处理器通过 `command_ctx.session` 获得以 bot+群+用户 为键的会话对象：

```python
async def delete_command(event, args, command_ctx):
    session = command_ctx.session
    if await session.confirm():
        await event.reply("已确认删除")
        return
    session.state["pending_id"] = args.extract_plain_text()
    await event.reply(await session.ask("确认删除？"))
```

- 插件内可全局使用 `ctx.session`（`SessionManager`）：`get / prune / active_count`。
- 会话默认 TTL 600 秒、上限 1000 个（`runtime.session_ttl_seconds` / `session_max_sessions` 可调），自动淘汰过期与最久未更新会话。

## Agent 工具调用循环

`ctx.services["agent"]`（`AgentRunner`）提供多智能体工具调用：

```python
runner = ctx.services["agent"]
result = await runner.run(
    "查询今天待办并汇总",
    session_id=f"{event.group_id}:{event.user_id}",
    max_rounds=5,
    permission_check=lambda perm: ctx.permissions.has_permission(
        event.user_id, perm
    ),
)
```

- 工具通过 `register_tool(name, func, description=..., sensitive=..., permission=...)` 注册；schema 默认由函数签名自动生成。
- 支持 function-calling 的 Provider 自动走工具调用；其余 Provider 自动降级 ReAct 文本解析（`工具: name(参数JSON)`）。
- 会话记忆保留最近 N 轮（`runtime.agent_max_memory_turns`）；运行日志可在 Web「AI → Agent 工具与运行日志」查看。
- 敏感工具（如发消息、写记录）需携带 `sensitive=True` + 权限点，未授权时返回明确提示。

## 参数与子命令（分段命令）

命令可在 `plugin.json` 声明参数与子命令，框架自动分词、类型转换与校验，无需手写字符串解析：

```json
{
  "commands": [{
    "name": "greet",
    "handler": "handlers.greet_command",
    "permission": "bot.command",
    "params": [],
    "subcommands": [
      {
        "name": "hello",
        "aliases": ["你好"],
        "description": "中文问候",
        "params": [
          {"name": "target", "type": "string", "default": "世界", "description": "问候对象"},
          {"name": "count", "type": "int", "default": 1, "description": "重复次数"}
        ]
      },
      {
        "name": "world",
        "description": "世界问候",
        "params": []
      }
    ]
  }]
}
```

```python
async def greet_command(event, args, command_ctx) -> None:
    if command_ctx.subcommand == "hello":
        params = command_ctx.params or {}
        await event.reply(f"你好，{params['target']} × {params['count']}")
```

解析规则：

- 参数类型：`string` / `int` / `float` / `bool`；支持 `choices` 限定取值、`required` 必填、`default` 默认值。
- 位置参数与 `key=value` 命名参数混用；含空格的参数用引号包裹（如 `/echo "hello world"`）。
- 未声明 `params` / `subcommands` 的命令，`args` 保持原始字符串（与旧插件完全兼容）。
- 参数错误自动回复「【参数错误】原因 + 用法」，不进入处理器；`command_ctx.params` 为解析后的字典，`command_ctx.subcommand` 为命中的子命令名。
- Web「命令速查」页与 `/help <命令>` 会自动展示参数与子命令。

## 消息段与发送

`MessageSegment` 提供工厂方法统一构造消息段：`text / at / image / voice / video / record / file / face / reply / forward / markdown / json`；`Message` 支持 `add_segment()` 与 `+` 拼接。

```python
from app.core.messages import Message, MessageSegment

message = (
    Message.text("早上好 ")
    + MessageSegment.at(100)
    + MessageSegment.image(file="a.png")
)
await event.reply(message)
```

- OneBot v11 发送统一使用消息数组（非 CQ 码字符串），规避转义问题；v12 / Red / Satori / Mirai 均按各自格式透传全部段类型。
- 官方机器人适配器仅支持文本发送（官方 API 限制），能力矩阵见 [CONNECTIONS.md](CONNECTIONS.md)。
- 未知段类型不崩溃：保留原始 data 并记日志。

## 连接与重连

正向连接使用统一指数退避重连：基础间隔 `reconnect_interval`（默认 3s），每次失败 ×2，上限 `reconnect_max_seconds`（默认 60s），±20% 抖动；`reconnect_max_attempts`（默认 0 = 无限）达到后连接进入 `disabled` 状态。收包超时视为心跳过期并触发重连。可在「连接中心」新增连接时配置这三个参数。

## 监听环境与作用域

框架按「监听环境」管理策略：群消息 → `group:<id>`，私聊 → `private:*`（单一私聊环境，不做逐人控制）。

- 功能开关优先级：`group:<id>` 覆盖 > `group:*` 覆盖 > `enable_on_default`；私聊只看 `private:*`。
- 权限覆盖：某环境可对权限点设「允许 / 拒绝 / 跟随全局」。
- 黑名单按环境配置，叠加全局 `security.blocked_users`。
- 账号绑定：每个环境可绑定连接 ID，出站消息走该连接。
- 所有作用域配置存于 `config.yaml` 的 `runtime.scopes`，Web / CLI 修改后即时生效。

插件内通过 `ctx.scope_policy` 读取（只读建议）：

```python
enabled = ctx.scope_policy.feature_enabled(ctx.name, "roll", "group:123")
```

## 多连接接入

`transport.connections` 支持 onebot v11 / v12、red、satori、mirai、qq_official 并存，每个连接独立启停。接入步骤与能力对比见 [CONNECTIONS.md](CONNECTIONS.md)。开发新适配器时实现 `ProtocolAdapter`（`start/stop/send_group_message/send_private_message/test`）并归一化为统一 `BotEvent` + `MessageSegment`；反向 WS / HTTP 事件入口通过 `handle_reverse_ws` / `handle_http_event` 暴露。

## 三角色使用指南

- **指令调用者（QQ 端）**：`/help` 按当前环境过滤并展示用法示例；未找到命令给出相近建议；功能未开启默认友好提示（环境可设静默）；支持 `@bot /命令` 触发。
- **Bot 主用户（Web/CLI）**：「监听环境」页三态开关矩阵 + 批量操作；「连接中心」向导式新增/测试；「账户」页管理后台账户；`ofbot2 doctor/status/logs/backup/scopes`。
- **插件开发者**：`ofbot2 plugin new --with-*` 脚手架 → `plugin check` 静态校验 → `plugin dev` 热重载 → `plugin test`；开发期可用 `/echo` 与 Web 日志页排障。

## 能力清单（capabilities）

框架与插件通过 `CapabilityRegistry` 登记能力（名称、版本、说明、方法清单、配置 Schema）。插件运行时可按需查询并降级：

```python
# 读取已注册能力（含框架基础能力与插件能力）
names = [cap.name for cap in ctx.capabilities.list()]
if ctx.capabilities.has("ai"):
    answer = await ctx.ai.chat([{"role": "user", "content": "hi"}])
```

`ofbot2 capabilities` 与 Web「能力中心」（`/capabilities`）展示同一份清单；基础能力包括 `records`、`state_machine`、`aggregation`、`export`、`audit`、`scheduler`、`ai`、`workflow`、`webhook`、`files` 等。

## 前端约定

- Web 页面为服务端渲染（Jinja2），样式使用 CSS 变量主题（浅/深色由 `<html data-theme>` 控制），新增页面不要硬编码颜色。
- 侧边栏菜单高亮使用 `nav_active(request, "/path")`，子页面（如 `/workflows/5/edit`）会自动高亮所属菜单项。
- 表单提交建议加 `js-ajax` 类（自动 Toast + 刷新）与 `csrf_token`；危险操作加 `data-confirm` 二次确认。
- 修改 `app/web/static/js/app.js` / `app.css` 后，把 `base.html` 中静态资源 URL 的 `?v=` 版本号递增，避免浏览器缓存旧文件。
- 页面间跳转统一走侧边栏入口；新增页面需同时加入 `base.html` 菜单与 `test_assets.py` 的路由构建测试。

## 测试与质量

```powershell
py -m pytest -q
py -m ruff check app plugins main.py tests scripts
py scripts/e2e_smoke.py
```

所有核心模块应有单元测试；Web 使用 `httpx.ASGITransport` 覆盖登录、Session、页面访问与权限拒绝。一键门禁：`scripts/dev.ps1 -SkipInstall`（compileall → ruff → pytest → e2e）。
