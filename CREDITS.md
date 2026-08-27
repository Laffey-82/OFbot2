# 致谢（CREDITS）

OFbot 2 站在以下成熟开源项目与生态的肩膀上，特此致谢：

## 参考与借鉴的项目

- **NoneBot2** — 事件驱动、插件化与命令系统的设计思路；响应规则（Rule）的声明式轻量版。
- **Koishi** — 插件市场、控制台式管理后台、多账号与权限模型。
- **ZeroBot / HoshinoBot** — 逐群 Service 功能开关（enable_on_default + 覆盖集）与 Ban/Permit 群管理。
- **LangBot** — 会话记忆与 Agent 工具调用循环（function-calling + ReAct 降级）。
- **OneBot 生态**（NapCat / LLOneBot / Lagrange / OpenShamrock / go-cqhttp）— 协议兼容矩阵与接入方案。
- **Chronocat** — Red / Satori 协议的早期接入参考。
- **Mirai** 与 mirai-api-http — 老牌 QQ 机器人接入方案。

## 依赖

- FastAPI / Uvicorn / Jinja2 — Web 后台
- SQLAlchemy 2.0 + aiosqlite — 异步数据层
- APScheduler — 调度器
- bubus — 事件总线
- Pydantic v2 / PyYAML — 配置模型
- 其余依赖见 `pyproject.toml`

## 社区贡献者

按 GitHub 贡献记录鸣谢。欢迎通过 Issue / PR 参与插件投稿、文档与代码贡献。

OFbot 2 使用 [Apache-2.0](LICENSE) 协议开源。
