# T04: Some order placements failing

**Outcome:** conclusive. Root cause: `feature_flag` on **orders-service**, triggered by `chg:2534`

## Summary

Starting at ~15:22 UTC a feature flag (new_pricing_path) was rolled out to 20% of accounts on orders‑service. The flag enables a new pricing implementation (PricingPathV2.applyCollar) that throws an ArithmeticException (“Non‑terminating decimal expansion”) for certain price inputs, producing a steady stream of 5xx errors for the affected accounts while overall service health metrics remain normal. The critic accepted HYP‑1 (confidence 0.78) as the root cause; the investigation stopped because this hypothesis fully explains the observed logs and metrics. The exact code paths activated by the flag have not been verified (GAP‑5).

## Hypotheses

### 1. `feature_flag` on **orders-service**, triggered by `chg:2534` (HYP-1)

Confidence 0.78 (high), critic: accept. The feature flag new_pricing_path was rolled out to 20% of accounts at 15:22 UTC. The flag enables the new pricing implementation PricingPathV2.applyCollar, which contains a bug that throws ArithmeticException: Non‑terminating decimal expansion for certain price inputs. Affected accounts consistently receive a generic 5xx error on POST /v1/orders.

**Supporting:**
- feature_flag on orders-service at 15:22:07 UTC by lena.fischer: Roll out new_pricing_path to 20% of accounts (flag: new_pricing_path, rollout: 0% -> 20%) (`chg:2534`)
- Orders‑service logs show 340 occurrences of “ArithmeticException: Non‑terminating decimal expansion; no exact representable decimal result (at PricingPathV2.applyCollar)” between 15:23:00.702 Z and 15:49:57.995 Z. (`log:e56c11822899`)
- Orders‑service error_rate metric rises sharply at the 15:22 UTC bucket (0.02187) and the 15:25 UTC bucket (0.02489), reaching 0.03637 by 15:49 UTC; baseline_mean is 0.001966. (`metric:orders-service/error_rate`)
- Orders‑service latency_p99, cpu_util, mem_util, db_pool_in_use and rps remain within baseline ranges throughout the window. (`metric:orders-service/latency_p99_ms`, `metric:orders-service/cpu_util`, `metric:orders-service/mem_util`, `metric:orders-service/db_pool_in_use`, `metric:orders-service/rps`)
**Assumptions:**
- ASM-1: The feature flag new_pricing_path switches the code path to PricingPathV2.applyCollar.
- ASM-2: The ArithmeticException is raised only for accounts that have the flag enabled (the 20% rollout).
**Objections:**
- [minor] gap_unaddressed: The feature‑flag definition (what code paths new_pricing_path enables) has not been confirmed (GAP‑5). Without it we assume the flag activates PricingPathV2.applyCollar.

### 2. `data_issue` on **market-data-service** (HYP-2)

Confidence 0.22 (low), critic: challenge. Market‑data‑service (hard gRPC dependency of orders‑service) begins emitting price values that cannot be represented exactly as a decimal (e.g., repeating fractions). The existing pricing code (or the new path) attempts to apply a collar and throws the same ArithmeticException, causing order failures for a subset of customers.

**Supporting:**
- orders-service has a hard gRPC dependency on market-data-service (dep:orders-service->market-data-service, timeout 500 ms). (`dep:orders-service->market-data-service`)
- Orders‑service logs show 340 occurrences of “ArithmeticException: Non‑terminating decimal expansion; no exact representable decimal result (at PricingPathV2.applyCollar)” between 15:23:00.702 Z and 15:49:57.995 Z. (`log:e56c11822899`)
- Orders‑service error_rate metric rises sharply at the 15:22 UTC bucket (0.02187) and the 15:25 UTC bucket (0.02489), reaching 0.03637 by 15:49 UTC; baseline_mean is 0.001966. (`metric:orders-service/error_rate`)
**Contradicting:**
- No recorded changes (config, feature‑flag, secret rotation, deploy, infra) for market-data-service, quotes-vendor, redis-cache, postgres-orders, edge-gateway, or kafka in the 14:40‑15:50 window. (`chg:2536`, `chg:2534`)
**Assumptions:**
- ASM-3: Market‑data can emit a price that triggers the decimal‑expansion bug in the pricing code.
- ASM-4: The bug is not limited to the new flag; the old pricing path would also fail on such a payload.
**Objections:**
- [blocking] gap_unaddressed: No logs or metrics from market‑data‑service (or quotes‑vendor) have been retrieved for the 15:20‑15:30 UTC window (GAP‑1, GAP‑2). This evidence is required to confirm or refute the bad‑price claim.
- [blocking] alternative_not_excluded: HYP‑1 already has change, log, and metric evidence that fully explains the symptom. Until HYP‑1 is ruled out, HYP‑2 remains an un‑excluded alternative.

### 3. `config_change` on **auth-service**, triggered by `chg:2536` (HYP-3)

Confidence 0.07 (low), critic: reject. The token refresh grace period was reduced from 120 s to 90 s at 15:05 UTC. A subset of clients now present expired refresh tokens, which the edge‑gateway or orders‑service translate into a generic 5xx error on order placement.

**Supporting:**
- config on auth-service at 15:05:40 UTC by config-bot: Lower token refresh grace period (token.refresh_grace_s: 120 -> 90) (`chg:2536`)
- auth-service config changed: token.refresh_grace_s lowered from 120 to 90 seconds at 2026-10-08T15:05:40Z (chg:2536). (`chg:2536`)
**Contradicting:**
- Orders‑service logs show 340 occurrences of “ArithmeticException: Non‑terminating decimal expansion; no exact representable decimal result (at PricingPathV2.applyCollar)” between 15:23:00.702 Z and 15:49:57.995 Z. (`log:e56c11822899`)
- Orders‑service latency_p99, cpu_util, mem_util, db_pool_in_use and rps remain within baseline ranges throughout the window. (`metric:orders-service/latency_p99_ms`, `metric:orders-service/cpu_util`, `metric:orders-service/mem_util`, `metric:orders-service/db_pool_in_use`, `metric:orders-service/rps`)
**Assumptions:**
- ASM-5: Token‑grace reduction can manifest as a generic 5xx without leaving a distinct auth‑error in orders‑service logs.
**Objections:**
- [blocking] ignores_contradiction: The hypothesis predicts auth‑related failures, yet the logs show a pure arithmetic exception (OBS‑3) and all service health metrics stay normal (OBS‑5). These observations directly contradict an authentication‑token cause.

## Recommended actions

| Urgency | Kind | Action | Why |
|---|---|---|---|
| now | mitigate | Roll back the new_pricing_path feature flag to 0% for all accounts. | Immediately stops the ArithmeticException and restores order placement for the affected 20% of customers. (HYP-1) |
| soon | fix | Patch PricingPathV2.applyCollar to handle non‑terminating decimal expansions (e.g., use BigDecimal with a defined scale or rounding mode). | Removes the underlying bug so the new pricing path can be safely re‑enabled. (HYP-1) |
| later | prevent | Add automated unit/integration tests covering edge‑case price values that produce repeating decimals, and enforce a flag‑rollout validation step that runs the test suite before any percentage increase. | Prevents regressions and ensures future flag changes are guarded by verification. (HYP-1) |
| later | investigate | Retrieve the feature‑flag definition for new_pricing_path to confirm exactly which code paths it enables (address GAP‑5). | Closes the remaining evidence gap and documents the flag’s scope for future audits. (HYP-1) |

## Evidence gaps

- **query_logs** (market-data-service, postgres-orders, edge-gateway (WARN+ patterns 14:40‑15:50 UTC)): Tool steps exhausted; logs for the other three services were not retrieved.
- **query_metrics** (market-data-service, postgres-orders, edge-gateway (full metric summaries 14:40‑15:50 UTC)): Tool steps exhausted; metrics for the other three services were not retrieved.
- **get_change_history** (market-data-service, quotes-vendor, redis-cache, postgres-orders, edge-gateway, kafka): Change census only returned two changes; we cannot confirm absence of unreported infra work (e.g., secret rotations, config pushes) on these services without broader audit logs.
- **get_service_dependencies** (auth-service downstream dependencies): Dependency graph does not show auth-service as a caller of orders-service or edge-gateway, so we cannot verify whether the token‑grace change can affect order placement.
- **get_change_history** (feature‑flag definition for new_pricing_path): We lack details on what code paths the flag enables; without that we cannot assess whether the flag could introduce a hard‑dependency failure.

## Open questions

- What precise code paths does the new_pricing_path feature flag activate? (GAP‑5)
- Are there any unreported configuration or infrastructure changes on market‑data‑service or its upstream quotes‑vendor during the incident window? (GAP‑1, GAP‑2, GAP‑3)

## How the investigation ran

Stopped because the critic accepted HYP-1, after 1 round(s): 15 model calls, 7 tool calls, 55,414 tokens, 402 s.
