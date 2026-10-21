# T03: Portfolio and order pages slow, users logged out

**Outcome:** inconclusive
- HYP-4 and HYP-2 are too close to tell apart

## Summary

Starting around 10:13 UTC the portfolio and order pages became very slow (p99 > 2.5 s) and many users were forced to log in again. Postgres‑orders CPU hit ~100 % and its active connections and query latency spiked sharply at 10:12 UTC. Two leading explanations remain indistinguishable: (1) a new heavy‑query workload amplified by the work_mem increase (HYP‑4, confidence 0.55) and (2) a Redis master failure that lost session keys and caused the logout wave (HYP‑2, confidence 0.50). The investigation was stopped because the time budget was exhausted, leaving the exact trigger and the relative contribution of each factor unknown.

## Hypotheses

### 1. `capacity_saturation` on **postgres-orders** (HYP-4)

Confidence 0.55 (medium), critic: challenge. At ~10:12 UTC a new query pattern (e.g., a scheduled reporting job, a feature‑flag‑enabled batch, or a sudden traffic spike) began issuing many concurrent heavy‑sort/hash queries. The higher work_mem (from chg:2519) amplified per‑query memory/CPU use, causing a rapid rise in active connections, CPU saturation and query latency. Downstream services suffer because they depend on postgres‑orders via hard SQL calls. The Redis fail‑over is a coincident but independent infrastructure event that explains the logout wave.

**Supporting:**
- postgres‑orders cpu_util stayed near its baseline (≈0.34‑0.41) from 09:30 through 10:09, then rose to 0.571 at 10:12 and 0.972 at 10:15, remaining ≥0.95 through 10:39. (`metric:postgres-orders/cpu_util`)
- postgres‑orders query_latency_p99_ms was stable around 17‑20 ms until 10:09, then spiked to 100 ms at 10:12, 737 ms at 10:15 and stayed in the 800‑1,067 ms range thereafter. (`metric:postgres-orders/query_latency_p99_ms`)
- postgres‑orders active_connections hovered around 70‑85 until 10:09, then jumped to 112 at 10:12, 193 at 10:15 and remained near 180‑190 through 10:39. (`metric:postgres-orders/active_connections`)
- postgres-orders cpu_util rose from 0.36 at 09:30 UTC to 0.95 at 10:40 UTC, well above its baseline mean of 0.34. (`metric:postgres-orders/cpu_util`)
- postgres-orders query_latency_p99_ms increased from 19 ms at 09:30 UTC to 1,067 ms at 10:40 UTC (baseline ≈ 18 ms). (`metric:postgres-orders/query_latency_p99_ms`)
- postgres-orders active_connections grew from ~70 to ~175 (baseline ≈ 73). (`metric:postgres-orders/active_connections`)
- portfolio-service latency_p99_ms climbed from 394 ms at 09:30 UTC to 2,780 ms at 10:40 UTC (baseline ≈ 424 ms). (`metric:portfolio-service/latency_p99_ms`)
- portfolio-service error_rate rose from 0.0014 to 0.0478 (baseline ≈ 0.0022). (`metric:portfolio-service/error_rate`)
- orders-service latency_p99_ms increased from 274 ms to 1,606 ms (baseline ≈ 253 ms). (`metric:orders-service/latency_p99_ms`)
- orders-service error_rate rose from 0.0017 to 0.0248 (baseline ≈ 0.0018). (`metric:orders-service/error_rate`)
- postgres‑orders is a direct hard SQL dependency (2 s timeout) of both orders‑service and portfolio‑service; edge‑gateway calls those two services (hard HTTP, 3 s). auth‑service has no upstream path to postgres‑orders. (`dep:orders-service->postgres-orders`, `dep:portfolio-service->postgres-orders`, `dep:edge-gateway->orders-service`, `dep:edge-gateway->portfolio-service`)
- At 09:31:44 UTC the postgres‑orders configuration was changed: work_mem raised from 4 MB to 8 MB (reload). (`chg:2519`)
- No other config, feature‑flag, secret‑rotation, or infra changes were recorded for postgres‑orders, orders‑service, portfolio‑service, edge‑gateway, or auth‑service between 09:30 UTC and 10:40 UTC. (`chg:2519`)
**Contradicting:**
- config on postgres-orders at 09:31:44 UTC by marta.silva: Raise work_mem for reporting queries (work_mem: 4MB -> 8MB, applied: reload) (`chg:2519`)
- At 09:31:44 UTC the postgres‑orders configuration was changed: work_mem raised from 4 MB to 8 MB (reload). (`chg:2519`)
- No other config, feature‑flag, secret‑rotation, or infra changes were recorded for postgres‑orders, orders‑service, portfolio‑service, edge‑gateway, or auth‑service between 09:30 UTC and 10:40 UTC. (`chg:2519`)
- Auth‑service emitted 665 WARN logs “session <session> not found in redis; forcing re‑login” between 10:12:36.674Z and 10:39:52.999Z. (`log:26d7a4550ba6`)
- Auth‑service error_rate mean 0.002015 vs baseline 0.001785; latency_p99 mean 262.2 ms vs baseline 258.2 ms over the window. (`metric:auth-service/error_rate`, `metric:auth-service/latency_p99_ms`)
- Redis‑cache sentinel reported master down (+sdown) at 10:12:03.988Z, a replica promotion with incomplete resync at 10:12:31.369Z, and master switch at 10:12:37.618Z. (`log:f58ca7278052`, `log:1eb56e1358d5`, `log:48f2fea2df36`)
- Redis‑cache sentinel reported master down (+sdown) at 10:12:03.988Z, a replica promotion with incomplete resync at 10:12:31.369Z, and master switch at 10:12:37.618Z. (`log:f58ca7278052`, `log:1eb56e1358d5`, `log:48f2fea2df36`)
- Change census query for redis‑cache between 09:30 UTC and 10:15 UTC returned no changes (config, feature‑flag, secret‑rotation, infra, or deploy). (`chg:2519`)
- Auth‑service, orders‑service, portfolio‑service, and market‑data‑service each have a direct (soft) Redis dependency on redis‑cache (timeout 50‑200 ms). (`dep:auth-service->redis-cache`, `dep:orders-service->redis-cache`, `dep:portfolio-service->redis-cache`, `dep:market-data-service->redis-cache`)
**Assumptions:**
- ASM-11: No deploy or config change on orders‑service or portfolio‑service in the window.
- ASM-12: The “unknown workload” is not captured in the automated change log (e.g., cron, manual pg_dump, feature‑flag flip).
- ASM-13: The Redis fail‑over did not cause the postgres‑orders saturation (they are independent).
**Objections:**
- [minor] gap_unaddressed: Requires pg_stat_statements snapshot around 10:12‑10:15 UTC to confirm new heavy sort/hash queries; not available via current tools.
- [minor] alternative_not_excluded: HYP‑1 still offers a possible mechanism (work_mem amplification) though its timing prediction failed; not fully excluded.

### 2. `infrastructure_failure` on **redis-cache** (HYP-2)

Confidence 0.50 (medium), critic: reject, capped from 0.52: it has unresolved blocking objections. The Redis master went down at 10:12:03 UTC and a replica was promoted with incomplete resync, causing loss of session keys stored in Redis. Auth‑service treats missing sessions as “session not found” and forces re‑login, generating the logout wave. The same Redis loss adds latency to services that use it as a soft cache (orders‑service, portfolio‑service), but the magnitude of their latency spikes is far larger than can be explained by cache loss alone.

**Supporting:**
- Auth‑service emitted 665 WARN logs “session <session> not found in redis; forcing re‑login” between 10:12:36.674Z and 10:39:52.999Z. (`log:26d7a4550ba6`)
- Auth‑service error_rate mean 0.002015 vs baseline 0.001785; latency_p99 mean 262.2 ms vs baseline 258.2 ms over the window. (`metric:auth-service/error_rate`, `metric:auth-service/latency_p99_ms`)
- Redis‑cache sentinel reported master down (+sdown) at 10:12:03.988Z, a replica promotion with incomplete resync at 10:12:31.369Z, and master switch at 10:12:37.618Z. (`log:f58ca7278052`, `log:1eb56e1358d5`, `log:48f2fea2df36`)
- Redis‑cache sentinel reported master down (+sdown) at 10:12:03.988Z, a replica promotion with incomplete resync at 10:12:31.369Z, and master switch at 10:12:37.618Z. (`log:f58ca7278052`, `log:1eb56e1358d5`, `log:48f2fea2df36`)
- Change census query for redis‑cache between 09:30 UTC and 10:15 UTC returned no changes (config, feature‑flag, secret‑rotation, infra, or deploy). (`chg:2519`)
- Auth‑service, orders‑service, portfolio‑service, and market‑data‑service each have a direct (soft) Redis dependency on redis‑cache (timeout 50‑200 ms). (`dep:auth-service->redis-cache`, `dep:orders-service->redis-cache`, `dep:portfolio-service->redis-cache`, `dep:market-data-service->redis-cache`)
**Contradicting:**
- postgres-orders cpu_util rose from 0.36 at 09:30 UTC to 0.95 at 10:40 UTC, well above its baseline mean of 0.34. (`metric:postgres-orders/cpu_util`)
- postgres-orders query_latency_p99_ms increased from 19 ms at 09:30 UTC to 1,067 ms at 10:40 UTC (baseline ≈ 18 ms). (`metric:postgres-orders/query_latency_p99_ms`)
- postgres-orders active_connections grew from ~70 to ~175 (baseline ≈ 73). (`metric:postgres-orders/active_connections`)
- portfolio-service latency_p99_ms climbed from 394 ms at 09:30 UTC to 2,780 ms at 10:40 UTC (baseline ≈ 424 ms). (`metric:portfolio-service/latency_p99_ms`)
- portfolio-service error_rate rose from 0.0014 to 0.0478 (baseline ≈ 0.0022). (`metric:portfolio-service/error_rate`)
- orders-service latency_p99_ms increased from 274 ms to 1,606 ms (baseline ≈ 253 ms). (`metric:orders-service/latency_p99_ms`)
- orders-service error_rate rose from 0.0017 to 0.0248 (baseline ≈ 0.0018). (`metric:orders-service/error_rate`)
- postgres‑orders is a direct hard SQL dependency (2 s timeout) of both orders‑service and portfolio‑service; edge‑gateway calls those two services (hard HTTP, 3 s). auth‑service has no upstream path to postgres‑orders. (`dep:orders-service->postgres-orders`, `dep:portfolio-service->postgres-orders`, `dep:edge-gateway->orders-service`, `dep:edge-gateway->portfolio-service`)
**Assumptions:**
- ASM-2: The Redis master‑down / incomplete‑resync event caused loss of session keys, which auth‑service treats as “session not found” and forces re‑login.
- ASM-3: Portfolio‑service’s soft Redis dependency is used only for caching; loss of the cache can increase latency modestly but cannot generate the 7× latency jump seen in OBS‑6/7.
**Objections:**
- [blocking] ignores_contradiction: Does not explain postgres‑orders CPU ≈100%, query latency >1 s, and connection surge (OBS‑3/4/5/20/21/22) nor the downstream service latency spikes.
- [blocking] alternative_not_excluded: HYP‑4 provides a coherent explanation for both the DB saturation and the Redis‑failover logouts; HYP‑2 has not ruled it out.

### 3. `config_change` on **postgres-orders**, triggered by `chg:2519` (HYP-1)

Confidence 0.48 (low), critic: challenge. Raising work_mem from 4 MiB to 8 MiB allows queries that perform large sorts or hashes to allocate twice as much memory. When a workload that issues such queries starts (≈10:12 UTC) the extra memory pressure appears as higher CPU, longer query latency and a spike in active connections, which then propagates over the hard‑SQL dependency to orders‑service and portfolio‑service.

**Supporting:**
- config on postgres-orders at 09:31:44 UTC by marta.silva: Raise work_mem for reporting queries (work_mem: 4MB -> 8MB, applied: reload) (`chg:2519`)
- At 09:31:44 UTC the postgres‑orders configuration was changed: work_mem raised from 4 MB to 8 MB (reload). (`chg:2519`)
- No other config, feature‑flag, secret‑rotation, or infra changes were recorded for postgres‑orders, orders‑service, portfolio‑service, edge‑gateway, or auth‑service between 09:30 UTC and 10:40 UTC. (`chg:2519`)
- postgres-orders cpu_util rose from 0.36 at 09:30 UTC to 0.95 at 10:40 UTC, well above its baseline mean of 0.34. (`metric:postgres-orders/cpu_util`)
- postgres-orders query_latency_p99_ms increased from 19 ms at 09:30 UTC to 1,067 ms at 10:40 UTC (baseline ≈ 18 ms). (`metric:postgres-orders/query_latency_p99_ms`)
- postgres-orders active_connections grew from ~70 to ~175 (baseline ≈ 73). (`metric:postgres-orders/active_connections`)
- portfolio-service latency_p99_ms climbed from 394 ms at 09:30 UTC to 2,780 ms at 10:40 UTC (baseline ≈ 424 ms). (`metric:portfolio-service/latency_p99_ms`)
- portfolio-service error_rate rose from 0.0014 to 0.0478 (baseline ≈ 0.0022). (`metric:portfolio-service/error_rate`)
- orders-service latency_p99_ms increased from 274 ms to 1,606 ms (baseline ≈ 253 ms). (`metric:orders-service/latency_p99_ms`)
- orders-service error_rate rose from 0.0017 to 0.0248 (baseline ≈ 0.0018). (`metric:orders-service/error_rate`)
- postgres‑orders is a direct hard SQL dependency (2 s timeout) of both orders‑service and portfolio‑service; edge‑gateway calls those two services (hard HTTP, 3 s). auth‑service has no upstream path to postgres‑orders. (`dep:orders-service->postgres-orders`, `dep:portfolio-service->postgres-orders`, `dep:edge-gateway->orders-service`, `dep:edge-gateway->portfolio-service`)
- The incident symptoms (portfolio p99 >2.5 s, postgres‑orders CPU ≈100 %, user log‑outs) were reported starting ~10:13 UTC, roughly 42 minutes after the work_mem change. (`chg:2519`)
**Contradicting:**
- postgres‑orders cpu_util stayed near its baseline (≈0.34‑0.41) from 09:30 through 10:09, then rose to 0.571 at 10:12 and 0.972 at 10:15, remaining ≥0.95 through 10:39. (`metric:postgres-orders/cpu_util`)
- postgres‑orders query_latency_p99_ms was stable around 17‑20 ms until 10:09, then spiked to 100 ms at 10:12, 737 ms at 10:15 and stayed in the 800‑1,067 ms range thereafter. (`metric:postgres-orders/query_latency_p99_ms`)
- postgres‑orders active_connections hovered around 70‑85 until 10:09, then jumped to 112 at 10:12, 193 at 10:15 and remained near 180‑190 through 10:39. (`metric:postgres-orders/active_connections`)
- Auth‑service emitted 665 WARN logs “session <session> not found in redis; forcing re‑login” between 10:12:36.674Z and 10:39:52.999Z. (`log:26d7a4550ba6`)
- Auth‑service error_rate mean 0.002015 vs baseline 0.001785; latency_p99 mean 262.2 ms vs baseline 258.2 ms over the window. (`metric:auth-service/error_rate`, `metric:auth-service/latency_p99_ms`)
- Redis‑cache sentinel reported master down (+sdown) at 10:12:03.988Z, a replica promotion with incomplete resync at 10:12:31.369Z, and master switch at 10:12:37.618Z. (`log:f58ca7278052`, `log:1eb56e1358d5`, `log:48f2fea2df36`)
- Redis‑cache sentinel reported master down (+sdown) at 10:12:03.988Z, a replica promotion with incomplete resync at 10:12:31.369Z, and master switch at 10:12:37.618Z. (`log:f58ca7278052`, `log:1eb56e1358d5`, `log:48f2fea2df36`)
- Change census query for redis‑cache between 09:30 UTC and 10:15 UTC returned no changes (config, feature‑flag, secret‑rotation, infra, or deploy). (`chg:2519`)
- Auth‑service, orders‑service, portfolio‑service, and market‑data‑service each have a direct (soft) Redis dependency on redis‑cache (timeout 50‑200 ms). (`dep:auth-service->redis-cache`, `dep:orders-service->redis-cache`, `dep:portfolio-service->redis-cache`, `dep:market-data-service->redis-cache`)
**Assumptions:**
- ASM-5: No other config, feature‑flag, secret rotation, or infra change on postgres‑orders between 09:30‑10:40 UTC.
- ASM-6: Only queries that perform large sorts or hashes can consume the extra work_mem.
- ASM-7: A workload that performs such heavy sorts started around 10:12 UTC (cron job, batch, or untracked feature flag).
**Objections:**
- [blocking] temporal_violation: Prediction that CPU should rise at/after 09:31 UTC contradicts observed stability until 10:12 UTC (OBS‑20/21/22).
- [minor] gap_unaddressed: No per‑query CPU/memory data (pg_stat_statements) to show whether the work_mem increase amplified existing queries; tooling cannot provide this.

### 4. `infrastructure_failure` on **redis-cache**, triggered by `log:f58ca7278052` (HYP-3)

Confidence 0.42 (low), critic: reject. The Redis master was marked down at 10:12:03 UTC, a replica was promoted with incomplete resync, and the master switch completed at 10:12:37 UTC. Session keys stored only on the lost master disappear; auth‑service therefore logs “session not found” and forces re‑login. Services that use Redis as a soft cache (orders‑service, portfolio‑service, market‑data‑service) see a modest latency increase, but the observed 2.5 s+ portfolio p99 cannot be explained by cache loss alone.

**Supporting:**
- Auth‑service emitted 665 WARN logs “session <session> not found in redis; forcing re‑login” between 10:12:36.674Z and 10:39:52.999Z. (`log:26d7a4550ba6`)
- Auth‑service error_rate mean 0.002015 vs baseline 0.001785; latency_p99 mean 262.2 ms vs baseline 258.2 ms over the window. (`metric:auth-service/error_rate`, `metric:auth-service/latency_p99_ms`)
- Redis‑cache sentinel reported master down (+sdown) at 10:12:03.988Z, a replica promotion with incomplete resync at 10:12:31.369Z, and master switch at 10:12:37.618Z. (`log:f58ca7278052`, `log:1eb56e1358d5`, `log:48f2fea2df36`)
- Redis‑cache sentinel reported master down (+sdown) at 10:12:03.988Z, a replica promotion with incomplete resync at 10:12:31.369Z, and master switch at 10:12:37.618Z. (`log:f58ca7278052`, `log:1eb56e1358d5`, `log:48f2fea2df36`)
- Change census query for redis‑cache between 09:30 UTC and 10:15 UTC returned no changes (config, feature‑flag, secret‑rotation, infra, or deploy). (`chg:2519`)
- Auth‑service, orders‑service, portfolio‑service, and market‑data‑service each have a direct (soft) Redis dependency on redis‑cache (timeout 50‑200 ms). (`dep:auth-service->redis-cache`, `dep:orders-service->redis-cache`, `dep:portfolio-service->redis-cache`, `dep:market-data-service->redis-cache`)
**Contradicting:**
- postgres-orders cpu_util rose from 0.36 at 09:30 UTC to 0.95 at 10:40 UTC, well above its baseline mean of 0.34. (`metric:postgres-orders/cpu_util`)
- postgres-orders query_latency_p99_ms increased from 19 ms at 09:30 UTC to 1,067 ms at 10:40 UTC (baseline ≈ 18 ms). (`metric:postgres-orders/query_latency_p99_ms`)
- postgres-orders active_connections grew from ~70 to ~175 (baseline ≈ 73). (`metric:postgres-orders/active_connections`)
- portfolio-service latency_p99_ms climbed from 394 ms at 09:30 UTC to 2,780 ms at 10:40 UTC (baseline ≈ 424 ms). (`metric:portfolio-service/latency_p99_ms`)
- portfolio-service error_rate rose from 0.0014 to 0.0478 (baseline ≈ 0.0022). (`metric:portfolio-service/error_rate`)
- orders-service latency_p99_ms increased from 274 ms to 1,606 ms (baseline ≈ 253 ms). (`metric:orders-service/latency_p99_ms`)
- orders-service error_rate rose from 0.0017 to 0.0248 (baseline ≈ 0.0018). (`metric:orders-service/error_rate`)
- postgres‑orders is a direct hard SQL dependency (2 s timeout) of both orders‑service and portfolio‑service; edge‑gateway calls those two services (hard HTTP, 3 s). auth‑service has no upstream path to postgres‑orders. (`dep:orders-service->postgres-orders`, `dep:portfolio-service->postgres-orders`, `dep:edge-gateway->orders-service`, `dep:edge-gateway->portfolio-service`)
**Assumptions:**
- ASM-8: The Redis master loss was not triggered by a recorded config change.
- ASM-9: Session data lives only in Redis with no fallback store.
- ASM-10: The incomplete replica resync caused loss of a non‑trivial fraction of active sessions.
**Objections:**
- [blocking] unsupported_claim: names log:f58ca7278052 as the trigger, but no change-history query returned it
- [blocking] unsupported_claim: Cites log:f58ca7278052 as trigger, but change‑census shows no change record for that log entry.
- [blocking] ignores_contradiction: Same missing explanation for postgres‑orders saturation as HYP‑2.
- [blocking] alternative_not_excluded: HYP‑4 remains a viable alternative covering all symptoms.

## Recommended actions

| Urgency | Kind | Action | Why |
|---|---|---|---|
| now | mitigate | Add read‑replica capacity or temporarily increase CPU limits for postgres‑orders and enable connection‑pool throttling to bring CPU below saturation. | HYP‑4 predicts the DB is the primary bottleneck; reducing load now restores service latency while root cause is investigated. (HYP-4) |
| now | mitigate | Force a clean Redis failover (promote a fully synced replica) and verify session persistence to stop further forced logouts. | HYP‑2 links the logout wave to the incomplete Redis promotion; a healthy replica eliminates the session‑loss path. (HYP-2) |
| soon | fix | Revert the work_mem change (chg:2519) from 8 MiB back to 4 MiB and monitor postgres‑orders CPU and latency. | HYP‑1 and HYP‑4 both implicate the work_mem increase as an amplifier; reverting tests whether it is necessary for the saturation. (HYP-1) |
| soon | fix | Configure max_connections and statement_timeout on postgres‑orders to prevent connection storms from overwhelming the instance. | HYP‑4 shows a rapid rise in active connections; hard limits stop future storms. (HYP-4) |
| later | prevent | Enable continuous pg_stat_statements collection with alerting on sudden increases in sort/hash memory usage or CPU per query. | Gap GAP‑7 and the HYP‑4 prediction require per‑query visibility to catch similar workload changes early. (HYP-4) |
| later | prevent | Add automated validation that Redis sentinel promotions only complete after full resync, and alert on incomplete promotions. | HYP‑2/HYP‑3 identify the incomplete resync as the cause of session loss; preventing it stops future logout waves. (HYP-2) |
| soon | investigate | Retrieve a pg_stat_statements snapshot for postgres‑orders covering 10:12‑10:15 UTC to identify the heavy sort/hash queries. | Directly tests the HYP‑4 prediction and closes GAP‑7/GAP‑9. (HYP-4) |
| soon | investigate | Collect redis‑cache metrics (CPU, memory, connected_clients, keyspace_hits/misses) for 09:30‑10:40 UTC. | Needed to confirm or refute pre‑failover saturation predicted by HYP‑2 (GAP‑5, GAP‑13, GAP‑15). (HYP-2) |
| later | investigate | Query deploy history for orders‑service and portfolio‑service between 09:30‑10:40 UTC. | A code deploy could have introduced the new query pattern mentioned in HYP‑4 (GAP‑8). (HYP-4) |
| later | investigate | Obtain edge‑gateway latency_p99_ms and 5xx error_rate for 09:30‑10:40 UTC. | Closes GAP‑1 and GAP‑4 to see whether gateway‑level errors correlate with auth‑service logouts or DB latency. |

## Evidence gaps

- **query_metrics** (edge-gateway latency_p99_ms and error_rate (5xx) for 09:30‑10:40 UTC): Metrics for edge-gateway were not requested; cannot confirm gateway‑level latency/5xx rise.
- **query_logs** (WARN/ERROR log patterns for portfolio-service, orders-service, postgres-orders, edge-gateway): No log queries executed; missing direct evidence of SQL errors, authentication failures, or gateway rejections.
- **query_metrics** (Per‑minute points for postgres-orders cpu_util, query_latency_p99_ms, active_connections to pinpoint exact onset minute): Only summary (first/last) values available; precise onset time remains uncertain.
- **query_logs** (edge-gateway WARN/ERROR patterns 09:30‑10:40 UTC): Not queried; needed to see if gateway surfaced auth failures to clients.
- **query_metrics** (redis-cache CPU, memory, connected_clients, keyspace_hits/misses 09:30‑10:40 UTC): Not queried; would show saturation or resource pressure before failover.
- **query_metrics** (auth-service latency_p99_ms and error_rate at 1‑minute resolution 10:10‑10:20 UTC): Only summary stats retrieved; per‑minute points needed to align onset with Redis failover.
- **metrics** (per‑query CPU and memory usage on postgres‑orders (pg_stat_statements, pg_stat_activity) for 09:30‑10:40 UTC): Needed to prove whether the work_mem increase caused the CPU saturation.
- **changes** (deploy history for orders‑service and portfolio‑service between 09:30‑10:40 UTC): A code deploy could have introduced heavier queries that only manifest after the work_mem change.
- **observability** (real‑time pg_stat_statements snapshot around 10:13 UTC): To identify which queries dominate CPU at the moment of slowdown.
- **observability** (auth‑service request‑rate and error‑rate for 09:30‑10:40 UTC): To determine if forced log‑outs are a downstream effect of portfolio timeouts.
- **get_change_history** (redis‑cache configuration, feature‑flag, secret‑rotation, infra, or deploy records): The change‑census returned an empty list for redis‑cache, but it is possible that a manual operational action (e.g., a Sentinel‑initiated failover, a rolling restart, or a capacity‑scale event) is not captured in the automated change log.
- **query_metrics** (per‑minute resolution for cpu_util, query_latency_p99_ms, active_connections): API limited series to 30 points, forcing a 3‑minute step; finer granularity would pinpoint the exact minute of onset.
- **query_metrics** (redis‑cache memory, connected_clients, keyspace_hits, keyspace_misses (09:30‑10:40)): Metric series not available or not returned by the metrics store.
- **query_metrics** (auth‑service latency_p99_ms and error_rate (10:10‑10:20)): Metric series not returned for the requested window.
- **query_metrics** (redis‑cache cpu_util after 10:00 UTC): Only data up to 09:59 UTC was returned; later points missing.

## Open questions

- Which specific query (or set of queries) caused the sudden CPU and connection surge on postgres‑orders at 10:12 UTC?
- Did the Redis master loss and incomplete resync contribute measurably to the portfolio‑service latency spike, or was the DB saturation the sole driver?
- Was the work_mem increase alone sufficient to cause saturation, or did it require a concurrent workload change (e.g., a scheduled job or feature‑flag rollout)?
- What triggered the new heavy‑query workload at ~10:12 UTC (scheduled reporting job, batch process, traffic spike, deploy, etc.)?
- Were the forced logouts solely due to lost Redis session keys, or did downstream timeouts from the DB latency cause auth‑service to treat sessions as missing?
- Is there any operational action on Redis (manual failover, rolling restart, capacity scale) not captured in the automated change log that could explain the master loss?

## How the investigation ran

Stopped because time budget reached, after 2 round(s): 36 model calls, 19 tool calls, 175,182 tokens, 975 s.
