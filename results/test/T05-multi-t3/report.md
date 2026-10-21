# T05: Nobody can log in

**Outcome:** conclusive. Root cause: `certificate_or_credential` on **auth-service**

## Summary

Login and token‑refresh failures began at 06:00 UTC when the TLS certificate presented by auth‑service expired (notAfter 2026‑10‑09T06:00:00Z). Edge‑gateway logged “certificate has expired or is not yet valid” on every new handshake and returned 5xx on POST /v1/session. The critic accepted HYP‑1 (confidence 0.92) as the root cause; the config change on edge‑gateway (HYP‑2) and a Redis issue (HYP‑3) were rejected. The incident is therefore conclusive, though several observability gaps remain (e.g., auth‑service idle_timeout, gateway keep‑alive pool metrics, missing AZ‑B logs).

## Hypotheses

### 1. `certificate_or_credential` on **auth-service** (HYP-1)

Confidence 0.92 (high), critic: accept. The TLS certificate presented by auth-service expired at 2026-10-09T06:00:00Z (notAfter). After expiry every new TLS handshake from edge-gateway fails with “certificate has expired or is not yet valid”. Edge-gateway therefore returns 5xx on POST /v1/session. Auth-service logs the same failure as “remote error: tls: bad certificate”.

**Supporting:**
- edge‑gateway logs TLS handshake failures to auth‑service with message “certificate has expired or is not yet valid (notAfter 2026‑10‑09T06:00:00Z)”, first seen 2026‑10‑09T06:00:09.657Z, 1,181 occurrences until 06:24:59.999Z (`log:6a1c72fa74da`)
- edge‑gateway returns 5xx on POST /v1/session starting at 2026‑10‑09T06:02:30.152Z (500) and continuing through 06:24:53.643Z (mix of 500,502,503,504) (`log:2664c15a6f77`, `log:dc6cae0ec986`, `log:14ec15d842b9`, `log:c92936371ff2`, `log:073f2869b231`, `log:b7069fbe54d0`, `log:dc09971a7bde`, `log:111c243da777`, `log:9e57f2e4448c`, `log:79d8636848f5`, `log:34169d3d8921`)
- auth‑service logs 907 TLS handshake errors “remote error: tls: bad certificate” from edge‑gateway IPs, first seen 2026‑10‑09T06:00:06.184Z, last seen 06:24:59.782Z (`log:be1de505ee3a`)
**Assumptions:**
- ASM-1: The auth‑service TLS certificate was not successfully rotated/reloaded before its notAfter time.
- ASM-2: Edge‑gateway validates the auth‑service certificate on every new TLS handshake (standard mTLS).

### 2. `config_change` on **edge-gateway**, triggered by `chg:2541` (HYP-2)

Confidence 0.18 (low), critic: challenge. The gateway keep‑alive timeout was raised from 60 s to 75 s at 05:52:30 (chg:2541). If auth-service’s HTTP server idle_timeout is < 75 s, the gateway re‑uses TCP/TLS connections that auth-service has already closed. When the gateway attempts a new handshake on those stale connections it encounters the already‑expired certificate, producing the observed “bad certificate” errors.

**Supporting:**
- config on edge-gateway at 05:52:30 UTC by platform-bot: Raise upstream keepalive timeout (upstream.keepalive_timeout_s: 60 -> 75) (`chg:2541`)
- The only recorded change in the window is edge‑gateway config chg:2541 raising upstream.keepalive_timeout_s from 60 s to 75 s at 05:52:30 UTC. (`chg:2541`)
- The config change occurred ~30 s before the first reported login failures (~06:00 UTC), making it temporally plausible as a trigger. (`chg:2541`)
- The login request path follows a hard‑dependency chain edge‑gateway → auth‑service → redis‑cache. (`dep:edge-gateway->auth-service`, `dep:auth-service->redis-cache`)
**Contradicting:**
- edge‑gateway logs TLS handshake failures to auth‑service with message “certificate has expired or is not yet valid (notAfter 2026‑10‑09T06:00:00Z)”, first seen 2026‑10‑09T06:00:09.657Z, 1,181 occurrences until 06:24:59.999Z (`log:6a1c72fa74da`)
- auth‑service logs 907 TLS handshake errors “remote error: tls: bad certificate” from edge‑gateway IPs, first seen 2026‑10‑09T06:00:06.184Z, last seen 06:24:59.782Z (`log:be1de505ee3a`)
**Assumptions:**
- ASM-3: Auth‑service HTTP server idle_timeout is configured to a value lower than 75 seconds.
- ASM-4: Edge‑gateway re‑uses TLS sessions across HTTP/1.1 keep‑alive connections.
- ASM-5: The certificate expiry is independent of the keep‑alive change; the change only exposes the expiry earlier.
**Objections:**
- [blocking] gap_unaddressed: The claim that auth‑service idle_timeout < 75 s is an unverified assumption (GAP‑6). Without the actual idle_timeout value the stale‑connection mechanism cannot be confirmed.
- [blocking] unsupported_claim: The hypothesis asserts that the keep‑alive change causes the gateway to reuse connections that present the already‑expired certificate, yet the handshake failures start exactly at the certificate notAfter time, not at the config change. No evidence shows increased connection reuse or resets after 05:52.

### 3. `dependency_degradation` on **redis-cache** (HYP-3)

Confidence 0.05 (low), critic: reject. An unobserved Redis issue (failover, OOM, replication lag) breaks the hard dependency auth-service → redis-cache, causing login/token‑refresh failures.

**Supporting:**
- The login request path follows a hard‑dependency chain edge‑gateway → auth‑service → redis‑cache. (`dep:edge-gateway->auth-service`, `dep:auth-service->redis-cache`)
**Contradicting:**
- Connected‑client count averaged 412.5 (baseline 405.8) with a max of 462.9; no sudden rise at 06:00. (`metric:redis-cache/connected_clients`)
- CPU utilization averaged 0.170 (baseline 0.162), max 0.203; values are flat across the window, no spike at incident start. (`metric:redis-cache/cpu_util`, `metric:redis-cache/cpu_util`)
- Memory utilization averaged 0.612 (baseline 0.610), ranging 0.599‑0.631; stable through the period. (`metric:redis-cache/mem_util`, `metric:redis-cache/mem_util`)
- Cache hit ratio averaged 0.939 (baseline 0.942), min 0.914; only a minor dip, not indicative of a failure. (`metric:redis-cache/hit_ratio`)
- auth‑service shows only occasional 504 on /v1/token/refresh (4 total) and normal login‑failure logs; no log lines indicating redis‑cache connection time‑outs or errors in the examined window (`log:82f41f6a7636`)
- No deploy, config, feature‑flag, secret‑rotation, or infra change was recorded for auth‑service or redis‑cache between 05:30‑06:15 UTC. (`chg:2541`)
- No deploy, config, feature‑flag, secret‑rotation, or infra change was recorded for redis‑cache between 05:30‑06:15 UTC. (`chg:2541`)
**Assumptions:**
- ASM-6: Redis may have suffered a brief failover that left no trace in the sampled metrics.
**Objections:**
- [blocking] ignores_contradiction: Observations OBS‑2, OBS‑3, OBS‑4, OBS‑5, OBS‑14, OBS‑6, and OBS‑7 all show Redis‑cache operating normally with no error signals; the hypothesis does not address these contradictory data points.

## Recommended actions

| Urgency | Kind | Action | Why |
|---|---|---|---|
| now | mitigate | Rotate the expired TLS certificate on auth‑service immediately and restart affected pods. | The expired certificate is the direct cause of all TLS handshake failures (HYP‑1). Restoring a valid cert restores logins instantly. (HYP-1) |
| soon | fix | Automate certificate renewal for auth‑service (e.g., cert‑manager or scheduled rotation) with a renewal window well before expiry. | Prevents recurrence of the same expiry‑driven outage. (HYP-1) |
| later | prevent | Add a monitoring alert that fires ≥ 24 h before any service TLS certificate’s notAfter date. | Early warning gives operators time to rotate certificates before they expire. (HYP-1) |
| soon | investigate | Retrieve auth‑service HTTP server idle_timeout configuration to verify the stale‑connection hypothesis (GAP‑6). | Even though HYP‑2 was rejected, confirming the idle_timeout value closes the remaining evidence gap. (HYP-2) |
| soon | investigate | Collect edge‑gateway upstream keep‑alive pool metrics (connection reuse, resets) for 05:50‑06:10 UTC (GAP‑4). | Quantifies whether the keep‑alive timeout change altered connection behavior. (HYP-2) |
| later | investigate | Query Redis‑cache server logs (ERROR/WARN) for 05:15‑06:25 UTC (GAP‑2, GAP‑9) and Redis client metrics from auth‑service (GAP‑7). | Ensures no hidden Redis degradation contributed, despite HYP‑3 being rejected. (HYP-3) |
| later | investigate | Obtain missing AZ‑B log shards for edge‑gateway and auth‑service (GAP‑10, GAP‑11). | Completes the log picture and rules out any zone‑specific anomalies. |

## Evidence gaps

- **query_metrics** (Redis command latency, replication lag, eviction rate, slowlog entries): Those metrics are not exposed in the current metric set, so we cannot confirm latency‑related saturation.
- **query_logs** (Redis‑cache server logs (ERROR/WARN) for 05:15‑06:25 UTC): Log collection for redis‑cache was not queried; any OOM, replication‑failover, or client‑rejection events would be invisible.
- **get_change_history** (auth-service, redis-cache (secret‑manager, feature‑flag service, redis‑cache ops logs)): No changes recorded in the change census, but unrecorded secret rotations, feature‑flag flips, or Redis topology events could have occurred.
- **observability_metrics** (edge-gateway upstream keep‑alive pool metrics (connection reuse, resets) 05:50‑06:10 UTC): Metrics not yet retrieved; needed to confirm whether the keep‑alive timeout change altered connection behavior.
- **observability_metrics** (auth‑service request latency, error rate, Redis client errors 05:50‑06:10 UTC): Metrics not yet retrieved; needed to see if downstream errors appear after the gateway config change.
- **config_audit** (auth‑service HTTP server idle_timeout configuration): Current idle‑timeout value unknown; required to evaluate stale‑connection hypothesis.
- **query_metrics** (auth-service redis‑cache client latency, error rate, connection‑pool saturation): Metrics not queried; needed to confirm or rule out redis‑cache hard‑dependency time‑outs.
- **query_metrics** (edge‑gateway upstream request latency, 5xx count, and keepalive‑timeout behavior): Metrics not queried; would quantify the 5xx surge and correlate with config change at 05:52.
- **query_logs** (redis‑cache service logs (any error / connection‑reset patterns) for the window 05:15‑06:25 UTC): Redis‑cache logs were not examined; could reveal server‑side issues.
- **query_logs** (service=edge-gateway, start=2026-10-09T05:15:00Z, end=2026-10-09T06:25:00Z): log shard for az-b is unavailable; results exclude pods in az-b
- **query_logs** (service=auth-service, start=2026-10-09T05:15:00Z, end=2026-10-09T06:25:00Z): log shard for az-b is unavailable; results exclude pods in az-b

## Open questions

- What is the exact idle_timeout value configured on auth‑service’s HTTP server?
- Did the edge‑gateway keep‑alive timeout change cause any measurable increase in connection reuse or resets?
- Are there any Redis‑cache error events or client‑side latency spikes in the missing AZ‑B logs?
- What is the current certificate‑expiry monitoring coverage across all services?

## How the investigation ran

Stopped because the critic accepted HYP-1, after 1 round(s): 20 model calls, 10 tool calls, 78,765 tokens, 453 s.
