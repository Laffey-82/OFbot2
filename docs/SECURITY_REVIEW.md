# 插件安全评审清单（SECURITY_REVIEW）

合并任何 `plugin-repo/plugins/**` 投稿前，维护者须逐项检查：

## 代码执行与依赖

- [ ] 无 `eval() / exec() / __import__` 动态执行外部输入。
- [ ] 无 `subprocess` / `os.system` 调用（确有必要时须白名单 + 脱敏）。
- [ ] 依赖声明完整（`dependencies` 字段），无引入已知漏洞的包。
- [ ] 不读取/写入项目目录之外的路径（`../`、绝对路径）。

## 网络与数据

- [ ] 网络请求仅访问声明用途的地址；不向第三方明文发送 Token/密钥。
- [ ] secret（API Key / Token）不硬编码，全部走 `config_schema`。
- [ ] 群消息发送有频率限制或节流，避免触发风控与打扰。

## 平台与数据安全

- [ ] 不收集、不上传用户聊天记录等敏感数据。
- [ ] 数据模型变更必须提供迁移脚本，禁止破坏现有表。
- [ ] 命令权限点最小化，管理类操作声明 `manage_permission`。

## 自动化审计辅助

安装时框架自动执行静态审计（`PluginInstaller.audit_zip`），输出文件白名单、网络库引用、执行模式、secret 直赋与循环发送风控提示；审计记录保存在 `plugins/.audit/`，评审时可运行：

```powershell
py -m ofbot2 plugin audit plugin-repo/packages/<name>.zip
```

> 进程沙箱（限制文件系统/网络访问）列为远期选项，当前以静态审计 + 评审清单为主。
