# order_ledger 插件（订单管理与记账，OFbot 重写版）

将旧版 OFbot（NoneBot2 / OneBot v11 单群记账机器人）重写为 OFbot2 的声明式插件，
适用于任意订单/记账场景（代打、代购、拼单等均可）：
订单录入 / 查询 / 接单 / 完成 / 取消接单 / 备注 / 改价 / 删除订单 / 标记急单 /
统计 / 导出 / 分账 / 分账历史 / 排行 / 个人账目，以及未接单提醒、每日/每周分账总结、
月度归档等定时任务。

## 安装与启用

本插件内置在 OFbot2 仓库，并已收录插件市场（`general` 分类）。两种安装方式：

```powershell
# 方式一：仓库内置（本目录即插件源码）
# 在 config.yaml 的 plugins 段启用：
#   plugins:
#     order_ledger: true

# 方式二：从插件市场安装（默认未启用，安装后需在 Web「插件」页启用）
py -m app.cli plugin repo install order_ledger
```

启动后在 Web「监听环境」页把群加入白名单，并确认
`order_ledger.order / order_ledger.stats / order_ledger.tasks` 功能开启（默认开启）。
管理员角色在 Web「角色管理」页为 QQ 分配 `admin` 或 `superadmin`
（`order_ledger.admin` 权限通过 `permission_roles` 只授予这两个角色）。

> 说明：插件的 `/统计`、`/分账` 命令与市场插件 `stats`（别名「统计」）、`commission`
> （别名「分账」）存在命令冲突。得益于 v1.4 的冲突解决策略，共存时后加载插件自动
> 命名空间化（如 `order_ledger.分账`），不会加载失败；只启用本插件时 `/分账`、`/统计`
> 保持原名。详见问题文档 I-13。

## 配置（config_schema）

Web 插件页「插件配置」可直接编辑（也可编辑 `config.yaml` 的 `plugin_configs.order_ledger`）：

```yaml
plugin_configs:
  order_ledger:
    commission_ratio:
      打手: 0.69
      接单人: 0.26
      OF: 0.0
      应急公款: 0.05
    order_settings:
      overdue_days: 3          # 已接单超时还原天数
      no_take_remind_hours: 2  # 未接单提醒阈值（小时）
      page_size: 5             # 查询分页
    notify_groups: []          # 定时任务通知群；空 = 所有启用本插件功能的群
    weekly_start_day: 5        # 本周起始日：0=周一 … 5=周六（旧群习惯）6=周日
    archive:
      enabled: true
      months: 3                # 归档多少个月之前的已完成订单
    tasks:
      no_take_remind: {enabled: true}
      daily_commission: {enabled: true, export: false}
      weekly_commission: {enabled: true}
      monthly_archive: {enabled: true}
```

> `commission_ratio` 四项之和需为 1（允许 ±0.001 误差），分账时会做对账校验。
> 任务开关也可在 Web「定时任务」页操作；任务 cron 支持配置模板（v1.4+）：
> 把 `plugin.json` 中任务参数写成 `"cron": "${tasks.daily_commission.cron}"`，
> 即可在插件配置里动态改时间，保存配置后自动重载生效。

## 设计要点（去专有化）

旧版写死在代码/配置里的内容，本插件全部改为通用配置或交由 OFbot2 框架管理：

| 旧版专有项 | 重写后的处理 |
| --- | --- |
| 固定分账比例（打手 69% / 接单人 26% / OF 0% / 应急公款 5%） | `commission_ratio` 配置，Web 修改后自动重载 |
| 固定 QQ 管理员/超级管理员列表 | Web「角色管理」按 QQ 分配 user/operator/admin/superadmin |
| 固定群白名单 | Web「监听环境」/ system 插件白名单管理 |
| 固定通知群 `SUMMARY_TARGET` | `notify_groups` 配置；留空则发给所有启用功能的群 |
| 固定定时任务时间与硬编码循环 | `plugin.json` 声明式任务（可 Web 启停），cron 可配置模板化 |
| 「本周」从周六起算的群习惯 | `weekly_start_day` 配置（默认 5 = 周六） |
| 固定「确认/完成」无斜杠触发 | 保留为监听器（`GroupMessageReceived` + 正则规则） |

## 指令

### 基础（群内全部成员）

| 指令 | 说明 |
| --- | --- |
| `/录入 <单子信息> <控分0/1> <控dx0/1> <成绩图0/1> <价格> [备注]` | 录入订单（多词信息/备注可用引号包裹） |
| `/查询 [筛选] [时间] [页码]` | 筛选：未接单/已接单/已完成/已取消/我的/急单/进行中/全部 |
| `/接单 <序号>` | 接单 |
| `/完成 <序号>` 或 `/确认 <序号>` | 确认完成（发单人/打手/管理员）；群内直接发「确认 5」也兼容 |
| `/我的订单` | 查看我的接单/发布 |
| `/取消接单 <序号>` | 取消已接订单 |
| `/备注 <序号> <内容>` | 修改备注（发单人/管理员） |
| `/改价 <序号> <价格>` | 改价（发单人/管理员） |
| `/排行 [时间] [类型]` | 接单数/派单数/总收益 Top10 |
| `/账目 [时间]` | 个人分账历史 |
| `/插件说明` | 本插件帮助（含当前分账比例） |
| `/订单状态` | 本群订单统计 |

### 管理员（admin / superadmin 角色）

| 指令 | 说明 |
| --- | --- |
| `/删除订单 <序号>` | 删除订单 |
| `/标记急单 <序号>` | 标记急单 |
| `/导出订单 [时间]` | 导出 Excel（发送文件） |
| `/分账 [时间]` | 立即分账并保存历史（默认昨日） |

### 时间参数

`本日 / 今日 / 昨日 / 本周 / 全部 / YYYYMMDD / YYYYMMDD YYYYMMDD`，适用于
`/查询 / 统计 / 导出订单 / 分账 / 分账历史 / 排行 / 账目`。

## 定时任务（北京时间）

| 任务 | 默认时间 | 说明 |
| --- | --- | --- |
| `no_take_remind` | 每小时 | 超时还原 + 未接单提醒 |
| `daily_commission` | 每日 01:00 | 昨日分账总结（可选自动导出） |
| `weekly_commission` | 每周六 01:00 | 上周分账总结 |
| `monthly_archive` | 每月 1 日 02:00 | 归档旧订单到 `data/archives/` |

## 数据与迁移

- 订单与分账历史存入 OFbot2 SQLite（表 `order_ledger_orders`、
  `order_ledger_commission_history`），与其他插件/框架数据同库。
- 从旧 OFbot 迁移订单（保留固定序号）：

```powershell
py plugins/order_ledger/scripts/import_old_data.py --file "旧版/data/orders/order_ledger.json" --group 1036036588
```

## 开发验证

```powershell
py -m app.cli plugin check order_ledger
py -m pytest plugins/order_ledger/tests -q
py scripts/e2e_order_ledger_smoke.py
```

## 与旧版的能力差异

- 新增：多群独立数据（按 `group_id` 隔离，序号按群分配）、Web 可视化配置/角色/功能开关。
- 移除：`/添加管理员`、`/删除管理员`、`/添加白名单群`、`/删除白名单群`、
  `/开机`、`/关机`、`/重启`、`/清理缓存`（均由 OFbot2 Web/CLI 与 system 插件承担）。
- 长消息不再转图片，改为自动分片发送（框架无文本转图能力，见问题文档）。
