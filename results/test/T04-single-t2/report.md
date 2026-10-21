# T04: Some order placements failing

**Outcome:** conclusive. Root cause: `code_regression` on **orders-service**, triggered by `chg:2534`

## Summary

At 15:22 UTC a feature flag `new_pricing_path` was rolled out to 20 % of accounts (chg:2534). One minute later orders‑service began throwing `ArithmeticException: Non‑terminating decimal expansion` from `PricingPathV2.applyCollar` (391 errors by 15:55). The service‑wide error rate rose from a baseline of 0.19 % to ~1.7 % (peak ~4 %). No deploys, config changes, secret rotations or infra work occurred. The failure affects only the flagged subset, matching the reported “some customers consistently fail, retry does not help”. The most likely root cause is a code regression in the newly‑enabled pricing path that performs a division without a rounding context.

## Hypotheses

### 1. `code_regression` on **orders-service**, triggered by `chg:2534` (HYP-1)

Confidence 0.92 (high). The new pricing path `PricingPathV2.applyCollar` performs a division on price data without specifying a MathContext, causing a BigDecimal ArithmeticException for prices that yield repeating decimals. The flag rollout enables this path for 20 % of accounts, producing the observed errors and error‑rate spike.

**Supporting:**
- orders‑service logs show a sharp rise of ERROR lines starting 15:23:00 UTC: “order <id> failed: ArithmeticException: Non‑terminating decimal expansion; no exact representable decimal result (at PricingPathV2.applyCollar)”. 391 occurrences, first log:e56c11822899, last 15:54:57. (`log:e56c11822899`)
- orders‑service error_rate metric jumps from baseline 0.0019 to mean 0.0175 (peak 0.0419) over 15:00‑15:55. (`metric:orders-service/error_rate`)
- Change history records a feature‑flag rollout at 15:22:07 UTC: `new_pricing_path` from 0 % → 20 % (chg:2534, actor lena.fischer). No other changes in the window. (`chg:2534`)
- Responder notes confirm no deploys today; change log corroborates only the flag change. (`chg:2534`)
**Assumptions:**
- ASM-1: The feature flag `new_pricing_path` gates execution of `PricingPathV2.applyCollar`.
- ASM-2: The `ArithmeticException` originates from a division that produces a non‑terminating decimal (e.g., BigDecimal.divide without MathContext).

### 2. `data_issue` on **market-data-service** (HYP-2)

Confidence 0.12 (low). Market‑data begins sending price values with higher precision or a new format that the new pricing path cannot represent, while the old path tolerates them. This triggers the same ArithmeticException only for flagged accounts.

**Supporting:**
- orders‑service has a hard gRPC dependency on market‑data‑service (500 ms timeout) and a hard SQL dependency on postgres‑orders (2 s timeout). (`dep:orders-service->market-data-service`, `dep:orders-service->postgres-orders`)
- orders‑service logs show a sharp rise of ERROR lines starting 15:23:00 UTC: “order <id> failed: ArithmeticException: Non‑terminating decimal expansion; no exact representable decimal result (at PricingPathV2.applyCollar)”. 391 occurrences, first log:e56c11822899, last 15:54:57. (`log:e56c11822899`)
**Contradicting:**
- Change history records a feature‑flag rollout at 15:22:07 UTC: `new_pricing_path` from 0 % → 20 % (chg:2534, actor lena.fischer). No other changes in the window. (`chg:2534`)
- Responder notes confirm no deploys today; change log corroborates only the flag change. (`chg:2534`)
- Latency (p50/p99), CPU and memory remain within baseline; the service is not saturated. (`metric:orders-service/latency_p50_ms`, `metric:orders-service/latency_p99_ms`, `metric:orders-service/cpu_util`, `metric:orders-service/mem_util`)
**Assumptions:**
- ASM-3: Market‑data could have changed its payload format without a recorded change.
- ASM-4: The legacy pricing path would have accepted the same price values without throwing.

### 3. `infrastructure_failure` on **redis-cache** (HYP-3)

Confidence 0.08 (low). A short Redis outage returns stale or null price data to the new pricing path, leading to division by zero or malformed decimals and the ArithmeticException.

**Supporting:**
- orders‑service has a hard gRPC dependency on market‑data‑service (500 ms timeout) and a hard SQL dependency on postgres‑orders (2 s timeout). (`dep:orders-service->market-data-service`, `dep:orders-service->postgres-orders`)
**Contradicting:**
- Latency (p50/p99), CPU and memory remain within baseline; the service is not saturated. (`metric:orders-service/latency_p50_ms`, `metric:orders-service/latency_p99_ms`, `metric:orders-service/cpu_util`, `metric:orders-service/mem_util`)
- No error spikes observed in upstream services (edge‑gateway, auth‑service, etc.) during the same period. (`metric:orders-service/rps`)
**Assumptions:**
- ASM-5: A brief Redis cache blip occurred exactly at 15:23 and affected only the flagged accounts.

### 4. `resource_exhaustion` on **postgres-orders** (HYP-4)

Confidence 0.07 (low). Transient DB contention causes the pricing query to return rounding‑error rows only when the new path is used, resulting in the exception.

**Supporting:**
- orders‑service has a hard gRPC dependency on market‑data‑service (500 ms timeout) and a hard SQL dependency on postgres‑orders (2 s timeout). (`dep:orders-service->market-data-service`, `dep:orders-service->postgres-orders`)
**Contradicting:**
- Latency (p50/p99), CPU and memory remain within baseline; the service is not saturated. (`metric:orders-service/latency_p50_ms`, `metric:orders-service/latency_p99_ms`, `metric:orders-service/cpu_util`, `metric:orders-service/mem_util`)
**Assumptions:**
- ASM-6: Database contention manifested only for the new code path.

## Recommended actions

| Urgency | Kind | Action | Why |
|---|---|---|---|
| now | mitigate | Roll back / disable `new_pricing_path` flag (set rollout → 0 %). | Immediately stops the faulty code path and eliminates 5xx errors for the affected 20 %. |
| now | fix | Add a guard in `PricingPathV2.applyCollar` to catch `ArithmeticException` and fall back to legacy pricing logic; then re‑enable flag for a 1 % canary. | Allows safe validation of a fix while keeping the new path off for the majority. |
| soon | prevent | Write unit/integration tests that feed problematic price values (e.g., 1/3, 0.1 repeating) to the collar logic and assert a rounded result instead of an exception. | Prevents regression and documents the exact numeric edge case. |
| soon | fix | Deploy a fix using `BigDecimal.divide(divisor, MathContext.DECIMAL128)` or `setScale` with `RoundingMode.HALF_EVEN`; gradually ramp the flag (5 % → 100 %) while monitoring error_rate. | Controlled rollout with observability ensures the fix works before full exposure. |
| later | prevent | Conduct a post‑mortem to capture why the division lacked a MathContext (code review gap, missing static analysis). | Process improvement to avoid similar regressions. |
| later | investigate | Verify market‑data‑service payload schema stability (add contract tests) to address H2 risk. | Reduces chance of future data‑driven crashes. |

## Evidence gaps

- **query_logs** (market-data-service logs (WARN/ERROR) 15:00‑15:55): Needed to confirm or reject H2 (data issue from market‑data).
- **query_metrics** (redis-cache latency/error metrics 15:00‑15:55): Needed to evaluate H3 (Redis blip).
- **query_metrics** (postgres-orders query latency / lock wait metrics 15:00‑15:55): Needed to evaluate H4 (DB contention).
- **get_change_history** (Feature‑flag evaluation logic for `new_pricing_path` (per‑account vs per‑request)): Clarifies assumption A1 and blast radius.
- **query_logs** (Sample failing order payloads (price, quantity) from orders-service): Reproduce the ArithmeticException and verify the exact numeric trigger.

## Open questions

- Which exact price values trigger the non‑terminating decimal?
- Does market‑data‑service ever emit prices with > scale‑limit precision?
- Was the flag evaluated per‑account or per‑request?
- Are there other code paths (portfolio‑service, notifications) that also call `PricingPathV2` and could surface the same bug?

## How the investigation ran

Stopped because the agent finished its investigation, after 1 round(s): 6 model calls, 4 tool calls, 37,765 tokens, 143 s.
