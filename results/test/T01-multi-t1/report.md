# T01: Order edits failing

**Outcome:** inconclusive
- HYP-1 has unresolved blocking objections

## Summary

Order edits began failing at ~13:35 UTC with a NullPointerException in AmendOrderHandler.validate after the orders‑service v2.15.0 deploy (commit e4a91c2) at 13:31 UTC. The error rate on orders‑service jumped from ~0.2 % to >4 % while latency stayed flat, and edge‑gateway returned 5xx on /v1/orders. Two plausible explanations remain: (1) the new amendment endpoint lacks a null‑check on a price/quantity field (code regression, HYP‑1) and (2) a subset of existing open orders have NULL limitPrice/quantity, which the new validator now dereferences (data issue, HYP‑2). The investigation was stopped after two rounds because the full file‑level diff for the commit was not retrieved (GAP‑11) and the database could not be queried for NULL values, leaving both hypotheses unruled‑out. The outcome is therefore inconclusive.

## Hypotheses

### 1. `code_regression` on **orders-service**, triggered by `chg:2501` (HYP-1)

Confidence 0.50 (medium), critic: challenge, capped from 0.71: it has unresolved blocking objections. The v2.15.0 deploy added a new order‑amendment endpoint. In AmendOrderHandler.validate a null‑check on a price/quantity field (e.g., order.limitPrice) was omitted. Every PATCH /v1/orders request that touches an order with that field null throws a NullPointerException, which bubbles up as HTTP 500 to edge‑gateway, producing the observed edit‑failure spike.

**Supporting:**
- deploy on orders-service at 13:31:20 UTC by ci/deploy-bot: orders-service v2.15.0: add order amendment endpoint (version: 2.15.0, previous_version: 2.14.3, commit: e4a91c2, diff: +296 / -41) (`chg:2501`)
- orders‑service logs show a NullPointerException in AmendOrderHandler.validate (PATCH /v1/orders/<order>) starting at 2026-10-05T13:33:01.127Z, occurring 413 times through 13:57:50Z. (`log:0953dd5b47dc`)
- edge‑gateway logs show upstream orders‑service returning 500 on route /v1/orders starting at 2026-10-05T13:34:05.896Z, 379 occurrences through 13:57:54Z. (`log:a41f996d606e`)
- edge‑gateway error_rate rises from a baseline mean of 0.0020 to a period mean of 0.0045 (max 0.0118) during the window, with the last recorded value at 0.0077. (`metric:edge-gateway/error_rate`)
- orders‑service error_rate jumps from ~0.002 at 13:30‑13:32 to >0.04 beginning at 13:33, reaching a max of 0.066 at 13:45 and staying elevated through 13:54 (baseline_mean = 0.00186). (`metric:orders-service/error_rate`)
- orders‑service latency_p99_ms remains stable, ranging 209‑304 ms with a period mean of 263 ms versus a baseline_mean of 260 ms; no latency spike coincides with the error‑rate rise. (`metric:orders-service/latency_p99_ms`)
- The deploy timestamp precedes the first observed NullPointerException in AmendOrderHandler.validate (13:33:01Z) and the increase in edge‑gateway 5xx on /v1/orders (13:34:05Z). (`chg:2501`, `log:0953dd5b47dc`, `log:a41f996d606e`)
**Assumptions:**
- ASM-6: The missing null‑check resides in the new AmendOrderHandler.validate method introduced by the +296/-41 diff.
- ASM-7: The stack trace points to a line inside AmendOrderHandler.validate, not a downstream library.
**Objections:**
- [blocking] gap_unaddressed: The full file‑level diff for commit e4a91c2 (the missing null‑check in AmendOrderHandler.validate) has not been retrieved (GAP‑11). Without it we cannot confirm the code regression.
- [blocking] alternative_not_excluded: HYP‑2 (data issue) offers an equally plausible explanation for the NPE and has not been ruled out.

### 2. `data_issue` on **orders-service**, triggered by `chg:2501` (HYP-2)

Confidence 0.18 (low), critic: challenge. The new amendment endpoint validates fields that older endpoints ignored (e.g., limitPrice). A subset of existing open orders have that column set to NULL in Postgres. When the new validator runs it dereferences the null value, causing the NPE. The deploy is the trigger because the validation logic did not exist before.

**Supporting:**
- deploy on orders-service at 13:31:20 UTC by ci/deploy-bot: orders-service v2.15.0: add order amendment endpoint (version: 2.15.0, previous_version: 2.14.3, commit: e4a91c2, diff: +296 / -41) (`chg:2501`)
- orders‑service logs show a NullPointerException in AmendOrderHandler.validate (PATCH /v1/orders/<order>) starting at 2026-10-05T13:33:01.127Z, occurring 413 times through 13:57:50Z. (`log:0953dd5b47dc`)
- edge‑gateway error_rate rises from a baseline mean of 0.0020 to a period mean of 0.0045 (max 0.0118) during the window, with the last recorded value at 0.0077. (`metric:edge-gateway/error_rate`)
- orders‑service error_rate jumps from ~0.002 at 13:30‑13:32 to >0.04 beginning at 13:33, reaching a max of 0.066 at 13:45 and staying elevated through 13:54 (baseline_mean = 0.00186). (`metric:orders-service/error_rate`)
- orders‑service latency_p99_ms remains stable, ranging 209‑304 ms with a period mean of 263 ms versus a baseline_mean of 260 ms; no latency spike coincides with the error‑rate rise. (`metric:orders-service/latency_p99_ms`)
**Contradicting:**
- No other production changes (deploy, config, feature‑flag, secret‑rotation, infra) were recorded for orders‑service, edge‑gateway, market‑data‑service, quotes‑vendor, or postgres‑orders in the 12:50‑13:58 UTC window besides the above deploy. (`chg:2501`)
**Assumptions:**
- ASM-8: At least one open order in postgres‑orders has a NULL limitPrice (or quantity) column.
- ASM-9: The validator does not contain a defensive null guard for that field.
**Objections:**
- [minor] gap_unaddressed: Database contents (NULL limitPrice/quantity on open orders) cannot be queried with the available tooling; this evidence gap is a limitation rather than a blockable tool query.
- [blocking] alternative_not_excluded: HYP‑1 (code regression) also explains the observations and has not been excluded.

### 3. `config_change` on **orders-service**, triggered by `chg:2501` (HYP-3)

Confidence 0.07 (low), critic: reject. The deploy also shipped an undeclared configuration change (e.g., a feature‑flag default or thread‑pool size) that altered the request‑processing pipeline, causing the validator to be invoked with a partially‑initialized request object, leading to the NPE.

**Supporting:**
- deploy on orders-service at 13:31:20 UTC by ci/deploy-bot: orders-service v2.15.0: add order amendment endpoint (version: 2.15.0, previous_version: 2.14.3, commit: e4a91c2, diff: +296 / -41) (`chg:2501`)
- orders‑service logs show a NullPointerException in AmendOrderHandler.validate (PATCH /v1/orders/<order>) starting at 2026-10-05T13:33:01.127Z, occurring 413 times through 13:57:50Z. (`log:0953dd5b47dc`)
- orders‑service error_rate jumps from ~0.002 at 13:30‑13:32 to >0.04 beginning at 13:33, reaching a max of 0.066 at 13:45 and staying elevated through 13:54 (baseline_mean = 0.00186). (`metric:orders-service/error_rate`)
- Hard‑dependency chain confirmed: edge‑gateway → orders‑service (hard). Therefore any failure in orders‑service propagates directly to the gateway. (`dep:edge-gateway->orders-service`)
**Contradicting:**
- No other changes (deploy, config, feature‑flag, secret rotation, infra) were recorded for edge‑gateway, market‑data‑service, quotes‑vendor, or postgres‑orders in the 12:50‑13:58 UTC window. (`chg:2501`)
- No other production changes (deploy, config, feature‑flag, secret‑rotation, infra) were recorded for orders‑service, edge‑gateway, market‑data‑service, quotes‑vendor, or postgres‑orders in the 12:50‑13:58 UTC window besides the above deploy. (`chg:2501`)
- orders‑service latency_p99_ms remains stable, ranging 209‑304 ms with a period mean of 263 ms versus a baseline_mean of 260 ms; no latency spike coincides with the error‑rate rise. (`metric:orders-service/latency_p99_ms`)
**Assumptions:**
- ASM-10: The deploy artifact includes an undocumented configuration change (e.g., a feature‑flag default).
**Objections:**
- [blocking] ignores_contradiction: Change census shows no config change in the relevant window (OBS‑8, OBS‑22), directly contradicting the claim of an undeclared config change.

## Recommended actions

| Urgency | Kind | Action | Why |
|---|---|---|---|
| now | mitigate | Roll back orders‑service to version 2.14.3 (the last known good release). | Stops the NPE‑driven 5xx errors immediately while the root cause is being confirmed; addresses both HYP‑1 and HYP‑2. (HYP-1) |
| now | investigate | Retrieve the full file‑level diff for commit e4a91c2 (AmendOrderHandler.validate) to verify whether a null‑check is missing. | Directly tests the code‑regression hypothesis (HYP‑1) and closes GAP‑11. (HYP-1) |
| soon | investigate | Query the orders database for any open orders where limitPrice or quantity columns are NULL. | Determines whether pre‑existing NULL data can trigger the NPE (HYP‑2). (HYP-2) |
| soon | fix | Add a defensive null‑check (or default handling) for the price/quantity field in AmendOrderHandler.validate and redeploy. | Removes the code path that throws NPE if the regression is confirmed (HYP‑1). (HYP-1) |
| later | prevent | Add an integration test that creates an order with NULL limitPrice/quantity and exercises the PATCH /v1/orders amendment endpoint. | Ensures future changes cannot re‑introduce the missing null guard (covers HYP‑1 and HYP‑2). (HYP-1) |
| later | prevent | Enhance the change‑census pipeline to automatically surface file‑level diffs for critical services on each deploy. | Eliminates the evidence gap (GAP‑11) for future incidents. |

## Evidence gaps

- **query_metrics** (orders-service, market-data-service, postgres-orders): Metrics for these services were not fetched within the step limit; needed to confirm latency/error‑rate behavior and any circuit‑breaker trips.
- **query_logs** (market-data-service, postgres-orders): Log patterns at WARN/ERROR for these services were not retrieved; could reveal upstream failures or timeouts.
- **get_change_history** (orders-service deploy details (full commit diff)): Change census only returned summary; the diff is needed to pinpoint code that could break price/quantity edits.
- **observability platform (metrics/logs)** (Real‑time error rates, latencies, and logs for orders-service, market-data-service, postgres-orders around 13:35 UTC): Telemetry not yet collected; required to correlate deploy with symptom onset.
- **external status page / vendor SLA dashboard** (quotes-vendor health during 13:30‑13:55 UTC): External dependency not covered by internal change census; could contribute to hard‑dependency failures.
- **query_metrics** (per‑minute vendor_error_rate and vendor_latency_p99_ms for 13:30‑13:45 UTC): Summary metrics mask short spikes that could align exactly with the edit‑failure onset.
- **query_logs** (search market-data-service ERROR logs for strings timeout, deadline, 800ms in 12:50‑13:58 UTC): Absence of timeout logs not confirmed; need explicit search for timeout‑related messages.
- **trace** (trace an order‑edit request to see call chain to market-data-service/quotes‑vendor): Call graph unknown; required to link vendor errors to order‑edit failures.
- **query_metrics** (orders-service thread‑pool queue saturation): Metric not listed among available series for orders-service.
- **query_metrics** (orders-service DB‑pool usage (in‑use vs max connections)): Only db_pool_in_use and db_pool_max_connections exist as separate series; no combined usage ratio or saturation metric was exposed for the requested window.
- **get_change_history** (file-level diff for AmendOrderHandler.validate in commit e4a91c2): The change record only provides a summary diff (+296/-41) and does not include the specific source changes needed to confirm the missing null‑check.
- **observability_logs** (full stack trace details (line number, variable name) for log:0953dd5b47dc): Current log excerpt shows only the exception type and location; the exact null variable is not visible.
- **metrics** (orders-service error_rate, request_rate, latency around 13:30‑13:40 UTC): Metrics for orders-service were not queried; they are needed to correlate the deploy with the observed error spike.

## Open questions

- Does commit e4a91c2 actually omit a null‑check in AmendOrderHandler.validate?
- Are there open orders in Postgres with NULL limitPrice or quantity columns?
- What is the exact variable and line number causing the NullPointerException (full stack trace)?
- Could an undeclared configuration change have been introduced despite OBS‑22 indicating none?
- Did any downstream dependency (market‑data‑service, quotes‑vendor) contribute to the failure window?

## How the investigation ran

Stopped because reached the limit of 2 rounds, after 2 round(s): 30 model calls, 12 tool calls, 139,642 tokens, 795 s.
