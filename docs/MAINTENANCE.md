# 维护指南（MAINTENANCE）

## 发布节奏

- 每完成一个功能里程碑，执行 `py scripts/sync_version.py X.Y.Z` 并更新 `docs/CHANGELOG.md`。
- 推送 `vX.Y.Z` tag 触发 [release.yml](../.github/workflows/release.yml) 自动生成 GitHub Release。
- 破坏性变更（插件 API、数据表结构）必须在 CHANGELOG 中显著标注。
- PyPI 发布：在仓库 Actions 手动触发 `Publish to PyPI`（需配置 OIDC 受信发布或
  `PYPI_TOKEN` secret），发布后可在 README 补挂 PyPI 版本徽章。

## 门禁清单（合并 PR 前）

```powershell
py -m compileall app plugins main.py tests scripts
py -m ruff check app plugins tests main.py scripts plugin-repo/tools
py -m pytest -q
py scripts/e2e_smoke.py
```

插件仓库变更需额外：

```powershell
py plugin-repo/tools/build_packages.py
py plugin-repo/tools/build_packages.py --check
git diff --exit-code -- plugin-repo
```

文档/仓库层变更需额外：

```powershell
py scripts/check_docs_links.py
```

## 分支与版本

- 主分支 `main`，功能开发使用 `of/*` 前缀分支。
- 里程碑规划见 [GOALS.md](GOALS.md)；详细文档索引见 `docs/`。

## 数据与备份

- SQLite 数据库位于 `data/ofbot2.db`；定时/手动备份在 Web「数据备份」页操作。
- 配置修改通过 Web/CLI 写入 `config.yaml`，修改前自动保留历史版本。

## 安全响应

- 安全漏洞请按 [SECURITY.md](../SECURITY.md) 私密报告。
- 插件投稿评审清单见 [SECURITY_REVIEW.md](SECURITY_REVIEW.md)。
