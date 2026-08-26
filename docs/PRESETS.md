# 插件示例模板说明

示例模板目录：`examples/plugins/presets/<分类>/<名称>/`

这些模板不作为运行插件，仅供插件作者复制参考。

## 通用互动

- `dice`：掷骰子。
- `signin`：每日签到与连续天数。
- `lottery`：随机抽取。
- `poll`：创建投票与投票。

## 群管理

- `welcome`：入群欢迎。
- `keyword_reply`：关键词自动回复。
- `announcement`：向指定群发送公告。
- `points`：积分查询与发放。
- `anti_spam`：简单防刷屏。

## 信息工具

- `reminder`：延迟提醒。
- `qrcode`：生成二维码。
- `calc`：安全计算器。
- `timestamp`：时间戳与日期转换。

## 业务管理

- `order`：简化订单管理。
- `commission`：分账比例计算。
- `todo`：个人待办。
- `duty`：值班排班。

## 数据自动化

- `stats`：消息统计。
- `export`：数据导出。
- `backup`：手动备份。
- `schedule_message`：定时发送消息。

## 运维管理

- `system_status`：系统状态。
- `health_check`：健康检查。
- `audit_viewer`：审计日志。

## 安装方式

```powershell
py -m app.cli plugin new mydice --preset dice
```

示例模板已全部按**声明式 features** 编写（命令/任务/监听在 `plugin.json` 中声明）。生成插件后可按需补充能力：

```powershell
py -m app.cli plugin new my_plugin --with-task --with-listener --with-web --with-model
py -m app.cli plugin check my_plugin   # 加载前静态校验
```

完整字段说明见 [PLUGIN_MANIFEST.md](PLUGIN_MANIFEST.md)。
