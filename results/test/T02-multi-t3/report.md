# T02: Portfolio pages slow and failing

**Outcome:** conclusive. Root cause: `dependency_degradation` on **market-data-service**

## Summary

Portfolio and positions pages became slow and error‑prone after the external quotes vendor latency rose to ~800 ms at ~14:41 UTC. Market‑data‑service calls the vendor with an 800 ms timeout, which exceeds the hard 500 ms gRPC timeout used by portfolio‑service, causing DEADLINE_EXCEEDED errors that cascade through portfolio‑service (error_rate up to 7.4 %, p99 latency >3 s) and hit the edge‑gateway 3 s hard timeout, producing 5xx responses and order rejections. The portfolio‑service v5.4.0 deploy occurred after the first vendor timeouts, so it is not the root cause. The investigation is conclusive for this chain, but the early orders‑service 5xx at 14:36 UTC and the exact code changes behind the deploy remain unexplained.

## Hypotheses

### 1. `dependency_degradation` on **market-data-service** (HYP-1)

Confidence 0.82 (high), critic: accept. External quotes‑vendor latency rose to ~800 ms (OBS‑13/15). Market‑data‑service calls the vendor with an 800 ms timeout, which exceeds the hard 500 ms gRPC timeout used by portfolio‑service (OBS‑4). Each gRPC call therefore fails with DEADLINE_EXCEEDED (OBS‑10) and propagates upstream: portfolio‑service error_rate spikes (OBS‑11) and latency_p99 climbs above the edge‑gateway 3 s hard timeout (OBS‑3, OBS‑12), producing 5xx to clients. Orders‑service also sees price‑check failures (OBS‑17). The deploy of portfolio‑service v5.4.0 occurs after the first vendor time‑outs (OBS‑14), so it cannot be the initial cause.

**Supporting:**
- portfolio-service gRPC calls to market-data-service began failing with DEADLINE_EXCEEDED at 14:42:01 UTC (679 occurrences by 15:05). (`log:3096c4afe74b`)
- market-data-service logged quotes‑vendor request timeouts (800 ms) starting at 14:41:01 UTC (1072 occurrences) and circuit‑breaker half‑open events from 14:47:02 UTC. (`log:785c94c54006`, `log:a9fa5c6b6926`)
- market-data-service began emitting quotes‑vendor request time‑outs (800 ms) at 2026-10-06T14:41:01.233Z, with 1 072 occurrences through 15:04:59. (`log:785c94c54006`)
- market-data-service circuit breaker entered half‑open state at 2026-10-06T14:47:02.904Z (78 occurrences). (`log:a9fa5c6b6926`)
- orders-service started logging price‑check failures due to market-data-service DEADLINE_EXCEEDED at 2026-10-06T14:42:01.422Z, total 178 events until 15:04:53. (`log:6f37ccdbcbc1`)
- edge-gateway calls portfolio-service over HTTP with a hard 3 s timeout. (`dep:edge-gateway->portfolio-service`)
- portfolio-service calls market-data-service via gRPC with a hard 500 ms timeout. (`dep:portfolio-service->market-data-service`)
- portfolio-service error_rate rose from a baseline of 0.0022 to a peak of 0.074 (max) and was 0.052 at 15:05 UTC. (`metric:portfolio-service/error_rate`)
- portfolio-service latency_p99_ms increased from a baseline of 415 ms to a peak of 3513 ms (mean 1588 ms) during the window, with the last measured value 3093 ms at 15:05 UTC. (`metric:portfolio-service/latency_p99_ms`)
**Contradicting:**
- portfolio-service deploy v5.4.0 occurred at 14:48:30 UTC, after the onset of gRPC failures and latency spike. (`chg:2512`)
- No config changes, feature-flag flips, secret rotations, or infra work were recorded for edge-gateway, market-data-service, postgres-orders, redis-cache, orders-service, or auth-service in the window. (`chg:2512`)
**Assumptions:**
- ASM-1: Market‑data‑service had no deploy/config/flag change in the 14:30‑15:05 window.
- ASM-2: The external quotes‑vendor latency spike (~800 ms) exceeds the 500 ms hard gRPC timeout, causing every downstream call to fail with DEADLINE_EXCEEDED.

### 2. `code_regression` on **portfolio-service**, triggered by `chg:2512` (HYP-2)

Confidence 0.38 (low), critic: challenge. Deploy v5.4.0 adds sector‑breakdown logic (+410/‑88 lines, OBS‑1/2/9). If the new code path is exercised on the /v1/portfolio endpoint (or via a feature flag not captured), it could issue extra gRPC calls to market‑data‑service and/or heavier SQL to postgres‑orders (OBS‑5, OBS‑6). This would amplify the existing vendor latency, pushing portfolio‑service latency_p99 above the edge‑gateway 3 s timeout after 14:48, raising error_rate (OBS‑11, OBS‑12).

**Supporting:**
- deploy on portfolio-service at 14:48:30 UTC by ci/deploy-bot: portfolio-service v5.4.0: add sector breakdown to performance page (version: 5.4.0, previous_version: 5.3.2, commit: 3c7d0aa, diff: +410 / -88) (`chg:2512`)
- A deploy of portfolio-service v5.4.0 was recorded at 2026-10-06T14:48:30Z (chg:2512). (`chg:2512`)
- The deploy added sector‑breakdown logic to the performance page (≈+410/−88 lines, commit 3c7d0aa). (`chg:2512`)
- portfolio-service error_rate rose from a baseline of 0.0022 to a peak of 0.074 (max) and was 0.052 at 15:05 UTC. (`metric:portfolio-service/error_rate`)
- portfolio-service latency_p99_ms increased from a baseline of 415 ms to a peak of 3513 ms (mean 1588 ms) during the window, with the last measured value 3093 ms at 15:05 UTC. (`metric:portfolio-service/latency_p99_ms`)
- portfolio-service calls postgres-orders via SQL with a hard 2 s timeout. (`dep:portfolio-service->postgres-orders`)
- portfolio-service calls redis-cache via Redis with a soft 100 ms timeout. (`dep:portfolio-service->redis-cache`)
**Contradicting:**
- portfolio-service gRPC calls to market-data-service began failing with DEADLINE_EXCEEDED at 14:42:01 UTC (679 occurrences by 15:05). (`log:3096c4afe74b`)
- market-data-service logged quotes‑vendor request timeouts (800 ms) starting at 14:41:01 UTC (1072 occurrences) and circuit‑breaker half‑open events from 14:47:02 UTC. (`log:785c94c54006`, `log:a9fa5c6b6926`)
- market-data-service began emitting quotes‑vendor request time‑outs (800 ms) at 2026-10-06T14:41:01.233Z, with 1 072 occurrences through 15:04:59. (`log:785c94c54006`)
- portfolio-service deploy v5.4.0 occurred at 14:48:30 UTC, after the onset of gRPC failures and latency spike. (`chg:2512`)
**Assumptions:**
- ASM-3: The new sector‑breakdown code is only reached on the performance‑page endpoint, not on the generic /v1/portfolio endpoint that is failing.
- ASM-4: If the new code does call market‑data‑service, it would add latency on top of the existing vendor latency but not create the initial timeout.
**Objections:**
- [blocking] temporal_violation: Portfolio‑service v5.4.0 deploy (14:48:30) occurs after the first gRPC DEADLINE_EXCEEDED (14:42) and vendor time‑outs (14:41). The cause cannot precede the effect.
- [minor] gap_unaddressed: Exact code changes (diff) and any feature‑flag enablement for the new sector‑breakdown are not known (GAP‑1, GAP‑3).

### 3. `resource_exhaustion` on **orders-service** (HYP-3)

Confidence 0.15 (low), critic: challenge. Orders‑service emits 13 HTTP 5xx starting at 14:36 (OBS‑18) and later price‑check failures caused by market‑data‑service DEADLINE_EXCEEDED (OBS‑17). A possible thread‑pool or DB‑connection‑pool saturation could cause early 5xx, which then compounds downstream via edge‑gateway (hard 3 s dependency, OBS‑7).

**Supporting:**
- orders-service emitted 13 HTTP 5xx responses (e.g., DELETE /v1/orders/{id} 503) beginning 2026-10-06T14:36:48.465Z. (`log:cdc0738b436d`)
- orders-service logged 22 “insufficient buying power” rejections spread across the whole window (first at 14:20:41). (`log:b6f43643b114`)
- edge-gateway also has hard dependencies on orders-service (3 s) and auth-service (1 s). (`dep:edge-gateway->orders-service`, `dep:edge-gateway->auth-service`)
**Contradicting:**
- orders-service started logging price‑check failures due to market-data-service DEADLINE_EXCEEDED at 2026-10-06T14:42:01.422Z, total 178 events until 15:04:53. (`log:6f37ccdbcbc1`)
- portfolio-service gRPC calls to market-data-service began failing with DEADLINE_EXCEEDED at 14:42:01 UTC (679 occurrences by 15:05). (`log:3096c4afe74b`)
- market-data-service logged quotes‑vendor request timeouts (800 ms) starting at 14:41:01 UTC (1072 occurrences) and circuit‑breaker half‑open events from 14:47:02 UTC. (`log:785c94c54006`, `log:a9fa5c6b6926`)
- No config changes, feature-flag flips, secret rotations, or infra work were recorded for edge-gateway, market-data-service, postgres-orders, redis-cache, orders-service, or auth-service in the window. (`chg:2512`)
**Assumptions:**
- ASM-5: The early orders‑service 5xx at 14:36 are unrelated to the later cascade (no metrics showing saturation).
**Objections:**
- [blocking] gap_unaddressed: Orders‑service CPU, thread‑pool, and DB‑connection‑pool metrics for 14:20‑15:05 have not been fetched (GAP‑10). Without them resource exhaustion cannot be verified.
- [minor] alternative_not_excluded: Early 5xx (14:36) could be unrelated to market‑data degradation; HYP‑1 explains later cascade but not the initial orders‑service errors.

### 4. `infrastructure_failure` on **infrastructure** (HYP-4)

Confidence 0.10 (low), critic: challenge. A transient network, DNS, or load‑balancer issue between market‑data‑service and its external quotes vendor could make vendor requests appear to time out at 800 ms (OBS‑13/15). This would manifest as gRPC DEADLINE_EXCEEDED in portfolio‑service (OBS‑10) and cascade similarly to H1.

**Supporting:**
- market-data-service logged quotes‑vendor request timeouts (800 ms) starting at 14:41:01 UTC (1072 occurrences) and circuit‑breaker half‑open events from 14:47:02 UTC. (`log:785c94c54006`, `log:a9fa5c6b6926`)
- market-data-service began emitting quotes‑vendor request time‑outs (800 ms) at 2026-10-06T14:41:01.233Z, with 1 072 occurrences through 15:04:59. (`log:785c94c54006`)
- portfolio-service calls market-data-service via gRPC with a hard 500 ms timeout. (`dep:portfolio-service->market-data-service`)
- edge-gateway calls portfolio-service over HTTP with a hard 3 s timeout. (`dep:edge-gateway->portfolio-service`)
**Contradicting:**
- No config changes, feature-flag flips, secret rotations, or infra work were recorded for edge-gateway, market-data-service, postgres-orders, redis-cache, orders-service, or auth-service in the window. (`chg:2512`)
- A deploy of portfolio-service v5.4.0 was recorded at 2026-10-06T14:48:30Z (chg:2512). (`chg:2512`)
**Assumptions:**
- ASM-6: No hidden infrastructure change (node‑pool resize, LB config, service‑mesh timeout tweak) occurred; GAP‑4 notes this is unknown.
**Objections:**
- [blocking] gap_unaddressed: No network‑level metrics (packet loss, RTT) to the quotes vendor are available (GAP‑4), so an infra failure cannot be confirmed or ruled out.
- [minor] alternative_not_excluded: HYP‑1 is accepted and fully accounts for the observed vendor time‑outs; infra failure remains an untested alternative.

## Recommended actions

| Urgency | Kind | Action | Why |
|---|---|---|---|
| now | mitigate | Increase the portfolio‑service gRPC timeout to ≥800 ms (or add a short retry with back‑off) to absorb vendor latency spikes. | Current 500 ms timeout is lower than observed vendor latency, causing immediate DEADLINE_EXCEEDED failures. (HYP-1) |
| now | mitigate | Enable a fast‑fail fallback in portfolio‑service (e.g., cached quotes) when market‑data‑service returns DEADLINE_EXCEEDED. | Prevents downstream latency spikes and 5xx to clients while vendor latency is high. (HYP-1) |
| soon | fix | Align timeout budgets across the call chain: set market‑data‑service vendor timeout ≤400 ms and portfolio‑service gRPC timeout ≥500 ms with a safety margin. | Ensures upstream timeouts are longer than downstream calls, eliminating deadline mismatches. (HYP-1) |
| soon | prevent | Add alerting on market‑data‑service vendor request latency >500 ms and circuit‑breaker half‑open transitions. | Early detection of vendor degradation before it breaches downstream timeouts. (HYP-1) |
| later | investigate | Retrieve full commit diff for portfolio‑service v5.4.0 (commit 3c7d0aa) and verify feature‑flag state at 14:48 UTC. | Confirms whether new sector‑breakdown code could add extra gRPC/DB calls that amplify latency (GAP‑1, GAP‑3). (HYP-2) |
| later | investigate | Collect orders‑service CPU, thread‑pool, and DB‑connection‑pool metrics for 14:20‑15:05 UTC. | Determines if early 5xx at 14:36 UTC were due to resource exhaustion (GAP‑10). (HYP-3) |
| later | investigate | Obtain network‑level metrics (packet loss, RTT) to the quotes vendor IP for the incident window. | Rules out a transient infrastructure failure as an alternative cause (GAP‑4). (HYP-4) |
| later | investigate | Query edge‑gateway logs and metrics (error_rate, latency_p99, rps) for 14:20‑15:05 UTC. | Quantifies gateway impact and confirms propagation path (GAP‑6, GAP‑7). |
| later | investigate | Query postgres‑orders logs and metrics (latency, error_rate, connections) for the same window. | Rules out DB saturation contributing to order rejections (GAP‑8, GAP‑9, GAP‑11). |

## Evidence gaps

- **get_change_history** (Full commit diff for portfolio-service commit 3c7d0aa): Only summary (+410/-88 lines) is available; need exact file/endpoint changes to map new DB/gRPC calls.
- **get_change_history** (Changes for services not in the seven‑service list (shared libraries, service‑mesh config, DNS, infra)): Change census only covered the listed services; upstream infra changes could affect the path.
- **get_change_history** (Feature‑flag state for portfolio-service around 14:48 UTC): A flag flip could enable the new sector‑breakdown only for some tenants, not captured as a deploy.
- **get_change_history** (Infrastructure events (node‑pool resize, network policy, load‑balancer config) in the window): Not recorded in change‑census but could impact hard‑timeout paths.
- **get_change_history** (Precise client‑side symptom onset timestamp): Report says “around when this started” at 15:05 UTC; exact error‑rate spike time would confirm coincidence with deploy.
- **query_logs** (edge-gateway (WARN+ patterns 14:20‑15:05 UTC)): No log query executed for edge-gateway; cannot confirm propagation vs independent errors.
- **query_metrics** (edge-gateway (error_rate, latency_p99, rps 14:20‑15:05 UTC)): Metrics not fetched; needed to quantify gateway impact.
- **query_logs** (postgres-orders (WARN+ patterns 14:20‑15:05 UTC)): No log query executed; unknown if DB contributed.
- **query_metrics** (postgres-orders (latency, error_rate, connections 14:20‑15:05 UTC)): Metrics not fetched; needed to rule out DB saturation.
- **query_metrics** (All metrics for orders-service, market-data-service, postgres-orders, redis-cache (summary and key series such as request latency, error rate, CPU, memory, connection pool usage, consumer lag).): Metrics were not fetched in the allocated steps; they are needed to quantify latency spikes, error rates, and saturation.
- **query_logs** (postgres-orders logs at WARN/ERROR for 14:20‑15:05.): Postgres‑orders logs were not queried; they could reveal DB‑side contention or errors contributing to order rejections.
- **query_logs** (orders-service DEBUG/INFO logs around 14:40‑14:45 to see request flow details.): Only WARN/ERROR patterns were retrieved; lower‑level logs may show retry logic or timeout configuration.

## Open questions

- What caused the 13 HTTP 5xx responses from orders‑service starting at 14:36 UTC, before the vendor latency spike?
- Exact code changes in portfolio‑service v5.4.0 (full diff) and whether a feature flag enabled the new sector‑breakdown for a subset of traffic.
- State of any feature flags for portfolio‑service around 14:48 UTC.
- Whether any infrastructure change (network policy, load‑balancer config, node‑pool resize) occurred that could affect the market‑data‑service → vendor path.
- Edge‑gateway error‑rate and latency behavior during the incident to confirm it was purely downstream propagation.
- Postgres‑orders health (latency, errors, connection pool) during the window to exclude DB‑side contribution.

## How the investigation ran

Stopped because the critic accepted HYP-1, after 1 round(s): 19 model calls, 9 tool calls, 78,098 tokens, 796 s.
