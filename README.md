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

## 种子投影流

- **member_profile**：会员档案变更（`member_id`，字段 `display_name` / `tier` / `region`）
- **store_archive**：门店档案变更（`store_id`，字段 `name` / `status` / `city`）
- **channel_attr**：渠道属性变更（`channel_code`，字段 `label` / `active`）

底座默认按 **事件 seq 升序** 投影；乱序缓冲表空挂，深逻辑留给后题。对外文案不用「工单」「CRM」。

## 技术栈

Python 3.12 + FastAPI + SQLite；Vue 3 + Vite + Nginx。

## 0-1 切口（未实现，见出题规划）

`arrival_vs_event_order` / `ooo_window` / `event_idempotency` / `tombstone_policy` / `watermark_rewind` / …
