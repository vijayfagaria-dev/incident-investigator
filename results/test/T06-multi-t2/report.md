# T06: Intermittent errors across the app

**Outcome:** inconclusive
- HYP-1 has unresolved blocking objections

## Summary

Starting around 11:15 UTC customers saw intermittent 2 % request failures on many screens; retries usually succeeded. The only change in the window was the orders‑service v2.16.0 deploy at 11:05, which introduced batch fee‑schedule lookups and coincides with DB‑connection‑reset warnings and a modest rise in orders‑service error rate. However, orders‑service latency did not increase, edge‑gateway timeouts were observed only to portfolio‑service, and a brief market‑data‑service degradation (HYP‑2) has not been ruled out. Because the blocking objections on HYP‑1 remain unresolved and the investigation hit its time budget, the root cause is inconclusive.

## Hypotheses

### 1. `code_regression` on **orders-service**, triggered by `chg:2561` (HYP-1)

Confidence 0.50 (medium), critic: challenge, capped from 0.55: it has unresolved blocking objections. The v2.16.0 deploy introduced batch fee‑schedule lookups that open or hold additional DB connections / longer transactions on postgres‑orders. This caused peer‑reset warnings, a modest rise in orders‑service error rate, and higher DB‑pool usage. Because edge‑gateway has a hard 3 s HTTP dependency on orders‑service, the latency spikes surface as upstream connect‑timeout errors (observed on the portfolio route) and a ~2 % error‑rate increase across portfolio, orders and payments screens.

**Supporting:**
- deploy on orders-service at 11:05:12 UTC by ci/deploy-bot: orders-service v2.16.0: batch fee schedule lookups (version: 2.16.0, previous_version: 2.15.2, commit: 8b20f4e, diff: +142 / -97) (`chg:2561`)
- Only one change recorded in the window for any service on the failing call‑path: orders‑service deploy v2.16.0 at 11:05:12 UTC (batch fee schedule lookups, +142/‑97 lines). (`chg:2561`)
- The deploy occurred ~10 minutes before the first reported intermittent errors (~11:15 UTC), making it temporally plausible as a cause. (`chg:2561`)
- The deploy diff mentions “batch fee schedule lookups”, suggesting a code path that now aggregates multiple fee‑schedule reads, potentially increasing DB/redis load or introducing a new retry loop that could fail intermittently. (`chg:2561`)
- orders-service v2.16.0 deployed at 2026-10-10T11:05:12Z (`chg:2561`)
- Fee cache cold warnings start at 11:06:22Z and continue until 11:18:41Z (36 occurrences) (`log:e91658633ca4`)
- DB connection reset warnings start at 11:15:13.977Z and persist to 11:49:45.782Z (203 occurrences) (`log:a32c4ff0bfc1`)
- orders-service error_rate rises from baseline 0.0018 to period mean 0.0045 (max 0.0126) (`metric:orders-service/error_rate`)
- edge‑gateway → orders‑service is a hard HTTP dependency (timeout 3 s); failures or latency spikes in orders‑service will surface as 5xx/timeout errors on edge‑gateway routes that call orders‑service (portfolio, orders, payments screens). (`dep:edge-gateway->orders-service`)
- orders‑service has hard downstream dependencies on market‑data‑service (gRPC, 500 ms) and postgres‑orders (SQL, 2 s); a regression in the new batch lookup could increase load or latency on these services. (`dep:orders-service->market-data-service`, `dep:orders-service->postgres-orders`)
- orders-service DB pool usage modestly higher (baseline 16.4 → 17.0 connections, max 40) (`metric:orders-service/db_pool_in_use`)
- postgres‑orders logged three WARN events “checkpoints are occurring too frequently (<seconds> seconds apart)” at 11:10:17, 11:25:?? and 11:40:16 UTC (total 3 occurrences). (`log:d71caa8bcd57`)
**Contradicting:**
- orders-service latency_p99 stays near baseline (256 ms → 260 ms) (`metric:orders-service/latency_p99_ms`)
- CPU and memory utilization for all three services remain within normal ranges (`metric:orders-service/cpu_util`, `metric:orders-service/mem_util`, `metric:edge-gateway/cpu_util`, `metric:edge-gateway/mem_util`, `metric:portfolio-service/cpu_util`, `metric:portfolio-service/mem_util`)
- portfolio-service error_rate unchanged (baseline 0.0021 → period 0.0020) (`metric:portfolio-service/error_rate`)
- portfolio-service latency_p99 essentially flat (416 ms → 417 ms) (`metric:portfolio-service/latency_p99_ms`)
- market-data-service latency_p99_ms baseline mean 250.3 ms; maximum observed 312.9 ms, period mean 259.6 ms, staying within normal range. (`metric:market-data-service/latency_p99_ms`)
**Assumptions:**
- ASM-5: The new batch‑lookup code in orders‑service v2.16.0 opens or holds more DB connections or runs longer transactions, causing peer‑reset warnings on postgres‑orders.
- ASM-6: The edge‑gateway “upstream connect‑timeout to portfolio‑service” is a downstream manifestation of orders‑service latency (e.g., portfolio‑service calls orders‑service for fee data, or the gateway’s portfolio route also fans‑out to orders‑service).
**Objections:**
- [blocking] unsupported_claim: The hypothesis asserts that orders‑service latency spikes generate edge‑gateway upstream connect‑timeouts to portfolio‑service, but edge‑gateway logs only show timeouts to portfolio‑service and orders‑service latency_p99 is unchanged (OBS‑19).
- [blocking] ignores_contradiction: Orders‑service latency_p99 remains at baseline (OBS‑19) while the hypothesis requires a latency spike to explain the 3 s gateway timeout.
- [blocking] alternative_not_excluded: HYP‑2 (market‑data‑service degradation) also explains the portfolio‑service gRPC failures and gateway timeouts and has not been ruled out.

### 2. `dependency_degradation` on **market-data-service** (HYP-2)

Confidence 0.20 (low), critic: challenge. A brief, un‑instrumented degradation (e.g., GC pause, thread‑pool exhaustion, transient resource saturation) in market‑data‑service caused gRPC UNAVAILABLE / connection‑reset errors. Portfolio‑service, which has a hard gRPC dependency on market‑data‑service, logged those failures at 11:15:13, and edge‑gateway subsequently recorded connect‑timeouts to portfolio‑service.

**Supporting:**
- portfolio‑service reported 174 gRPC failures to market‑data‑service (UNAVAILABLE, connection reset) beginning 2026‑10‑10 11:15:13 UTC. (`log:e0364bef1b6f`)
- portfolio-service gRPC failures to market-data-service start at 11:15:13.445Z (174 occurrences) (`log:e0364bef1b6f`)
- edge‑gateway logged 1 443 upstream connect‑timeout errors to portfolio‑service starting 2026‑10‑10 11:15:01 UTC (last at 11:49:59). (`log:80f1f968cbad`)
- edge-gateway upstream timeout errors to portfolio-service start at 11:15:01.636Z (1,443 occurrences) (`log:80f1f968cbad`)
- edge‑gateway logged 1,443 upstream connect‑timeout errors to portfolio‑service starting 2026‑10‑10 11:15:01 UTC (last at 11:49:59 UTC). (`log:80f1f968cbad`)
- market-data-service error_rate baseline mean 0.001827; maximum observed 0.00393 (point 0.003525 at 11:26 UTC) during 11:10‑11:50 UTC. (`metric:market-data-service/error_rate`)
**Contradicting:**
- No config changes, feature‑flag flips, secret rotations, or infra work were recorded for any other service on the call‑path (auth‑service, market‑data‑service, portfolio‑service, payments‑service, redis‑cache, postgres‑orders, postgres‑payments, quotes‑vendor, bank‑rails, kafka) during the window. (`chg:2561`)
- CPU and memory utilization for all three services remain within normal ranges (`metric:orders-service/cpu_util`, `metric:orders-service/mem_util`, `metric:edge-gateway/cpu_util`, `metric:edge-gateway/mem_util`, `metric:portfolio-service/cpu_util`, `metric:portfolio-service/mem_util`)
- market-data-service latency_p99_ms baseline mean 250.3 ms; maximum observed 312.9 ms, period mean 259.6 ms, staying within normal range. (`metric:market-data-service/latency_p99_ms`)
- portfolio-service error_rate unchanged (baseline 0.0021 → period 0.0020) (`metric:portfolio-service/error_rate`)
- portfolio-service latency_p99 essentially flat (416 ms → 417 ms) (`metric:portfolio-service/latency_p99_ms`)
**Assumptions:**
- ASM-7: A short‑lived internal event (GC pause, thread‑pool stall, brief saturation) occurred in market‑data‑service around 11:15 UTC but is not captured by the coarse‑grained metrics we have.
**Objections:**
- [blocking] gap_unaddressed: Market‑data‑service WARN/ERROR logs for 11:10‑11:50 have not been queried (GAP‑13) and vendor error‑rate metrics are missing (GAP‑14); without them we cannot confirm a brief degradation.
- [minor] unsupported_claim: Market‑data‑service error_rate rises only to ~0.004 (OBS‑29) and latency_p99 stays normal (OBS‑30), which may be insufficient to cause the observed 174 gRPC failures.
- [minor] alternative_not_excluded: HYP‑1 (orders‑service regression) also fits the timing and has supporting DB‑reset warnings; it has not been excluded. (not blocking: this review rejected HYP-1 or found it flawed)

### 3. `infrastructure_failure` on **infrastructure** (HYP-3)

Confidence 0.10 (low), critic: challenge. A fleeting network partition or host‑level outage affected the subnet hosting portfolio‑service and market‑data‑service simultaneously. This would generate connect‑timeout errors from edge‑gateway to portfolio‑service and gRPC UNAVAILABLE errors from portfolio‑service to market‑data‑service, while leaving other services on different subnets untouched.

**Supporting:**
- edge‑gateway logged 1 443 upstream connect‑timeout errors to portfolio‑service starting 2026‑10‑10 11:15:01 UTC (last at 11:49:59). (`log:80f1f968cbad`)
- edge-gateway upstream timeout errors to portfolio-service start at 11:15:01.636Z (1,443 occurrences) (`log:80f1f968cbad`)
- edge‑gateway logged 1,443 upstream connect‑timeout errors to portfolio‑service starting 2026‑10‑10 11:15:01 UTC (last at 11:49:59 UTC). (`log:80f1f968cbad`)
- portfolio‑service reported 174 gRPC failures to market‑data‑service (UNAVAILABLE, connection reset) beginning 2026‑10‑10 11:15:13 UTC. (`log:e0364bef1b6f`)
- portfolio-service gRPC failures to market-data-service start at 11:15:13.445Z (174 occurrences) (`log:e0364bef1b6f`)
**Contradicting:**
- No config changes, feature‑flag flips, secret rotations, or infra work were recorded for any other service on the call‑path (auth‑service, market‑data‑service, portfolio‑service, payments‑service, redis‑cache, postgres‑orders, postgres‑payments, quotes‑vendor, bank‑rails, kafka) during the window. (`chg:2561`)
- CPU and memory utilization for all three services remain within normal ranges (`metric:orders-service/cpu_util`, `metric:orders-service/mem_util`, `metric:edge-gateway/cpu_util`, `metric:edge-gateway/mem_util`, `metric:portfolio-service/cpu_util`, `metric:portfolio-service/mem_util`)
- portfolio-service error_rate unchanged (baseline 0.0021 → period 0.0020) (`metric:portfolio-service/error_rate`)
- portfolio-service latency_p99 essentially flat (416 ms → 417 ms) (`metric:portfolio-service/latency_p99_ms`)
**Assumptions:**
- ASM-8: A network or AZ event affected the subnet hosting portfolio‑service and market‑data‑service simultaneously, invisible to service‑level metrics.
**Objections:**
- [minor] gap_unaddressed: Network/AZ health metrics, packet‑loss or host‑level outage data are not exposed by the current observability tools, so the infrastructure‑failure claim cannot be verified.
- [minor] alternative_not_excluded: Both HYP‑1 and HYP‑2 provide concrete service‑level evidence for the error bursts and remain viable alternatives. (not blocking: this review rejected HYP-1 or found it flawed)

## Recommended actions

| Urgency | Kind | Action | Why |
|---|---|---|---|
| now | mitigate | Roll back orders‑service to v2.15.2 (pre‑batch‑lookup) to stop the ongoing error burst. | The deploy is the only change temporally aligned with the incident and is the primary suspect (HYP‑1). Rolling back removes the new code path immediately. (HYP-1) |
| soon | fix | Analyze commit 8b20f4e (diff +142/‑97) for the batch fee‑schedule lookup implementation, verify DB‑connection handling, and add safeguards (e.g., connection‑pool limits, circuit‑breaker, retry back‑off). | If the new bulk‑read logic is holding connections longer, it can cause peer‑reset warnings and downstream timeouts despite unchanged latency_p99. (HYP-1) |
| soon | investigate | Query market‑data‑service WARN/ERROR logs for 11:10‑11:50 UTC and retrieve vendor error‑rate metrics. | Gap‑13 and Gap‑14 block confirmation of a brief market‑data degradation (HYP‑2). (HYP-2) |
| soon | investigate | Enable and collect per‑upstream error‑rate and latency_p99 metrics from edge‑gateway (orders‑service, portfolio‑service, etc.). | Current aggregate metrics cannot attribute the timeout spike to a specific upstream (Gap‑3, Gap‑15). (HYP-1) |
| soon | investigate | Fetch postgres‑orders logs for connection‑reset warnings and checkpoint‑frequency metrics. | Gap‑9 and Gap‑16 are needed to verify the DB side of the peer‑reset warnings seen in orders‑service. (HYP-1) |
| later | prevent | Add client‑side telemetry (browser/mobile error/retry reporting) and enrich edge‑gateway dashboards with per‑upstream SLO alerts. | Gap‑7 prevents ruling out client‑side issues; per‑upstream observability will make future regressions detectable faster. |
| later | prevent | Implement automated canary/rollback guard for orders‑service that triggers on error‑rate > 1 % or DB‑pool saturation. | Provides a safety net for future deployments that introduce similar batch‑lookup patterns. (HYP-1) |

## Evidence gaps

- **query_metrics** (market-data-service, orders-service, payments-service, auth-service, postgres-orders, postgres-payments, quotes-vendor, bank-rails): No metrics were retrieved for these services; cannot assess their health or saturation during the incident.
- **query_logs** (market-data-service, orders-service, payments-service, auth-service, postgres-orders, postgres-payments, quotes-vendor, bank-rails): No WARN/ERROR log patterns were fetched for these services; possible upstream failures are invisible.
- **query_metrics** (edge-gateway per‑upstream latency/error breakdown): Edge‑gateway metrics only provide aggregate error_rate and latency; we cannot attribute the spike to a specific upstream without per‑target series.
- **get_change_history** (Feature‑flag or config toggles on any service in the window): Change history only returns deploys; a flag flip enabling the new batch‑lookup path would not appear as a deploy.
- **get_change_history** (Secret rotations or infra maintenance for redis‑cache, postgres‑orders, postgres‑payments, kafka, quotes‑vendor, bank‑rails): No records were returned for these operations; a brief rotation or restart could cause transient errors.
- **get_change_history** (Detailed diff of orders‑service commit 8b20f4e): Only a line‑count diff (+142/‑97) is available; without the exact code change we cannot confirm new retry loops, bulk reads, or circuit‑breaker modifications.
- **client‑side telemetry (browser/mobile)** (End‑user error and retry behavior): Responder hypothesised a client‑side issue; lack of client telemetry prevents ruling that out.
- **query_logs** (market-data-service logs (WARN+)): Not queried; needed to see if market-data-service emitted errors or resets at 11:15
- **query_logs** (postgres-orders logs (WARN+)): Not queried; needed to confirm DB side of connection resets
- **query_metrics** (circuit_breaker_open_total for orders-service, edge-gateway, portfolio-service): Metrics not present in current metric list; needed to verify breaker trips
- **query_logs** (edge-gateway upstream error records with upstream identifier): Current pattern only shows timeout to portfolio-service; need breakdown to see if orders-service also timed out
- **query_logs** (edge‑gateway logs filtered for timeout to auth‑service, payments‑service, quotes‑vendor, bank‑rails): Step limit reached; only a generic timeout pattern query was executed, which returned a single pattern for portfolio‑service.
- **query_logs** (market-data-service WARN/ERROR logs 2026-10-10T11:10:00Z‑2026-10-10T11:50:00Z): Log query not executed; no log evidence available for this service in the window.
- **query_metrics** (market-data-service vendor_error_rate 2026-10-10T11:10:00Z‑2026-10-10T11:50:00Z): Vendor error rate not examined; could reveal upstream quote‑vendor issues.
- **query_metrics** (per‑upstream error_rate and latency_p99 for edge‑gateway upstreams (orders‑service, portfolio‑service)): The metrics endpoint only returns service‑level aggregates; upstream‑specific series are not exposed.
- **query_metrics** (postgres‑orders checkpoint interval, write latency, or WAL throughput metrics): Only log patterns were queryable; no metric series for postgres‑orders were available in the tool.

## Open questions

- Did market‑data‑service experience a brief, uninstrumented degradation (GC pause, thread‑pool exhaustion) at ~11:15 UTC?
- Do edge‑gateway per‑upstream metrics show timeouts to orders‑service as well as portfolio‑service?
- What exact code changes are in commit 8b20f4e (new retry loops, bulk reads, connection‑pool usage)?
- Do postgres‑orders logs confirm a surge of ‘connection reset by peer’ errors and frequent checkpoints during the window?
- Is there any client‑side evidence (browser/mobile) that the errors originated before reaching edge‑gateway?

## How the investigation ran

Stopped because time budget reached, after 2 round(s): 35 model calls, 21 tool calls, 191,735 tokens, 1176 s.
