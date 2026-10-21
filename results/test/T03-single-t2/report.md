# T03: Portfolio and order pages slow, users logged out

**Outcome:** conclusive. Root cause: `config_change` on **postgres-orders**, triggered by `chg:2519`

## Summary

At 09:31 UTC a DBA raised postgres‑orders.work_mem from 4 MiB to 8 MiB (chg:2519). Within ~40 min CPU, active connections and query latency rose sharply. By 10:13 UTC portfolio‑service began a massive cache‑miss storm for position data, forcing direct DB reads. The positions query (SELECT * FROM positions WHERE account_id = $1) slowed to ~1.8 s, exceeding the 2 s client timeout and producing thousands of timeout errors. Slow queries held connections open, exhausting the pool; PostgreSQL then emitted “remaining connection slots are reserved…” errors. Downstream callers (portfolio‑service, orders‑service) returned 5xx/502 and some users were logged out. The config change, combined with pre‑existing checkpoint pressure, pushed the primary over its memory/connection ceiling.

## Hypotheses

### 1. `config_change` on **postgres-orders**, triggered by `chg:2519` (HYP-1)

Confidence 0.55 (medium). Increasing work_mem doubles per‑query memory allocation. Under existing load the extra memory pushes the server toward its max_connections memory limit, causing queries to run slower (more paging/CPU) and connections to stay open longer, exhausting the pool and generating timeout errors.

**Supporting:**
- postgres‑orders logs show the positions query taking ~1.8 s from 10:14:01 UTC (1 050 occurrences). (`log:d9900d4bc11e`)
- postgres‑orders emits “FATAL: remaining connection slots are reserved for non‑replication superuser connections” from 10:16:25 UTC (302 occurrences). (`log:e1265c62e747`)
- Metrics for postgres‑orders (09:28‑10:40) vs baseline: cpu_util mean 0.58 (baseline 0.34), last 0.95; active_connections mean 118 (baseline 73), last 175; query_latency_p99_ms mean 330 ms (baseline 17.5 ms), last 1 067 ms; replication_lag_s slight rise. (`metric:postgres-orders/cpu_util`, `metric:postgres-orders/active_connections`, `metric:postgres-orders/query_latency_p99_ms`, `metric:postgres-orders/replication_lag_s`)
- Config change on postgres‑orders at 09:31:44 UTC raising work_mem from 4 MiB to 8 MiB (reload). (`chg:2519`)
- Dependency graph shows portfolio‑service → postgres‑orders (SQL, hard, 2 s timeout) and orders‑service → postgres‑orders (SQL, hard, 2 s timeout). (`dep:portfolio-service->postgres-orders`, `dep:orders-service->postgres-orders`)
**Contradicting:**
- postgres‑orders warns “checkpoints are occurring too frequently (≈28 s apart)” already at 09:33 UTC (3 occurrences). (`log:5dc98c9be4d4`)
**Assumptions:**
- ASM-1: work_mem reload applies instantly to all new backend processes.
- ASM-2: The 4 MiB → 8 MiB increase raises per‑query memory enough to hit the max_connections memory ceiling under observed concurrency.

### 2. `capacity_saturation` on **postgres-orders** (HYP-2)

Confidence 0.35 (low). A sudden traffic surge (unobserved) caused a burst of cache misses, driving many more concurrent position queries. The fixed connection pool could not absorb the added load once queries slowed, leading to pool exhaustion and timeouts.

**Supporting:**
- portfolio‑service logs start showing “cache miss for positions:<account>; loading from postgres‑orders” at 10:13:01 UTC (1 604 occurrences). (`log:4c3c36a1bb07`)
- Metrics for postgres‑orders (09:28‑10:40) vs baseline: cpu_util mean 0.58 (baseline 0.34), last 0.95; active_connections mean 118 (baseline 73), last 175; query_latency_p99_ms mean 330 ms (baseline 17.5 ms), last 1 067 ms; replication_lag_s slight rise. (`metric:postgres-orders/cpu_util`, `metric:postgres-orders/active_connections`, `metric:postgres-orders/query_latency_p99_ms`, `metric:postgres-orders/replication_lag_s`)
- Dependency graph shows portfolio‑service → postgres‑orders (SQL, hard, 2 s timeout) and orders‑service → postgres‑orders (SQL, hard, 2 s timeout). (`dep:portfolio-service->postgres-orders`, `dep:orders-service->postgres-orders`)
**Contradicting:**
- No other deploys, feature‑flag changes, secret rotations or infra work for the four services in the 08:00‑10:40 window. (`chg:2519`)
- orders‑service reports a few slow queries on the orders table (≈223 ms) between 09:51‑10:20 UTC. (`log:3d03e926d542`)
**Assumptions:**
- ASM-3: Portfolio‑service cache‑miss rate is driven primarily by external request volume, not by DB latency.
- ASM-4: Connection pool sizes for portfolio‑service and orders‑service are static (≈150‑200).

### 3. `code_regression` on **postgres-orders** (HYP-3)

Confidence 0.20 (low). An automatic ANALYZE updated planner statistics, causing the positions query to choose a sequential scan instead of an index scan, inflating latency to ~1.8 s and cascading into connection‑pool exhaustion.

**Supporting:**
- postgres‑orders logs show the positions query taking ~1.8 s from 10:14:01 UTC (1 050 occurrences). (`log:d9900d4bc11e`)
- Metrics for postgres‑orders (09:28‑10:40) vs baseline: cpu_util mean 0.58 (baseline 0.34), last 0.95; active_connections mean 118 (baseline 73), last 175; query_latency_p99_ms mean 330 ms (baseline 17.5 ms), last 1 067 ms; replication_lag_s slight rise. (`metric:postgres-orders/cpu_util`, `metric:postgres-orders/active_connections`, `metric:postgres-orders/query_latency_p99_ms`, `metric:postgres-orders/replication_lag_s`)
**Contradicting:**
- Config change on postgres‑orders at 09:31:44 UTC raising work_mem from 4 MiB to 8 MiB (reload). (`chg:2519`)
- No other deploys, feature‑flag changes, secret rotations or infra work for the four services in the 08:00‑10:40 window. (`chg:2519`)
**Assumptions:**
- ASM-5: An automatic ANALYZE or planner statistics update could have occurred just before 10:13, producing a worse plan for the positions query.

### 4. `dependency_degradation` on **auth-service** (HYP-4)

Confidence 0.10 (low). Downstream DB overload caused portfolio‑service to return 5xx; edge‑gateway retries auth calls, which time out, forcing users to log in again.

**Contradicting:**
- portfolio‑service logs “query on postgres‑orders timed out after 2000 ms” from 10:16:01 UTC (496 occurrences). (`log:1b4046047da5`)
- postgres‑orders emits “FATAL: remaining connection slots are reserved for non‑replication superuser connections” from 10:16:25 UTC (302 occurrences). (`log:e1265c62e747`)
**Assumptions:**
- ASM-6: Forced log‑outs are a downstream symptom of portfolio‑service failures, not a primary auth‑service problem.

## Recommended actions

| Urgency | Kind | Action | Why |
|---|---|---|---|
| now | mitigate | Rollback postgres‑orders work_mem to 4 MiB (or lower) and reload. | Config change (chg:2519) correlates with latency and connection surge; removing it should reduce memory pressure immediately. |
| now | fix | Increase max_connections on postgres‑orders or add a read replica and route portfolio‑service position reads to it. | Connection pool exhaustion (F4) is a direct symptom; more slots or a replica provides headroom. |
| soon | investigate | Enable log_min_duration_statement = 500 on postgres‑orders temporarily to capture exact query plans for the positions query. | Will confirm whether the plan changed after the config change or due to statistics drift (H3). |
| soon | fix | Run ANALYZE on the positions table and verify index on account_id is used. | If planner regression (H3) contributed, fresh stats may restore optimal plan. |
| later | prevent | Add portfolio‑service request‑rate and cache‑hit‑rate metrics with alerts on sudden cache‑miss spikes. | Early detection of traffic surges (H2) before they saturate the DB. |
| later | prevent | Review all recent PostgreSQL config changes (including checkpoint settings) and conduct capacity‑planning exercise. | Pre‑existing checkpoint pressure (F5) indicates the system was near a limit; systematic review avoids repeat. |

## Evidence gaps

- **query_metrics** (portfolio-service request rate, error rate, latency (p99) 09:30‑10:40): Metric not available in current dataset; needed to confirm traffic surge.
- **query_logs** (edge-gateway and auth-service WARN/ERROR logs 09:30‑10:40): No logs retrieved for these services; needed to verify auth cascade.
- **get_change_history** (PostgreSQL runtime settings (max_connections, shared_buffers, work_mem) and memory usage breakdown): Configuration details not captured; required to quantify memory pressure.
- **query_logs** (PostgreSQL pg_stat_activity / pg_stat_statements snapshots around 10:13‑10:20): Would reveal exact query plans and confirm planner regression.
- **query_metrics** (redis-cache hit‑rate, evictions, memory 09:30‑10:40): Cache behavior not observed; needed to understand cache‑miss driver.

## Open questions

- Did a traffic surge actually occur at ~10:12‑10:13? (missing portfolio‑service request‑rate metrics)
- What is the exact memory impact of the work_mem increase given current max_connections and shared_buffers?
- Did an automatic ANALYZE run just before 10:13, changing the positions query plan?
- Why were users logged out – is there an auth‑service error path not captured in logs?

## How the investigation ran

Stopped because the agent finished its investigation, after 1 round(s): 6 model calls, 6 tool calls, 44,593 tokens, 225 s.
