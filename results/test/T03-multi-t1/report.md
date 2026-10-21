# T03: Portfolio and order pages slow, users logged out

**Outcome:** inconclusive
- HYP-1 and HYP-2 are too close to tell apart

## Summary

Starting around 10:13 UTC the portfolio and order APIs slowed dramatically (portfolio‑service p99 > 2.5 s) and a subset of users were forced to log out. postgres‑orders CPU rose to ~100 % and active connections more than doubled. Two plausible root causes were identified but could not be distinguished: (HYP‑1) a work_mem increase from 4 MiB to 8 MiB at 09:31 that may have caused the planner to choose CPU‑heavy hash/sort plans, and (HYP‑2) a Redis master failover at 10:12 that promoted a replica before it finished resync, leaving the keyspace empty and causing auth‑service session misses. Evidence for each hypothesis exists (config change, CPU/connection metrics, Redis failover logs, auth‑service “session not found” logs) but key observability gaps (pg_stat_statements, Redis key‑count/replication‑lag, per‑minute service latency series) remain unfilled. The investigation stopped after two rounds, leaving the outcome inconclusive.

## Hypotheses

### 1. `config_change` on **postgres-orders**, triggered by `chg:2519` (HYP-1)

Confidence 0.55 (medium), critic: challenge. Increasing work_mem from 4 MiB to 8 MiB at 09:31 caused the planner to choose hash-/sort‑based plans for reporting‑type queries. Those plans consume substantially more CPU per execution, lengthening query runtime. Longer queries raise active connections (OBS‑4) and query latency (OBS‑5), which propagates through the hard SQL dependencies of orders‑service (OBS‑19) and portfolio‑service (OBS‑20), producing their latency (OBS‑6, OBS‑8) and error‑rate (OBS‑7, OBS‑9) increases and downstream gateway time‑outs (OBS‑17).

**Supporting:**
- config on postgres-orders at 09:31:44 UTC by marta.silva: Raise work_mem for reporting queries (work_mem: 4MB -> 8MB, applied: reload) (`chg:2519`)
- postgres-orders config changed: work_mem raised from 4 MiB to 8 MiB at 2026-10-07T09:31:44Z (applied via reload). (`chg:2519`)
- postgres‑orders CPU utilization spikes from 0.34 (baseline 0.339) at 10:09 to 0.57 at 10:12 and reaches 0.97 by 10:15, remaining >0.95 through 10:40. (`metric:postgres-orders/cpu_util`)
- postgres‑orders active connections rise from a baseline mean of 73.3 to a mean of 118.8 and a last value of 175 at 10:40. (`metric:postgres-orders/active_connections`)
- postgres‑orders query p99 latency increases from a baseline of 17.6 ms to a mean of 338.7 ms and a last value of 1067 ms at 10:40. (`metric:postgres-orders/query_latency_p99_ms`)
- orders-service has a hard SQL dependency on postgres-orders. (`dep:orders-service->postgres-orders`)
- portfolio-service has a hard SQL dependency on postgres-orders. (`dep:portfolio-service->postgres-orders`)
- portfolio‑service p99 latency rises from a baseline of 424 ms to a mean of 1274 ms and a last value of 2780 ms at 10:40. (`metric:portfolio-service/latency_p99_ms`)
- portfolio‑service error rate climbs from a baseline of 0.22 % to a mean of 1.87 % and a last value of 4.78 % at 10:40. (`metric:portfolio-service/error_rate`)
- orders‑service p99 latency rises from a baseline of 253 ms to a mean of 795 ms and a last value of 1606 ms at 10:40. (`metric:orders-service/latency_p99_ms`)
- orders‑service error rate climbs from a baseline of 0.18 % to a mean of 0.79 % and a last value of 2.48 % at 10:40. (`metric:orders-service/error_rate`)
- Edge‑gateway began reporting upstream portfolio‑service timeouts (3000 ms) at 2026‑10‑07T10:16:04.412Z (243 occurrences through 10:39:38). (`log:2710d027f157`)
**Assumptions:**
- ASM-6: The postgres‑orders workload includes at least one reporting‑type query (large aggregation/window) whose plan is sensitive to work_mem.
- ASM-7: Raising work_mem from 4 MiB to 8 MiB pushes the planner over the cost threshold for that query, causing a switch to a hash‑/sort‑heavy plan.
- ASM-8: No other simultaneous change (deploy, feature flag, secret rotation) touched postgres‑orders or its callers in the 09:30‑10:40 window.
**Objections:**
- [minor] gap_unaddressed: Missing pg_stat_statements / slow‑query metrics for postgres‑orders after the work_mem change; without them we cannot verify the planner‑plan shift claimed by the hypothesis.
- [minor] unsupported_claim: The hypothesis asserts that raising work_mem caused the planner to choose hash/sort plans, but no observation (plan change, sort‑spill, temp‑file usage) supports this claim.

### 2. `infrastructure_failure` on **redis-cache**, triggered by `log:f58ca7278052` (HYP-2)

Confidence 0.48 (low), critic: challenge. The Redis master (redis‑cache‑0) was marked down at 10:12:03 (OBS‑13). Sentinel promoted replica redis‑cache‑1 at 10:12:37 (OBS‑15) before it completed full resync, so it began serving from an empty keyspace at 10:12:31 (OBS‑14). auth‑service reads session tokens from Redis; missing keys cause it to log “session <id> not found in redis; forcing re‑login” (OBS‑16, 665 occurrences) and return 401/redirect, which users experience as forced logouts. This chain is independent of the postgres‑orders overload (auth‑service error rate barely moves, OBS‑12).

**Supporting:**
- Redis master cache redis‑cache‑0 was marked down by sentinel at 2026‑10‑07T10:12:03.988Z and 2026‑10‑07T10:12:05.847Z. (`log:f58ca7278052`)
- A replica was promoted but had not finished full resync; it began serving from an empty keyspace at 2026‑10‑07T10:12:31.369Z. (`log:1eb56e1358d5`)
- Sentinel performed a master switch from redis‑cache‑0 to redis‑cache‑1 at 2026‑10‑07T10:12:37.618Z. (`log:48f2fea2df36`)
- Auth‑service started logging “session <id> not found in redis; forcing re‑login” at 2026‑10‑07T10:12:36.674Z (665 occurrences through 10:39:52). (`log:26d7a4550ba6`)
- auth‑service error rate shows only a slight increase (baseline 0.18 % → last 0.29 %). (`metric:auth-service/error_rate`)
**Contradicting:**
- postgres‑orders CPU utilization spikes from 0.34 (baseline 0.339) at 10:09 to 0.57 at 10:12 and reaches 0.97 by 10:15, remaining >0.95 through 10:40. (`metric:postgres-orders/cpu_util`)
- postgres‑orders active connections rise from a baseline mean of 73.3 to a mean of 118.8 and a last value of 175 at 10:40. (`metric:postgres-orders/active_connections`)
- postgres‑orders query p99 latency increases from a baseline of 17.6 ms to a mean of 338.7 ms and a last value of 1067 ms at 10:40. (`metric:postgres-orders/query_latency_p99_ms`)
- portfolio‑service p99 latency rises from a baseline of 424 ms to a mean of 1274 ms and a last value of 2780 ms at 10:40. (`metric:portfolio-service/latency_p99_ms`)
- portfolio‑service error rate climbs from a baseline of 0.22 % to a mean of 1.87 % and a last value of 4.78 % at 10:40. (`metric:portfolio-service/error_rate`)
- orders‑service p99 latency rises from a baseline of 253 ms to a mean of 795 ms and a last value of 1606 ms at 10:40. (`metric:orders-service/latency_p99_ms`)
- orders‑service error rate climbs from a baseline of 0.18 % to a mean of 0.79 % and a last value of 2.48 % at 10:40. (`metric:orders-service/error_rate`)
**Assumptions:**
- ASM-9: auth‑service reads session data synchronously from Redis on each request with no local cache fallback.
- ASM-10: The promoted replica’s empty keyspace persisted at least until the former master finished resync (duration unknown).
- ASM-11: No auth‑service deploy or config change occurred in the 09:30‑10:12 window.
**Objections:**
- [blocking] unsupported_claim: names log:f58ca7278052 as the trigger, but no change-history query returned it

### 3. `code_regression` on **payments-service**, triggered by `chg:2522` (HYP-3)

Confidence 0.12 (low), critic: reject. The payments‑service deploy could have introduced a code path that calls orders‑service (or directly postgres‑orders) for reporting, adding load that coincides with the DB CPU spike. No dependency is currently documented, so this remains speculative.

**Supporting:**
- deploy on payments-service at 09:58:10 UTC by ci/deploy-bot: payments-service v7.3.1: update bank-rails client (version: 7.3.1, previous_version: 7.3.0, commit: 52e9b14, diff: +64 / -30) (`chg:2522`)
**Contradicting:**
- orders-service has a hard SQL dependency on postgres-orders. (`dep:orders-service->postgres-orders`)
- portfolio-service has a hard SQL dependency on postgres-orders. (`dep:portfolio-service->postgres-orders`)
- Change history for the window 09:30‑10:40 UTC shows no deployments, config changes, feature‑flag toggles, secret rotations, or infra ops for edge-gateway, orders-service, portfolio-service, auth-service, or redis-cache (only chg:2519 appears). (`chg:2519`)
**Assumptions:**
- ASM-5: Payments‑service might have an undocumented dependency on orders‑service or postgres‑orders.
**Objections:**
- [blocking] ignores_contradiction: The dependency graph (OBS‑19, OBS‑20, OBS‑21) shows no path from payments‑service to postgres‑orders, yet the hypothesis assumes such a path exists.

## Recommended actions

| Urgency | Kind | Action | Why |
|---|---|---|---|
| now | mitigate | Revert postgres‑orders work_mem to 4 MiB (or a value proven safe) and reload the configuration. | If HYP‑1 is the driver, lowering work_mem should reduce per‑query CPU and bring active connections back toward baseline within minutes. (HYP-1) |
| now | mitigate | Add a pre‑promotion check that the Redis replica has completed full resync (replication lag = 0) before Sentinel promotes it, or pause promotion until sync finishes. | If HYP‑2 is the driver, preventing promotion of an unsynced replica avoids serving an empty keyspace and the resulting forced logouts. (HYP-2) |
| now | investigate | Query pg_stat_statements (or equivalent slow‑query view) for postgres‑orders covering 09:30‑10:40 UTC to identify queries whose total_exec_time, sort_spill_count or temp_file_bytes jump after the work_mem change. | Directly tests the planner‑plan shift claimed by HYP‑1 (gap 4, 13). (HYP-1) |
| now | investigate | Collect Redis key‑count and replication‑lag metrics for the 09:30‑10:40 UTC window (or enable them if missing) to verify the empty‑keyspace interval after the failover. | Confirms whether the replica served from an empty keyspace and for how long (gaps 10, 11). (HYP-2) |
| soon | investigate | Retrieve per‑minute latency_p99_ms and error_rate series for portfolio‑service, orders‑service and edge‑gateway for 09:30‑10:40 UTC. | Aligns the exact onset of service‑level degradation with either the DB CPU spike or the Redis failover (gaps 2, 14, 15, 7). |
| later | prevent | Introduce a change‑validation gate for PostgreSQL configuration changes that runs a short‑term canary workload and checks planner choice / CPU impact before wide rollout. | Reduces risk of future work_mem (or similar) changes silently shifting query plans (addresses HYP‑1 recurrence). (HYP-1) |
| later | prevent | Update Sentinel/Redis failover policy to require full resync (replication lag = 0) before promoting a replica, and add an alert on replica lag exceeding a safe threshold. | Eliminates the class of failure where a partially synced replica serves stale/empty data (addresses HYP‑2 recurrence). (HYP-2) |
| soon | fix | Add alerts for postgres‑orders CPU > 80 % sustained for > 2 min and for Redis master health (master down, replica lag > 30 s). | Provides earlier detection of the two failure modes so on‑call can act before user impact escalates. |

## Evidence gaps

- **query_logs** (WARN+ logs for portfolio-service, orders-service, postgres-orders, auth-service between 10:10‑10:20 UTC): Log query tool not invoked; needed to see query‑level errors, authentication failures, or pool‑exhaustion messages.
- **query_metrics** (Per‑minute latency_p99_ms and error_rate series for portfolio-service and orders-service): Only aggregate summaries were fetched; minute‑level series required to align onset precisely with DB CPU spike.
- **query_metrics** (Portfolio‑service DB connection pool metrics (in‑use, max, waiters)): Missing pool telemetry for portfolio-service; could reveal if it is opening many connections that drive postgres‑orders active_connections.
- **query_metrics** (Postgres‑orders pg_stat_statements or slow‑query metrics): Needed to identify the specific query patterns responsible for CPU saturation after the work_mem change.
- **query_metrics** (redis-cache (CPU, memory, replication lag, key count) 09:30‑10:40 UTC): Metrics not queried; needed to confirm resource pressure or replication lag before failover.
- **query_metrics** (auth-service (request latency, error rate, session‑lookup latency) 09:30‑10:40 UTC): Metrics not queried; would show when auth‑service latency spiked relative to Redis outage.
- **query_metrics** (edge-gateway (upstream latency, error rate, 5xx count) 09:30‑10:40 UTC): Metrics not queried; would quantify impact of portfolio‑service slowdown on the gateway.
- **get_change_history** (Infrastructure operations (replica promotion, instance resize, autoscaling events), feature‑flag toggles, secret rotations for DB credentials or connection‑pool settings): Change census only captures service‑level changes; infra‑level actions and flag/secret changes are not recorded there.
- **get_service_dependencies** (Deeper dependency chains beyond depth 2 (e.g., services that call orders-service or portfolio-service)): Current depth 2 may miss indirect callers that could generate load on postgres-orders.
- **query_metrics** (redis-cache replication lag): Metric not present in the service catalog; cannot assess replica sync state.
- **query_metrics** (redis-cache key count): Metric not present in the service catalog; cannot verify empty‑keyspace duration.
- **query_metrics** (auth-service session lookup latency (p99)): Metric not present in the service catalog; unable to quantify impact on forced logouts.
- **query_metrics** (postgres-orders per‑minute series (cpu_util, active_connections, query_latency_p99_ms, replication_lag_s) and pg_stat_statements data): The metrics endpoint returned only a list of available series; no time‑series points were provided for the requested window.
- **query_metrics** (orders-service per‑minute latency_p99_ms and error_rate): orders-service metrics were not queried within the allowed steps.
- **query_metrics** (portfolio-service per‑minute latency_p99_ms, error_rate and DB connection‑pool metrics): Only aggregate summaries were returned; per‑minute resolution and pool metrics are missing.

## Open questions

- Which specific query (or query class) caused the CPU surge after the work_mem increase?
- Did the Redis replica truly serve from an empty keyspace, and for how long did key‑count remain near zero?
- What was the auth‑service session‑lookup latency profile around 10:12:31‑10:12:37, and does it correlate with the forced‑logout logs?
- Were there any indirect callers (beyond depth‑2) that began issuing heavy reporting queries to postgres‑orders during the window?
- Did the portfolio‑service connection pool saturate, contributing to the rise in postgres‑orders active connections?

## How the investigation ran

Stopped because reached the limit of 2 rounds, after 2 round(s): 31 model calls, 18 tool calls, 150,755 tokens, 806 s.
