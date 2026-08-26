# 插件投稿指南

## 步骤

1. Fork 主仓库，在 `plugin-repo/plugins/<分类>/<插件名>/` 下新建插件。
2. 参考现有示例（`dice`、`welcome`）与 [docs/PLUGIN_MANIFEST.md](../docs/PLUGIN_MANIFEST.md) 编写声明式清单。
3. 本地自测：把插件目录复制到 `plugins/<插件名>/` 后启用机器人，验证命令/监听行为。
4. 校验并构建产物：

```powershell
py plugin-repo/tools/build_packages.py --check
py plugin-repo/tools/build_packages.py
```

5. 提交 `plugins/`、`packages/`、`registry.json` 的变更，发起 Pull Request。

## 清单要求

- `name` 与目录名一致，小写字母开头（`a-z0-9_`）。
- `api_version` 为 `1`，`version` 为 `X.Y.Z`。
- 命令/定时任务/监听器声明在 `features` 中，`handler` 指向包内符号（如 `handlers.xxx_command`）。
- 涉及数据的插件声明 `config_schema`；涉及 Web 的插件声明 `web: true` 并注册路由。
- 每个插件附 `README.md`：功能、命令、配置、依赖。

## 质量要求

- 命令提供 `usage` / `examples`；参数尽量用声明式 `params`（类型/必填/默认/choices）。
- 不依赖框架全局单例，只通过 `PluginContext` 访问能力。
- 耗时操作放入后台任务，不阻塞消息循环。
- CI 会对 `plugin-repo/**` 变更运行校验；产物不一致会失败，请先运行构建脚本。

## 不建议投稿的内容

- 与具体账号/密钥绑定的插件（密钥应走插件 `config_schema`，由使用者填写）。
- 恶意/收集个人信息、绕过限流与权限的代码。
- 仅个人用途、无通用价值的硬编码插件。
