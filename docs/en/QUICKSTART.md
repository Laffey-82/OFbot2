# Quick Start (3 Minutes)

> [中文版](../QUICKSTART.md)

Three steps to get the bot running and serving your groups.

## ① Connect a protocol (about 1 minute)

1. Install and log in to a protocol implementation — **NapCat** (headless NTQQ) is recommended.
2. In NapCat, enable **Reverse WebSocket** at `ws://127.0.0.1:8080/onebot/v11/ws`.
3. Open the web admin → **Connections**, confirm `napcat_main` is **Connected**.

Other options (Chronocat / Lagrange / Mirai / official QQ bot) are covered in
[CONNECTIONS.md](CONNECTIONS.md).

## ② Install plugins (about 1 minute)

1. Open the web admin → **Plugin Market**.
2. Browse or search plugins (e.g. `dice`, `keyword_reply`, `signin`, `todo`).
3. Click **Install** (with confirmation). Installed plugins are **disabled by default**.

CLI alternative:
`py -m app.cli plugin repo list` / `py -m app.cli plugin repo install dice`.

## ③ Enable features (about 1 minute)

1. Open the web admin → **Plugins**, enable the plugin you just installed.
2. Open **Scopes**, add your group ID.
3. In the feature matrix, turn on the features for that group (e.g. dice, welcome).

Send `/help` in the group to see available commands; `/help <command>` shows usage examples.

## Quick reference

| What you want | Where |
| --- | --- |
| Connect / test a connection | Management → Connections |
| Install / update plugins | Management → Plugin Market |
| Toggle features per group | Management → Scopes |
| Scheduled tasks / workflows | Automation → Tasks / Workflows |
| Configuration & security | Management → Config |
| Troubleshooting | System → Setup wizard / Logs |
