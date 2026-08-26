# OFbot 2 插件仓库

本目录是 OFbot 2 的**内置插件仓库**：插件开发者以 PR 向 `plugin-repo/plugins/` 投稿，维护者合并后由 CI 校验并发布到 `plugin-repo/packages/` 与 `registry.json`。机器人端「插件市场」会读取这里的注册表并一键安装。

## 目录结构

```text
plugin-repo/
  registry.json               # 机器可读注册表（框架安装源）
  plugins/<分类>/<插件名>/    # 插件源码（投稿位置）
    plugin.json / __init__.py / handlers.py / README.md
  packages/<插件名>.zip       # 构建产物（安装源）
  tools/build_packages.py     # 打包与校验脚本
```

## 插件市场接入方式

- **本地目录模式（默认，离线可用）**：框架直接扫描本目录的 `registry.json` 与 `packages/*.zip`。
- **URL 模式**：在 Web「配置」页或 `config.yaml` 设置 `web.plugin_repo_url` 指向 `plugin-repo/registry.json` 的 raw 地址；私有仓库需同时配置 `web.plugin_repo_token`（GitHub Token）或将仓库公开。

入口：

- Web 后台 → 管理 → 插件市场
- CLI：`py -m app.cli plugin repo list` / `py -m app.cli plugin repo install <id>`

## 插件投稿规范

1. 在 `plugins/<分类>/<插件名>/` 下创建包式插件（必含 `plugin.json`、`__init__.py`，建议 `handlers.py`）。
2. `plugin.json` 遵循 [docs/PLUGIN_MANIFEST.md](../docs/PLUGIN_MANIFEST.md)：`api_version: 1`、`version` 为 `X.Y.Z`、`name` 与目录名一致、命令/任务/监听声明在 `features` 中。
3. 本地运行构建并确认通过：

```powershell
py plugin-repo/tools/build_packages.py --check
py plugin-repo/tools/build_packages.py
```

4. 提交源码与构建产物（`packages/*.zip`、`registry.json` 的变更）后发起 PR；CI 会自动复跑校验。

## 安全边界

- 插件安装即代码执行：仅安装可信来源的插件；Web 与 CLI 均会在安装前二次确认。
- 安装器强制校验插件名、`api_version`、`version` 并拒绝路径穿越。
- 安装后默认**不启用**，由主用户按监听环境手动开启。

详细说明见 [docs/PLUGIN_REPO.md](../docs/PLUGIN_REPO.md)。
