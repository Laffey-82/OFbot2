# OFbot2 插件开发问题文档

> 来源：将旧版 OFbot（NoneBot2 / OneBot v11 单群记账机器人）重写为 OFbot2 声明式插件的
> 全流程实测（2026-09-01，OFbot2 v1.3.0，Python 3.14）。
> 覆盖：插件开发、数据建模、命令声明、定时任务、Web 配置、端到端运行。
> 目的：为 OFbot2 后续开发与优化提供依据。

## 结论速览

OFbot2 **能够胜任**复杂业务插件的开发与运行：本次将旧版约 3000 行业务代码（订单/分账/
统计/排行/账目/导出/定时任务）重写为声明式插件，全部指令端到端跑通（12 条命令 + 纯文本
监听兼容 + 4 个定时任务 + Excel 导出文件发送），数据落入框架 SQLite。但过程中暴露了
**12 个影响插件开发便利性/正确性的问题**，按影响面分为 3 个高、3 个中、6 个低。

| ID | 严重度 | 问题 |
| --- | --- | --- |
| I-01 | P1 | 插件声明的权限点自动授予 user 角色，无法声明“仅管理员”权限 |
| I-02 | P1 | 声明式任务参数是静态的，cron 无法从插件配置绑定；运行时任务在 Web 任务页不可见 |
| I-03 | P1 | Web 插件配置保存不做 config_schema 校验，表单只渲染顶层字段 |
| I-04 | P2 | records 通用记录查询能力有限（无字段过滤/事务），复杂业务被迫自建模型 |
| I-05 | P2 | `ctx.register_models` 是死代码，模型注册实际依赖 `manifest.models` 模块导入 |
| I-06 | P2 | 命令参数解析没有“贪婪字符串”类型，多词自由文本参数只能手写解析 |
| I-07 | P3 | 消息发送缺少文本转图与群文件上传动作（OneBot 高级动作） |
| I-08 | P3 | 声明式 handler 无上下文注入，只能模块级全局变量，热重载有悬挂风险 |
| I-09 | P3 | 定时任务 `target=all` 只按 `group:*` 门控，无法按群精细控制 |
| I-10 | P3 | 插件配置热重载不重建任务/模型等结构性资源，部分变更需重启 |
| I-11 | P3 | 无官方插件级端到端测试工具（plugin test 仅跑 pytest） |
| I-12 | P3 | 长消息/超长参数受输入安全限制，且无分片外的展示策略 |
| I-13 | P2 | 命令名/别名全局冲突会使整个插件加载失败，通用中文别名在生态内撞车 |

---

## P1：影响插件正确性/开发主路径

### I-01 插件声明的权限点自动授予 user 角色，无法声明“仅管理员”权限

- **位置**：`app/core/plugin.py:464`
  `self.permissions.grant_role_permission("user", permission)`
- **现象**：`load_plugin()` 会把 `manifest.permissions` 中每个权限点都授予 `user` 角色。
- **影响**：命令声明 `permission: "order_ledger.admin"` 后，所有普通用户仍能通过框架的命令权限
  门禁（`commands.py` 的 `permission_manager.has_permission` 检查）。要实现“仅管理员”，
  插件必须在 handler 内自行校验角色（本次用 `principal.role in {admin, superadmin}` +
  scope 覆盖，见 `handlers.py::_is_admin`）。这不是个例——任何“分级权限”插件都会踩到。
- **建议**：`permissions` 字段支持角色映射（如 `{"order_ledger.admin": ["admin", "superadmin"]}`），
  或默认只登记不授予，由插件/Web「角色管理」显式授权。

### I-02 声明式任务参数是静态的，cron 无法从插件配置绑定；运行时任务在 Web 任务页不可见

- **位置**：`app/core/plugin.py::_register_manifest_task`（直接用 `declared.params`）；
  `app/web/routers/tasks.py::tasks_page`（`plugin_tasks` 仅来自 `task_registry.list()`）。
- **现象**：`plugin.json` 的 tasks 声明是唯一注册来源，cron/interval 全部写死；通过
  `ctx.scheduler.add_cron_job()` 动态注册的任务**不会**出现在 Web「定时任务」页，也无法
  用 Web 启停。
- **影响**：本次“去除固定时间任务”的诉求无法用声明式任务满足——要么改 `plugin.json`
  静态 cron（需重启/重载），要么放弃 Web 可视化管理。最终选择了声明式任务 + 配置里的
  `tasks.*.enabled` 开关，cron 修改仍需改 manifest。这是“配置驱动定时任务”的硬伤。
- **建议**：任务参数支持配置模板（如 `"cron": "${tasks.daily_commission.cron}"`），配置
  变更自动重注册；或将运行时任务也纳入 `PluginTaskRegistry` 与 Web 任务页（含启停、手动执行）。

### I-03 Web 插件配置保存不做 config_schema 校验，表单只渲染顶层字段

- **位置**：`app/web/routers/plugins.py::plugin_config_save`（`json.loads` 后直接保存并重载，
  无 schema 校验）；`app/web/templates/plugins.html`（`renderPluginFields` 只遍历
  `schema.properties` 一层）。
- **现象**：文档声称“config_schema 强类型校验，Web 自动生成表单”，实际保存端不校验；
  嵌套对象（如 `commission_ratio.打手`、`tasks.daily_commission.enabled`）在表单中退化为
  一整块 JSON textarea，用户改错只能在运行时暴露。
- **影响**：插件必须自己防御（本次在 `config.py::merged_config` 做深合并、分账比例在
  `Commission.validate_ratio` 运行时校验），配置体验和文档承诺不符。
- **建议**：保存时按 `config_schema` 校验并返回字段级错误；表单递归渲染嵌套 `properties`；
  校验失败的配置不重载插件。

---

## P2：影响复杂业务建模与命令声明

### I-04 records 通用记录查询能力有限，复杂业务被迫自建模型

- **位置**：`app/services/records.py::RecordService.list`（仅 `record_type/limit/offset/
  status/order`，无字段过滤与区间查询）；`update` 为整体覆盖式合并。
- **现象**：订单查询需要“状态 + 创建人 + 日期范围 + 页码 + 排序”，records 无法表达；
  接单的原子“状态检查 + 更新”也无原生支持。
- **影响**：order_ledger 最终使用自建 SQLAlchemy 模型（`plugins/order_ledger/models.py`）+ 原生查询。
  对中等复杂业务，records 只能作为“轻量记录”用。
- **建议**：`list` 增加字段过滤/区间参数（如 `filters={"status": ..., "create_time": [a, b]}`）；
  提供基于条件的原子更新；或在文档中明确 records 的适用范围与自建模型路径。

### I-05 `ctx.register_models` 是死代码；模型注册实际依赖 `manifest.models` 模块导入

- **位置**：`app/core/plugin.py:189-190`（`register_models` 仅 `self._models.extend(...)`），
  全仓库无任何消费 `_models` 的代码；真正建表靠 `manifest.models` 的模块导入
  （类定义时注册到 `Base.metadata`）+ `init_db` 的 `create_all`。
- **现象**：按 `docs/DEVELOPMENT.md` 在 `setup()` 里 `ctx.register_models(...)` 不会报错，
  但表永远不会创建——静默失败。
- **影响**：本次模型注册走的是 `plugin.json` 的 `"models": ["models"]`（有效），但文档
  示例代码是误导性的。
- **建议**：实现 `register_models` 并让 `init_db` 消费 `PluginContext._models`；或修改文档，
  明确“模型必须在 `manifest.models` 声明（模块导入即注册）”，并移除误导示例。

### I-06 命令参数解析没有“贪婪字符串”类型，多词自由文本参数只能手写解析

- **位置**：`app/core/parsing.py::bind_params`（按空白分词，`string` 参数不吞后续 token）。
- **现象**：旧版 `/录入 <单子信息> <控分> <控dx> <成绩图> <价格> [备注]` 中“单子信息”
  可能含空格、备注在尾部，声明式 params 无法表达“剩余参数合并为字符串”。
- **影响**：order_ledger 的 `/录入` 只能手写 `tokenize_args` + 自定义规则（兼容引号包裹）。
- **建议**：新增 `type: "rest"`（或 `greedy_string`）参数：位置参数模式下把剩余 token 合并
  为一个字符串；同时保持 `key=value` 命名参数可解析。

### I-13 命令名/别名全局冲突会使整个插件加载失败

- **位置**：`app/core/plugin.py::_register_declarative`（`check_conflict` 命中即抛
  `ValueError`，`load_enabled` 捕获后整插件标记 `PluginFailed`，不加载任何命令）。
- **现象**：`/统计`（stats 插件别名「统计」）、`/分账`（commission 插件别名「分账」）等
  通用中文词在生态内被多个插件占用；修复前 ofbot 与市场插件同装时直接加载失败，而非“跳过冲突命令”。
- **影响**：修复后重命名为 order_ledger 并收录进 `plugin-repo` 市场（v1.4 起加载期
  自动命名空间化共存）；插件开发者仍应使用 `plugin conflicts` 排查别名占用。
- **建议**：冲突时支持按优先级保留/跳过单个命令（记录日志），或引入插件命令命名空间
  （如 `order_ledger.统计`）与显式 `conflicts` 声明；并提供 `plugin check` 的跨插件冲突预检。

---

## P3：影响体验/便利性

### I-07 消息发送缺少文本转图与群文件上传动作

- **位置**：`app/adapters/onebot.py`（`_segment_to_onebot` 仅透传 `file` 段，无
  `upload_group_file` 动作）；框架无 text-to-image 工具（`app/services` 无 Pillow 封装）。
- **现象**：旧版帮助/长文本会转图片、导出文件走 `upload_group_file`；新版只能分片发文本，
  文件用 OneBot `file` 段（依赖 NapCat 端支持路径文件）。
- **影响**：长帮助文本体验下降（分片后多条消息）；文件上传在不同协议端行为不一致。
- **建议**：提供可选的 text2img 工具（Pillow 依赖可选），并在 OneBot 适配器实现
  `upload_group_file` 动作（NapCat 能力）。

### I-08 声明式 handler 无上下文注入，只能模块级全局变量

- **位置**：`app/core/plugin.py::resolve_dotted` + `_register_declarative`（handler 为无参
  函数签名，仅 `(event, args, command_ctx)`）。
- **现象**：所有示例插件都用模块级 `_ctx` 全局 + `setup()` 赋值；热重载时旧模块引用清理
  依赖 `unload_plugin` 的 `sys.modules` 清理，但全局变量在进程内仍可能被残留引用。
- **影响**：本次沿用该模式（`handlers.init(ctx)`），工作正常，但属易错样板代码。
- **建议**：支持 handler 参数依赖注入（如参数名为 `ctx` 时自动注入 `PluginContext`），
  或在文档中给出标准模式并保证卸载时置空。

### I-09 定时任务 `target=all` 只按 `group:*` 默认作用域门控

- **位置**：`app/core/plugin.py::_run_manifest_task`（`target=all` 只查
  `feature_enabled(plugin, feature_id, "group:*")`）。
- **现象**：任务无法逐群开关；插件要向“所有启用了功能的群”发消息，必须自己遍历
  `scope_policy.scope_keys()` 并逐个检查 `feature_enabled`（本次 `services.resolve_target_groups`）。
- **建议**：支持 `target: ["group:a", "group:b"]` 或任务级 per-group 门控。

### I-10 插件配置热重载不重建结构性资源

- **位置**：`app/web/routers/plugins.py::plugin_config_save` → `reload_plugin`；
  `app/db/base.py::init_db`（`create_all` 只在启动时执行）。
- **现象**：改配置后插件重载，handler 读到新 `ctx.config`（本次 `notify_groups` 等即时生效），
  但声明式任务 cron、模型表结构不会重建/变更（文档已说明模型不支持热更新）。
- **影响**：配置驱动的任务/模型变更必须重启；对“改配置即时生效”的预期要明确文档边界。
- **建议**：任务参数绑定配置模板后随 reload 自动重注册（与 I-02 一并解决）。

### I-11 无官方插件级端到端测试工具

- **位置**：`app/cli.py::_plugin_test`（仅 `pytest`）；`scripts/e2e_smoke.py` 为框架冒烟，
  非插件可复用夹具。
- **现象**：插件要验证真实消息流，只能自己搭假适配器（本次写了 `scripts/e2e_order_ledger_smoke.py`，
  复用 fake Chronocat + Red HTTP 捕获）。
- **建议**：提供 `tests/conftest.py` 级别的假适配器/命令注入夹具，让插件测试可直接
  断言“发命令 → 收回复”。

### I-12 长消息/超长参数受输入安全限制，且无分片外展示策略

- **位置**：`app/core/security.py`（`max_message_length=2000`、`max_arg_length=500`）；
  `app/services/preset_utils.py::split_message`（分片上限 1800）。
- **现象**：超长备注/单子信息在入站即被拒绝；长回复只能分片，无图片/文件降级策略。
- **影响**：旧版长回复转图能力丢失（见 I-07）；业务上超长输入需插件自行截断/提示。
- **建议**：与 I-07 合并考虑；文档明确各限制数值与调整入口（config 已可配）。

---

## 框架做得好的地方（实测）

- **声明式 features + 作用域开关**：命令/监听/任务自动注册，Web「监听环境」逐群三态开关
  与帮助过滤开箱即用；本次用 `group_only` 规则和 `regex` 规则分别实现了“仅群聊”和
  “无斜杠确认”兼容，工作量极小。
- **模型建表链路**：`manifest.models` 导入在 `load_enabled` 阶段完成，`init_db` 的
  `create_all` 随后建表，插件模型 + 唯一约束 + 索引工作正常（实测建出
  `order_ledger_orders` / `order_ledger_commission_history`）。
- **配置保存 → 插件重载**：Web 保存配置后 `reload_plugin` 即时生效，handler 读取新配置；
  配合 JSON Schema 描述，编辑入口可用。
- **消息模型**：`MessageSegment` 多段构造（文本 + @ + 文件）、`split_message` 分片、
  协议归一化都很顺手；OneBot 文件段在 NapCat 上可发路径文件。
- **权限/角色系统**：Web「角色管理」按 QQ 分配角色 + 作用域权限覆盖，替代了旧版
  “QQ 列表写死”的做法，superadmin 经 `basic.superusers` 配置即可。
- **端到端可测**：`scripts/fake_chronocat.py` + Red HTTP 捕获使本地全流程冒烟可行，
  无需真实 QQ（本次 12 条指令全部通过）。

---

## 后续建议优先级

1. **P0（强烈建议下一迭代做）**：I-01 权限角色映射、I-02 配置驱动任务、I-03 配置校验。
   三者共同决定“复杂业务插件能否以声明式、低样板的方式表达”。
2. **P1**：I-04 records 过滤、I-05 register_models 落地、I-06 rest 参数。
3. **P2**：I-07 文本转图/文件上传、I-09 任务按群门控、I-11 插件 e2e 夹具。
