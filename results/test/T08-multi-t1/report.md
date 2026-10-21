# T08: Deposits and checkout failing overnight

**Outcome:** conclusive. Root cause: `certificate_or_credential` on **postgres-payments**, triggered by `chg:2581`

## Summary

Deposits and checkout began failing around 02:00 UTC with a rapidly rising 5xx error rate. The investigation concluded (conclusive) that the vault secret rotation for the postgres‑payments database at 02:00:05 UTC (v31→v32) changed the DB password while payments‑service pods continued using the stale credential, producing “password authentication failed” errors that surface as 500/502 on /v1/checkout and /v1/deposits (HYP‑1, confidence 0.78). Earlier 504s on /v1/withdrawals at 01:34 remain unexplained but are not the primary cause of the later outage. The exact mechanism of credential refresh in the pods and the root cause of the early 504s are still unknown.

## Hypotheses

### 1. `certificate_or_credential` on **postgres-payments**, triggered by `chg:2581` (HYP-1)

Confidence 0.78 (high), critic: accept. The vault secret rotation at 02:00:05 UTC changed the DB password (v31→v32). Payments‑service pods continued using the stale password for a short window, causing “password authentication failed” errors that surface as 500/502 on /v1/checkout and /v1/deposits. Edge‑gateway forwards those upstream 5xx responses.

**Supporting:**
- payments‑service logs show 788 “could not open connection to postgres‑payments: FATAL: password authentication failed for user “payments_app”” errors, first seen at 2026‑10‑13T02:02:05.222Z and last seen at 2026‑10‑13T02:34:53.178Z. (`log:07bf0979f12c`)
- postgres‑payments logs show 865 “FATAL: password authentication failed for user “payments_app”” errors, first seen at 2026‑10‑13T02:02:00.662Z and last seen at 2026‑10‑13T02:34:57.135Z. (`log:94d1aef944ce`)
- The secret rotation for postgres‑payments (db password version v31→v32) occurred at 2026‑10‑13T02:00:05 UTC (change‑census OBS‑2). (`chg:2581`)
- Edge-gateway logged upstream payments-service 500 responses on route /v1/checkout starting at 2026-10-13T02:03:01Z, totaling 196 occurrences by 02:34:57Z. (`log:ca1979ec42e9`)
- POST /v1/checkout 502 errors first appear at 2026-10-13T02:05:08Z and continue until 02:09:55Z (8 occurrences). (`log:d4f8251184e5`)
- POST /v1/deposits 500 errors first appear at 2026-10-13T02:07:15Z and continue until 02:09:22Z (7 occurrences). (`log:b216857f9fa5`)
- payments‑service db_pool_in_use dropped from 6.4 connections at 01:30 to 2.0 at 02:30 (baseline 5.94). (`metric:payments-service/db_pool_in_use`)
**Contradicting:**
- The secret rotation on postgres-payments occurred at 02:00:05, after the reported failure start (~02:00), so it cannot explain the initial spike. (`chg:2581`)
**Assumptions:**
- ASM-5: Payments‑service reads the DB password only at start‑up or via a periodic Vault‑agent refresh (≈30‑60 s). The rotation at 02:00:05 therefore leaves a window of stale credentials.
- ASM-6: The on‑call’s “failure start ~02:00” is an approximation; the first instrumented error appears at 02:02 in the logs.
**Objections:**
- [minor] gap_unaddressed: The mechanism assumes payments‑service pods continue using the stale password until a reload/restart; no direct evidence (pod restart or credential‑refresh logs) has been shown.

### 2. `dependency_degradation` on **bank-rails** (HYP-2)

Confidence 0.18 (low), critic: reject. An unobserved latency spike or saturation in bank‑rails began before 01:38, pushing calls past the 4 s client timeout (hence the 504s on /v1/withdrawals at 01:34). The timeout was raised to 5 s at 01:38, but latency remained high, eventually exhausting payments‑service thread pools and turning into 500/502 on checkout and deposits.

**Supporting:**
- payments‑service logs a 504 error pattern (“POST /v1/withdrawals 504 88ms”) beginning at 2026‑10‑13T01:34:34.566Z, before the bank‑rails timeout config change at 01:38:20 UTC, and persisting through the incident. (`log:9a103e61f521`)
- payments-service has a hard dependency on bank-rails via HTTPS with a configured timeout of 4000 ms (dep:payments-service->bank-rails). (`dep:payments-service->bank-rails`)
- The bank‑rails client timeout on payments‑service was raised from 4000 ms to 5000 ms at 2026‑10‑13T01:38:20 UTC (change‑census OBS‑1). (`chg:2578`)
- No changes (deploy, config, feature‑flag, secret, infra) recorded for bank-rails or edge-gateway between 01:00 and 02:35 UTC. (`chg:2578`, `chg:2581`)
**Contradicting:**
- payments‑service logs show 788 “could not open connection to postgres‑payments: FATAL: password authentication failed for user “payments_app”” errors, first seen at 2026‑10‑13T02:02:05.222Z and last seen at 2026‑10‑13T02:34:53.178Z. (`log:07bf0979f12c`)
- postgres‑payments logs show 865 “FATAL: password authentication failed for user “payments_app”” errors, first seen at 2026‑10‑13T02:02:00.662Z and last seen at 2026‑10‑13T02:34:57.135Z. (`log:94d1aef944ce`)
- Edge-gateway logged upstream payments-service 500 responses on route /v1/checkout starting at 2026-10-13T02:03:01Z, totaling 196 occurrences by 02:34:57Z. (`log:ca1979ec42e9`)
- payments‑service db_pool_in_use dropped from 6.4 connections at 01:30 to 2.0 at 02:30 (baseline 5.94). (`metric:payments-service/db_pool_in_use`)
**Assumptions:**
- ASM-7: Bank‑rails may have suffered a short‑lived latency spike not captured by the default metrics (e.g., a single‑node GC pause).
- ASM-8: Payments‑service error handling translates any downstream timeout (bank‑rails) into a generic 500 after the timeout increase.
**Objections:**
- [blocking] ignores_contradiction: Observations OBS‑9, OBS‑10, OBS‑14, and OBS‑23 show abundant DB authentication failures and a dropping db_pool_in_use, which directly oppose a bank‑rails latency‑driven thread‑pool exhaustion scenario.

### 3. `config_change` on **edge-gateway** (HYP-3)

Confidence 0.08 (low), critic: reject. An undocumented change to edge‑gateway retry/back‑off or circuit‑breaker settings amplified upstream 500s into a higher error‑rate, even though no timeout logs appear.

**Supporting:**
- Edge-gateway error_rate metric rose from 0.0034 at 01:15 to 0.0193 at 02:35 (≈10× the baseline of 0.00196). (`metric:edge-gateway/error_rate`)
- Edge-gateway latency_p99_ms increased from a baseline of 349.5 ms to 431.7 ms at period end (peak 432.8 ms). (`metric:edge-gateway/latency_p99_ms`)
**Contradicting:**
- No edge-gateway log entries containing the word “timeout” were found in the 01:15–02:35 window, indicating no client‑side timeout events were recorded. (`log:0d4fbbb98f6d`)
- Edge-gateway logged upstream payments-service 500 responses on route /v1/checkout starting at 2026-10-13T02:03:01Z, totaling 196 occurrences by 02:34:57Z. (`log:ca1979ec42e9`)
- No changes (deploy, config, feature‑flag, secret, infra) recorded for bank-rails or edge-gateway between 01:00 and 02:35 UTC. (`chg:2578`, `chg:2581`)
**Assumptions:**
- ASM-4: A recent, unrecorded change to edge‑gateway retry/back‑off or circuit‑breaker settings could amplify upstream errors.
**Objections:**
- [blocking] alternative_not_excluded: HYP‑1 provides a fully evidenced explanation for the 5xx responses; HYP‑3 remains viable only if HYP‑1 is ruled out, which it is not.

## Recommended actions

| Urgency | Kind | Action | Why |
|---|---|---|---|
| now | mitigate | Roll back the postgres‑payments password to version v31 or restart all payments‑service pods so they pick up the new secret (v32). | Immediately restores DB connectivity and stops the 5xx flood on checkout and deposits. (HYP-1) |
| soon | fix | Configure payments‑service (or its deployment) to automatically reload database credentials on secret rotation, e.g., via a Vault Agent sidecar or a reload‑on‑signal mechanism. | Eliminates the window where pods run with a stale password after future rotations. (HYP-1) |
| later | prevent | Add a health‑check that validates DB authentication (not just liveness) and alert on authentication‑failure spikes; enforce automated pod restart on secret‑change events. | Detects and self‑heals credential‑mismatch incidents before they impact customers. (HYP-1) |
| soon | investigate | Determine why payments‑service pods did not refresh the DB password after the vault rotation (review pod spec, Vault Agent config, and any credential‑caching logic). | Closes the evidence gap about the stale‑credential window (critic objection). (HYP-1) |
| later | investigate | Analyse the early 504 errors on POST /v1/withdrawals starting at 01:34 (before the secret rotation) to establish whether a bank‑rails latency spike or other dependency issue occurred. | Addresses the unexplained pre‑incident symptom and rules out a concurrent bank‑rails degradation (HYP‑2). (HYP-2) |

## Evidence gaps

- **get_change_history** (bank-rails, edge-gateway): Change census returned only two changes; any config‑map, feature‑flag, or infra work on these two services in the window is not captured.
- **get_service_dependencies** (bank-rails upstream dependencies): Only downstream deps from payments-service and edge-gateway were retrieved; bank-rails internal circuit‑breaker or pool settings are not visible.
- **query_metrics** (payments-service bank-rails client latency, timeout count, error rate): Metrics not queried; needed to confirm whether the 01:38 timeout increase correlates with any change in bank‑rails call performance.
- **query_metrics** (bank-rails request latency, error rate, saturation (CPU, connections)): No metrics retrieved; bank‑rails logs show no errors, but latency or saturation could cause upstream 504s.
- **query_logs** (payments-service DEBUG/INFO logs for bank‑rails client (e.g., retry, timeout messages)): Only WARN+ patterns were fetched; lower‑level logs may contain explicit timeout or circuit‑breaker events.
- **query_logs** (edge-gateway retry/timeout configuration or explicit retry log lines): Log search for “timeout” returned zero patterns; retry logic would not appear unless explicitly logged. Configuration audit not captured by current tooling.
- **query_logs** (payments-service error/exception logs for the same window): Payments-service logs were not queried; needed to confirm upstream failure cause.
- **query_metrics** (payments-service error_rate (and endpoint‑level error rates) for 01:55‑02:10 UTC): Metric endpoint not queried; only log patterns available, so exact per‑minute error rates cannot be plotted.
- **query_metrics** (bank-rails p99 latency, error_rate, cpu_util, connection‑pool metrics): No metric series were returned for bank-rails in the requested window.
- **query_metrics** (payments-service bank_rails_client_timeout_count and circuit_breaker_open_close events): These custom metrics are not present in the available metric list for payments-service.

## Open questions

- Do payments‑service pods automatically reload the rotated database secret, or is a restart required?
- What caused the 504 errors on /v1/withdrawals at 01:34 UTC, prior to the secret rotation?
- Were there any unrecorded configuration or infrastructure changes on bank‑rails or edge‑gateway in the 01:00‑02:35 window?
- What are the exact bank‑rails latency, timeout, and circuit‑breaker metrics during the incident window?

## How the investigation ran

Stopped because the critic accepted HYP-1, after 2 round(s): 31 model calls, 16 tool calls, 135,212 tokens, 948 s.
