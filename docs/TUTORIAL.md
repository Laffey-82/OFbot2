# 从零写第一个插件（教程）

目标：用 10 分钟写一个「掷硬币」插件 `/coin`，覆盖脚手架、声明式 manifest、handler、静态校验、启用与投稿。

## 1. 生成脚手架

```powershell
ofbot2 plugin new coin
```

会在 `plugins/coin/` 生成最小包（`plugin.json` + `__init__.py`）。

## 2. 声明命令（plugin.json）

编辑 `plugins/coin/plugin.json`，加入声明式 feature：

```json
{
  "features": [{
    "id": "coin",
    "label": "掷硬币",
    "description": "随机正反面",
    "enable_on_default": true,
    "manage_permission": "coin.admin",
    "commands": [{
      "name": "coin",
      "aliases": ["硬币"],
      "handler": "handlers.coin_command",
      "permission": "coin.use",
      "description": "随机正反面",
      "usage": "/coin",
      "examples": ["/coin"]
    }]
  }]
}
```

## 3. 实现 handler

新建 `plugins/coin/handlers.py`：

```python
import random

from app.core.messages import Message, MessageEvent
from app.core.plugin import PluginContext

_ctx: PluginContext | None = None

def setup(ctx: PluginContext) -> None:
    global _ctx
    _ctx = ctx

async def coin_command(event: MessageEvent, args: Message, command_ctx) -> None:
    await event.reply("🪙 " + random.choice(["正面", "反面"]))
```

在 `__init__.py` 中让插件加载 handlers：

```python
from app.core.plugin import Plugin, PluginContext
from . import handlers

class CoinPlugin(Plugin):
    def setup(self, ctx: PluginContext) -> None:
        handlers.setup(ctx)

def create_plugin() -> Plugin:
    return CoinPlugin()
```

## 4. 静态校验

```powershell
ofbot2 plugin check coin
```

校验 manifest 字段、handler 符号是否存在、规则是否注册；失败会给出明确错误。

## 5. 启用

1. 在 `config.yaml` 的 `plugins` 中加入 `coin: true`，重启机器人（或 Web「插件」页启用）。
2. 在群内发送 `/coin`。
3. 在 Web「监听环境」页可按群独立开/关该功能，群管理员也可用 `/功能启用 coin.coin`。

## 6. 进阶：响应规则与会话

- 命令声明 `"rules": [{"name": "group_only"}]` 限制仅群内可用；`"session": true` 后可读写 `command_ctx.session`（确认流示例见 `plugins/template` 的 `/ask`）。
- 定时任务与事件监听直接在 manifest 的 `tasks` / `listeners` 声明。

## 7. 投稿到插件仓库

1. 参照官方插件补 `README.md`（功能/配置/启用方式）。
2. 把插件放入 `plugin-repo/plugins/<分类>/<插件名>/`，运行：

```powershell
py plugin-repo/tools/build_packages.py --check
py plugin-repo/tools/build_packages.py
```

3. 提交源码与构建产物（`packages/*.zip`、`registry.json`）并发 PR；CI 会复跑校验。

完整字段参考：[PLUGIN_MANIFEST.md](PLUGIN_MANIFEST.md)；开发指南：[DEVELOPMENT.md](DEVELOPMENT.md)。
