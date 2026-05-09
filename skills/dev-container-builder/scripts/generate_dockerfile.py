#!/usr/bin/env python3
"""
generate_dockerfile.py

Analyze a project directory and generate an optimized, multi-stage Dockerfile
with language-specific base images, security hardening, and caching best practices.

Usage:
    python generate_dockerfile.py /path/to/project
    python generate_dockerfile.py /path/to/project --out Dockerfile --ignore
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional


def detect_language(project_dir: Path) -> Optional[str]:
    """Detect primary language/runtime from manifest files."""
    if (project_dir / "go.mod").exists():
        return "go"
    if (project_dir / "Cargo.toml").exists():
        return "rust"
    if (project_dir / "package.json").exists():
        return "nodejs"
    if (project_dir / "requirements.txt").exists() or (project_dir / "pyproject.toml").exists():
        return "python"
    if (project_dir / "pom.xml").exists():
        return "java-maven"
    if (project_dir / "build.gradle").exists() or (project_dir / "build.gradle.kts").exists():
        return "java-gradle"
    if any(project_dir.glob("*.csproj")):
        return "dotnet"
    if (project_dir / "Gemfile").exists():
        return "ruby"
    if (project_dir / "composer.json").exists():
        return "php"
    return None


def detect_framework(project_dir: Path, language: str) -> str:
    """Detect framework from manifest content."""
    if language == "nodejs":
        package_json = project_dir / "package.json"
        if package_json.exists():
            try:
                data = json.loads(package_json.read_text())
                deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
                for fw in ["next", "nuxt", "react", "vue", "express", "fastify", "nest", "@nestjs/core", "hapi", "koa"]:
                    if fw in deps:
                        return fw.lstrip("@").replace("/core", "")
            except Exception:
                pass
        return "nodejs"

    if language == "python":
        for req_file in ["requirements.txt", "pyproject.toml"]:
            req_path = project_dir / req_file
            if req_path.exists():
                text = req_path.read_text().lower()
                for fw in ["fastapi", "flask", "django", "starlette", "tornado"]:
                    if fw in text:
                        return fw
        return "python"

    if language == "go":
        return "go"

    if language == "rust":
        cargo = project_dir / "Cargo.toml"
        if cargo.exists():
            text = cargo.read_text().lower()
            for fw in ["axum", "actix", "rocket", "warp", "tide"]:
                if fw in text:
                    return fw
        return "rust"

    if language.startswith("java"):
        return "spring" if any(project_dir.rglob("*Application.java")) or any(project_dir.rglob("*Application.kt")) else "java"

    if language == "dotnet":
        return "aspnet"

    if language == "ruby":
        gemfile = project_dir / "Gemfile"
        if gemfile.exists():
            text = gemfile.read_text().lower()
            if "rails" in text:
                return "rails"
            if "sinatra" in text:
                return "sinatra"
        return "ruby"

    if language == "php":
        composer = project_dir / "composer.json"
        if composer.exists():
            text = composer.read_text().lower()
            for fw in ["laravel", "symfony", "slim"]:
                if fw in text:
                    return fw
        return "php"

    return "unknown"


def detect_port(project_dir: Path, language: str, framework: str) -> int:
    """Infer application listening port from common conventions and source files."""
    # Check environment files
    for env_file in [".env", ".env.example", ".env.local", ".env.development"]:
        env_path = project_dir / env_file
        if env_path.exists():
            match = re.search(r'PORT\s*=\s*(\d+)', env_path.read_text())
            if match:
                return int(match.group(1))

    # Check common config files
    if language == "nodejs" and framework == "next":
        next_config = project_dir / "next.config.js"
        if next_config.exists() and "3000" not in next_config.read_text():
            pass
        return 3000

    if framework == "django":
        return 8000

    if framework in ["flask", "fastapi", "python"]:
        return 8000

    if language == "go":
        return 8080

    if language == "rust":
        return 8080

    if language.startswith("java") or language == "dotnet":
        return 8080

    if language == "ruby":
        return 3000

    if language == "php":
        return 9000

    return 3000


def detect_entrypoint(project_dir: Path, language: str, framework: str) -> str:
    """Guess the main entrypoint or build artifact."""
    if language == "nodejs":
        package_json = project_dir / "package.json"
        if package_json.exists():
            try:
                data = json.loads(package_json.read_text())
                if "main" in data:
                    return data["main"]
                if "bin" in data and isinstance(data["bin"], str):
                    return data["bin"]
            except Exception:
                pass
        if framework == "next":
            return "server.js"
        return "index.js"

    if language == "python":
        for candidate in ["app/main.py", "main.py", "manage.py", "src/main.py", "server.py", "app.py"]:
            if (project_dir / candidate).exists():
                return candidate
        return "main.py"

    if language == "go":
        for candidate in ["cmd/server/main.go", "cmd/main.go", "main.go", "server.go"]:
            if (project_dir / candidate).exists():
                return candidate
        return "cmd/server"

    if language == "rust":
        cargo = project_dir / "Cargo.toml"
        if cargo.exists():
            match = re.search(r'\[\[bin\]\].*?name\s*=\s*"([^"]+)"', cargo.read_text(), re.DOTALL)
            if match:
                return match.group(1)
        return "server"

    if language.startswith("java"):
        jar_files = list(project_dir.rglob("target/*.jar"))
        if jar_files:
            return jar_files[0].name
        return "app.jar"

    if language == "dotnet":
        csproj = next(project_dir.glob("*.csproj"), None)
        if csproj:
            return csproj.stem + ".dll"
        return "App.dll"

    if language == "ruby":
        for candidate in ["config.ru", "config/puma.rb", "bin/rails"]:
            if (project_dir / candidate).exists():
                return candidate
        return "config.ru"

    if language == "php":
        for candidate in ["public/index.php", "index.php", "server.php"]:
            if (project_dir / candidate).exists():
                return candidate
        return "public/index.php"

    return "app"


def generate_dockerfile(language: str, framework: str, port: int, entrypoint: str) -> str:
    """Generate an optimized multi-stage Dockerfile for the detected language."""
    if language == "nodejs":
        return _dockerfile_nodejs(framework, port, entrypoint)
    if language == "python":
        return _dockerfile_python(framework, port, entrypoint)
    if language == "go":
        return _dockerfile_go(port, entrypoint)
    if language == "rust":
        return _dockerfile_rust(port, entrypoint)
    if language.startswith("java"):
        return _dockerfile_java(language, port)
    if language == "dotnet":
        return _dockerfile_dotnet(port)
    if language == "ruby":
        return _dockerfile_ruby(framework, port, entrypoint)
    if language == "php":
        return _dockerfile_php(framework, port, entrypoint)
    return _dockerfile_generic()


def _dockerfile_nodejs(framework: str, port: int, entrypoint: str) -> str:
    base = "node:22-alpine"
    user = "node"
    if framework == "next":
        return f"""# syntax=docker/dockerfile:1
FROM {base} AS builder
WORKDIR /app
COPY package*.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --ignore-scripts
COPY . .
RUN npm run build

FROM {base} AS runtime
ENV NODE_ENV=production
WORKDIR /app
COPY --from=builder --chown={user}:{user} /app/public ./public
COPY --from=builder --chown={user}:{user} /app/.next/standalone ./
COPY --from=builder --chown={user}:{user} /app/.next/static ./.next/static
USER {user}
EXPOSE {port}
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \\
  CMD node -e "require('http').get('http://localhost:{port}/health', (r) => r.statusCode === 200 ? process.exit(0) : process.exit(1))"
CMD ["node", "server.js"]
"""
    return f"""# syntax=docker/dockerfile:1
FROM {base} AS builder
WORKDIR /app
COPY package*.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --ignore-scripts
COPY . .
RUN npm run build

FROM {base} AS runtime
ENV NODE_ENV=production
WORKDIR /app
COPY --from=builder --chown={user}:{user} /app/dist ./dist
COPY --from=builder --chown={user}:{user} /app/node_modules ./node_modules
COPY --from=builder --chown={user}:{user} /app/package.json ./
USER {user}
EXPOSE {port}
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \\
  CMD node -e "require('http').get('http://localhost:{port}/health', (r) => r.statusCode === 200 ? process.exit(0) : process.exit(1))"
CMD ["node", "{entrypoint}"]
"""


def _dockerfile_python(framework: str, port: int, entrypoint: str) -> str:
    base = "python:3.12-slim"
    if framework == "django":
        asgi_module = _find_django_module(Path("."))
        cmd = f'["gunicorn", "{asgi_module}.wsgi:application", "--bind", "0.0.0.0:{port}"]'
    elif framework == "fastapi":
        module = _find_python_module(entrypoint)
        cmd = f'["uvicorn", "{module}:app", "--host", "0.0.0.0", "--port", "{port}"]'
    else:
        module = _find_python_module(entrypoint)
        cmd = f'["flask", "--app", "{module}", "run", "--host=0.0.0.0", "--port={port}"]'
    return f"""# syntax=docker/dockerfile:1
FROM {base} AS builder
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*
COPY requirements.txt pyproject.toml ./
RUN --mount=type=cache,target=/root/.cache/pip \\
    pip install --user --no-cache-dir -r requirements.txt

FROM {base} AS runtime
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH=/root/.local/bin:$PATH
WORKDIR /app
COPY --from=builder /root/.local /root/.local
COPY . .
RUN groupadd -r appgroup && useradd -r -g appgroup appuser
USER appuser
EXPOSE {port}
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \\
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:{port}/health')"
CMD {cmd}
"""


def _dockerfile_go(port: int, entrypoint: str) -> str:
    return f"""# syntax=docker/dockerfile:1
FROM golang:1.22-alpine AS builder
WORKDIR /app
COPY go.mod go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -a -installsuffix cgo -ldflags="-w -s" -o /bin/server ./{entrypoint}

FROM gcr.io/distroless/static:nonroot
COPY --from=builder /bin/server /server
COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/
USER nonroot:nonroot
EXPOSE {port}
ENTRYPOINT ["/server"]
"""


def _dockerfile_rust(port: int, entrypoint: str) -> str:
    return f"""# syntax=docker/dockerfile:1
FROM rust:1.78-slim AS chef
RUN cargo install cargo-chef

FROM chef AS planner
WORKDIR /app
COPY . .
RUN cargo chef prepare --recipe-path recipe.json

FROM chef AS builder
WORKDIR /app
COPY --from=planner /app/recipe.json recipe.json
RUN --mount=type=cache,target=/usr/local/cargo/registry \\
    cargo chef cook --release --recipe-path recipe.json
COPY . .
RUN cargo build --release --bin {entrypoint}

FROM debian:12-slim AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=builder /app/target/release/{entrypoint} /usr/local/bin/{entrypoint}
RUN groupadd -r rustapp && useradd -r -g rustapp rustapp
USER rustapp
EXPOSE {port}
CMD ["/usr/local/bin/{entrypoint}"]
"""


def _dockerfile_java(build_tool: str, port: int) -> str:
    jdk = "eclipse-temurin:21-jdk-alpine"
    jre = "eclipse-temurin:21-jre-alpine"
    if "maven" in build_tool:
        build_cmd = "mvn package -DskipTests"
        artifact_path = "/app/target/*.jar"
    else:
        build_cmd = "./gradlew bootJar --no-daemon"
        artifact_path = "/app/build/libs/*.jar"
    return f"""# syntax=docker/dockerfile:1
FROM {jdk} AS builder
WORKDIR /app
COPY . .
RUN --mount=type=cache,target=/root/.m2 {build_cmd}

FROM {jre}
WORKDIR /app
COPY --from=builder {artifact_path} app.jar
RUN addgroup -S spring && adduser -S spring -G spring
USER spring:spring
EXPOSE {port}
HEALTHCHECK --interval=30s --timeout=3s --start-period=60s --retries=3 \\
  CMD wget -qO- http://localhost:{port}/actuator/health || exit 1
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
"""


def _dockerfile_dotnet(port: int) -> str:
    return f"""# syntax=docker/dockerfile:1
FROM mcr.microsoft.com/dotnet/sdk:8.0 AS builder
WORKDIR /src
COPY *.csproj ./
RUN --mount=type=cache,target=/root/.nuget/packages dotnet restore
COPY . .
RUN dotnet publish -c Release -o /app/publish --no-restore

FROM mcr.microsoft.com/dotnet/aspnet:8.0 AS runtime
WORKDIR /app
COPY --from=builder /app/publish .
RUN addgroup --system appgroup && adduser --system appuser --ingroup appgroup
USER appuser
EXPOSE {port}
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \\
  CMD wget -qO- http://localhost:{port}/healthz || exit 1
ENTRYPOINT ["dotnet", "$(ls *.dll | head -1)"]
"""


def _dockerfile_ruby(framework: str, port: int, entrypoint: str) -> str:
    base = "ruby:3.3-slim"
    if framework == "rails":
        cmd = f'["bundle", "exec", "puma", "-C", "config/puma.rb"]'
    else:
        cmd = f'["bundle", "exec", "ruby", "{entrypoint}"]'
    return f"""# syntax=docker/dockerfile:1
FROM {base} AS builder
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends build-essential libpq-dev && rm -rf /var/lib/apt/lists/*
COPY Gemfile Gemfile.lock ./
RUN bundle config set --local deployment 'true' && \\
    bundle config set --local without 'development test' && \\
    bundle install --jobs 4 --retry 3

FROM {base} AS runtime
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libpq5 && rm -rf /var/lib/apt/lists/*
COPY --from=builder /usr/local/bundle /usr/local/bundle
COPY . .
RUN groupadd -r rails && useradd -r -g rails rails && chown -R rails:rails /app
USER rails
EXPOSE {port}
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \\
  CMD wget -qO- http://localhost:{port}/up || exit 1
CMD {cmd}
"""


def _dockerfile_php(framework: str, port: int, entrypoint: str) -> str:
    return f"""# syntax=docker/dockerfile:1
FROM php:8.3-fpm-alpine AS builder
WORKDIR /app
RUN apk add --no-cache postgresql-dev libzip-dev unzip
COPY --from=composer:2 /usr/bin/composer /usr/bin/composer
COPY composer.json composer.lock ./
RUN composer install --no-dev --optimize-autoloader --no-interaction
COPY . .
RUN php artisan config:cache 2>/dev/null || true

FROM php:8.3-fpm-alpine AS runtime
WORKDIR /app
RUN apk add --no-cache postgresql-libs libzip && \\
    docker-php-ext-install opcache pdo_pgsql zip
COPY --from=builder /app /app
RUN addgroup -S phpgroup && adduser -S phpuser -G phpgroup
USER phpuser
EXPOSE {port}
CMD ["php-fpm"]
"""


def _dockerfile_generic() -> str:
    return """# syntax=docker/dockerfile:1
FROM alpine:3.19
WORKDIR /app
COPY . .
RUN addgroup -S appgroup && adduser -S appuser -G appgroup
USER appuser
CMD ["echo", "Please customize this generic Dockerfile for your application"]
"""


def _find_django_module(project_dir: Path) -> str:
    """Attempt to locate the Django project module containing settings.py."""
    for settings in project_dir.rglob("settings.py"):
        relative = settings.relative_to(project_dir)
        if len(relative.parts) >= 2:
            return relative.parts[0]
    return "myproject"


def _find_python_module(entrypoint: str) -> str:
    """Convert an entrypoint file path to a module path."""
    ep = entrypoint.replace(".py", "").replace("/", ".")
    if ep.startswith("."):
        ep = ep[1:]
    return ep


def generate_dockerignore(language: str) -> str:
    """Generate a .dockerignore tailored to the language."""
    common = """.git
.gitignore
README.md
README*
LICENSE*
CHANGELOG*
.env
.env.*
*.md
docker-compose*.yml
Dockerfile*
.vscode
.idea
*.swp
*.swo
*~
"""
    language_specific = {
        "nodejs": """node_modules
npm-debug.log
yarn-error.log
.pnpm-debug.log
dist
.next
.nuxt
coverage
.nyc_output
""",
        "python": """__pycache__
*.pyc
*.pyo
*.pyd
.Python
env/
venv/
.venv/
pip-log.txt
pip-delete-this-directory.txt
.tox
.coverage
.coverage.*
htmlcov/
.pytest_cache
.mypy_cache
.ruff_cache
""",
        "go": """bin/
vendor/
*.exe
*.dll
*.so
*.dylib
*.test
*.out
""",
        "rust": """target/
Cargo.lock
cargo-timing*.html
*.rs.bk
""",
        "java-maven": """target/
*.class
.mvn/
!**/mvnw
""",
        "java-gradle": """build/
.gradle/
!**/gradlew
""",
        "dotnet": """bin/
obj/
*.user
*.suo
.vs/
""",
        "ruby": """.bundle/
vendor/bundle/
log/*
tmp/
coverage/
.yardoc
""",
        "php": """vendor/
node_modules/
.env.local
var/cache/*
var/log/*
.phpunit.result.cache
""",
    }
    return common + language_specific.get(language, "")


def print_summary(language: str, framework: str, port: int, entrypoint: str, out_file: Optional[str], ignore_file: Optional[str]):
    """Print a human-readable analysis summary."""
    print("=" * 60)
    print("Project Analysis Summary")
    print("=" * 60)
    print(f"  Language:    {language}")
    print(f"  Framework:   {framework}")
    print(f"  Port:        {port}")
    print(f"  Entrypoint:  {entrypoint}")
    print()
    if out_file:
        print(f"  Dockerfile:  {out_file}")
    if ignore_file:
        print(f"  .dockerignore: {ignore_file}")
    print()
    print("Next steps:")
    print("  1. Review the generated Dockerfile and adjust COPY paths.")
    print("  2. Verify the HEALTHCHECK endpoint matches your app.")
    print("  3. Run: docker build -t myapp:latest .")
    print("  4. Scan: trivy image myapp:latest")
    print("  5. Harden: read references/security_hardening.md")
    print("=" * 60)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate an optimized Dockerfile from project analysis.")
    parser.add_argument("project_dir", help="Path to the project root directory")
    parser.add_argument("--out", "-o", default="Dockerfile", help="Output Dockerfile path")
    parser.add_argument("--ignore", action="store_true", help="Also generate .dockerignore")
    parser.add_argument("--dry-run", action="store_true", help="Print analysis without writing files")
    args = parser.parse_args()

    project_dir = Path(args.project_dir).resolve()
    if not project_dir.exists() or not project_dir.is_dir():
        print(f"Error: {project_dir} is not a valid directory", file=sys.stderr)
        return 1

    os.chdir(project_dir)

    language = detect_language(project_dir)
    if language is None:
        print("Error: Could not detect language/runtime from project files.", file=sys.stderr)
        print("Supported manifests: package.json, requirements.txt, pyproject.toml, go.mod, Cargo.toml, pom.xml, build.gradle, *.csproj, Gemfile, composer.json", file=sys.stderr)
        return 1

    framework = detect_framework(project_dir, language)
    port = detect_port(project_dir, language, framework)
    entrypoint = detect_entrypoint(project_dir, language, framework)
    dockerfile = generate_dockerfile(language, framework, port, entrypoint)

    if args.dry_run:
        print_summary(language, framework, port, entrypoint, None, None)
        print("\n--- Generated Dockerfile (dry run) ---\n")
        print(dockerfile)
        if args.ignore:
            print("\n--- Generated .dockerignore (dry run) ---\n")
            print(generate_dockerignore(language))
        return 0

    out_path = project_dir / args.out
    out_path.write_text(dockerfile)
    print(f"Generated {out_path}")

    ignore_path = None
    if args.ignore:
        ignore_path = project_dir / ".dockerignore"
        ignore_path.write_text(generate_dockerignore(language))
        print(f"Generated {ignore_path}")

    print_summary(language, framework, port, entrypoint, str(out_path), str(ignore_path) if ignore_path else None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
