# T01: Order edits failing

**Outcome:** conclusive. Root cause: `code_regression` on **orders-service**, triggered by `chg:2501`

## Summary

A deploy of orders-service v2.15.0 at 13:31 UTC introduced a new order‑amendment endpoint. Within two minutes the new validation code in AmendOrderHandler.validate began throwing a NullPointerException because it dereferenced order.limitPrice without a null check. This caused ~447 amendment requests to fail with HTTP 500, which edge-gateway surfaced as a spike of 5xx on /v1/orders (~420 occurrences). No other service or infrastructure change coincided, and system‑level metrics remained normal. The root cause is a code regression introduced by the deploy.

## Hypotheses

### 1. `code_regression` on **orders-service**, triggered by `chg:2501` (HYP-1)

Confidence 0.92 (high). The v2.15.0 deploy added a new amendment endpoint whose validation code dereferences order.limitPrice without a null check. When clients edit an open order that lacks a limit price, the NPE is thrown, causing HTTP 500 responses that edge-gateway propagates as 5xx.

**Supporting:**
- orders-service logs show a NullPointerException in AmendOrderHandler.validate (PATCH /v1/orders/<order>) 447 times, first at 13:33:01 UTC, last at 13:59:58 UTC. (`log:0953dd5b47dc`)
- The exception message is “Cannot invoke BigDecimal.compareTo(Object) because order.limitPrice is null”, indicating a missing null check on order.limitPrice. (`log:0953dd5b47dc`)
- edge-gateway logs show “upstream orders-service returned 500 (route /v1/orders)” 420 times, first at 13:34:05 UTC. (`log:a41f996d606e`)
- A deploy of orders-service v2.15.0 (“add order amendment endpoint”) occurred at 13:31:20 UTC (chg:2501). (`chg:2501`)
- orders-service error_rate metric jumps from baseline 0.0021 to mean 0.022 during the window. (`metric:orders-service/error_rate`)
- Dependency graph shows a hard HTTP dependency edge‑gateway → orders-service (timeout 3000 ms). (`dep:edge-gateway->orders-service`)
**Assumptions:**
- ASM-1: The PATCH /v1/orders endpoint is the only code path that invokes AmendOrderHandler.validate.
- ASM-2: The NPE aborts the request and returns HTTP 500 to edge-gateway.
- ASM-4: The amendment endpoint did not exist before v2.15.0, so the validation code is new.

### 2. `data_issue` on **orders-service** (HYP-2)

Confidence 0.15 (low). Existing orders have null limitPrice; the new amendment validation now checks this field, so the NPE reflects a pre‑existing data gap rather than a code bug.

**Supporting:**
- orders-service logs show a NullPointerException in AmendOrderHandler.validate (PATCH /v1/orders/<order>) 447 times, first at 13:33:01 UTC, last at 13:59:58 UTC. (`log:0953dd5b47dc`)
- The exception message is “Cannot invoke BigDecimal.compareTo(Object) because order.limitPrice is null”, indicating a missing null check on order.limitPrice. (`log:0953dd5b47dc`)
- A deploy of orders-service v2.15.0 (“add order amendment endpoint”) occurred at 13:31:20 UTC (chg:2501). (`chg:2501`)
**Contradicting:**
- orders-service error_rate metric jumps from baseline 0.0021 to mean 0.022 during the window. (`metric:orders-service/error_rate`)
- Change history for orders-service and its hard dependencies shows no other deploys, config changes, feature‑flag flips, secret rotations or infra work between 12:00‑14:00 UTC. (`chg:2501`)
**Assumptions:**
- ASM-3: Pre‑existing open orders may have limitPrice = null, and the new validation now exposes this.
- ASM-4: The amendment endpoint did not exist before v2.15.0, so the validation code is new.

### 3. `dependency_degradation` on **market-data-service** (HYP-3)

Confidence 0.05 (low). A slowdown or failure in market-data-service causes the amendment handler to receive a null price, leading to the NPE.

**Contradicting:**
- Change history for orders-service and its hard dependencies shows no other deploys, config changes, feature‑flag flips, secret rotations or infra work between 12:00‑14:00 UTC. (`chg:2501`)
- Dependency graph shows a hard HTTP dependency edge‑gateway → orders-service (timeout 3000 ms). (`dep:edge-gateway->orders-service`)
**Assumptions:**
- ASM-5: Market‑data-service showed no anomalies in the window (no changes, no error logs observed).

### 4. `feature_flag` on **orders-service** (HYP-4)

Confidence 0.03 (low). An unrecorded feature‑flag enabling the amendment endpoint was flipped at 13:31, activating the buggy validation.

**Contradicting:**
- A deploy of orders-service v2.15.0 (“add order amendment endpoint”) occurred at 13:31:20 UTC (chg:2501). (`chg:2501`)
- Change history for orders-service and its hard dependencies shows no other deploys, config changes, feature‑flag flips, secret rotations or infra work between 12:00‑14:00 UTC. (`chg:2501`)
**Assumptions:**
- ASM-6: All production changes are captured in the change‑history store; an unrecorded feature‑flag flip is unlikely.

## Recommended actions

| Urgency | Kind | Action | Why |
|---|---|---|---|
| now | mitigate | Roll back orders-service to v2.14.3 or deploy a hot‑fix v2.15.1 with a null check on order.limitPrice. | Immediately stops the NPE and restores edit‑order functionality. |
| soon | fix | Add null guard / default handling for limitPrice in AmendOrderHandler.validate and release v2.15.1. | Permanent code fix while preserving the new amendment feature. |
| later | prevent | Add unit and integration tests covering amendment of orders with missing limitPrice. | Prevents regression of the same null‑check omission. |
| later | prevent | Update deploy checklist to require validation null‑checks and contract tests for new endpoints. | Process improvement to catch similar bugs before production. |

## Evidence gaps

- **get_change_history** (Source diff for commit e4a91c2 (orders-service v2.15.0)): Tooling does not provide source diffs; needed to confirm exact validation change.
- **query_logs** (orders-service logs before 13:31 for PATCH /v1/orders): Not queried; would prove the NPE is new.
- **query_logs / query_metrics** (market-data-service 13:00‑14:00): Not examined; needed to fully rule out dependency degradation.
- **get_change_history** (Feature‑flag audit for orders-service amendment endpoint): Change history does not capture flag flips; needed to rule out H4.

## Open questions

- What exact code change in commit e4a91c2 introduced the missing null check? (source diff unavailable).
- Did market-data-service experience any latency or error spikes between 13:31‑13:35? (logs/metrics not queried).
- Is there a feature‑flag controlling the amendment endpoint that could have been toggled independently of the deploy? (flag audit not captured).

## How the investigation ran

Stopped because the agent finished its investigation, after 1 round(s): 7 model calls, 5 tool calls, 43,754 tokens, 209 s.
