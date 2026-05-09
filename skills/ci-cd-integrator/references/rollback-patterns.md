# Rollback Patterns by Deployment Target

Reference for automated and manual rollback procedures across common deployment targets.

---

## Kubernetes (Deployment / ReplicaSet)

### Automated Rollback

```bash
# Undo the last rollout
kubectl rollout undo deployment/<deployment-name> -n <namespace>

# Roll back to a specific revision
kubectl rollout undo deployment/<deployment-name> --to-revision=<N> -n <namespace>
```

### Argo Rollouts (Canary/Blue-Green)

```bash
# Abort an in-progress rollout
kubectl argo rollouts abort <rollout-name> -n <namespace>

# Retry after abort
kubectl argo rollouts retry <rollout-name> -n <namespace>
```

Argo Rollouts automatically reverts traffic to the stable ReplicaSet on abort.

### Helm

```bash
# Roll back to previous release
helm rollback <release-name> <revision> -n <namespace>
```

### Manual Fallback

1. Identify last stable image tag from CI artifact registry
2. `kubectl set image deployment/<name> container=<stable-image> -n <namespace>`
3. `kubectl rollout status deployment/<name> -n <namespace>`
4. Verify pod readiness and traffic health

---

## AWS ECS (Fargate / EC2)

### Automated Rollback

ECS circuit breaker (enabled by default in new services) automatically rolls back
failed deployments. To force manual rollback:

```bash
# Update service to prior stable task definition
aws ecs update-service \
  --cluster <cluster-name> \
  --service <service-name> \
  --task-definition <stable-task-def-family>:<stable-revision> \
  --force-new-deployment
```

### Blue/Green via CodeDeploy

```bash
# Stop an in-progress deployment
aws deploy stop-deployment --deployment-id <deployment-id>

# Re-route traffic to original (blue) task set
aws ecs update-service-primary-task-set \
  --cluster <cluster-name> \
  --service <service-name> \
  --primary-task-set <blue-task-set-arn>
```

### Manual Fallback

1. Find last stable task definition revision in ECS console or via `aws ecs describe-task-definition`
2. Update service to that revision
3. Verify target group health checks pass

---

## AWS Lambda

### Automated Rollback

```bash
# Revert alias to previous version
aws lambda update-alias \
  --function-name <function-name> \
  --name <alias-name> \
  --function-version <stable-version>

# Or use AWS CodeDeploy hooks (PreTraffic / PostTraffic) to abort
```

### Manual Fallback

1. Identify stable version from CloudWatch metrics / CI artifact tag
2. Update alias to stable version
3. Verify invocation error rate via CloudWatch

---

## Azure Container Instances / Azure App Service

### Azure App Service (Deployment Slots)

```bash
# Swap back to previous slot
az webapp deployment slot swap \
  --resource-group <rg> \
  --name <app-name> \
  --slot <staging-slot> \
  --action swap

# Or directly revert to last known good container
az webapp config container set \
  --name <app-name> \
  --resource-group <rg> \
  --docker-custom-image-name <stable-image>
```

### Azure Kubernetes Service (AKS)

Same as Kubernetes section above, plus:

```bash
# Use AKS rollback via Azure CLI
az aks command invoke \
  --resource-group <rg> \
  --name <cluster> \
  --command "kubectl rollout undo deployment/<name> -n <ns>"
```

---

## Google Cloud Run

```bash
# List revisions
gcloud run revisions list --service=<service> --region=<region>

# Roll back to a specific revision
gcloud run services update-traffic <service> \
  --to-revisions <revision-name>=100 \
  --region=<region>
```

Cloud Run automatically keeps prior revisions; traffic split changes are immediate.

---

## VM / Static Hosts (Ansible / SSH / rsync)

### Blue/Green with Load Balancer

```bash
# Swap load balancer target from green back to blue
# Example: AWS ALB target group swap
aws elbv2 register-targets --target-group-arn <blue-tg-arn> --targets ...
aws elbv2 deregister-targets --target-group-arn <green-tg-arn> --targets ...
```

### Direct Redeploy

```bash
# Re-deploy prior artifact
ansible-playbook -i inventory deploy.yml \
  -e artifact_url=<stable-artifact-url> \
  -e rollback=true
```

### Manual Fallback

1. Locate last stable artifact in artifact store (S3, GCS, Artifactory, etc.)
2. Stop new service/version on affected hosts
3. Re-deploy stable artifact via CI pipeline or ad-hoc script
4. Verify health endpoint on each host before re-adding to LB

---

## Rollback Decision Matrix

| Target | Auto-Rollback Trigger | Rollback Latency | Manual Fallback Complexity |
|--------|----------------------|------------------|--------------------------|
| Kubernetes Deployment | rollout failure / custom metric | 10-60s | Low (`kubectl rollout undo`) |
| Argo Rollouts | metric breach / abort | 5-30s | Low (`abort` command) |
| ECS (circuit breaker) | deployment failure | 1-5 min | Medium (task def swap) |
| ECS Blue/Green | CodeDeploy hook abort | 1-5 min | Medium (task set swap) |
| Lambda | CodeDeploy hook / alias | <1s | Low (alias version update) |
| Azure App Service | slot swap / health check | 10-30s | Low (slot swap) |
| Cloud Run | traffic split revision | <1s | Low (traffic update) |
| VM / Static | external LB health check | 1-10 min | High (host-by-host redeploy) |

---

## Rollback Checklist

- [ ] Identify last known stable artifact tag / revision / version
- [ ] Confirm current deployment target and namespace/region/service
- [ ] Execute platform-specific rollback command
- [ ] Verify traffic/error metrics return to baseline within SLO window
- [ ] Notify on-call and stakeholders
- [ ] Capture incident timeline and root-cause artifacts (logs, metrics)
- [ ] Update incident documentation and schedule post-mortem if SLO was breached
