# 贡献指南

感谢你愿意参与 OFbot 2 的开发！请先阅读 [readme.md](readme.md) 与 [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) 了解架构与插件规范。

## 环境准备

```powershell
py -m pip install -r requirements.txt
py -m pip install pytest pytest-asyncio ruff
```

要求 Python >= 3.11。

## 开发流程

1. Fork 仓库并创建特性分支：`git checkout -b feat/your-feature`。
2. 实现功能并补充测试（框架核心改动必须带单元测试）。
3. 本地通过完整门禁：

```powershell
scripts\dev.ps1 -SkipInstall
```

（等价于 compileall → ruff → pytest → e2e_smoke，全部通过。）
4. 提交时写明改动目的；如涉及文档，同步更新 `docs/` 与 [readme.md](readme.md)。
5. 提交 Pull Request，CI 会在 GitHub Actions 自动复跑门禁。

## 代码约定

- 插件只能通过 `PluginContext` 访问框架能力，不直接依赖全局单例。
- 新命令/任务/监听优先在 `plugin.json` 的 `features` 中声明（全声明式），运行时 API 仅作逃生通道。
- 消息处理必须为异步函数，耗时操作放入后台任务，避免阻塞消息循环。
- Web 页面为服务端渲染 + 原生 JS，样式使用 CSS 变量主题，不硬编码颜色。
- 保持测试全绿：新增功能同时新增 `tests/` 用例。

## 提交信息格式

建议前缀：

- `feat:` 新功能
- `fix:` 缺陷修复
- `docs:` 文档
- `refactor:` 重构（行为不变）
- `test:` 测试
- `chore:` 构建/工具

## 报告问题

Bug 与功能建议请开 GitHub Issue，附上版本号、复现步骤与日志。安全问题见 [SECURITY.md](SECURITY.md)。
