# T04: Some order placements failing

**Outcome:** conclusive. Root cause: `code_regression` on **orders-service**, triggered by `chg:2534`

## Summary

A feature‑flag rollout of the new_pricing_path flag to 20 % of accounts at 15:22 UTC introduced a non‑terminating decimal arithmetic bug in PricingPathV2.applyCollar, which threw ArithmeticException for flag‑enabled accounts. The exception propagated uncaught, causing orders‑service to return 5xx errors for roughly one‑fifth of order attempts from 15:23 to 15:50 UTC. The critic accepted this hypothesis (confidence 0.86) and rejected the market‑data and auth alternatives. The root cause is identified, but per‑account flag state at request time was not captured in logs, and several observability gaps remain.

## Hypotheses

### 1. `code_regression` on **orders-service**, triggered by `chg:2534` (HYP-1)

Confidence 0.86 (high), critic: accept. The feature‑flag rollout of new_pricing_path to 20 % of accounts activates a new pricing code path (PricingPathV2). That path contains a non‑terminating decimal arithmetic bug that throws ArithmeticException in applyCollar. The exception propagates uncaught, causing orders‑service to return 5xx for every request from flag‑enabled accounts, which appear as upstream‑500 errors in edge‑gateway.

**Supporting:**
- feature_flag on orders-service at 15:22:07 UTC by lena.fischer: Roll out new_pricing_path to 20% of accounts (flag: new_pricing_path, rollout: 0% -> 20%) (`chg:2534`)
- A feature‑flag rollout on orders‑service changed new_pricing_path from 0% to 20% at 2026‑10‑08T15:22:07Z. (`chg:2534`)
- The flag rollout occurred before the first symptom onset (~15:25 UTC), making it a plausible cause. (`chg:2534`)
- orders‑service logs an ArithmeticException in PricingPathV2.applyCollar 340 times, first at 2026‑10‑08T15:23:00.702Z and last at 2026‑10‑08T15:49:57.995Z (`log:e56c11822899`)
- edge‑gateway records 312 upstream‑500 warnings for POST /v1/orders from 15:23:05.719Z to 15:49:48.906Z (`log:209f37015f90`)
- No other config changes, feature‑flag toggles, secret rotations, or infra work were recorded for edge‑gateway, market‑data‑service, quotes‑vendor, postgres‑orders, or redis‑cache in the 14:35‑15:50 UTC window. (`chg:2534`)
**Contradicting:**
- market-data-service logged 6 WARN events “quotes‑vendor responded 429; backing off <ms>ms” from 2026‑10‑08T14:42:13.873Z to 2026‑10‑08T15:46:30.422Z (`log:706d3b8ae4bd`)
- market-data-service logged 3 ERROR events “GET /v1/quotes 503 12ms” between 2026‑10‑08T14:35:59.250Z and 2026‑10‑08T14:44:50.789Z (`log:6f5ff0cc8b59`)
- market-data-service vendor_error_rate averaged 0.00106 (baseline 0.00093) with a peak of 0.00220 during the window (`metric:market-data-service/vendor_error_rate`)
- market‑data‑service logs 6 vendor 429‑rate‑limit warnings between 14:42:13.873Z and 15:46:30.422Z (`log:706d3b8ae4bd`)
- market‑data‑service logs 3 HTTP 503 errors on GET /v1/quotes early in the window (14:35:59‑14:44:50) (`log:6f5ff0cc8b59`)
- market-data-service latency_p99_ms and error_rate remained essentially at baseline (p99 ≈ 257 ms vs 256 ms baseline; error_rate ≈ 0.00196 vs 0.00195 baseline) (`metric:market-data-service/latency_p99_ms`, `metric:market-data-service/error_rate`)
**Assumptions:**
- ASM-1: ArithmeticException is thrown only for requests that execute the new pricing code path (i.e., accounts with new_pricing_path flag enabled).
- ASM-2: The feature‑flag rollout is per‑account and remains stable for the duration of the incident (no mid‑window toggles).
- ASM-3: The generic 5xx observed by edge‑gateway is the direct HTTP translation of the uncaught ArithmeticException in orders‑service.
**Objections:**
- [minor] gap_unaddressed: The hypothesis predicts errors only for the 20 % of accounts with the flag enabled, but per‑account flag state at request time is not captured in current logs or metrics (GAP‑10). This gap does not block acceptance because three other evidence kinds already converge.

### 2. `dependency_degradation` on **market-data-service** (HYP-2)

Confidence 0.18 (low), critic: reject. An external quotes‑vendor began rate‑limiting (429) and returning 503 responses around 14:35‑14:44. Market‑data‑service forwards these failures to its callers. Because orders‑service has a hard gRPC dependency (500 ms timeout) on market‑data‑service, the vendor degradation leaks through as gRPC errors or timeouts, causing orders‑service to return 5xx for a subset of requests.

**Supporting:**
- market-data-service logged 6 WARN events “quotes‑vendor responded 429; backing off <ms>ms” from 2026‑10‑08T14:42:13.873Z to 2026‑10‑08T15:46:30.422Z (`log:706d3b8ae4bd`)
- market-data-service logged 3 ERROR events “GET /v1/quotes 503 12ms” between 2026‑10‑08T14:35:59.250Z and 2026‑10‑08T14:44:50.789Z (`log:6f5ff0cc8b59`)
- market-data-service vendor_error_rate averaged 0.00106 (baseline 0.00093) with a peak of 0.00220 during the window (`metric:market-data-service/vendor_error_rate`)
- market‑data‑service logs 6 vendor 429‑rate‑limit warnings between 14:42:13.873Z and 15:46:30.422Z (`log:706d3b8ae4bd`)
- market‑data‑service logs 3 HTTP 503 errors on GET /v1/quotes early in the window (14:35:59‑14:44:50) (`log:6f5ff0cc8b59`)
- orders‑service has a hard gRPC dependency on market‑data‑service (500 ms timeout) and a hard SQL dependency on postgres‑orders (2 s timeout). (`dep:orders-service->market-data-service`, `dep:orders-service->postgres-orders`)
- market‑data‑service has a hard HTTPS dependency on quotes‑vendor (800 ms timeout). (`dep:market-data-service->quotes-vendor`)
- Change census shows zero changes for quotes‑vendor and market‑data‑service in the 14:30‑15:00 UTC window. (`chg:2534`)
**Contradicting:**
- market-data-service latency_p99_ms and error_rate remained essentially at baseline (p99 ≈ 257 ms vs 256 ms baseline; error_rate ≈ 0.00196 vs 0.00195 baseline) (`metric:market-data-service/latency_p99_ms`, `metric:market-data-service/error_rate`)
- orders‑service logs an ArithmeticException in PricingPathV2.applyCollar 340 times, first at 2026‑10‑08T15:23:00.702Z and last at 2026‑10‑08T15:49:57.995Z (`log:e56c11822899`)
- edge‑gateway records 312 upstream‑500 warnings for POST /v1/orders from 15:23:05.719Z to 15:49:48.906Z (`log:209f37015f90`)
**Assumptions:**
- ASM-4: The vendor 429/503 bursts were short‑lived and fully absorbed by market‑data‑service’s cache/back‑off logic, leaving no residual error surface.
- ASM-5: The new pricing path does not increase the call‑rate to market‑data‑service enough to saturate the vendor quota.
**Objections:**
- [blocking] ignores_contradiction: Market‑data service metrics show no degradation during the symptom window (OBS‑6), directly contradicting the claim that vendor rate‑limiting leaked through as gRPC errors.

### 3. `config_change` on **auth-service**, triggered by `chg:2536` (HYP-3)

Confidence 0.04 (low), critic: reject. The token refresh grace period was reduced from 120 s to 90 s at 15:05. Clients whose tokens were near expiry would start receiving auth failures (401/403) when placing orders, manifesting as generic errors for a subset of users.

**Supporting:**
- config on auth-service at 15:05:40 UTC by config-bot: Lower token refresh grace period (token.refresh_grace_s: 120 -> 90) (`chg:2536`)
**Contradicting:**
- orders‑service logs an ArithmeticException in PricingPathV2.applyCollar 340 times, first at 2026‑10‑08T15:23:00.702Z and last at 2026‑10‑08T15:49:57.995Z (`log:e56c11822899`)
- edge‑gateway records 312 upstream‑500 warnings for POST /v1/orders from 15:23:05.719Z to 15:49:48.906Z (`log:209f37015f90`)
- No other config changes, feature‑flag toggles, secret rotations, or infra work were recorded for edge‑gateway, market‑data‑service, quotes‑vendor, postgres‑orders, or redis‑cache in the 14:35‑15:50 UTC window. (`chg:2534`)
**Assumptions:**
- ASM-6: The generic order‑placement error reported by customers is not an auth error (no 401/403 observed in any log).
**Objections:**
- [blocking] ignores_contradiction: Observed failures are 5xx with ArithmeticExceptions, not 401/403 auth errors; the hypothesis does not account for this mismatch.

## Recommended actions

| Urgency | Kind | Action | Why |
|---|---|---|---|
| now | mitigate | Roll back the new_pricing_path flag to 0 % rollout immediately. | Disabling the flag stops the faulty code path and eliminates the 5xx errors for affected customers. (HYP-1) |
| soon | fix | Patch the arithmetic bug in PricingPathV2.applyCollar (handle non‑terminating decimals safely) and deploy the fix. | Removes the underlying defect so the new pricing path can be re‑enabled safely. (HYP-1) |
| later | prevent | Add unit and integration tests covering the collar calculation with edge‑case decimal values; enforce canary rollout with automated error‑rate alerts for future flag changes. | Prevents regression of similar arithmetic bugs and catches them before wide exposure. (HYP-1) |
| soon | investigate | Correlate per‑account flag state with request outcomes by instrumenting the flag evaluation in logs/metrics. | Closes GAP‑10 (no per‑account flag visibility) and validates the 20 % error distribution assumption. (HYP-1) |
| later | investigate | Collect quotes‑vendor metrics (error_rate, latency_p99, response‑code distribution) for the incident window. | Addresses GAP‑2 and GAP‑11 to definitively rule out any vendor‑side contribution. (HYP-2) |
| later | investigate | Enable distributed tracing for POST /v1/orders to pinpoint failure origin (orders‑service vs market‑data‑service vs quotes‑vendor). | Closes GAP‑9 and provides end‑to‑end visibility for future incidents. |

## Evidence gaps

- **query_logs** (quotes-vendor logs at INFO/DEBUG level for payload inspection): Only WARN/ERROR patterns were queried; lower‑severity logs may contain evidence of malformed or stale price messages.
- **query_metrics** (quotes-vendor metrics (error_rate, latency_p99, response_code distribution)): No metrics were fetched for quotes-vendor, so we cannot see its health or rate‑limit behavior directly.
- **query_logs** (market-data-service logs mentioning cache refresh, price validation, or stale‑price detection): Current log patterns show only 429 back‑off and 503 errors; no visibility into whether bad prices were cached and served.
- **query_metrics** (orders‑service latency, error rate, CPU, memory, thread‑pool saturation): Metrics not queried; needed to see if orders‑service itself saturated before 15:23.
- **query_logs** (postgres‑orders SQL error / timeout logs): Postgres‑orders service logs not retrieved; could reveal DB‑side failures.
- **query_metrics** (market‑data‑service gRPC call latency and error rate): No metric data fetched for the downstream market‑data dependency.
- **query_metrics** (edge‑gateway upstream latency / error counters): Missing gateway‑side metrics to correlate 5xx volume with upstream latency.
- **get_change_history** (Implementation details of the new_pricing_path flag (code path, config values, validation logic)): Change census only records flag rollout, not the underlying code or config changes.
- **get_service_dependencies** (Distributed traces for failing POST /v1/orders requests to pinpoint whether failure originates in orders‑service validation, market‑data‑service price fetch, or quotes‑vendor call): Dependency tool provides topology but not request‑level trace data.
- **get_change_history** (Per‑account feature‑flag state at request time): No metric linking individual customer accounts to the flag rollout is captured in the change log.
- **get_change_history** (quotes-vendor (external)): External vendor changes are not recorded in internal change census; cannot confirm or rule out vendor‑side rate‑limit config changes.
- **get_change_history** (market-data-service dynamic/runtime config (e.g., Consul/etcd keys, feature‑flag values read at start‑up)): Change census only captures explicit config‑change events; runtime config shifts would not appear.
- **get_change_history** (market-data-service prior deploys (before 14:30 UTC) that may have altered hard‑coded rate‑limit or cache‑TTL constants): A prior deploy could have introduced a latent behavior that only manifests under current load; not covered by the 14:30‑15:00 window query.

## Open questions

- What is the exact per‑account flag state at request time (GAP‑10)?
- What were the quotes‑vendor health metrics during 14:30‑15:50 UTC (GAP‑2, GAP‑11)?
- Do lower‑severity vendor logs show malformed or stale price payloads (GAP‑1)?
- Did market‑data‑service cache or serve any bad prices (GAP‑3)?
- Were there any orders‑service resource saturation signals before 15:23 (GAP‑4)?
- Did postgres‑orders log any SQL errors or timeouts (GAP‑5)?
- What are the gRPC latency/error metrics for the orders‑service → market‑data‑service call (GAP‑6)?
- What do edge‑gateway upstream latency/error counters show (GAP‑7)?
- What are the implementation details and validation logic of the new_pricing_path flag (GAP‑8)?
- Are there any runtime config changes in market‑data‑service not captured by the change census (GAP‑12)?
- Could a prior deploy before 14:30 have introduced latent behavior (GAP‑13)?

## How the investigation ran

Stopped because the critic accepted HYP-1, after 1 round(s): 23 model calls, 11 tool calls, 93,066 tokens, 606 s.
