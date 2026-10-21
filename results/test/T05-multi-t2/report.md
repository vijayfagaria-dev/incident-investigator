# T05: Nobody can log in

**Outcome:** conclusive. Root cause: `certificate_or_credential` on **auth-service**

## Summary

All login and token‑refresh requests began failing at ~06:00 UTC because the TLS server certificate presented by auth‑service expired at 2026‑10‑09T06:00:00Z. Edge‑gateway and auth‑service logs show a sudden burst of TLS handshake failures (“certificate notAfter …” and “remote error: tls: bad certificate”) exactly at that moment, and the edge‑gateway error rate jumped from ~0.2 % to >9 %. No downstream Redis errors were observed, confirming the failure originates at the TLS layer of auth‑service. The investigation concluded (conclusive) with high confidence (0.92) that the certificate expiry is the root cause; why the certificate was not renewed remains unverified.

## Hypotheses

### 1. `certificate_or_credential` on **auth-service** (HYP-1)

Confidence 0.92 (high), critic: accept. The TLS server certificate presented by auth-service expired at 2026-10-09T06:00:00Z. After that moment every new TLS handshake from edge-gateway fails with “certificate notAfter 2026-10-09T06:00:00Z” (edge-gateway logs) and “remote error: tls: bad certificate” (auth-service logs). The handshake failures appear on both sides at 06:00:06‑06:00:09 and the edge-gateway error_rate jumps from 0.2 % to >4 % (last 9.6 %). No downstream Redis errors are observed, confirming the failure originates at the TLS layer of auth-service.

**Supporting:**
- edge-gateway logs TLS handshake failures to auth-service beginning 2026-10-09T06:00:09.657Z, 1,181 occurrences, citing certificate notAfter 2026-10-09T06:00:00Z (`log:6a1c72fa74da`)
- auth-service logs TLS handshake errors from edge-gateway IPs beginning 2026-10-09T06:00:06.184Z, 907 occurrences, reporting “remote error: tls: bad certificate” (`log:be1de505ee3a`)
- edge-gateway error_rate metric rises from baseline_mean 0.002029 (0.2 %) to a period mean of 0.04009 (4 %) and a last value of 0.0963 (9.6 %) during the window (`metric:edge-gateway/error_rate`)
- No Redis‑cache error or timeout log patterns appear at WARN/ERROR in the captured range for any service (`log:6a1c72fa74da`, `log:be1de505ee3a`)
- edge-gateway error_rate rose from a baseline mean of 0.0020 (0.2 %) to a period mean of 0.0555 (5.5 %) and a last value of 0.0833 (8.3 %) during 05:50‑06:10 UTC. (`metric:edge-gateway/error_rate`, `metric:edge-gateway/error_rate`)
- edge-gateway logged TLS handshake failures to auth-service starting 2026‑10‑09T06:00:09.657Z, 1,181 occurrences, citing certificate notAfter 2026‑10‑09T06:00:00Z. (`log:6a1c72fa74da`)
- auth-service logged TLS handshake errors from edge‑gateway IPs starting 2026‑10‑09T06:00:06.184Z, 907 occurrences, reporting “remote error: tls: bad certificate”. (`log:be1de505ee3a`)
**Contradicting:**
- config on edge-gateway at 05:52:30 UTC by platform-bot: Raise upstream keepalive timeout (upstream.keepalive_timeout_s: 60 -> 75) (`chg:2541`)
- A single config change on edge‑gateway at 2026-10-09T05:52:30Z raised upstream.keepalive_timeout_s from 60 to 75 (chg:2541). (`chg:2541`)
- The changed keep‑alive timeout governs idle connection reuse and does not modify request routing, auth‑header processing, or the request timeout. (`chg:2541`, `dep:edge-gateway->auth-service`)
- edge‑gateway config change chg:2541 raised upstream.keepalive_timeout_s from 60 s to 75 s at 2026-10-09T05:52:30Z. (`chg:2541`)
- No deploy, config, feature‑flag, secret‑rotation, or infra events were recorded for auth‑service or redis‑cache between 05:15 UTC and 06:25 UTC. (`chg:2541`)
**Assumptions:**
- ASM-7: The certificate’s notAfter value is exactly 2026-10-09T06:00:00Z (as logged by edge-gateway).
- ASM-8: Edge-gateway validates notAfter on every new handshake (standard TLS behaviour).
- ASM-9: No auth-service deploy / config / secret-rotation occurred between 05:15‑06:25 UTC.

### 2. `config_change` on **edge-gateway**, triggered by `chg:2541` (HYP-2)

Confidence 0.18 (low), critic: challenge. The only recorded change before the outage is chg:2541 (05:52:30 UTC) which raised upstream.keepalive_timeout_s from 60 s to 75 s. A longer keep‑alive can keep idle TLS connections in the gateway’s connection pool past the certificate expiry moment (06:00 UTC). When the pool later re‑uses those stale connections, the server presents an already‑expired certificate, causing a burst of handshake failures that surface as 5xx on /v1/session.

**Supporting:**
- config on edge-gateway at 05:52:30 UTC by platform-bot: Raise upstream keepalive timeout (upstream.keepalive_timeout_s: 60 -> 75) (`chg:2541`)
- A single config change on edge‑gateway at 2026-10-09T05:52:30Z raised upstream.keepalive_timeout_s from 60 to 75 (chg:2541). (`chg:2541`)
- edge‑gateway config change chg:2541 raised upstream.keepalive_timeout_s from 60 s to 75 s at 2026-10-09T05:52:30Z. (`chg:2541`)
- Edge‑gateway forwards /v1/session traffic to auth‑service via a hard HTTP dependency with a 1 000 ms timeout (dep:edge-gateway→auth-service). (`dep:edge-gateway->auth-service`)
- edge‑gateway has a hard HTTP dependency on auth‑service with a 1000 ms timeout (dep:edge-gateway->auth-service). (`dep:edge-gateway->auth-service`)
- edge-gateway error_rate metric rises from baseline_mean 0.002029 (0.2 %) to a period mean of 0.04009 (4 %) and a last value of 0.0963 (9.6 %) during the window (`metric:edge-gateway/error_rate`)
- edge-gateway error_rate rose from a baseline mean of 0.0020 (0.2 %) to a period mean of 0.0555 (5.5 %) and a last value of 0.0833 (8.3 %) during 05:50‑06:10 UTC. (`metric:edge-gateway/error_rate`, `metric:edge-gateway/error_rate`)
**Contradicting:**
- The changed keep‑alive timeout governs idle connection reuse and does not modify request routing, auth‑header processing, or the request timeout. (`chg:2541`, `dep:edge-gateway->auth-service`)
- edge-gateway logs TLS handshake failures to auth-service beginning 2026-10-09T06:00:09.657Z, 1,181 occurrences, citing certificate notAfter 2026-10-09T06:00:00Z (`log:6a1c72fa74da`)
- auth-service logs TLS handshake errors from edge-gateway IPs beginning 2026-10-09T06:00:06.184Z, 907 occurrences, reporting “remote error: tls: bad certificate” (`log:be1de505ee3a`)
- No deploy, config, feature‑flag, secret‑rotation, or infra events were recorded for auth‑service or redis‑cache between 05:15 UTC and 06:25 UTC. (`chg:2541`)
- No Redis‑cache error or timeout log patterns appear at WARN/ERROR in the captured range for any service (`log:6a1c72fa74da`, `log:be1de505ee3a`)
**Assumptions:**
- ASM-10: Edge-gateway’s HTTP client re-uses a TLS session without performing a fresh handshake when a keep-alive connection is taken from the pool (session‑ticket / session‑ID resumption).
- ASM-11: The keep-alive increase caused a measurable number of connections opened before 06:00 to stay alive after 06:00.
- ASM-12: The gateway does not validate notAfter on resumed sessions (unlikely for standard libraries).
**Objections:**
- [blocking] gap_unaddressed: No edge‑gateway TLS connection‑pool metrics (idle count, handshake‑success vs reuse) are available for 05:50‑06:10 UTC (GAP‑13). Without them we cannot confirm that longer keep‑alive caused reuse of expired‑cert connections.
- [blocking] alternative_not_excluded: HYP‑1 (certificate expiry) fully explains the observed handshake failures and error‑rate spike. Until HYP‑2 demonstrates a distinct contribution, it remains an unruled‑out alternative.

### 3. `infrastructure_failure` on **infrastructure** (HYP-3)

Confidence 0.07 (low), critic: reject. An automated certificate-management component (e.g., cert-manager, Vault, external CA) failed to renew the auth-service TLS certificate before its notAfter = 06:00 UTC. The failure is invisible in the change census because it is not a user‑initiated config change. The expiry then produces the same TLS‑handshake failure pattern as H1.

**Supporting:**
- edge-gateway logs TLS handshake failures to auth-service beginning 2026-10-09T06:00:09.657Z, 1,181 occurrences, citing certificate notAfter 2026-10-09T06:00:00Z (`log:6a1c72fa74da`)
- auth-service logs TLS handshake errors from edge-gateway IPs beginning 2026-10-09T06:00:06.184Z, 907 occurrences, reporting “remote error: tls: bad certificate” (`log:be1de505ee3a`)
- edge-gateway error_rate metric rises from baseline_mean 0.002029 (0.2 %) to a period mean of 0.04009 (4 %) and a last value of 0.0963 (9.6 %) during the window (`metric:edge-gateway/error_rate`)
- No Redis‑cache error or timeout log patterns appear at WARN/ERROR in the captured range for any service (`log:6a1c72fa74da`, `log:be1de505ee3a`)
- edge-gateway error_rate rose from a baseline mean of 0.0020 (0.2 %) to a period mean of 0.0555 (5.5 %) and a last value of 0.0833 (8.3 %) during 05:50‑06:10 UTC. (`metric:edge-gateway/error_rate`, `metric:edge-gateway/error_rate`)
- edge-gateway logged TLS handshake failures to auth-service starting 2026‑10‑09T06:00:09.657Z, 1,181 occurrences, citing certificate notAfter 2026‑10‑09T06:00:00Z. (`log:6a1c72fa74da`)
- auth-service logged TLS handshake errors from edge‑gateway IPs starting 2026‑10‑09T06:00:06.184Z, 907 occurrences, reporting “remote error: tls: bad certificate”. (`log:be1de505ee3a`)
**Contradicting:**
- No deploy, config, feature‑flag, secret‑rotation, or infra events were recorded for auth‑service or redis‑cache between 05:15 UTC and 06:25 UTC. (`chg:2541`)
**Assumptions:**
- ASM-13: The certificate is managed by an external controller not represented in the change census.
- ASM-14: The controller attempted renewal but the new cert was not deployed to auth-service pods before 06:00.
**Objections:**
- [minor] unsupported_claim: Assertion that a certificate‑management component failed to renew the cert has no log or metric support (GAP‑15).

## Recommended actions

| Urgency | Kind | Action | Why |
|---|---|---|---|
| now | mitigate | Renew the auth‑service TLS certificate immediately and roll it out to all pods. | The expired certificate is the direct cause of the handshake failures and the login outage. (HYP-1) |
| soon | fix | Repair or reconfigure the certificate‑management automation (e.g., cert‑manager/Vault) so that certificates are renewed well before their notAfter date. | The certificate was allowed to expire, indicating a failure in the renewal process. (HYP-1) |
| later | prevent | Add monitoring and alerting on TLS certificate expiry (e.g., cert‑exporter alerts 30 days, 7 days, 1 day before expiry) and on auth‑service TLS handshake error rates. | Early detection will prevent a repeat outage caused by an unnoticed expiry. (HYP-1) |
| soon | investigate | Examine cert‑manager / secret‑controller logs and the auth‑service secret history to determine why the renewal did not complete before 06:00 UTC. | The root cause of the expiry (HYP‑3) is still unknown; logs were not captured (GAP‑15). (HYP-3) |

## Evidence gaps

- **get_change_history** (Full config diff for chg:2541): Tool returns only the summary field; the complete diff (which could include routing or header changes) is not available.
- **observability (logs/metrics)** (Edge‑gateway access and error logs for 05:55‑06:10 UTC): Log data not accessible via current tooling; needed to see exact 5xx codes and any connection‑reuse errors.
- **observability (logs/metrics)** (Auth‑service internal request logs for 05:55‑06:05 UTC): Auth‑service logs not captured; could reveal connection‑pool exhaustion or request rejections linked to longer keep‑alive.
- **get_change_history** (Full rollout timeline of chg:2541 (rolling restart vs hot reload)): Change census only records the config‑map write; need to know if pods were recycled, affecting connection pools.
- **get_change_history** (Auth‑service and redis‑cache change logs (Helm, ArgoCD, manual kubectl)): Census shows zero changes, but external deployment mechanisms may not be captured.
- **get_change_history** (Network / service‑mesh / CNI events in the 05:15‑06:25 window): Infrastructure changes could affect the gateway→auth‑service path but are not in the change census.
- **get_service_dependencies** (Exact error payloads / trace samples for POST /v1/session failures): Need to know whether the 5xx originates from gateway upstream timeout or auth‑service/redis errors.
- **query_metrics** (auth-service error_rate, latency_p99, Redis client metrics): Metrics not fetched; needed to confirm whether auth-service itself emitted 5xx or latency spikes and whether Redis contributed.
- **query_metrics** (redis-cache error_rate, command_latency, pool saturation): Redis metrics not fetched; required to rule out Redis‑layer failures.
- **query_metrics** (edge-gateway per‑route error_rate for /v1/session): Only aggregate error_rate retrieved; per‑route data would pinpoint the exact endpoint impact.
- **query_logs** (service=edge-gateway, start=2026-10-09T05:15:00Z, end=2026-10-09T06:25:00Z): log shard for az-b is unavailable; results exclude pods in az-b
- **query_logs** (service=auth-service, start=2026-10-09T05:15:00Z, end=2026-10-09T06:25:00Z): log shard for az-b is unavailable; results exclude pods in az-b
- **query_metrics** (edge-gateway TLS connection‑pool metrics (idle count, handshake‑success, handshake‑reuse) for 05:50‑06:10 UTC): Metric catalog for edge-gateway does not list these series; they are either not emitted or not scraped.
- **query_metrics** (auth-service metrics (error_rate, latency, rps, etc.) for 05:55‑06:05 UTC): All auth-service metric summaries returned null; metrics may be disabled or the scraper lacked access.
- **query_logs** (auth-service certificate issuance/renewal log entries for 05:55‑06:05 UTC): Log patterns at WARN/ERROR show only handshake errors; no certificate lifecycle logs were captured (possible log level or missing logger).
- **query_logs** (service=auth-service, start=2026-10-09T05:55:00Z, end=2026-10-09T06:05:00Z): log shard for az-b is unavailable; results exclude pods in az-b

## Open questions

- Why did the certificate‑management component fail to renew the auth‑service TLS certificate before its notAfter timestamp?
- Whether the edge‑gateway keep‑alive timeout increase (chg:2541) contributed to the failure burst (insufficient TLS connection‑pool metrics – GAP‑13).
- What caused the missing log shards for az‑b (GAP‑11, GAP‑12, GAP‑16) and could they contain additional clues?

## How the investigation ran

Stopped because the critic accepted HYP-1, after 2 round(s): 28 model calls, 12 tool calls, 124,221 tokens, 752 s.
