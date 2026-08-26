# OFbot 2

![CI](https://github.com/Laffey-82/OFbot2/actions/workflows/ci.yml/badge.svg)

可扩展的插件化 QQ 机器人框架：**多协议多账号并存**（OneBot v11/v12、Red、Satori、Mirai、QQ 官方机器人），**逐群/私聊独立控制功能开关**，配套 FastAPI Web 管理后台、异步 SQLite、APScheduler 与 bubus 事件总线。

> 要求 Python >= 3.11；默认本地/私域部署，公网部署请阅读 [FAQ](docs/FAQ.md) 的安全建议。

> [English Overview](docs/README.en.md)

## 功能特性

- **多连接接入**：一个实例同时接入 NapCat / LLOneBot / Lagrange / Chronocat / Mirai / 官方机器人，连接独立启停、按群绑定账号路由出站消息。
- **监听环境**：每个群、私聊独立控制插件功能开关、权限覆盖、黑名单与静默模式（Web「监听环境」页三态开关矩阵）。
- **声明式插件**：命令 / 定时任务 / 监听器在 `plugin.json` 中声明，加载自动注册与校验；插件只提供功能，开关由主用户控制。
- **参数与子命令**：命令可声明类型化参数（必填/默认/可选值）与子命令（分段命令），解析错误自动给出用法提示。
- **Web 后台**：仪表盘、连接中心、插件管理、定时任务、流程引擎、AI 能力、记录/状态机/聚合、导出/文件/备份、审计/监控/自愈。
- **统一 AI**：OpenAI 兼容（OpenAI/DeepSeek/Qwen/Moonshot/Azure）、Anthropic、Gemini、Ollama，多 Provider 切换与降级。
- **自动化流程引擎**：消息/定时/Webhook/记录变更触发，动作可组合（发消息、执行命令、调 AI、写记录、导出）。
- **可观测与安全**：结构化日志、Prometheus 指标、审计日志、登录锁定与 CSRF、命令冷却与三级限流、异常脱敏。

## 快速开始

```powershell
install.bat
start_bot.bat
```

或手动执行：

```powershell
py -m pip install -r requirements.txt
py -m app.cli run
```

默认 Web 后台：http://127.0.0.1:8080
默认账户：`admin / admin`，首次启动后请立即修改。

接入 QQ 的推荐方式（NapCat OneBot v11 反向 WS，默认配置已内置）：

1. 部署并登录 NapCat，开启「反向 WebSocket」，地址填 `ws://127.0.0.1:8080/onebot/v11/ws`。
2. 启动机器人后打开「连接中心」，确认 `napcat_main` 状态为「已连接」。
3. 在「监听环境」页添加你的群，并开启需要的插件功能。

各协议接入步骤与能力对比见 [docs/CONNECTIONS.md](docs/CONNECTIONS.md)。

没有 QQ 环境时可用假 Red 服务联调：

```powershell
py scripts/fake_chronocat.py        # 启动假服务（另一终端）
py main.py --config data/fake_config.yaml
```

一键端到端冒烟（自动起假服务 → 启动 bot → 发 `/ping` → 验证 `pong`）：

```powershell
py scripts/e2e_smoke.py
```

## 文档导航

| 文档 | 说明 |
| --- | --- |
| [docs/CONNECTIONS.md](docs/CONNECTIONS.md) | QQ 接入方案总览、能力矩阵与图文步骤 |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | 插件开发指南（声明式规范、能力 API、CLI） |
| [docs/PLUGIN_MANIFEST.md](docs/PLUGIN_MANIFEST.md) | `plugin.json` 全字段参考与校验错误对照 |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 架构分层、消息流、作用域判定、插件生命周期 |
| [docs/FAQ.md](docs/FAQ.md) | 常见问题与运维排查 |
| [docs/API.md](docs/API.md) | REST 接口清单（自动生成） |
| [docs/CHANGELOG.md](docs/CHANGELOG.md) | 版本更新记录 |
| [docs/CHRONOCAT.md](docs/CHRONOCAT.md) | Chronocat/Red 旧接入指南（兼容保留） |

## 目录结构

- `app/core`：配置、日志、事件总线、权限、限流、缓存、命令路由、作用域策略、插件管理、调度器。
- `app/adapters`：多协议适配器（OneBot v11/v12、Red、Satori、Mirai、QQ 官方）、`ConnectionManager` 与统一消息模型。
- `app/db`：异步 SQLAlchemy 模型、会话、迁移基础设施。
- `app/web`：FastAPI 后台（服务端渲染 + 原生 JS），路由按域拆分（仪表盘/配置/插件/连接/监听环境/任务/流程/AI/审计等）。
- `app/services`：records / state_machine / aggregation / audit / ai / workflow / webhook / alerts / export / files / backup 等服务。
- `app/runtime.py`：运行时装配（任务恢复与执行、命令统计、审计持久化、适配器构建）。
- `plugins/<name>/`：包式插件（`plugin.json` + `__init__.py`），system 与 template 为内置示例。
- `examples/plugins/presets/`：示例模板，供 `ofbot2 plugin new` 生成新插件。

## 插件开发

推荐**声明式**写法：在 `plugin.json` 中用 `features` 声明命令、任务与监听器，框架自动注册并按监听环境控制开关：

```json
{
  "features": [{
    "id": "ping",
    "label": "连通测试",
    "enable_on_default": true,
    "commands": [{
      "name": "ping",
      "handler": "handlers.ping_command",
      "permission": "my_plugin.ping",
      "description": "返回 pong",
      "usage": "/ping",
      "examples": ["/ping"]
    }]
  }]
}
```

处理器放在 `handlers.py`：

```python
from app.core.messages import Message, MessageEvent

async def ping_command(event: MessageEvent, args: Message, command_ctx) -> None:
    await event.reply("pong")
```

从模板生成完整可运行插件：

```powershell
py -m app.cli plugin new my_plugin --with-task --with-listener
py -m app.cli plugin check my_plugin
py -m app.cli plugin dev my_plugin
```

完整规范见 [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) 与 [docs/PLUGIN_MANIFEST.md](docs/PLUGIN_MANIFEST.md)。

## 配置

主配置位于 `config.yaml`（参考 [config.example.yaml](config.example.yaml)）。默认接入 NapCat（OneBot v11 反向 WS）：

```yaml
transport:
  connections:
    - id: napcat_main
      protocol: onebot
      version: v11
      mode: reverse_ws
      host: 127.0.0.1
      port: 8080
      path: /onebot/v11/ws
      access_token: ""
```

作用域（逐环境功能开关/权限/黑名单/账号绑定）与插件任务启停保存在 `config.yaml` 的 `runtime` 段，Web/CLI 修改后即时生效。

## 内置命令

- `/help [命令]`：查看帮助（按当前环境过滤，展示用法与示例）。
- `/about`：框架版本与核心能力清单。
- `/echo <内容>`：调试用。
- `/whitelist add|del|list <群号>`：管理群白名单。
- `/task list|add|enable|disable|remove`：管理定时任务。
- `/plugins`、`/status`：查看插件与系统状态。

## CLI

```powershell
py -m app.cli run [--config PATH]     # 启动机器人
py -m app.cli doctor                  # 环境自检
py -m app.cli status                  # 运行状态
py -m app.cli logs --tail 50          # 查看日志
py -m app.cli backup                  # 立即备份
py -m app.cli connections list|add|test
py -m app.cli scopes list|set
py -m app.cli plugin new|list|install|reload|unload|check|dev|test|features
py -m app.cli capabilities            # 框架能力清单
py -m app.cli workflow list|run
```

## 开发验证

一键质量门禁：

```powershell
scripts\dev.ps1
```

或单独执行：

```powershell
py -m compileall -q app plugins main.py tests scripts
py -m ruff check app plugins main.py tests scripts
py -m pytest -q
py scripts/e2e_smoke.py
```

GitHub Actions 会在每次 push / PR 自动运行上述检查。

## 更新记录

版本里程碑见 [docs/CHANGELOG.md](docs/CHANGELOG.md)，逐条历史见 [docs/CHANGELOG_FULL.md](docs/CHANGELOG_FULL.md)。
