# T04: Some order placements failing

**Outcome:** conclusive. Root cause: `code_regression` on **orders-service**, triggered by `chg:2534`

## Summary

At 15:22 UTC a feature‑flag rollout (new_pricing_path 0%→20%) enabled a new pricing code path in orders‑service. Within a minute the new code (PricingPathV2.applyCollar) began throwing ArithmeticException: Non‑terminating decimal expansion for the flagged accounts, producing a sustained ~10× rise in 5xx errors (≈2% of all requests) while all downstream services remained healthy. The failure is deterministic for the rolled‑out subset, explaining why retries do not help those customers.

## Hypotheses

### 1. `code_regression` on **orders-service**, triggered by `chg:2534` (HYP-1)

Confidence 0.96 (high). Feature‑flag rollout enables new pricing implementation (PricingPathV2.applyCollar) which performs a division that can produce a non‑terminating decimal, throwing ArithmeticException for affected accounts and returning 5xx.

**Supporting:**
- Orders‑service error‑rate jumped from baseline 0.20% to a window mean 1.31% (last minute 2.36%) – ≈10× increase. (`metric:orders-service/error_rate`)
- At 15:22:07 UTC a feature‑flag change rolled new_pricing_path from 0% → 20% on orders‑service. (`chg:2534`)
- First ArithmeticException in orders‑service logs appears at 15:23:00.7 UTC – “Non‑terminating decimal expansion; no exact representable decimal result (at PricingPathV2.applyCollar)”. 272 occurrences until 15:44:58. (`log:e56c11822899`)
- Exception stack points to PricingPathV2.applyCollar, a code path only exercised when new_pricing_path flag is enabled. (`log:e56c11822899`)
- Dependency graph shows orders‑service calls market‑data‑service (hard, gRPC, 500 ms) and postgres‑orders (hard); both downstream services were healthy. (`dep:orders-service->market-data-service`, `dep:orders-service->postgres-orders`)
**Assumptions:**
- ASM-1: The feature flag new_pricing_path enables the PricingPathV2 code path for the rolled‑out accounts (≈20% of traffic).
- ASM-2: The ArithmeticException is fatal for the request and surfaces as a 5xx to the caller (edge‑gateway → client).
- ASM-3: “Some customers cannot place orders; retrying does not help those customers” maps to deterministic failure for the flagged accounts.

### 2. `dependency_degradation` on **market-data-service** (HYP-2)

Confidence 0.07 (low). Market‑data returns bad or delayed prices causing order validation to fail.

**Supporting:**
- Market‑data‑service showed only a few vendor‑rate‑limit warnings (429) and its error‑rate stayed at baseline. (`metric:market-data-service/error_rate`, `log:09bb3f8bfbff`)
**Contradicting:**
- Orders‑service error‑rate jumped from baseline 0.20% to a window mean 1.31% (last minute 2.36%) – ≈10× increase. (`metric:orders-service/error_rate`)
- Market‑data‑service showed only a few vendor‑rate‑limit warnings (429) and its error‑rate stayed at baseline. (`metric:market-data-service/error_rate`, `log:09bb3f8bfbff`)
- Dependency graph shows orders‑service calls market‑data‑service (hard, gRPC, 500 ms) and postgres‑orders (hard); both downstream services were healthy. (`dep:orders-service->market-data-service`, `dep:orders-service->postgres-orders`)

### 3. `config_change` on **auth-service**, triggered by `chg:2536` (HYP-3)

Confidence 0.04 (low). Reduced token refresh grace period causes auth failures for a subset of users, leading to order rejection.

**Supporting:**
- Auth‑service config change (token refresh grace 120→90s) occurred at 15:05:40 UTC – well before error surge. (`chg:2536`)
**Contradicting:**
- Orders‑service error‑rate jumped from baseline 0.20% to a window mean 1.31% (last minute 2.36%) – ≈10× increase. (`metric:orders-service/error_rate`)
- Postgres‑orders, redis‑cache, auth‑service metrics all remained at baseline; no saturation or error spikes. (`metric:postgres-orders/active_connections`, `metric:postgres-orders/cpu_util`, `metric:postgres-orders/query_latency_p99_ms`, `metric:redis-cache/hit_ratio`, `metric:redis-cache/mem_util`, `metric:auth-service/error_rate`, `metric:auth-service/latency_p99_ms`)
- Dependency graph shows orders‑service calls market‑data‑service (hard, gRPC, 500 ms) and postgres‑orders (hard); both downstream services were healthy. (`dep:orders-service->market-data-service`, `dep:orders-service->postgres-orders`)

### 4. `resource_exhaustion` on **postgres-orders** (HYP-4)

Confidence 0.02 (low). Database connection‑pool exhaustion or query slowdown causes order persistence failures.

**Contradicting:**
- Postgres‑orders, redis‑cache, auth‑service metrics all remained at baseline; no saturation or error spikes. (`metric:postgres-orders/active_connections`, `metric:postgres-orders/cpu_util`, `metric:postgres-orders/query_latency_p99_ms`, `metric:redis-cache/hit_ratio`, `metric:redis-cache/mem_util`, `metric:auth-service/error_rate`, `metric:auth-service/latency_p99_ms`)

## Recommended actions

| Urgency | Kind | Action | Why |
|---|---|---|---|
| now | mitigate | Roll back / disable new_pricing_path flag (set rollout → 0%). | Stops the faulty code path instantly; eliminates the 5xx surge. |
| now | fix | Deploy hot‑fix to guard decimal arithmetic in PricingPathV2.applyCollar (e.g., use BigDecimal with MathContext) and add unit test for collar calculation. | Prevents recurrence when the flag is re‑enabled. |
| soon | mitigate | Verify error‑rate returns to baseline (<0.3%) and order placement succeeds for all accounts. | Confirms mitigation effectiveness. |
| later | prevent | Add automated canary analysis for feature‑flag rollouts, improve numeric‑precision testing, and document flag‑rollout procedure. | Systemic prevention of similar regressions. |

## Evidence gaps

- **query_logs** (Edge‑gateway / client‑side logs showing 5xx mapping to the ArithmeticException): Not queried; would close loop to user‑visible error.
- **get_change_history** (Exact rollout percentage vs observed failure rate to confirm 20% ≈ “some customers”): Only flag rollout percentage known; actual affected traffic not measured.
- **source_code** (Source diff for PricingPathV2.applyCollar to see the exact arithmetic operation): Source code not available via provided tools.

## Open questions

- What exact input values (price, collar ratio) trigger the non‑terminating decimal?
- Why was the flag jumped directly to 20% instead of a gradual rollout?
- Do any downstream services (portfolio‑service, notification‑service) observe side‑effects from the failed orders?

## How the investigation ran

Stopped because the agent finished its investigation, after 1 round(s): 7 model calls, 9 tool calls, 55,325 tokens, 200 s.
