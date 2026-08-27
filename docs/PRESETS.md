# 插件示例与预设说明

> 说明：`examples/plugins/presets/` 下的示例模板是脚手架数据源（`ofbot2 plugin new --preset <名称>`），**不作为运行插件**。其中 15 个通用示例已转正为官方插件，可在「插件市场」直接安装：

- 通用互动：`dice`、`signin`、`lottery`、`poll`、`random_choice`
- 群管理：`welcome`、`keyword_reply`、`announcement`、`points`、`anti_spam`
- 信息工具：`reminder`、`qrcode`、`calc`、`timestamp`
- 业务管理：`order`、`commission`、`duty`
- 数据自动化：`stats`、`export`、`backup`、`schedule_message`
- 运维管理：`audit_viewer`、`health_check`、`system_status`

每个官方插件包含 `plugin.json`（声明式 features）、`handlers.py` 与 `README.md`（功能/配置/启用方式），并可通过 `plugin-repo/` 的构建脚本打包。

## 用示例模板开发新插件

```powershell
ofbot2 plugin new myplugin --preset dice
```

生成后编辑 `plugin.json` 与 `handlers.py`，用 `ofbot2 plugin check myplugin` 校验，再按 `docs/TUTORIAL.md` 启用与投稿。
