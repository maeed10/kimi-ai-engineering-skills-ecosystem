# Dockerfile Patterns

Language-specific multi-stage Dockerfile templates optimized for production size, build caching, and security.

## Table of Contents

- [Node.js](#nodejs)
- [Python](#python)
- [Go](#go)
- [Rust](#rust)
- [Java (Maven / Gradle)](#java)
- [.NET](#net)
- [Ruby](#ruby)
- [PHP](#php)

---

## Node.js

### Web Service (Express / Fastify / NestJS)

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
COPY --from=builder --chown=node:node /app/dist ./dist
COPY --from=builder --chown=node:node /app/node_modules ./node_modules
COPY --from=builder --chown=node:node /app/package.json ./
USER node
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD node -e "require('http').get('http://localhost:3000/health', (r) => r.statusCode === 200 ? process.exit(0) : process.exit(1))"
CMD ["node", "dist/main.js"]
```

### Next.js / Static Frontend

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
COPY --from=builder --chown=node:node /app/public ./public
COPY --from=builder --chown=node:node /app/.next/standalone ./
COPY --from=builder --chown=node:node /app/.next/static ./.next/static
USER node
EXPOSE 3000
CMD ["node", "server.js"]
```

> For Next.js, enable `output: 'standalone'` in `next.config.js`.

---

## Python

### FastAPI / Flask / Starlette (ASGI)

```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.12-slim AS builder
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH=/root/.local/bin:$PATH
WORKDIR /app
COPY --from=builder /root/.local /root/.local
COPY ./app ./app
RUN groupadd -r appgroup && useradd -r -g appgroup appuser
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Django

```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.12-slim AS builder
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends gcc libpq-dev && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH=/root/.local/bin:$PATH
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libpq5 && rm -rf /var/lib/apt/lists/*
COPY --from=builder /root/.local /root/.local
COPY . .
RUN python manage.py collectstatic --noinput
RUN groupadd -r django && useradd -r -g django django
USER django
EXPOSE 8000
CMD ["gunicorn", "myproject.wsgi:application", "--bind", "0.0.0.0:8000"]
```

---

## Go

### Minimal Static Binary (Scratch)

```dockerfile
# syntax=docker/dockerfile:1
FROM golang:1.22-alpine AS builder
WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -a -installsuffix cgo -ldflags="-w -s" -o /bin/server ./cmd/server

FROM scratch
COPY --from=builder /bin/server /server
COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/
EXPOSE 8080
USER 65534:65534
ENTRYPOINT ["/server"]
```

> `scratch` images contain no shell or utilities. Ensure application emits structured logs and metrics.

### With Debug Utilities (Distroless)

```dockerfile
# syntax=docker/dockerfile:1
FROM golang:1.22-alpine AS builder
WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-w -s" -o /bin/server ./cmd/server

FROM gcr.io/distroless/static:nonroot
COPY --from=builder /bin/server /server
EXPOSE 8080
USER nonroot:nonroot
ENTRYPOINT ["/server"]
```

---

## Rust

### Server (Axum / Actix / Rocket)

```dockerfile
# syntax=docker/dockerfile:1
FROM rust:1.78-slim AS chef
RUN cargo install cargo-chef

FROM chef AS planner
WORKDIR /app
COPY . .
RUN cargo chef prepare --recipe-path recipe.json

FROM chef AS builder
WORKDIR /app
COPY --from=planner /app/recipe.json recipe.json
RUN cargo chef cook --release --recipe-path recipe.json
COPY . .
RUN cargo build --release --bin server

FROM debian:12-slim AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=builder /app/target/release/server /usr/local/bin/server
RUN groupadd -r rustapp && useradd -r -g rustapp rustapp
USER rustapp
EXPOSE 8080
CMD ["/usr/local/bin/server"]
```

> `cargo-chef` caches dependency compilation independently of source changes, dramatically speeding up CI builds.

---

## Java

### Maven

```dockerfile
# syntax=docker/dockerfile:1
FROM eclipse-temurin:21-jdk-alpine AS builder
WORKDIR /app
COPY pom.xml .
COPY src ./src
RUN mvn package -DskipTests

FROM eclipse-temurin:21-jre-alpine
WORKDIR /app
COPY --from=builder /app/target/*.jar app.jar
RUN addgroup -S spring && adduser -S spring -G spring
USER spring:spring
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=60s --retries=3 \
  CMD wget -qO- http://localhost:8080/actuator/health || exit 1
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
```

### Gradle

```dockerfile
# syntax=docker/dockerfile:1
FROM eclipse-temurin:21-jdk-alpine AS builder
WORKDIR /app
COPY gradle gradle
COPY gradlew build.gradle.kts settings.gradle.kts ./
RUN ./gradlew dependencies --no-daemon
COPY src ./src
RUN ./gradlew bootJar --no-daemon

FROM eclipse-temurin:21-jre-alpine
WORKDIR /app
COPY --from=builder /app/build/libs/*.jar app.jar
RUN addgroup -S spring && adduser -S spring -G spring
USER spring:spring
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
```

---

## .NET

### ASP.NET Core

```dockerfile
# syntax=docker/dockerfile:1
FROM mcr.microsoft.com/dotnet/sdk:8.0 AS builder
WORKDIR /src
COPY *.csproj ./
RUN dotnet restore
COPY . .
RUN dotnet publish -c Release -o /app/publish --no-restore

FROM mcr.microsoft.com/dotnet/aspnet:8.0 AS runtime
WORKDIR /app
COPY --from=builder /app/publish .
RUN addgroup --system appgroup && adduser --system appuser --ingroup appgroup
USER appuser
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -qO- http://localhost:8080/healthz || exit 1
ENTRYPOINT ["dotnet", "MyApp.dll"]
```

---

## Ruby

### Rails / Sinatra

```dockerfile
# syntax=docker/dockerfile:1
FROM ruby:3.3-slim AS builder
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends build-essential libpq-dev && rm -rf /var/lib/apt/lists/*
COPY Gemfile Gemfile.lock ./
RUN bundle config set --local deployment 'true' && \
    bundle config set --local without 'development test' && \
    bundle install --jobs 4 --retry 3

FROM ruby:3.3-slim AS runtime
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libpq5 && rm -rf /var/lib/apt/lists/*
COPY --from=builder /usr/local/bundle /usr/local/bundle
COPY . .
RUN groupadd -r rails && useradd -r -g rails rails && chown -R rails:rails /app
USER rails
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD wget -qO- http://localhost:3000/up || exit 1
CMD ["bundle", "exec", "puma", "-C", "config/puma.rb"]
```

---

## PHP

### Laravel / Symfony (FPM + Nginx sidecar)

FPM runtime image (use with separate nginx container or combined via supervisor if necessary):

```dockerfile
# syntax=docker/dockerfile:1
FROM php:8.3-fpm-alpine AS builder
WORKDIR /app
RUN apk add --no-cache postgresql-dev libzip-dev unzip
COPY --from=composer:2 /usr/bin/composer /usr/bin/composer
COPY composer.json composer.lock ./
RUN composer install --no-dev --optimize-autoloader --no-interaction
COPY . .
RUN php artisan config:cache || true
RUN php artisan route:cache || true

FROM php:8.3-fpm-alpine AS runtime
WORKDIR /app
RUN apk add --no-cache postgresql-libs libzip && \
    docker-php-ext-install opcache pdo_pgsql zip
COPY --from=builder /app /app
RUN addgroup -S phpgroup && adduser -S phpuser -G phpgroup
USER phpuser
EXPOSE 9000
CMD ["php-fpm"]
```

> For a single-container Laravel deployment, add an nginx stage and use a process manager (supervisord), or run nginx + php-fpm as separate containers in a pod/compose setup.

---

## BuildKit Cache Mount Variants

Replace package install steps with cache mounts for CI speed:

### Node.js

```dockerfile
RUN --mount=type=cache,target=/root/.npm \
    npm ci
```

### Python

```dockerfile
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --user --no-cache-dir -r requirements.txt
```

### Go

```dockerfile
RUN --mount=type=cache,target=/go/pkg/mod \
    go mod download
```

### Rust

```dockerfile
RUN --mount=type=cache,target=/usr/local/cargo/registry \
    cargo chef cook --release --recipe-path recipe.json
```

### Java (Maven)

```dockerfile
RUN --mount=type=cache,target=/root/.m2 \
    mvn package -DskipTests
```

### .NET

```dockerfile
RUN --mount=type=cache,target=/root/.nuget/packages \
    dotnet restore
```

---

## Base Image Selection Quick Reference

| Language | Build Image | Minimal Runtime | Distroless Runtime |
|----------|-------------|-----------------|--------------------|
| Node.js  | `node:22-alpine` | `node:22-alpine` | `gcr.io/distroless/nodejs22` |
| Python   | `python:3.12-slim` | `python:3.12-slim` | `gcr.io/distroless/python3` |
| Go       | `golang:1.22-alpine` | `scratch` | `gcr.io/distroless/static` |
| Rust     | `rust:1.78-slim` | `debian:12-slim` | `gcr.io/distroless/cc` |
| Java     | `eclipse-temurin:21-jdk-alpine` | `eclipse-temurin:21-jre-alpine` | N/A (use JRE) |
| .NET     | `mcr.microsoft.com/dotnet/sdk:8.0` | `mcr.microsoft.com/dotnet/aspnet:8.0` | N/A |
| Ruby     | `ruby:3.3-slim` | `ruby:3.3-slim` | N/A |
| PHP      | `php:8.3-fpm-alpine` | `php:8.3-fpm-alpine` | N/A |
