# T10: Withdrawals failing

**Outcome:** inconclusive
- HYP-1 has unresolved blocking objections

## Summary

The investigation into the withdrawal failures (INCIDENT T10) ended inconclusive after two rounds. The leading hypothesis (HYP‑1) that bank‑rails experienced a degradation fits the observed error logs and the 4 s timeout dependency, but the required bank‑rails 5xx error‑rate and latency metrics for 17:30‑18:00 UTC are unavailable (GAP‑14‑16). Alternative hypotheses — a payments‑service code regression (HYP‑2), a network fault on the AZ‑a path (HYP‑3), and a bank‑rails credential rotation (HYP‑4) — each have supporting observations and have not been ruled out because change‑history and network‑level data could not be retrieved (GAP‑9‑13, GAP‑3). The investigation stopped because the round limit was reached.

## Hypotheses

### 1. `dependency_degradation` on **bank-rails** (HYP-1)

Confidence 0.50 (medium), critic: challenge, capped from 0.71: it has unresolved blocking objections. Bank‑rails began returning error HTTP responses or timing‑out (> 4 s) for withdrawal calls. Payments‑service has a hard 4 s HTTPS dependency on bank‑rails (OBS‑3), so each failure is logged as “bank‑rails call returned an error” and results in a 5xx response to the caller.

**Supporting:**
- payments‑service emitted 44 ERROR log lines matching “withdrawal <id> failed: bank‑rails call returned an error” between 2026‑10‑15T17:48:12.345Z and 2026‑10‑15T17:59:37.986Z. (`log:33df62f69e8a`)
- payments-service calls bank-rails over HTTPS with a hard criticality and 4000 ms timeout. (`dep:payments-service->bank-rails`)
**Contradicting:**
- payments‑service also logged 6 ERROR lines for “POST /v1/checkout 502 …” between 2026‑10‑15T17:48:21.239Z and 2026‑10‑15T17:58:09.128Z, indicating broader upstream errors. (`log:3d2e4dba2230`)
**Assumptions:**
- ASM-6: The withdrawal path is the only payments‑service call that reaches bank‑rails during the window (deposits/checkout use a different rail).
- ASM-7: The 44 error lines represent the majority of withdrawal traffic in the window.
**Objections:**
- [blocking] gap_unaddressed: Bank‑rails 5xx error‑rate and latency p99 for 17:30‑18:00 UTC are not available (GAP‑14‑16). These metrics are required to confirm the predicted degradation.
- [blocking] alternative_not_excluded: HYP‑2 (code regression), HYP‑3 (network fault), and HYP‑4 (credential rotation) all have supporting observations and have not been ruled out.

### 2. `certificate_or_credential` on **bank-rails** (HYP-4)

Confidence 0.16 (low), critic: challenge. A scheduled rotation of the bank‑rails API key / client certificate occurred just before 17:45 UTC. Payments‑service continued using the stale credential, so every HTTPS call was rejected with 401/403, which payments‑service logs as “bank‑rails call returned an error”.

**Supporting:**
- payments‑service emitted 44 ERROR log lines matching “withdrawal <id> failed: bank‑rails call returned an error” between 2026‑10‑15T17:48:12.345Z and 2026‑10‑15T17:59:37.986Z. (`log:33df62f69e8a`)
- payments-service calls bank-rails over HTTPS with a hard criticality and 4000 ms timeout. (`dep:payments-service->bank-rails`)
**Contradicting:**
- payments‑service also logged 6 ERROR lines for “POST /v1/checkout 502 …” between 2026‑10‑15T17:48:21.239Z and 2026‑10‑15T17:58:09.128Z, indicating broader upstream errors. (`log:3d2e4dba2230`)
**Assumptions:**
- ASM-8: A credential rotation for bank‑rails occurred in the 17:15‑18:00 window.
- ASM-9: Payments‑service does not automatically reload the secret on 4xx responses.
**Objections:**
- [blocking] gap_unaddressed: Secret/credential rotation events for bank‑rails in the 17:15‑18:00 window cannot be retrieved (change‑history backend down, GAP‑9‑13).
- [blocking] alternative_not_excluded: HYP‑1 (bank‑rails degradation) and HYP‑2 (code regression) also explain the withdrawal failures and have not been ruled out.

### 3. `code_regression` on **payments-service** (HYP-2)

Confidence 0.09 (low), critic: challenge. A recent payments‑service deploy or feature‑flag toggle introduced a bug that mis‑classifies successful bank‑rails responses (or treats any timeout as an error) and also breaks the checkout path, producing the 502s seen in OBS‑2.

**Supporting:**
- payments‑service emitted 44 ERROR log lines matching “withdrawal <id> failed: bank‑rails call returned an error” between 2026‑10‑15T17:48:12.345Z and 2026‑10‑15T17:59:37.986Z. (`log:33df62f69e8a`)
- payments‑service also logged 6 ERROR lines for “POST /v1/checkout 502 …” between 2026‑10‑15T17:48:21.239Z and 2026‑10‑15T17:58:09.128Z, indicating broader upstream errors. (`log:3d2e4dba2230`)
**Contradicting:**
- payments-service calls bank-rails over HTTPS with a hard criticality and 4000 ms timeout. (`dep:payments-service->bank-rails`)
**Assumptions:**
- ASM-10: A payments‑service deploy or flag change occurred ≈ 17:40 UTC.
- ASM-11: The bug manifests only on the withdrawal code path and the checkout path simultaneously.
**Objections:**
- [blocking] gap_unaddressed: Change history for payments‑service (and bank‑rails) during 17:15‑18:00 is unavailable (GAP‑9‑13). A deploy or flag toggle near 17:45 cannot be confirmed or excluded.
- [blocking] alternative_not_excluded: HYP‑1 (bank‑rails degradation) and HYP‑4 (credential rotation) also explain the observed errors and remain viable.

### 4. `infrastructure_failure` on **network** (HYP-3)

Confidence 0.04 (low), critic: challenge. A transient network fault (routing change, firewall rule, packet loss) on the AZ‑a path between payments‑service and bank‑rails caused HTTPS calls to be reset or timed‑out, which payments‑service records as “bank‑rails call returned an error”.

**Supporting:**
- payments‑service emitted 44 ERROR log lines matching “withdrawal <id> failed: bank‑rails call returned an error” between 2026‑10‑15T17:48:12.345Z and 2026‑10‑15T17:59:37.986Z. (`log:33df62f69e8a`)
- payments-service calls bank-rails over HTTPS with a hard criticality and 4000 ms timeout. (`dep:payments-service->bank-rails`)
**Contradicting:**
- payments‑service also logged 6 ERROR lines for “POST /v1/checkout 502 …” between 2026‑10‑15T17:48:21.239Z and 2026‑10‑15T17:58:09.128Z, indicating broader upstream errors. (`log:3d2e4dba2230`)
- payments-service calls postgres-payments over SQL with a hard criticality and 2000 ms timeout. (`dep:payments-service->postgres-payments`)
**Assumptions:**
- ASM-12: The fault is confined to the payments‑service → bank‑rails AZ‑a path.
- ASM-13: No other callers of bank‑rails exist in the same AZ.
**Objections:**
- [blocking] gap_unaddressed: Network‑level metrics (packet loss, TCP retransmits) for the AZ‑a path between payments‑service and bank‑rails are not available via the observability tools.
- [blocking] alternative_not_excluded: HYP‑1 and HYP‑2 also fit the observations and have not been eliminated.

## Recommended actions

| Urgency | Kind | Action | Why |
|---|---|---|---|
| now | investigate | Retrieve bank‑rails per‑minute 5xx error‑rate and p99 latency for 2026‑10‑15T17:30‑18:00 UTC. | Directly tests HYP‑1’s prediction; the metrics are currently missing (GAP‑14‑16). (HYP-1) |
| now | investigate | Obtain change‑history records for payments‑service and bank‑rails covering 17:15‑18:00 UTC. | Needed to confirm or exclude a deploy/flag toggle (HYP‑2) and a secret rotation (HYP‑4); the backend is down (GAP‑9‑13). (HYP-2) |
| now | investigate | Obtain change‑history records for bank‑rails credential rotation in the same window. | Tests HYP‑4’s prediction of a scheduled API‑key/cert rotation; currently unavailable (GAP‑9‑13). (HYP-4) |
| soon | investigate | Collect network‑level metrics (packet loss, TCP retransmits) for the AZ‑a path between payments‑service and bank‑rails. | Validates or rules out HYP‑3; such metrics are not exposed by current observability (GAP‑3). (HYP-3) |
| soon | mitigate | Add real‑time alerting on bank‑rails latency exceeding 4 s and on 5xx error‑rate spikes. | Provides early warning for the failure mode described in HYP‑1 and HYP‑4. (HYP-1) |
| later | fix | Implement automatic credential reload in payments‑service on 4xx responses from bank‑rails. | Addresses the credential‑rotation failure mode (HYP‑4) and prevents stale‑credential outages. (HYP-4) |
| later | prevent | Enforce deployment verification (canary + health checks) for payments‑service and bank‑rails to catch regressions before they affect withdrawals. | Reduces risk of a code regression like HYP‑2 causing similar incidents. (HYP-2) |
| later | prevent | Deploy a circuit‑breaker / fallback path for withdrawal requests when bank‑rails latency or error‑rate exceeds thresholds. | Limits customer impact while downstream issues are resolved. (HYP-1) |

## Evidence gaps

- **get_change_history** (start=2026-10-15T17:00:00Z, end=2026-10-15T18:00:00Z): unavailable: get_change_history backend returned 503 Service Unavailable
- **query_metrics** (payments-service (all metrics 17:15‑18:00)): Request timed out after 10 s; no metric data returned.
- **query_metrics** (bank-rails, postgres-payments, edge-gateway (all metrics 17:15‑18:00)): Not queried due to step limit; needed to assess downstream health.
- **query_logs** (payments-service logs before 17:48 UTC): Log shards have expired; cannot see onset earlier than 17:48.
- **query_logs** (bank-rails logs (az‑a shard)): Shard unavailable; possible errors hidden.
- **query_logs** (service=payments-service, start=2026-10-15T17:15:00Z, end=2026-10-15T18:00:00Z): log shard for az-a is unavailable; results exclude pods in az-a; logs before 2026-10-15 17:48 UTC have expired and are not returned
- **query_metrics** (service=payments-service, start=2026-10-15T17:15:00Z, end=2026-10-15T18:00:00Z): timeout: query_metrics did not respond within 10s
- **query_logs** (service=bank-rails, start=2026-10-15T17:15:00Z, end=2026-10-15T18:00:00Z): log shard for az-a is unavailable; results exclude pods in az-a; logs before 2026-10-15 17:48 UTC have expired and are not returned
- **get_change_history** (payments-service, bank-rails, postgres-payments, edge-gateway (2026-10-15 17:15‑18:00 UTC)): Backend returned 503 and then was marked down; no change records could be retrieved for the investigation window.
- **get_change_history** (services=['payments-service', 'bank-rails', 'postgres-payments', 'edge-gateway'], start=2026-10-15T17:15:00Z, end=2026-10-15T18:00:00Z): unavailable: get_change_history backend returned 503 Service Unavailable
- **get_change_history** (services=['payments-service', 'bank-rails', 'postgres-payments', 'edge-gateway'], start=2026-10-15T17:15:00Z, end=2026-10-15T18:00:00Z): refused: get_change_history has failed 2 calls in a row; its backend is treated as down for the rest of this investigation
- **get_change_history** (payments-service 2026-10-15T17:15:00Z–2026-10-15T18:00:00Z): Backend refused after two consecutive failures; service marked down for the rest of the investigation.
- **get_change_history** (services=['payments-service'], start=2026-10-15T17:15:00Z, end=2026-10-15T18:00:00Z): refused: get_change_history has failed 2 calls in a row; its backend is treated as down for the rest of this investigation
- **query_metrics** (bank-rails per‑minute 5xx error‑rate and p99 latency for 2026-10-15T17:30:00Z–2026-10-15T18:00:00Z): First call timed out (call-0010); subsequent call refused because the backend was marked down (call-0011). No metric series IDs were returned.
- **query_metrics** (service=bank-rails): timeout: query_metrics did not respond within 10s
- **query_metrics** (service=bank-rails): refused: query_metrics has failed 2 calls in a row; its backend is treated as down for the rest of this investigation

## Open questions

- What were the bank‑rails 5xx error‑rate and p99 latency between 17:30‑18:00 UTC?
- Did a payments‑service deploy or feature‑flag change occur near 17:45 UTC?
- Was a bank‑rails API key or client certificate rotated in the 17:15‑18:00 window?
- Did the AZ‑a network path experience packet loss or TCP retransmit spikes during the incident?
- Why did the checkout endpoint also return 502 errors (OBS‑2) – shared cause or independent?

## How the investigation ran

Stopped because reached the limit of 2 rounds, after 2 round(s): 27 model calls, 11 tool calls, 102,346 tokens, 654 s.
