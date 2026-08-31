# OFbot 2 (English Overview)

![CI](https://github.com/Laffey-82/OFbot2/actions/workflows/ci.yml/badge.svg)
![Python](https://img.shields.io/badge/Python-3.11%2B-blue)
![License](https://img.shields.io/github/license/Laffey-82/OFbot2)

OFbot 2 is an extensible, plugin-based QQ bot framework: **multi-protocol & multi-account**
(OneBot v11/v12, Red, Satori, Mirai, official QQ bot), **per-group/per-private-chat feature
toggles**, a FastAPI web admin, async SQLite and a self-built async event bus.

> Requires Python >= 3.11. Intended for local/private deployment; read
> [SECURITY.md](../SECURITY.md) before exposing publicly.

> [中文版](../readme.md) · [Docs index](README.md)

## Highlights

- **Multi-connection**: run NapCat / LLOneBot / Lagrange / Chronocat / Mirai / official QQ
  bot side by side; connections start/stop independently and can be bound per group.
- **Listener scopes**: enable/disable each plugin feature per group or private chat, plus
  per-scope permissions, blacklist and account binding.
- **Declarative plugins**: commands, scheduled tasks and listeners are declared in
  `plugin.json`; the framework registers, validates and gates them automatically.
- **Typed params & subcommands**: commands declare typed arguments (required/default/choices)
  and subcommands; parse errors show usage hints automatically.
- **Web admin**: dashboard, connections, plugin market, scopes, tasks, workflow engine,
  AI providers, records/state machines, exports/files/backups, audit/monitoring/self-healing.
- **Unified AI**: OpenAI-compatible providers (OpenAI/DeepSeek/Qwen/Moonshot/Azure),
  Anthropic, Gemini, Ollama, with provider fallback.
- **Workflow engine**: triggered by message / schedule / webhook / record changes; actions
  compose into automations (send message, run command, call AI, write records, export).
- **Plugin market**: built-in `plugin-repo/` with 25+ official plugins; URL or local sources.
- **Observability & security**: structured logs, Prometheus metrics, audit logs, login lockout
  & CSRF, command cooldown & rate limits, exception redaction, plugin static audit and an
  optional subprocess sandbox.

## Quick Start

```powershell
install.bat
start_bot.bat
```

Or manually:

```powershell
py -m pip install -r requirements.txt
py -m app.cli run
```

Default web admin: http://127.0.0.1:8080 — login with `admin / admin`, change it immediately.

Recommended QQ setup: run NapCat with a reverse WebSocket at
`ws://127.0.0.1:8080/onebot/v11/ws`, then open the "Connections" page to verify the
`napcat_main` connection, add your group in the "Scopes" page and enable features.

See [CONNECTIONS.md](CONNECTIONS.md) for the connection matrix and step-by-step guides.

No QQ environment? Use the fake Red service:

```powershell
py scripts/fake_chronocat.py        # start the fake service (second terminal)
py main.py --config data/fake_config.yaml
```

One-command end-to-end smoke test (starts the fake service → starts the bot → sends `/ping`
→ verifies `pong`):

```powershell
py scripts/e2e_smoke.py
```

## Documentation

| Doc | Description |
| --- | --- |
| [README.md](README.md) | Docs index (上手/开发/运维/参考/治理) |
| [QUICKSTART.md](QUICKSTART.md) | 3-minute start: connect → plugins → toggles |
| [INSTALL.md](INSTALL.md) | Install via pip / Git / Docker |
| [CONNECTIONS.md](CONNECTIONS.md) | QQ connection matrix and guides |
| [DEVELOPMENT.md](DEVELOPMENT.md) | Plugin development guide |
| [PLUGIN_MANIFEST.md](PLUGIN_MANIFEST.md) | `plugin.json` field reference |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Architecture, message flow, scopes, plugin lifecycle |
| [GLOSSARY.md](GLOSSARY.md) | Terminology |
| [FAQ.md](FAQ.md) | Frequently asked questions |
| [API.md](API.md) | REST API reference (generated) |
| [CHANGELOG.md](CHANGELOG.md) | Version history |

> Most detailed docs are in Chinese; the English pages cover the key entry points
> (Quick Start, Install, Connections). Contributions of English translations are welcome.

## Development

Plugin handlers are plain async functions declared in `plugin.json`:

```python
from app.core.messages import Message, MessageEvent

async def ping_command(event: MessageEvent, args: Message, command_ctx) -> None:
    await event.reply("pong")
```

Run the full quality gate:

```powershell
scripts\dev.ps1
```

## Contributing & License

See [CONTRIBUTING.md](../CONTRIBUTING.md), [MAINTAINERS.md](MAINTAINERS.md) and
[SECURITY.md](../SECURITY.md). Licensed under [MIT](../LICENSE).
