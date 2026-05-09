# Security Hardening Guide

Comprehensive security hardening patterns for Docker containers, from basic least-privilege configurations to advanced kernel-level restrictions.

## Table of Contents

- [Non-Root User](#non-root-user)
- [Read-Only Filesystem](#read-only-filesystem)
- [Linux Capabilities](#linux-capabilities)
- [Distroless Images](#distroless-images)
- [No-New-Privileges](#no-new-privileges)
- [Seccomp & AppArmor](#seccomp--apparmor)
- [Secrets Management](#secrets-management)
- [Vulnerability Scanning Integration](#vulnerability-scanning-integration)

---

## Non-Root User

### Principle

Run the application process as an unprivileged user to limit the blast radius of container escapes and runtime exploits.

### Dockerfile Pattern

```dockerfile
# Create a non-root user with fixed UID/GID for predictable host mapping
RUN groupadd -r appgroup --gid=1000 && \
    useradd -r -g appgroup --uid=1000 appuser

# Or on Alpine:
RUN addgroup -g 1000 -S appgroup && \
    adduser -u 1000 -S appuser -G appgroup

# Set ownership during copy to avoid extra RUN chown layer
COPY --chown=appuser:appgroup . /app

USER appuser:appgroup
```

### Why Fixed UID/GID?

- **Host volume permissions**: When bind-mounting host directories, the container UID must match the host UID for write access
- **Kubernetes security contexts**: `runAsUser: 1000` requires a known numeric ID
- **Auditability**: Named users without explicit UIDs may vary across image rebuilds

### Docker Compose

```yaml
services:
  app:
    user: "1000:1000"
```

### Kubernetes

```yaml
securityContext:
  runAsNonRoot: true
  runAsUser: 1000
  runAsGroup: 1000
  fsGroup: 1000
```

### Common Pitfall: Binding to Port < 1024

Non-root users cannot bind to privileged ports. Options:

1. **Use unprivileged ports** (recommended): `EXPOSE 8080` instead of `80`
2. **Ambient capabilities** (advanced): `cap_add: [NET_BIND_SERVICE]` + `setcap cap_net_bind_service=+ep`
3. **External port mapping**: Map host 80 → container 8080

---

## Read-Only Filesystem

### Principle

Mount the container root filesystem as read-only to prevent attackers from writing binaries, modifying configuration, or tampering with application code.

### Docker Compose

```yaml
services:
  app:
    read_only: true
```

### Docker Run

```bash
docker run --read-only myapp:latest
```

### Writable Directories with tmpfs

Applications usually need temporary write paths for logs, caches, uploads, or PID files. Mount these as ephemeral tmpfs volumes:

```yaml
services:
  app:
    read_only: true
    tmpfs:
      - /tmp:noexec,nosuid,size=100m
      - /var/tmp:noexec,nosuid,size=50m
      - /app/tmp:noexec,nosuid,size=50m
```

### Kubernetes

```yaml
securityContext:
  readOnlyRootFilesystem: true
volumeMounts:
  - name: tmp
    mountPath: /tmp
volumes:
  - name: tmp
    emptyDir:
      sizeLimit: 100Mi
```

### Dockerfile Preparation

Ensure the application does not attempt to write to the application code directory at runtime:

```dockerfile
# Pre-create directories and set ownership in build stage
RUN mkdir -p /app/tmp /app/logs && chown -R appuser:appgroup /app/tmp /app/logs
```

---

## Linux Capabilities

### Principle

Drop all capabilities and add back only the specific ones required. This follows the principle of least privilege at the kernel syscall level.

### Default Dangerous Capabilities

| Capability | Risk |
|------------|------|
| `CAP_SYS_ADMIN` | Equivalent to root; container escape trivial |
| `CAP_SYS_PTRACE` | Debug other processes; escape vector |
| `CAP_SYS_MODULE` | Load kernel modules |
| `CAP_DAC_READ_SEARCH` | Bypass file read permissions |
| `CAP_SETUID` | Change process UID; privilege escalation |
| `CAP_SETGID` | Change process GID; privilege escalation |
| `CAP_NET_ADMIN` | Configure network interfaces, iptables |
| `CAP_NET_RAW` | Create raw sockets; packet sniffing, ARP spoofing |

### Safe Minimal Set

Most web applications require **no capabilities at all**:

```yaml
services:
  app:
    cap_drop:
      - ALL
    # cap_add: []   # none needed for port 8080
```

### When Capabilities Are Needed

| Use Case | Capability | Notes |
|----------|-----------|-------|
| Bind to port < 1024 | `NET_BIND_SERVICE` | Better to use port 8080 |
| Ping / ICMP | `NET_RAW` | Use unprivileged ping or avoid |
| Packet capture | `NET_RAW` | Debugging only; never in production |
| Time sync | `SYS_TIME` | Use host NTP instead |
| Mount volumes | `SYS_ADMIN` | Reconsider architecture |

### Docker Compose with One Capability

```yaml
services:
  app:
    cap_drop:
      - ALL
    cap_add:
      - NET_BIND_SERVICE
```

---

## Distroless Images

### Principle

Remove the shell, package manager, and unnecessary OS utilities from the runtime image. If an attacker compromises the application, there is no `sh`, `curl`, or `apt` to facilitate lateral movement.

### Google Distroless Family

| Image | Use Case |
|-------|----------|
| `gcr.io/distroless/static` | Static binaries (Go, C) |
| `gcr.io/distroless/static:nonroot` | Static binaries as non-root |
| `gcr.io/distroless/cc` | C/C++ dependencies (Rust, C++) |
| `gcr.io/distroless/python3` | Python applications |
| `gcr.io/distroless/nodejs22` | Node.js applications |
| `gcr.io/distroless/java21` | Java applications |

### Go Example (Scratch)

```dockerfile
FROM golang:1.22-alpine AS builder
WORKDIR /app
COPY . .
RUN CGO_ENABLED=0 go build -o /bin/server ./cmd/server

FROM scratch
COPY --from=builder /bin/server /server
COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/
USER 65534:65534
EXPOSE 8080
ENTRYPOINT ["/server"]
```

### Node.js Example (Distroless)

```dockerfile
FROM node:22-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci --ignore-scripts
COPY . .
RUN npm run build

FROM gcr.io/distroless/nodejs22
WORKDIR /app
COPY --from=builder /app/dist ./dist
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./
ENV NODE_ENV=production
EXPOSE 3000
CMD ["dist/main.js"]
```

> Distroless images have no shell. Debugging requires:
> - `docker inspect` for config
> - Sidecar debug containers (Kubernetes ephemeral containers)
> - Copying files out with `docker cp`

---

## No-New-Privileges

### Principle

Prevent processes from gaining additional privileges via `setuid` binaries or file capabilities. Even if a vulnerable `setuid` binary exists in the image, it cannot escalate privileges.

### Docker Compose

```yaml
services:
  app:
    security_opt:
      - no-new-privileges:true
```

### Docker Run

```bash
docker run --security-opt no-new-privileges:true myapp:latest
```

### Kubernetes

```yaml
securityContext:
  allowPrivilegeEscalation: false
```

---

## Seccomp & AppArmor

### Seccomp (Secure Computing Mode)

Seccomp filters limit which syscalls a container can make. Docker applies a default seccomp profile that blocks ~44 dangerous syscalls.

#### Custom Seccomp Profile

For highly sensitive workloads, create a custom profile that blocks additional syscalls:

```json
{
  "defaultAction": "SCMP_ACT_ERRNO",
  "architectures": ["SCMP_ARCH_X86_64", "SCMP_ARCH_X86"],
  "syscalls": [
    {
      "names": ["accept", "bind", "clone", "close", "connect", "epoll_create", "epoll_ctl", "epoll_wait", "exit", "exit_group", "fcntl", "fstat", "futex", "getpid", "getrandom", "ioctl", "listen", "mmap", "mprotect", "munmap", "nanosleep", "open", "openat", "poll", "read", "recvfrom", "recvmsg", "rt_sigaction", "rt_sigprocmask", "rt_sigreturn", "select", "sendmsg", "sendto", "setitimer", "setsockopt", "socket", "socketpair", "write", "writev"],
      "action": "SCMP_ACT_ALLOW"
    }
  ]
}
```

```bash
docker run --security-opt seccomp=custom-seccomp.json myapp:latest
```

### AppArmor

AppArmor restricts program capabilities with per-program profiles. Docker applies a default `docker-default` profile.

```bash
# Use a custom AppArmor profile
docker run --security-opt apparmor=myapp-profile myapp:latest
```

> AppArmor profiles are path-based. The profile must be loaded on the **host** before the container starts.

---

## Secrets Management

### Never Commit Secrets

Secrets must never appear in:
- Dockerfile `ENV` or `ARG` instructions (unless using BuildKit secrets)
- Image layers (inspectable via `docker history`)
- `docker-compose.yml` committed to version control

### BuildKit Secrets Mount

Inject secrets at build time without persisting them in the image:

```dockerfile
# syntax=docker/dockerfile:1
FROM node:22-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN --mount=type=secret,id=npmrc,target=/root/.npmrc \
    npm ci
COPY . .
RUN npm run build
```

```bash
docker build --secret id=npmrc,src=$HOME/.npmrc -t myapp:latest .
```

### SSH Forwarding for Private Repos

```dockerfile
# syntax=docker/dockerfile:1
FROM golang:1.22-alpine AS builder
WORKDIR /app
RUN apk add --no-cache openssh-client
RUN mkdir -p -m 0600 ~/.ssh && ssh-keyscan github.com >> ~/.ssh/known_hosts
RUN --mount=type=ssh git clone git@github.com:myorg/private-repo.git
```

```bash
# Requires ssh-agent with key loaded
docker build --ssh default -t myapp:latest .
```

### Runtime Secrets (Compose)

Use environment files excluded from version control:

```yaml
services:
  app:
    env_file:
      - .env.production
```

`.env.production` should be in `.gitignore` and distributed via a secret manager (1Password, Vault, AWS Secrets Manager, etc.).

---

## Vulnerability Scanning Integration

### Trivy (Recommended)

Fast, open-source scanner for OS packages and language dependencies.

#### Local Scan

```bash
# Full image scan
trivy image myapp:latest

# Dockerfile misconfiguration
trivy config Dockerfile

# Filesystem (before building)
trivy filesystem .
```

#### CI Fail Threshold

```bash
trivy image --exit-code 1 --severity HIGH,CRITICAL myapp:latest
```

#### SARIF Output (GitHub Advanced Security)

```bash
trivy image --format sarif --output trivy-results.sarif myapp:latest
```

### Snyk

```bash
snyk container test myapp:latest --severity-threshold=high
snyk container monitor myapp:latest --file=Dockerfile
```

### Clair

Integrate with Harbor registry or use `clair-scanner` locally:

```bash
clair-scanner --ip scanner-host-ip myapp:latest
```

### GitLab Container Scanning

```yaml
container_scanning:
  image: $CI_REGISTRY/container-scanning/trivy:latest
  script:
    - trivy image --format template --template "@contrib/gitlab.tpl"
        -o gl-container-scanning-report.json $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA
  artifacts:
    reports:
      container_scanning: gl-container-scanning-report.json
```

### Docker Scout

```bash
docker scout cves myapp:latest
docker scout quickview myapp:latest
docker scout recommendations myapp:latest
```

### Scanning Best Practices

1. **Scan at build time**, not just at deploy time
2. **Fail CI on HIGH/CRITICAL** findings (with exceptions tracked in an allowlist)
3. **Re-scan base images regularly**; a clean image today may have a CVE tomorrow
4. **Track false positives** in a `.trivyignore` or `trivy.yaml` file committed to the repo
5. **Use fixed base image tags** so scans are reproducible across environments

---

## Hardening Checklist

Before shipping any production container:

- [ ] Base image is minimal (alpine, slim, or distroless)
- [ ] Image tag is pinned (no `latest`)
- [ ] Multi-stage build separates build and runtime
- [ ] Application runs as non-root user (numeric UID/GID)
- [ ] Filesystem is read-only with tmpfs for temporary writes
- [ ] All capabilities dropped (`cap_drop: [ALL]`)
- [ ] No additional capabilities added unless strictly required
- [ ] `no-new-privileges` is set
- [ ] No secrets in image layers (verified with `dive` or `docker history`)
- [ ] Healthcheck defined
- [ ] Resource limits set (CPU, memory)
- [ ] Image scanned with Trivy / Snyk / Clair
- [ ] No HIGH/CRITICAL vulnerabilities (or explicitly documented exceptions)
- [ ] `.dockerignore` excludes `.git`, build artifacts, and secrets
