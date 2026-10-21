# T03: Portfolio and order pages slow, users logged out

**Outcome:** inconclusive
- HYP-2 and HYP-3 are too close to tell apart
- HYP-2 has unresolved blocking objections

## Summary

From ~10:13 UTC portfolio pages slowed dramatically (p99 > 2.5 s) and many users were forced to log in again. The Redis master failed at 10:12 UTC and a not‑fully‑synced replica was promoted, emptying the cache and causing a massive cache‑miss storm that drove postgres‑orders CPU to >90 % and query latencies >500 ms. Two leading explanations remain equally plausible: (HYP‑2) the empty Redis cache alone generated the load spike, or (HYP‑3) postgres‑orders was already near a hidden capacity ceiling and the extra load pushed it over. The investigation was stopped because the time budget was exhausted and the blocking objections on HYP‑2 (missing Redis failover metrics and an unverified trigger log) could not be resolved. Consequently the root cause is inconclusive.

## Hypotheses

### 1. `infrastructure_failure` on **redis-cache**, triggered by `log:f58ca7278052` (HYP-2)

Confidence 0.50 (medium), critic: challenge, capped from 0.68: it has unresolved blocking objections. The Redis master failed at 10:12 UTC and a replica that had not completed resync was promoted, leaving the cache empty. Auth‑service cannot find session entries (forcing re‑logins) and portfolio‑service suffers a massive cache‑miss storm for position keys, redirecting ~1 600 req/min to postgres‑orders. The sudden surge of concurrent SQL drives postgres‑orders CPU > 90 % and query timeouts.

**Supporting:**
- Redis‑cache sentinel reported master down at 10:12:03.988Z and performed a master switch to redis‑cache‑1 at 10:12:37.618Z; the promoted replica had not finished full resync and was serving from an empty keyspace at 10:12:31.369Z. (`log:f58ca7278052`, `log:1eb56e1358d5`, `log:48f2fea2df36`)
- Auth‑service emitted 665 WARN logs “session <id> not found in redis; forcing re‑login” starting at 10:12:36.674Z and continuing until 10:39:52.999Z. (`log:26d7a4550ba6`)
- Auth‑service error_rate mean over the window was 0.0020 vs baseline 0.0018; latency_p99 mean 261 ms vs baseline 261 ms; rps rose modestly to 135.6 req/s from a baseline of 128.3 req/s. No abrupt latency or error spike coincident with the Redis failover. (`metric:auth-service/error_rate`, `metric:auth-service/latency_p99_ms`, `metric:auth-service/rps`)
- auth-service has a hard Redis dependency on redis-cache (timeout 200 ms). (`dep:auth-service->redis-cache`)
- Portfolio‑service began emitting “cache miss for positions:<account>; loading from postgres‑orders” WARN messages at 2026‑10‑07T10:13:01.462Z, continuing until 10:39:59.983Z (1,604 occurrences). (`log:4c3c36a1bb07`)
- Portfolio‑service started logging “query on postgres‑orders timed out after 2000ms” ERROR messages at 2026‑10‑07T10:16:01.462Z, persisting until 10:39:55.538Z (496 occurrences). (`log:1b4046047da5`)
- cpu_util stayed at ~0.33‑0.37 from 09:20 through 10:08 UTC (baseline 0.341), with the first elevated point at 10:11 UTC (0.455) and a sharp step to >0.9 at 10:14 UTC. (`metric:postgres-orders/cpu_util`)
- Overall query_latency_p99_ms mean over 09:20‑10:40 UTC was 298 ms vs baseline 17.5 ms (max 1158 ms), indicating a large increase sometime in the window. (`metric:postgres-orders/query_latency_p99_ms`)
- Active connections were stable around 73‑80 until 10:11 UTC (≈90), then jumped to 182 at 10:14 UTC and remained >170 thereafter. (`metric:postgres-orders/active_connections`)
- redis‑cache hit_ratio dropped from 0.9548 at 10:00 UTC to 0.1985 at 10:20 UTC (baseline 0.9419), indicating an empty cache after the 10:12 UTC master switch. (`metric:redis-cache/hit_ratio`)
**Contradicting:**
- Auth‑service error_rate mean over the window was 0.0020 vs baseline 0.0018; latency_p99 mean 261 ms vs baseline 261 ms; rps rose modestly to 135.6 req/s from a baseline of 128.3 req/s. No abrupt latency or error spike coincident with the Redis failover. (`metric:auth-service/error_rate`, `metric:auth-service/latency_p99_ms`, `metric:auth-service/rps`)
**Assumptions:**
- ASM-8: The promoted replica’s keyspace was essentially empty at promotion.
- ASM-9: Portfolio‑service’s cache‑miss logic immediately falls back to postgres‑orders for every miss (no local fallback).
- ASM-10: The cache‑miss rate is high enough to raise postgres‑orders active connections from ~80 to >180 within two minutes.
**Objections:**
- [blocking] unsupported_claim: names log:f58ca7278052 as the trigger, but no change-history query returned it
- [blocking] gap_unaddressed: Redis‑cache client‑side latency and ops during the 10:12‑10:14 failover are not available (GAP‑1); portfolio‑service per‑minute latency_p99 is missing (GAP‑12); edge‑gateway auth‑failure logs are missing (GAP‑2).
- [minor] alternative_not_excluded: HYP‑3 (capacity saturation triggered by the same Redis failover) remains viable and has not been ruled out. (not blocking: this review rejected HYP-3 or found it flawed)

### 2. `capacity_saturation` on **postgres-orders**, triggered by `log:f58ca7278052` (HYP-3)

Confidence 0.45 (low), critic: challenge. The same Redis failover triggers a cache‑miss storm, but postgres‑orders was already operating near a hidden saturation point (elevated baseline connections, early slow queries). The modest extra load from misses pushes the instance over its capacity ceiling, causing the abrupt CPU and latency spike.

**Supporting:**
- Redis‑cache sentinel reported master down at 10:12:03.988Z and performed a master switch to redis‑cache‑1 at 10:12:37.618Z; the promoted replica had not finished full resync and was serving from an empty keyspace at 10:12:31.369Z. (`log:f58ca7278052`, `log:1eb56e1358d5`, `log:48f2fea2df36`)
- Auth‑service emitted 665 WARN logs “session <id> not found in redis; forcing re‑login” starting at 10:12:36.674Z and continuing until 10:39:52.999Z. (`log:26d7a4550ba6`)
- auth-service has a hard Redis dependency on redis-cache (timeout 200 ms). (`dep:auth-service->redis-cache`)
- Portfolio‑service began emitting “cache miss for positions:<account>; loading from postgres‑orders” WARN messages at 2026‑10‑07T10:13:01.462Z, continuing until 10:39:59.983Z (1,604 occurrences). (`log:4c3c36a1bb07`)
- Portfolio‑service started logging “query on postgres‑orders timed out after 2000ms” ERROR messages at 2026‑10‑07T10:16:01.462Z, persisting until 10:39:55.538Z (496 occurrences). (`log:1b4046047da5`)
- cpu_util stayed at ~0.33‑0.37 from 09:20 through 10:08 UTC (baseline 0.341), with the first elevated point at 10:11 UTC (0.455) and a sharp step to >0.9 at 10:14 UTC. (`metric:postgres-orders/cpu_util`)
- Overall query_latency_p99_ms mean over 09:20‑10:40 UTC was 298 ms vs baseline 17.5 ms (max 1158 ms), indicating a large increase sometime in the window. (`metric:postgres-orders/query_latency_p99_ms`)
- Overall active_connections mean over the window was 113 vs baseline 72.6 (max 221), showing higher concurrency but the minute‑level onset is unknown. (`metric:postgres-orders/active_connections`)
- Orders‑service logged three “slow query: SELECT * FROM orders WHERE account_id = $1 took <ms>ms” WARN events, first at 09:51:43.967Z (223 ms) and last at 10:20:01.885Z. (`log:3d03e926d542`)
- Orders‑service emitted 503 errors on GET /v1/orders from 09:33:00.952Z through 10:38:59.994Z (11 occurrences). (`log:c84179768ef2`)
- Active connections were stable around 73‑80 until 10:11 UTC (≈90), then jumped to 182 at 10:14 UTC and remained >170 thereafter. (`metric:postgres-orders/active_connections`)
- redis‑cache hit_ratio dropped from 0.9548 at 10:00 UTC to 0.1985 at 10:20 UTC (baseline 0.9419), indicating an empty cache after the 10:12 UTC master switch. (`metric:redis-cache/hit_ratio`)
**Contradicting:**
- The work_mem increase at 09:31:44 UTC did not produce a measurable change in either latency or connections. (`metric:postgres-orders/query_latency_p99_ms`, `metric:postgres-orders/active_connections`)
**Assumptions:**
- ASM-11: Postgres‑orders had a latent bottleneck (e.g., max_connections ≈200, autovacuum throttling) that was not visible in the 09:20‑10:10 metrics because the workload was just below the threshold.
- ASM-12: The extra ~100 concurrent connections from the cache‑miss storm were enough to exceed that bottleneck.
**Objections:**
- [blocking] unsupported_claim: names log:f58ca7278052 as the trigger, but no change-history query returned it
- [blocking] gap_unaddressed: Minute‑level postgres‑orders active_connections and query_latency_p99 for 09:20‑10:14 are missing (GAP‑7, 8, 9, 10), preventing verification of a pre‑existing saturation ceiling.
- [minor] alternative_not_excluded: HYP‑2 (Redis failover‑driven cache‑miss storm) also explains the observations and has not been excluded. (not blocking: this review rejected HYP-2 or found it flawed)

### 3. `config_change` on **postgres-orders**, triggered by `chg:2519` (HYP-1)

Confidence 0.15 (low), critic: reject. Increasing work_mem from 4 MiB to 8 MiB raises per‑query memory consumption; when many concurrent reporting queries run the larger allocation creates memory pressure and lock contention, driving CPU to ~100 % and query latency > 500 ms, which propagates as timeouts to portfolio‑service and orders‑service.

**Supporting:**
- config on postgres-orders at 09:31:44 UTC by marta.silva: Raise work_mem for reporting queries (work_mem: 4MB -> 8MB, applied: reload) (`chg:2519`)
- postgres-orders config changed at 09:31:44 UTC, raising work_mem from 4 MB to 8 MB (reload). (`chg:2519`)
- A configuration change on postgres‑orders raising work_mem from 4 MB to 8 MB was applied at 09:31:44 UTC (change‑census record). (`chg:2519`)
- portfolio-service has a hard SQL dependency on postgres-orders (timeout 2000 ms). (`dep:portfolio-service->postgres-orders`)
- Orders‑service logged three “slow query: SELECT * FROM orders WHERE account_id = $1 took <ms>ms” WARN events, first at 09:51:43.967Z (223 ms) and last at 10:20:01.885Z. (`log:3d03e926d542`)
- Orders‑service emitted 503 errors on GET /v1/orders from 09:33:00.952Z through 10:38:59.994Z (11 occurrences). (`log:c84179768ef2`)
- cpu_util stayed at ~0.33‑0.37 from 09:20 through 10:08 UTC (baseline 0.341), with the first elevated point at 10:11 UTC (0.455) and a sharp step to >0.9 at 10:14 UTC. (`metric:postgres-orders/cpu_util`)
- Overall query_latency_p99_ms mean over 09:20‑10:40 UTC was 298 ms vs baseline 17.5 ms (max 1158 ms), indicating a large increase sometime in the window. (`metric:postgres-orders/query_latency_p99_ms`)
**Contradicting:**
- cpu_util stayed at ~0.33‑0.37 from 09:20 through 10:08 UTC (baseline 0.341), with the first elevated point at 10:11 UTC (0.455) and a sharp step to >0.9 at 10:14 UTC. (`metric:postgres-orders/cpu_util`)
- From 09:20 to 09:58 UTC postgres‑orders query_latency_p99_ms stayed within 15‑20 ms (baseline ~17.5 ms). (`metric:postgres-orders/query_latency_p99_ms`)
- At 10:11 UTC the 3‑minute aggregated p99 was still 16.5 ms; the first elevated 3‑minute bucket is at 10:14 UTC with 540.7 ms. (`metric:postgres-orders/query_latency_p99_ms`)
- Active connections were stable around 73‑80 until 10:11 UTC (≈90), then jumped to 182 at 10:14 UTC and remained >170 thereafter. (`metric:postgres-orders/active_connections`)
- The work_mem increase at 09:31:44 UTC did not produce a measurable change in either latency or connections. (`metric:postgres-orders/query_latency_p99_ms`, `metric:postgres-orders/active_connections`)
**Assumptions:**
- ASM-6: The workload that would feel the work_mem increase (large reporting sorts/hashes) was already running at a steady rate before 09:31.
- ASM-7: No other config or code change altered the query mix between 09:31‑10:10.
**Objections:**
- [blocking] ignores_contradiction: The hypothesis cites the 09:31 config change as the trigger but does not address metrics showing no latency or connection change until 10:14 (OBS‑16, 19‑22).

## Recommended actions

| Urgency | Kind | Action | Why |
|---|---|---|---|
| now | mitigate | Add a read‑replica or increase connection‑pool limits for postgres‑orders and enable query‑timeout circuit‑breakers to relieve CPU pressure immediately. | Both HYP‑2 and HYP‑3 show postgres‑orders CPU >90 % and connection surge at 10:14 UTC; reducing load now limits user impact. (HYP-2) |
| now | mitigate | Warm the Redis cache after failover (e.g., pre‑populate session keys and portfolio position keys) and enable client‑side fallback to a secondary cache. | HYP‑2 attributes the outage to an empty keyspace; repopulating the cache restores auth‑service sessions and eliminates the cache‑miss storm. (HYP-2) |
| soon | fix | Configure Redis Sentinel to require full replica resync before promotion, and add a health‑check that blocks promotion when replication lag >0. | HYP‑2’s mechanism relies on a replica promoted with an empty keyspace; preventing premature promotion eliminates that failure mode. (HYP-2) |
| soon | fix | Re‑evaluate postgres‑orders capacity: set max_connections and work_mem based on observed peak (≈220 connections, CPU > 0.9) and enable autoscaling or read‑replica routing. | HYP‑3 argues the instance was near a hidden saturation point; proper capacity limits prevent the same spike from overwhelming the DB. (HYP-3) |
| later | prevent | Add alerts for Redis replication lag, keyspace size, and hit‑ratio drops; add alerts for postgres‑orders CPU, active_connections, and query_latency_p99 crossing thresholds. | Early detection of the conditions that preceded both HYP‑2 and HYP‑3 will allow pre‑emptive action before users are affected. (HYP-2) |
| later | prevent | Deploy automated cache‑warm‑up jobs that run after any Redis master switch. | Ensures the cache is populated quickly, mitigating the cache‑miss storm described in HYP‑2. (HYP-2) |
| now | investigate | Retrieve the missing metrics identified in GAP‑1, GAP‑2, GAP‑7‑10, GAP‑11, GAP‑12 (Redis client‑side latency/ops, edge‑gateway auth logs, minute‑level postgres‑orders latency & connections, Redis replication lag, portfolio‑service per‑minute latency). | These data points are required to decide whether the Redis failover alone (HYP‑2) or pre‑existing DB saturation (HYP‑3) was the primary driver. (HYP-2) |
| now | investigate | Verify the existence and content of trigger log f58ca7278052 in the change‑history system; determine why it was not returned by the change‑history query. | Both HYP‑2 and HYP‑3 cite this log as the trigger; confirming or refuting it resolves a blocking objection. (HYP-2) |
| soon | investigate | Examine edge‑gateway WARN/ERROR logs for auth‑failure patterns around 10:12‑10:14 UTC (GAP‑2). | Direct evidence of user‑visible log‑out events will confirm the auth‑service impact path in HYP‑2. (HYP-2) |

## Evidence gaps

- **query_metrics** (redis-cache latency, ops, replication lag): Redis metrics were not queried; they would confirm whether client‑side latency spiked during failover.
- **query_logs** (edge-gateway WARN/ERROR patterns): Edge‑gateway logs were not examined; they could show downstream auth failures visible to users.
- **get_change_history** (orders-service, edge-gateway, auth-service, redis-cache, portfolio-service (09:28–10:40 UTC)): The call returned only the postgres-orders config change; absence of entries may mean no changes occurred or the source does not capture feature‑flag / secret‑rotation events.
- **query_metrics** (postgres-orders cpu_util, query_latency_p99_ms, active_connections, replication_lag_s): Metric name used (cpu_usage_percent) does not exist; correct series not queried.
- **query_logs** (auth-service (WARN+), edge-gateway (WARN+), postgres-orders (WARN+)): Logs for these services were not fetched; needed to confirm auth timeouts and gateway error correlation.
- **query_metrics** (portfolio-service request_latency_p99_ms, error_rate): Portfolio‑service latency and error metrics not retrieved; required to verify reported p99 >2.5 s.
- **query_metrics** (postgres-orders query_latency_p99_ms (1‑minute resolution) from 09:20‑10:40 UTC): Minute‑level series not retrieved; needed to pinpoint latency onset relative to the 09:31 config change.
- **query_metrics** (postgres-orders active_connections (1‑minute resolution) from 09:20‑10:40 UTC): Minute‑level series not retrieved; needed to see if connection count jumped at the config change or later.
- **query_metrics** (postgres-orders query_latency_p99_ms at 1‑minute resolution for 09:20‑10:11 UTC): API limited to 30 points; step was raised to 2‑minute (early) and 3‑minute (full window), hiding any sub‑minute onset before 10:14.
- **query_metrics** (postgres-orders active_connections at 1‑minute resolution for 10:11‑10:14 UTC): Same point‑limit caused 3‑minute aggregation; exact minute of connection surge cannot be pinpointed.
- **query_metrics** (redis-cache replication_lag_seconds, ops/sec, keyspace size): These metrics are not exposed by the redis‑cache service; the tool returned an invalid‑query error for replication_lag_seconds and the summary endpoint does not list ops/sec or keyspace size.
- **query_metrics** (portfolio-service per‑minute latency_p99_ms and error_rate points): Only aggregate summaries were returned; minute‑level series are unavailable, preventing precise onset pinpointing.

## Open questions

- What caused the Redis master to fail at 10:12 UTC and why was the replica not fully resynced?
- Was postgres‑orders already operating near a hidden capacity ceiling before the Redis failover?
- Exact minute‑level timeline of postgres‑orders active_connections and query_latency_p99 between 10:11‑10:14 UTC.
- Edge‑gateway auth‑failure logs: do they show a spike matching the Redis failover?
- Does the missing trigger log f58ca7278052 exist, and what does it record?
- Redis client‑side latency, ops/sec, and replication lag during the failover (GAP‑1, GAP‑11).
- Portfolio‑service per‑minute latency_p99 and error_rate onset (GAP‑12).

## How the investigation ran

Stopped because time budget reached, after 2 round(s): 35 model calls, 19 tool calls, 165,401 tokens, 1053 s.
