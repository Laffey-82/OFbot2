# OFbot 2 (English Overview)

OFbot 2 is an extensible, plugin-based QQ bot framework: multi-protocol & multi-account (OneBot v11/v12, Red, Satori, Mirai, official QQ bot), per-group/per-private-chat feature toggles, a FastAPI web admin, async SQLite, APScheduler and a bubus event bus.

> Requires Python >= 3.11. Intended for local/private deployment; read [SECURITY.md](../SECURITY.md) before exposing publicly.

## Highlights

- **Multi-connection**: run NapCat / LLOneBot / Lagrange / Chronocat / Mirai / official QQ bot side by side; connections start/stop independently and can be bound per group.
- **Listener scopes**: enable/disable each plugin feature per group or private chat, plus per-scope permissions, blacklist and account binding.
- **Declarative plugins**: commands, scheduled tasks and listeners are declared in `plugin.json` (with typed params and subcommands); the framework registers, validates and gates them automatically.
- **Plugin market**: a built-in `plugin-repo/` with registry + packages; install via Web or CLI (`plugin repo list` / `plugin repo install <id>`).
- **Web admin**: dashboard, connections, plugin market, scopes, tasks, workflow engine, AI providers, records/state machines, exports/files/backups, audit/monitoring/self-healing.
- **Unified AI**: OpenAI-compatible providers, Anthropic, Gemini, Ollama, with fallback.

## Quick Start

```powershell
install.bat
start_bot.bat
```

Default web admin: http://127.0.0.1:8080 — login with `admin / admin`, change it immediately.

Recommended QQ setup: run NapCat with reverse WebSocket at `ws://127.0.0.1:8080/onebot/v11/ws`, then open the "Connections" page to verify the `napcat_main` connection, and enable features per group in the "Scopes" page.

Connection matrix and step-by-step guides: [CONNECTIONS.md](CONNECTIONS.md).

## Documentation

- [DEVELOPMENT.md](DEVELOPMENT.md) — plugin development guide
- [PLUGIN_MANIFEST.md](PLUGIN_MANIFEST.md) — `plugin.json` field reference
- [PLUGIN_REPO.md](PLUGIN_REPO.md) — plugin market & submission guide
- [ARCHITECTURE.md](ARCHITECTURE.md) — architecture overview
- [FAQ.md](FAQ.md) — common questions
- [API.md](API.md) — REST API reference

## Development & Quality Gates

```powershell
scripts\dev.ps1
```

Equivalently: `compileall` → `ruff` → `pytest` → `e2e_smoke.py`. CI runs the same gates on every push/PR, plus dependency audits (`pip-audit`) and plugin-repo artifact verification.

## License

MIT — see [LICENSE](../LICENSE).
