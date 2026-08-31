# 贡献指南

感谢你愿意参与 OFbot 2 的开发！请先阅读 [readme.md](readme.md)、[docs/README.md](docs/README.md)
与 [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) 了解架构与插件规范。

## 环境准备

```powershell
py -m pip install -r requirements.txt
py -m pip install pytest pytest-asyncio ruff
```

要求 Python >= 3.11。建议同时安装开发依赖：`py -m pip install -e ".[dev]"`。

## 开发流程

1. Fork 仓库并创建特性分支：`git checkout -b of/your-feature`（或 `feat/` / `fix/`）。
2. 实现功能并补充测试（框架核心改动必须带单元测试）。
3. 本地通过完整门禁：

```powershell
scripts\dev.ps1 -SkipInstall
```

（等价于 compileall → ruff → pytest → e2e_smoke；涉及文档时另跑
`py scripts/check_docs_links.py`，全部通过。）
4. 提交时使用规范的提交信息（见下）。
5. 提交 Pull Request，CI 会在 GitHub Actions 自动复跑门禁；评审通过后合并。

## 提交信息格式（Conventional Commits）

格式：`<type>(<scope>): <描述>`，描述用祈使句、不超过 72 字符。

| 类型 | 用途 |
| --- | --- |
| `feat:` | 新功能 |
| `fix:` | 缺陷修复 |
| `docs:` | 文档（README、docs/、注释） |
| `refactor:` | 重构（行为不变） |
| `test:` | 测试 |
| `chore:` | 构建/工具/依赖 |
| `perf:` | 性能优化 |
| `ci:` | CI 配置 |
| `style:` | 格式（ruff 等） |
| `build:` | 打包/发布相关 |
| `revert:` | 回滚 |

示例：`feat(adapters): 支持 OneBot v12 心跳重连`、`fix(web): /tasks 页面连接泄漏`。
涉及破坏性变更时在正文说明并标注 `BREAKING CHANGE:`。

## 代码约定

- 插件只能通过 `PluginContext` 访问框架能力，不直接依赖全局单例。
- 新命令/任务/监听优先在 `plugin.json` 的 `features` 中声明（全声明式），运行时 API 仅作逃生通道。
- 消息处理必须为异步函数，耗时操作放入后台任务，避免阻塞消息循环。
- Web 页面为服务端渲染 + 原生 JS，样式使用 CSS 变量主题，不硬编码颜色。
- 保持测试全绿：新增功能同时新增 `tests/` 用例。
- 事件总线、插件沙箱等核心模块变更需附带对应的单元/集成测试。

## 文档贡献

- 修改行为时同步更新 [docs/](../docs/README.md) 与 [readme.md](readme.md) 对应段落。
- 文档以中文为主；关键入口（快速开始/安装/连接）的中英文页要保持互链。
- 新增/删除/重命名文档页时，同步更新文档导航表与 `docs/README.md`。
- 合并前确保 `py scripts/check_docs_links.py` 通过（校验链接、锚点与截图资产）。

## 插件投稿

1. 在 `plugin-repo/plugins/<分类>/<插件名>/` 下按 [docs/PLUGIN_MANIFEST.md](docs/PLUGIN_MANIFEST.md)
   声明插件（`api_version=1`、features 声明式）。
2. 本地运行：

```powershell
py plugin-repo/tools/build_packages.py
py plugin-repo/tools/build_packages.py --check
git diff --exit-code -- plugin-repo
```

3. 提交源码、`packages/*.zip` 与 `registry.json` 变更。
4. 开插件投稿 Issue（模板会自动生成）或在 PR 中说明，评审按
   [docs/SECURITY_REVIEW.md](docs/SECURITY_REVIEW.md) 执行。

## 评审期望

- 评审者核对：门禁全绿、代码约定、安全影响（鉴权/路径/注入/密钥）、测试覆盖与文档同步。
- 投稿者及时响应评审意见；CI 修复后重新请求评审。
- 保持讨论友善，遵循 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)；违反者可被关闭讨论/移除贡献。

## 报告问题

Bug 与功能建议请开 GitHub Issue（使用模板），附版本号、复现步骤、环境（Python 版本、
协议端与版本、部署方式）与日志。安全问题**不要**公开提交，走 [SECURITY.md](SECURITY.md)
私密渠道。
