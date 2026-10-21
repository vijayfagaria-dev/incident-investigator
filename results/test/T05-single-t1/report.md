# T05: Nobody can log in

**Outcome:** conclusive. Root cause: `certificate_or_credential` on **auth-service**

## Summary

The internal TLS certificate used by auth‑service expired at 2026‑10‑09T06:00:00Z. Edge‑gateway, which calls auth‑service over a hard‑dependency HTTP/TLS link (1 s timeout), began rejecting every request with “x509: certificate has expired”. This caused a total loss of POST /v1/session and token‑refresh traffic (edge‑gateway 5xx, auth‑service request rate collapsed). The only production change in the window was an unrelated edge‑gateway keep‑alive config tweak at 05:52 Z; it did not cause the failure. No deploy, secret rotation, or infra work touched the certificate. A previous incident (pir:2025‑040) had the exact same mechanism.

## Hypotheses

### 1. `certificate_or_credential` on **auth-service** (HYP-1)

Confidence 0.96 (high). The internal TLS certificate presented by auth‑service expired at 06:00 UTC. Edge‑gateway validates the cert on every upstream request; handshake failures are logged as “certificate has expired” and returned as 5xx, causing all login/token‑refresh requests to fail.

**Supporting:**
- Edge‑gateway logs show TLS handshake with auth‑service failed: certificate expired (notAfter 2026‑10‑09T06:00:00Z) starting 06:00:09.657 Z, 1 428 occurrences. (`log:6a1c72fa74da`)
- Auth‑service logs show TLS handshake error “remote error: tls: bad certificate” starting 06:00:06.184 Z, 1 112 occurrences. (`log:be1de505ee3a`)
- Edge‑gateway error_rate rose from baseline 0.0021 to a mean of 0.0556 and 0.1166 at the end of the window. (`metric:edge-gateway/error_rate`)
- Auth‑service request rate dropped from ~98 req/s to ~7.8 req/s while error_rate, latency, CPU and memory stayed at baseline. (`metric:auth-service/rps`, `metric:auth-service/error_rate`, `metric:auth-service/latency_p50_ms`, `metric:auth-service/cpu_util`, `metric:auth-service/mem_util`)
- Past incident pir:2025‑040 (Aug 2025) shows identical symptom: expired internal TLS cert on auth‑service caused edge‑gateway “x509: certificate has expired” and total login outage. (`pir:2025-040`)
**Assumptions:**
- ASM-1: The `notAfter` timestamp logged by edge‑gateway reflects the true certificate expiration time.
- ASM-2: Edge‑gateway treats the auth‑service TLS cert as a hard dependency (1 s timeout); any handshake failure becomes a 5xx to the client.
- ASM-3: No other concurrent change (secret rotation, deploy, infra) affected the certificate.

### 2. `config_change` on **edge-gateway**, triggered by `chg:2541` (HYP-2)

Confidence 0.04 (low). Increasing the upstream keep‑alive timeout caused stale connections that presented an expired certificate, leading to handshake failures.

**Supporting:**
- Only production change in the window: edge‑gateway config keep‑alive timeout changed 60 → 75 s at 05:52:30 Z. (`chg:2541`)
**Contradicting:**
- Edge‑gateway logs show TLS handshake with auth‑service failed: certificate expired (notAfter 2026‑10‑09T06:00:00Z) starting 06:00:09.657 Z, 1 428 occurrences. (`log:6a1c72fa74da`)
- Auth‑service logs show TLS handshake error “remote error: tls: bad certificate” starting 06:00:06.184 Z, 1 112 occurrences. (`log:be1de505ee3a`)
- Edge‑gateway error_rate rose from baseline 0.0021 to a mean of 0.0556 and 0.1166 at the end of the window. (`metric:edge-gateway/error_rate`)
- Auth‑service request rate dropped from ~98 req/s to ~7.8 req/s while error_rate, latency, CPU and memory stayed at baseline. (`metric:auth-service/rps`, `metric:auth-service/error_rate`, `metric:auth-service/latency_p50_ms`, `metric:auth-service/cpu_util`, `metric:auth-service/mem_util`)
**Assumptions:**
- ASM-4: The keep‑alive timeout change cannot alter certificate validity.

### 3. `code_regression` on **auth-service** (HYP-3)

Confidence 0.02 (low). A recent (unrecorded) deploy introduced a bug that serves an expired certificate.

**Contradicting:**
- Only production change in the window: edge‑gateway config keep‑alive timeout changed 60 → 75 s at 05:52:30 Z. (`chg:2541`)
**Assumptions:**
- ASM-5: No undocumented deploy to auth‑service occurred.

### 4. `infrastructure_failure` on **auth-service** (HYP-4)

Confidence 0.01 (low). Clock drift on auth‑service nodes made a still‑valid cert appear expired.

**Contradicting:**
- Edge‑gateway logs show TLS handshake with auth‑service failed: certificate expired (notAfter 2026‑10‑09T06:00:00Z) starting 06:00:09.657 Z, 1 428 occurrences. (`log:6a1c72fa74da`)
- Auth‑service logs show TLS handshake error “remote error: tls: bad certificate” starting 06:00:06.184 Z, 1 112 occurrences. (`log:be1de505ee3a`)
**Assumptions:**
- ASM-6: Clock‑skew would not produce a log line that quotes the certificate’s own `notAfter` field.

## Recommended actions

| Urgency | Kind | Action | Why |
|---|---|---|---|
| now | fix | Replace the expired internal TLS certificate on auth‑service (push new cert via secret‑management pipeline and restart pods). | Restores TLS handshakes; immediate fix for the outage. |
| soon | mitigate | Add a health‑check endpoint that performs a TLS handshake to the auth‑service internal endpoint (or validates cert expiry) so readiness fails before cert expiry. | Prevents future “healthy pods but bad cert” situation. |
| soon | prevent | Enable automated certificate issuance/renewal (cert‑manager, Vault PKI, etc.) for auth‑service and set alerts ≥ 14 days before expiry. | Eliminates manual expiry risk; aligns with prior postmortem recommendation. |
| later | prevent | Audit all internal service‑to‑service TLS certs for expiration dates and automation coverage. | Broadens protection beyond auth‑service. |
| later | investigate | Post‑mortem: document the gap in cert‑lifecycle automation, update runbooks, and add a “certificate expiry” runbook step to the on‑call playbook. | Institutional learning, prevents recurrence. |

## Evidence gaps

- **query_logs** (Auth‑service startup logs around 05:55 Z (AZ‑b shard unavailable)): Missing shard may hide early certificate‑load messages.
- **secret_store_inspection** (Current certificate details (CN, issuer, serial, notAfter) for auth‑service internal TLS cert): Direct cert inspection not available via current tooling.
- **cert_manager_status** (Automation coverage for auth‑service certificates): Need to verify why automated renewal did not replace the expired cert.
- **query_logs** (service=edge-gateway, start=2026-10-09T05:30:00Z, end=2026-10-09T06:30:00Z): log shard for az-b is unavailable; results exclude pods in az-b
- **query_logs** (service=auth-service, start=2026-10-09T05:30:00Z, end=2026-10-09T06:30:00Z): log shard for az-b is unavailable; results exclude pods in az-b

## Open questions

- What exact certificate (CN, issuer, serial) expired? Confirm via secret store once access is restored.
- Why was this certificate not covered by the automated renewal that was supposedly put in place after pir:2025‑040?
- Could any client‑side (mobile/web) caching of the failed handshake prolong perceived outage after the cert is rotated?

## How the investigation ran

Stopped because the agent finished its investigation, after 1 round(s): 10 model calls, 8 tool calls, 69,209 tokens, 233 s.
