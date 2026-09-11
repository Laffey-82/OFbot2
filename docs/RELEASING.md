# 发版指南

本文档面向维护者，说明如何为一个新版本完成从版本号、变更日志到 GitHub Release 与 wiki
同步的完整闭环。仓库使用「单一版本号 + tag 触发 Release workflow」的模型，任何一次
「改了代码却忘了升版本/打 tag」都会在 CI 的一致性门禁中被拦截。

## 一次标准发版

1. 确认 `main` 上的代码已经通过全量门禁：`compileall`、`ruff check`、`pytest`、
   `scripts/e2e_smoke.py`（如涉及插件则跑对应插件 e2e）。
2. 在 `docs/CHANGELOG.md` 顶部新增 `## vX.Y.Z（日期）— 标题` 小节，按用户可见的行为变化
   组织条目；只保留 1.x 版本线，历史版本统一在 `docs/archive/` 归档。
3. 运行一致性校验与预览：

   ```powershell
   python scripts/release.py --version X.Y.Z --dry-run
   ```

   该命令会检查 `app/__init__.py`、`pyproject.toml`、`docs/CHANGELOG.md` 三者版本是否一致，
   并打印将要执行的 git/gh 动作。
4. 升级版本号并执行真实发版：

   ```powershell
   python scripts/release.py --version X.Y.Z --bump
   ```

   `--bump` 会调用 `scripts/sync_version.py` 同步版本号；真实执行会提交、打 tag、推送并
   创建 GitHub Release。
5. tag 推送后，`.github/workflows/release.yml` 会从 CHANGELOG 的对应小节生成发布说明。
   若手动或自动化过程中发现 Release 缺失，可回退到 tag 后用 `gh release create` 重建。

## 版本一致性门禁

`scripts/check_release.py` 是 CI 中的发布门禁，检查：

- `pyproject.toml` 的 `project.version` 与 `app.__version__` 一致；
- 两者与 `docs/CHANGELOG.md` 最新的 `## vX.Y.Z` 标题一致；
- 若当前提交信息包含 `vX.Y.Z`，该版本必须等于 `app.__version__`。

这条门禁用于防止「提交信息写 v1.5.0、实际版本仍是 1.4.0」这类漂移。CI 在每次 push
运行 `python scripts/check_release.py`，任何不一致都会使 job 失败。

## 插件市场同步

发版前运行：

```powershell
python scripts/audit_plugin_repo.py --check
python plugin-repo/tools/build_packages.py --check
```

前者检查市场 zip 是否只含预期文件、以及内置插件与市场插件是否同步；后者核对已提交的
`packages/*.zip` 与 `registry.json` 是否与源码一致。修改任何市场插件后都需要重新构建并提交
产物。

## wiki 同步

每次发版后同步 [wiki](https://github.com/Laffey-82/OFbot2/wiki)，至少更新：

- `Home.md`：版本号与当次特性速览；
- `Plugin-Development.md`：新增的插件开发能力；
- `Plugin-Manifest.md`：manifest 字段与命令/任务声明变化；
- 需要时新增或更新 `Release-Process.md`。

## 常见问题

- **Release 出现重复草稿**：通常是移动/重建 tag 导致旧 Release 与 tag 脱钩。删除未发布的
  untagged 草稿，再用 `gh release create` 或 workflow 重建指向正确 tag 的 Release。
- **`check_release.py` 失败但代码正常**：先确认三个版本出处是否都已更新，必要时补 CHANGELOG
  小节或修正提交信息。
