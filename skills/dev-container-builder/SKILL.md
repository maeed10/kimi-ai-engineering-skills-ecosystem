---
name: dev-container-builder
description: Developer-facing Docker container builder with multi-stage optimization, image scanning, layer caching, and security hardening. Use when creating Dockerfiles, optimizing image size, scanning vulnerabilities, setting up Compose, or configuring production-ready containers. Supports BuildKit, distroless images, and cosign signing.
---

# Dev Container Builder

## Overview

Build, optimize, and secure Docker containers and Docker Compose configurations for everyday software engineering. This skill provides opinionated, production-ready patterns for multi-stage builds, layer caching, vulnerability scanning, and security hardening.

## When to Use

- Creating a Dockerfile for a new application
- Optimizing existing Docker images (size, build time, security)
- Setting up Docker Compose for local development or testing
- Scanning images for vulnerabilities before deployment
- Configuring multi-stage builds for production efficiency
- Hardening containers with non-root users, read-only filesystems, or distroless bases
- Setting up CI pipelines with BuildKit, cache mounts, and image signing

## Workflow Decision Tree

```
1. Does the project already have a Dockerfile?
   ├── NO → Generate Dockerfile from project analysis (see ## Dockerfile Generation)
   └── YES → Is it optimized?
       ├── NO → Optimize (see ## Multi-Stage Optimization and ## Layer Caching)
       └── YES → Is it secure?
           ├── NO → Harden (see ## Security Hardening)
           └── YES → Scan & ship (see ## Image Scanning)

2. Need local orchestration?
   └── Create Compose files (see ## Docker Compose Setup)

3. Need CI integration?
   └── Configure BuildKit + registry (see ## BuildKit Features and ## Registry Management)
```

## Dockerfile Generation

### Step 1: Analyze Project Structure

Inspect the codebase to determine:
- **Language/runtime**: `package.json` → Node.js; `requirements.txt` / `pyproject.toml` → Python; `Cargo.toml` → Rust; `go.mod` → Go; `pom.xml` / `build.gradle` → Java
- **Framework**: Express, FastAPI, Spring Boot, Rails, etc.
- **Build tool**: Webpack, Vite, Maven, Gradle, Cargo
- **Port**: Application listening port (commonly 3000, 8080, 8000, 5000)
- **Entry point**: `CMD` or `ENTRYPOINT` script

### Step 2: Select Base Image Strategy

| Language | Development Base | Production Base | Notes |
|----------|----------------|-----------------|-------|
| Node.js  | `node:22-alpine` | `node:22-alpine` or `gcr.io/distroless/nodejs22` | Alpine for dev; distroless for prod if pure JS |
| Python   | `python:3.12-slim` | `python:3.12-slim` or `gcr.io/distroless/python3` | Slim usually sufficient; distroless limits debugging |
| Go       | `golang:1.22-alpine` | `gcr.io/distroless/static` or `scratch` | Static binary → scratch is ideal |
| Rust     | `rust:1.78-slim` | `gcr.io/distroless/cc` or `debian:12-slim` | CC variant if linking to C libs |
| Java     | `eclipse-temurin:21-jdk-alpine` | `eclipse-temurin:21-jre-alpine` | JRE for runtime; multi-stage mandatory |
| .NET     | `mcr.microsoft.com/dotnet/sdk:8.0` | `mcr.microsoft.com/dotnet/aspnet:8.0` | Runtime image is smaller |
| Ruby     | `ruby:3.3-slim` | `ruby:3.3-slim` | Multi-stage for gems with native extensions |

### Step 3: Generate Dockerfile

Use the `scripts/generate_dockerfile.py` script or reference `references/dockerfile_patterns.md` for language-specific templates. Follow these universal rules:

1. Pin exact base image tags (no `latest`)
2. Use multi-stage builds when the build artifact differs from runtime artifact
3. Group `RUN` commands that install dependencies to reduce layers
4. Copy `package.json` / `requirements.txt` before source code for cache efficiency
5. Define `HEALTHCHECK` for production images
6. Expose only the required port

## Multi-Stage Optimization

### Core Pattern

Separate **build**, **test**, and **runtime** stages. Only the runtime stage is published.

```dockerfile
# syntax=docker/dockerfile:1
FROM node:22-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci --ignore-scripts
COPY . .
RUN npm run build

FROM node:22-alpine AS runtime
ENV NODE_ENV=production
WORKDIR /app
COPY --from=builder /app/dist ./dist
COPY --from=builder /app/node_modules ./node_modules
COPY package.json ./
USER node
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD node -e "require('http').get('http://localhost:3000/health', (r) => r.statusCode === 200 ? process.exit(0) : process.exit(1))"
CMD ["node", "dist/main.js"]
```

### Size Reduction Checklist

- [ ] Remove build tools (gcc, make, git) from final image
- [ ] Remove devDependencies after build (or use separate stage)
- [ ] Use `.dockerignore` to exclude `.git`, `node_modules`, `*.md`, tests
- [ ] Clean package manager caches (`npm cache clean`, `rm -rf /var/cache/apk/*`)
- [ ] Use `COPY --from` with `--chown` to avoid `RUN chown` layers
- [ ] Consider `python:slim` or `alpine` over `ubuntu` or `debian` full

### Sample .dockerignore

```
node_modules
npm-debug.log
.git
.gitignore
README.md
.env
.env.*
docker-compose*.yml
Dockerfile*
.vscode
.idea
coverage
dist  # if built in container
```

## Layer Caching Optimization

### Cache-Efficient Layer Ordering

Order Dockerfile instructions from **least frequently changed** to **most frequently changed**:

1. Base image (`FROM`)
2. System dependencies (`RUN apt-get`)
3. Application dependency manifests (`COPY package.json`)
4. Application dependencies (`RUN npm ci`)
5. Application source (`COPY . .`)
6. Build (`RUN npm run build`)

### BuildKit Cache Mounts

Use cache mounts for package managers to persist dependency caches across builds without bloating layers:

```dockerfile
# syntax=docker/dockerfile:1
RUN --mount=type=cache,target=/root/.npm \
    npm ci

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

RUN --mount=type=cache,target=/root/.m2 \
    mvn package -DskipTests
```

### Remote Cache (CI)

Enable inline or registry-based cache in CI:

```bash
# BuildKit inline cache
docker buildx build \
  --cache-to type=inline \
  --cache-from type=registry,ref=myimage:buildcache \
  -t myimage:latest \
  --push .
```

## Security Hardening

Reference `references/security_hardening.md` for complete details.

### Quick Hardening Checklist

- [ ] Run as non-root user (`USER` directive or `--user` flag)
- [ ] Use read-only root filesystem (`docker run --read-only` or `read_only: true` in Compose)
- [ ] Drop unnecessary Linux capabilities (`cap_drop: [ALL]`)
- [ ] Add only required capabilities (`cap_add: [NET_BIND_SERVICE]`)
- [ ] Use distroless or minimal base images
- [ ] Scan image with Trivy/Snyk before pushing
- [ ] No secrets in layers (use BuildKit secrets mounts)
- [ ] Pin image digests in production (`image: node:22-alpine@sha256:...`)

### BuildKit Secrets Mount

Inject secrets at build time without leaving them in layers:

```dockerfile
# syntax=docker/dockerfile:1
RUN --mount=type=secret,id=npmrc,target=/root/.npmrc \
    npm ci
```

```bash
docker build --secret id=npmrc,src=$HOME/.npmrc .
```

## Docker Compose Setup

### Environment-Specific Files

Create separate compose files per environment to avoid accidental production misconfiguration:

```
docker-compose.yml          # Common services
docker-compose.override.yml   # Local development defaults (auto-loaded)
docker-compose.test.yml       # Test dependencies (databases, mocks)
docker-compose.prod.yml       # Production overrides (replicas, limits, healthchecks)
```

### Production Compose Essentials

```yaml
services:
  app:
    image: myapp:1.2.3@sha256:abc...
    read_only: true
    user: "1000:1000"
    cap_drop:
      - ALL
    security_opt:
      - no-new-privileges:true
    tmpfs:
      - /tmp:noexec,nosuid,size=100m
    healthcheck:
      test: ["CMD", "wget", "-qO-", "http://localhost:3000/health"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s
    deploy:
      resources:
        limits:
          cpus: '1.0'
          memory: 512M
        reservations:
          cpus: '0.25'
          memory: 128M
    restart: unless-stopped
```

### Local Development Compose

Enable live-reload, volume mounts, and debug ports without affecting production:

```yaml
services:
  app:
    build:
      context: .
      target: builder  # stop at builder stage for dev
    volumes:
      - .:/app
      - /app/node_modules  # anonymous volume preserves container node_modules
    environment:
      - NODE_ENV=development
    ports:
      - "3000:3000"
      - "9229:9229"  # Node inspector
    command: ["npm", "run", "dev"]
```

## Image Scanning

### Local Scanning with Trivy

```bash
# Scan image for OS and library vulnerabilities
trivy image myapp:latest

# Fail CI on HIGH/CRITICAL
trivy image --exit-code 1 --severity HIGH,CRITICAL myapp:latest

# Scan Dockerfile itself
trivy config Dockerfile
```

### CI Integration Template

```yaml
# .github/workflows/scan.yml (excerpt)
- name: Build image
  run: docker build -t app:${{ github.sha }} .

- name: Scan with Trivy
  uses: aquasecurity/trivy-action@master
  with:
    image-ref: 'app:${{ github.sha }}'
    format: 'sarif'
    output: 'trivy-results.sarif'

- name: Fail on critical
  run: |
    trivy image --exit-code 1 --severity CRITICAL app:${{ github.sha }}
```

### Snyk Alternative

```bash
snyk container test myapp:latest --severity-threshold=high
snyk container monitor myapp:latest  # ongoing monitoring
```

## BuildKit Features

### Enable BuildKit

```bash
export DOCKER_BUILDKIT=1
# or permanently in ~/.docker/daemon.json: {"features": {"buildkit": true}}
```

### Key BuildKit Capabilities

| Feature | Use Case | Dockerfile Syntax |
|---------|----------|-------------------|
| Cache mounts | Speed up package installs | `RUN --mount=type=cache,target=/root/.npm` |
| Secrets mounts | Inject credentials safely | `RUN --mount=type=secret,id=mysecret` |
| SSH forwarding | Clone private repos during build | `RUN --mount=type=ssh` |
| Parallel stages | Independent stages build concurrently | Define multiple unrelated `FROM ... AS` stages |
| Output exports | Export only built artifacts | `docker build --output type=local,dest=./out` |

### Multi-Platform Builds

```bash
docker buildx create --use --name multiplatform
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t myapp:latest \
  --push .
```

## Registry Management

### Tagging Strategy

Use semantic, immutable tags. Avoid `latest` in production orchestration.

```bash
VERSION=$(git describe --tags --always)
SHA=$(git rev-parse --short HEAD)
BRANCH=$(git rev-parse --abbrev-ref HEAD)

# Tag variants
docker tag myapp:latest myapp:${VERSION}
docker tag myapp:latest myapp:${SHA}
docker tag myapp:latest myapp:${BRANCH}-${SHA}
```

### Image Signing with Cosign

```bash
# Generate key pair (or use keyless with OIDC)
cosign generate-key-pair

# Sign image after push
cosign sign --key cosign.key myregistry.io/myapp:1.2.3

# Verify before deploy
cosign verify --key cosign.pub myregistry.io/myapp:1.2.3
```

### Keyless Signing (CI with OIDC)

```bash
cosign sign --yes myregistry.io/myapp:1.2.3
cosign verify --certificate-identity-regexp '.*' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  myregistry.io/myapp:1.2.3
```

### Push/Pull Optimization

- Use a registry mirror or pull-through cache for base images
- Layer compression: ensure consistent file timestamps to maximize layer reuse
- Rebase instead of rebuild when only the base image changes (experimental `docker rebase` or buildkit)

## Troubleshooting

### Large Image Size

1. Inspect layers: `dive myapp:latest` or `docker history myapp:latest`
2. Check for leftover build artifacts, caches, or source maps in final stage
3. Confirm multi-stage `COPY --from` only copies necessary files

### Slow Builds

1. Verify `.dockerignore` excludes large directories (`.git`, `node_modules`, `target`)
2. Move dependency manifests earlier in Dockerfile than source code
3. Use BuildKit cache mounts for package managers
4. Enable registry cache in CI (`--cache-to type=registry`)

### Permission Denied in Container

1. Check host UID/GID mapping when using volume binds
2. Ensure `USER` exists in `/etc/passwd` inside container
3. Use numeric UID/GID in `USER` and `docker run --user` for compatibility

## References

- `references/dockerfile_patterns.md` — Language-specific multi-stage Dockerfile templates
- `references/security_hardening.md` — Complete security hardening guide with capability lists and distroless strategies
- `scripts/generate_dockerfile.py` — Automated Dockerfile generator from project analysis
