# T04: Some order placements failing

**Outcome:** conclusive. Root cause: `code_regression` on **orders-service**, triggered by `chg:2534`

## Summary

At 15:22 UTC the feature flag `new_pricing_path` was rolled out to 20% of accounts on `orders-service`. Within a minute the new pricing implementation (`PricingPathV2.applyCollar`) began throwing `ArithmeticException: Non‑terminating decimal expansion` for a subset of orders, causing a sharp rise in 5xx errors (error‑rate from 0.2% to >4%). The failure is consistent for the flagged customers while the remaining 80% succeed. No deploy, config, or infrastructure change coincided; downstream services show no anomalies. Root cause is a code regression in the newly‑enabled pricing path.

## Hypotheses

### 1. `code_regression` on **orders-service**, triggered by `chg:2534` (HYP-1)

Confidence 0.92 (high). The newly enabled `PricingPathV2.applyCollar` performs a division that can produce a non‑terminating decimal for certain price/size combinations, throwing an ArithmeticException that bubbles up as a 5xx error for the 20% of accounts with the flag on.

**Supporting:**
- orders-service error_rate rose from a baseline of 0.19% to a peak of 4.19% between 15:00‑15:55 UTC. (`metric:orders-service/error_rate`)
- First ERROR log matching 'ArithmeticException: Non‑terminating decimal expansion; no exact representable decimal result (at PricingPathV2.applyCollar)' appears at 15:23:00 UTC and repeats 391 times until 15:54 UTC. (`log:e56c11822899`)
- Feature flag `new_pricing_path` for orders-service rolled out from 0% to 20% at 15:22:07 UTC. (`chg:2534`)
- The failing log line references `PricingPathV2.applyCollar`, a code path only exercised when the `new_pricing_path` flag is on. (`log:e56c11822899`)
**Assumptions:**
- ASM-1: The feature flag `new_pricing_path` controls entry into `PricingPathV2.applyCollar`.
- ASM-2: The ArithmeticException propagates uncaught and results in a 5xx response to the client.

### 2. `data_issue` on **market-data-service** (HYP-2)

Confidence 0.04 (low). Market-data began sending a price value with a non‑terminating decimal representation, which the new pricing path cannot handle, causing the same ArithmeticException.

**Supporting:**
- First ERROR log matching 'ArithmeticException: Non‑terminating decimal expansion; no exact representable decimal result (at PricingPathV2.applyCollar)' appears at 15:23:00 UTC and repeats 391 times until 15:54 UTC. (`log:e56c11822899`)
**Contradicting:**
- Feature flag `new_pricing_path` for orders-service rolled out from 0% to 20% at 15:22:07 UTC. (`chg:2534`)
- No deploys, config changes, secret rotations or infra work for orders-service or market-data-service in the 14:00‑16:00 window. (`chg:2534`)
- Dependency graph shows orders-service → market-data-service (gRPC, hard, 500 ms) and orders-service → postgres-orders (SQL, hard). Both downstream services exhibit baseline latency and resource usage. (`dep:orders-service->market-data-service`, `dep:orders-service->postgres-orders`)
- orders-service latency_p99_ms and cpu_util remain close to baseline during the incident. (`metric:orders-service/latency_p99_ms`, `metric:orders-service/cpu_util`)
**Assumptions:**
- ASM-3: Market-data-service did not emit anomalous price values at 15:23 UTC.

### 3. `resource_exhaustion` on **postgres-orders** (HYP-3)

Confidence 0.02 (low). Database contention leads to transaction aborts that surface as arithmetic errors in the pricing code.

**Supporting:**
- orders-service error_rate rose from a baseline of 0.19% to a peak of 4.19% between 15:00‑15:55 UTC. (`metric:orders-service/error_rate`)
**Contradicting:**
- Dependency graph shows orders-service → market-data-service (gRPC, hard, 500 ms) and orders-service → postgres-orders (SQL, hard). Both downstream services exhibit baseline latency and resource usage. (`dep:orders-service->market-data-service`, `dep:orders-service->postgres-orders`)
- orders-service latency_p99_ms and cpu_util remain close to baseline during the incident. (`metric:orders-service/latency_p99_ms`, `metric:orders-service/cpu_util`)
**Assumptions:**
- ASM-4: A database issue would manifest as SQL errors, not a Java ArithmeticException.

### 4. `infrastructure_failure` on **redis-cache** (HYP-4)

Confidence 0.02 (low). Corrupted cache entries feed stale price data to the new pricing path, triggering the exception.

**Supporting:**
- First ERROR log matching 'ArithmeticException: Non‑terminating decimal expansion; no exact representable decimal result (at PricingPathV2.applyCollar)' appears at 15:23:00 UTC and repeats 391 times until 15:54 UTC. (`log:e56c11822899`)
**Contradicting:**
- Dependency graph shows orders-service → market-data-service (gRPC, hard, 500 ms) and orders-service → postgres-orders (SQL, hard). Both downstream services exhibit baseline latency and resource usage. (`dep:orders-service->market-data-service`, `dep:orders-service->postgres-orders`)
- orders-service latency_p99_ms and cpu_util remain close to baseline during the incident. (`metric:orders-service/latency_p99_ms`, `metric:orders-service/cpu_util`)
**Assumptions:**
- ASM-5: Redis is a soft dependency for orders-service and its failure would affect many code paths, not only the new pricing flag.

## Recommended actions

| Urgency | Kind | Action | Why |
|---|---|---|---|
| now | mitigate | Rollback feature flag `new_pricing_path` to 0% for orders-service. | Immediately stops the faulty code path; error-rate should return to baseline. |
| soon | fix | Add safe division/rounding in `PricingPathV2.applyCollar` (e.g., BigDecimal with MathContext) and write unit tests for problematic price/size combos. | Eliminates the ArithmeticException so the new pricing path can be re‑enabled safely. |
| later | investigate | Canary the fixed version behind the same flag, monitor error_rate and latency for 30 minutes before full rollout. | Validates the fix in production with limited exposure. |
| later | prevent | Extend integration tests to cover price values that produce non‑terminating decimals; add alerting on orders-service error_rate spikes >1%. | Early detection of similar bugs in future releases. |

## Evidence gaps

- **query_logs** (market-data-service logs 15:20‑15:30 UTC): Not queried; needed to confirm or rule out a price anomaly.
- **query_logs** (orders-service detailed trace for a failing order (request payload, price values)): Source code and request payloads unavailable; would identify the exact values causing the non‑terminating decimal.
- **get_change_history** (any config or secret changes for pricing library shared across services): Change history only covered orders-service and market-data-service; a shared library change could be missed.

## Open questions

- Which exact price/size combinations cause the non‑terminating decimal in `applyCollar`?
- Did any market-data price feed momentarily emit such a value, or is the bug purely internal to the pricing calculation?
- Are there other callers of `PricingPathV2` (e.g., portfolio-service) that might be affected once the flag is widened?

## How the investigation ran

Stopped because the agent finished its investigation, after 1 round(s): 7 model calls, 5 tool calls, 41,616 tokens, 141 s.
