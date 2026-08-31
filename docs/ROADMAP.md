# 修复路线图（v1.0.8 → v1.3.0）

依据 2026-08 项目审查结论（第 1/2/4/5/6/7 项；第 3 项 Agent 长期记忆为远期目标），
按「先稳后进」分四个批次推进。每批都通过全部门禁：
`compileall` + `ruff check` + `pytest` + `scripts/e2e_smoke.py`。

## 批次 1（v1.0.8）— 稳定与卫生

- [x] 第 1 项：数据库引擎/事件总线重置显式释放
  - `reset_db_engine()` 改为 async 并 `await engine.dispose()`，避免 GC 触发
    "non-checked-in connection" 警告。
  - `reset_bus()` 先 `stop(clear=True)` 再从 bubus 全局注册表摘除，消除同名告警。
  - 顺带修复真实连接泄漏：`/tasks` 页面在 `async with` 块外继续使用 session，
    每次打开任务页泄漏一条数据库连接（[tasks.py](../app/web/routers/tasks.py)）。
  - 测试警告从 20 条降为 0。
- [x] 第 7 项：日志轮转清理与配置收敛
  - `prune_log_files` 覆盖 `ofbot2-*.log*` 轮转后缀与历史遗留格式
    （`bot*.log*`、`web-*.log*`、`diag_fh.log*`、`ofbot2.log*`）。
  - 文件日志默认级别 DEBUG → INFO，降低磁盘写入。
  - `save_settings` 在 `transport.connections` 非空时不再写回旧 `red`/`onebot` 播种键，
    `config.example.yaml` 同步收敛。
- [x] 第 6 项：文档同步
  - GOALS 测试数 238 → 271，状态刷新；`docs/API.md` 重新生成；本文件即修复规划。

## 批次 2（v1.1.0）— 自研事件总线

- [x] 在 `app/core/bus.py` 实现轻量异步 pub/sub（`on` / `dispatch` / `stop`），
  按事件类型 `isinstance` 匹配（保留 `GroupPoke → NoticeReceived` 父类订阅语义）。
- [x] `BaseEvent` 改为继承 pydantic `BaseModel`，插件与订阅代码零改动。
- [x] 移除 `arm_hard_exit()` 与 `os._exit` 兜底，关闭流程只调 `await bus.stop(timeout, clear=True)`。
- [x] 从 `requirements.txt` / `pyproject.toml` 移除 bubus 依赖。
- [x] 新增高负载测试：数千事件 + 慢 handler → 关闭不阻塞、任务不泄漏。

## 批次 3（v1.2.0）— 插件审计加固 + Web E2E

- [x] 第 4a 项：插件安装 / `plugin check` 静态安全审计强化
  - 扫描 `eval/exec/subprocess/open/socket` 等高危调用，输出风险分级。
  - 依赖白名单校验；更新 `docs/SECURITY_REVIEW.md`。
- [x] 第 5 项：Playwright 浏览器端 E2E
  - `tests/e2e/` 覆盖登录 → 仪表盘 → 连接中心 → 监听环境 → 插件 → 任务 → 流程。
  - 复用 `data/fake_config.yaml` + 假 Red 服务，临时 uvicorn 随机端口；CI 新增 job。

## 批次 4（v1.3.0）— 插件子进程沙箱

- [x] `plugin.json` 新增 `sandbox: "inline" | "process"`（默认 inline 兼容存量）。
- [x] process 模式：子进程加载插件，JSON-RPC over stdio 代理 `PluginContext` 能力。
- [x] `sandbox_policy.allow_services` 能力白名单，越权调用拒绝；子进程崩溃不影响主进程。
- [x] 官方插件保持 inline；process 模式定位为第三方插件部署选项。

## 状态

- 批次 1：✅ 完成（v1.0.8）
- 批次 2：✅ 完成（v1.1.0）
- 批次 3：✅ 完成（v1.2.0）
- 批次 4：✅ 完成（v1.3.0）
