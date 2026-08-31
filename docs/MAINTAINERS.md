# 维护者指南（MAINTAINERS）

本文档面向 OFbot 2 维护者：评审、合并、发布与治理的职责边界和操作清单。

## 角色与职责

- **维护者**：负责评审 PR、合并代码、发布版本、响应安全问题与治理争议。
- **投稿者**：按 [CONTRIBUTING.md](../CONTRIBUTING.md) 提交 Issue / PR / 插件投稿。
- **安全处理**：漏洞报告走 [SECURITY.md](../SECURITY.md) 私密渠道，修复发布前保密。

## 评审清单（合并 PR 前）

1. 本地门禁全绿：`scripts\dev.ps1 -SkipInstall`
   （compileall → ruff → pytest → e2e_smoke；文档变更另加 `py scripts/check_docs_links.py`）。
2. 代码约定：插件仅经 `PluginContext` 访问能力；新功能带测试；文档同步更新。
3. 插件投稿：运行 `py plugin-repo/tools/build_packages.py --check` 且 `git diff --exit-code -- plugin-repo` 干净。
4. 破坏性变更（插件 API、数据表结构）必须在 [CHANGELOG.md](CHANGELOG.md) 显著标注。
5. 安全相关改动重点评审：鉴权、路径穿越、注入、限流与密钥处理。

## 发布流程（checklist）

1. 更新版本号：`py scripts/sync_version.py X.Y.Z`（同步 `app/__init__.py` 与 `pyproject.toml`）。
2. 在 [CHANGELOG.md](CHANGELOG.md) 顶部写本版本条目；破坏性变更显著标注。
3. 如需公开截图：`py scripts/capture_screenshots.py` 重新生成并提交 `docs/assets/screenshots/`。
4. 提交并推送，CI 全绿。
5. 打 tag 推送：`git tag vX.Y.Z && git push origin vX.Y.Z` → [release.yml](../.github/workflows/release.yml) 自动生成 GitHub Release。
6. PyPI 发布（可选）：在仓库 Actions 手动触发 `Publish to PyPI`（需配置 OIDC 或 `PYPI_TOKEN` secret）。
7. 归档：把 ISSUE_LABELS 中对应里程碑标签标记完成；更新 [GOALS.md](GOALS.md) 状态。

## 决策与版本策略

- **语义化版本**：破坏性变更（插件 API、数据库表结构、配置不兼容）升 minor；缺陷修复升 patch。
- **分支**：主分支 `main`；功能开发用 `of/*` 前缀分支；插件仓库单独评审。
- **争议决策**：维护者讨论后在 CHANGELOG / GOALS 记录结论，保持透明。
- **行为准则**：按 [CODE_OF_CONDUCT.md](../CODE_OF_CONDUCT.md) 执行，违规可移除贡献者/关闭讨论。

## 标签与分类

- 标签体系见 [ISSUE_LABELS.md](ISSUE_LABELS.md)，由 `scripts/repo_setup.py` 自动同步。
- 新 Issue 默认 `needs-triage`；评审后打类型/模块/协议标签，标记 `good-first-issue` 给新手。
- 插件投稿使用 `plugin-submission`，评审中改 `plugin-review`。

## 日常维护

- Dependabot 每周扫描依赖与 Actions；合并前跑完整门禁。
- 关注 CI 失败与告警（自愈/审计）；数据库定期备份（Web「数据备份」页或 CLI `backup`）。
- 文档变更保持中英互链与 `check_docs_links.py` 通过。
