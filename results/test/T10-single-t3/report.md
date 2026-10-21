# T10: Withdrawals failing

**Outcome:** conclusive. Root cause: `dependency_degradation` on **bank-rails**

## Summary

At ~17:48 UTC payments-service began logging “withdrawal … failed: bank‑rails call returned an error”. The error appeared 44 times over ~12 minutes on pods in two availability zones. The withdrawal path has a hard HTTPS dependency on the external bank‑rails service (4 s timeout). No logs, metrics, or change‑history data are available for the window, and bank‑rails logs show no entries. The most likely cause is a degradation/outage of bank‑rails, though a recent payments‑service deploy, config change, or shared network failure cannot be ruled out.

## Hypotheses

### 1. `dependency_degradation` on **bank-rails** (HYP-1)

Confidence 0.78 (high). bank‑rails becomes unavailable or returns errors; payments-service's hard dependency propagates the failure to withdrawal calls.

**Supporting:**
- payments-service began logging withdrawal failures referencing bank‑rails at 2026-10-15T17:48:12Z (`log:33df62f69e8a`)
- The same error appears 44 times between 17:48:12 and 17:59:37 on pods in az‑b and az‑c (`log:33df62f69e8a`)
- payments-service → bank‑rails is a hard HTTPS dependency with a 4 s timeout (`dep:payments-service->bank-rails`)
**Assumptions:**
- ASM-1: Withdrawal endpoint calls bank‑rails synchronously; a failure there surfaces as the logged error
- ASM-2: Deposit processing does not depend on bank‑rails (or uses a different provider)

### 2. `code_regression` on **payments-service** (HYP-2)

Confidence 0.15 (low). A recent code deploy introduced a bug that mishandles bank‑rails responses, causing all withdrawals to fail.

**Supporting:**
- payments-service began logging withdrawal failures referencing bank‑rails at 2026-10-15T17:48:12Z (`log:33df62f69e8a`)
- The same error appears 44 times between 17:48:12 and 17:59:37 on pods in az‑b and az‑c (`log:33df62f69e8a`)
**Assumptions:**
- ASM-3: A payments‑service deploy could have occurred just before 17:48 but was not captured by change‑history

### 3. `infrastructure_failure` on **infrastructure** (HYP-4)

Confidence 0.12 (low). A network‑level issue (DNS, firewall, TLS cert) blocks connectivity from the cluster to bank‑rails, affecting all pods in az‑b and az‑c.

**Supporting:**
- payments-service began logging withdrawal failures referencing bank‑rails at 2026-10-15T17:48:12Z (`log:33df62f69e8a`)
- The same error appears 44 times between 17:48:12 and 17:59:37 on pods in az‑b and az‑c (`log:33df62f69e8a`)
- payments-service → bank‑rails is a hard HTTPS dependency with a 4 s timeout (`dep:payments-service->bank-rails`)
**Assumptions:**
- ASM-5: The network path to bank‑rails is shared across az‑b and az‑c; a single network event would affect both

### 4. `config_change` on **payments-service** (HYP-3)

Confidence 0.10 (low). A configuration change (e.g., wrong bank‑rails endpoint, timeout, or auth token) makes every bank‑rails call fail.

**Supporting:**
- payments-service began logging withdrawal failures referencing bank‑rails at 2026-10-15T17:48:12Z (`log:33df62f69e8a`)
- The same error appears 44 times between 17:48:12 and 17:59:37 on pods in az‑b and az‑c (`log:33df62f69e8a`)
- payments-service → bank‑rails is a hard HTTPS dependency with a 4 s timeout (`dep:payments-service->bank-rails`)
**Assumptions:**
- ASM-4: A config push (e.g., new bank‑rails URL or credentials) could have been applied just before 17:48 but is not recorded

## Recommended actions

| Urgency | Kind | Action | Why |
|---|---|---|---|
| now | investigate | Contact bank‑rails vendor / check their status page for any incident or maintenance at ~17:48 UTC | Directly tests H1 (bank‑rails degradation) |
| now | investigate | From a test pod, run HTTPS request to bank‑rails endpoint and capture status code, latency, and error body | Confirms whether bank‑rails is reachable and returning errors |
| soon | investigate | Retrieve change‑history from CI/CD or GitOps system once backend recovers to verify any payments‑service deploy or config change before 17:48 | Discriminates H2 and H3 |
| soon | investigate | Pull payments‑service metrics (error rate, latency, saturation) from monitoring UI for 17:30‑18:00 | Shows whether the service itself became saturated (resource_exhaustion) or only downstream calls failed |
| later | mitigate | Add a circuit‑breaker / fast‑fail fallback around the bank‑rails call (e.g., queue withdrawal for retry) | Reduces impact of future bank‑rails outages |
| later | prevent | Instrument payments-service to log HTTP status code and response body from bank‑rails | Provides observable evidence for future incidents |
| later | prevent | Document bank‑rails as a single‑point‑of‑failure and evaluate a secondary withdrawal provider | Addresses hard dependency identified in F4 |

## Evidence gaps

- **get_change_history** (payments-service, bank-rails, infrastructure (17:15‑18:00 UTC)): Backend returned 503; no deploy, config, feature‑flag, secret, or infra change records available
- **query_metrics** (payments-service (17:15‑18:00 UTC)): Metrics backend timed out and is marked down; error‑rate, latency, saturation data missing
- **query_logs** (bank-rails (17:15‑18:00 UTC)): Zero log matches; bank‑rails may not emit logs we can ingest
- **query_logs** (payments-service before 17:48 UTC): Log shards expired; early onset data unavailable
- **query_logs** (deposit path services): Deposits reported fine but no logs/metrics examined to confirm
- **query_logs** (service=payments-service, start=2026-10-15T17:15:00Z, end=2026-10-15T18:00:00Z): log shard for az-a is unavailable; results exclude pods in az-a; logs before 2026-10-15 17:48 UTC have expired and are not returned
- **query_metrics** (service=payments-service, start=2026-10-15T17:15:00Z, end=2026-10-15T18:00:00Z): timeout: query_metrics did not respond within 10s
- **query_metrics** (service=payments-service): refused: query_metrics has failed 2 calls in a row; its backend is treated as down for the rest of this investigation
- **get_change_history** (services=['payments-service', 'bank-rails'], start=2026-10-15T17:15:00Z, end=2026-10-15T18:00:00Z): unavailable: get_change_history backend returned 503 Service Unavailable
- **query_logs** (service=bank-rails, start=2026-10-15T17:15:00Z, end=2026-10-15T18:00:00Z): log shard for az-a is unavailable; results exclude pods in az-a; logs before 2026-10-15 17:48 UTC have expired and are not returned
- **query_logs** (service=payments-service, start=2026-10-15T17:40:00Z, end=2026-10-15T18:00:00Z): log shard for az-a is unavailable; results exclude pods in az-a; logs before 2026-10-15 17:48 UTC have expired and are not returned
- **get_change_history** (start=2026-10-15T17:15:00Z, end=2026-10-15T18:00:00Z): unavailable: get_change_history backend returned 503 Service Unavailable

## Open questions

- Did bank‑rails have a known maintenance window or outage at 17:48 UTC?
- Was a payments‑service deploy or config change pushed just before 17:48 UTC that the change‑history service missed?
- Do deposit flows truly bypass bank‑rails, or do they use a different endpoint that remained healthy?
- What does the network path (DNS, TLS, firewall) look like between the cluster and bank‑rails; any recent infra changes?
- Can we add client‑side logging of bank‑rails HTTP responses for faster triage next time?

## How the investigation ran

Stopped because the agent finished its investigation, after 1 round(s): 11 model calls, 9 tool calls, 68,426 tokens, 402 s.
