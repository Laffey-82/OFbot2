# API 文档

> 本文件由 `scripts/gen_api_doc.py` 依据 FastAPI OpenAPI 自动生成，接口变化后请运行 `py scripts/gen_api_doc.py` 重新生成。

## 鉴权说明

- 浏览器页面路由：需登录（服务端 Session + CSRF）。
- `/api/v1/*` REST 接口：配置了 `web.api_keys` 时需请求头 `X-API-Key`；未配置时要求后台管理员登录会话。

## 接口总览

共 171 个路径。

### /

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/` | Dashboard |
| GET | `/account` | Account Page |
| POST | `/account` | Account Update |
| GET | `/ai` | Ai Page |
| GET | `/alerts` | Alerts Page |
| GET | `/api-keys` | Api Keys Page |
| GET | `/audit` | Audit Page |
| GET | `/backups` | Backups Page |
| GET | `/capabilities` | Capabilities Page |
| GET | `/commands` | Commands Page |
| GET | `/config` | Config Page |
| POST | `/config` | Config Update |
| GET | `/connections` | Connections Page |
| GET | `/executions` | Executions Page |
| GET | `/exports` | Exports Page |
| GET | `/files` | Files Page |
| GET | `/login` | Login Page |
| POST | `/login` | Login |
| GET | `/logout` | Logout |
| GET | `/logs` | Logs Page |
| GET | `/metrics` | Metrics Endpoint |
| GET | `/monitor` | Monitor Page |
| GET | `/plugins` | Plugins Page |
| GET | `/records` | Records Page |
| GET | `/roles` | Roles Page |
| GET | `/scopes` | Scopes Page |
| GET | `/self-heal` | Self Heal Page |
| GET | `/setup` | Setup Page |
| POST | `/setup` | Setup Save |
| GET | `/state-machines` | State Machines Page |
| GET | `/stats` | Stats Page |
| GET | `/tasks` | Tasks Page |
| GET | `/webhooks` | Webhooks Page |
| GET | `/workflows` | Workflows Page |

### /account

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/account/accounts/add` | Account Add |
| POST | `/account/accounts/remove` | Account Remove |

### /ai

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/ai/activate` | Ai Activate |
| GET | `/ai/agent` | Ai Agent Status |
| POST | `/ai/agent/run` | Ai Agent Run |
| POST | `/ai/config` | Ai Config |
| POST | `/ai/test` | Ai Test |

### /alerts

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/alerts/add` | Alerts Add |
| GET | `/alerts/export` | Alerts Export |
| POST | `/alerts/history/clear` | Alerts History Clear |
| POST | `/alerts/install-template` | Alerts Install Template |
| POST | `/alerts/remove` | Alerts Remove |
| POST | `/alerts/toggle` | Alerts Toggle |
| POST | `/alerts/{name}/edit` | Alerts Edit |
| POST | `/alerts/{name}/test` | Alerts Test |

### /api

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/v1/alerts` | Api Alerts |
| POST | `/api/v1/alerts` | Api Alerts Create |
| DELETE | `/api/v1/alerts/{name}` | Api Alerts Delete |
| POST | `/api/v1/alerts/{name}/toggle` | Api Alerts Toggle |
| GET | `/api/v1/backups` | Api Backups |
| POST | `/api/v1/backups` | Api Create Backup |
| GET | `/api/v1/capabilities` | Api Capabilities |
| GET | `/api/v1/metrics/history` | Api Metrics History |
| POST | `/api/v1/plugins/install` | Api Install Plugin |
| POST | `/api/v1/plugins/{name}/reload` | Api Plugin Reload |
| POST | `/api/v1/plugins/{name}/unload` | Api Plugin Unload |
| GET | `/api/v1/record-types` | Api Record Types |
| POST | `/api/v1/record-types` | Api Record Types Create |
| DELETE | `/api/v1/record-types/{name}` | Api Record Types Delete |
| GET | `/api/v1/records` | Api Records |
| POST | `/api/v1/records` | Api Records Create |
| DELETE | `/api/v1/records/{record_id}` | Api Records Delete |
| GET | `/api/v1/state-machines` | Api State Machines |
| POST | `/api/v1/state-machines` | Api State Machines Create |
| DELETE | `/api/v1/state-machines/{name}` | Api State Machines Delete |
| POST | `/api/v1/state-machines/{name}/transition` | Api State Machine Transition |
| GET | `/api/v1/status` | Api Status |
| GET | `/api/v1/tasks` | Api Tasks |
| POST | `/api/v1/tasks` | Api Tasks Create |
| DELETE | `/api/v1/tasks/{task_id}` | Api Tasks Delete |
| POST | `/api/v1/tasks/{task_id}/run` | Api Tasks Run |
| POST | `/api/v1/tasks/{task_id}/toggle` | Api Tasks Toggle |
| GET | `/api/v1/webhooks` | Api Webhooks |
| POST | `/api/v1/webhooks` | Api Webhooks Create |
| DELETE | `/api/v1/webhooks/{name}` | Api Webhooks Delete |
| GET | `/api/v1/workflows` | Api Workflows |
| POST | `/api/v1/workflows` | Api Workflows Create |
| POST | `/api/v1/workflows/{workflow_id}/run` | Api Workflow Run |

### /api-keys

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api-keys/add` | Api Keys Add |
| POST | `/api-keys/remove` | Api Keys Remove |

### /audit

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/audit/export` | Audit Export |
| POST | `/audit/export-job` | Audit Export Job |

### /backups

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/backups/auto-interval` | Backups Auto Interval |
| POST | `/backups/auto-toggle` | Backups Auto Toggle |
| GET | `/backups/compare` | Backups Compare Page |
| POST | `/backups/create` | Backups Create |
| POST | `/backups/{name}/delete` | Backups Delete |
| GET | `/backups/{name}/download` | Backups Download |
| GET | `/backups/{name}/file` | Backup File Download |
| POST | `/backups/{name}/restore` | Backups Restore |

### /commands

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/commands/export` | Commands Export |

### /connections

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/connections/add` | Connections Add |
| POST | `/connections/import-bindings` | Connections Import Bindings |
| POST | `/connections/reconnect-all` | Connections Reconnect All |
| POST | `/connections/send-test` | Connections Send Test |
| POST | `/connections/test-all` | Connections Test All |
| POST | `/connections/{conn_id}/delete` | Connections Delete |
| POST | `/connections/{conn_id}/toggle` | Connections Toggle |
| POST | `/connections/{name}/reconnect` | Connections Reconnect |
| POST | `/connections/{name}/test` | Connections Test |

### /docs

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/docs/index` | Docs Page |
| GET | `/docs/view/{name}` | Docs View |

### /executions

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/executions/export` | Executions Export |

### /exports

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/exports/bulk-delete` | Exports Bulk Delete |
| POST | `/exports/bulk-download` | Exports Bulk Download |
| POST | `/exports/create` | Exports Create |
| GET | `/exports/jobs` | Exports Jobs |
| POST | `/exports/jobs/clear` | Exports Jobs Clear |
| POST | `/exports/jobs/retry-failed` | Exports Jobs Retry Failed |
| POST | `/exports/jobs/{job_id}/retry` | Exports Jobs Retry |
| POST | `/exports/{name}/delete` | Exports Delete |
| GET | `/exports/{name}/download` | Exports Download |

### /files

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/files/bulk-delete` | Files Bulk Delete |
| POST | `/files/bulk-download` | Files Bulk Download |
| POST | `/files/upload` | Files Upload |
| POST | `/files/{name}/delete` | Files Delete |
| GET | `/files/{name}/download` | Files Download |
| GET | `/files/{name}/preview` | Files Preview |

### /health

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/health/live` | Health Live |
| GET | `/health/ready` | Health Ready |

### /monitor

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/monitor/history/export` | Monitor History Export |
| POST | `/monitor/thresholds` | Monitor Thresholds |

### /plugins

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/plugins/install` | Plugin Install Upload |
| POST | `/plugins/new` | Plugin Scaffold Create |
| GET | `/plugins/repo` | Plugin Repo Page |
| POST | `/plugins/repo/install` | Plugin Repo Install |
| POST | `/plugins/{name}/config` | Plugin Config Save |
| POST | `/plugins/{name}/load` | Load Plugin Route |
| POST | `/plugins/{name}/reload` | Reload Plugin |
| POST | `/plugins/{name}/unload` | Unload Plugin |

### /records

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/records/add` | Records Add |
| POST | `/records/bulk-delete` | Records Bulk Delete |
| POST | `/records/bulk-export` | Records Bulk Export |
| POST | `/records/create` | Records Create |
| POST | `/records/types/{name}/delete` | Records Type Delete |
| POST | `/records/{record_id}/delete` | Records Delete |
| POST | `/records/{record_id}/transition` | Records Transition |
| POST | `/records/{record_id}/update` | Records Update |

### /roles

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/roles/remove` | Roles Remove |
| POST | `/roles/set` | Roles Set |

### /scopes

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/scopes/add` | Scopes Add |
| POST | `/scopes/features/bulk` | Scopes Features Bulk |
| POST | `/scopes/{scope}/blocked/add` | Scopes Blocked Add |
| POST | `/scopes/{scope}/blocked/remove` | Scopes Blocked Remove |
| POST | `/scopes/{scope}/connection` | Scopes Connection |
| POST | `/scopes/{scope}/feature` | Scopes Feature |
| POST | `/scopes/{scope}/permission` | Scopes Permission |
| POST | `/scopes/{scope}/remove` | Scopes Remove |
| POST | `/scopes/{scope}/silent` | Scopes Silent |

### /setup

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/setup/check` | Setup Check |

### /state-machines

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/state-machines/add` | State Machines Add |
| POST | `/state-machines/{name}/delete` | State Machines Delete |

### /stats

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/stats/export` | Stats Export |

### /tasks

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/tasks/add` | Tasks Add |
| POST | `/tasks/bulk` | Tasks Bulk |
| GET | `/tasks/export` | Tasks Export |
| POST | `/tasks/plugin/{plugin}/{task_id}/toggle` | Plugin Task Toggle |
| POST | `/tasks/runs/clear` | Tasks Runs Clear |
| POST | `/tasks/{task_id}/edit` | Tasks Edit |
| POST | `/tasks/{task_id}/remove` | Tasks Remove |
| POST | `/tasks/{task_id}/run` | Tasks Run Now |
| POST | `/tasks/{task_id}/toggle` | Tasks Toggle |

### /webhook

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/webhook/{name}` | Webhook Receive |

### /webhooks

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/webhooks/add` | Webhooks Add |
| POST | `/webhooks/remove` | Webhooks Remove |
| GET | `/webhooks/{name}/history` | Webhooks History Page |
| POST | `/webhooks/{name}/history/bulk-delete` | Webhooks History Bulk Delete |
| POST | `/webhooks/{name}/history/clear` | Webhooks History Clear |
| GET | `/webhooks/{name}/history/export` | Webhooks History Export |
| POST | `/webhooks/{name}/history/{event_id}/replay` | Webhooks History Replay |

### /workflows

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/workflows/create` | Workflows Create |
| POST | `/workflows/dry-run-definition` | Workflows Dry Run Definition |
| POST | `/workflows/import-template` | Workflows Import Template |
| GET | `/workflows/runs/{run_id}` | Workflow Run Detail |
| POST | `/workflows/{workflow_id}/delete` | Workflows Delete |
| POST | `/workflows/{workflow_id}/dry-run` | Workflows Dry Run |
| GET | `/workflows/{workflow_id}/edit` | Workflow Edit Page |
| POST | `/workflows/{workflow_id}/edit` | Workflow Edit Save |
| POST | `/workflows/{workflow_id}/enable` | Workflows Enable |
| POST | `/workflows/{workflow_id}/run` | Workflows Run |
