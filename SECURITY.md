# 安全说明

## 支持范围

OFbot 2 面向本地/私域部署。当前维护范围：

- `main` 分支最新提交。
- 最近一个里程碑版本（见 [docs/CHANGELOG.md](docs/CHANGELOG.md)）。

## 报告漏洞

请**不要**在公开 issue 中提交未修复的安全问题。请通过以下任一渠道私密报告：

- GitHub 仓库的 **Security → Report a vulnerability**（私有安全公告）。
- 直接联系仓库维护者。

报告内容建议包含：

- 影响版本与复现步骤；
- 漏洞类型（命令注入、路径穿越、越权、敏感信息泄露等）；
- 可能的影响面与修复建议。

我们会在确认后尽快修复，并在修复发布前对细节保密。

## 部署安全清单

- 修改默认账户 `admin/admin`，配置强 `web.secret`。
- 公网部署必须启用 HTTPS（反向代理）并按需限制访问来源。
- 插件 zip 安装属于代码执行：仅安装可信来源的插件。
- REST API 配置 `web.api_keys` 后需携带 `X-API-Key`，不要直接暴露到公网。
- 定期备份 `data/ofbot2.db` 与 `config.yaml`。
