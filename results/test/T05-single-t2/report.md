# T05: Nobody can log in

**Outcome:** conclusive. Root cause: `certificate_or_credential` on **auth-service**

## Summary

At 06:00 UTC the TLS certificate used by auth-service expired (notAfter 2026-10-09T06:00:00Z). Both edge-gateway (client) and auth-service (server) immediately logged TLS‑handshake failures, causing a spike in edge‑gateway error_rate from 0.2 % to >11 % and 5xx on all POST /v1/session requests. The only production change in the preceding hour was an unrelated keep‑alive‑timeout increase on edge-gateway (chg:2541). No certificate‑rotation change was recorded. The root cause is a missed certificate rotation for auth-service.

## Hypotheses

### 1. `certificate_or_credential` on **auth-service** (HYP-1)

Confidence 0.95 (high). The auth-service server TLS certificate expired at 06:00Z. Clients (edge-gateway) attempting TLS handshakes receive an expired certificate, causing handshake failures logged on both sides. Failed handshakes translate to 5xx responses for session routes.

**Supporting:**
- edge-gateway logged 1,428 TLS handshake failures with message 'certificate has expired or is not yet valid (notAfter 2026-10-09T06:00:00Z)' starting at 06:00:09.657Z. (`log:6a1c72fa74da`)
- auth-service logged 1,112 TLS handshake errors 'remote error: tls: bad certificate' starting at 06:00:06.184Z. (`log:be1de505ee3a`)
- edge-gateway error_rate metric rose from a baseline of 0.0021 to 0.1166 (≈55×) by 06:30Z. (`metric:edge-gateway/error_rate`)
**Assumptions:**
- ASM-1: The notAfter timestamp in the TLS error messages reflects the actual expiry of the auth-service server certificate.
- ASM-2: No other component (gateway trust store, CA, load‑balancer) changed its certificate configuration at 06:00Z.

### 2. `config_change` on **edge-gateway**, triggered by `chg:2541` (HYP-2)

Confidence 0.02 (low). Increasing the upstream keepalive timeout altered connection pooling in a way that caused TLS validation to fail.

**Supporting:**
- The only change in the 05:00‑07:00 window for edge-gateway or auth-service was a config change on edge-gateway at 05:52:30Z raising upstream.keepalive_timeout_s from 60 to 75 (chg:2541). (`chg:2541`)
**Contradicting:**
- edge-gateway logged 1,428 TLS handshake failures with message 'certificate has expired or is not yet valid (notAfter 2026-10-09T06:00:00Z)' starting at 06:00:09.657Z. (`log:6a1c72fa74da`)
- auth-service logged 1,112 TLS handshake errors 'remote error: tls: bad certificate' starting at 06:00:06.184Z. (`log:be1de505ee3a`)
- edge-gateway rps, latency_p50, latency_p99, cpu_util, and mem_util remained within normal ranges throughout the window. (`metric:edge-gateway/rps`, `metric:edge-gateway/latency_p50_ms`, `metric:edge-gateway/latency_p99_ms`, `metric:edge-gateway/cpu_util`, `metric:edge-gateway/mem_util`)
**Assumptions:**
- ASM-3: Changing the keepalive timeout cannot cause TLS certificate validation failures.

### 3. `code_regression` on **auth-service** (HYP-3)

Confidence 0.02 (low). A recent (unrecorded) code change in auth-service introduced a bug that rejects valid client certificates, logging 'bad certificate'.

**Supporting:**
- auth-service logged 1,112 TLS handshake errors 'remote error: tls: bad certificate' starting at 06:00:06.184Z. (`log:be1de505ee3a`)
**Contradicting:**
- edge-gateway logged 1,428 TLS handshake failures with message 'certificate has expired or is not yet valid (notAfter 2026-10-09T06:00:00Z)' starting at 06:00:09.657Z. (`log:6a1c72fa74da`)
- The only change in the 05:00‑07:00 window for edge-gateway or auth-service was a config change on edge-gateway at 05:52:30Z raising upstream.keepalive_timeout_s from 60 to 75 (chg:2541). (`chg:2541`)
- edge-gateway rps, latency_p50, latency_p99, cpu_util, and mem_util remained within normal ranges throughout the window. (`metric:edge-gateway/rps`, `metric:edge-gateway/latency_p50_ms`, `metric:edge-gateway/latency_p99_ms`, `metric:edge-gateway/cpu_util`, `metric:edge-gateway/mem_util`)
**Assumptions:**
- ASM-4: A code regression in auth-service would not produce the exact 'certificate has expired' message.

### 4. `infrastructure_failure` on **platform** (HYP-4)

Confidence 0.01 (low). An infrastructure‑level CA or certificate store expired, affecting both gateway and auth-service.

**Supporting:**
- edge-gateway logged 1,428 TLS handshake failures with message 'certificate has expired or is not yet valid (notAfter 2026-10-09T06:00:00Z)' starting at 06:00:09.657Z. (`log:6a1c72fa74da`)
- auth-service logged 1,112 TLS handshake errors 'remote error: tls: bad certificate' starting at 06:00:06.184Z. (`log:be1de505ee3a`)
**Contradicting:**
- The only change in the 05:00‑07:00 window for edge-gateway or auth-service was a config change on edge-gateway at 05:52:30Z raising upstream.keepalive_timeout_s from 60 to 75 (chg:2541). (`chg:2541`)
- edge-gateway rps, latency_p50, latency_p99, cpu_util, and mem_util remained within normal ranges throughout the window. (`metric:edge-gateway/rps`, `metric:edge-gateway/latency_p50_ms`, `metric:edge-gateway/latency_p99_ms`, `metric:edge-gateway/cpu_util`, `metric:edge-gateway/mem_util`)
**Assumptions:**
- ASM-5: A shared CA expiry would show the same notAfter on both client and server logs, which is not observed.

## Recommended actions

| Urgency | Kind | Action | Why |
|---|---|---|---|
| now | fix | Deploy a renewed TLS certificate to auth-service and reload/restart the service. | Eliminates the expired certificate causing handshake failures (addresses hypothesis h1). |
| now | mitigate | Verify edge-gateway trust store contains the new certificate/CA and, if needed, update it. | Ensures gateway accepts the renewed cert; prevents continued 5xx. |
| soon | fix | Run synthetic login and token‑refresh tests through edge-gateway to confirm error_rate returns to baseline (<0.5%). | Validates end‑to‑end restoration of the session path. |
| later | prevent | Add certificate‑expiry monitoring alerts (30‑day, 7‑day, 1‑day) for all services using mTLS. | Detects upcoming expirations before they cause outages. |
| later | prevent | Record the certificate renewal as a secret_rotation change in the change‑history system and enforce a mandatory rotation workflow. | Closes gap G1 and provides audit trail for future incidents. |
| later | investigate | Investigate why AZ‑b log shards were unavailable during the incident and remediate logging coverage. | Removes gap G2 for future visibility. |

## Evidence gaps

- **get_change_history** (auth-service secret_rotation or certificate renewal): No secret_rotation change record found for auth-service before 06:00Z; expected a chg: entry for certificate renewal.
- **query_logs** (AZ‑b log shards for edge-gateway and auth-service): Log shard for az-b was unavailable, potentially hiding early warnings or a partial rollout.
- **query_metrics** (auth-service TLS handshake failure counters): No auth-service metrics were queried; would help quantify impact on the auth side.
- **inspect_certificate** (auth-service server certificate details): Direct certificate inspection (e.g., openssl) not available via current tooling to confirm expiry and SANs.
- **query_logs** (service=edge-gateway, start=2026-10-09T05:15:00Z, end=2026-10-09T06:30:00Z): log shard for az-b is unavailable; results exclude pods in az-b
- **query_logs** (service=auth-service, start=2026-10-09T05:15:00Z, end=2026-10-09T06:30:00Z): log shard for az-b is unavailable; results exclude pods in az-b

## Open questions

- Who owns the certificate lifecycle for auth-service and why was the rotation missed?
- Was the certificate stored in a secret manager that failed to rotate automatically?
- Did any other internal services that call auth-service experience failures not captured in the current logs?
- Why were AZ‑b log shards unavailable at the time of the incident?

## How the investigation ran

Stopped because the agent finished its investigation, after 1 round(s): 7 model calls, 5 tool calls, 43,714 tokens, 242 s.
