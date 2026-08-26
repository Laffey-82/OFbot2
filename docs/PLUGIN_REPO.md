# 插件仓库（Plugin Repo）

OFbot 2 在主仓库内置了插件仓库 `plugin-repo/`，用于存放插件开发者开发的插件。机器人端「插件市场」（Web 页 + CLI）从仓库注册表读取并一键安装。

## 双数据源

| 模式 | 触发条件 | 说明 |
| --- | --- | --- |
| 本地目录模式（默认） | `web.plugin_repo_url` 为空 | 直接扫描仓库内 `plugin-repo/registry.json` 与 `packages/*.zip`，完全离线可用 |
| URL 模式 | 配置 `web.plugin_repo_url` | 拉取远程注册表（默认指向本仓库 raw 地址）；私有仓库需配置 `web.plugin_repo_token` |

配置位置：Web「配置」页 → 基础配置 → 插件仓库地址 / 插件仓库 Token；或直接编辑 `config.yaml`：

```yaml
web:
  plugin_repo_url: https://raw.githubusercontent.com/Laffey-82/OFbot2/main/plugin-repo/registry.json
  plugin_repo_token: ""   # 私有仓库读取用（GitHub Token）
```

## 使用入口

- Web 后台 → 管理 → **插件市场**：卡片展示插件（名称/版本/分类/作者/说明），一键安装（二次确认），已安装插件标注状态。
- CLI：

```powershell
py -m app.cli plugin repo list
py -m app.cli plugin repo install dice
py -m app.cli plugin repo install dice --name my_dice
```

## 安装行为与安全

- 安装即代码执行：Web/CLI 均会提示确认；安装器强制校验 `name`、`api_version`、`version` 并拒绝路径穿越。
- 安装后默认**不启用**：请到「插件」页启用，再到「监听环境」页按群控制功能开关。
- 带模型（`models.py`）的插件安装后需重启建表。
- Token 仅用于读取私有注册表与插件包，不写入审计明文。

## 仓库结构与投稿

```text
plugin-repo/
  registry.json               # 注册表（安装源）
  plugins/<分类>/<插件名>/    # 插件源码（投稿位置）
  packages/<插件名>.zip       # 构建产物
  tools/build_packages.py     # 打包与校验脚本
```

投稿流程：

1. 在 `plugin-repo/plugins/<分类>/<插件名>/` 创建包式插件（参考 `dice`、`welcome` 与 [PLUGIN_MANIFEST.md](PLUGIN_MANIFEST.md)）。
2. 本地校验并构建：

```powershell
py plugin-repo/tools/build_packages.py --check
py plugin-repo/tools/build_packages.py
```

3. 提交源码与构建产物（`packages/*.zip`、`registry.json`），发起 PR；CI 会自动复跑校验（构建后 `git diff` 不一致会失败）。

投稿规范详见 [plugin-repo/CONTRIBUTING.md](../plugin-repo/CONTRIBUTING.md)。
