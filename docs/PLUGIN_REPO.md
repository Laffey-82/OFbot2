# 插件市场（plugin-repo）

`plugin-repo/` 是 OFbot2 的官方插件市场。机器人端「插件市场」（Web 页 + CLI）从市场注册表读取并一键安装，同时支持完全离线的本地目录模式。

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

- 安装即代码执行：Web/CLI 均会提示确认；安装器强制校验 `name`、`api_version`、`version`、`checksum` 并拒绝路径穿越。
- 安装后默认**不启用**：请到「插件」页启用，再到「监听环境」页按群控制功能开关。
- 带模型（`models.py`）的插件安装后需重启建表。
- Token 仅用于读取私有注册表与插件包，不写入审计明文。

## 目录结构

```text
plugin-repo/
  plugins/<category>/<name>/   # 插件源码（含 plugin.json / __init__.py / handlers.py 等）
  packages/<name>.zip          # 由 build_packages.py 生成的发布制品
  registry.json                # 市场索引（元数据 + checksum + 下载地址）
  tools/build_packages.py      # 打包与一致性校验脚本
```

官方插件（26 个，见 `plugin-repo/plugins/`）：`dice`、`welcome`、`keyword_reply`、`schedule_message`、`signin`、`todo`、`announcement`、`points`、`poll`、`random_choice`、`calc`、`lottery`、`qrcode`、`timestamp`、`commission`、`duty`、`order`、`backup`、`export`、`stats`、`audit_viewer`、`health_check`、`system_status`、`anti_spam`、`reminder`、`order_ledger`。

## 打包与校验

```powershell
python plugin-repo/tools/build_packages.py              # 全量构建 packages/ 与 registry.json
python plugin-repo/tools/build_packages.py --check      # 仅校验，不写入（CI 使用）
python scripts/audit_plugin_repo.py --check             # 制品健康与内置同步审计
```

CI 的 `plugin-repo.yml` 只在 `plugin-repo/**` 变化时运行 `build_packages.py --check`，确保已提交产物与源码一致。产物采用确定性打包（固定时间戳、STORE 压缩、LF 统一），保证跨平台字节一致。

## 新增一个市场插件

1. 在 `plugin-repo/plugins/<category>/<name>/` 创建源码，`plugin.json` 的 `name` 必须等于目录名，`api_version` 为 1，`version` 为 `X.Y.Z`，且必须有 `__init__.py`（参考 `dice`、`welcome` 与 [PLUGIN_MANIFEST.md](PLUGIN_MANIFEST.md)）。
2. 本地校验并构建：

```powershell
py plugin-repo/tools/build_packages.py --check
py plugin-repo/tools/build_packages.py
```

3. 若该插件同时作为内置插件维护在 `plugins/<name>/`，保持两端 `name/version/description/author` 完全一致；`audit_plugin_repo.py` 会对此做同步校验。
4. 将源码、`packages/*.zip` 与 `registry.json` 一起提交，发起 PR；CI 会自动复跑校验（构建后 `git diff` 不一致会失败）。投稿规范详见 [plugin-repo/CONTRIBUTING.md](../plugin-repo/CONTRIBUTING.md)。

## 制品健康规则

`scripts/audit_plugin_repo.py` 对每个 zip 条目分类：

- error：打包了缓存/隐藏目录、`.pyc`/`.pyo` 等编译产物、超大文件（>2MB）。
- warning：打包了测试文件、编辑器备份文件、偏大文件（>200KB）。

`--check` 只对 error 非零退出；`--strict` 对 warning 也非零退出。发行包应尽量排除 `tests/` 与开发用文件（`build_packages.py` 默认已排除 `tests/`、缓存与 `.git`）。

## 内置插件与市场同步

只有同时出现在 `plugins/<name>/` 与 `plugin-repo/plugins/*/<name>/` 的插件需要保持同步。以 `order_ledger` 为例，两处 `plugin.json` 应完全一致；市场提供安装分发，内置目录用于框架默认可用与仓库级测试。

## 注册表元数据

`registry.json` 条目由构建脚本自动生成，除基础字段外包含：

| 字段 | 说明 |
|---|---|
| `api_version` | 插件 API 版本；非 1 的插件市场禁止安装 |
| `dependencies` | 依赖声明（名称 → 版本范围），市场页展示 |
| `tags` | 标签（默认取分类），市场页展示 |
| `released_at` | 发布日期（插件 manifest 可填，留空则不展示） |
| `checksum` | 插件包 SHA-256，安装前强制校验，不匹配拒绝安装 |

安装器校验顺序：`checksum` → `api_version` → 清单字段 → 路径穿越；校验失败即拒绝。
