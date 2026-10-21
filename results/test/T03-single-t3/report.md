# T03: Portfolio and order pages slow, users logged out

**Outcome:** conclusive. Root cause: `config_change` on **postgres-orders**, triggered by `chg:2519`

## Summary

At 09:31 UTC a config reload on postgres-orders doubled work_mem (4 MB → 8 MB). Within ~40 minutes the database’s per‑query memory usage grew, exhausting connection slots and driving CPU to 100 %. The positions query used by portfolio-service slowed from ~20 ms to >1.8 s, causing massive cache‑misses, 2‑second SQL timeouts, and downstream 502/503 errors on /v1/portfolio. Connection‑slot exhaustion also produced FATAL errors. Some users were logged out because the edge‑gateway timed out while stalled on portfolio calls.

## Hypotheses

### 1. `config_change` on **postgres-orders**, triggered by `chg:2519` (HYP-1)

Confidence 0.78 (high). Increasing work_mem doubles per‑query memory allocation. Concurrent portfolio-service queries (positions) now consume more RAM, hitting max_connections limit, causing connection‑slot FATAL errors and CPU saturation. Slow queries exceed the 2 s client timeout, leading to cache‑miss storms and downstream 502/503 errors.

**Supporting:**
- Portfolio-service begins seeing massive cache‑misses for positions at 10:13:01 UTC (≈1,800/min) and falls back to postgres-orders. (`log:4c3c36a1bb07`)
- Portfolio-service reports SQL timeout (2000 ms) on postgres-orders from 10:16:01 UTC onward (≈600 errors). (`log:1b4046047da5`)
- Postgres-orders logs show the positions query taking ~1.8 s from 10:14:01 UTC (≈1,260 occurrences). (`log:d9900d4bc11e`)
- Postgres-orders emits FATAL: remaining connection slots are reserved… from 10:16:25 UTC (≈350 occurrences). (`log:e1265c62e747`)
- CPU utilisation on postgres-orders jumps from baseline 0.34 to ~1.0 (last minute 0.977). (`metric:postgres-orders/cpu_util`)
- Active connections rise from baseline ~73 to ~165 (last minute). (`metric:postgres-orders/active_connections`)
- p99 query latency climbs from baseline ~18 ms to ~681 ms (last minute). (`metric:postgres-orders/query_latency_p99_ms`)
- Config change on postgres-orders at 09:31:44 UTC raised work_mem from 4 MB to 8 MB (reload). (`chg:2519`)
**Assumptions:**
- ASM-1: Raising work_mem from 4 MB to 8 MB increases per‑query memory consumption enough to exhaust max_connections slots and drive CPU higher.

### 2. `capacity_saturation` on **postgres-orders** (HYP-2)

Confidence 0.18 (low). A sudden surge of portfolio requests overwhelms the positions table, exhausting connections and CPU independent of any config change.

**Supporting:**
- CPU utilisation on postgres-orders jumps from baseline 0.34 to ~1.0 (last minute 0.977). (`metric:postgres-orders/cpu_util`)
- Active connections rise from baseline ~73 to ~165 (last minute). (`metric:postgres-orders/active_connections`)
- p99 query latency climbs from baseline ~18 ms to ~681 ms (last minute). (`metric:postgres-orders/query_latency_p99_ms`)
- Portfolio-service begins seeing massive cache‑misses for positions at 10:13:01 UTC (≈1,800/min) and falls back to postgres-orders. (`log:4c3c36a1bb07`)
**Contradicting:**
- Config change on postgres-orders at 09:31:44 UTC raised work_mem from 4 MB to 8 MB (reload). (`chg:2519`)
- Orders-service shows a few slow SELECT on orders (~223 ms) between 09:51‑10:20 UTC – modest compared to positions query. (`log:3d03e926d542`)
**Assumptions:**
- ASM-2: No external traffic surge occurred in the 10:00‑10:45 window that could independently explain the connection‑count jump.

### 3. `resource_exhaustion` on **postgres-orders** (HYP-3)

Confidence 0.07 (low). Frequent checkpoints cause I/O contention, raising CPU and latency, leading to the observed symptoms.

**Contradicting:**
- Postgres-orders logs show the positions query taking ~1.8 s from 10:14:01 UTC (≈1,260 occurrences). (`log:d9900d4bc11e`)
- CPU utilisation on postgres-orders jumps from baseline 0.34 to ~1.0 (last minute 0.977). (`metric:postgres-orders/cpu_util`)
- Active connections rise from baseline ~73 to ~165 (last minute). (`metric:postgres-orders/active_connections`)
- p99 query latency climbs from baseline ~18 ms to ~681 ms (last minute). (`metric:postgres-orders/query_latency_p99_ms`)
- Config change on postgres-orders at 09:31:44 UTC raised work_mem from 4 MB to 8 MB (reload). (`chg:2519`)
**Assumptions:**
- ASM-3: The checkpoint‑frequency warning at 09:33 UTC is a pre‑existing condition, not the proximate cause of the 10:13‑10:45 collapse.

### 4. `dependency_degradation` on **auth-service** (HYP-4)

Confidence 0.02 (low). Auth-service failure forces logouts; portfolio slowness is a side‑effect of re‑auth traffic.

**Contradicting:**
- Portfolio-service begins seeing massive cache‑misses for positions at 10:13:01 UTC (≈1,800/min) and falls back to postgres-orders. (`log:4c3c36a1bb07`)
- Portfolio-service reports SQL timeout (2000 ms) on postgres-orders from 10:16:01 UTC onward (≈600 errors). (`log:1b4046047da5`)
- Postgres-orders logs show the positions query taking ~1.8 s from 10:14:01 UTC (≈1,260 occurrences). (`log:d9900d4bc11e`)
- Postgres-orders emits FATAL: remaining connection slots are reserved… from 10:16:25 UTC (≈350 occurrences). (`log:e1265c62e747`)
- CPU utilisation on postgres-orders jumps from baseline 0.34 to ~1.0 (last minute 0.977). (`metric:postgres-orders/cpu_util`)
- Active connections rise from baseline ~73 to ~165 (last minute). (`metric:postgres-orders/active_connections`)
- p99 query latency climbs from baseline ~18 ms to ~681 ms (last minute). (`metric:postgres-orders/query_latency_p99_ms`)

## Recommended actions

| Urgency | Kind | Action | Why |
|---|---|---|---|
| now | mitigate | Rollback work_mem on postgres-orders to 4 MB and reload. | Config change is the strongest candidate; rollback is immediate and reversible. |
| now | mitigate | Temporarily increase max_connections (or superuser_reserved_connections) on postgres-orders. | Alleviates ongoing connection‑slot FATAL errors while rollback propagates. |
| soon | investigate | Capture pg_stat_statements for the positions query before and after rollback; compare planner choices. | Provides concrete proof that work_mem altered the execution plan. |
| later | fix | Add pre‑deploy guard: any work_mem (or similar memory‑affecting) change must pass a load‑test or canary on a read‑replica. | Prevents recurrence of memory‑induced saturation. |
| later | prevent | Review and size max_connections relative to peak connection count plus headroom for memory‑heavy queries. | Ensures DB can absorb similar spikes without slot exhaustion. |
| later | prevent | Enable alerting on postgres-orders/cpu_util > 0.85 AND active_connections > 1.5× baseline with a 2‑minute evaluation window. | Gives earlier warning before user‑visible impact. |

## Evidence gaps

- **query_logs** (auth-service, edge-gateway (WARN/ERROR) 09:30‑10:45 UTC): Needed to confirm or rule out auth‑service failure as cause of logouts.
- **query_logs** (postgres-orders pg_stat_statements / EXPLAIN ANALYZE for positions query): To verify whether work_mem change altered the query plan (e.g., hash‑join spill).
- **get_change_history** (postgres-orders max_connections, superuser_reserved_connections settings): To prove connection‑slot exhaustion mechanism.
- **query_metrics** (portfolio-service request rate (RPS) 09:30‑10:45 UTC): To definitively rule out a traffic surge (H2).
- **get_change_history** (postgres-orders checkpoint‑related config before 09:30 UTC): To ensure no other config tweak contributed.

## Open questions

- Exact mechanism: does larger work_mem cause the planner to pick a hash‑aggregate that spills to temporary files, driving CPU, or does it simply increase per‑connection memory pressure leading to OOM‑style throttling?
- Why is there a ~40‑minute latency between the config reload (09:31) and the first symptom (10:13)? Could be gradual connection‑pool growth as services re‑establish pools after the reload.
- Root cause of user logouts: were they a direct result of gateway timeouts, or did the gateway drop sessions because it could not reach auth‑service while busy on portfolio calls? (Need auth‑service & edge‑gateway logs.)
- Replica fail‑over feasibility: responder asked about failing over to the replica; replication lag stayed <1 s but we have not verified the replica carries the same work_mem setting.

## How the investigation ran

Stopped because the agent finished its investigation, after 1 round(s): 8 model calls, 6 tool calls, 53,519 tokens, 278 s.
