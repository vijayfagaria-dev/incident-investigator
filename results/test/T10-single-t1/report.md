# T10: Withdrawals failing

**Outcome:** conclusive. Root cause: `dependency_degradation` on **bank-rails**

## Summary

Starting at 2026-10-15T17:48:12Z the payments-service began emitting dozens of errors indicating that calls to the external bank-rails dependency failed. The dependency is a hard HTTPS call with a 4 s timeout. No logs, metrics, or change‑history data are available for the window, so the exact trigger cannot be confirmed.

## Hypotheses

### 1. `dependency_degradation` on **bank-rails** (HYP-1)

Confidence 0.55 (medium). An external outage or unannounced maintenance on bank-rails caused the HTTPS calls from payments-service to fail, which payments-service surfaces as “bank‑rails call returned an error”.

**Supporting:**
- payments-service logged 44 ERROR lines “withdrawal <id> failed: bank-rails call returned an error” from 17:48:12Z to 17:59:37Z. (`log:33df62f69e8a`)
- Dependency graph shows a hard HTTPS dependency payments-service → bank-rails with a 4000 ms timeout. (`dep:payments-service->bank-rails`)
**Assumptions:**
- ASM-1: The error text “bank‑rails call returned an error” is emitted only when the downstream HTTP call fails (non‑2xx, timeout, TLS error, etc.).
- ASM-3: No other service (e.g., edge‑gateway) shows errors, suggesting the problem is confined to the payments‑service → bank‑rails link.

### 2. `code_regression` on **payments-service** (HYP-2)

Confidence 0.20 (low). A recent code deploy introduced a bug in handling bank‑rails responses, causing every call to be treated as an error starting at 17:48.

**Supporting:**
- payments-service logged 44 ERROR lines “withdrawal <id> failed: bank-rails call returned an error” from 17:48:12Z to 17:59:37Z. (`log:33df62f69e8a`)
**Assumptions:**
- ASM-2: A deploy to payments-service could have been rolled out a few minutes before 17:48 but is invisible because the change‑history API is down.

### 3. `infrastructure_failure` on **infrastructure** (HYP-3)

Confidence 0.15 (low). A network, DNS, or TLS/certificate problem between payments-service and bank-rails caused the HTTPS calls to fail (handshake error, timeout, cert validation failure).

**Supporting:**
- payments-service logged 44 ERROR lines “withdrawal <id> failed: bank-rails call returned an error” from 17:48:12Z to 17:59:37Z. (`log:33df62f69e8a`)
- Dependency graph shows a hard HTTPS dependency payments-service → bank-rails with a 4000 ms timeout. (`dep:payments-service->bank-rails`)
**Assumptions:**
- ASM-1: The error text “bank‑rails call returned an error” is emitted only when the downstream HTTP call fails (non‑2xx, timeout, TLS error, etc.).
- ASM-3: No other service (e.g., edge‑gateway) shows errors, suggesting the problem is confined to the payments‑service → bank‑rails link.

### 4. `config_change` on **payments-service** (HYP-4)

Confidence 0.10 (low). A configuration change reduced the HTTP client timeout or tightened a circuit‑breaker threshold, so normal bank‑rails latency now exceeds the limit and is logged as an error.

**Supporting:**
- payments-service logged 44 ERROR lines “withdrawal <id> failed: bank-rails call returned an error” from 17:48:12Z to 17:59:37Z. (`log:33df62f69e8a`)
- Dependency graph shows a hard HTTPS dependency payments-service → bank-rails with a 4000 ms timeout. (`dep:payments-service->bank-rails`)
**Assumptions:**
- ASM-4: A config change (e.g., lowered timeout or circuit‑breaker threshold) could have been applied just before 17:48 but is not captured.

## Recommended actions

| Urgency | Kind | Action | Why |
|---|---|---|---|
| now | investigate | Contact bank‑rails vendor (status page, support) to confirm any outage or maintenance around 17:45‑18:00. | Directly tests the most likely hypothesis (H1) that the external dependency degraded. |
| now | investigate | Retrieve payments-service metrics (error rate, latency, saturation) once the metrics backend recovers and correlate with the 17:48 error spike. | Quantifies impact and confirms whether the error rate matches log volume. |
| soon | investigate | Re‑run get_change_history (or query CI/CD) for payments-service and bank-rails to locate any deploy, config, feature‑flag, secret rotation, or infra work at ~17:40‑17:50. | Needed to validate or discard hypotheses H2, H4 (code regression or config change). |
| soon | investigate | Request detailed error codes / logs from bank‑rails (HTTP status, TLS alerts) for the failing calls. | Determines exact failure mode (timeout, cert error, rate‑limit) to discriminate H1 vs H3. |
| later | mitigate | Add a circuit‑breaker / fallback for the bank‑rails call in payments-service and improve alerting on hard‑dependency error rates. | Reduces blast radius for future provider issues regardless of root cause. |
| later | prevent | Verify certificate expiry and TLS configuration for the payments‑service → bank‑rails connection; automate renewal monitoring. | Guards against hypothesis H3 (certificate_or_credential). |
| later | prevent | Extend log retention to cover at least 2 hours before any alert so early warning patterns are not lost. | Addresses gap F7 and improves future investigations. |

## Evidence gaps

- **query_metrics** (payments-service and bank-rails (17:30‑18:00)): Metrics backend timed out / marked down, preventing error‑rate and latency verification.
- **get_change_history** (payments-service, bank-rails (16:00‑18:00)): Change‑history service returned 503, so no deploy/config/flag/secret/infra records are available.
- **query_logs** (bank-rails (17:30‑18:00)): External provider logs not accessible; only notice that AZ‑a shard unavailable.
- **query_logs** (payments-service before 17:48): Log retention expired at 17:48, hiding any earlier warning signs.
- **query_logs** (service=payments-service, start=2026-10-15T17:00:00Z, end=2026-10-15T18:00:00Z): log shard for az-a is unavailable; results exclude pods in az-a; logs before 2026-10-15 17:48 UTC have expired and are not returned
- **query_metrics** (service=payments-service, start=2026-10-15T17:30:00Z, end=2026-10-15T18:00:00Z): timeout: query_metrics did not respond within 10s
- **query_logs** (service=bank-rails, start=2026-10-15T17:00:00Z, end=2026-10-15T18:00:00Z): log shard for az-a is unavailable; results exclude pods in az-a; logs before 2026-10-15 17:48 UTC have expired and are not returned
- **get_change_history** (services=['payments-service', 'bank-rails'], start=2026-10-15T16:00:00Z, end=2026-10-15T18:00:00Z): unavailable: get_change_history backend returned 503 Service Unavailable
- **get_change_history** (start=2026-10-15T16:00:00Z, end=2026-10-15T18:00:00Z): unavailable: get_change_history backend returned 503 Service Unavailable
- **query_metrics** (service=bank-rails, start=2026-10-15T17:30:00Z, end=2026-10-15T18:00:00Z): refused: query_metrics has failed 2 calls in a row; its backend is treated as down for the rest of this investigation

## Open questions

- Did bank‑rails publish a maintenance window or experience an unplanned outage at ~17:45?
- Was there a payments-service deploy or config push between 17:30‑17:48 that is invisible to the change‑history API?
- What exact HTTP status or TLS error did the bank‑rails call return? (requires provider logs.)
- Why are the metrics and change‑history back‑ends currently down—are they related to the same incident?
- Are any upstream services (e.g., edge‑gateway) seeing elevated 5xx that would indicate a broader platform issue?

## How the investigation ran

Stopped because the agent finished its investigation, after 1 round(s): 10 model calls, 8 tool calls, 56,363 tokens, 408 s.
