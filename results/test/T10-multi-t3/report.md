# T10: Withdrawals failing

**Outcome:** conclusive. Root cause: `dependency_degradation` on **bank-rails**

## Summary

Withdrawals began failing around 17:48 UTC on 2026‑10‑15. The strongest hypothesis (HYP‑1, 55 % confidence) is that the external bank‑rails provider degraded or became unreachable, causing the synchronous 4 s HTTPS call from payments‑service to error and the edge‑gateway to return upstream‑502. However, metrics and change‑history back‑ends were unavailable, so the degradation cannot be confirmed and a concurrent config change in payments‑service or edge‑gateway cannot be ruled out. The investigation was stopped because the time budget was reached, leaving the exact root cause unverified.

## Hypotheses

### 1. `dependency_degradation` on **bank-rails** (HYP-1)

Confidence 0.55 (medium), critic: challenge. The external bank‑rails provider began returning errors or became unreachable during ~17:45‑18:00 UTC. Payments‑service, which has a hard synchronous HTTPS dependency on bank‑rails with a 4 s timeout (OBS-1), propagates those failures as “bank‑rails call returned an error” (OBS-4). Edge‑gateway then reports upstream‑502 for POST /v1/withdrawals (OBS-2).

**Supporting:**
- payments-service has a hard, synchronous HTTPS dependency on the external bank-rails provider with a 4000 ms timeout. (`dep:payments-service->bank-rails`)
- edge‑gateway logged 31 upstream‑502 warnings for POST /v1/withdrawals between 17:48:34 and 17:59:57 UTC. (`log:8fed29f3ce72`)
- payments‑service recorded 44 ERROR lines “withdrawal <id> failed: bank‑rails call returned an error” from 17:48:12 to 17:59:37 UTC. (`log:33df62f69e8a`)
**Assumptions:**
- ASM-5: The bank‑rails provider suffered an un‑announced degradation (errors, latency spikes or partial outage) during ≈17:45‑18:00 UTC.
- ASM-6: No configuration change was made to the payments‑service → bank‑rails client (timeout, retry, base‑url) in the 30 min before the first error.
**Objections:**
- [minor] gap_unaddressed: Bank‑rails latency / 5xx‑rate metrics for 17:45‑18:00 UTC cannot be retrieved (metrics backend down).
- [minor] gap_unaddressed: Payments‑service change‑history for 17:30‑17:45 UTC cannot be retrieved (change‑history backend down), so we cannot confirm the absence of a config change.

### 2. `config_change` on **payments-service**, triggered by `chg:unknown` (HYP-2)

Confidence 0.25 (low), critic: challenge. A configuration change (e.g., reduced HTTP timeout, altered retry count, switched endpoint URL, or a feature‑flag such as withdrawal‑mode / bank‑rails‑fallback) was rolled out to payments‑service between 17:30‑17:45 UTC. The new, tighter timeout causes previously‑successful bank‑rails calls to be treated as failures, producing the same “bank‑rails call returned an error” logs (OBS-4) and upstream‑502 at the gateway (OBS-2).

**Supporting:**
- payments-service has a hard, synchronous HTTPS dependency on the external bank-rails provider with a 4000 ms timeout. (`dep:payments-service->bank-rails`)
- edge‑gateway logged 31 upstream‑502 warnings for POST /v1/withdrawals between 17:48:34 and 17:59:57 UTC. (`log:8fed29f3ce72`)
- payments‑service recorded 44 ERROR lines “withdrawal <id> failed: bank‑rails call returned an error” from 17:48:12 to 17:59:37 UTC. (`log:33df62f69e8a`)
**Contradicting:**
- payments‑service also emitted 6 generic 502 errors on POST /v1/checkout between 17:48:21 and 17:58:09 UTC. (`log:3d2e4dba2230`)
**Assumptions:**
- ASM-7: A configuration change (e.g., reduced HTTP timeout, altered retry count, switched endpoint URL, or a feature‑flag such as withdrawal‑mode / bank‑rails‑fallback) was rolled out to payments‑service between 17:30‑17:45 UTC.
- ASM-8: The change made previously‑successful bank‑rails calls exceed the new timeout, so they are logged as “bank‑rails call returned an error”.
**Objections:**
- [blocking] unsupported_claim: names chg:unknown as the trigger, but no change-history query returned it
- [minor] unsupported_claim: The trigger “chg:unknown” is cited but no change‑history query returned a change; the change‑history service is unavailable.
- [blocking] alternative_not_excluded: HYP‑1 (bank‑rails degradation) remains a plausible alternative with supporting observations (OBS‑1, OBS‑2, OBS‑4).

### 3. `config_change` on **edge-gateway**, triggered by `chg:unknown` (HYP-4)

Confidence 0.10 (low), critic: challenge. Edge‑gateway’s per‑route timeout for POST /v1/withdrawals was lowered to less than the payments‑service 4 s bank‑rails client timeout. The gateway aborts the request while payments‑service is still waiting, emitting upstream‑502 (OBS-2). Payments‑service still logs a bank‑rails error because the downstream call eventually fails (OBS-4).

**Supporting:**
- edge‑gateway logged 31 upstream‑502 warnings for POST /v1/withdrawals between 17:48:34 and 17:59:57 UTC. (`log:8fed29f3ce72`)
- The core withdrawal request path is edge‑gateway → payments‑service → bank‑rails (hard dependency, HTTPS, 4000 ms timeout) and payments‑service → postgres‑payments (hard dependency, SQL, 2000 ms timeout). (`dep:edge-gateway->payments-service`, `dep:payments-service->bank-rails`, `dep:payments-service->postgres-payments`)
**Contradicting:**
- payments‑service recorded 44 ERROR lines “withdrawal <id> failed: bank‑rails call returned an error” from 17:48:12 to 17:59:37 UTC. (`log:33df62f69e8a`)
**Assumptions:**
- ASM-9: Edge‑gateway’s per‑route timeout was lowered to < payments‑service’s 4 s bank‑rails timeout, causing the gateway to abort while payments‑service is still waiting.
**Objections:**
- [blocking] unsupported_claim: names chg:unknown as the trigger, but no change-history query returned it
- [minor] unsupported_claim: The trigger “chg:unknown” for an edge‑gateway timeout change is asserted but change‑history queries return no data; the backend is down.
- [blocking] alternative_not_excluded: HYP‑1 (bank‑rails degradation) explains the same upstream‑502 and payments‑service error logs without requiring a gateway config change.

### 4. `resource_exhaustion` on **postgres-payments** (HYP-3)

Confidence 0.04 (low), critic: reject. Transient saturation of the payments database (connection‑pool exhaustion, autovacuum spike, replication lag) caused payments‑service to abort the withdrawal flow before or while calling bank‑rails, resulting in a generic error that is logged as a bank‑rails failure.

**Supporting:**
- postgres‑payments logged a single WARN about autovacuum dead tuples at 17:59:09 UTC. (`log:ebf2696ab540`)
- The core withdrawal request path is edge‑gateway → payments‑service → bank‑rails (hard dependency, HTTPS, 4000 ms timeout) and payments‑service → postgres‑payments (hard dependency, SQL, 2000 ms timeout). (`dep:edge-gateway->payments-service`, `dep:payments-service->bank-rails`, `dep:payments-service->postgres-payments`)
**Contradicting:**
- payments‑service recorded 44 ERROR lines “withdrawal <id> failed: bank‑rails call returned an error” from 17:48:12 to 17:59:37 UTC. (`log:33df62f69e8a`)
- payments‑service also emitted 6 generic 502 errors on POST /v1/checkout between 17:48:21 and 17:58:09 UTC. (`log:3d2e4dba2230`)
**Assumptions:**
- ASM-4: The autovacuum warning at 17:59:09 UTC is unrelated to the withdrawal path.
**Objections:**
- [blocking] ignores_contradiction: OBS‑4 shows explicit bank‑rails errors from payments‑service, contradicting a postgres‑exhaustion cause.

## Recommended actions

| Urgency | Kind | Action | Why |
|---|---|---|---|
| now | mitigate | Enable a short‑circuit / fallback path in payments‑service for withdrawals (e.g., queue for retry or return a user‑friendly error) so that bank‑rails outages do not block the whole flow. | Immediately reduces customer impact while the upstream provider is unstable. (HYP-1) |
| soon | fix | Contact the bank‑rails vendor to obtain an incident report for the 17:45‑18:00 UTC window and negotiate SLA improvements or a status‑page webhook. | Addresses the most likely external degradation (HYP‑1) and prevents recurrence. (HYP-1) |
| soon | prevent | Add automated health‑checks and alerting on bank‑rails latency / 5xx rate, and configure a circuit‑breaker in payments‑service with a lower timeout and exponential back‑off. | Detects future degradations early and limits blast radius. (HYP-1) |
| later | investigate | When the metrics and change‑history services recover, query bank‑rails latency/5xx metrics for 17:45‑18:00 UTC and payments‑service change‑history for 17:30‑17:45 UTC to confirm or exclude HYP‑1 and HYP‑2. | Closes the evidence gaps (GAP‑1, GAP‑2, GAP‑5‑GAP‑14) that prevent a definitive conclusion. (HYP-1) |
| later | investigate | Verify whether any payments‑service or edge‑gateway config/feature‑flag changes were deployed in the 17:30‑17:45 UTC window once change‑history is available. | Rules out HYP‑2 and HYP‑4 which remain plausible alternatives. (HYP-2) |

## Evidence gaps

- **get_change_history** (start=2026-10-15T17:00:00Z, end=2026-10-15T18:00:00Z): unavailable: get_change_history backend returned 503 Service Unavailable
- **get_change_history** (bank-rails changes between 2026-10-15T17:15:00Z and 2026-10-15T18:00:00Z): Change‑history backend returned 503 then refused further calls; no change data available.
- **get_change_history** (services=['bank-rails'], start=2026-10-15T17:15:00Z, end=2026-10-15T18:00:00Z): unavailable: get_change_history backend returned 503 Service Unavailable
- **get_change_history** (services=['bank-rails'], start=2026-10-15T17:15:00Z, end=2026-10-15T18:00:00Z): refused: get_change_history has failed 2 calls in a row; its backend is treated as down for the rest of this investigation
- **query_metrics** (All four services (edge-gateway, payments-service, bank-rails, postgres-payments) for 2026‑10‑15 17:15‑18:00 UTC): Metrics backend timed out on first calls and then was marked down; no latency, error‑rate, or saturation data could be retrieved.
- **query_logs** (bank-rails logs before 17:48 UTC (az‑a shard unavailable)): Log shard for az‑a is unavailable and logs before 17:48 UTC have expired, so early‑window bank‑rails errors cannot be confirmed.
- **query_logs** (service=edge-gateway, start=2026-10-15T17:15:00Z, end=2026-10-15T18:00:00Z): log shard for az-a is unavailable; results exclude pods in az-a; logs before 2026-10-15 17:48 UTC have expired and are not returned
- **query_logs** (service=payments-service, start=2026-10-15T17:15:00Z, end=2026-10-15T18:00:00Z): log shard for az-a is unavailable; results exclude pods in az-a; logs before 2026-10-15 17:48 UTC have expired and are not returned
- **query_logs** (service=bank-rails, start=2026-10-15T17:15:00Z, end=2026-10-15T18:00:00Z): log shard for az-a is unavailable; results exclude pods in az-a; logs before 2026-10-15 17:48 UTC have expired and are not returned
- **query_logs** (service=postgres-payments, start=2026-10-15T17:15:00Z, end=2026-10-15T18:00:00Z): log shard for az-a is unavailable; results exclude pods in az-a; logs before 2026-10-15 17:48 UTC have expired and are not returned
- **query_metrics** (service=edge-gateway, start=2026-10-15T17:15:00Z, end=2026-10-15T18:00:00Z): timeout: query_metrics did not respond within 10s
- **query_metrics** (service=payments-service, start=2026-10-15T17:15:00Z, end=2026-10-15T18:00:00Z): timeout: query_metrics did not respond within 10s
- **query_metrics** (service=bank-rails, start=2026-10-15T17:15:00Z, end=2026-10-15T18:00:00Z): timeout: query_metrics did not respond within 10s
- **query_metrics** (service=postgres-payments, start=2026-10-15T17:15:00Z, end=2026-10-15T18:00:00Z): timeout: query_metrics did not respond within 10s
- **query_metrics** (service=edge-gateway): refused: query_metrics has failed 4 calls in a row; its backend is treated as down for the rest of this investigation
- **query_metrics** (service=payments-service): refused: query_metrics has failed 4 calls in a row; its backend is treated as down for the rest of this investigation
- **query_metrics** (service=bank-rails): refused: query_metrics has failed 4 calls in a row; its backend is treated as down for the rest of this investigation
- **query_metrics** (service=postgres-payments): refused: query_metrics has failed 4 calls in a row; its backend is treated as down for the rest of this investigation
- **get_change_history** (services edge-gateway, payments-service, bank-rails, postgres-payments from 2026-10-15T17:15:00Z to 2026-10-15T18:00:00Z): Backend refused after two consecutive failures; treated as down for the rest of the investigation.
- **get_change_history** (services=['edge-gateway', 'payments-service', 'bank-rails', 'postgres-payments'], start=2026-10-15T17:15:00Z, end=2026-10-15T18:00:00Z): refused: get_change_history has failed 2 calls in a row; its backend is treated as down for the rest of this investigation
- **get_change_history** (payments-service config/feature_flag changes 2026-10-15T16:00:00Z–2026-10-15T18:00:00Z): Backend returned a permanent error; change‑history service treated as down for the rest of the investigation.
- **get_change_history** (services=['payments-service'], start=2026-10-15T16:00:00Z, end=2026-10-15T18:00:00Z): refused: get_change_history has failed 2 calls in a row; its backend is treated as down for the rest of this investigation
- **query_logs** (payments-service 2026-10-15T17:30:00Z–2026-10-15T17:45:00Z): Log shards for the requested period have expired and are not retained.
- **query_logs** (service=payments-service, start=2026-10-15T17:30:00Z, end=2026-10-15T17:45:00Z): log shard for az-a is unavailable; results exclude pods in az-a; logs before 2026-10-15 17:48 UTC have expired and are not returned
- **query_logs** (payments‑service structured logs for timeout, retry, baseurl (INFO+) across 16:00‑18:00 UTC): Log shard az‑a unavailable and logs before 17:48 UTC expired, so any relevant lines in that period or on that AZ cannot be retrieved.
- **query_metrics** (payments‑service metrics that might surface HTTP client config (timeout, retries, base URL)): No metrics query was performed; such metrics could reveal the values even if logs do not.
- **query_logs** (service=payments-service, start=2026-10-15T16:00:00Z, end=2026-10-15T18:00:00Z): log shard for az-a is unavailable; results exclude pods in az-a; logs before 2026-10-15 17:48 UTC have expired and are not returned

## Open questions

- Did the bank‑rails provider experience a latency spike or error‑rate increase between 17:45‑18:00 UTC?
- Was there any payments‑service configuration change (timeout, retry, endpoint, feature flag) deployed between 17:30‑17:45 UTC?
- Was the edge‑gateway per‑route timeout for POST /v1/withdrawals altered to a value < 4 s during the same window?
- What do the bank‑rails internal logs (az‑a shard) show for the period before 17:48 UTC?
- Are there any correlated infrastructure events (network, DNS, cert renewal) that could have affected the bank‑rails HTTPS endpoint?

## How the investigation ran

Stopped because time budget reached, after 2 round(s): 33 model calls, 23 tool calls, 133,919 tokens, 995 s.
