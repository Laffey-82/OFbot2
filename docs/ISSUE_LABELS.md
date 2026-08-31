# Issue 标签体系

建议在仓库中启用以下标签，统一分类：

| 类别 | 标签 | 说明 |
|---|---|---|
| 类型 | `bug` / `feature` / `enhancement` / `question` | 问题、功能、优化、咨询 |
| 模块 | `core` / `adapters` / `web` / `plugins` / `docs` / `cli` | 影响范围 |
| 协议 | `onebot` / `red` / `satori` / `mirai` / `qq-official` | 连接协议 |
| 插件投稿 | `plugin-submission` / `plugin-review` | 仓库投稿与评审 |
| 流程 | `needs-triage` / `good-first-issue` / `wontfix` / `duplicate` | 处理状态 |
| 安全 | `security` | 安全问题（优先处理，走 SECURITY.md 私密报告） |
| 版本 | `v1.0.0` / `v1.1.0` / `v1.2.0` / `v1.3.0` … | 目标里程碑 |

> 标签由 `scripts/repo_setup.py` 自动创建（幂等）：`py scripts/repo_setup.py`。
