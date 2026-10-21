# T01: Order edits failing

**Outcome:** inconclusive
- HYP-1 has unresolved blocking objections

## Summary

Order‑edit failures began at ~13:33 UTC after the orders‑service v2.15.0 deploy (chg:2501) added a PATCH /v1/orders amendment endpoint. The service logs show a NullPointerException in AmendOrderHandler.validate caused by a missing null guard on order.limitPrice, producing a sharp error‑rate spike (orders‑service error_rate ~0.06) that propagates as upstream 5xx from edge‑gateway. The most likely cause is a code regression in the new endpoint, but the full source diff of commit e4a91c2 has not been retrieved and the feature‑flag that enables the endpoint (order.amendment.enabled) has not been verified as flipped on at deploy. Because these two blocking gaps remain, the investigation was stopped on time‑budget and the outcome is inconclusive.

## Hypotheses

### 1. `code_regression` on **orders-service**, triggered by `chg:2501` (HYP-1)

Confidence 0.50 (medium), critic: challenge, capped from 0.78: it has unresolved blocking objections. The v2.15.0 deploy added a PATCH /v1/orders amendment endpoint. AmendOrderHandler.validate reads order.limitPrice without a null guard; when limitPrice is missing a NullPointerException is thrown, producing 500 errors that propagate to edge-gateway as upstream 5xx.

**Supporting:**
- deploy on orders-service at 13:31:20 UTC by ci/deploy-bot: orders-service v2.15.0: add order amendment endpoint (version: 2.15.0, previous_version: 2.14.3, commit: e4a91c2, diff: +296 / -41) (`chg:2501`)
- orders‑service v2.15.0 was deployed at 13:31:20 UTC (chg:2501) adding an order amendment endpoint (+296/-41 lines). (`chg:2501`)
- orders‑service logged a NullPointerException because order.limitPrice is null in AmendOrderHandler.validate for PATCH /v1/orders, first seen at 13:33:01 UTC (413 occurrences through 13:57:50). (`log:0953dd5b47dc`)
- First NullPointerException in AmendOrderHandler.validate (order.limitPrice is null) logged at 2026‑10‑05T13:33:01Z (413 occurrences through 13:57:50). (`log:0953dd5b47dc`)
- orders‑service error_rate rose sharply (max 0.06632 vs baseline 0.002091). The first NullPointerException in AmendOrderHandler.validate was logged at 13:33:01 UTC, showing the error‑rate spike at/around 13:33. (`metric:orders-service/error_rate`, `log:0953dd5b47dc`)
- orders‑service error_rate was at baseline (~0.002) until 13:33 UTC, then spiked to 0.0615 at 13:33 and remained elevated (0.042‑0.052) through 13:39 UTC. (`metric:orders-service/error_rate`)
- edge‑gateway began returning upstream 500 errors from orders‑service on the /v1/orders route at 13:34:05 UTC (379 occurrences through 13:57:54). (`log:a41f996d606e`)
- edge‑gateway overall error_rate exceeded its baseline (max 0.01176 vs baseline 0.002013) but the first upstream 5xx from orders‑service was logged at 13:34:05 UTC, indicating the spike occurred after 13:33. (`metric:edge-gateway/error_rate`, `log:a41f996d606e`)
- edge‑gateway error_rate remained at baseline (~0.002) through 13:33 UTC and rose sharply starting at 13:34 UTC, reaching 0.0118 at 13:35 UTC and staying above baseline through 13:39 UTC. (`metric:edge-gateway/error_rate`)
- Edge‑gateway began returning upstream 5xx from orders‑service on /v1/orders at 2026‑10‑05T13:34:05Z (379 occurrences through 13:57:54). (`log:a41f996d606e`)
**Contradicting:**
- market‑data‑service reported quotes‑vendor 429 rate‑limit responses throughout the window (first at 12:53:15, last at 13:55:58) and three 503 responses on GET /v1/quotes/{symbol} starting at 13:12:53. (`log:ba5421c7350c`, `log:3b7d1bd7af1a`)
- market-data-service logged 6 occurrences of “quotes-vendor responded 429; backing off <ms>ms” between 12:53:15 UTC and 13:55:58 UTC. (`log:ba5421c7350c`)
- market-data-service logged 3 occurrences of “GET /v1/quotes/{symbol} 503 40ms” between 13:12:53 UTC and 13:47:02 UTC, indicating failed price look‑ups. (`log:3b7d1bd7af1a`)
- Vendor error‑rate metric for market-data-service hovered around its baseline (mean 0.00097, baseline 0.00098) with brief peaks up to 0.0013 at 13:02 and 13:17 UTC, but no sustained spike. (`metric:market-data-service/vendor_error_rate`)
- Overall request latency (p99) and CPU/memory utilization for market-data-service remained within normal ranges throughout the window. (`metric:market-data-service/latency_p99_ms`, `metric:market-data-service/cpu_util`, `metric:market-data-service/mem_util`)
- market‑data‑service error_rate and vendor_error_rate stayed at baseline levels (error_rate max 0.0034 vs baseline 0.00197; vendor_error_rate mean 0.00097 vs baseline 0.00098) with no spike before 13:33. (`metric:market-data-service/error_rate`, `metric:market-data-service/vendor_error_rate`)
- market‑data‑service p99 latency remained at baseline (mean 258.4 ms, baseline 259.5 ms; max 325.3 ms). (`metric:market-data-service/latency_p99_ms`)
**Assumptions:**
- ASM-7: The diff of commit e4a91c2 contains an unguarded read of order.limitPrice in AmendOrderHandler.validate.
- ASM-8: The NPE stack trace (log 0953dd5b47dc) points to the exact line in AmendOrderHandler.validate that accesses order.limitPrice without a null guard.
**Objections:**
- [blocking] gap_unaddressed: Full source diff of commit e4a91c2 (orders‑service v2.15.0) not retrieved; needed to verify missing null guard on order.limitPrice in AmendOrderHandler.validate.
- [blocking] alternative_not_excluded: HYP‑4 (feature‑flag activation) offers an alternative explanation for the same deploy‑time spike and has not been ruled out.

### 2. `feature_flag` on **orders-service**, triggered by `chg:2501` (HYP-4)

Confidence 0.32 (low), critic: challenge. The v2.15.0 release includes a feature flag (order.amendment.enabled) that is flipped on at deploy time, instantly exposing the new amendment code path to 100% of traffic. The immediate, full‑traffic error‑rate jump matches an all‑at‑once flag activation.

**Supporting:**
- deploy on orders-service at 13:31:20 UTC by ci/deploy-bot: orders-service v2.15.0: add order amendment endpoint (version: 2.15.0, previous_version: 2.14.3, commit: e4a91c2, diff: +296 / -41) (`chg:2501`)
- orders‑service v2.15.0 was deployed at 13:31:20 UTC (chg:2501) adding an order amendment endpoint (+296/-41 lines). (`chg:2501`)
- orders‑service logged a NullPointerException because order.limitPrice is null in AmendOrderHandler.validate for PATCH /v1/orders, first seen at 13:33:01 UTC (413 occurrences through 13:57:50). (`log:0953dd5b47dc`)
- First NullPointerException in AmendOrderHandler.validate (order.limitPrice is null) logged at 2026‑10‑05T13:33:01Z (413 occurrences through 13:57:50). (`log:0953dd5b47dc`)
- orders‑service error_rate rose sharply (max 0.06632 vs baseline 0.002091). The first NullPointerException in AmendOrderHandler.validate was logged at 13:33:01 UTC, showing the error‑rate spike at/around 13:33. (`metric:orders-service/error_rate`, `log:0953dd5b47dc`)
- orders‑service error_rate was at baseline (~0.002) until 13:33 UTC, then spiked to 0.0615 at 13:33 and remained elevated (0.042‑0.052) through 13:39 UTC. (`metric:orders-service/error_rate`)
**Contradicting:**
- market‑data‑service reported quotes‑vendor 429 rate‑limit responses throughout the window (first at 12:53:15, last at 13:55:58) and three 503 responses on GET /v1/quotes/{symbol} starting at 13:12:53. (`log:ba5421c7350c`, `log:3b7d1bd7af1a`)
- market-data-service logged 6 occurrences of “quotes-vendor responded 429; backing off <ms>ms” between 12:53:15 UTC and 13:55:58 UTC. (`log:ba5421c7350c`)
- market-data-service logged 3 occurrences of “GET /v1/quotes/{symbol} 503 40ms” between 13:12:53 UTC and 13:47:02 UTC, indicating failed price look‑ups. (`log:3b7d1bd7af1a`)
- Vendor error‑rate metric for market-data-service hovered around its baseline (mean 0.00097, baseline 0.00098) with brief peaks up to 0.0013 at 13:02 and 13:17 UTC, but no sustained spike. (`metric:market-data-service/vendor_error_rate`)
- Overall request latency (p99) and CPU/memory utilization for market-data-service remained within normal ranges throughout the window. (`metric:market-data-service/latency_p99_ms`, `metric:market-data-service/cpu_util`, `metric:market-data-service/mem_util`)
- market‑data‑service error_rate and vendor_error_rate stayed at baseline levels (error_rate max 0.0034 vs baseline 0.00197; vendor_error_rate mean 0.00097 vs baseline 0.00098) with no spike before 13:33. (`metric:market-data-service/error_rate`, `metric:market-data-service/vendor_error_rate`)
- market‑data‑service p99 latency remained at baseline (mean 258.4 ms, baseline 259.5 ms; max 325.3 ms). (`metric:market-data-service/latency_p99_ms`)
**Assumptions:**
- ASM-9: The release process for v2.15.0 includes a feature flag (order.amendment.enabled) that is turned on at deploy time.
**Objections:**
- [blocking] gap_unaddressed: Feature‑flag audit log for order.amendment.enabled not captured; cannot confirm flag was flipped on at deploy time.
- [blocking] alternative_not_excluded: HYP‑1 (code regression) also explains the spike and has stronger direct evidence (NPE stack trace).

### 3. `dependency_degradation` on **market-data-service** (HYP-2)

Confidence 0.28 (low), critic: reject. Bursts of quotes‑vendor 429/503 responses (starting 12:53 UTC) cause price look‑ups to fail, leaving limitPrice null for orders that later get amended. The failure propagates as NPE in orders‑service.

**Supporting:**
- market‑data‑service reported quotes‑vendor 429 rate‑limit responses throughout the window (first at 12:53:15, last at 13:55:58) and three 503 responses on GET /v1/quotes/{symbol} starting at 13:12:53. (`log:ba5421c7350c`, `log:3b7d1bd7af1a`)
- market-data-service logged 6 occurrences of “quotes-vendor responded 429; backing off <ms>ms” between 12:53:15 UTC and 13:55:58 UTC. (`log:ba5421c7350c`)
- market-data-service logged 3 occurrences of “GET /v1/quotes/{symbol} 503 40ms” between 13:12:53 UTC and 13:47:02 UTC, indicating failed price look‑ups. (`log:3b7d1bd7af1a`)
- The hard‑dependency chain for order‑edit is edge‑gateway → orders‑service (dep:edge-gateway->orders-service) → market‑data‑service (dep:orders-service->market-data-service) → quotes‑vendor (dep:market-data-service->quotes-vendor) plus edge‑gateway → auth‑service (dep:edge-gateway->auth-service) and orders‑service → postgres‑orders (dep:orders-service->postgres-orders). (`dep:edge-gateway->orders-service`, `dep:orders-service->market-data-service`, `dep:market-data-service->quotes-vendor`, `dep:edge-gateway->auth-service`, `dep:orders-service->postgres-orders`)
**Contradicting:**
- Vendor error‑rate metric for market-data-service hovered around its baseline (mean 0.00097, baseline 0.00098) with brief peaks up to 0.0013 at 13:02 and 13:17 UTC, but no sustained spike. (`metric:market-data-service/vendor_error_rate`)
- Overall request latency (p99) and CPU/memory utilization for market-data-service remained within normal ranges throughout the window. (`metric:market-data-service/latency_p99_ms`, `metric:market-data-service/cpu_util`, `metric:market-data-service/mem_util`)
- market‑data‑service error_rate and vendor_error_rate stayed at baseline levels (error_rate max 0.0034 vs baseline 0.00197; vendor_error_rate mean 0.00097 vs baseline 0.00098) with no spike before 13:33. (`metric:market-data-service/error_rate`, `metric:market-data-service/vendor_error_rate`)
- market‑data‑service p99 latency remained at baseline (mean 258.4 ms, baseline 259.5 ms; max 325.3 ms). (`metric:market-data-service/latency_p99_ms`)
- orders‑service error_rate rose sharply (max 0.06632 vs baseline 0.002091). The first NullPointerException in AmendOrderHandler.validate was logged at 13:33:01 UTC, showing the error‑rate spike at/around 13:33. (`metric:orders-service/error_rate`, `log:0953dd5b47dc`)
- edge‑gateway began returning upstream 500 errors from orders‑service on the /v1/orders route at 13:34:05 UTC (379 occurrences through 13:57:54). (`log:a41f996d606e`)
- edge‑gateway overall error_rate exceeded its baseline (max 0.01176 vs baseline 0.002013) but the first upstream 5xx from orders‑service was logged at 13:34:05 UTC, indicating the spike occurred after 13:33. (`metric:edge-gateway/error_rate`, `log:a41f996d606e`)
**Assumptions:**
- ASM-3: Vendor 429/503 bursts are sufficient to empty the price cache for the symbols being edited.
- ASM-4: Orders‑service has no fallback/default price when market‑data lookup fails.
**Objections:**
- [blocking] ignores_contradiction: Market‑data‑service error_rate, vendor_error_rate and latency remain at baseline (OBS‑9, OBS‑10, OBS‑19, OBS‑20), contradicting a degradation that would cause limitPrice to be null.
- [blocking] temporal_violation: Quotes‑vendor 429/503 bursts begin at 12:53 UTC, but the orders‑service NPE appears at 13:33 UTC with no concurrent market‑data error spike.

### 4. `dependency_degradation` on **orders-service** (HYP-5)

Confidence 0.12 (low), critic: reject. A transient Redis price‑cache miss/eviction caused limitPrice to be null for orders being amended. The NPE is a symptom of missing price data rather than a code bug; the spike coincides with the new endpoint being exercised.

**Supporting:**
- market‑data‑service reported quotes‑vendor 429 rate‑limit responses throughout the window (first at 12:53:15, last at 13:55:58) and three 503 responses on GET /v1/quotes/{symbol} starting at 13:12:53. (`log:ba5421c7350c`, `log:3b7d1bd7af1a`)
- market-data-service logged 6 occurrences of “quotes-vendor responded 429; backing off <ms>ms” between 12:53:15 UTC and 13:55:58 UTC. (`log:ba5421c7350c`)
- market-data-service logged 3 occurrences of “GET /v1/quotes/{symbol} 503 40ms” between 13:12:53 UTC and 13:47:02 UTC, indicating failed price look‑ups. (`log:3b7d1bd7af1a`)
- The hard‑dependency chain for order‑edit is edge‑gateway → orders‑service (dep:edge-gateway->orders-service) → market‑data‑service (dep:orders-service->market-data-service) → quotes‑vendor (dep:market-data-service->quotes-vendor) plus edge‑gateway → auth‑service (dep:edge-gateway->auth-service) and orders‑service → postgres‑orders (dep:orders-service->postgres-orders). (`dep:edge-gateway->orders-service`, `dep:orders-service->market-data-service`, `dep:market-data-service->quotes-vendor`, `dep:edge-gateway->auth-service`, `dep:orders-service->postgres-orders`)
**Contradicting:**
- Vendor error‑rate metric for market-data-service hovered around its baseline (mean 0.00097, baseline 0.00098) with brief peaks up to 0.0013 at 13:02 and 13:17 UTC, but no sustained spike. (`metric:market-data-service/vendor_error_rate`)
- Overall request latency (p99) and CPU/memory utilization for market-data-service remained within normal ranges throughout the window. (`metric:market-data-service/latency_p99_ms`, `metric:market-data-service/cpu_util`, `metric:market-data-service/mem_util`)
- market‑data‑service error_rate and vendor_error_rate stayed at baseline levels (error_rate max 0.0034 vs baseline 0.00197; vendor_error_rate mean 0.00097 vs baseline 0.00098) with no spike before 13:33. (`metric:market-data-service/error_rate`, `metric:market-data-service/vendor_error_rate`)
- market‑data‑service p99 latency remained at baseline (mean 258.4 ms, baseline 259.5 ms; max 325.3 ms). (`metric:market-data-service/latency_p99_ms`)
- orders‑service error_rate rose sharply (max 0.06632 vs baseline 0.002091). The first NullPointerException in AmendOrderHandler.validate was logged at 13:33:01 UTC, showing the error‑rate spike at/around 13:33. (`metric:orders-service/error_rate`, `log:0953dd5b47dc`)
- orders‑service error_rate was at baseline (~0.002) until 13:33 UTC, then spiked to 0.0615 at 13:33 and remained elevated (0.042‑0.052) through 13:39 UTC. (`metric:orders-service/error_rate`)
- edge‑gateway began returning upstream 500 errors from orders‑service on the /v1/orders route at 13:34:05 UTC (379 occurrences through 13:57:54). (`log:a41f996d606e`)
- edge‑gateway overall error_rate exceeded its baseline (max 0.01176 vs baseline 0.002013) but the first upstream 5xx from orders‑service was logged at 13:34:05 UTC, indicating the spike occurred after 13:33. (`metric:edge-gateway/error_rate`, `log:a41f996d606e`)
- edge‑gateway error_rate remained at baseline (~0.002) through 13:33 UTC and rose sharply starting at 13:34 UTC, reaching 0.0118 at 13:35 UTC and staying above baseline through 13:39 UTC. (`metric:edge-gateway/error_rate`)
- Edge‑gateway began returning upstream 5xx from orders‑service on /v1/orders at 2026‑10‑05T13:34:05Z (379 occurrences through 13:57:54). (`log:a41f996d606e`)
**Assumptions:**
- ASM-10: Order limitPrice is populated only via a cached quote; a cache miss returns null rather than a price.
- ASM-11: The cache‑miss rate spiked at 13:33 coincidentally with the deploy.
**Objections:**
- [blocking] ignores_contradiction: Market‑data‑service metrics show no error/latency spike at 13:33 UTC (OBS‑19, OBS‑20); no Redis metrics available to support cache‑miss claim.

### 5. `config_change` on **auth-service**, triggered by `chg:2497` (HYP-3)

Confidence 0.07 (low), critic: reject. Increasing session.idle_timeout from 15 m to 30 m changes token renewal timing for long‑lived edit sessions, causing authentication failures that manifest as 500s downstream.

**Supporting:**
- config on auth-service at 12:55:02 UTC by priya.nair: Raise session idle timeout for web clients (session.idle_timeout: 15m -> 30m) (`chg:2497`)
- auth‑service config changed at 12:55:02 UTC (chg:2497) raising session.idle_timeout from 15 m to 30 m. (`chg:2497`)
- The hard‑dependency chain for order‑edit is edge‑gateway → orders‑service (dep:edge-gateway->orders-service) → market‑data‑service (dep:orders-service->market-data-service) → quotes‑vendor (dep:market-data-service->quotes-vendor) plus edge‑gateway → auth‑service (dep:edge-gateway->auth-service) and orders‑service → postgres‑orders (dep:orders-service->postgres-orders). (`dep:edge-gateway->orders-service`, `dep:orders-service->market-data-service`, `dep:market-data-service->quotes-vendor`, `dep:edge-gateway->auth-service`, `dep:orders-service->postgres-orders`)
**Contradicting:**
- edge‑gateway overall error_rate exceeded its baseline (max 0.01176 vs baseline 0.002013) but the first upstream 5xx from orders‑service was logged at 13:34:05 UTC, indicating the spike occurred after 13:33. (`metric:edge-gateway/error_rate`, `log:a41f996d606e`)
- edge‑gateway p99 latency stayed at baseline (mean 339.4 ms, baseline 339.4 ms; max 418.3 ms) with no evidence of a pre‑13:33 spike. (`metric:edge-gateway/latency_p99_ms`)
- edge‑gateway began returning upstream 500 errors from orders‑service on the /v1/orders route at 13:34:05 UTC (379 occurrences through 13:57:54). (`log:a41f996d606e`)
- orders‑service logged a NullPointerException because order.limitPrice is null in AmendOrderHandler.validate for PATCH /v1/orders, first seen at 13:33:01 UTC (413 occurrences through 13:57:50). (`log:0953dd5b47dc`)
- orders‑service also emitted generic 500 error lines for POST /v1/orders starting at 13:33:15 UTC (30 occurrences). (`log:45e18c1c5f9a`)
**Assumptions:**
- ASM-5: The idle‑timeout change could affect token renewal only for long‑lived edit sessions.
- ASM-6: Auth failures would surface as 401/403 rather than 500.
**Objections:**
- [blocking] ignores_contradiction: No auth‑service error rise or edge‑gateway auth upstream errors observed before 13:33 UTC (OBS‑15, OBS‑16, OBS‑3, OBS‑4).

## Recommended actions

| Urgency | Kind | Action | Why |
|---|---|---|---|
| now | mitigate | Disable the order amendment feature flag (order.amendment.enabled) to stop the NPE‑driven 5xx spike immediately. | Both HYP‑1 (code regression) and HYP‑4 (feature‑flag activation) predict that turning the flag off will eliminate the error surge; this stops customer impact while the root cause is confirmed. (HYP-1) |
| soon | fix | Add a null check for order.limitPrice in AmendOrderHandler.validate (or guard the price lookup) and deploy a hot‑fix. | HYP‑1 identifies the missing guard as the direct mechanism of the NPE; once the diff confirms the defect, the fix removes the root cause. (HYP-1) |
| later | prevent | Introduce a mandatory code‑review rule and automated test that any new endpoint accessing order.limitPrice must handle null values. | Prevents recurrence of the same regression in future releases (addresses HYP‑1). (HYP-1) |
| now | investigate | Retrieve the full source diff of commit e4a91c2 (orders‑service v2.15.0) to verify the presence/absence of a null guard on order.limitPrice. | GAP‑7 / GAP‑14 block confirmation of HYP‑1; the diff is the decisive evidence. (HYP-1) |
| now | investigate | Obtain the feature‑flag audit log for order.amendment.enabled to confirm whether it was switched on at 13:31:20 UTC. | GAP‑8 blocks exclusion of HYP‑4; the flag state determines if the new code path was exposed to 100 % traffic. (HYP-4) |
| soon | investigate | Correlate request‑path data with the NPE logs to prove the exception occurs only on the newly added PATCH /v1/orders endpoint. | GAP‑15 leaves open whether other paths could trigger the same NPE. (HYP-1) |

## Evidence gaps

- **query_metrics** (latency, error‑rate, timeout, saturation for edge‑gateway, orders‑service, market‑data‑service, quotes‑vendor, redis‑cache): Metrics not fetched; required to confirm quantitative spikes and cache behavior.
- **query_logs** (quotes‑vendor and redis‑cache logs at WARN/ERROR): No log data returned for those services; need to verify vendor errors or cache misses.
- **query_logs** (quotes-vendor service logs (WARN+) for 12:50‑13:58 UTC): Tool step budget exhausted; need vendor‑side error/rate‑limit logs to confirm 429 source.
- **query_logs** (redis-cache service logs (WARN+) for 12:50‑13:58 UTC): Tool step budget exhausted; cache miss/eviction could amplify vendor calls.
- **query_metrics** (market-data-service gRPC latency, error‑code breakdown, circuit‑breaker state metrics): Not available in default metric set; need dedicated series to pinpoint price‑lookup failures.
- **query_metrics** (quotes-vendor HTTP health / rate‑limit quota metrics): Not queried; required to verify vendor‑side limit change.
- **get_change_history** (Full diff of commit e4a91c2 (chg:2501) to see exact code added for order amendment): Change‑census only shows summary (+296/-41); detailed diff not retrieved
- **get_change_history** (Feature‑flag state controlling the new amendment endpoint): Feature‑flag flips are not captured in the change‑census output
- **get_change_history** (Infrastructure incidents affecting quotes‑vendor HTTPS endpoint (dep:market-data-service->quotes-vendor) during 13:30‑13:40 UTC): No infra change recorded, but external vendor outage could cause failures
- **get_change_history** (Postgres‑orders health metrics (connection pool, replication lag) around 13:35 UTC): No config/secret change recorded; DB‑side issue could still manifest
- **query_metrics** (Per‑endpoint (edit‑order) latency, error‑rate, and timeout series for edge‑gateway → orders‑service → market‑data‑service → quotes‑vendor): Only aggregate service‑level metrics are available; minute‑resolution series for the specific call chain were not returned.
- **query_metrics** (Timeout metrics (e.g., request_timeout_count, upstream_timeout) for any service in the chain): No timeout metrics are exposed in the metric catalog for the listed services.
- **query_metrics** (edge-gateway error_rate per minute 13:30‑13:40): Metric series not yet retrieved; required to complete the requested comparison.
- **get_change_history** (Full source diff of commit e4a91c2 (orders‑service v2.15.0)): The change‑history endpoint only returns a line‑count summary (+296/‑41) and does not expose the actual code changes needed to verify the presence or absence of a null check on order.limitPrice.
- **get_change_history** (Confirmation that the NPE path is exercised only by the newly added amendment endpoint): Current logs show NPE timestamps but do not include request‑path correlation; without request‑path data we cannot definitively prove the new endpoint is the sole trigger.

## Open questions

- Was the feature flag order.amendment.enabled turned on at deploy time (13:31:20 UTC)?
- Does the full diff of commit e4a91c2 show a direct access to order.limitPrice without a null check in AmendOrderHandler.validate?
- Are there any other code paths (e.g., POST /v1/orders) that can reach the same validation and cause the NPE?
- Did market‑data‑service or Redis cache experience any degradation at 13:33 UTC that could leave limitPrice null?
- What is the exact per‑endpoint error‑rate profile for PATCH /v1/orders versus other order endpoints during the incident?

## How the investigation ran

Stopped because time budget reached, after 2 round(s): 34 model calls, 16 tool calls, 166,470 tokens, 971 s.
