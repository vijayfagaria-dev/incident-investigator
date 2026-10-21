# T02: Portfolio pages slow and failing

**Outcome:** conclusive. Root cause: `dependency_degradation` on **market-data-service**

## Summary

Portfolio and positions pages became slow and error‑prone beginning ~14:41 UTC when the external quotes‑vendor latency rose sharply, causing market‑data‑service HTTPS calls (800 ms timeout) to time out and its circuit breaker to go half‑open. Downstream callers – portfolio‑service (gRPC 500 ms timeout) and orders‑service – received DEADLINE_EXCEEDED errors, which manifested as >2 s p99 latency, 5xx errors, and order rejections. The portfolio‑service v5.4.0 deploy occurred at 14:48 UTC, after the degradation had already started, and was ruled out as the primary cause. Confidence in the vendor‑latency hypothesis (HYP‑1) is moderate (≈0.62). The exact reason for the vendor slowdown (throttling, internal outage, network path) remains unknown.

## Hypotheses

### 1. `dependency_degradation` on **market-data-service** (HYP-1)

Confidence 0.62 (medium), critic: accept. An increase in latency or throttling at the external quotes‑vendor caused market‑data‑service HTTPS calls (800 ms timeout) to time out. The service’s circuit breaker went half‑open, so downstream callers (portfolio‑service via gRPC 500 ms timeout and orders‑service) received DEADLINE_EXCEEDED errors. This cascaded into elevated portfolio‑service latency and 5xx errors, and order rejections at orders‑service.

**Supporting:**
- market‑data‑service began logging quotes‑vendor request timeouts (800 ms) at 14:41:01 UTC; 1,072 occurrences through 15:04:59 UTC. (`log:785c94c54006`)
- market‑data‑service circuit to quotes‑vendor went half‑open at 14:47:02 UTC and stayed half‑open through 15:04:50 UTC (78 events). (`log:a9fa5c6b6926`)
- Portfolio‑service began logging gRPC DEADLINE_EXCEEDED errors to market‑data‑service at 14:42:01 UTC (679 occurrences through 15:04:59 UTC). (`log:3096c4afe74b`)
- First portfolio‑service gRPC DEADLINE_EXCEEDED to market‑data‑service logged at 14:42:01 UTC; 679 occurrences through 15:04:59 UTC. (`log:3096c4afe74b`)
- WARN log pattern “price check for order <order> failed: market-data-service DEADLINE_EXCEEDED; rejecting” appears first at 14:42:01 UTC and persists until 15:04:53 UTC (178 occurrences). (`log:6f37ccdbcbc1`)
- Error rate metric rises from a baseline mean of 0.0019 to a window mean of 0.0108 (peak 0.0265), a ~5× increase. (`metric:orders-service/error_rate`)
- At 14:45 UTC portfolio‑service p99 latency was 2,906 ms (baseline ~497 ms) and remained >2 s for the entire 14:45‑15:09 window, peaking at 3,513 ms at 14:53 UTC. (`metric:portfolio-service/latency_p99_ms`)
- At 14:45 UTC portfolio‑service error‑rate was 0.0683 (baseline ~0.0038) and stayed elevated (0.046‑0.074) through 15:09 UTC. (`metric:portfolio-service/error_rate`)
- The v5.4.0 deploy of portfolio‑service occurred at 14:48:30 UTC, after both latency and error‑rate were already spiked (first metric points at 14:45‑14:47 show the elevation). (`chg:2512`, `metric:portfolio-service/latency_p99_ms`, `metric:portfolio-service/error_rate`)
- Baseline (14:35‑14:39) latency_p99 ≈ 253 ms and error_rate ≈ 0.002 (baseline_mean). (`metric:market-data-service/latency_p99_ms`, `metric:market-data-service/error_rate`)
- First latency jump at 14:41 UTC: p99 rose from 272 ms (14:39) to 1,064 ms (≈4× baseline). (`metric:market-data-service/latency_p99_ms`)
- First error‑rate rise at 14:41 UTC: error_rate increased to 0.0073 (≈3.7× baseline). (`metric:market-data-service/error_rate`)
- Sustained degradation: latency stayed >1.6 s (peak 2,399 ms at 14:47) and error_rate climbed to 0.0456 (≈23× baseline) at 14:55, remaining >0.02 through 15:09. (`metric:market-data-service/latency_p99_ms`, `metric:market-data-service/error_rate`)
- Baseline (14:30‑14:38) latency_p99 ≈ 250 ms and error_rate ≈ 0.002. (`metric:market-data-service/latency_p99_ms`, `metric:market-data-service/error_rate`)
- First latency increase at 14:40 UTC: p99 rose to 463 ms (≈2× baseline) while error_rate remained near baseline. (`metric:market-data-service/latency_p99_ms`, `metric:market-data-service/error_rate`)
- Sharp degradation onset at 14:42 UTC: latency_p99 spiked to 1,644 ms (≈6× baseline) and error_rate rose to 0.019 (≈10× baseline). (`metric:market-data-service/latency_p99_ms`, `metric:market-data-service/error_rate`)
- Sustained high latency: p99 stayed >1.6 s for the remainder of the window, peaking at 2,148 ms at 14:46 UTC. (`metric:market-data-service/latency_p99_ms`)
- Error_rate peaked at 0.0456 (≈23× baseline) at 14:54 UTC and remained above 0.02 through 15:09 UTC. (`metric:market-data-service/error_rate`)
**Contradicting:**
- No other deploy, config, feature‑flag, secret rotation, or infra changes were returned for market-data-service, orders-service, edge-gateway, postgres-orders, redis-cache, or quotes-vendor in the 14:20‑15:05 window. (`chg:2512`)
**Assumptions:**
- ASM-6: The quotes‑vendor experienced increased latency or rate‑limiting around 14:40 UTC.
- ASM-7: Portfolio‑service latency spike is fully explained by downstream market‑data‑service timeouts, not by the v5.4.0 code change.

### 2. `code_regression` on **portfolio-service**, triggered by `chg:2512` (HYP-2)

Confidence 0.22 (low), critic: reject. The v5.4.0 deploy added a sector‑breakdown feature that introduced a slower code path (e.g., extra DB query or cache miss) which increased the time spent in the market‑data‑service gRPC call and/or postgres‑orders, pushing p99 latency above the gateway timeout and raising error rates.

**Supporting:**
- deploy on portfolio-service at 14:48:30 UTC by ci/deploy-bot: portfolio-service v5.4.0: add sector breakdown to performance page (version: 5.4.0, previous_version: 5.3.2, commit: 3c7d0aa, diff: +410 / -88) (`chg:2512`)
- portfolio-service v5.4.0 was deployed at 2026-10-06T14:48:30Z (chg:2512). (`chg:2512`)
- The deploy occurred ~17 minutes before the incident was reported at 15:05, placing it inside a plausible causation window. (`chg:2512`)
- portfolio‑service deploy v5.4.0 recorded at 14:48:30 UTC (after the latency/error onset). (`chg:2512`)
- portfolio‑service error_rate rose from a baseline mean of 0.0022 to a peak of 0.074 (mean 0.030) during the window. (`metric:portfolio-service/error_rate`)
- portfolio‑service p99 latency jumped from a baseline of ~415 ms to a maximum of 3.5 s (mean 1.6 s, last 3.1 s). (`metric:portfolio-service/latency_p99_ms`)
- At 14:45 UTC portfolio‑service p99 latency was 2,906 ms (baseline ~497 ms) and remained >2 s for the entire 14:45‑15:09 window, peaking at 3,513 ms at 14:53 UTC. (`metric:portfolio-service/latency_p99_ms`)
- At 14:45 UTC portfolio‑service error‑rate was 0.0683 (baseline ~0.0038) and stayed elevated (0.046‑0.074) through 15:09 UTC. (`metric:portfolio-service/error_rate`)
**Contradicting:**
- The v5.4.0 deploy of portfolio‑service occurred at 14:48:30 UTC, after both latency and error‑rate were already spiked (first metric points at 14:45‑14:47 show the elevation). (`chg:2512`, `metric:portfolio-service/latency_p99_ms`, `metric:portfolio-service/error_rate`)
**Assumptions:**
- ASM-3: The v5.4.0 diff may contain hidden changes (new DB query, cache key, extra gRPC call) that could worsen an existing problem.
**Objections:**
- [blocking] temporal_violation: Portfolio‑service v5.4.0 deployed at 14:48 UTC, after latency/error spikes began at 14:41‑14:45 UTC (OBS‑24).

### 3. `infrastructure_failure` on **infrastructure** (HYP-5)

Confidence 0.18 (low), critic: challenge. A transient network or routing issue between market‑data‑service and the quotes‑vendor increased round‑trip latency beyond the 800 ms timeout, causing the same cascade of DEADLINE_EXCEEDED errors to portfolio‑service and orders‑service.

**Supporting:**
- market‑data‑service began logging quotes‑vendor request timeouts (800 ms) at 14:41:01 UTC; 1,072 occurrences through 15:04:59 UTC. (`log:785c94c54006`)
- market‑data‑service circuit to quotes‑vendor went half‑open at 14:47:02 UTC and stayed half‑open through 15:04:50 UTC (78 events). (`log:a9fa5c6b6926`)
- Portfolio‑service began logging gRPC DEADLINE_EXCEEDED errors to market‑data‑service at 14:42:01 UTC (679 occurrences through 15:04:59 UTC). (`log:3096c4afe74b`)
- First portfolio‑service gRPC DEADLINE_EXCEEDED to market‑data‑service logged at 14:42:01 UTC; 679 occurrences through 15:04:59 UTC. (`log:3096c4afe74b`)
- WARN log pattern “price check for order <order> failed: market-data-service DEADLINE_EXCEEDED; rejecting” appears first at 14:42:01 UTC and persists until 15:04:53 UTC (178 occurrences). (`log:6f37ccdbcbc1`)
- Error rate metric rises from a baseline mean of 0.0019 to a window mean of 0.0108 (peak 0.0265), a ~5× increase. (`metric:orders-service/error_rate`)
- At 14:45 UTC portfolio‑service p99 latency was 2,906 ms (baseline ~497 ms) and remained >2 s for the entire 14:45‑15:09 window, peaking at 3,513 ms at 14:53 UTC. (`metric:portfolio-service/latency_p99_ms`)
- At 14:45 UTC portfolio‑service error‑rate was 0.0683 (baseline ~0.0038) and stayed elevated (0.046‑0.074) through 15:09 UTC. (`metric:portfolio-service/error_rate`)
- Baseline (14:35‑14:39) latency_p99 ≈ 253 ms and error_rate ≈ 0.002 (baseline_mean). (`metric:market-data-service/latency_p99_ms`, `metric:market-data-service/error_rate`)
- First latency jump at 14:41 UTC: p99 rose from 272 ms (14:39) to 1,064 ms (≈4× baseline). (`metric:market-data-service/latency_p99_ms`)
- First error‑rate rise at 14:41 UTC: error_rate increased to 0.0073 (≈3.7× baseline). (`metric:market-data-service/error_rate`)
- Sustained degradation: latency stayed >1.6 s (peak 2,399 ms at 14:47) and error_rate climbed to 0.0456 (≈23× baseline) at 14:55, remaining >0.02 through 15:09. (`metric:market-data-service/latency_p99_ms`, `metric:market-data-service/error_rate`)
- Baseline (14:30‑14:38) latency_p99 ≈ 250 ms and error_rate ≈ 0.002. (`metric:market-data-service/latency_p99_ms`, `metric:market-data-service/error_rate`)
- First latency increase at 14:40 UTC: p99 rose to 463 ms (≈2× baseline) while error_rate remained near baseline. (`metric:market-data-service/latency_p99_ms`, `metric:market-data-service/error_rate`)
- Sharp degradation onset at 14:42 UTC: latency_p99 spiked to 1,644 ms (≈6× baseline) and error_rate rose to 0.019 (≈10× baseline). (`metric:market-data-service/latency_p99_ms`, `metric:market-data-service/error_rate`)
- Sustained high latency: p99 stayed >1.6 s for the remainder of the window, peaking at 2,148 ms at 14:46 UTC. (`metric:market-data-service/latency_p99_ms`)
- Error_rate peaked at 0.0456 (≈23× baseline) at 14:54 UTC and remained above 0.02 through 15:09 UTC. (`metric:market-data-service/error_rate`)
**Assumptions:**
- ASM-8: A transient network degradation occurred on the path from market‑data‑service to quotes‑vendor.
**Objections:**
- [minor] alternative_not_excluded: HYP‑1 (quotes‑vendor latency/throttling) explains all observed symptoms with direct log and metric evidence; a generic network failure has not been ruled out but lacks supporting data.

### 4. `resource_exhaustion` on **market-data-service** (HYP-3)

Confidence 0.07 (low), critic: reject. A sudden burst of requests (perhaps from portfolio‑service) exhausted market‑data‑service thread‑pool or connection‑pool, causing its outbound HTTPS calls to quotes‑vendor to timeout and the circuit breaker to half‑open.

**Supporting:**
- market‑data‑service began logging quotes‑vendor request timeouts (800 ms) at 14:41:01 UTC; 1,072 occurrences through 15:04:59 UTC. (`log:785c94c54006`)
- market‑data‑service circuit to quotes‑vendor went half‑open at 14:47:02 UTC and stayed half‑open through 15:04:50 UTC (78 events). (`log:a9fa5c6b6926`)
- First portfolio‑service gRPC DEADLINE_EXCEEDED to market‑data‑service logged at 14:42:01 UTC; 679 occurrences through 15:04:59 UTC. (`log:3096c4afe74b`)
- Portfolio‑service began logging gRPC DEADLINE_EXCEEDED errors to market‑data‑service at 14:42:01 UTC (679 occurrences through 15:04:59 UTC). (`log:3096c4afe74b`)
**Contradicting:**
- No other deploy, config, feature‑flag, secret rotation, or infra changes were returned for market-data-service, orders-service, edge-gateway, postgres-orders, redis-cache, or quotes-vendor in the 14:20‑15:05 window. (`chg:2512`)
- p99 latency stays near baseline (baseline 266 ms, window mean 259 ms, max 332 ms) – no major latency regression locally. (`metric:orders-service/latency_p99_ms`)
- CPU, memory, DB pool usage, RPS and DB queries per request all remain within baseline ranges. (`metric:orders-service/cpu_util`, `metric:orders-service/mem_util`, `metric:orders-service/db_pool_in_use`, `metric:orders-service/rps`, `metric:orders-service/db_queries_per_request`)
**Assumptions:**
- ASM-4: A sudden burst of requests from portfolio‑service could have saturated market‑data‑service resources.
**Objections:**
- [blocking] ignores_contradiction: Market‑data‑service logs show quotes‑vendor request timeouts and circuit‑breaker half‑open (OBS‑19, OBS‑20, OBS‑25, OBS‑26), indicating an external dependency problem rather than internal resource exhaustion.

### 5. `config_change` on **orders-service** (HYP-4)

Confidence 0.07 (low), critic: reject. A silent configuration change (e.g., lowered circuit‑breaker timeout or stricter validation flag) made orders‑service reject orders when market‑data‑service latency rose, producing the observed error‑rate increase without affecting its own latency.

**Supporting:**
- WARN log pattern “price check for order <order> failed: market-data-service DEADLINE_EXCEEDED; rejecting” appears first at 14:42:01 UTC and persists until 15:04:53 UTC (178 occurrences). (`log:6f37ccdbcbc1`)
- Error rate metric rises from a baseline mean of 0.0019 to a window mean of 0.0108 (peak 0.0265), a ~5× increase. (`metric:orders-service/error_rate`)
**Contradicting:**
- p99 latency stays near baseline (baseline 266 ms, window mean 259 ms, max 332 ms) – no major latency regression locally. (`metric:orders-service/latency_p99_ms`)
- No other deploy, config, feature‑flag, secret rotation, or infra changes were returned for market-data-service, orders-service, edge-gateway, postgres-orders, redis-cache, or quotes-vendor in the 14:20‑15:05 window. (`chg:2512`)
**Assumptions:**
- ASM-5: A silent config toggle or feature‑flag change on orders‑service altered its rejection threshold just before 14:42 UTC.
**Objections:**
- [blocking] unsupported_claim: No deploy, config change, feature‑flag toggle, or secret rotation recorded for orders‑service in the relevant window (OBS‑9).

## Recommended actions

| Urgency | Kind | Action | Why |
|---|---|---|---|
| now | mitigate | Increase the market‑data‑service → quotes‑vendor timeout and/or add a short‑circuit fallback (e.g., cached quote) to prevent cascading DEADLINE_EXCEEDED errors. | Current 800 ms timeout is too tight for observed vendor latency spikes; a higher timeout or cached fallback buys time for upstream services. (HYP-1) |
| now | mitigate | Raise portfolio‑service gRPC timeout to market‑data‑service (currently 500 ms) and implement retry/back‑off with circuit‑breaker awareness. | Portfolio‑service is the first downstream consumer; a modest timeout increase reduces 5xx errors while the vendor issue is resolved. (HYP-1) |
| soon | fix | Add explicit resilience patterns (timeout, retry, bulkhead, fallback) for the market‑data‑service → quotes‑vendor call and expose per‑dependency latency metrics. | Hard‑coded 800 ms timeout and lack of observability made the cascade invisible until it impacted customers. (HYP-1) |
| soon | prevent | Create an alert on market‑data‑service latency_p99_ms and error_rate crossing 2× baseline, and on circuit‑breaker state changes. | Early detection of vendor degradation would allow proactive mitigation before portfolio‑service SLA breach. (HYP-1) |
| soon | investigate | Obtain quotes‑vendor side metrics (latency, throttling, error rates) for the 14:30‑15:10 UTC window to confirm the root cause. | HYP‑1 assumes vendor latency/throttling; vendor data will verify or refute this and guide vendor‑side remediation. (HYP-1) |
| later | investigate | Collect network‑level metrics (RTT, packet loss) between market‑data‑service and the quotes‑vendor for the same window. | HYP‑5 (generic network failure) was not excluded; network data will determine if a routing issue contributed. (HYP-5) |
| later | investigate | Enable and collect portfolio‑service internal latency breakdown (grpc_client_latency_ms, db_latency_ms, cache_latency_ms) for future incidents. | Current metric catalog lacks per‑dependency latency; this gap prevented confirming the exact downstream bottleneck. |

## Evidence gaps

- **get_change_history** (All seven services (portfolio-service, market-data-service, orders-service, edge-gateway, postgres-orders, redis-cache, quotes-vendor) for 14:20‑15:05): Only one change (portfolio-service deploy) was returned; infra‑level changes (e.g., network config, capacity scaling, DNS) or feature‑flag toggles may not be captured in this source.
- **get_change_history** (Detailed diff of portfolio-service v5.4.0 (commit 3c7d0aa)): The change summary mentions “add sector breakdown to performance page” but the exact code paths touched (e.g., new DB queries, cache keys, external calls) are unknown.
- **get_service_dependencies** (Full transitive dependency graph beyond depth 2): Only depth 2 was queried; deeper downstream services (e.g., orders-service) could be indirectly affected but were not examined.
- **query_metrics** (orders-service Kafka consumer lag / consumer group lag): Metric not exposed in the current metrics catalogue; cannot verify if Kafka lag contributed.
- **query_logs** (market-data-service logs at WARN/ERROR): Needed to confirm the downstream timeout source but not part of assigned services.
- **query_changes** (orders-service deployment / config change history): Change census for orders-service not provided; cannot rule out a local config regression.
- **query_logs** (edge-gateway, postgres-orders, orders-service (WARN+ patterns)): Tool step limit reached; logs for these services were not fetched.
- **query_metrics** (edge-gateway, postgres-orders, orders-service (full metric summary)): Tool step limit reached; metrics for these services were not fetched.
- **query_metrics** (market-data-service latency_p99_ms and error_rate (minute granularity)): Needed to confirm upstream degradation timeline and magnitude.
- **query_metrics** (portfolio-service internal latency components (e.g., grpc_client_latency_ms, db_latency_ms, cache_latency_ms)): Would identify which downstream call dominates the >2 s p99.
- **query_metrics** (redis-cache and postgres-orders metrics (latency, error_rate, pool usage) for 14:45‑15:10): To rule out secondary contributors such as cache‑miss spikes or DB pool exhaustion.
- **query_logs** (Full changelog/diff for portfolio-service v5.4.0 beyond the brief description): To assess whether the code change could have worsened an already‑present problem.
- **query_metrics** (portfolio-service internal latency components (grpc_client_latency_ms, db_latency_ms, cache_latency_ms) 14:35‑15:10 UTC): Metrics not present in the service's exported catalog; cannot retrieve per‑dependency latency breakdown.
- **query_metrics** (market-data-service per‑minute latency_p99_ms and error_rate (14:35‑15:10)): API down‑sampled to 2‑minute steps to stay within 30 points, limiting minute‑level onset precision.
- **query_logs** (market-data-service WARN/ERROR patterns (14:35‑15:10)): Log patterns for market‑data‑service were not fetched in this step; they could confirm vendor timeout details.
- **query_metrics** (minute‑resolution latency_p99_ms and error_rate for market-data-service 14:30‑15:10 UTC): The metrics API limited the step to 2 minutes (30‑point max), so true per‑minute granularity is unavailable.
- **query_logs** (WARN/ERROR log patterns for market-data-service during 14:30‑15:10 UTC): Logs were not queried in this step; timeout/error lines and circuit‑breaker state changes are not captured here.

## Open questions

- What specific condition on the quotes‑vendor side caused the latency spike (throttling, internal outage, capacity limit)?
- Was there any transient network routing or congestion between market‑data‑service and the quotes‑vendor during 14:40‑15:10 UTC?
- Do the portfolio‑service internal latency components show the gRPC call to market‑data‑service dominating the >2 s p99, or were DB/cache calls also elevated?
- Can the quotes‑vendor provide SLA‑level metrics or incident logs for the affected period?
- Are there any configuration or capacity changes in the market‑data‑service (e.g., thread‑pool size) that could have amplified the vendor latency impact?

## How the investigation ran

Stopped because the critic accepted HYP-1, after 2 round(s): 39 model calls, 19 tool calls, 198,267 tokens, 1120 s.
