# schedule_message 定时播报

按 cron 定时向指定群发送消息。

- 配置：`group_id`（目标群）、`message`（播报内容）。
- 计划：默认每日 09:00（`plugin.json` 中 `features[].tasks[].params.cron`，可按需修改后重载插件）。
- 功能默认关闭：在「监听环境」页开启「定时播报」后任务才会执行（执行前还会按目标环境功能开关门控）。
