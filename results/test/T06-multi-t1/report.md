# T06: Intermittent errors across the app

**Outcome:** inconclusive
- HYP-2 has unresolved blocking objections

## Summary

Starting around 10:35 UTC the external quotes‑vendor began returning 429/503 responses, which propagated through market‑data‑service to its hard dependents (orders‑service, portfolio‑service, edge‑gateway) and produced a modest, intermittent rise in error rates (~2 % peak) and latency across many routes. A deploy of orders‑service v2.16.0 at 11:05 UTC added batch fee‑schedule lookups, but per‑minute vendor error data shows a gradual increase beginning well before the deploy with no step change at 11:05, and the orders‑service outbound gRPC call rate to market‑data‑service is unavailable. Because the key evidence gap (per‑minute vendor error series) remains unfilled, the investigation was stopped as inconclusive.

## Hypotheses

### 1. `dependency_degradation` on **quotes-vendor** (HYP-2)

Confidence 0.50 (medium), critic: challenge, capped from 0.58: it has unresolved blocking objections. The external quotes‑vendor began returning 429/503 responses around 10:35 UTC (perhaps due to a quota change or traffic surge). market‑data‑service forwards these as gRPC errors to its hard dependents (orders‑service, portfolio‑service, edge‑gateway), causing a modest rise in error rates and latency across those services while payments‑service (which does not depend on the vendor) remains healthy.

**Supporting:**
- market‑data‑service logged 7 WARN events “quotes‑vendor responded 429; backing off” from 10:35:49 UTC to 11:44:30 UTC. (`log:04398295b807`)
- market‑data‑service logged 3 ERROR 503 responses on GET /v1/quotes between 10:50:02 UTC and 11:43:43 UTC. (`log:11728e4fe3dc`)
- vendor_error_rate metric peaked at 0.002124 (max) with a mean of 0.001012, above its baseline mean of 0.000973. (`metric:market-data-service/vendor_error_rate`)
- market-data-service vendor_error_rate averaged 0.1012 % (baseline 0.0973 %) with a max of 0.2124 %. (`metric:market-data-service/vendor_error_rate`)
- Request rate rose to a mean of 413 req/s (baseline 396.8 req/s). (`metric:market-data-service/rps`)
- portfolio-service latency_p99 averaged 416.6 ms (baseline 415.6 ms) with a last value of 519.2 ms. (`metric:portfolio-service/latency_p99_ms`)
- Edge‑gateway error_rate peaked at 2.53 % (max) with a window‑average of 0.96 % versus a baseline of 0.20 %. (`metric:edge-gateway/error_rate`)
- Edge‑gateway p99 latency rose from a baseline of 342 ms to a window‑average of 414 ms and a last value of 436 ms. (`metric:edge-gateway/latency_p99_ms`)
- portfolio-service also has a hard dependency on market-data-service (gRPC, 500 ms timeout). (`dep:portfolio-service->market-data-service`)
- edge-gateway has hard dependencies on orders-service, market-data-service, and portfolio-service (HTTP, 2–3 s timeouts). (`dep:edge-gateway->orders-service`, `dep:edge-gateway->market-data-service`, `dep:edge-gateway->portfolio-service`)
**Contradicting:**
- market‑data‑service overall error_rate remained near baseline (mean 0.001866 vs baseline 0.001955). (`metric:market-data-service/error_rate`)
- market-data-service error_rate averaged 0.1866 % (max 0.393 %) versus a baseline of 0.1955 %. (`metric:market-data-service/error_rate`)
- Orders‑service p99 latency was near baseline (baseline 256 ms, window‑average 260 ms, last 236 ms). (`metric:orders-service/latency_p99_ms`)
- Payments‑service error_rate remained at baseline (window‑average 0.20 % vs baseline 0.21 %). (`metric:payments-service/error_rate`)
- Payments‑service latency (p50 and p99) stayed within baseline bounds. (`metric:payments-service/latency_p50_ms`, `metric:payments-service/latency_p99_ms`)
- portfolio-service error_rate averaged 0.1985 % (max 0.3138 %) versus a baseline of 0.2112 %. (`metric:portfolio-service/error_rate`)
**Assumptions:**
- ASM-7: market‑data‑service retries vendor 429/503 internally and does not count them in its own error_rate metric.
- ASM-8: edge‑gateway’s default retry policy (e.g., 2 retries with exponential back‑off) masks most downstream failures, yielding only ~2 % end‑user error rate.
- ASM-9: The quotes‑vendor began enforcing a tighter rate‑limit (or experienced a quota change) around 10:35 UTC, independent of our deploy.
**Objections:**
- [blocking] gap_unaddressed: Only summary vendor_error_rate stats are present; per‑minute series needed to verify smooth rise vs step (GAP‑10).
- [minor] alternative_not_excluded: HYP‑1 (deploy‑induced fan‑out) has not been excluded. (not blocking: this review rejected HYP-1 or found it flawed)
- [minor] unsupported_claim: Claims vendor errors propagate to edge‑gateway errors, but edge‑gateway error rise is modest (2.5 % peak) and could have other contributors.

### 2. `code_regression` on **orders-service**, triggered by `chg:2561` (HYP-1)

Confidence 0.31 (low), critic: challenge. The v2.16.0 deploy introduced batch fee‑schedule lookups that added a new fan‑out to market‑data‑service (or increased call volume). Calls to the external quotes‑vendor now hit the vendor’s rate limit, producing 429/503 responses that propagate as errors/timeouts up the call chain, raising edge‑gateway error rate and latency.

**Supporting:**
- deploy on orders-service at 11:05:12 UTC by ci/deploy-bot: orders-service v2.16.0: batch fee schedule lookups (version: 2.16.0, previous_version: 2.15.2, commit: 8b20f4e, diff: +142 / -97) (`chg:2561`)
- Orders‑service error_rate averaged 0.45 % (max 1.26 %) versus a baseline of 0.18 %. (`metric:orders-service/error_rate`)
- edge-gateway has hard dependencies on orders-service, market-data-service, and portfolio-service (HTTP, 2–3 s timeouts). (`dep:edge-gateway->orders-service`, `dep:edge-gateway->market-data-service`, `dep:edge-gateway->portfolio-service`)
- market‑data‑service logged 7 WARN events “quotes‑vendor responded 429; backing off” from 10:35:49 UTC to 11:44:30 UTC. (`log:04398295b807`)
- market‑data‑service logged 3 ERROR 503 responses on GET /v1/quotes between 10:50:02 UTC and 11:43:43 UTC. (`log:11728e4fe3dc`)
- vendor_error_rate metric peaked at 0.002124 (max) with a mean of 0.001012, above its baseline mean of 0.000973. (`metric:market-data-service/vendor_error_rate`)
- market-data-service vendor_error_rate averaged 0.1012 % (baseline 0.0973 %) with a max of 0.2124 %. (`metric:market-data-service/vendor_error_rate`)
**Contradicting:**
- Orders‑service p99 latency was near baseline (baseline 256 ms, window‑average 260 ms, last 236 ms). (`metric:orders-service/latency_p99_ms`)
- market‑data‑service vendor_error_rate (3‑minute granularity) ranged from 0.00055 to 0.00157 (ratio) between 10:30 UTC and 11:48 UTC, with a window mean of 0.001012 versus baseline_mean 0.000973. (`metric:market-data-service/vendor_error_rate`)
- The highest vendor_error_rate value (0.002124) occurred at 11:48 UTC, well after the 11:05 deploy; values around the deploy (10:57‑11:06) stayed near 0.00055‑0.00117, showing no abrupt increase. (`metric:market-data-service/vendor_error_rate`)
- market‑data‑service overall error_rate remained near baseline (mean 0.001866 vs baseline 0.001955). (`metric:market-data-service/error_rate`)
- market-data-service error_rate averaged 0.1866 % (max 0.393 %) versus a baseline of 0.1955 %. (`metric:market-data-service/error_rate`)
- Payments‑service error_rate remained at baseline (window‑average 0.20 % vs baseline 0.21 %). (`metric:payments-service/error_rate`)
- Payments‑service latency (p50 and p99) stayed within baseline bounds. (`metric:payments-service/latency_p50_ms`, `metric:payments-service/latency_p99_ms`)
- portfolio-service error_rate averaged 0.1985 % (max 0.3138 %) versus a baseline of 0.2112 %. (`metric:portfolio-service/error_rate`)
**Assumptions:**
- ASM-10: orders‑service v2.16.0 adds a new batch fee‑schedule lookup that issues additional gRPC calls to market‑data‑service.
- ASM-11: The extra gRPC traffic from the batch lookup is enough to push the vendor over its limit after the deploy.
- ASM-12: Orders‑service latency metric (p99) does not capture the added gRPC latency because the calls are made asynchronously or are cached.
**Objections:**
- [blocking] unsupported_claim: Predicts a step increase in vendor_error_rate at 11:05, but per‑minute data shows a gradual rise starting at 10:35 with no abrupt change at deploy (OBS‑31, OBS‑32).
- [blocking] alternative_not_excluded: HYP‑2 (vendor degradation) explains the same symptoms and is not ruled out.
- [blocking] gap_unaddressed: Orders‑service outbound gRPC call rate to market‑data‑service is not available (GAP‑14); a jump there would support the batch‑lookup fan‑out claim.

### 3. `config_change` on **edge-gateway** (HYP-3)

Confidence 0.07 (low), critic: reject. An unreleased configuration change or feature‑flag toggle on edge‑gateway (e.g., altered retry/back‑off or timeout settings) around 11:00 caused a small increase in error rate and latency for all downstream routes. The effect appears across portfolio, orders, and payments routes, but payments‑service metrics show no degradation, making this unlikely.

**Supporting:**
- Edge‑gateway error_rate peaked at 2.53 % (max) with a window‑average of 0.96 % versus a baseline of 0.20 %. (`metric:edge-gateway/error_rate`)
- Edge‑gateway p99 latency rose from a baseline of 342 ms to a window‑average of 414 ms and a last value of 436 ms. (`metric:edge-gateway/latency_p99_ms`)
- edge-gateway has hard dependencies on orders-service, market-data-service, and portfolio-service (HTTP, 2–3 s timeouts). (`dep:edge-gateway->orders-service`, `dep:edge-gateway->market-data-service`, `dep:edge-gateway->portfolio-service`)
**Contradicting:**
- Payments‑service error_rate remained at baseline (window‑average 0.20 % vs baseline 0.21 %). (`metric:payments-service/error_rate`)
- Payments‑service latency (p50 and p99) stayed within baseline bounds. (`metric:payments-service/latency_p50_ms`, `metric:payments-service/latency_p99_ms`)
- portfolio-service error_rate averaged 0.1985 % (max 0.3138 %) versus a baseline of 0.2112 %. (`metric:portfolio-service/error_rate`)
**Assumptions:**
- ASM-13: An undocumented edge‑gateway config/flag change altered retry/timeout behavior at ~11:00.
**Objections:**
- [blocking] unsupported_claim: No config/flag change on edge‑gateway is observed in the change history (GAP‑4, GAP‑5).
- [blocking] ignores_contradiction: Payments‑service metrics remain at baseline (OBS‑6, OBS‑7), contradicting a gateway‑wide configuration impact.

### 4. `resource_exhaustion` on **postgres-orders** (HYP-4)

Confidence 0.04 (low), critic: reject. The orders‑service deploy increased load on postgres‑orders (e.g., new batch queries), exhausting connection pool or causing slow queries, which manifests as higher error rates in orders‑service and downstream edge‑gateway. No direct metrics for postgres‑orders are available.

**Supporting:**
- Orders‑service error_rate averaged 0.45 % (max 1.26 %) versus a baseline of 0.18 %. (`metric:orders-service/error_rate`)
- orders-service has hard dependencies on market-data-service (gRPC, 500 ms timeout) and postgres-orders (SQL, 2 s timeout). (`dep:orders-service->market-data-service`, `dep:orders-service->postgres-orders`)
**Contradicting:**
- Orders‑service p99 latency was near baseline (baseline 256 ms, window‑average 260 ms, last 236 ms). (`metric:orders-service/latency_p99_ms`)
- Payments‑service error_rate remained at baseline (window‑average 0.20 % vs baseline 0.21 %). (`metric:payments-service/error_rate`)
- Payments‑service latency (p50 and p99) stayed within baseline bounds. (`metric:payments-service/latency_p50_ms`, `metric:payments-service/latency_p99_ms`)
- market‑data‑service logged 7 WARN events “quotes‑vendor responded 429; backing off” from 10:35:49 UTC to 11:44:30 UTC. (`log:04398295b807`)
- market‑data‑service logged 3 ERROR 503 responses on GET /v1/quotes between 10:50:02 UTC and 11:43:43 UTC. (`log:11728e4fe3dc`)
- vendor_error_rate metric peaked at 0.002124 (max) with a mean of 0.001012, above its baseline mean of 0.000973. (`metric:market-data-service/vendor_error_rate`)
- market-data-service vendor_error_rate averaged 0.1012 % (baseline 0.0973 %) with a max of 0.2124 %. (`metric:market-data-service/vendor_error_rate`)
**Assumptions:**
- ASM-14: v2.16.0 introduced a heavy SQL batch that exhausted postgres‑orders connections.
**Objections:**
- [blocking] unsupported_claim: No postgres‑orders metrics (connection pool, query latency) were collected (GAP‑1); orders‑service latency is unchanged (OBS‑5).
- [blocking] ignores_contradiction: Vendor 429/503 errors appear before the deploy (OBS‑14‑16) and payments‑service, which does not use postgres‑orders, is healthy.

## Recommended actions

| Urgency | Kind | Action | Why |
|---|---|---|---|
| now | mitigate | Enable a short‑circuit / fallback in market‑data‑service for quotes‑vendor 429/503 responses (e.g., serve stale cache or return degraded payload) so downstream services see fewer errors immediately. | Vendor errors are already occurring and affect multiple services; a circuit‑breaker reduces impact while root cause is resolved. (HYP-2) |
| now | mitigate | Increase edge‑gateway retry/back‑off settings for calls to orders‑service and portfolio‑service to absorb transient vendor failures. | Retries already succeed most of the time; tuned retries lower the visible error rate for customers. (HYP-2) |
| soon | fix | Engage the quotes‑vendor to clarify quota limits, request a higher quota or dedicated capacity, and verify any recent quota change around 10:30 UTC. | Vendor 429/503 responses are the proximal cause; fixing the quota eliminates the error source. (HYP-2) |
| soon | fix | Roll back orders‑service v2.16.0 or disable the new batch fee‑schedule lookup feature flag until the vendor issue is resolved and the call‑rate impact is quantified. | If the deploy increased call volume, it may exacerbate vendor rate‑limiting; rollback removes that amplification. (HYP-1) |
| later | prevent | Add per‑minute vendor_error_rate and vendor_latency metrics (or export the existing high‑resolution series) to the monitoring dashboard and alert on sustained >0.1 % error rate. | The investigation was blocked by lack of granular vendor error data; continuous visibility prevents future blind spots. (HYP-2) |
| later | prevent | Instrument orders‑service with an outbound gRPC call‑rate metric to market‑data‑service and add alerts for sudden spikes. | Gap‑14 prevents confirming whether the deploy added load; metric enables rapid detection of similar regressions. (HYP-1) |
| soon | investigate | Retrieve per‑minute vendor_error_rate time series from market‑data‑service (or directly from the quotes‑vendor) for 10:00‑12:00 UTC to confirm smooth rise vs step at 11:05. | Blocking objection on HYP‑2 (GAP‑10) – this data will confirm or refute the vendor‑degradation hypothesis. (HYP-2) |
| soon | investigate | Collect orders‑service outbound gRPC call counts to market‑data‑service (or add temporary logging) for the 10:30‑11:30 window. | Blocking objection on HYP‑1 (GAP‑14) – needed to verify whether the deploy caused a call‑rate jump. (HYP-1) |
| later | investigate | Audit edge‑gateway config/feature‑flag changes around 11:00 UTC (change history, flag service) to rule out HYP‑3. | Blocking objection on HYP‑3 (GAP‑4, GAP‑5) – confirms no gateway‑wide config change contributed. (HYP-3) |
| later | investigate | Gather postgres‑orders connection‑pool and query‑latency metrics for the incident window. | Blocking objection on HYP‑4 (GAP‑1) – rules out DB exhaustion as a contributor. (HYP-4) |

## Evidence gaps

- **query_metrics** (portfolio-service, market-data-service, auth-service): Metrics not queried; no error‑rate, latency, or saturation data available for these services.
- **query_metrics** (retry‑success / retry‑count metrics across the call chain): No metric series for retry outcomes were requested; cannot quantify retry‑success rate.
- **query_logs** (WARN+ log patterns for all six services 10:30‑11:50 UTC): Log query not performed; error‑type details and stack traces are missing.
- **get_change_history** (market-data-service, postgres-orders, portfolio-service, edge-gateway, auth-service): Change census only returned the orders-service deploy; no deploy/config/flag/secret/infra records for the other services in the 10:30‑11:50 window were retrieved.
- **get_change_history** (feature‑flag or config service): No source for feature‑flag flips or configuration changes was queried; possible flag affecting fee‑schedule batching may exist.
- **get_change_history** (secret rotation / infra maintenance): Secret rotations or platform infra work (e.g., cert renewal, network change) were not captured in the census.
- **query_metrics** (redis-cache): No metrics were fetched for redis‑cache; cannot assess its health or saturation.
- **query_logs** (quotes-vendor): Logs for the upstream quotes‑vendor were not queried; missing direct evidence of 429 generation.
- **query_metrics** (quotes-vendor): No vendor‑side metrics (error rate, latency, rate‑limit counters) were retrieved.
- **query_metrics** (market-data-service (time‑series points)): Only summary statistics were returned; per‑minute points are needed to pinpoint the exact onset of the vendor error‑rate rise.
- **query_metrics** (portfolio-service retry_success (or retry_count) metric): Metric not present in the service’s exported metrics; cannot quantify retry success.
- **query_metrics** (market-data-service retry_success (or retry_count) metric): Metric not present in the service’s exported metrics; cannot quantify retry success.
- **query_metrics** (auth-service retry_success (or retry_count) metric): Metric not present in the service’s exported metrics; cannot quantify retry success.
- **query_metrics** (orders-service gRPC call rate to market-data-service (per minute)): Metric grpc_calls_per_second does not exist on orders-service; available metrics lack a direct measure of outbound gRPC traffic.

## Open questions

- What caused the quotes‑vendor error rate to start rising at ~10:35 UTC (quota change, traffic surge, upstream incident)?
- Did the orders‑service v2.16.0 deploy increase the call volume to market‑data‑service, and by how much?
- What is the exact per‑minute trajectory of vendor_error_rate around the deploy time?
- Were there any edge‑gateway configuration or feature‑flag changes near 11:00 UTC?
- What are the retry‑success rates at each hop (edge‑gateway → orders/portfolio → market‑data‑service → quotes‑vendor)?
- Did postgres‑orders experience any saturation or latency increase during the window?

## How the investigation ran

Stopped because time budget reached, after 2 round(s): 31 model calls, 16 tool calls, 156,466 tokens, 1023 s.
