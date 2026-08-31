# QQ Connection Guide

> [中文版](../CONNECTIONS.md)

OFbot 2 supports multiple connections at once: one instance can run several protocols /
accounts side by side. Each connection starts/stops independently. Outbound messages use
the first available connection by default; you can bind a specific connection per group in
the **Scopes** page.

## Solution overview

| Solution | Protocol | Transport | Notes |
| --- | --- | --- | --- |
| NapCat | OneBot v11 | Reverse WS (recommended) / forward WS / HTTP | Headless NTQQ, most active, low footprint |
| LLOneBot | OneBot v11 | WS / HTTP | NTQQ plugin, same adapter as NapCat |
| Lagrange.OneBot | OneBot v11 / v12 | WS / HTTP | Cross-platform |
| OpenShamrock | OneBot v11 | WS / HTTP | Android + LSPosed |
| Chronocat (new) | Satori | Forward WS | Project discontinued; Satori only |
| Chronocat (legacy) | Red | WS + HTTP API | Kept for compatibility |
| Lagrange.Satori | Satori | Forward WS | Lagrange via Satori |
| Mirai + mirai-api-http | Mirai HTTP | HTTP / WS / reverse WS | verifyKey + session auth |
| Official QQ bot | Official API v2 | WS Gateway + REST | Group messages only when @-mentioned; rate-limited |

> **Media**: except for the official bot, all protocols pass through full message segments
> (text / @ / image / voice / video / file / sticker / quote / forward / JSON); the official
> bot currently supports text only.

## Capability × implementation matrix

| Capability | OneBot v11 | OneBot v12 | Red | Satori | Mirai | Official |
| --- | :-: | :-: | :-: | :-: | :-: | :-: |
| Forward WS | ✅ | ✅ | ✅ | ✅ | — | ✅ (Gateway) |
| Reverse WS | ✅ | ✅ | — | — | ✅ | — |
| HTTP events | ✅ | ✅ | — | — | ✅ (polling) | — |
| Group messages | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ (only @) |
| Private messages | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ (C2C) |
| Media passthrough | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ (text only) |
| Event types (poke/file/recall) | ✅ | ✅ | partial | partial | partial | ❌ |
| Multi-account | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Heartbeat / reconnect | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

## Recommended: NapCat OneBot v11 reverse WS

1. Deploy NapCat (Windows / Linux / macOS) and log in a QQ account.
2. In NapCat, enable **Reverse WebSocket** listening at
   `ws://127.0.0.1:8080/onebot/v11/ws`.
3. In OFbot's **Connections** page, confirm the `napcat_main` connection exists
   (protocol `onebot`, version `v11`, mode `reverse_ws`).
4. Connect NapCat; the connection status becomes **Connected**.

> In reverse WS mode NapCat connects into OFbot, so "Test connection" is unavailable —
> that is expected. Verify NapCat is running and the reverse WS URL is correct.

## Other protocols

- **OneBot v12 (Lagrange.OneBot)**: protocol `onebot`, version `v12`, reverse WS
  (recommended) or forward WS.
- **Satori (new Chronocat / Lagrange.Satori)**: protocol `satori`, forward WS; optional
  gateway token.
- **Red (legacy Chronocat)**: protocol `red`, forward WS, with `host/port/token/api_base`.
- **Mirai**: protocol `mirai`, mode `http`, `token` = verifyKey, `self_id` = bot QQ.
- **Official QQ bot**: protocol `qq_official`, mode `ws_gateway`, with `app_id` and bot
  token; group chat only receives @-mentions.

## Connection config (config.yaml)

```yaml
transport:
  connections:
    - id: napcat_main
      protocol: onebot        # onebot | red | satori | mirai | qq_official
      version: v11            # onebot: v11 | v12
      mode: reverse_ws        # forward_ws | reverse_ws | http | ws_gateway
      enabled: true
      host: 127.0.0.1
      port: 8080
      path: /onebot/v11/ws
      access_token: ""
      token: ""
      api_base: ""
      app_id: ""
      secret: ""
      self_id: ""
      reconnect_interval: 3.0
```

> Legacy `transport.red` / `transport.onebot` keys are seeded into the connection list on
> first load; `connections` is the single source of truth afterwards.

## Account binding (per-group routing)

In the **Scopes** page you can bind a connection to each group/private environment:

- Outbound messages (scheduled tasks, workflow actions, plugin sends) use the bound
  connection;
- inbound events always come from the connection that actually received them;
- without a binding, the first **Connected** connection is used automatically.
