# T05: Nobody can log in

**Outcome:** conclusive. Root cause: `certificate_or_credential` on **auth-service**

## Summary

At 06:00 UTC the TLS certificate used by auth‑service expired (notAfter 2026‑10‑09T06:00:00Z). edge‑gateway has a hard HTTP‑TLS dependency on auth‑service, so every login/token‑refresh request (POST /v1/session) began failing with TLS handshake errors, producing a >10 % error‑rate on the gateway. The gateway config change at 05:52 (keep‑alive timeout) is unrelated.

## Hypotheses

### 1. `certificate_or_credential` on **auth-service** (HYP-1)

Confidence 0.94 (high). The TLS certificate presented by auth‑service expired at 06:00 UTC. edge‑gateway, which requires a valid TLS handshake for its hard dependency, immediately began failing every request to auth‑service, resulting in 5xx on /v1/session and a spike in gateway error‑rate.

**Supporting:**
- edge‑gateway calls auth‑service over HTTP with a hard dependency (timeout 1 s). (`dep:edge-gateway->auth-service`)
- From 06:00:09 UTC edge‑gateway logs show 1 428 TLS handshake failures: “certificate has expired or is not yet valid (notAfter 2026‑10‑09T06:00:00Z)”. (`log:6a1c72fa74da`)
- auth‑service logs show matching peer errors “remote error: tls: bad certificate” from 06:00:06 UTC onward (1 112 occurrences). (`log:be1de505ee3a`)
- edge‑gateway error‑rate jumps from a baseline 0.2 % to a mean 7.3 % (last 11.6 % at 06:30). (`metric:edge-gateway/error_rate`)
**Assumptions:**
- ASM-1: The “notAfter 2026‑10‑09T06:00:00Z” timestamp in the TLS error accurately reflects the certificate’s expiry time.
- ASM-2: No hidden secret‑rotation or certificate‑renewal job occurred that the change‑history API missed.

### 2. `config_change` on **edge-gateway**, triggered by `chg:2541` (HYP-2)

Confidence 0.04 (low). The keep‑alive timeout increase caused downstream connections to stay open longer, leading to timeouts that manifest as 5xx on session routes.

**Supporting:**
- A config change on edge‑gateway at 05:52:30 UTC raised upstream keep‑alive timeout from 60 s to 75 s. (`chg:2541`)
**Contradicting:**
- From 06:00:09 UTC edge‑gateway logs show 1 428 TLS handshake failures: “certificate has expired or is not yet valid (notAfter 2026‑10‑09T06:00:00Z)”. (`log:6a1c72fa74da`)
- auth‑service logs show matching peer errors “remote error: tls: bad certificate” from 06:00:06 UTC onward (1 112 occurrences). (`log:be1de505ee3a`)
- edge‑gateway error‑rate jumps from a baseline 0.2 % to a mean 7.3 % (last 11.6 % at 06:30). (`metric:edge-gateway/error_rate`)
**Assumptions:**
- ASM-3: Raising the gateway keep‑alive timeout cannot cause TLS handshake failures.

### 3. `dependency_degradation` on **auth-service** (HYP-3)

Confidence 0.01 (low). auth‑service became unhealthy (e.g., process crash) despite passing health checks, causing gateway failures.

**Supporting:**
- edge‑gateway calls auth‑service over HTTP with a hard dependency (timeout 1 s). (`dep:edge-gateway->auth-service`)
**Contradicting:**
- From 06:00:09 UTC edge‑gateway logs show 1 428 TLS handshake failures: “certificate has expired or is not yet valid (notAfter 2026‑10‑09T06:00:00Z)”. (`log:6a1c72fa74da`)
- auth‑service logs show matching peer errors “remote error: tls: bad certificate” from 06:00:06 UTC onward (1 112 occurrences). (`log:be1de505ee3a`)
- Responder notes that auth‑service pods are up and health checks pass. (`log:be1de505ee3a`)
**Assumptions:**
- ASM-4: Health‑check endpoint for auth‑service does not validate the TLS server certificate.

### 4. `infrastructure_failure` on **infrastructure** (HYP-4)

Confidence 0.01 (low). A network‑level TLS interception or certificate validation change broke the handshake for all callers.

**Supporting:**
- From 06:00:09 UTC edge‑gateway logs show 1 428 TLS handshake failures: “certificate has expired or is not yet valid (notAfter 2026‑10‑09T06:00:00Z)”. (`log:6a1c72fa74da`)
- auth‑service logs show matching peer errors “remote error: tls: bad certificate” from 06:00:06 UTC onward (1 112 occurrences). (`log:be1de505ee3a`)
**Contradicting:**
- No secret‑rotation, deploy, or other config changes for auth‑service or edge‑gateway in the 05:00‑07:00 window (only chg:2541). (`chg:2541`)
- edge‑gateway error‑rate jumps from a baseline 0.2 % to a mean 7.3 % (last 11.6 % at 06:30). (`metric:edge-gateway/error_rate`)
**Assumptions:**
- ASM-5: No infrastructure change (network policy, TLS termination) occurred in the window.

## Recommended actions

| Urgency | Kind | Action | Why |
|---|---|---|---|
| now | fix | Replace the expired TLS certificate on auth‑service and restart affected pods. | Directly eliminates the handshake failure identified as root cause (H1). |
| now | mitigate | Validate that edge‑gateway logs no longer show TLS handshake errors and that POST /v1/session returns 200 for test accounts. | Confirms the fix propagates through the hard dependency. |
| soon | prevent | Add certificate‑expiry monitoring alerts (30‑day, 7‑day, 1‑day) for all identity‑service certificates. | Prevents future time‑based expirations from causing outages. |
| soon | prevent | Automate certificate rotation (e.g., cert‑manager or secret‑rotation pipeline) so no manual step is required. | Removes human‑process gap that allowed the cert to expire. |
| later | prevent | Extend auth‑service health check to perform a TLS handshake or verify cert notAfter > now. | Makes future cert expirations visible to the health‑check system. |
| later | prevent | Ensure secret/cert rotation events are recorded in the change‑history feed. | Closes visibility gap (G2) for future investigations. |

## Evidence gaps

- **query_logs** (AZ‑b pods for edge‑gateway and auth‑service): Log shard for AZ‑b unavailable; results exclude those pods.
- **get_change_history** (Certificate rotation jobs for auth‑service): Change‑history API does not surface secret/cert rotation events; cannot confirm if a rotation was attempted.
- **query_metrics** (auth‑service TLS handshake success/failure counters): No metric series exposed for TLS handshake outcome; only gateway error‑rate available.
- **query_logs** (service=edge-gateway, start=2026-10-09T05:45:00Z, end=2026-10-09T06:30:00Z): log shard for az-b is unavailable; results exclude pods in az-b
- **query_logs** (service=auth-service, start=2026-10-09T05:45:00Z, end=2026-10-09T06:30:00Z): log shard for az-b is unavailable; results exclude pods in az-b

## Open questions

- Why was the certificate not rotated automatically before expiry?
- Did any pods in AZ‑b behave differently (logs missing)?
- Are there other downstream services that call auth‑service over TLS and may have silently failed?

## How the investigation ran

Stopped because the agent finished its investigation, after 1 round(s): 8 model calls, 6 tool calls, 48,918 tokens, 373 s.
