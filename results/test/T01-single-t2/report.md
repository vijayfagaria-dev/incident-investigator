# T01: Order edits failing

**Outcome:** conclusive. Root cause: `code_regression` on **orders-service**, triggered by `chg:2501`

## Summary

At 13:31 UTC the orders-service was deployed to v2.15.0 (chg:2501) adding a new order‑amendment endpoint. The new validation code assumes every order has a limitPrice; market‑type orders have limitPrice == null, causing a NullPointerException in AmendOrderHandler.validate. The exception appears as 500 errors from orders-service (log pattern F1) and upstream 5xx on edge‑gateway (log pattern F2). Error‑rate spikes from a baseline of ~0.2% to ~6% (metric F3) while all resource metrics stay normal (F4). No config, flag, secret or infra changes occurred in the window (F5). The root cause is a code regression in the newly deployed amendment endpoint.

## Hypotheses

### 1. `code_regression` on **orders-service**, triggered by `chg:2501` (HYP-1)

Confidence 0.96 (high). The v2.15.0 amendment endpoint validates order.limitPrice without a null check. Market orders have null limitPrice, causing a NullPointerException that bubbles up as HTTP 500. Edge‑gateway propagates these as upstream 5xx, producing the observed customer‑facing errors.

**Supporting:**
- orders-service logs show a NullPointerException “Cannot invoke BigDecimal.compareTo because order.limitPrice is null” in AmendOrderHandler.validate on PATCH /v1/orders, 447 occurrences, first at 13:33:01 UTC. (`log:0953dd5b47dc`)
- edge‑gateway logs record upstream 500 responses from orders-service on route /v1/orders, 420 occurrences, first at 13:34:06 UTC. (`log:a41f996d606e`)
- orders-service error_rate metric rises from baseline 0.0021 to a mean of 0.019 (peak 0.066) over the incident window. (`metric:orders-service/error_rate`)
- A single production change occurred: deploy of orders-service v2.15.0 at 13:31:20 UTC (chg:2501) adding the order amendment endpoint. (`chg:2501`)
**Assumptions:**
- ASM-1: The new amendment endpoint (PATCH /v1/orders) is the only code path that validates order.limitPrice.
- ASM-2: Market‑type orders legitimately have limitPrice == null and were handled correctly in v2.14.3.
- ASM-3: The deploy at 13:31 UTC was fully rolled out before the first NPE at 13:33 UTC (typical rollout < 2 min).

### 2. `config_change` on **orders-service** (HYP-2)

Confidence 0.05 (low). A configuration change or feature‑flag enabled stricter validation that rejects null limitPrice.

**Contradicting:**
- A single production change occurred: deploy of orders-service v2.15.0 at 13:31:20 UTC (chg:2501) adding the order amendment endpoint. (`chg:2501`)

### 3. `dependency_degradation` on **market-data-service** (HYP-3)

Confidence 0.04 (low). Degraded market‑data service returns malformed order objects lacking limitPrice, leading to NPE.

**Contradicting:**
- orders-service CPU, memory, DB‑pool usage and request rate remain within baseline ranges throughout the window. (`metric:orders-service/cpu_util`, `metric:orders-service/mem_util`, `metric:orders-service/db_pool_in_use`, `metric:orders-service/rps`)

### 4. `resource_exhaustion` on **orders-service** (HYP-4)

Confidence 0.03 (low). Thread‑pool or DB‑pool exhaustion corrupts request state, causing null limitPrice.

**Contradicting:**
- orders-service CPU, memory, DB‑pool usage and request rate remain within baseline ranges throughout the window. (`metric:orders-service/cpu_util`, `metric:orders-service/mem_util`, `metric:orders-service/db_pool_in_use`, `metric:orders-service/rps`)

## Recommended actions

| Urgency | Kind | Action | Why |
|---|---|---|---|
| now | mitigate | Rollback orders-service to v2.14.3 (or disable the amendment endpoint via feature flag). | Stops the NPE immediately; the deploy is the only change correlated with onset. |
| soon | fix | Deploy a patch adding a null check / default handling for order.limitPrice in AmendOrderHandler.validate and run amendment‑endpoint tests. | Addresses the code regression so the endpoint can be re‑enabled safely. |
| later | prevent | Add contract / schema validation and a CI gate that ensures all new endpoints handle optional fields (e.g., limitPrice) safely. | Prevents similar regressions when future endpoints are added. |
| later | investigate | Review feature‑flag rollout strategy for new endpoints to allow gradual traffic shift and quick disable. | Provides operational safety net for future deployments. |

## Evidence gaps

- **query_logs** (orders-service AmendOrderHandler source diff (validation logic for limitPrice)): Source code diffs are not available via the provided tools.
- **query_logs** (market-data-service and postgres-orders logs during 13:30‑14:00 UTC): Not queried; would confirm downstream health.
- **query_metrics** (market-data-service error_rate, latency, and saturation metrics for the same window): Not queried; would rule out hidden dependency degradation.

## Open questions

- What fraction of amendment requests during the window were market orders (limitPrice null)?
- Are there other validation paths in the amendment endpoint that could fail similarly?
- Did any canary or staging run of v2.15.0 execute amendment requests with null limitPrice?

## How the investigation ran

Stopped because the agent finished its investigation, after 1 round(s): 7 model calls, 5 tool calls, 43,418 tokens, 271 s.
