# T04: Some order placements failing

**Outcome:** conclusive. Root cause: `code_regression` on **orders-service**, triggered by `chg:2534`

## Summary

At 15:22 UTC the feature flag new_pricing_path was rolled out to 20 % of accounts (chg:2534). Shortly afterward orders‑service began logging ArithmeticException: “Non‑terminating decimal expansion” from the new code path PricingPathV2.applyCollar, and the error rate rose from ~0.2 % to >3 % matching the flag’s rollout percentage. The critic accepted HYP‑1 (confidence 0.88) as the root cause and rejected the alternative hypotheses. The investigation is therefore conclusive, but we still lack visibility into whether the external quotes‑vendor ever emits malformed price payloads and we have no DEBUG/INFO logs or vendor metrics to confirm or rule that out.

## Hypotheses

### 1. `code_regression` on **orders-service**, triggered by `chg:2534` (HYP-1)

Confidence 0.88 (high), critic: accept. The feature flag new_pricing_path enables a new code path (PricingPathV2.applyCollar). For certain price values the new logic performs a division that yields a non‑terminating decimal, causing an ArithmeticException that bubbles up as a 5xx response. Only the 20 % of accounts with the flag enabled hit this path, matching the observed failure share.

**Supporting:**
- feature_flag on orders-service at 15:22:07 UTC by lena.fischer: Roll out new_pricing_path to 20% of accounts (flag: new_pricing_path, rollout: 0% -> 20%) (`chg:2534`)
- orders-service error_rate rose from a baseline mean of 0.001966 to 0.02187 at 15:22 UTC and continued climbing to 0.03637 by 15:49 UTC. (`metric:orders-service/error_rate`)
- Log pattern “order <order> failed: ArithmeticException: Non‑terminating decimal expansion; no exact representable decimal result (at PricingPathV2.applyCollar)” first appears at 2026‑10‑08T15:23:00.702Z and occurs 340 times through 15:49 UTC. (`log:e56c11822899`)
- Feature flag new_pricing_path was rolled out to 20 % of accounts at 2026‑10‑08T15:22:07Z. (`chg:2534`)
- Feature flag new_pricing_path on orders-service was rolled out from 0 % to 20 % at 15:22 UTC (chg:2534); symptom onset at ~15:25 UTC and only a subset of customers affected, matching the rollout percentage. (`chg:2534`)
**Assumptions:**
- ASM-1: PricingPathV2.applyCollar performs a division/rounding that can produce a non‑terminating decimal for certain price inputs.
- ASM-2: The feature flag new_pricing_path only controls execution of the new pricing path; the legacy path remains unchanged.

### 2. `dependency_degradation` on **market-data-service** (HYP-2)

Confidence 0.22 (low), critic: challenge. An external quotes‑vendor change (not visible in internal change census) began emitting malformed price payloads (e.g., repeating‑decimal values). The new pricing path in orders‑service processes these payloads and throws the same ArithmeticException, but the old path tolerates them. Because the flag was rolled out at the same time, only flagged accounts surface the error.

**Supporting:**
- market-data-service logged WARN messages “quotes-vendor responded 429; backing off <ms>ms” six times, first at 2026-10-08T14:42:13.873Z and last at 2026-10-08T15:46:30.422Z. (`log:706d3b8ae4bd`)
- market-data-service logged ERROR responses “GET /v1/quotes/{symbol} 502 27ms” twice, at 2026-10-08T14:44:33.958Z and 2026-10-08T14:44:50.789Z. (`log:cf20f569a90e`)
- market-data-service vendor_error_rate metric averaged 0.00104 over the interval, above its baseline mean of 0.000967, indicating a slight increase in vendor‑side errors. (`metric:market-data-service/vendor_error_rate`)
**Contradicting:**
- Log pattern “order <order> failed: ArithmeticException: Non‑terminating decimal expansion; no exact representable decimal result (at PricingPathV2.applyCollar)” first appears at 2026‑10‑08T15:23:00.702Z and occurs 340 times through 15:49 UTC. (`log:e56c11822899`)
- Feature flag new_pricing_path on orders-service was rolled out from 0 % to 20 % at 15:22 UTC (chg:2534); symptom onset at ~15:25 UTC and only a subset of customers affected, matching the rollout percentage. (`chg:2534`)
- Auth-service config change (token.refresh_grace_s 120→90) at 15:05 UTC (chg:2536) is not on the failing path; auth-service does not appear as a downstream dependency of orders-service. (`chg:2536`, `dep:orders-service->market-data-service`, `dep:orders-service->postgres-orders`)
**Assumptions:**
- ASM-3: A malformed price payload (e.g., a repeating decimal) from quotes‑vendor can trigger the same ArithmeticException when processed by the new pricing code.
- ASM-4: The external quotes‑vendor may have deployed a configuration or schema change around 15:15‑15:30 that is not captured in internal change history.
**Objections:**
- [minor] gap_unaddressed: No vendor‑payload validation logs or metrics are available to confirm malformed price values; GAP‑7 (DEBUG/INFO logs not captured) and GAP‑8 (vendor exposes no metrics) leave this unverified.

### 3. `config_change` on **auth-service**, triggered by `chg:2536` (HYP-3)

Confidence 0.04 (low), critic: reject. Reducing token.refresh_grace_s from 120 s to 90 s causes token‑refresh failures for a subset of clients that happen to be on the new pricing path, leading to downstream 5xx from orders‑service.

**Supporting:**
- config on auth-service at 15:05:40 UTC by config-bot: Lower token refresh grace period (token.refresh_grace_s: 120 -> 90) (`chg:2536`)
- Auth‑service config change (token.refresh_grace_s 120→90) occurred at 2026‑10‑08T15:05:40Z, well before the error spike. (`chg:2536`)
**Contradicting:**
- Auth-service config change (token.refresh_grace_s 120→90) at 15:05 UTC (chg:2536) is not on the failing path; auth-service does not appear as a downstream dependency of orders-service. (`chg:2536`, `dep:orders-service->market-data-service`, `dep:orders-service->postgres-orders`)
- Feature flag new_pricing_path on orders-service was rolled out from 0 % to 20 % at 15:22 UTC (chg:2534); symptom onset at ~15:25 UTC and only a subset of customers affected, matching the rollout percentage. (`chg:2534`)
**Assumptions:**
- ASM-5: The new pricing path might call an authenticated endpoint that now rejects tokens refreshed under the tighter grace period.
**Objections:**
- [blocking] ignores_contradiction: Observations OBS‑9 and OBS‑10 directly contradict the hypothesis: auth‑service is not on the failing path and the error subset matches the feature‑flag rollout, not an auth‑token issue.

## Recommended actions

| Urgency | Kind | Action | Why |
|---|---|---|---|
| now | mitigate | Disable the new_pricing_path feature flag (roll back to 0 %) to stop the ArithmeticException errors immediately. | The flag rollout correlates exactly with the error spike; turning it off removes the faulty code path for all users. (HYP-1) |
| soon | fix | Patch PricingPathV2.applyCollar to handle non‑terminating decimal results (e.g., use BigDecimal with a defined rounding mode or guard against division that yields repeating decimals). | The exception originates from a division that can produce a non‑terminating decimal for certain price values; fixing the arithmetic eliminates the root cause. (HYP-1) |
| later | prevent | Add automated unit/integration tests covering edge‑case price values that trigger non‑terminating decimals, and enforce a pre‑rollout checklist for feature‑flag changes including error‑rate monitoring. | Testing the problematic arithmetic and gating flag rollouts on error‑rate alerts will prevent regression. (HYP-1) |
| later | investigate | Enable DEBUG/INFO logging on the quotes‑vendor integration (or request vendor payload samples) to determine whether malformed price values are ever sent. | GAP‑7 notes that lower‑severity logs were not captured; confirming or disproving vendor‑side malformed payloads closes the remaining uncertainty around HYP‑2. (HYP-2) |
| later | investigate | Establish a metrics contract with the quotes‑vendor (latency, error, payload‑validation metrics) or implement a wrapper that validates price payload schema before processing. | GAP‑8 shows the vendor exposes no metrics; without visibility we cannot fully rule out external data quality issues. (HYP-2) |

## Evidence gaps

- **query_logs** (market-data-service, edge-gateway, postgres-orders, auth-service (WARN+ patterns) 14:40‑15:50 UTC): Tool step limit reached; downstream logs not retrieved.
- **query_metrics** (Full metric summaries for market-data-service, edge-gateway, postgres-orders, auth-service 14:40‑15:50 UTC): Tool step limit reached; downstream metrics not retrieved.
- **query_metrics** (Per‑minute latency/error series for orders-service downstream calls (e.g., market‑data client latency) 15:20‑15:35 UTC): Metric not available in current dataset; would require service‑specific instrumentation.
- **get_change_history** (External vendor quotes-vendor): Change census only covers internal services; an outage or config change at quotes-vendor would not appear.
- **get_service_dependencies** (Depth limited to 2 hops): Potential indirect dependencies beyond two hops (e.g., auth-service via a shared library) were not examined.
- **get_change_history** (Secret rotations on redis-cache or postgres-orders): Secret rotations may be logged in a separate audit system not queried by the change‑history endpoint.
- **query_logs** (quotes-vendor DEBUG/INFO level logs for price payload validation): Only WARN+ patterns were queried; lower‑severity logs that could reveal malformed or stale prices were not captured.
- **query_metrics** (quotes-vendor latency, error, and payload‑validation metrics): quotes-vendor exposes no metrics in the monitoring system, so quantitative vendor health cannot be assessed.

## Open questions

- Does the external quotes‑vendor occasionally emit price values that cause non‑terminating decimal expansions?
- Are there any secret rotations or indirect dependencies (beyond two hops) that could affect orders‑service behavior?
- What are the full downstream latency/error metrics for market‑data‑service calls during the incident window (GAP‑1, GAP‑2, GAP‑3)?

## How the investigation ran

Stopped because the critic accepted HYP-1, after 1 round(s): 19 model calls, 12 tool calls, 71,025 tokens, 470 s.
