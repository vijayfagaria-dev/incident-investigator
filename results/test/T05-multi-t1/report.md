# T05: Nobody can log in

**Outcome:** conclusive. Root cause: `certificate_or_credential` on **auth-service**

## Summary

All login and token‑refresh requests began failing at ~06:00 UTC because the TLS certificate used by auth‑service expired at 2026‑10‑09T06:00:00Z. Edge‑gateway logs show a sharp rise in TLS handshake failures citing that exact notAfter time, and the critic accepted this hypothesis (HYP‑1) with high confidence (0.88). The investigation is conclusive, but the certificate’s expiry has not been independently confirmed via a secret‑rotation or cert‑management change record, and several observability gaps (missing az‑b logs, connection‑pool metrics, possible secret‑rotation events) remain.

## Hypotheses

### 1. `certificate_or_credential` on **auth-service** (HYP-1)

Confidence 0.88 (high), critic: accept. The auth-service TLS certificate expired at 2026-10-09T06:00:00Z. When edge-gateway attempted new TLS handshakes to auth-service after that time, the handshakes failed with “certificate notAfter 2026-10-09T06:00:00Z”, causing a sharp rise in 5xx errors on POST /v1/session.

**Supporting:**
- Edge‑gateway logs show 1,181 TLS handshake failures with auth‑service starting at 2026-10-09T06:00:09.657Z, citing a certificate notAfter 2026-10-09T06:00:00Z. (`log:6a1c72fa74da`)
- Auth‑service logs record 907 TLS handshake errors (“remote error: tls: bad certificate”) from gateway IPs starting at 2026-10-09T06:00:06.184Z. (`log:be1de505ee3a`)
- Edge‑gateway logs record 1,428 TLS handshake failures with auth‑service beginning at 2026-10-09T06:00:09.657Z (certificate notAfter 2026-10-09T06:00:00Z). (`log:6a1c72fa74da`)
- Edge‑gateway error_rate rises from a baseline mean of 0.0020 to a window mean of 0.0401 (max 0.1275) during the incident window. (`metric:edge-gateway/error_rate`)
- Edge‑gateway error_rate rises from a baseline mean of 0.00204 to a window mean of 0.08244 (max 0.1331) after ~06:00 UTC. (`metric:edge-gateway/error_rate`)
**Contradicting:**
- config on edge-gateway at 05:52:30 UTC by platform-bot: Raise upstream keepalive timeout (upstream.keepalive_timeout_s: 60 -> 75) (`chg:2541`)
- Only change in the window is chg:2541 – edge‑gateway config raising upstream.keepalive_timeout_s from 60 to 75 at 05:52:30 UTC. (`chg:2541`)
- The config change (chg:2541) occurred ~8 minutes before the first reported login failures (~06:00 UTC), making it a plausible cause. (`chg:2541`)
- The changed setting controls how long edge‑gateway keeps idle HTTP connections to upstreams; increasing it to 75 s may keep connections alive longer than auth‑service expects, leading to upstream‑side connection drops. (`chg:2541`)
- Only change in window was edge-gateway config at 05:52:30 raising upstream.keepalive_timeout_s from 60 to 75. (`chg:2541`)
- Increasing keepalive timeout makes idle connections stay open longer, potentially exhausting gateway upstream pool or auth-service connection limits. (`chg:2541`)
**Assumptions:**
- ASM-1: The auth-service TLS certificate was set to expire at 2026-10-09T06:00:00Z and was not rotated or renewed before that moment.
- ASM-2: Edge-gateway validates the peer certificate on every new TLS handshake (does not cache a validated cert for the life of a keep-alive connection).
**Objections:**
- [minor] gap_unaddressed: Certificate metadata (notAfter field) has not been independently verified via a secret‑rotation or cert‑management change record; the conclusion rests on log messages that cite the expiry time.

### 2. `config_change` on **edge-gateway**, triggered by `chg:2541` (HYP-2)

Confidence 0.32 (low), critic: reject. The gateway config change at 05:52:30 UTC raised upstream.keepalive_timeout_s from 60 s to 75 s. Idle HTTP/TCP connections to auth-service were kept alive longer than auth-service’s inbound idle‑timeout, causing auth-service to close them. The gateway then reused stale connections, leading to TLS handshake failures (or connection resets) and a rise in 5xx error rate starting ~06:00 UTC.

**Supporting:**
- config on edge-gateway at 05:52:30 UTC by platform-bot: Raise upstream keepalive timeout (upstream.keepalive_timeout_s: 60 -> 75) (`chg:2541`)
- Only change in the window is chg:2541 – edge‑gateway config raising upstream.keepalive_timeout_s from 60 to 75 at 05:52:30 UTC. (`chg:2541`)
- The config change (chg:2541) occurred ~8 minutes before the first reported login failures (~06:00 UTC), making it a plausible cause. (`chg:2541`)
- The changed setting controls how long edge‑gateway keeps idle HTTP connections to upstreams; increasing it to 75 s may keep connections alive longer than auth‑service expects, leading to upstream‑side connection drops. (`chg:2541`)
- Only change in window was edge-gateway config at 05:52:30 raising upstream.keepalive_timeout_s from 60 to 75. (`chg:2541`)
- Increasing keepalive timeout makes idle connections stay open longer, potentially exhausting gateway upstream pool or auth-service connection limits. (`chg:2541`)
- edge‑gateway has a hard HTTP dependency on auth‑service (timeout 1000 ms). (`dep:edge-gateway->auth-service`)
- auth‑service has a hard Redis dependency on redis‑cache (timeout 200 ms). (`dep:auth-service->redis-cache`)
- The login request path follows the hard‑dependency chain edge‑gateway → auth‑service → redis‑cache. (`dep:edge-gateway->auth-service`, `dep:auth-service->redis-cache`)
**Contradicting:**
- Edge‑gateway logs show 1,181 TLS handshake failures with auth‑service starting at 2026-10-09T06:00:09.657Z, citing a certificate notAfter 2026-10-09T06:00:00Z. (`log:6a1c72fa74da`)
- Auth‑service logs record 907 TLS handshake errors (“remote error: tls: bad certificate”) from gateway IPs starting at 2026-10-09T06:00:06.184Z. (`log:be1de505ee3a`)
- Edge‑gateway logs record 1,428 TLS handshake failures with auth‑service beginning at 2026-10-09T06:00:09.657Z (certificate notAfter 2026-10-09T06:00:00Z). (`log:6a1c72fa74da`)
- Edge‑gateway latency_p99_ms remains near its baseline (baseline 343 ms, window mean 339.5 ms), indicating latency is not the primary symptom. (`metric:edge-gateway/latency_p99_ms`)
- Edge‑gateway latency_p99_ms remains near its baseline (baseline 338.9 ms, window mean 341.2 ms), indicating latency is not the primary symptom. (`metric:edge-gateway/latency_p99_ms`)
**Assumptions:**
- ASM-3: Auth-service’s inbound HTTP idle‑timeout is ≤ 60 s, so a gateway keep‑alive of 75 s would exceed it.
- ASM-4: Edge-gateway re‑uses a keep‑alive connection for a new request without performing a fresh TLS handshake (i.e., it resumes the TLS session).
- ASM-5: The gateway’s TLS session resumption does not validate the peer certificate’s notAfter field on resume.
**Objections:**
- [blocking] ignores_contradiction: Logs from both services report TLS handshake failures due to an expired certificate (notAfter 2026‑10‑09T06:00:00Z). The hypothesis attributes failures to stale connections caused by a keepalive change, which would manifest as connection resets, not certificate‑expiry errors.
- [blocking] unsupported_claim: The claim that raising upstream.keepalive_timeout_s to 75 s causes TLS handshake failures is not backed by any log or metric showing connection‑reset or pool‑exhaustion events.

## Recommended actions

| Urgency | Kind | Action | Why |
|---|---|---|---|
| now | mitigate | Deploy a valid TLS certificate to auth‑service (or restart auth‑service with a renewed cert) to restore successful TLS handshakes on the gateway‑auth link. | Handshake failures are directly caused by the expired certificate (HYP‑1). Restoring a valid cert will immediately stop the 5xx errors on POST /v1/session. (HYP-1) |
| soon | fix | Update the certificate‑rotation pipeline for auth‑service to renew certificates well before their notAfter date and add automated pre‑expiry checks. | The root cause is an unrotated certificate; fixing the rotation process prevents recurrence. (HYP-1) |
| later | prevent | Add monitoring and alerting on TLS certificate expiration for all services that terminate TLS (auth‑service, edge‑gateway) and on the secret‑management system. | Early detection of upcoming expirations will stop future outages of this class. (HYP-1) |
| soon | investigate | Verify the auth‑service certificate metadata (notAfter field) against the secret‑rotation / cert‑management change log to confirm the exact expiry time. | Critic noted a minor gap: the conclusion rests on log messages that cite the expiry time, not an independent change record (GAP‑13). (HYP-1) |
| soon | investigate | Retrieve missing edge‑gateway and auth‑service logs from availability zone az‑b (log shards currently unavailable) to ensure no additional error patterns exist. | Log gaps (GAP‑8, GAP‑9, GAP‑14, GAP‑16) could hide connection‑reset or other anomalies. |
| soon | investigate | Collect edge‑gateway upstream connection‑pool metrics (active/idle connections, queue length, reset counters) and auth‑service inbound connection metrics for the 05:50‑06:30 UTC window. | Gaps GAP‑2, GAP‑10, GAP‑15 prevent ruling out connection‑exhaustion effects from the keepalive change. |
| soon | investigate | Search for any secret‑rotation or TLS‑cert change events for the gateway‑auth link outside the queried services (e.g., in a central cert manager). | GAP‑13 notes change‑census was limited to edge‑gateway and auth‑service; a rotation elsewhere could explain the expiry. |

## Evidence gaps

- **get_change_history** (auth-service inbound HTTP keepalive/idle‑timeout configuration): Not captured as a recorded change; needed to determine if upstream timeout mismatch exists.
- **observability** (edge‑gateway upstream connection pool stats (active/idle connections, queue length) around 05:52‑06:30 UTC): Would reveal whether the longer keepalive caused connection exhaustion.
- **observability** (redis‑cache health metrics (CPU, memory, eviction rate) for 05:50‑06:30 UTC): Even without recorded changes, a latent resource issue could surface simultaneously.
- **get_change_history** (any feature‑flag or runtime config toggle on edge‑gateway affecting keepalive behavior): Such toggles may not appear as a config change but could interact with the timeout setting.
- **query_metrics** (auth-service metrics (error_rate, latency_p99_ms, cpu_util, mem_util, connection pool) for 2026-10-09T05:15Z‑06:25Z): Tool step limit reached; need auth‑service metric series to confirm service‑side saturation or error spikes.
- **query_metrics** (redis-cache metrics (error_rate, latency, connection count) for 2026-10-09T05:15Z‑06:25Z): Tool step limit reached; need redis‑cache data to verify the auth‑service → redis hop.
- **query_logs** (redis-cache logs at WARN/ERROR for 2026-10-09T05:15Z‑06:25Z): Tool step limit reached; no log visibility on redis‑cache to rule out downstream failures.
- **query_logs** (service=edge-gateway, start=2026-10-09T05:15:00Z, end=2026-10-09T06:25:00Z): log shard for az-b is unavailable; results exclude pods in az-b
- **query_logs** (service=auth-service, start=2026-10-09T05:15:00Z, end=2026-10-09T06:25:00Z): log shard for az-b is unavailable; results exclude pods in az-b
- **metrics** (edge-gateway upstream connection pool usage and auth-service inbound connections): Not available in change-census or dependency data
- **logs** (edge-gateway and auth-service logs around 05:55-06:15): Only responder notes are available
- **config** (gateway upstream connection pool limits and auth-service max_connections settings): Not captured in current tooling
- **changes** (any secret rotation or TLS cert change for gateway-auth link outside queried services): Change census limited to edge-gateway and auth-service
- **query_logs** (edge-gateway logs from availability zone az‑b): Log shard for az‑b is unavailable; results exclude pods in that zone, so connection‑reset evidence from those pods is missing.
- **query_metrics** (edge-gateway upstream connection error counters (reset, broken pipe)): No such metric series is exposed in the current metric catalog, preventing direct quantification of connection‑reset events.
- **query_logs** (service=edge-gateway, start=2026-10-09T05:50:00Z, end=2026-10-09T06:30:00Z): log shard for az-b is unavailable; results exclude pods in az-b

## Open questions

- Exact certificate metadata (notAfter) from the secret‑management system – has it been independently verified?
- Why did the certificate expire without an automated renewal or alert?
- What do the missing az‑b logs (edge‑gateway and auth‑service) show for the incident window?
- What were the edge‑gateway upstream connection‑pool statistics and auth‑service inbound connection counts during 05:50‑06:30 UTC?
- Were there any secret‑rotation or cert‑change events for the gateway‑auth TLS link recorded outside the edge‑gateway/auth‑service change census?
- Redis‑cache health (CPU, memory, eviction rate) during the window – could a downstream issue have contributed?

## How the investigation ran

Stopped because the critic accepted HYP-1, after 1 round(s): 24 model calls, 12 tool calls, 97,634 tokens, 601 s.
