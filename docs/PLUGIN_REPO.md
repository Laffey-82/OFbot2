# 插件仓库（Plugin Repo）

OFbot 2 在主仓库内置了插件仓库 `plugin-repo/`，用于存放插件开发者开发的插件。机器人端「插件市场」（Web 页 + CLI）从仓库注册表读取并一键安装。

## 双数据源

| 模式 | 触发条件 | 说明 |
| --- | --- | --- |
| 本地目录模式 | `web.plugin_repo_url` 为空 | 直接扫描仓库内 `plugin-repo/registry.json` 与 `packages/*.zip`，完全离线可用 |
| URL 模式（默认，推荐） | 默认指向本仓库公开 raw 地址 | 拉取远程注册表与插件包；仓库已公开，**无需 Token**（仅接入私有仓库时才需 `web.plugin_repo_token`） |

配置位置：Web「配置」页 → 基础配置 → 插件仓库地址 / 插件仓库 Token；或直接编辑 `config.yaml`：

```yaml
web:
  plugin_repo_url: https://raw.githubusercontent.com/Laffey-82/OFbot2/main/plugin-repo/registry.json
  plugin_repo_token: ""   # 私有仓库读取用（GitHub Token）
```

## 使用入口

- Web 后台 → 管理 → **插件市场**：支持搜索与分类筛选、插件详情展开、已安装版本与可更新标记；一键安装（二次确认），已安装可覆盖更新（旧版本归档到 `plugins/.trash/`）。
- CLI：

```powershell
py -m app.cli plugin repo list
py -m app.cli plugin repo install dice
py -m app.cli plugin repo install dice --name my_dice
py -m app.cli plugin repo install dice --force   # 已存在时覆盖更新
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

官方插件（25 个，见 `plugin-repo/plugins/`）：`dice`、`welcome`、`keyword_reply`、`schedule_message`、`signin`、`todo`、`announcement`、`points`、`poll`、`random_choice`、`calc`、`lottery`、`qrcode`、`timestamp`、`commission`、`duty`、`order`、`backup`、`export`、`stats`、`audit_viewer`、`health_check`、`system_status`、`anti_spam`、`reminder`。投稿流程：

1. 在 `plugin-repo/plugins/<分类>/<插件名>/` 创建包式插件（参考 `dice`、`welcome` 与 [PLUGIN_MANIFEST.md](PLUGIN_MANIFEST.md)）。
2. 本地校验并构建：

```powershell
py plugin-repo/tools/build_packages.py --check
py plugin-repo/tools/build_packages.py
```

3. 提交源码与构建产物（`packages/*.zip`、`registry.json`），发起 PR；CI 会自动复跑校验（构建后 `git diff` 不一致会失败）。

投稿规范详见 [plugin-repo/CONTRIBUTING.md](../plugin-repo/CONTRIBUTING.md)。

## 注册表元数据（v1.0.0 起）

`registry.json` 条目由构建脚本自动生成，除基础字段外包含：

| 字段 | 说明 |
|---|---|
| `api_version` | 插件 API 版本；非 1 的插件市场禁止安装 |
| `dependencies` | 依赖声明（名称 → 版本范围），市场页展示 |
| `tags` | 标签（默认取分类），市场页展示 |
| `released_at` | 发布日期（插件 manifest 可填，留空则不展示） |
| `checksum` | 插件包 SHA-256，安装前强制校验，不匹配拒绝安装 |

安装器校验顺序：`checksum` → `api_version` → 清单字段 → 路径穿越；校验失败即拒绝。
