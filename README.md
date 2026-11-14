# 04-changecast（变投影）

Changecast — 变更日志投影：源变更流 → 按序投影 → 乱序/晚到策略钩子 → 快照可查互证。

与 Feedstitch（多源 Feed 归并）、Batchgate（作业依赖编排）、Syncledger（双端对账）主链路不同。夹具全本地，不连活库。

## 启动

```bash
docker compose up --build
```

| 入口 | 地址 |
| --- | --- |
| 前端 | http://localhost:5400 |
| API | http://localhost:10400 |

## 主链

配置投影流 → 读取 CDC 夹具并按 seq 应用到投影表 → 批次计数与快照互证

## 投影切面固化（快照一致性）

「投影快照」展示实时投影；「投影切面」把某一时刻的投影**固化**为可事后复证的静态行集合。

- **明确绑定**：切面必须且只能绑定一个明确水位 seq，或一个已成功批次号（非 completed 批次拒绝）。
  协议落在 `snapshot_cuts.bound_watermark_seq` / `bind_batch_no`。
- **行集合**：每行记录实体键、`applied_seq`、删除态与载荷摘要（SHA-256 规范化 JSON）。
  行数、存活/已删必须与绑定水位下的查询一致；`GET /api/cuts/{id}/verify` 会按事件日志重放该水位再逐行比对。
- **同流互斥**：切面固化进行中，同流常规应用的策略先持久化在切面元数据中（`policy`），只有两种：
  - `reject_apply`：拒绝应用开跑直至切面完成或失败（HTTP 409）。
  - `snapshot_read`：允许应用开跑，但切面在**单一已提交快照**中读取（WAL 快照事务），
    读不到本趟未提交的半截投影；`snapshot_watermark_seq` 写明所读快照点。
- **失败不留半截**：任一步失败都把切面标为 `failed`、删除其 `cut_rows`、清空成功计数与快照点；
  进程重启会把遗留的 `running` 切面收敛为 `failed`。失败切面不可被核验为成功。
- **页面**：`/cuts` 可选「明确水位 / 已成功批次号」发起固化，观察同流并发状态，
  并同时看到绑定水位、快照读点、行数与存活/已删的「切面记录 vs 按水位重放」对账。

> 由 `app/engines/cut.py`（按水位重放）与 `app/services/cut_service.py`（绑定、快照读、互斥、失败收敛）实现。
> 互斥基于 `stream_ops` 操作标记，在同一个 `BEGIN IMMEDIATE` 串行写事务中判定，无「检查—开跑」竞态窗口。

## 种子投影流

- **member_profile**：会员档案变更（`member_id`，字段 `display_name` / `tier` / `region`）
- **store_archive**：门店档案变更（`store_id`，字段 `name` / `status` / `city`）
- **channel_attr**：渠道属性变更（`channel_code`，字段 `label` / `active`）

底座默认按 **事件 seq 升序** 投影；乱序缓冲表空挂，深逻辑留给后题。对外文案不用「工单」「CRM」。

## API 摘要（切面）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/cuts` | 固化切面。body：`stream_id` + `watermark_seq` 或 `batch_no`（二选一）、`policy`、`hold_ms`、`note` |
| `GET` | `/api/cuts?stream_id=` | 切面历史 |
| `GET` | `/api/cuts/{id}` | 切面详情与行 |
| `GET` | `/api/cuts/{id}/verify` | 按绑定水位重放并逐行比对 |
| `GET` | `/api/concurrency?stream_id=` | 同流进行中的固化/应用标记 |
| `POST` | `/api/project` | 常规应用；可选 `up_to_seq` 截断、`hold_ms` 在提交前停顿（演示并发） |

## 技术栈

Python 3.12 + FastAPI + SQLite；Vue 3 + Vite + Nginx。

## 0-1 切口（未实现，见出题规划）

`arrival_vs_event_order` / `ooo_window` / `event_idempotency` / `tombstone_policy` / `watermark_rewind` / …
