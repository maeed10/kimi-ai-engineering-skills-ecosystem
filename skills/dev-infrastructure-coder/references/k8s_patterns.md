# Kubernetes Patterns Reference

Opinionated patterns for Kubernetes manifests, Helm values, and operator configurations. Use when generating Deployment, Service, Ingress, HPA, PDB, NetworkPolicy, and security-hardened pod specs.

---

## Namespace & Resource Governance

### Namespace Template
```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: ${app}-${env}
  labels:
    environment: ${env}
    cost-center: ${team}
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/audit: restricted
    pod-security.kubernetes.io/warn: restricted
```

### ResourceQuota
```yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: compute-quota
  namespace: ${app}-${env}
spec:
  hard:
    requests.cpu: "10"
    requests.memory: 20Gi
    limits.cpu: "20"
    limits.memory: 40Gi
    pods: "50"
    services: "10"
    secrets: "20"
    configmaps: "20"
```

### LimitRange
```yaml
apiVersion: v1
kind: LimitRange
metadata:
  name: default-limits
  namespace: ${app}-${env}
spec:
  limits:
    - default:
        cpu: "500m"
        memory: "512Mi"
      defaultRequest:
        cpu: "100m"
        memory: "128Mi"
      type: Container
```

---

## Deployment Patterns

### Standard Web Deployment
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ${app}
  namespace: ${app}-${env}
  labels:
    app.kubernetes.io/name: ${app}
    app.kubernetes.io/version: "${version}"
    app.kubernetes.io/component: api
    app.kubernetes.io/part-of: ${system}
    app.kubernetes.io/managed-by: terraform
spec:
  replicas: ${replicas}
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 25%
      maxUnavailable: 0
  selector:
    matchLabels:
      app.kubernetes.io/name: ${app}
  template:
    metadata:
      labels:
        app.kubernetes.io/name: ${app}
        app.kubernetes.io/version: "${version}"
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "8080"
        prometheus.io/path: "/metrics"
    spec:
      serviceAccountName: ${app}-sa
      securityContext:
        runAsNonRoot: true
        seccompProfile:
          type: RuntimeDefault
      containers:
        - name: ${app}
          image: "${registry}/${app}:${version}"
          imagePullPolicy: IfNotPresent
          ports:
            - name: http
              containerPort: 8080
              protocol: TCP
          resources:
            requests:
              cpu: 100m
              memory: 128Mi
            limits:
              cpu: 500m
              memory: 512Mi
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities:
              drop:
                - ALL
          livenessProbe:
            httpGet:
              path: /healthz
              port: http
            initialDelaySeconds: 10
            periodSeconds: 10
            timeoutSeconds: 5
            failureThreshold: 3
          readinessProbe:
            httpGet:
              path: /ready
              port: http
            initialDelaySeconds: 5
            periodSeconds: 5
            timeoutSeconds: 3
            failureThreshold: 3
          startupProbe:
            httpGet:
              path: /healthz
              port: http
            initialDelaySeconds: 5
            periodSeconds: 5
            failureThreshold: 30
          volumeMounts:
            - name: tmp
              mountPath: /tmp
            - name: config
              mountPath: /etc/${app}/config.yaml
              subPath: config.yaml
              readOnly: true
      volumes:
        - name: tmp
          emptyDir: {}
        - name: config
          configMap:
            name: ${app}-config
            optional: false
      affinity:
        podAntiAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
            - weight: 100
              podAffinityTerm:
                labelSelector:
                  matchLabels:
                    app.kubernetes.io/name: ${app}
                topologyKey: kubernetes.io/hostname
      topologySpreadConstraints:
        - maxSkew: 1
          topologyKey: topology.kubernetes.io/zone
          whenUnsatisfiable: ScheduleAnyway
          labelSelector:
            matchLabels:
              app.kubernetes.io/name: ${app}
```

### CronJob Pattern
```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: ${app}-job
  namespace: ${app}-${env}
spec:
  schedule: "0 2 * * *"
  timeZone: "UTC"
  concurrencyPolicy: Forbid
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 3
  jobTemplate:
    spec:
      activeDeadlineSeconds: 3600
      ttlSecondsAfterFinished: 86400
      template:
        spec:
          serviceAccountName: ${app}-job-sa
          securityContext:
            runAsNonRoot: true
            seccompProfile:
              type: RuntimeDefault
          containers:
            - name: job
              image: "${registry}/${app}:${version}"
              command: ["/bin/sh", "-c", "exec ./job"]
              resources:
                requests:
                  cpu: 100m
                  memory: 128Mi
                limits:
                  cpu: 500m
                  memory: 512Mi
              securityContext:
                allowPrivilegeEscalation: false
                readOnlyRootFilesystem: true
                capabilities:
                  drop:
                    - ALL
              volumeMounts:
                - name: tmp
                  mountPath: /tmp
          volumes:
            - name: tmp
              emptyDir: {}
          restartPolicy: OnFailure
```

### DaemonSet Pattern (Node Agent)
```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: ${app}-agent
  namespace: ${app}-${env}
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: ${app}-agent
  template:
    metadata:
      labels:
        app.kubernetes.io/name: ${app}-agent
    spec:
      serviceAccountName: ${app}-agent-sa
      hostNetwork: false
      securityContext:
        runAsNonRoot: true
        seccompProfile:
          type: RuntimeDefault
      containers:
        - name: agent
          image: "${registry}/${app}-agent:${version}"
          resources:
            requests:
              cpu: 50m
              memory: 64Mi
            limits:
              cpu: 200m
              memory: 256Mi
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities:
              drop:
                - ALL
          volumeMounts:
            - name: host-logs
              mountPath: /var/log/host
              readOnly: true
      volumes:
        - name: host-logs
          hostPath:
            path: /var/log
            type: Directory
```

---

## Service Patterns

### ClusterIP (Internal)
```yaml
apiVersion: v1
kind: Service
metadata:
  name: ${app}
  namespace: ${app}-${env}
  labels:
    app.kubernetes.io/name: ${app}
spec:
  type: ClusterIP
  selector:
    app.kubernetes.io/name: ${app}
  ports:
    - name: http
      port: 80
      targetPort: http
      protocol: TCP
```

### LoadBalancer (Public, cloud-only)
```yaml
apiVersion: v1
kind: Service
metadata:
  name: ${app}-lb
  namespace: ${app}-${env}
  annotations:
    service.beta.kubernetes.io/aws-load-balancer-type: "nlb"
    service.beta.kubernetes.io/aws-load-balancer-scheme: "internet-facing"
    service.beta.kubernetes.io/aws-load-balancer-healthcheck-path: /healthz
    service.beta.kubernetes.io/aws-load-balancer-ssl-cert: ${acm_cert_arn}
    service.beta.kubernetes.io/aws-load-balancer-ssl-ports: "443"
spec:
  type: LoadBalancer
  selector:
    app.kubernetes.io/name: ${app}
  ports:
    - name: https
      port: 443
      targetPort: http
      protocol: TCP
```

### Headless Service (StatefulSet)
```yaml
apiVersion: v1
kind: Service
metadata:
  name: ${app}-headless
  namespace: ${app}-${env}
spec:
  type: ClusterIP
  clusterIP: None
  selector:
    app.kubernetes.io/name: ${app}
  ports:
    - name: http
      port: 8080
      targetPort: http
```

---

## Ingress Patterns

### Ingress with TLS (nginx ingress controller)
```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: ${app}
  namespace: ${app}-${env}
  annotations:
    nginx.ingress.kubernetes.io/rewrite-target: /
    nginx.ingress.kubernetes.io/rate-limit: "100"
    nginx.ingress.kubernetes.io/rate-limit-window: "1m"
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    nginx.ingress.kubernetes.io/proxy-body-size: "10m"
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
spec:
  ingressClassName: nginx
  tls:
    - hosts:
        - ${app}.${domain}
      secretName: ${app}-tls
  rules:
    - host: ${app}.${domain}
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: ${app}
                port:
                  number: 80
```

### AWS ALB Ingress (AWS Load Balancer Controller)
```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: ${app}
  namespace: ${app}-${env}
  annotations:
    alb.ingress.kubernetes.io/scheme: internet-facing
    alb.ingress.kubernetes.io/target-type: ip
    alb.ingress.kubernetes.io/listen-ports: '[{"HTTPS":443}]'
    alb.ingress.kubernetes.io/certificate-arn: ${acm_cert_arn}
    alb.ingress.kubernetes.io/healthcheck-path: /healthz
    alb.ingress.kubernetes.io/ssl-policy: ELBSecurityPolicy-TLS13-1-2-2021-06
spec:
  ingressClassName: alb
  rules:
    - host: ${app}.${domain}
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: ${app}
                port:
                  number: 80
```

---

## ConfigMap & Secret Patterns

### ConfigMap
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: ${app}-config
  namespace: ${app}-${env}
data:
  config.yaml: |
    server:
      port: 8080
      log_level: info
    database:
      pool_size: 20
      max_overflow: 10
```

### Secret (Opaque)
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: ${app}-secrets
  namespace: ${app}-${env}
type: Opaque
stringData:
  DB_PASSWORD: ${db_password}
  API_KEY: ${api_key}
```

> **Never commit raw Secret YAML.** Use External Secrets Operator, Sealed Secrets, or SOPS.

---

## HorizontalPodAutoscaler (HPA)

### CPU + Memory Based
```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: ${app}
  namespace: ${app}-${env}
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: ${app}
  minReplicas: 2
  maxReplicas: 20
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 60
    - type: Resource
      resource:
        name: memory
        target:
          type: Utilization
          averageUtilization: 70
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
        - type: Percent
          value: 10
          periodSeconds: 60
    scaleUp:
      stabilizationWindowSeconds: 0
      policies:
        - type: Percent
          value: 100
          periodSeconds: 15
        - type: Pods
          value: 4
          periodSeconds: 15
      selectPolicy: Max
```

### Custom Metrics (Prometheus Adapter / KEDA)
```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: ${app}-custom
  namespace: ${app}-${env}
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: ${app}
  minReplicas: 2
  maxReplicas: 50
  metrics:
    - type: Pods
      pods:
        metric:
          name: http_requests_per_second
        target:
          type: AverageValue
          averageValue: "100"
```

---

## PodDisruptionBudget (PDB)

### Min Available
```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: ${app}
  namespace: ${app}-${env}
spec:
  minAvailable: 1
  selector:
    matchLabels:
      app.kubernetes.io/name: ${app}
```

### Max Unavailable (preferred for rolling updates)
```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: ${app}
  namespace: ${app}-${env}
spec:
  maxUnavailable: 25%
  selector:
    matchLabels:
      app.kubernetes.io/name: ${app}
```

---

## NetworkPolicy Patterns

### Default Deny All (Namespace)
```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-all
  namespace: ${app}-${env}
spec:
  podSelector: {}
  policyTypes:
    - Ingress
    - Egress
```

### Allow Ingress from Same Namespace
```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-same-namespace
  namespace: ${app}-${env}
spec:
  podSelector: {}
  ingress:
    - from:
        - podSelector: {}
  policyTypes:
    - Ingress
```

### Allow Ingress from Specific Namespace
```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-from-monitoring
  namespace: ${app}-${env}
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: ${app}
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              name: monitoring
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: prometheus
      ports:
        - protocol: TCP
          port: 8080
  policyTypes:
    - Ingress
```

### Allow Egress to DNS and External HTTPS Only
```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-limited-egress
  namespace: ${app}-${env}
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: ${app}
  egress:
    - to:
        - namespaceSelector: {}
          podSelector:
            matchLabels:
              k8s-app: kube-dns
      ports:
        - protocol: UDP
          port: 53
    - to: []
      ports:
        - protocol: TCP
          port: 443
  policyTypes:
    - Egress
```

---

## SecurityContext Patterns

### Pod-Level Security Context
```yaml
spec:
  securityContext:
    runAsNonRoot: true
    runAsUser: 1000
    runAsGroup: 1000
    fsGroup: 1000
    fsGroupChangePolicy: OnRootMismatch
    seccompProfile:
      type: RuntimeDefault
```

### Container-Level Security Context
```yaml
securityContext:
  allowPrivilegeEscalation: false
  readOnlyRootFilesystem: true
  privileged: false
  capabilities:
    drop:
      - ALL
  seccompProfile:
    type: RuntimeDefault
```

### Exception Pattern (Only when absolutely required)
```yaml
securityContext:
  allowPrivilegeEscalation: false
  readOnlyRootFilesystem: true
  capabilities:
    add:
      - NET_BIND_SERVICE
    drop:
      - ALL
```

---

## RBAC Patterns

### ServiceAccount
```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: ${app}-sa
  namespace: ${app}-${env}
automountServiceAccountToken: false
```

### Role (Namespaced)
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: ${app}-role
  namespace: ${app}-${env}
rules:
  - apiGroups: [""]
    resources: ["configmaps", "secrets"]
    verbs: ["get", "list", "watch"]
  - apiGroups: [""]
    resources: ["pods"]
    verbs: ["get", "list", "watch"]
```

### RoleBinding
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: ${app}-binding
  namespace: ${app}-${env}
subjects:
  - kind: ServiceAccount
    name: ${app}-sa
    namespace: ${app}-${env}
roleRef:
  kind: Role
  name: ${app}-role
  apiGroup: rbac.authorization.k8s.io
```

### ClusterRole (Read-only for nodes/agents)
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: ${app}-node-reader
rules:
  - apiGroups: [""]
    resources: ["nodes", "namespaces"]
    verbs: ["get", "list", "watch"]
```

---

## Storage Patterns

### PersistentVolumeClaim (General)
```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: ${app}-data
  namespace: ${app}-${env}
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 10Gi
  storageClassName: gp3-retained
```

### StatefulSet with VolumeClaimTemplate
```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: ${app}
  namespace: ${app}-${env}
spec:
  serviceName: ${app}-headless
  replicas: 3
  selector:
    matchLabels:
      app.kubernetes.io/name: ${app}
  template:
    metadata:
      labels:
        app.kubernetes.io/name: ${app}
    spec:
      serviceAccountName: ${app}-sa
      securityContext:
        runAsNonRoot: true
        seccompProfile:
          type: RuntimeDefault
      containers:
        - name: ${app}
          image: "${registry}/${app}:${version}"
          resources:
            requests:
              cpu: 250m
              memory: 512Mi
            limits:
              cpu: 1000m
              memory: 1Gi
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities:
              drop:
                - ALL
          volumeMounts:
            - name: data
              mountPath: /data
            - name: tmp
              mountPath: /tmp
      volumes:
        - name: tmp
          emptyDir: {}
  volumeClaimTemplates:
    - metadata:
        name: data
      spec:
        accessModes: ["ReadWriteOnce"]
        resources:
          requests:
            storage: 10Gi
        storageClassName: gp3-retained
```

---

## Observability Sidecars

### Prometheus Exporter Sidecar
```yaml
- name: exporter
  image: prom/node-exporter:v1.7.0
  ports:
    - name: metrics
      containerPort: 9100
  resources:
    requests:
      cpu: 10m
      memory: 32Mi
    limits:
      cpu: 50m
      memory: 64Mi
  securityContext:
    allowPrivilegeEscalation: false
    readOnlyRootFilesystem: true
    capabilities:
      drop:
        - ALL
```

### Fluent Bit Log Forwarder
```yaml
- name: fluent-bit
  image: fluent/fluent-bit:2.2
  volumeMounts:
    - name: varlog
      mountPath: /var/log
    - name: fluent-bit-config
      mountPath: /fluent-bit/etc/
  resources:
    requests:
      cpu: 25m
      memory: 64Mi
    limits:
      cpu: 100m
      memory: 128Mi
```

---

## Helm Values Baseline

When generating `values.yaml` for Helm charts, include these defaults:

```yaml
replicaCount: 2

image:
  repository: "${registry}/${app}"
  tag: ""
  pullPolicy: IfNotPresent

imagePullSecrets: []
nameOverride: ""
fullnameOverride: ""

serviceAccount:
  create: true
  annotations: {}
  automount: false

podAnnotations: {}

podSecurityContext:
  runAsNonRoot: true
  seccompProfile:
    type: RuntimeDefault

securityContext:
  allowPrivilegeEscalation: false
  readOnlyRootFilesystem: true
  capabilities:
    drop:
      - ALL

service:
  type: ClusterIP
  port: 80
  targetPort: 8080

ingress:
  enabled: true
  className: nginx
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
  hosts:
    - host: ${app}.${domain}
      paths:
        - path: /
          pathType: Prefix
  tls:
    - secretName: ${app}-tls
      hosts:
        - ${app}.${domain}

resources:
  requests:
    cpu: 100m
    memory: 128Mi
  limits:
    cpu: 500m
    memory: 512Mi

autoscaling:
  enabled: true
  minReplicas: 2
  maxReplicas: 20
  targetCPUUtilizationPercentage: 60
  targetMemoryUtilizationPercentage: 70

pdb:
  enabled: true
  minAvailable: 1

nodeSelector: {}
tolerations: []
affinity:
  podAntiAffinity:
    preferredDuringSchedulingIgnoredDuringExecution:
      - weight: 100
        podAffinityTerm:
          labelSelector:
            matchLabels:
              app.kubernetes.io/name: ${app}
          topologyKey: kubernetes.io/hostname
```

---

## Validation Commands

Always run these against generated manifests:

```bash
# Schema validation against multiple Kubernetes versions
kubeconform -kubernetes-version 1.29 -strict -summary manifests/

# Security posture scan
kubescape scan manifests/ --severity-threshold high

# Misconfiguration scan (Trivy)
trivy config manifests/

# Helm lint (if applicable)
helm lint ./chart
helm template ./chart | kubeconform -strict -summary
```
