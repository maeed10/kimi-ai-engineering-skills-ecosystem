#!/usr/bin/env python3
"""
generate_pipeline.py

Analyzes project structure in the current directory and generates a CI/CD
pipeline configuration for the requested platform.

Usage:
    python generate_pipeline.py --platform github-actions [--output .github/workflows/ci.yml]
    python generate_pipeline.py --platform gitlab-ci [--output .gitlab-ci.yml]
    python generate_pipeline.py --platform azure-devops [--output azure-pipelines.yml]
    python generate_pipeline.py --platform jenkins [--output Jenkinsfile]
    python generate_pipeline.py --platform circleci [--output .circleci/config.yml]
    python generate_pipeline.py --platform travis [--output .travis.yml]

Options:
    --platform      Target CI/CD platform (required)
    --output        Output file path (default: platform-specific default)
    --with-docker   Include Docker build stage (default: auto-detect)
    --with-deploy   Include deployment stage (default: false)
    --with-security Include security scanning stages (default: true)
    --node-version  Node.js version override
    --python-version Python version override
    --java-version  Java version override
"""

import argparse
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class ProjectDetector:
    """Detects project type, language, framework, and build tools from filesystem."""

    # Detection rules: (glob_patterns, project_type, build_tool, test_framework)
    DETECTION_RULES: List[Tuple[List[str], str, Optional[str], Optional[str]]] = [
        (["package.json"], "node", None, None),
        (["requirements.txt", "pyproject.toml", "setup.py", "setup.cfg", "Pipfile"], "python", None, None),
        (["pom.xml"], "java", "maven", None),
        (["build.gradle", "build.gradle.kts"], "java", "gradle", None),
        (["Cargo.toml"], "rust", "cargo", None),
        (["go.mod"], "go", "go modules", None),
        (["*.csproj", "*.sln"], "dotnet", None, None),
        (["Gemfile"], "ruby", "bundler", None),
        (["pubspec.yaml"], "flutter", None, None),
        (["composer.json"], "php", "composer", None),
        (["*.tf", "*.tfvars"], "terraform", None, None),
        (["Dockerfile", "docker-compose.yml", "docker-compose.yaml"], "docker", None, None),
    ]

    def __init__(self, root: Path = Path(".")):
        self.root = root.resolve()
        self.files = set(str(p.relative_to(self.root)) for p in self.root.rglob("*") if p.is_file())
        self.top_level = set(p.name for p in self.root.iterdir() if p.is_file())

    def detect(self) -> Dict[str, any]:
        result = {
            "project_type": "generic",
            "build_tool": None,
            "test_framework": None,
            "package_manager": None,
            "has_docker": False,
            "has_kubernetes": False,
            "has_terraform": False,
            "has_pre_commit": False,
            "languages": [],
            "frameworks": [],
            "versions": {},
        }

        # Type detection
        for patterns, proj_type, build_tool, test_fw in self.DETECTION_RULES:
            for pattern in patterns:
                if self._match(pattern):
                    result["project_type"] = proj_type
                    if build_tool:
                        result["build_tool"] = build_tool
                    if test_fw:
                        result["test_framework"] = test_fw
                    break
            if result["project_type"] != "generic":
                break

        # Supplementary detection
        if "package.json" in self.top_level:
            result["package_manager"] = self._detect_node_package_manager()
            result["frameworks"] = self._detect_node_frameworks()
            result["versions"]["node"] = self._detect_node_version()

        if any(f in self.top_level for f in ["requirements.txt", "pyproject.toml", "setup.py"]):
            result["package_manager"] = self._detect_python_package_manager()
            result["versions"]["python"] = self._detect_python_version()
            result["test_framework"] = self._detect_python_test_framework()

        if "pom.xml" in self.top_level:
            result["versions"]["java"] = self._detect_java_version("pom.xml")

        if any(f in self.top_level for f in ["build.gradle", "build.gradle.kts"]):
            result["versions"]["java"] = self._detect_java_version("build.gradle")

        if "Cargo.toml" in self.top_level:
            result["versions"]["rust"] = self._detect_rust_version()

        if "go.mod" in self.top_level:
            result["versions"]["go"] = self._detect_go_version()

        # Infrastructure
        result["has_docker"] = any(
            self._match(p) for p in ["Dockerfile", "docker-compose.yml", "docker-compose.yaml"]
        )
        result["has_kubernetes"] = self.root.joinpath("k8s").exists() or self.root.joinpath("kubernetes").exists()
        result["has_terraform"] = any(self._match("*.tf") for _ in [True])
        result["has_pre_commit"] = self.root.joinpath(".pre-commit-config.yaml").exists()

        return result

    def _match(self, pattern: str) -> bool:
        if pattern.startswith("*"):
            suffix = pattern[1:]
            return any(f.endswith(suffix) for f in self.files)
        return pattern in self.files

    def _detect_node_package_manager(self) -> str:
        if "pnpm-lock.yaml" in self.top_level:
            return "pnpm"
        if "yarn.lock" in self.top_level:
            return "yarn"
        return "npm"

    def _detect_node_frameworks(self) -> List[str]:
        frameworks = []
        pkg = self.root / "package.json"
        if not pkg.exists():
            return frameworks
        text = pkg.read_text(encoding="utf-8", errors="ignore")
        fw_map = {
            "next": "Next.js",
            "nuxt": "Nuxt",
            "react": "React",
            "vue": "Vue",
            "angular": "Angular",
            "svelte": "Svelte",
            "express": "Express",
            "fastify": "Fastify",
            "nestjs": "NestJS",
            "astro": "Astro",
        }
        for key, name in fw_map.items():
            if key in text.lower():
                frameworks.append(name)
        return frameworks

    def _detect_node_version(self) -> str:
        nvmrc = self.root / ".nvmrc"
        if nvmrc.exists():
            return nvmrc.read_text().strip().lstrip("v")
        pkg = self.root / "package.json"
        if pkg.exists():
            import json
            try:
                data = json.loads(pkg.read_text())
                engines = data.get("engines", {})
                if "node" in engines:
                    return engines["node"].replace(">=", "").replace("^", "").split(".")[0]
            except Exception:
                pass
        return "20"

    def _detect_python_package_manager(self) -> str:
        if "uv.lock" in self.top_level or "pyproject.toml" in self.top_level:
            text = (self.root / "pyproject.toml").read_text(encoding="utf-8", errors="ignore")
            if "[tool.uv" in text or "uv.lock" in self.top_level:
                return "uv"
            if "[tool.poetry" in text:
                return "poetry"
        if "Pipfile" in self.top_level:
            return "pipenv"
        if "requirements.txt" in self.top_level:
            return "pip"
        return "pip"

    def _detect_python_version(self) -> str:
        dotpython = self.root / ".python-version"
        if dotpython.exists():
            return dotpython.read_text().strip()
        pyproject = self.root / "pyproject.toml"
        if pyproject.exists():
            text = pyproject.read_text()
            for line in text.splitlines():
                if "python" in line and any(c.isdigit() for c in line):
                    import re
                    match = re.search(r'(\d+\.?\d*)', line)
                    if match:
                        return match.group(1)
        return "3.11"

    def _detect_python_test_framework(self) -> str:
        pyproject = self.root / "pyproject.toml"
        if pyproject.exists():
            text = pyproject.read_text().lower()
            if "pytest" in text:
                return "pytest"
        requirements = self.root / "requirements.txt"
        if requirements.exists():
            text = requirements.read_text().lower()
            if "pytest" in text:
                return "pytest"
        setup = self.root / "setup.py"
        if setup.exists():
            text = setup.read_text().lower()
            if "pytest" in text:
                return "pytest"
        return "pytest"

    def _detect_java_version(self, build_file: str) -> str:
        path = self.root / build_file
        if not path.exists():
            return "21"
        text = path.read_text()
        import re
        # Maven property
        m = re.search(r'<java\.version>(\d+)</java\.version>', text)
        if m:
            return m.group(1)
        # Gradle
        m = re.search(r'JavaVersion\.VERSION_(\d+)', text)
        if m:
            return m.group(1)
        m = re.search(r'languageVersion\s*=\s*JavaLanguageVersion\.of\((\d+)\)', text)
        if m:
            return m.group(1)
        return "21"

    def _detect_rust_version(self) -> str:
        rust_toolchain = self.root / "rust-toolchain.toml"
        if rust_toolchain.exists():
            text = rust_toolchain.read_text()
            import re
            m = re.search(r'channel\s*=\s*"([^"]+)"', text)
            if m:
                return m.group(1)
        return "stable"

    def _detect_go_version(self) -> str:
        mod = self.root / "go.mod"
        if mod.exists():
            text = mod.read_text()
            import re
            m = re.search(r'^go\s+(\d+\.\d+)', text, re.MULTILINE)
            if m:
                return m.group(1)
        return "1.22"


class PipelineGenerator:
    """Generates platform-specific CI/CD configuration strings."""

    def __init__(self, project: Dict[str, any], args: argparse.Namespace):
        self.project = project
        self.args = args
        self.platform = args.platform

    def generate(self) -> str:
        generators = {
            "github-actions": self._github_actions,
            "gitlab-ci": self._gitlab_ci,
            "azure-devops": self._azure_devops,
            "jenkins": self._jenkins,
            "circleci": self._circleci,
            "travis": self._travis,
        }
        gen = generators.get(self.platform)
        if not gen:
            raise ValueError(f"Unsupported platform: {self.platform}")
        return gen()

    # ------------------------------------------------------------------
    # GitHub Actions
    # ------------------------------------------------------------------
    def _github_actions(self) -> str:
        ptype = self.project["project_type"]
        parts = ["name: CI", "", "on:", "  push:", "    branches: [ main ]", "  pull_request:", "    branches: [ main ]", ""]

        jobs = ["jobs:"]

        # Setup job based on type
        if ptype == "node":
            jobs.extend(self._gha_node_jobs())
        elif ptype == "python":
            jobs.extend(self._gha_python_jobs())
        elif ptype == "java":
            jobs.extend(self._gha_java_jobs())
        elif ptype == "go":
            jobs.extend(self._gha_go_jobs())
        elif ptype == "rust":
            jobs.extend(self._gha_rust_jobs())
        elif ptype == "dotnet":
            jobs.extend(self._gha_dotnet_jobs())
        else:
            jobs.extend(self._gha_generic_jobs())

        if self.args.with_docker or self.project["has_docker"]:
            jobs.extend(self._gha_docker_jobs())

        if self.args.with_security:
            jobs.extend(self._gha_security_jobs())

        if self.args.with_deploy:
            jobs.extend(self._gha_deploy_jobs())

        parts.extend(jobs)
        return "\n".join(parts)

    def _gha_node_jobs(self) -> List[str]:
        node = self.args.node_version or self.project["versions"].get("node", "20")
        pm = self.project["package_manager"]
        install_cmd = {"npm": "npm ci", "yarn": "yarn install --frozen-lockfile", "pnpm": "pnpm install --frozen-lockfile"}.get(pm, "npm ci")
        build_cmd = "npm run build" if pm == "npm" else f"{pm} run build"
        test_cmd = "npm test" if pm == "npm" else f"{pm} test"
        lint_cmd = "npm run lint" if pm == "npm" else f"{pm} run lint"

        return [
            "  build:",
            "    runs-on: ubuntu-latest",
            "    steps:",
            "      - uses: actions/checkout@v4",
            f"      - uses: actions/setup-node@v4",
            f"        with:",
            f"          node-version: '{node}'",
            f"          cache: '{pm if pm != 'yarn' else 'yarn'}'",
            f"      - run: {install_cmd}",
            f"      - run: {build_cmd}",
            "      - uses: actions/upload-artifact@v4",
            "        with:",
            "          name: build",
            "          path: dist/",
            "",
            "  test:",
            "    runs-on: ubuntu-latest",
            "    needs: build",
            "    strategy:",
            "      fail-fast: false",
            "    steps:",
            "      - uses: actions/checkout@v4",
            f"      - uses: actions/setup-node@v4",
            f"        with:",
            f"          node-version: '{node}'",
            f"          cache: '{pm if pm != 'yarn' else 'yarn'}'",
            f"      - run: {install_cmd}",
            f"      - run: {test_cmd}",
            "      - uses: actions/upload-artifact@v4",
            "        if: always()",
            "        with:",
            "          name: test-results",
            "          path: reports/",
            "",
            "  lint:",
            "    runs-on: ubuntu-latest",
            "    steps:",
            "      - uses: actions/checkout@v4",
            f"      - uses: actions/setup-node@v4",
            f"        with:",
            f"          node-version: '{node}'",
            f"          cache: '{pm if pm != 'yarn' else 'yarn'}'",
            f"      - run: {install_cmd}",
            f"      - run: {lint_cmd}",
            "",
        ]

    def _gha_python_jobs(self) -> List[str]:
        py = self.args.python_version or self.project["versions"].get("python", "3.11")
        pm = self.project["package_manager"]
        install_map = {
            "pip": "pip install -r requirements.txt",
            "poetry": "pip install poetry && poetry install",
            "pipenv": "pip install pipenv && pipenv install --dev",
            "uv": "pip install uv && uv sync",
        }
        install_cmd = install_map.get(pm, "pip install -r requirements.txt")
        test_cmd = self.project.get("test_framework", "pytest")
        cache_dep = {"pip": "pip", "poetry": "poetry", "pipenv": "pipenv", "uv": "pip"}.get(pm, "pip")

        return [
            "  build:",
            "    runs-on: ubuntu-latest",
            "    steps:",
            "      - uses: actions/checkout@v4",
            f"      - uses: actions/setup-python@v5",
            f"        with:",
            f"          python-version: '{py}'",
            f"          cache: '{cache_dep}'",
            f"      - run: {install_cmd}",
            "      - run: python -m build",
            "",
            "  test:",
            "    runs-on: ubuntu-latest",
            "    strategy:",
            "      fail-fast: false",
            "      matrix:",
            f"        python-version: ['{py}']",
            "    steps:",
            "      - uses: actions/checkout@v4",
            f"      - uses: actions/setup-python@v5",
            f"        with:",
            f"          python-version: ${{ matrix.python-version }}",
            f"          cache: '{cache_dep}'",
            f"      - run: {install_cmd}",
            f"      - run: {test_cmd}",
            "",
            "  lint:",
            "    runs-on: ubuntu-latest",
            "    steps:",
            "      - uses: actions/checkout@v4",
            f"      - uses: actions/setup-python@v5",
            f"        with:",
            f"          python-version: '{py}'",
            f"          cache: '{cache_dep}'",
            f"      - run: {install_cmd}",
            "      - run: ruff check . || flake8 . || true",
            "",
        ]

    def _gha_java_jobs(self) -> List[str]:
        java = self.args.java_version or self.project["versions"].get("java", "21")
        bt = self.project["build_tool"]
        build_cmd = "./mvnw -B package -DskipTests" if bt == "maven" else "./gradlew build -x test"
        test_cmd = "./mvnw test" if bt == "maven" else "./gradlew test"
        wrapper = "./mvnw" if bt == "maven" else "./gradlew"

        return [
            "  build:",
            "    runs-on: ubuntu-latest",
            "    steps:",
            "      - uses: actions/checkout@v4",
            f"      - uses: actions/setup-java@v4",
            f"        with:",
            f"          java-version: '{java}'",
            "          distribution: 'temurin'",
            f"          cache: '{bt}'",
            f"      - run: {build_cmd}",
            "      - uses: actions/upload-artifact@v4",
            "        with:",
            "          name: jar",
            "          path: build/libs/*.jar || target/*.jar",
            "",
            "  test:",
            "    runs-on: ubuntu-latest",
            "    needs: build",
            "    steps:",
            "      - uses: actions/checkout@v4",
            f"      - uses: actions/setup-java@v4",
            f"        with:",
            f"          java-version: '{java}'",
            "          distribution: 'temurin'",
            f"          cache: '{bt}'",
            f"      - run: {test_cmd}",
            "      - uses: actions/upload-artifact@v4",
            "        if: always()",
            "        with:",
            "          name: test-results",
            "          path: build/reports/ || target/surefire-reports/",
            "",
        ]

    def _gha_go_jobs(self) -> List[str]:
        go = self.project["versions"].get("go", "1.22")
        return [
            "  build:",
            "    runs-on: ubuntu-latest",
            "    steps:",
            "      - uses: actions/checkout@v4",
            f"      - uses: actions/setup-go@v5",
            f"        with:",
            f"          go-version: '{go}'",
            "      - run: go build ./...",
            "",
            "  test:",
            "    runs-on: ubuntu-latest",
            "    steps:",
            "      - uses: actions/checkout@v4",
            f"      - uses: actions/setup-go@v5",
            f"        with:",
            f"          go-version: '{go}'",
            "      - run: go test -race -coverprofile=coverage.out ./...",
            "      - uses: actions/upload-artifact@v4",
            "        with:",
            "          name: coverage",
            "          path: coverage.out",
            "",
            "  lint:",
            "    runs-on: ubuntu-latest",
            "    steps:",
            "      - uses: actions/checkout@v4",
            f"      - uses: actions/setup-go@v5",
            f"        with:",
            f"          go-version: '{go}'",
            "      - uses: golangci/golangci-lint-action@v6",
            "        with:",
            "          version: latest",
            "",
        ]

    def _gha_rust_jobs(self) -> List[str]:
        rust = self.project["versions"].get("rust", "stable")
        return [
            "  build:",
            "    runs-on: ubuntu-latest",
            "    steps:",
            "      - uses: actions/checkout@v4",
            f"      - uses: dtolnay/rust-toolchain@stable",
            f"        with:",
            f"          toolchain: {rust}",
            "      - uses: Swatinem/rust-cache@v2",
            "      - run: cargo build --release",
            "      - uses: actions/upload-artifact@v4",
            "        with:",
            "          name: binary",
            "          path: target/release/*",
            "",
            "  test:",
            "    runs-on: ubuntu-latest",
            "    steps:",
            "      - uses: actions/checkout@v4",
            f"      - uses: dtolnay/rust-toolchain@stable",
            f"        with:",
            f"          toolchain: {rust}",
            "      - uses: Swatinem/rust-cache@v2",
            "      - run: cargo test",
            "",
            "  lint:",
            "    runs-on: ubuntu-latest",
            "    steps:",
            "      - uses: actions/checkout@v4",
            f"      - uses: dtolnay/rust-toolchain@stable",
            f"        with:",
            f"          toolchain: {rust}",
            "          components: rustfmt, clippy",
            "      - run: cargo fmt -- --check",
            "      - run: cargo clippy -- -D warnings",
            "",
        ]

    def _gha_dotnet_jobs(self) -> List[str]:
        return [
            "  build:",
            "    runs-on: ubuntu-latest",
            "    steps:",
            "      - uses: actions/checkout@v4",
            "      - uses: actions/setup-dotnet@v4",
            "        with:",
            "          dotnet-version: '8.0.x'",
            "      - run: dotnet restore",
            "      - run: dotnet build --no-restore",
            "",
            "  test:",
            "    runs-on: ubuntu-latest",
            "    needs: build",
            "    steps:",
            "      - uses: actions/checkout@v4",
            "      - uses: actions/setup-dotnet@v4",
            "        with:",
            "          dotnet-version: '8.0.x'",
            "      - run: dotnet test --no-build --verbosity normal",
            "",
        ]

    def _gha_generic_jobs(self) -> List[str]:
        return [
            "  build:",
            "    runs-on: ubuntu-latest",
            "    steps:",
            "      - uses: actions/checkout@v4",
            "      - run: echo 'Add your build commands here'",
            "",
            "  test:",
            "    runs-on: ubuntu-latest",
            "    needs: build",
            "    steps:",
            "      - uses: actions/checkout@v4",
            "      - run: echo 'Add your test commands here'",
            "",
        ]

    def _gha_docker_jobs(self) -> List[str]:
        return [
            "  docker:",
            "    runs-on: ubuntu-latest",
            "    needs: build",
            "    steps:",
            "      - uses: actions/checkout@v4",
            "      - uses: docker/setup-buildx-action@v3",
            "      - uses: docker/build-push-action@v5",
            "        with:",
            "          context: .",
            "          push: false",
            "          tags: myapp:${{ github.sha }}",
            "          cache-from: type=gha",
            "          cache-to: type=gha,mode=max",
            "",
        ]

    def _gha_security_jobs(self) -> List[str]:
        return [
            "  security:",
            "    runs-on: ubuntu-latest",
            "    needs: build",
            "    permissions:",
            "      actions: read",
            "      contents: read",
            "      security-events: write",
            "    steps:",
            "      - uses: actions/checkout@v4",
            "      - name: Run Trivy vulnerability scanner",
            "        uses: aquasecurity/trivy-action@master",
            "        with:",
            "          scan-type: 'fs'",
            "          format: 'sarif'",
            "          output: 'trivy-results.sarif'",
            "      - uses: github/codeql-action/upload-sarif@v3",
            "        with:",
            "          sarif_file: 'trivy-results.sarif'",
            "",
        ]

    def _gha_deploy_jobs(self) -> List[str]:
        return [
            "  deploy-staging:",
            "    runs-on: ubuntu-latest",
            "    needs: [test, docker]",
            "    if: github.ref == 'refs/heads/main'",
            "    environment: staging",
            "    steps:",
            "      - uses: actions/checkout@v4",
            "      - run: echo 'Deploy to staging'",
            "",
            "  deploy-production:",
            "    runs-on: ubuntu-latest",
            "    needs: deploy-staging",
            "    if: github.ref == 'refs/heads/main'",
            "    environment: production",
            "    steps:",
            "      - uses: actions/checkout@v4",
            "      - run: echo 'Deploy to production'",
            "",
        ]

    # ------------------------------------------------------------------
    # GitLab CI
    # ------------------------------------------------------------------
    def _gitlab_ci(self) -> str:
        ptype = self.project["project_type"]
        lines = [
            "stages:",
            "  - build",
            "  - test",
        ]
        if self.args.with_security:
            lines.append("  - security")
        if self.args.with_docker or self.project["has_docker"]:
            lines.append("  - container")
        if self.args.with_deploy:
            lines.append("  - deploy")
        lines.append("")
        lines.append("variables:")
        lines.append("  DOCKER_DRIVER: overlay2")
        lines.append("")

        if ptype == "node":
            lines.extend(self._gl_node())
        elif ptype == "python":
            lines.extend(self._gl_python())
        elif ptype == "java":
            lines.extend(self._gl_java())
        elif ptype == "go":
            lines.extend(self._gl_go())
        elif ptype == "rust":
            lines.extend(self._gl_rust())
        else:
            lines.extend(self._gl_generic())

        if self.args.with_docker or self.project["has_docker"]:
            lines.extend(self._gl_docker())
        if self.args.with_security:
            lines.extend(self._gl_security())
        if self.args.with_deploy:
            lines.extend(self._gl_deploy())

        return "\n".join(lines)

    def _gl_node(self) -> List[str]:
        node = self.args.node_version or self.project["versions"].get("node", "20")
        pm = self.project["package_manager"]
        install = {"npm": "npm ci", "yarn": "yarn install --frozen-lockfile", "pnpm": "pnpm install --frozen-lockfile"}.get(pm, "npm ci")
        return [
            "default:",
            "  image: node:" + node + "-alpine",
            "  cache:",
            "    key:",
            "      files:",
            "        - package-lock.json",
            "    paths:",
            "      - node_modules/",
            "",
            "build:",
            "  stage: build",
            "  script:",
            f"    - {install}",
            "    - npm run build",
            "  artifacts:",
            "    paths:",
            "      - dist/",
            "    expire_in: 1 hour",
            "",
            "test:",
            "  stage: test",
            "  script:",
            f"    - {install}",
            "    - npm test",
            "  coverage: '/All files[^|]*\\|[^|]*\\s+([\\d\\.]+)/'",
            "  artifacts:",
            "    reports:",
            "      junit: reports/junit.xml",
            "    paths:",
            "      - coverage/",
            "",
            "lint:",
            "  stage: build",
            "  script:",
            f"    - {install}",
            "    - npm run lint",
            "",
        ]

    def _gl_python(self) -> List[str]:
        py = self.args.python_version or self.project["versions"].get("python", "3.11")
        pm = self.project["package_manager"]
        install_map = {
            "pip": "pip install -r requirements.txt",
            "poetry": "pip install poetry && poetry install",
            "pipenv": "pip install pipenv && pipenv install --dev",
            "uv": "pip install uv && uv sync",
        }
        install = install_map.get(pm, "pip install -r requirements.txt")
        return [
            "default:",
            f"  image: python:{py}-slim",
            "  cache:",
            "    key:",
            "      files:",
            "        - requirements.txt",
            "    paths:",
            "      - .cache/pip/",
            "",
            "build:",
            "  stage: build",
            "  script:",
            f"    - {install}",
            "    - python -m build",
            "  artifacts:",
            "    paths:",
            "      - dist/",
            "",
            "test:",
            "  stage: test",
            "  script:",
            f"    - {install}",
            "    - pytest --junitxml=reports/junit.xml",
            "  artifacts:",
            "    reports:",
            "      junit: reports/junit.xml",
            "",
            "lint:",
            "  stage: build",
            "  script:",
            f"    - {install}",
            "    - flake8 . || ruff check . || true",
            "",
        ]

    def _gl_java(self) -> List[str]:
        java = self.args.java_version or self.project["versions"].get("java", "21")
        bt = self.project["build_tool"]
        build = "./mvnw -B package -DskipTests" if bt == "maven" else "./gradlew build -x test"
        test = "./mvnw test" if bt == "maven" else "./gradlew test"
        img = f"eclipse-temurin:{java}-jdk"
        return [
            "default:",
            f"  image: {img}",
            "  cache:",
            "    key:",
            f"      files:",
            f"        - {('pom.xml' if bt == 'maven' else 'build.gradle')}",
            "    paths:",
            "      - .m2/repository" if bt == "maven" else "      - .gradle/caches",
            "",
            "build:",
            "  stage: build",
            "  script:",
            f"    - {build}",
            "  artifacts:",
            "    paths:",
            "      - target/*.jar" if bt == "maven" else "      - build/libs/*.jar",
            "",
            "test:",
            "  stage: test",
            "  script:",
            f"    - {test}",
            "  artifacts:",
            "    reports:",
            "      junit: target/surefire-reports/*.xml" if bt == "maven" else "      - build/reports/**/*.xml",
            "",
        ]

    def _gl_go(self) -> List[str]:
        go = self.project["versions"].get("go", "1.22")
        return [
            f"  image: golang:{go}",
            "  cache:",
            "    key:",
            "      files:",
            "        - go.mod",
            "    paths:",
            "      - /go/pkg/mod/",
            "",
            "build:",
            "  stage: build",
            "  script:",
            "    - go build ./...",
            "",
            "test:",
            "  stage: test",
            "  script:",
            "    - go test -race ./...",
            "",
        ]

    def _gl_rust(self) -> List[str]:
        return [
            "  image: rust:latest",
            "  cache:",
            "    key:",
            "      files:",
            "        - Cargo.lock",
            "    paths:",
            "      - target/",
            "      - .cargo/",
            "",
            "build:",
            "  stage: build",
            "  script:",
            "    - cargo build --release",
            "  artifacts:",
            "    paths:",
            "      - target/release/",
            "",
            "test:",
            "  stage: test",
            "  script:",
            "    - cargo test",
            "",
        ]

    def _gl_generic(self) -> List[str]:
        return [
            "build:",
            "  stage: build",
            "  script:",
            "    - echo 'Add your build commands here'",
            "",
            "test:",
            "  stage: test",
            "  script:",
            "    - echo 'Add your test commands here'",
            "",
        ]

    def _gl_docker(self) -> List[str]:
        return [
            "docker-build:",
            "  stage: container",
            "  image: docker:latest",
            "  services:",
            "    - docker:dind",
            "  variables:",
            "    DOCKER_DRIVER: overlay2",
            "  script:",
            "    - docker build -t $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA .",
            "    - docker login -u $CI_REGISTRY_USER -p $CI_REGISTRY_PASSWORD $CI_REGISTRY",
            "    - docker push $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA",
            "",
        ]

    def _gl_security(self) -> List[str]:
        return [
            "sast:",
            "  stage: security",
            "  script:",
            "    - echo 'Run semgrep or other SAST tool'",
            "  artifacts:",
            "    reports:",
            "      sast: gl-sast-report.json",
            "",
            "dependency-scan:",
            "  stage: security",
            "  script:",
            "    - echo 'Run dependency scan'",
            "  artifacts:",
            "    reports:",
            "      dependency_scanning: gl-dependency-scanning-report.json",
            "",
        ]

    def _gl_deploy(self) -> List[str]:
        return [
            "deploy-staging:",
            "  stage: deploy",
            "  script:",
            "    - echo 'Deploy to staging'",
            "  environment:",
            "    name: staging",
            "  only:",
            "    - main",
            "",
            "deploy-production:",
            "  stage: deploy",
            "  script:",
            "    - echo 'Deploy to production'",
            "  environment:",
            "    name: production",
            "  only:",
            "    - main",
            "  when: manual",
            "",
        ]

    # ------------------------------------------------------------------
    # Azure DevOps
    # ------------------------------------------------------------------
    def _azure_devops(self) -> str:
        ptype = self.project["project_type"]
        lines = [
            "trigger:",
            "  branches:",
            "    include:",
            "      - main",
            "",
            "pr:",
            "  branches:",
            "    include:",
            "      - main",
            "",
            "variables:",
            "  vmImage: 'ubuntu-latest'",
            "",
            "stages:",
        ]

        if ptype == "node":
            lines.extend(self._az_node())
        elif ptype == "python":
            lines.extend(self._az_python())
        elif ptype == "java":
            lines.extend(self._az_java())
        else:
            lines.extend(self._az_generic())

        if self.args.with_docker or self.project["has_docker"]:
            lines.extend(self._az_docker())
        if self.args.with_security:
            lines.extend(self._az_security())
        if self.args.with_deploy:
            lines.extend(self._az_deploy())

        return "\n".join(lines)

    def _az_node(self) -> List[str]:
        node = self.args.node_version or self.project["versions"].get("node", "20")
        return [
            "- stage: BuildAndTest",
            "  jobs:",
            "  - job: Build",
            "    pool:",
            "      vmImage: $(vmImage)",
            "    steps:",
            "    - task: NodeTool@0",
            "      inputs:",
            f"        versionSpec: '{node}'",
            "      displayName: 'Install Node.js'",
            "    - task: Cache@2",
            "      inputs:",
            "        key: 'npm | \"$(Agent.OS)\" | package-lock.json'",
            "        restoreKeys: |",
            "          npm | \"$(Agent.OS)\"",
            "        path: $(npm_config_cache)",
            "      displayName: 'Cache npm'",
            "    - script: npm ci",
            "      displayName: 'Install dependencies'",
            "    - script: npm run build",
            "      displayName: 'Build'",
            "    - task: PublishBuildArtifacts@1",
            "      inputs:",
            "        pathToPublish: 'dist'",
            "        artifactName: 'drop'",
            "",
            "  - job: Test",
            "    dependsOn: Build",
            "    pool:",
            "      vmImage: $(vmImage)",
            "    steps:",
            "    - task: NodeTool@0",
            "      inputs:",
            f"        versionSpec: '{node}'",
            "    - script: npm ci",
            "    - script: npm test",
            "      displayName: 'Run tests'",
            "",
        ]

    def _az_python(self) -> List[str]:
        py = self.args.python_version or self.project["versions"].get("python", "3.11")
        return [
            "- stage: BuildAndTest",
            "  jobs:",
            "  - job: Build",
            "    pool:",
            "      vmImage: $(vmImage)",
            "    steps:",
            "    - task: UsePythonVersion@0",
            "      inputs:",
            f"        versionSpec: '{py}'",
            "    - script: pip install -r requirements.txt",
            "    - script: python -m build",
            "    - task: PublishBuildArtifacts@1",
            "      inputs:",
            "        pathToPublish: 'dist'",
            "        artifactName: 'drop'",
            "",
            "  - job: Test",
            "    dependsOn: Build",
            "    pool:",
            "      vmImage: $(vmImage)",
            "    steps:",
            "    - task: UsePythonVersion@0",
            "      inputs:",
            f"        versionSpec: '{py}'",
            "    - script: pip install -r requirements.txt",
            "    - script: pytest",
            "",
        ]

    def _az_java(self) -> List[str]:
        java = self.args.java_version or self.project["versions"].get("java", "21")
        return [
            "- stage: BuildAndTest",
            "  jobs:",
            "  - job: Build",
            "    pool:",
            "      vmImage: $(vmImage)",
            "    steps:",
            "    - task: JavaToolInstaller@0",
            "      inputs:",
            f"        versionSpec: '{java}'",
            "        jdkArchitectureOption: 'x64'",
            "        jdkSourceOption: 'PreInstalled'",
            "    - task: Cache@2",
            "      inputs:",
            "        key: 'maven | \"$(Agent.OS)\" | pom.xml'",
            "        path: $(MAVEN_CACHE_FOLDER)",
            "    - script: ./mvnw -B package -DskipTests",
            "    - task: PublishBuildArtifacts@1",
            "      inputs:",
            "        pathToPublish: 'target'",
            "        artifactName: 'drop'",
            "",
            "  - job: Test",
            "    dependsOn: Build",
            "    pool:",
            "      vmImage: $(vmImage)",
            "    steps:",
            "    - task: JavaToolInstaller@0",
            "      inputs:",
            f"        versionSpec: '{java}'",
            "    - script: ./mvnw test",
            "",
        ]

    def _az_generic(self) -> List[str]:
        return [
            "- stage: BuildAndTest",
            "  jobs:",
            "  - job: Build",
            "    pool:",
            "      vmImage: $(vmImage)",
            "    steps:",
            "    - script: echo 'Add build commands'",
            "",
        ]

    def _az_docker(self) -> List[str]:
        return [
            "- stage: Container",
            "  jobs:",
            "  - job: Docker",
            "    pool:",
            "      vmImage: $(vmImage)",
            "    steps:",
            "    - task: Docker@2",
            "      inputs:",
            "        containerRegistry: 'myRegistry'",
            "        repository: 'myapp'",
            "        command: 'buildAndPush'",
            "        Dockerfile: '**/Dockerfile'",
            "        tags: |",
            "          $(Build.BuildId)",
            "",
        ]

    def _az_security(self) -> List[str]:
        return [
            "- stage: Security",
            "  jobs:",
            "  - job: SAST",
            "    pool:",
            "      vmImage: $(vmImage)",
            "    steps:",
            "    - script: echo 'Run SAST scan'",
            "",
        ]

    def _az_deploy(self) -> List[str]:
        return [
            "- stage: Deploy",
            "  jobs:",
            "  - deployment: DeployStaging",
            "    pool:",
            "      vmImage: $(vmImage)",
            "    environment: 'staging'",
            "    strategy:",
            "      runOnce:",
            "        deploy:",
            "          steps:",
            "          - script: echo 'Deploy to staging'",
            "",
        ]

    # ------------------------------------------------------------------
    # Jenkins
    # ------------------------------------------------------------------
    def _jenkins(self) -> str:
        ptype = self.project["project_type"]
        lines = [
            "pipeline {",
            "    agent any",
            "    options {",
            "        buildDiscarder(logRotator(numToKeepStr: '10'))",
            "        timeout(time: 30, unit: 'MINUTES')",
            "    }",
            "    stages {",
        ]

        if ptype == "node":
            lines.extend(self._jk_node())
        elif ptype == "python":
            lines.extend(self._jk_python())
        elif ptype == "java":
            lines.extend(self._jk_java())
        else:
            lines.extend(self._jk_generic())

        if self.args.with_docker or self.project["has_docker"]:
            lines.extend(self._jk_docker())
        if self.args.with_security:
            lines.extend(self._jk_security())
        if self.args.with_deploy:
            lines.extend(self._jk_deploy())

        lines.extend([
            "    }",
            "    post {",
            "        always {",
            "            junit '**/reports/*.xml'",
            "            archiveArtifacts artifacts: 'dist/**/*', allowEmptyArchive: true",
            "        }",
            "    }",
            "}",
        ])
        return "\n".join(lines)

    def _jk_node(self) -> List[str]:
        node = self.args.node_version or self.project["versions"].get("node", "20")
        return [
            f"        stage('Install') {{",
            "            steps {",
            f"                nodejs(nodeJSInstallationName: 'NodeJS-{node}') {{",
            "                    sh 'npm ci'",
            "                }",
            "            }",
            "        }",
            "        stage('Build') {",
            "            steps {",
            f"                nodejs(nodeJSInstallationName: 'NodeJS-{node}') {{",
            "                    sh 'npm run build'",
            "                }",
            "            }",
            "        }",
            "        stage('Test') {",
            "            steps {",
            f"                nodejs(nodeJSInstallationName: 'NodeJS-{node}') {{",
            "                    sh 'npm test'",
            "                }",
            "            }",
            "        }",
        ]

    def _jk_python(self) -> List[str]:
        py = self.args.python_version or self.project["versions"].get("python", "3.11")
        return [
            f"        stage('Build') {{",
            "            steps {",
            f"                sh 'python{py} -m pip install -r requirements.txt'",
            "                sh 'python -m build'",
            "            }",
            "        }",
            "        stage('Test') {",
            "            steps {",
            "                sh 'pytest'",
            "            }",
            "        }",
        ]

    def _jk_java(self) -> List[str]:
        java = self.args.java_version or self.project["versions"].get("java", "21")
        bt = self.project["build_tool"]
        build = "./mvnw -B package -DskipTests" if bt == "maven" else "./gradlew build -x test"
        test = "./mvnw test" if bt == "maven" else "./gradlew test"
        return [
            f"        stage('Build') {{",
            "            steps {",
            f"                sh '{build}'",
            "            }",
            "        }",
            "        stage('Test') {",
            "            steps {",
            f"                sh '{test}'",
            "            }",
            "        }",
        ]

    def _jk_generic(self) -> List[str]:
        return [
            "        stage('Build') {",
            "            steps {",
            "                sh 'echo Add build commands'",
            "            }",
            "        }",
        ]

    def _jk_docker(self) -> List[str]:
        return [
            "        stage('Docker') {",
            "            steps {",
            "                sh 'docker build -t myapp:${BUILD_NUMBER} .'",
            "            }",
            "        }",
        ]

    def _jk_security(self) -> List[str]:
        return [
            "        stage('Security Scan') {",
            "            steps {",
            "                sh 'echo Run security scan'",
            "            }",
            "        }",
        ]

    def _jk_deploy(self) -> List[str]:
        return [
            "        stage('Deploy') {",
            "            when {",
            "                branch 'main'",
            "            }",
            "            steps {",
            "                sh './deploy.sh'",
            "            }",
            "        }",
        ]

    # ------------------------------------------------------------------
    # CircleCI
    # ------------------------------------------------------------------
    def _circleci(self) -> str:
        ptype = self.project["project_type"]
        lines = [
            "version: 2.1",
            "",
            "executors:",
            "  default:",
            "    docker:",
            "      - image: cimg/base:stable",
            "",
            "jobs:",
        ]

        if ptype == "node":
            lines.extend(self._cci_node())
        elif ptype == "python":
            lines.extend(self._cci_python())
        elif ptype == "java":
            lines.extend(self._cci_java())
        else:
            lines.extend(self._cci_generic())

        if self.args.with_docker or self.project["has_docker"]:
            lines.extend(self._cci_docker())
        if self.args.with_security:
            lines.extend(self._cci_security())

        lines.extend([
            "",
            "workflows:",
            "  build-and-test:",
            "    jobs:",
        ])
        if ptype in ["node", "python", "java", "go", "rust", "dotnet"]:
            lines.append("      - build")
            lines.append("      - test:")
            lines.append("          requires: [build]")
        else:
            lines.append("      - build")

        if self.args.with_docker or self.project["has_docker"]:
            lines.append("      - docker:")
            lines.append("          requires: [build, test]")
        if self.args.with_security:
            lines.append("      - security:")
            lines.append("          requires: [build, test]")
        if self.args.with_deploy:
            lines.append("      - deploy:")
            lines.append("          requires: [build, test]")
            lines.append("          filters:")
            lines.append("            branches:")
            lines.append("              only: main")

        return "\n".join(lines)

    def _cci_node(self) -> List[str]:
        node = self.args.node_version or self.project["versions"].get("node", "20")
        pm = self.project["package_manager"]
        install = {"npm": "npm ci", "yarn": "yarn install --frozen-lockfile", "pnpm": "pnpm install --frozen-lockfile"}.get(pm, "npm ci")
        return [
            "  build:",
            f"    docker:",
            f"      - image: cimg/node:{node}.0",
            "    steps:",
            "      - checkout",
            f"      - run: {install}",
            "      - run: npm run build",
            "      - persist_to_workspace:",
            "          root: .",
            "          paths:",
            "            - dist",
            "",
            "  test:",
            f"    docker:",
            f"      - image: cimg/node:{node}.0",
            "    parallelism: 2",
            "    steps:",
            "      - checkout",
            "      - attach_workspace:",
            "          at: .",
            f"      - run: {install}",
            "      - run:",
            "          name: Run tests",
            "          command: |",
            f"            TEST_FILES=$(circleci tests glob '**/*.test.js' | circleci tests split --split-by=timings)",
            f"            npm test -- $TEST_FILES",
            "      - store_test_results:",
            "          path: reports/junit",
            "",
        ]

    def _cci_python(self) -> List[str]:
        py = self.args.python_version or self.project["versions"].get("python", "3.11")
        return [
            "  build:",
            f"    docker:",
            f"      - image: cimg/python:{py}",
            "    steps:",
            "      - checkout",
            "      - run: pip install -r requirements.txt",
            "      - run: python -m build",
            "      - persist_to_workspace:",
            "          root: .",
            "          paths:",
            "            - dist",
            "",
            "  test:",
            f"    docker:",
            f"      - image: cimg/python:{py}",
            "    steps:",
            "      - checkout",
            "      - attach_workspace:",
            "          at: .",
            "      - run: pip install -r requirements.txt",
            "      - run: pytest",
            "      - store_test_results:",
            "          path: reports/junit",
            "",
        ]

    def _cci_java(self) -> List[str]:
        java = self.args.java_version or self.project["versions"].get("java", "21")
        return [
            "  build:",
            f"    docker:",
            f"      - image: cimg/openjdk:{java}.0",
            "    steps:",
            "      - checkout",
            "      - run: ./mvnw -B package -DskipTests",
            "      - persist_to_workspace:",
            "          root: .",
            "          paths:",
            "            - target",
            "",
            "  test:",
            f"    docker:",
            f"      - image: cimg/openjdk:{java}.0",
            "    steps:",
            "      - checkout",
            "      - attach_workspace:",
            "          at: .",
            "      - run: ./mvnw test",
            "      - store_test_results:",
            "          path: target/surefire-reports",
            "",
        ]

    def _cci_generic(self) -> List[str]:
        return [
            "  build:",
            "    executor: default",
            "    steps:",
            "      - checkout",
            "      - run: echo 'Add build commands'",
            "",
        ]

    def _cci_docker(self) -> List[str]:
        return [
            "  docker:",
            "    executor: default",
            "    steps:",
            "      - checkout",
            "      - setup_remote_docker:",
            "          docker_layer_caching: true",
            "      - run: docker build -t myapp:${CIRCLE_SHA1} .",
            "",
        ]

    def _cci_security(self) -> List[str]:
        return [
            "  security:",
            "    executor: default",
            "    steps:",
            "      - checkout",
            "      - run: echo 'Run security scan'",
            "",
        ]

    # ------------------------------------------------------------------
    # Travis CI
    # ------------------------------------------------------------------
    def _travis(self) -> str:
        ptype = self.project["project_type"]
        lines = []

        if ptype == "node":
            lines.extend(self._tv_node())
        elif ptype == "python":
            lines.extend(self._tv_python())
        elif ptype == "java":
            lines.extend(self._tv_java())
        elif ptype == "go":
            lines.extend(self._tv_go())
        elif ptype == "rust":
            lines.extend(self._tv_rust())
        else:
            lines.extend(self._tv_generic())

        lines.extend([
            "",
            "script:",
            "  - echo 'Build and test commands go here'",
        ])

        if self.args.with_deploy:
            lines.extend(self._tv_deploy())

        return "\n".join(lines)

    def _tv_node(self) -> List[str]:
        node = self.args.node_version or self.project["versions"].get("node", "20")
        return [
            f"language: node_js",
            f"node_js:",
            f"  - \"{node}\"",
            "cache:",
            "  npm: true",
        ]

    def _tv_python(self) -> List[str]:
        py = self.args.python_version or self.project["versions"].get("python", "3.11")
        return [
            f"language: python",
            f"python:",
            f"  - \"{py}\"",
            "cache:",
            "  pip: true",
        ]

    def _tv_java(self) -> List[str]:
        java = self.args.java_version or self.project["versions"].get("java", "21")
        distros = {"21": "openjdk21", "17": "openjdk17", "11": "openjdk11", "8": "openjdk8"}
        dist = distros.get(str(java), "openjdk21")
        return [
            f"language: java",
            f"jdk:",
            f"  - {dist}",
        ]

    def _tv_go(self) -> List[str]:
        go = self.project["versions"].get("go", "1.22")
        return [
            f"language: go",
            f"go:",
            f"  - \"{go}\"",
        ]

    def _tv_rust(self) -> List[str]:
        return [
            "language: rust",
            "rust:",
            "  - stable",
            "cache: cargo",
        ]

    def _tv_generic(self) -> List[str]:
        return [
            "language: generic",
        ]

    def _tv_deploy(self) -> List[str]:
        return [
            "",
            "deploy:",
            "  provider: script",
            "  script: bash deploy.sh",
            "  on:",
            "    branch: main",
        ]


def main():
    parser = argparse.ArgumentParser(description="Generate CI/CD pipeline configuration")
    parser.add_argument("--platform", required=True,
                        choices=["github-actions", "gitlab-ci", "azure-devops", "jenkins", "circleci", "travis"],
                        help="Target CI/CD platform")
    parser.add_argument("--output", default=None,
                        help="Output file path (default: platform-specific default)")
    parser.add_argument("--with-docker", action="store_true", default=None,
                        help="Include Docker build stage")
    parser.add_argument("--with-deploy", action="store_true", default=False,
                        help="Include deployment stages")
    parser.add_argument("--with-security", action="store_true", default=True,
                        help="Include security scanning stages")
    parser.add_argument("--node-version", default=None, help="Override Node.js version")
    parser.add_argument("--python-version", default=None, help="Override Python version")
    parser.add_argument("--java-version", default=None, help="Override Java version")
    args = parser.parse_args()

    # Auto-detect docker if not explicitly disabled
    detector = ProjectDetector()
    project = detector.detect()
    if args.with_docker is None:
        args.with_docker = project["has_docker"]

    # Determine default output path
    default_outputs = {
        "github-actions": ".github/workflows/ci.yml",
        "gitlab-ci": ".gitlab-ci.yml",
        "azure-devops": "azure-pipelines.yml",
        "jenkins": "Jenkinsfile",
        "circleci": ".circleci/config.yml",
        "travis": ".travis.yml",
    }
    output_path = Path(args.output) if args.output else Path(default_outputs[args.platform])

    generator = PipelineGenerator(project, args)
    config = generator.generate()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(config, encoding="utf-8")
    print(f"Generated {args.platform} pipeline at {output_path}")
    print(f"Detected project type: {project['project_type']}")
    if project["build_tool"]:
        print(f"Build tool: {project['build_tool']}")
    if project["package_manager"]:
        print(f"Package manager: {project['package_manager']}")


if __name__ == "__main__":
    main()
