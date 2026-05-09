# Incident Playbooks

Step-by-step remediation guides for common production incident types. These are designed to be executed under pressure: each step states the action, the command or query to run, and the expected outcome.

---

## Playbook: Database Outage / Connection Pool Exhaustion

### Detection Signals
- Alert: `DBConnectionPoolHighUtilization`, `DBConnectionErrors`, `DatabaseDown`
- Metrics: Connection pool > 90% for > 2 min; query latency p99 spiking
- Logs: `connection refused`, `too many connections`, `FATAL: sorry, too many clients already`
- Customer impact: All writes failing; read-heavy pages timing out

### Triage (first 3 minutes)
1. **Check primary DB health** in cloud console / monitoring dashboard.
2. **Identify active connections**: `SELECT count(*), state FROM pg_stat_activity GROUP BY state;`
3. **Look for long-running queries / locks**: `SELECT pid, now() - pg_stat_activity.query_start AS duration, query FROM pg_stat_activity WHERE state != 'idle' ORDER BY duration DESC LIMIT 20;`
4. **Check replication lag** (if read replicas exist): `SELECT EXTRACT(EPOCH FROM (now() - pg_last_xact_replay_timestamp())) AS lag_seconds;`
5. **Check for recent deploy** or migration that changed query patterns.

### Mitigation
1. **If primary is unresponsive:**
   - Promote read replica to primary (if failover is not automatic).
   - Update application connection strings or DNS to point to new primary.
2. **If connection pool exhausted:**
   - Increase application connection pool temporarily (if memory allows).
   - Kill idle-in-transaction or stale connections: `SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE state = 'idle in transaction' AND now() - state_change > interval '5 minutes';`
3. **If slow query / lock storm:**
   - Identify and kill blocking query if safe: `SELECT pg_terminate_backend(<pid>);`
   - Enable query-level circuit breaker or rate-limit in app layer.
4. **If disk full / IOPS exhaustion:**
   - Scale storage / IOPS via cloud console.
   - Expire old logs or WAL if safe.

### Verification
- Connection pool utilization < 50% for 5 minutes.
- Query latency p99 returned to baseline.
- Error rate in app dropped.
- Replication lag < 1 second (if failover occurred).

### Escalation Triggers
- Failover does not complete in 10 minutes → escalate to DBA / infra.
- Data corruption suspected after failover → engage security + data team.
- RPO/RTO breached → exec notification.

### Prevention Action Items
- Implement connection pool monitoring and auto-scaling.
- Add slow-query alerts (> 2 seconds).
- Review and index query patterns from incident.
- Test failover procedures monthly.

---

## Playbook: API Failure / 5xx Spike

### Detection Signals
- Alert: `HighErrorRate`, `ALERT: API 5xx > 1%`
- Metrics: `http_requests_total{status=~"5.."}` spiking; p99 latency climbing
- Logs: Stack traces, `Internal Server Error`, downstream timeout messages
- Customer impact: API clients receiving errors; web app broken

### Triage (first 3 minutes)
1. **Quantify**: What is the 5xx rate? Which status codes? Which routes?
   - PromQL: `sum(rate(http_requests_total{status=~"5.."}[5m])) by (status, route)`
2. **Check deploys**: What version is running? Any deploy in last 30 minutes?
   - `kubectl get pods -l app=api --sort-by=.metadata.creationTimestamp`
3. **Check downstream health**: Is the failure originating in the API or a dependency?
   - Look at outbound request error rate by dependency.
4. **Check resource pressure**: CPU throttling? Memory pressure? Disk I/O?
   - `container_cpu_cfs_throttled_seconds_total`, `container_memory_working_set_bytes`

### Mitigation
1. **If bad deploy suspected:**
   - **Rollback immediately**: `kubectl rollout undo deployment/api` or equivalent.
   - Confirm new pods are old version and old pods are terminating.
2. **If downstream dependency failing:**
   - Enable circuit breaker: drop dependency calls; serve degraded response.
   - If cache is available, serve stale data for read paths.
3. **If resource pressure (CPU/mem):**
   - Horizontal pod autoscaler scale-up: `kubectl scale deployment/api --replicas=<N>`
   - If HPA is stuck, manual scale and investigate limit.
4. **If database is cause:**
   - Cross-reference Database Outage playbook.

### Verification
- 5xx rate < 0.1% for 10 minutes.
- All routes in error budget recovered.
- Latency p99 below SLO.
- No new error patterns in logs.

### Escalation Triggers
- Rollback fails or does not reduce error rate → escalate to platform / SRE.
- Error rate climbs after rollback → indicate deeper issue; engage service owner.
- Security-related 5xx (auth failures at scale) → security team.

### Prevention Action Items
- Add canary deploy gates on error rate and latency.
- Improve integration test coverage for dependency failures.
- Add automatic rollback on SLO breach.
- Ensure circuit breaker configs are tested in chaos engineering.

---

## Playbook: Memory Leak / OOMKill

### Detection Signals
- Alert: `PodOOMKilled`, `MemoryUsageHigh`, `ContainerRestartLoop`
- Metrics: `container_memory_working_set_bytes` steadily climbing; pod restart count increasing
- Logs: `OOMKilled`, `Exit Code 137`, heap out of memory in app logs
- Customer impact: Requests interrupted on restarting pods; latency spikes

### Triage (first 3 minutes)
1. **Identify affected pods / nodes**:
   - `kubectl get pods -o wide | grep -E 'OOMKilled|CrashLoopBackOff'`
2. **Check memory trend** over last 6 hours:
   - Grafana: `container_memory_working_set_bytes{pod=~"<service>.*"}` — is it a steady climb?
3. **Check for recent deploy or config change** that changed memory profile.
4. **Check node memory pressure**:
   - `kubectl describe node <node>` — look for `MemoryPressure` condition.

### Mitigation
1. **Immediate relief:**
   - Restart affected pods (drain traffic first if possible).
   - Scale horizontally to spread load and give leaking pods time to drain.
2. **If node memory pressure:**
   - Cordon node: `kubectl cordon <node>`
   - Evict pods to healthy nodes: `kubectl drain <node> --ignore-daemonsets`
3. **If leak is confirmed and not deploy-related:**
   - Temporarily increase memory limits to extend time between OOMKills.
   - Enable memory profiling (heap dump / pprof) on a non-production replica.
4. **If recent deploy is suspect:**
   - Rollback to last known good version.

### Verification
- Memory working set flat or slowly varying (not climbing) for 30 minutes.
- Pod restart count stable at 0.
- Node MemoryPressure cleared.
- Application latency and error rate normal.

### Escalation Triggers
- Leak persists after rollback → app team must profile and fix code.
- All nodes in pool under memory pressure → escalate to infra / cluster ops.
- OOMKill causing data corruption → data team + app team.

### Prevention Action Items
- Add memory growth alert: `memory > 80% for 1 hour` (leading indicator).
- Add integration tests that exercise long-running processes.
- Schedule periodic heap profiling in CI for memory-intensive services.
- Review memory limits vs. actual usage quarterly.

---

## Playbook: DDoS / Traffic Anomaly

### Detection Signals
- Alert: `TrafficSpike`, `RateLimitExceeded`, `UnusualRequestPattern`
- Metrics: Requests per second >> baseline; bandwidth ingress climbing; cache hit rate dropping
- Logs: High volume of requests from few IPs or user-agents; many 404s to non-existent paths
- Customer impact: Legitimate traffic slowed or rejected; origin overload

### Triage (first 3 minutes)
1. **Quantify traffic**: QPS vs. baseline? Geographic distribution?
   - CDN / edge dashboard: requests by country, IP, URL.
2. **Identify pattern**: Is it volumetric (UDP/TCP flood) or application-layer (HTTP GET/POST flood)?
3. **Check source**: Top IPs / ASNs. Are they from known good crawlers (Googlebot) or obviously malicious?
4. **Assess origin health**: Are backend CPU/memory climbing? Error rate up?

### Mitigation
1. **If CDN / WAF in path:**
   - Enable **Under Attack mode** (Cloudflare) or equivalent DDoS protection.
   - Create rate-limiting rule: block IPs with > N requests per minute.
   - Challenge suspicious user-agents or countries (if business allows).
2. **If application-layer flood on specific endpoint:**
   - Temporarily disable or rate-limit that endpoint at edge / load balancer.
   - Return `429 Too Many Requests` with `Retry-After`.
3. **If origin is already overwhelmed:**
   - Scale origin horizontally immediately.
   - Enable aggressive caching at CDN for static assets.
   - If feasible, serve degraded / static fallback page.
4. **If volumetric (L3/L4) and cloud-native:**
   - Engage cloud provider DDoS response (AWS Shield, GCP Armor).
   - Consider upstream BGP flowspec / blackhole if own infra.

### Verification
- Legitimate traffic error rate < baseline.
- Origin CPU/memory returned to normal.
- Rate-limited / blocked IPs visible in WAF logs.
- No new attack vectors appearing.

### Escalation Triggers
- Attack size exceeds cloud DDoS protection capacity → provider + exec.
- Attack is causing billing spike (egress/ingress) → finance + exec.
- Attack vector is a zero-day exploit, not just flood → security team.
- Customer data exfiltration suspected → security + legal.

### Prevention Action Items
- Implement bot detection and rate-limiting at edge.
- Review CDN cache policies; increase TTL where possible.
- Add application-layer rate limiting (per IP, per user, per API key).
- Subscribe to cloud DDoS protection (AWS Shield Advanced, etc.).
- Run load tests to know capacity ceiling.

---

## Playbook: CDN / Cache Failure

### Detection Signals
- Alert: `CacheHitRateLow`, `OriginOverload`, `CDNErrorRateHigh`
- Metrics: Cache hit rate dropped sharply; origin request rate spiked; CDN status codes > 5%
- Logs: `CACHE_MISS` rate high; origin latency climbing; CDN timeout logs
- Customer impact: Slow page loads; images/assets not loading; origin at risk

### Triage (first 3 minutes)
1. **Check CDN status page** (Cloudflare, Fastly, AWS CloudFront).
2. **Check cache hit rate** by URL pattern:
   - `cdn_cache_hit_ratio` or edge dashboard.
3. **Check for cache purge** (intentional or accidental):
   - Audit logs for `Purge All` or `Purge by URL` API calls.
4. **Check origin health**: Can origin serve the cache-miss load?
   - Origin CPU, error rate, latency.

### Mitigation
1. **If CDN provider incident:**
   - Switch DNS to backup CDN or serve directly from origin with rate-limiting.
   - Enable origin circuit breaker to prevent overload.
2. **If accidental cache purge:**
   - Warm cache by replaying top URLs or triggering cache-warm job.
   - Reduce cache TTL temporarily to avoid serving stale data while warming.
3. **If cache configuration issue (bad rule):**
   - Revert last CDN config change.
   - Verify cache headers from origin (`Cache-Control`, `ETag`).
4. **If origin cannot handle cache miss volume:**
   - Scale origin horizontally.
   - Temporarily increase edge cache TTL for static assets.
   - Serve degraded static page for non-critical paths.

### Verification
- Cache hit rate recovering toward baseline.
- Origin request rate dropping.
- Page load times / asset delivery times normal.
- CDN status page green (if provider incident).

### Escalation Triggers
- CDN provider incident without ETA → engage account team.
- Origin at risk of cascading failure → scale + exec notification.
- Cache corruption (serving wrong content) → rollback config + investigate.

### Prevention Action Items
- Require approval for `Purge All` operations.
- Automate cache-warming after deploys.
- Test failover to origin in chaos engineering exercises.
- Monitor cache hit rate with alert < threshold.

---

## Playbook: Message Queue Backlog

### Detection Signals
- Alert: `QueueDepthHigh`, `ConsumerLag`, `MessageAgeHigh`
- Metrics: Queue depth climbing; consumer lag growing; message age p99 up
- Logs: Consumer errors, retry loops, poison pill messages
- Customer impact: Delayed jobs, stale data, webhook delivery delays

### Triage (first 3 minutes)
1. **Check queue depth and consumer count**:
   - RabbitMQ Management UI, Kafka `consumer-group` lag, SQS approximate number of messages.
2. **Check consumer health**: Are consumers running? Error rate? Restart loops?
   - `kubectl get pods -l app=consumer`
3. **Check for poison pill**: Is one message type causing repeated failures?
   - Look at DLQ (dead-letter queue) depth and error logs.
4. **Check for upstream publishing spike**: Did a deploy increase message volume?

### Mitigation
1. **If consumers are down or scaled too low:**
   - Scale consumer replicas: `kubectl scale deployment/consumer --replicas=<N>`
   - Restart stuck consumers (drain first if stateful).
2. **If poison pill is blocking:**
   - Move poison message to DLQ manually or via admin tool.
   - Identify message ID and route around.
3. **If processing is slow (DB/dependency bottleneck):**
   - Increase consumer concurrency if I/O-bound.
   - Scale dependency (DB read replicas, cache).
   - Temporarily reduce batch size to improve throughput.
4. **If queue is irrecoverably deep and data is re-playable:**
   - Consider truncating and re-publishing from source of truth (last resort).

### Verification
- Queue depth / consumer lag flat or decreasing.
- Message age p99 below threshold.
- Consumer error rate zero.
- Downstream processing (webhooks, DB writes) caught up.

### Escalation Triggers
- Queue is mission-critical (payments, auth tokens) and lag > SLO → exec.
- DLQ is also filling → data loss risk; engage app + data teams.
- Consumer scaling does not reduce lag → architectural bottleneck; escalate to platform.

### Prevention Action Items
- Auto-scale consumers on queue depth.
- Implement DLQ monitoring and replay automation.
- Add message age SLO and alerting.
- Test backpressure handling in load tests.
- Add circuit breaker on message processors to prevent retry storms.

---

## Playbook: Third-Party Dependency Failure

### Detection Signals
- Alert: `ExternalAPITimeout`, `ExternalAPIErrorRate`, `IntegrationDown`
- Metrics: Outbound request latency p99 climbing to dependency; error rate > baseline
- Logs: `timeout`, `connection reset`, `503 Service Unavailable` from third-party
- Customer impact: Features relying on integration broken (payments, auth, maps, etc.)

### Triage (first 3 minutes)
1. **Check third-party status page** (Stripe, Auth0, Twilio, SendGrid, etc.).
2. **Check our outbound metrics**: Is it a timeout (network) or 5xx (their server)?
   - `outbound_http_requests_total{destination="<provider>",status=~"5..|Timeout"}`
3. **Check for recent API key rotation, URL change, or version upgrade** on our side.
4. **Test from another IP / network** to rule out our network path.

### Mitigation
1. **If third-party confirmed down (status page incident):**
   - Enable circuit breaker: fail fast and serve degraded experience.
   - Queue non-critical operations for retry when restored.
   - If critical path, consider fallback provider (secondary payment processor, etc.).
2. **If timeout (network / DNS):**
   - Reduce client timeout to fail faster and free threads.
   - Retry with exponential backoff (respect `Retry-After` header).
3. **If our credential / config issue:**
   - Rollback API key, endpoint URL, or integration version change.
   - Verify key permissions and quotas in provider dashboard.
4. **If rate-limit hit (429):**
   - Reduce request rate; implement token bucket client-side.
   - Check if burst traffic caused by internal retry storm.

### Verification
- Outbound error rate < baseline for 10 minutes.
- Feature functionality restored (end-to-end test).
- Third-party status page all-clear.
- No retry storm or queue backlog remaining.

### Escalation Triggers
- Third-party is payment processor and down > 15 min → exec + finance.
- Third-party is identity provider and users cannot log in → exec + CS.
- No fallback exists and SLA is at risk → product + exec.

### Prevention Action Items
- Implement circuit breaker + fallback for all critical third-party calls.
- Maintain secondary provider for payment / SMS / push gateways.
- Add synthetic monitoring of each integration (probe every 60 seconds).
- Review third-party SLA and ensure ours are not tighter than theirs.

---

## Playbook: Disk Full / Storage Exhaustion

### Detection Signals
- Alert: `DiskSpaceHigh`, `VolumeFull`, `WriteFailures`
- Metrics: Disk utilization > 85% and climbing; I/O errors
- Logs: `No space left on device`, `write error`, WAL archival failures
- Customer impact: Writes failing; new data not persisted; backups failing

### Triage (first 3 minutes)
1. **Identify full volume**: `df -h` or cloud block storage metrics.
2. **Identify largest consumers**: `du -sh /* | sort -rh | head -n 20`
3. **Check for log explosion**: Are application logs filling disk?
   - `journalctl --disk-usage` or `/var/log` size.
4. **Check for temp files / core dumps**: `/tmp`, `/var/crash`.
5. **Check if database WAL / binlog is not archiving**.

### Mitigation
1. **If logs are cause:**
   - Truncate old logs safely: `journalctl --vacuum-time=1d` or rotate logs.
   - Ensure log shipping to central store is working.
2. **If temp / cache files:**
   - Clear safe-to-delete temp directories.
   - Remove old core dumps if not needed.
3. **If database WAL / binlog backlog:**
   - Force archival / push to backup storage.
   - If replication is broken, fix replication to consume WAL.
4. **If legitimate data growth:**
   - Expand volume via cloud console (if EBS/GCP disk, can often expand live).
   - Move cold data to object storage (S3/GCS).

### Verification
- Disk utilization < 70%.
- Writes succeeding (test insert / file create).
- Backups / WAL archival resumed.
- No new `No space left on device` errors.

### Escalation Triggers
- Root volume on node/VM full and system unstable → infra team.
- Data loss because WAL could not archive → data team + exec.
- Expansion not possible (maxed out cloud limit) → infra + exec.

### Prevention Action Items
- Alert at 75% (not 90%) to give headroom.
- Automate log rotation and retention.
- Size storage with 6-month growth projection.
- Use object storage for large / cold data.

---

## Playbook: TLS / Certificate Expiry

### Detection Signals
- Alert: `CertificateExpiringSoon`, `TLSHandshakeFailure`
- Metrics: HTTPS error rate climbing; connection failures on port 443
- Logs: `certificate has expired`, `x509: certificate signed by unknown authority`
- Customer impact: Browsers reject site; API clients fail; mobile apps broken

### Triage (first 3 minutes)
1. **Check certificate expiry**: `openssl s_client -connect <host>:443 -servername <host> | openssl x509 -noout -dates`
2. **Check cert source**: Let's Encrypt, ACM, cert-manager, manual upload?
3. **Check renewal automation**: Is cert-manager running? Are DNS challenges passing?
4. **Check for recent config change** to ingress / load balancer.

### Mitigation
1. **If cert is expired and auto-renew failed:**
   - If cert-manager: Check `CertificateRequest` and `Order` status; fix DNS / HTTP-01 challenge; force renew: `cmctl renew <cert>`.
   - If ACM: Validate DNS / email validation; re-issue via console.
   - If manual: Upload new cert to load balancer / CDN immediately.
2. **If wrong cert served (SNI issue):**
   - Check ingress / load balancer SNI routing rules.
   - Revert last ingress config change.
3. **If intermediate cert missing:**
   - Re-bundle full chain and re-upload.

### Verification
- `openssl s_client` shows valid dates and trusted chain.
- SSL Labs test or `curl -v https://<host>` returns 200 with valid TLS.
- Error rate back to zero.
- Browsers / mobile apps connect successfully.

### Escalation Triggers
- Cannot renew and expiry within 24 hours → infra + exec (revenue risk).
- Root CA / intermediate issue affecting all certs → security team.
- Customers actively unable to use product → CS + exec.

### Prevention Action Items
- Alert 30 days and 7 days before expiry.
- Automate renewal with cert-manager or ACM.
- Monitor cert-manager pod health.
- Add synthetic TLS check to monitoring.

---

## Playbook: Deployment Failure / Rollback Stuck

### Detection Signals
- Alert: `DeploymentStuck`, `ReplicasUnavailable`, `CanaryFailed`
- Metrics: Available replicas < desired; rollout progress stalled
- Logs: CrashLoopBackOff, ImagePullBackOff, Init container failures
- Customer impact: New version not serving; old version scaled down

### Triage (first 3 minutes)
1. **Check rollout status**: `kubectl rollout status deployment/<name>`
2. **Check pod status and events**:
   - `kubectl get pods -l app=<name>`
   - `kubectl describe pod <pod>` — look at Events for `ImagePullBackOff`, `CrashLoopBackOff`, `FailedMount`.
3. **Check init containers** if used.
4. **Check resource quotas / limits**: Is scheduling blocked?
   - `kubectl describe node` for `Insufficient cpu` or `Insufficient memory`.

### Mitigation
1. **If rollout is stuck but not critical:**
   - Pause rollout: `kubectl rollout pause deployment/<name>`
   - Investigate and fix root cause (image tag, config map, secret missing).
2. **If new pods are crashing:**
   - Check container logs: `kubectl logs <pod> --previous`
   - If bad code/config, rollback: `kubectl rollout undo deployment/<name>`
3. **If ImagePullBackOff:**
   - Verify image tag exists in registry.
   - Check image pull secrets.
   - If registry is down, use cached image on nodes or fallback registry.
4. **If quota / scheduling issue:**
   - Scale down non-critical workloads temporarily.
   - Increase node pool size.
   - Reduce resource requests (not limits) if over-provisioned.

### Verification
- All pods Running and Ready.
- Rollout history shows desired revision active.
- Application metrics (error rate, latency) normal.
- End-to-end smoke test passes.

### Escalation Triggers
- Rollback also fails → cluster / platform team immediately.
- Data migration job in deploy caused corruption → data team + rollback.
- Deploy touches auth/security layer and is broken → security team.

### Prevention Action Items
- Require canary / blue-green deploy with automated promotion gates.
- Add pre-deploy validation (image exists, config valid, secrets present).
- Use Helm/Argo pre-sync hooks to validate before rollout.
- Practice rollback in staging regularly.
