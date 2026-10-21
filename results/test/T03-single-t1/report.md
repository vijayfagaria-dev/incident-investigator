# T03: Portfolio and order pages slow, users logged out

**Outcome:** inconclusive
- the leading hypothesis has confidence 0.35, below 0.5
- HYP-1 and HYP-2 are too close to tell apart

## Summary

Around 10:12‑10:14 UTC the postgres‑orders database saturated (CPU ~100%, connections >2× baseline, query latency >60×). The dominant workload was a simple SELECT on positions executed >1k times per minute. This caused portfolio‑service timeouts and p99 latency >2.5 s, and auth‑service session loss because its Redis cache became unavailable. A config reload at 09:31:44 that doubled work_mem (chg:2519) may have contributed, but a sudden surge of concurrent reads, a missing index, or a Redis degradation are also plausible. Evidence is insufficient to single out one root cause.

## Hypotheses

### 1. `config_change` on **postgres-orders**, triggered by `chg:2519` (HYP-1)

Confidence 0.35 (low). Increasing work_mem doubled per‑query memory allocation; with many concurrent executions the instance ran out of memory, causing CPU thrashing, connection‑slot exhaustion and query timeouts.

**Supporting:**
- postgres‑orders CPU utilisation rose from baseline 0.34 to 0.95 by 10:40 UTC, first high point ~10:14. (`metric:postgres-orders/cpu_util`)
- Active connections on postgres‑orders climbed from baseline ~73 to 175 at 10:40 UTC. (`metric:postgres-orders/active_connections`)
- Query latency p99 on postgres‑orders jumped from baseline ~18 ms to 1067 ms by 10:40 UTC, first rise ~10:14. (`metric:postgres-orders/query_latency_p99_ms`)
- Postgres log shows 1050 executions of ‘SELECT * FROM positions WHERE account_id = $1’ between 10:14:01 and 10:39:59. (`log:d9900d4bc11e`)
- Postgres log reports 302 ‘FATAL: remaining connection slots are reserved for non‑replication superuser connections’ errors starting 10:16:25. (`log:e1265c62e747`)
- Config change chg:2519 at 09:31:44 raised work_mem from 4 MB to 8 MB (reload). (`chg:2519`)
**Contradicting:**
- Checkpoint frequency warnings appeared at 09:33 and 10:25. (`log:5dc98c9be4d4`)
- portfolio‑service latency p99 rose from baseline 424 ms to 2780 ms at 10:40 UTC, first rise ~10:13. (`metric:portfolio-service/latency_p99_ms`)
- portfolio‑service error rate increased from baseline 0.002 to 0.048 at 10:40 UTC. (`metric:portfolio-service/error_rate`)
- Portfolio logs show 1604 cache‑misses for positions loading from postgres‑orders starting 10:13:01. (`log:4c3c36a1bb07`)
- Portfolio logs show 496 query‑timeout errors (2000 ms) to postgres‑orders starting 10:16:01. (`log:1b4046047da5`)
**Assumptions:**
- ASM-1: The work_mem reload took effect immediately and remained at 8 MB for the incident window.
- ASM-2: The dominant SELECT on positions uses work_mem (e.g., large sorts or hash aggregates).

### 2. `capacity_saturation` on **postgres-orders** (HYP-2)

Confidence 0.30 (low). An unexpected burst of concurrent SELECT * FROM positions (e.g., a batch job or feature flag) saturated CPU and connection pool, leading to timeouts and downstream latency.

**Supporting:**
- postgres‑orders CPU utilisation rose from baseline 0.34 to 0.95 by 10:40 UTC, first high point ~10:14. (`metric:postgres-orders/cpu_util`)
- Active connections on postgres‑orders climbed from baseline ~73 to 175 at 10:40 UTC. (`metric:postgres-orders/active_connections`)
- Query latency p99 on postgres‑orders jumped from baseline ~18 ms to 1067 ms by 10:40 UTC, first rise ~10:14. (`metric:postgres-orders/query_latency_p99_ms`)
- Postgres log shows 1050 executions of ‘SELECT * FROM positions WHERE account_id = $1’ between 10:14:01 and 10:39:59. (`log:d9900d4bc11e`)
- Postgres log reports 302 ‘FATAL: remaining connection slots are reserved for non‑replication superuser connections’ errors starting 10:16:25. (`log:e1265c62e747`)
- Portfolio logs show 1604 cache‑misses for positions loading from postgres‑orders starting 10:13:01. (`log:4c3c36a1bb07`)
- Portfolio logs show 496 query‑timeout errors (2000 ms) to postgres‑orders starting 10:16:01. (`log:1b4046047da5`)
**Contradicting:**
- Config change chg:2519 at 09:31:44 raised work_mem from 4 MB to 8 MB (reload). (`chg:2519`)
- portfolio‑service latency p99 rose from baseline 424 ms to 2780 ms at 10:40 UTC, first rise ~10:13. (`metric:portfolio-service/latency_p99_ms`)
- portfolio‑service error rate increased from baseline 0.002 to 0.048 at 10:40 UTC. (`metric:portfolio-service/error_rate`)
**Assumptions:**
- ASM-3: A surge of concurrent positions reads originated upstream (batch job or feature flag) not captured in change history.

### 3. `data_issue` on **postgres-orders** (HYP-3)

Confidence 0.25 (low). Missing or ineffective index on positions.account_id forces full‑table scans; each scan consumes CPU and holds connections longer, producing the observed overload.

**Supporting:**
- postgres‑orders CPU utilisation rose from baseline 0.34 to 0.95 by 10:40 UTC, first high point ~10:14. (`metric:postgres-orders/cpu_util`)
- Active connections on postgres‑orders climbed from baseline ~73 to 175 at 10:40 UTC. (`metric:postgres-orders/active_connections`)
- Query latency p99 on postgres‑orders jumped from baseline ~18 ms to 1067 ms by 10:40 UTC, first rise ~10:14. (`metric:postgres-orders/query_latency_p99_ms`)
- Postgres log shows 1050 executions of ‘SELECT * FROM positions WHERE account_id = $1’ between 10:14:01 and 10:39:59. (`log:d9900d4bc11e`)
- Postgres log reports 302 ‘FATAL: remaining connection slots are reserved for non‑replication superuser connections’ errors starting 10:16:25. (`log:e1265c62e747`)
**Contradicting:**
- Config change chg:2519 at 09:31:44 raised work_mem from 4 MB to 8 MB (reload). (`chg:2519`)
- Checkpoint frequency warnings appeared at 09:33 and 10:25. (`log:5dc98c9be4d4`)
- Portfolio logs show 1604 cache‑misses for positions loading from postgres‑orders starting 10:13:01. (`log:4c3c36a1bb07`)
- Portfolio logs show 496 query‑timeout errors (2000 ms) to postgres‑orders starting 10:16:01. (`log:1b4046047da5`)
**Assumptions:**
- ASM-4: Planner may have chosen a sequential scan on positions because statistics were stale or table grew past a threshold.

### 4. `dependency_degradation` on **redis-cache** (HYP-4)

Confidence 0.20 (low). Redis memory pressure or restart caused mass eviction of portfolio position caches and auth sessions; services fell back to postgres‑orders (cache miss storm) and forced re‑logins, overloading the DB.

**Supporting:**
- Portfolio logs show 1604 cache‑misses for positions loading from postgres‑orders starting 10:13:01. (`log:4c3c36a1bb07`)
- Portfolio logs show 496 query‑timeout errors (2000 ms) to postgres‑orders starting 10:16:01. (`log:1b4046047da5`)
- auth‑service logs 665 ‘session not found in redis; forcing re‑login’ events starting 10:12:36. (`log:26d7a4550ba6`)
- Dependency graph: auth‑service → redis‑cache (hard, 200 ms). (`dep:auth-service->redis-cache`)
- Dependency graph: portfolio‑service → postgres‑orders (hard, 2000 ms) and → redis‑cache (soft, 100 ms). (`dep:portfolio-service->postgres-orders`, `dep:portfolio-service->redis-cache`)
**Contradicting:**
- postgres‑orders CPU utilisation rose from baseline 0.34 to 0.95 by 10:40 UTC, first high point ~10:14. (`metric:postgres-orders/cpu_util`)
- Active connections on postgres‑orders climbed from baseline ~73 to 175 at 10:40 UTC. (`metric:postgres-orders/active_connections`)
- Query latency p99 on postgres‑orders jumped from baseline ~18 ms to 1067 ms by 10:40 UTC, first rise ~10:14. (`metric:postgres-orders/query_latency_p99_ms`)
- Postgres log shows 1050 executions of ‘SELECT * FROM positions WHERE account_id = $1’ between 10:14:01 and 10:39:59. (`log:d9900d4bc11e`)
- Postgres log reports 302 ‘FATAL: remaining connection slots are reserved for non‑replication superuser connections’ errors starting 10:16:25. (`log:e1265c62e747`)
- Config change chg:2519 at 09:31:44 raised work_mem from 4 MB to 8 MB (reload). (`chg:2519`)
**Assumptions:**
- ASM-5: Redis cache experienced memory pressure or a brief restart around 10:12, causing evictions and session loss.

## Recommended actions

| Urgency | Kind | Action | Why |
|---|---|---|---|
| now | investigate | Collect Redis metrics (memory, evictions, uptime) and logs for 09:30‑10:40. | Directly tests hypothesis H4 (Redis degradation). |
| now | investigate | Run EXPLAIN (ANALYZE, BUFFERS) for SELECT * FROM positions WHERE account_id = $1 on a replica. | Determines index usage and memory‑grant behavior (H1 vs H3). |
| now | mitigate | Revert work_mem to 4 MB via ALTER SYSTEM SET work_mem='4MB'; SELECT pg_reload_conf(); | If config change (H1) is contributing, this reduces per‑query memory pressure quickly. |
| soon | investigate | Enable pg_stat_statements snapshot for last 30 min and capture top‑SQL. | Quantifies query load to validate capacity‑saturation (H2) or missing index (H3). |
| soon | investigate | Review orders‑service request rate and any scheduled batch jobs around 10:12. | Checks for upstream traffic surge (H2). |
| soon | fix | If index missing, create CREATE INDEX ON positions(account_id); if connection slots exhausted, raise max_connections temporarily. | Addresses H3 and connection‑slot exhaustion. |
| later | prevent | Add alerts on postgres‑orders CPU >80% and active_connections >150; add Redis memory‑eviction alert. | Early detection for similar overload patterns. |
| later | prevent | Update change‑management policy for memory‑related GUCs (work_mem) to require canary rollout and post‑change monitoring. | Mitigates future config‑change induced saturation (H1). |
| later | prevent | Validate read‑replica fail‑over readiness for postgres‑orders. | Responder asked about fail‑over; improves resilience. |

## Evidence gaps

- **query_metrics** (redis-cache CPU, memory, eviction rate, uptime 09:30‑10:40): Redis telemetry not queried; needed to confirm or reject H4.
- **query_logs** (redis-cache logs 09:30‑10:40): No Redis logs retrieved; would show restarts or OOM.
- **query_metrics** (orders-service request rate, error rate, latency 09:30‑10:40): Upstream traffic burst (H2) not observed.
- **query_logs** (orders-service logs 09:30‑10:40): Could reveal batch job or feature‑flag activation.
- **query_logs** (postgres-orders EXPLAIN ANALYZE for the positions query): Plan details missing; needed to test H1 vs H3.

## Open questions

- Did Redis experience a restart or OOM around 10:12?
- What was the exact request rate on orders‑service at the onset?
- Does the positions table have an index on account_id, and are statistics up to date?
- Was any feature flag or batch job enabled at 10:10‑10:15 that could cause the query surge?

## How the investigation ran

Stopped because the agent finished its investigation, after 1 round(s): 9 model calls, 7 tool calls, 60,984 tokens, 279 s.
