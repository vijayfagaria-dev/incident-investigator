# T10: Withdrawals failing

**Outcome:** conclusive. Root cause: `dependency_degradation` on **bank-rails**

## Summary

Withdrawals failed for several customers between roughly 17:48 UTC and 17:59 UTC, with the edge‑gateway returning 502 errors from payments‑service, which logged repeated “bank‑rails call returned an error” messages. The most likely cause is an unannounced maintenance window on the bank‑rails dependency (HYP‑1, 68 % confidence), but bank‑rails metrics and logs for the critical 17:15‑18:00 UTC window are unavailable, so the hypothesis cannot be fully verified. Deposits remained healthy because they use a different rail. The investigation was stopped because the allocated time budget was reached.

## Hypotheses

### 1. `dependency_degradation` on **bank-rails** (HYP-1)

Confidence 0.68 (medium), critic: challenge. Bank‑rails entered an unannounced maintenance window, causing its HTTPS endpoint to return errors or time out. Payments‑service calls bank‑rails with a hard 4 s timeout (OBS‑2) and propagates those failures as “bank‑rails call returned an error” (OBS‑9). Edge‑gateway receives 502 from payments‑service on POST /v1/withdrawals (OBS‑5). Deposits remain healthy because they use a different rail.

**Supporting:**
- payments-service calls bank-rails over HTTPS with hard criticality (timeout 4 s). (`dep:payments-service->bank-rails`)
- No direct hard dependency from edge-gateway to bank-rails or postgres-payments; the withdrawal path must traverse payments-service. (`dep:edge-gateway->payments-service`, `dep:payments-service->bank-rails`, `dep:payments-service->postgres-payments`)
- Edge‑gateway logged 31 warnings of “upstream payments‑service returned 502 (route POST /v1/withdrawals)” between 2026‑10‑15 17:48:34 UTC and 2026‑10‑15 17:59:57 UTC. (`log:8fed29f3ce72`, `log:21ea9e40baee`, `log:5cc048209803`)
- payments-service logged 44 ERROR lines matching “withdrawal <id> failed: bank‑rails call returned an error” between 2026‑10‑15T17:48:12.345Z and 2026‑10‑15T17:59:37.986Z. (`log:33df62f69e8a`)
**Assumptions:**
- ASM-6: Bank‑rails endpoint began returning errors/time‑outs at ~17:45 UTC and stayed degraded until ~18:00 UTC.
- ASM-7: Deposits succeed because they use a different rail, unaffected by the maintenance.
**Objections:**
- [minor] gap_unaddressed: Bank‑rails metrics (error rate, latency, circuit‑breaker) and logs for 17:15‑18:00 UTC are unavailable (GAP‑19, GAP‑20, GAP‑21), so the predicted spike cannot be verified.
- [minor] analogy_only: Supporting citations OBS‑11 and OBS‑12 reference a past incident (pir:2026-011) rather than current observations.
- [minor] alternative_not_excluded: HYP‑2, HYP‑3, and HYP‑4 remain plausible and have not been ruled out.

### 2. `code_regression` on **payments-service** (HYP-2)

Confidence 0.22 (low), critic: challenge. A silent deploy or configuration change around 17:45 UTC introduced a regression in the bank‑rails client (e.g., wrong timeout, broken retry logic). Payments‑service then fails calls to bank‑rails and logs “bank‑rails call returned an error” (OBS‑9) while also breaking checkout (OBS‑10). Edge‑gateway surfaces the 502 (OBS‑5).

**Supporting:**
- Edge‑gateway logged 31 warnings of “upstream payments‑service returned 502 (route POST /v1/withdrawals)” between 2026‑10‑15 17:48:34 UTC and 2026‑10‑15 17:59:57 UTC. (`log:8fed29f3ce72`, `log:21ea9e40baee`, `log:5cc048209803`)
- payments-service logged 44 ERROR lines matching “withdrawal <id> failed: bank‑rails call returned an error” between 2026‑10‑15T17:48:12.345Z and 2026‑10‑15T17:59:37.986Z. (`log:33df62f69e8a`)
- payments-service also emitted 6 ERROR lines for “POST /v1/checkout 502 9ms” between 2026‑10‑15T17:48:21.239Z and 2026‑10‑15T17:58:09.128Z. (`log:3d2e4dba2230`)
**Contradicting:**
- payments-service calls bank-rails over HTTPS with hard criticality (timeout 4 s). (`dep:payments-service->bank-rails`)
- No direct hard dependency from edge-gateway to bank-rails or postgres-payments; the withdrawal path must traverse payments-service. (`dep:edge-gateway->payments-service`, `dep:payments-service->bank-rails`, `dep:payments-service->postgres-payments`)
**Assumptions:**
- ASM-8: A deploy / flag flip / secret rotation occurred at ~17:45 UTC that altered the bank‑rails client in payments‑service.
- ASM-9: The change only affected withdrawal/checkout code paths, leaving deposits untouched.
**Objections:**
- [minor] gap_unaddressed: Change‑history for payments‑service (and related services) could not be retrieved (GAP‑1‑4, GAP‑17‑18), so a deploy at ~17:45 UTC cannot be confirmed.
- [minor] unsupported_claim: Assumes a silent deploy/config change without any observed change record.
- [minor] alternative_not_excluded: HYP‑1, HYP‑3, HYP‑4 still possible.

### 3. `resource_exhaustion` on **payments-service** (HYP-3)

Confidence 0.07 (low), critic: challenge. Payments‑service exhausted its HTTP client connection pool (or thread pool) when calling bank‑rails, causing it to surface upstream errors as “bank‑rails call returned an error” (OBS‑9) and also break checkout (OBS‑10). Edge‑gateway receives 502 from payments‑service (OBS‑5).

**Supporting:**
- Edge‑gateway logged 31 warnings of “upstream payments‑service returned 502 (route POST /v1/withdrawals)” between 2026‑10‑15 17:48:34 UTC and 2026‑10‑15 17:59:57 UTC. (`log:8fed29f3ce72`, `log:21ea9e40baee`, `log:5cc048209803`)
- payments-service logged 44 ERROR lines matching “withdrawal <id> failed: bank‑rails call returned an error” between 2026‑10‑15T17:48:12.345Z and 2026‑10‑15T17:59:37.986Z. (`log:33df62f69e8a`)
- payments-service also emitted 6 ERROR lines for “POST /v1/checkout 502 9ms” between 2026‑10‑15T17:48:21.239Z and 2026‑10‑15T17:58:09.128Z. (`log:3d2e4dba2230`)
**Contradicting:**
- payments-service calls bank-rails over HTTPS with hard criticality (timeout 4 s). (`dep:payments-service->bank-rails`)
**Assumptions:**
- ASM-10: Payments‑service ran out of HTTP client connections to bank‑rails (or its own DB pool) causing it to surface upstream errors.
- ASM-11: The exhaustion started ~17:45 UTC and cleared by 18:00 UTC.
**Objections:**
- [minor] gap_unaddressed: Payments‑service client‑pool saturation metrics not fetched (GAP‑14) and metrics backend down, preventing verification of exhaustion.
- [minor] unsupported_claim: Assumes connection‑pool exhaustion without metric evidence.
- [minor] alternative_not_excluded: HYP‑1, HYP‑2, HYP‑4 still possible.

### 4. `certificate_or_credential` on **bank-rails** (HYP-4)

Confidence 0.03 (low), critic: challenge. Bank‑rails rotated a TLS certificate or revoked an API key at ~17:45 UTC. HTTPS calls from payments‑service fail with a generic error that payments‑service logs as “bank‑rails call returned an error” (OBS‑9). Edge‑gateway sees 502 (OBS‑5).

**Supporting:**
- Edge‑gateway logged 31 warnings of “upstream payments‑service returned 502 (route POST /v1/withdrawals)” between 2026‑10‑15 17:48:34 UTC and 2026‑10‑15 17:59:57 UTC. (`log:8fed29f3ce72`, `log:21ea9e40baee`, `log:5cc048209803`)
- payments-service logged 44 ERROR lines matching “withdrawal <id> failed: bank‑rails call returned an error” between 2026‑10‑15T17:48:12.345Z and 2026‑10‑15T17:59:37.986Z. (`log:33df62f69e8a`)
**Contradicting:**
- payments-service calls bank-rails over HTTPS with hard criticality (timeout 4 s). (`dep:payments-service->bank-rails`)
**Assumptions:**
- ASM-12: Bank‑rails rotated a cert or revoked a key at ~17:45 UTC, causing HTTPS calls to fail.
**Objections:**
- [minor] gap_unaddressed: Bank‑rails logs showing TLS handshake or credential failures are missing for the critical window (GAP‑12, GAP‑16, GAP‑20, GAP‑21).
- [minor] unsupported_claim: Assumes certificate/credential rotation without any observed log evidence.
- [minor] alternative_not_excluded: HYP‑1, HYP‑2, HYP‑3 still possible.

## Recommended actions

| Urgency | Kind | Action | Why |
|---|---|---|---|
| now | mitigate | Add a graceful fallback for withdrawal requests when bank‑rails calls fail (e.g., return a user‑friendly error and queue the request for retry). | Immediately reduces customer impact while the root cause is being confirmed. (HYP-1) |
| soon | fix | Engage the bank‑rails vendor to obtain a maintenance schedule and enforce a notification SLA for any future planned or unplanned outages. | If HYP‑1 is correct, lack of notice caused the outage; a formal SLA prevents recurrence. (HYP-1) |
| later | prevent | Improve observability for bank‑rails: retain metrics (error rate, latency, circuit‑breaker state) and logs for at least 48 h, and add alerts on sustained error‑rate spikes. | Current gaps (GAP‑19‑21) prevented verification; better data will allow faster confirmation next time. (HYP-1) |
| soon | investigate | Retrieve bank‑rails metrics and full logs for 17:15‑18:00 UTC (including AZ‑a shard) to confirm a latency/error spike or maintenance messages. | Directly tests the prediction of HYP‑1 and closes GAP‑19‑21. (HYP-1) |
| soon | investigate | Obtain payments‑service change history for 17:15‑18:00 UTC to rule out a silent deploy or config change. | Addresses GAP‑1‑4, 17‑18 and the HYP‑2 alternative. (HYP-2) |
| soon | investigate | Collect payments‑service HTTP client‑pool saturation metrics for the incident window. | Validates or rejects the connection‑pool exhaustion scenario in HYP‑3 (GAP‑14). (HYP-3) |
| later | investigate | Check bank‑rails TLS certificate and credential rotation logs around 17:45 UTC. | Tests the certificate/credential hypothesis (HYP‑4) and closes GAP‑12, 16, 20, 21. (HYP-4) |

## Evidence gaps

- **get_change_history** (start=2026-10-15T17:00:00Z, end=2026-10-15T18:00:00Z): unavailable: get_change_history backend returned 503 Service Unavailable
- **get_change_history** (payments-service, bank-rails, postgres-payments, edge-gateway, kafka (2026-10-15 17:15‑18:00 UTC)): Backend returned 503 then was marked down; no change records could be retrieved.
- **get_change_history** (services=['payments-service', 'bank-rails', 'postgres-payments', 'edge-gateway', 'kafka'], start=2026-10-15T17:15:00Z, end=2026-10-15T18:00:00Z): unavailable: get_change_history backend returned 503 Service Unavailable
- **get_change_history** (services=['payments-service', 'bank-rails', 'postgres-payments', 'edge-gateway', 'kafka'], start=2026-10-15T17:15:00Z, end=2026-10-15T18:00:00Z): refused: get_change_history has failed 2 calls in a row; its backend is treated as down for the rest of this investigation
- **query_metrics** (edge-gateway metrics 2026‑10‑15 17:15‑18:00 UTC): Query timed out after 10 s; no metric data retrieved.
- **query_logs** (edge-gateway logs before 2026‑10‑15 17:48 UTC): Log retention expired; earlier events not returned.
- **query_logs** (edge-gateway az‑a shard): Shard unavailable; logs from that AZ excluded.
- **query_logs** (service=edge-gateway, start=2026-10-15T17:15:00Z, end=2026-10-15T18:00:00Z): log shard for az-a is unavailable; results exclude pods in az-a; logs before 2026-10-15 17:48 UTC have expired and are not returned
- **query_metrics** (service=edge-gateway, start=2026-10-15T17:15:00Z, end=2026-10-15T18:00:00Z): timeout: query_metrics did not respond within 10s
- **query_metrics** (service=edge-gateway): timeout: query_metrics did not respond within 10s
- **query_logs** (payments-service logs before 17:48 UTC): Log shards expired; cannot see when the first failure began.
- **query_logs** (bank‑rails logs (all levels) for 17:15‑18:00): No patterns returned; missing shard az‑a and possible log loss.
- **query_logs** (postgres‑payments logs (WARN/ERROR) for 17:15‑18:00): Not queried; need to confirm DB‑side errors.
- **query_metrics** (payments‑service, bank‑rails, postgres‑payments key metrics (error rate, latency, saturation, circuit‑breaker state) for 17:15‑18:00): Metrics not fetched; needed to pinpoint onset and saturation signals.
- **query_logs** (service=payments-service, start=2026-10-15T17:15:00Z, end=2026-10-15T18:00:00Z): log shard for az-a is unavailable; results exclude pods in az-a; logs before 2026-10-15 17:48 UTC have expired and are not returned
- **query_logs** (service=bank-rails, start=2026-10-15T17:15:00Z, end=2026-10-15T18:00:00Z): log shard for az-a is unavailable; results exclude pods in az-a; logs before 2026-10-15 17:48 UTC have expired and are not returned
- **get_change_history** (payments-service, bank-rails between 2026-10-15T17:15:00Z and 2026-10-15T18:00:00Z): Backend refused the request and is treated as down; no change records could be fetched.
- **get_change_history** (services=['payments-service', 'bank-rails'], start=2026-10-15T17:15:00Z, end=2026-10-15T18:00:00Z): refused: get_change_history has failed 2 calls in a row; its backend is treated as down for the rest of this investigation
- **query_metrics** (bank‑rails error‑rate, latency (p99), saturation, circuit‑breaker state for 2026‑10‑15T17:15:00Z‑2026‑10‑15T18:00:00Z): Metrics backend refused after two consecutive failures and is treated as down.
- **query_logs** (bank‑rails logs from 2026‑10‑15T17:15:00Z‑2026‑10‑15T17:48:00Z (all AZs)): Logs before 17:48 UTC have expired; AZ‑a shard unavailable.
- **query_logs** (bank‑rails logs from AZ‑a after 2026‑10‑15T17:48:00Z): AZ‑a log shard is unavailable, so any zone‑specific errors are missing.
- **query_metrics** (service=bank-rails, start=2026-10-15T17:15:00Z, end=2026-10-15T18:00:00Z): refused: query_metrics has failed 2 calls in a row; its backend is treated as down for the rest of this investigation
- **query_logs** (service=bank-rails, start=2026-10-15T17:15:00Z, end=2026-10-15T18:00:00Z): log shard for az-a is unavailable; results exclude pods in az-a; logs before 2026-10-15 17:48 UTC have expired and are not returned

## Open questions

- Did bank‑rails actually undergo an unannounced maintenance window during 17:15‑18:00 UTC?
- Was there any silent deploy or configuration change in payments‑service (or its dependencies) at ~17:45 UTC?
- Did the payments‑service HTTP client connection pool become saturated during the incident?
- Were any TLS certificate rotations or API‑key revocations performed on bank‑rails at the onset?
- What was the exact start time of the first withdrawal failure (logs before 17:48 UTC are missing)?

## How the investigation ran

Stopped because time budget reached, after 2 round(s): 31 model calls, 14 tool calls, 123,124 tokens, 1010 s.
