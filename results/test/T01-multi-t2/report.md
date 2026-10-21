# T01: Order edits failing

**Outcome:** conclusive. Root cause: `code_regression` on **orders-service**, triggered by `chg:2501`

## Summary

Order edits began failing at 13:35 UTC after the orders-service v2.15.0 deploy (chg:2501) introduced a new PATCH /v1/orders amendment endpoint. The endpoint’s validation code dereferences `order.limitPrice` without a null guard, causing a NullPointerException that surfaces as 500 errors on the edge‑gateway (HYP‑1, confidence 0.86). The critic accepted HYP‑1 as the conclusive cause. A secondary data‑issue hypothesis (pre‑existing NULL limitPrice values) was not ruled out but lacks direct evidence (no DB query confirming NULL rows).

## Hypotheses

### 1. `code_regression` on **orders-service**, triggered by `chg:2501` (HYP-1)

Confidence 0.86 (high), critic: accept. The v2.15.0 deploy added a new PATCH /v1/orders amendment endpoint. Its validation code (AmendOrderHandler.validate) reads order.limitPrice and dereferences it without a null guard. When the endpoint is invoked on any order, a NullPointerException is thrown, producing 500 responses that propagate to edge-gateway.

**Supporting:**
- orders-service throws NullPointerException on PATCH /v1/orders because order.limitPrice is null in AmendOrderHandler.validate (first seen 13:33:01 UTC, 413 occurrences). (`log:0953dd5b47dc`)
- orders-service error_rate spikes to a mean of 0.0185 (baseline 0.0021) with a peak of 0.0663 between 13:33‑13:58 UTC. (`metric:orders-service/error_rate`)
- edge-gateway logs 379 upstream 500 responses from orders-service on route /v1/orders starting at 13:34:05 UTC. (`log:a41f996d606e`)
- orders-service latency (p50 mean 44 ms, p99 mean 260 ms) is unchanged versus baseline. (`metric:orders-service/latency_p50_ms`, `metric:orders-service/latency_p99_ms`)
- orders-service v2.15.0 (adds amendment endpoint) deployed at 13:31:20 UTC, two minutes before the first NPE. (`chg:2501`)
- The change census for the six call‑chain services returns exactly two changes in the window: chg:2497 (auth-service config) and chg:2501 (orders-service deploy). (`chg:2497`, `chg:2501`)
- orders-service deploy chg:2501 at 2026-10-05T13:31:20Z released v2.15.0 adding an order amendment endpoint (diff +296/-41). (`chg:2501`)
- The auth-service timeout change (chg:2497) only affects session idle expiration and cannot directly cause order‑edit failures. (`chg:2497`)
**Assumptions:**
- ASM-1: The amendment endpoint validates order.limitPrice and assumes it is non‑null.
- ASM-2: The v2.15.0 deploy introduced the validation code path with no feature‑flag gating observed.

### 2. `data_issue` on **orders-service**, triggered by `chg:2501` (HYP-2)

Confidence 0.32 (low), critic: challenge. Existing open market orders have limitPrice = NULL. The previous edit flow never inspected limitPrice, so they succeeded. The new amendment endpoint (introduced by the same deploy) validates limitPrice and crashes when it encounters the pre‑existing NULL values.

**Supporting:**
- orders-service throws NullPointerException on PATCH /v1/orders because order.limitPrice is null in AmendOrderHandler.validate (first seen 13:33:01 UTC, 413 occurrences). (`log:0953dd5b47dc`)
- orders-service error_rate spikes to a mean of 0.0185 (baseline 0.0021) with a peak of 0.0663 between 13:33‑13:58 UTC. (`metric:orders-service/error_rate`)
- edge-gateway logs 379 upstream 500 responses from orders-service on route /v1/orders starting at 13:34:05 UTC. (`log:a41f996d606e`)
**Contradicting:**
- postgres-orders reports only checkpoint‑frequency warnings; CPU, query latency p99, and active connections stay within baseline. (`metric:postgres-orders/cpu_util`, `metric:postgres-orders/query_latency_p99_ms`, `metric:postgres-orders/active_connections`)
- The auth-service timeout change (chg:2497) only affects session idle expiration and cannot directly cause order‑edit failures. (`chg:2497`)
**Assumptions:**
- ASM-3: Some open orders in the system legitimately have limitPrice = NULL (e.g., market orders).
- ASM-4: The prior edit flow did not read limitPrice, so the NULL values were harmless until the new endpoint was added.
**Objections:**
- [minor] alternative_not_excluded: HYP‑1 (code regression) fully accounts for the observed NPEs and error‑rate spike. Until HYP‑2 is either confirmed (by showing NULL limitPrice rows) or falsified, it remains an alternative that has not been excluded.
- [blocking] gap_unaddressed: No evidence has been gathered that any open order records have limitPrice = NULL. The tools can reveal this by querying orders‑service logs for the validation path or by inspecting the orders table, but neither has been done.

## Recommended actions

| Urgency | Kind | Action | Why |
|---|---|---|---|
| now | mitigate | Disable the new amendment endpoint (e.g., via feature flag) or roll back orders-service to v2.14.3 to stop the 5xx error burst immediately. | The NPE occurs on every edit request; turning off the faulty code path restores order‑edit functionality while a permanent fix is prepared. (HYP-1) |
| soon | fix | Add a null check for `order.limitPrice` in `AmendOrderHandler.validate` (or make the field non‑nullable with a default) and deploy the corrected version. | Directly eliminates the NPE identified in the logs (OBS‑7) and matches the prediction that error_rate will return to baseline. (HYP-1) |
| later | prevent | Introduce unit/integration tests that exercise the amendment endpoint with market orders lacking a limitPrice, and add a pre‑deploy static‑analysis rule to flag missing null guards on newly added fields. | Prevents regression of the same null‑dereference pattern in future endpoint additions. (HYP-1) |
| soon | investigate | Query the orders table (or orders‑service logs) for any open orders where `limitPrice` IS NULL to confirm or falsify HYP‑2. | The critic flagged the lack of evidence for existing NULL limitPrice rows; confirming this would clarify whether a data back‑fill is also required. (HYP-2) |
| later | investigate | Obtain the full source diff for commit e4a91c2 (orders‑service v2.15.0) and verify the exact validation logic and any feature‑flag gating. | Gap‑4 and Gap‑7 indicate the diff is not in the tooling; seeing the code confirms the null‑check omission and flag state. (HYP-1) |

## Evidence gaps

- **query_logs** (quotes-vendor service logs (WARN+)): No logs were fetched for quotes‑vendor; unable to see vendor‑side errors or timeouts.
- **query_metrics** (quotes‑vendor metrics (error_rate, latency_p99, rps)): Metrics for quotes‑vendor were not queried; missing vendor‑side health signals.
- **query_metrics** (Per‑request latency for PATCH /v1/orders endpoint): Metric granularity does not expose per‑endpoint latency; cannot confirm latency impact of the new endpoint.
- **query_logs** (Exact diff of commit e4a91c2 (orders-service v2.15.0)): Log tooling does not provide source‑code diffs; needed to pinpoint the null‑check omission.
- **query_changes** (Feature‑flag or config changes accompanying the deploy): Change census only records the deploy; any accompanying flag toggles are not captured.
- **get_change_history** (edge-gateway, market-data-service, postgres-orders, redis-cache): No change entries returned; untracked infra or config changes could exist but are invisible to the census.
- **get_change_history** (orders-service commit e4a91c2 diff): Full code diff for v2.15.0 not available; needed to pinpoint exact amendment‑endpoint changes.
- **get_change_history** (feature-flag state for amendment endpoint): Flag activation time unknown; could differ from deploy timestamp.
- **get_change_history** (orders-service runtime config (e.g., gRPC timeouts to market-data-service)): Config tweaks not captured as explicit config changes in the census.

## Open questions

- Do any currently open orders have `limitPrice = NULL` (i.e., is HYP‑2 true)?
- What is the exact code change in commit e4a91c2 that introduced the missing null guard?
- Was the amendment endpoint gated behind a feature flag, and if so, when was the flag enabled relative to the deploy?
- Are there any untracked config or infra changes for the involved services during the incident window (Gap‑6)?

## How the investigation ran

Stopped because the critic accepted HYP-1, after 1 round(s): 19 model calls, 14 tool calls, 86,425 tokens, 693 s.
