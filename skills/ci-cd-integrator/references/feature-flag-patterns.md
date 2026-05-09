# Feature Flag Coordination Patterns

Reference for integrating feature flags into canary deployment stages.

---

## Provider Detection

The CI/CD Integrator detects the feature flag provider by checking, in order:

1. Environment variable `LAUNCHDARKLY_SDK_KEY` or `LD_SDK_KEY` → LaunchDarkly
2. Environment variable `UNLEASH_URL` or `UNLEASH_API_TOKEN` → Unleash
3. File `feature-flags.yml` or `feature-flags.yaml` in repo root → Config-based
4. File `flags.json` in repo root → Config-based fallback

If none are found, the pipeline defaults to **config-based flags**.

---

## LaunchDarkly

### SDK Client (application-side)

```python
import ldclient
from ldclient.config import Config

ldclient.set_config(Config("sdk-key-from-env"))
client = ldclient.get()

# Use canary context to target percentage
canary_context = {"kind": "user", "key": "canary-segment"}
flag_value = client.variation("my-new-feature", canary_context, False)
```

### CI/CD Stage — Progressive Enablement

```yaml
  - name: LaunchDarkly Canary Ramp
    env:
      LD_API_TOKEN: ${{ secrets.LD_API_TOKEN }}
      LD_PROJECT: my-project
      LD_ENV: production
    run: |
      CANARY_PCT=${CANARY_TRAFFIC}
      echo "[FEATURE_FLAG] Ramping LaunchDarkly flag to ${CANARY_PCT}%"

      # Update flag targeting rule for canary segment
      curl -s -X PATCH "https://app.launchdarkly.com/api/v2/flags/${LD_PROJECT}/${FLAG_KEY}" \
        -H "Authorization: ${LD_API_TOKEN}" \
        -H "Content-Type: application/json; domain-model=launchdarkly.semanticpatch" \
        -d "{
          \"patch\": [{
            \"op\": \"replace\",
            \"path\": \"/environments/${LD_ENV}/rules/0\",
            \"value\": {
              \"variation\": 0,
              \"clauses\": [{ \"attribute\": \"canary\", \"op\": \"in\", \"values\": [true], \"negate\": false }],
              \"trackEvents\": true,
              \"rollout\": { \"bucketBy\": \"key\", \"variations\": [{ \"variation\": 0, \"weight\": ${CANARY_PCT}00 }] }
            }
          }]
        }"
```

> Weight is expressed in thousandths (e.g., 5000 = 50%).

### Kill Switch

```bash
# Disable flag immediately — all users get `false` (off variation)
curl -s -X PATCH "https://app.launchdarkly.com/api/v2/flags/${LD_PROJECT}/${FLAG_KEY}" \
  -H "Authorization: ${LD_API_TOKEN}" \
  -d '{
    "patch": [{ "op": "replace", "path": "/environments/'"${LD_ENV}"'/on", "value": false }]
  }'
```

---

## Unleash

### SDK Client (application-side)

```python
from UnleashClient import UnleashClient

client = UnleashClient(
    url=os.getenv("UNLEASH_URL"),
    custom_headers={"Authorization": os.getenv("UNLEASH_API_TOKEN")},
    app_name="my-app"
)
client.initialize()

enabled = client.is_enabled("my-new-feature")
```

### CI/CD Stage — Progressive Enablement

```yaml
  - name: Unleash Canary Ramp
    env:
      UNLEASH_URL: ${{ secrets.UNLEASH_URL }}
      UNLEASH_API_TOKEN: ${{ secrets.UNLEASH_API_TOKEN }}
    run: |
      CANARY_PCT=${CANARY_TRAFFIC}
      echo "[FEATURE_FLAG] Ramping Unleash flag to ${CANARY_PCT}%"

      # Update flexibleRollout strategy
      curl -s -X PUT "${UNLEASH_URL}/api/admin/projects/default/features/${FLAG_NAME}" \
        -H "Authorization: ${UNLEASH_API_TOKEN}" \
        -H "Content-Type: application/json" \
        -d "{
          \"name\": \"${FLAG_NAME}\",
          \"enabled\": true,
          \"strategies\": [{
            \"name\": \"flexibleRollout\",
            \"parameters\": {
              \"rollout\": \"${CANARY_PCT}\",
              \"stickiness\": \"default\",
              \"groupId\": \"${FLAG_NAME}\"
            },
            \"constraints\": []
          }]
        }"
```

### Kill Switch

```bash
# Disable strategy or set rollout to 0
curl -s -X PUT "${UNLEASH_URL}/api/admin/projects/default/features/${FLAG_NAME}" \
  -H "Authorization: ${UNLEASH_API_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "'"${FLAG_NAME}"'",
    "enabled": false,
    "strategies": []
  }'
```

---

## Config-Based Flags (`feature-flags.yml`)

### File Format

```yaml
# feature-flags.yml
flags:
  my-new-feature:
    enabled: true
    rollout_percentage: 5
    stickiness: user-id
    kill_switch: false
```

### CI/CD Stage — Progressive Enablement

```yaml
  - name: Update Feature Flags Config
    run: |
      CANARY_PCT=${CANARY_TRAFFIC}
      echo "[FEATURE_FLAG] Updating feature-flags.yml to ${CANARY_PCT}%"

      sed -i "s/rollout_percentage: .*/rollout_percentage: ${CANARY_PCT}/" feature-flags.yml

      git config user.name "ci-bot"
      git config user.email "ci@example.com"
      git add feature-flags.yml
      git commit -m "ci: ramp my-new-feature to ${CANARY_PCT}%"
      git push origin HEAD:${GITHUB_REF_NAME}
```

For environments that do **not** auto-reload config:

```yaml
  - name: Trigger Config Reload
    run: |
      # Option A: Kubernetes ConfigMap reload
      kubectl create configmap feature-flags \
        --from-file=feature-flags.yml -o yaml --dry-run=client | kubectl apply -f -
      kubectl rollout restart deployment/my-app -n <namespace>

      # Option B: S3 / GCS hosted config
      aws s3 cp feature-flags.yml s3://<bucket>/config/feature-flags.yml
```

### Kill Switch

```bash
# Immediate disable via sed or yq
sed -i "s/enabled: true/enabled: false/" feature-flags.yml
# Or target a specific flag
yq eval '.flags.my-new-feature.enabled = false' -i feature-flags.yml
```

---

## Feature Flag Ramp Plan

Default canary progression with flag coordination:

| Stage | Traffic % | Flag Rollout % | Action on Regression |
|-------|-----------|---------------|----------------------|
| Canary 5% | 5% | 5% | Kill flag, abort rollout, trigger rollback |
| Canary 25% | 25% | 25% | Kill flag, abort rollout, trigger rollback |
| Canary 50% | 50% | 50% | Kill flag, abort rollout, trigger rollback |
| Canary 100% | 100% | 100% | Kill flag, revert traffic to stable revision |

### Gate Logic

```yaml
  - name: Metric Gate + Kill Switch
    run: |
      echo "[ROLLBACK_GATE] Checking SLOs before next ramp..."
      # Query metrics backend (Prometheus, Datadog, CloudWatch)
      ERROR_RATE=$(curl -s "<metrics-query-url>" | jq '.data.result[0].value[1]')
      P99=$(curl -s "<metrics-query-url-p99>" | jq '.data.result[0].value[1]')

      if (( $(echo "$ERROR_RATE > $ROLLBACK_ERROR_RATE" | bc -l) )) || \
         (( $(echo "$P99 > $ROLLBACK_P99_MS" | bc -l) )); then
        echo "[FAIL] SLO breached. Executing kill switch and rollback."
        # Invoke provider-specific kill switch here
        exit 1
      fi
```

---

## Safety Rules for Feature Flags

- **ALWAYS** implement a kill switch that can disable a flag in <30 seconds.
- **ALWAYS** separate flag enablement from code deployment; deploy code first, ramp flag second.
- **NEVER** use feature flags for long-term branching; flags should be temporary (target lifetime <2 weeks).
- **NEVER** skip metric validation before increasing traffic percentage.
- **ALWAYS** log flag evaluation decisions for debugging.
