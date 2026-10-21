# T01: Order edits failing

**Outcome:** conclusive. Root cause: `code_regression` on **orders-service**, triggered by `chg:2501`

## Summary

A deploy of orders-service v2.15.0 at 13:31 UTC introduced a new order amendment endpoint. Starting at 13:33 UTC the service threw NullPointerExceptions in AmendOrderHandler.validate because order.limitPrice was null, causing 500 responses that propagated to edge-gateway. Error-rate metric spiked while CPU, memory, DB pool and latency stayed normal. No config, flag, secret or infra changes occurred in the window. Root cause is a code regression in the newly added handler.

## Hypotheses

### 1. `code_regression` on **orders-service**, triggered by `chg:2501` (HYP-1)

Confidence 0.96 (high). The new amendment handler validates limitPrice by calling compareTo without first checking for null; when a market order (limitPrice=null) is edited, a NullPointerException is thrown, resulting in a 500 that edge-gateway surfaces.

**Supporting:**
- orders-service v2.15.0 deployed (add order amendment endpoint) at 2026-10-05T13:31:20Z (`chg:2501`)
- orders-service logs show NullPointerException: order.limitPrice is null in AmendOrderHandler.validate (PATCH /v1/orders) – 413 occurrences, first at 13:33:01Z (`log:0953dd5b47dc`)
- edge-gateway logs show upstream orders-service returned 500 on /v1/orders – 379 occurrences, first at 13:34:05Z (`log:a41f996d606e`)
- orders-service error_rate metric rose from baseline 0.0021 to peak 0.0663 (mean 0.0185) between 13:31‑13:58Z (`metric:orders-service/error_rate`)
**Assumptions:**
- ASM-1: Customer edit action maps to PATCH /v1/orders (the amendment endpoint added in v2.15.0)
- ASM-2: An order can legitimately have limitPrice == null (e.g., market orders) and the new validation omitted a null check

### 2. `config_change` on **orders-service** (HYP-2)

Confidence 0.02 (low). A configuration change (e.g., feature flag) disabled a default price value causing limitPrice to be null.

**Contradicting:**
- orders-service v2.15.0 deployed (add order amendment endpoint) at 2026-10-05T13:31:20Z (`chg:2501`)
- orders-service CPU, memory, DB pool usage, latency_p99 and RPS remained within normal bounds during the same window (`metric:orders-service/cpu_util`, `metric:orders-service/mem_util`, `metric:orders-service/db_pool_in_use`, `metric:orders-service/latency_p99_ms`, `metric:orders-service/rps`)

### 3. `dependency_degradation` on **orders-service** (HYP-3)

Confidence 0.01 (low). market-data-service started returning null prices, causing orders-service to store null limitPrice.

**Contradicting:**
- orders-service logs show NullPointerException: order.limitPrice is null in AmendOrderHandler.validate (PATCH /v1/orders) – 413 occurrences, first at 13:33:01Z (`log:0953dd5b47dc`)
- orders-service CPU, memory, DB pool usage, latency_p99 and RPS remained within normal bounds during the same window (`metric:orders-service/cpu_util`, `metric:orders-service/mem_util`, `metric:orders-service/db_pool_in_use`, `metric:orders-service/latency_p99_ms`, `metric:orders-service/rps`)

### 4. `resource_exhaustion` on **orders-service** (HYP-4)

Confidence 0.01 (low). Database connection pool saturation caused failures that manifest as NPE.

**Contradicting:**
- orders-service CPU, memory, DB pool usage, latency_p99 and RPS remained within normal bounds during the same window (`metric:orders-service/cpu_util`, `metric:orders-service/mem_util`, `metric:orders-service/db_pool_in_use`, `metric:orders-service/latency_p99_ms`, `metric:orders-service/rps`)

## Recommended actions

| Urgency | Kind | Action | Why |
|---|---|---|---|
| now | mitigate | Rollback orders-service to v2.14.3 or deploy hot‑fix adding null guard in AmendOrderHandler.validate | Immediately stops the NPE and restores edit functionality |
| now | fix | Add defensive check `if (order.limitPrice == null) return errorResponse` before compareTo in the amendment handler | Permanent code fix for the regression |
| soon | prevent | Add unit/integration test covering PATCH /v1/orders with missing limitPrice (market order) | Prevents regression of same null‑check omission |
| later | prevent | Update code‑review checklist to require null checks on optional fields for new endpoints | Process improvement to catch similar bugs early |
| later | investigate | Enable structured error code for “missing limit price” and add alert on its occurrence | Improves observability for future incidents |

## Evidence gaps

- **get_change_history** (Full diff of commit e4a91c2 (orders-service v2.15.0) to confirm missing null check): Source code diffs are not accessible via available tooling
- **query_logs** (market-data-service logs 13:30‑13:58 UTC): Not queried; low priority given high confidence in H1
- **query_logs** (Request payloads for PATCH /v1/orders during incident): Tooling does not capture request bodies

## Open questions

- Exact diff of commit e4a91c2 – does it contain any other changes affecting order editing?
- What is the full customer impact scope (only price/qty edits or any PATCH payload)?
- Why did pre‑prod testing not catch the missing null check (missing market‑order test case)?

## How the investigation ran

Stopped because the agent finished its investigation, after 1 round(s): 7 model calls, 5 tool calls, 43,914 tokens, 238 s.
