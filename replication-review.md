# Replication Feature Review

/**
 * Module: replication-review.md
 * Purpose: Detailed review of the replication feature implementation, risks, and fixes.
 * Author: Ravi Sharma
 * Copyright (c) 2026 Ravi Sharma
 * SPDX-License-Identifier: MIT
 */

## Overview
The replication feature in this project is implemented as a **live CDC (Change Data Capture) pipeline** from SQL Server to PostgreSQL. While the UI displays "Preview feature" warnings, the underlying implementation is functional and uses real-time metrics rather than dummy values.

---

## 1. Dashboard Analysis
### KPI Cards & Information
- **Data Veracity**: The KPI cards (**Active Streams**, **Commands Captured**, **Commands Applied**, **Queue Depth**) are **NOT dummy values**. They are fetched from the server via `/api/replication/summary` and `/api/replication/streams/{id}/details`.
- **Live Updates**: The UI implementation (`replication-page.tsx` and `replication-detail-page.tsx`) uses a polling mechanism (every 3-4 seconds for active streams) to refresh metrics from the backend.
- **Data Source**: The backend metrics are sourced directly from the `ReplicationRuntimeManager`, which tracks in-memory state for active `CaptureAgent` and `ChangeApplier` instances.

---

## 2. Implementation Review

### Core Components
| Component | Implementation Class | Responsibility |
| :--- | :--- | :--- |
| **Capture** | `CaptureAgent` | Orchestrates the polling loop for SQL Server CDC tables. |
| **Provider** | `SqlServerCdcProvider` | Reads `cdc.fn_cdc_get_all_changes_*` and maps to `ChangeEvent`. |
| **Queue** | `InMemoryChangeBus` | Bounded `asyncio.Queue` (default 2000 events) providing backpressure. |
| **Apply** | `ChangeApplier` | Executes idempotent SQL on the target PostgreSQL database. |
| **Deduplicator** | `Deduplicator` | Ensures exactly-once delivery using LSN-based caching. |

### Handling of Data Changes (I/U/D)
- **INSERT**: Handled via an **idempotent UPSERT** (`INSERT ... ON CONFLICT DO UPDATE SET ...`). This ensures that if an insert is retried, it simply refreshes the existing row.
- **UPDATE**: Also handled via the same **UPSERT** logic. The `SqlServerCdcProvider` captures the "after-image" (op-code 4) from SQL Server, and the applier applies it to PostgreSQL.
- **DELETE**: Handled via `DELETE FROM ... WHERE ...` using the primary key columns.
- **Deduplication**: Every event is checked against a `Deduplicator` (using LSN or a synthetic content-based key) before application to prevent duplicate processing.

### Queuing Mechanism
- **Mechanism**: The default queue is an in-process `asyncio.Queue` (via `InMemoryChangeBus`).
- **Backpressure**: When the queue reaches its limit (controlled by `REPLICATION_QUEUE_SIZE`), the `CaptureAgent` will block on `publish()`, effectively slowing down the capture from SQL Server until the applier catches up.
- **Durability**: The default queue is **volatile**. If the API process restarts, any events currently in the queue (up to 2000) that haven't been applied will be lost (though they would be re-captured upon restart if the checkpoint hasn't advanced).

---

## 3. Critical Issues & Risks

### 1. ChangeApplier Argument Bug (High Risk)
In `apps/replicator/apply/applier.py`, the `apply` method passes a `dict` as the second argument to `self._conn.execute(sql, params)`.
```python
# Current (Buggy)
sql, params = self._build_upsert(event, ...)
await self._conn.execute(sql, params) 
```
**Issue**: `asyncpg` (used for the target connection) does not support passing a `dict` for positional `$1, $2` placeholders. It expects separate positional arguments or a list/tuple. This will cause a runtime exception when the first replication event is applied.

### 2. Single-Process Runtime Volatility
The replication runtime exists entirely within the API process memory.
- **Restart Impact**: If the API restarts, all active streams are lost from the `RuntimeManager`. They appear as "IDLE" or "STOPPED" in the UI and must be manually restarted.
- **Queue Loss**: Any un-applied events in the `InMemoryChangeBus` are lost on restart.

### 3. Volatile Deduplication
By default, the `Deduplicator` uses an in-memory `OrderedDict`. 
- **Risk**: Upon restart, the "already applied" memory is cleared. If the capture process restarts from an older LSN (before the last saved checkpoint), it may attempt to re-apply events, relying solely on the idempotency of the UPSERT (which works for I/U but might cause issues with interleaved Deletes).

### 4. Hardcoded Lowercasing
The `ReplicationChangeConsumer` forces all table names to lowercase for the target:
```python
event.table_name = event.table_name.lower()
```
While standard for PostgreSQL, this might conflict with specific user schemas that rely on quoted case-sensitive identifiers.

---

## 4. Workarounds & Recommendations

### Fix for the Applier Bug
The `apply` method should be updated to unpack the parameter values:
```python
# Recommended Fix in apps/replicator/apply/applier.py
await self._conn.execute(sql, *params.values())
```
*(Note: Since Python 3.7+, dict insertion order is preserved, so `params.values()` will match the `$1, $2` order defined in `_build_upsert`).*

### Persistence Enhancements
1. **Durable Queuing**: Configure `REPLICATION_RABBITMQ_URL` in the environment. The system already has a `RabbitMqBridgeConsumer` implemented but it is only enabled if the URL is present.
2. **Persistent Dedup**: Provide a Redis client to the `Deduplicator` to ensure LSN history survives API restarts.

### High Availability
Move the `ReplicationRuntime` out of the API process into a dedicated worker service (using the provided `apps/worker` or a custom replicator container) to decouple data movement from API lifecycle.

---
**Status**: The replication feature is architecturally sound but currently limited by its in-process nature and the specific `asyncpg` argument bug identified above.
