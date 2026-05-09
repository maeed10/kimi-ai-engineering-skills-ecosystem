---
name: dev-code-generator
description: Developer-facing intelligent code generator with language/framework auto-detection, context-aware imports, and idiomatic template library. Use when implementing features from descriptions, scaffolding projects, generating boilerplate, or converting pseudocode to production code. Supports Python, JavaScript/TypeScript, Go, Rust, Java, C#, Ruby with type safety and best practices.
---

# Dev Code Generator

## Overview

The `dev-code-generator` skill transforms natural language descriptions, pseudocode, and requirements into production-quality, idiomatic code. It auto-detects the target language and framework from project context, matches existing codebase style and conventions, and applies established templates for common software engineering patterns. The skill prioritizes type safety, correct imports, documentation, and adherence to language-specific best practices.

## Workflow Decision Tree

```
User Request
│
├─→ "Implement X" / "Create Y" / "Build Z"
│   │
│   ├─→ Existing codebase visible?
│   │   ├─→ YES → Read existing files → Detect language/framework
│   │   │             → Match naming conventions & import style
│   │   │             → Match architectural patterns
│   │   └─→ NO  → Ask user or infer from file extension / description
│   │
│   ├─→ Request matches known template?
│   │   ├─→ YES → Load template → Customize to context → Generate
│   │   └─→ NO  → Build from language patterns → Generate idiomatic code
│   │
│   └─→ Generate code → Resolve imports → Add documentation → Output
│
├─→ "Scaffold project / Init service"
│   └─→ Select project template → Generate directory structure
│       → Generate config files → Generate starter code → Output
│
└─→ "Convert pseudocode / Write algorithm"
    └─→ Parse logic → Map to language constructs → Optimize idioms
        → Add types → Add documentation → Output
```

## Core Capabilities

### 1. Language & Framework Auto-Detection
- **Detection sources**: File extensions (`.py`, `.ts`, `.go`, `.rs`, `.java`, `.cs`, `.rb`), existing imports, `package.json`, `go.mod`, `Cargo.toml`, `requirements.txt`, `pom.xml`, `Gemfile`, directory structure.
- **Supported languages**: Python, JavaScript, TypeScript, Go, Rust, Java, C#, Ruby.
- **Supported frameworks**: React, Vue, Django, FastAPI, Flask, Express, NestJS, Spring Boot, ASP.NET Core, Rails, Gin, Actix.
- **Fallback**: If ambiguous, generate in the most common language for the template (Python for backends, TypeScript for frontends) and ask user to confirm.

### 2. Context-Aware Code Generation
- **Style matching**: Before generating, read 3-5 existing files to infer:
  - Naming conventions (`snake_case` vs `camelCase` vs `PascalCase`)
  - Quote style (single vs double)
  - Import organization (stdlib-first, grouped, absolute vs relative)
  - Async/await vs callback vs sync patterns
  - Error handling style (exceptions vs result types vs error returns)
- **Dependency awareness**: Use detected dependency manager to generate correct import/install statements.

### 3. Template Library
Pre-built, parameterized templates for common developer tasks. See `references/template_library.md` for full specifications.

| Template Category | Included Patterns |
|---|---|
| **CRUD APIs** | REST controllers, GraphQL resolvers, repository layer, service layer, DTOs/validators |
| **Auth & Security** | JWT middleware, OAuth2 handlers, session management, RBAC decorators, password hashing utilities |
| **Database** | ORM models, migrations, seeders, connection pooling, transaction wrappers |
| **CLI Tools** | Argument parsing, subcommands, progress bars, colored output, configuration file handling |
| **Microservices** | Health check endpoints, structured logging, config loaders, circuit breaker, gRPC stubs |
| **Testing** | Unit test scaffolds, integration test harnesses, mock fixtures, property-based tests |
| **Background Jobs** | Task queues, scheduled workers, retry logic with backoff, dead-letter handling |

### 4. Import & Dependency Resolution
- **Python**: `import` vs `from ... import ...`, `requirements.txt` / `pyproject.toml` entries.
- **JS/TS**: `import` / `require`, `package.json` dependencies, path aliases (`@/`, `~/`).
- **Go**: Module path resolution, stdlib vs third-party grouping, dot imports avoidance.
- **Rust**: Crate imports, `use` statements, feature-gated modules.
- **Java**: Package declarations, `import` static vs instance, Maven/Gradle coordinates.
- **C#**: `using` statements, namespace matching, NuGet package hints.
- **Ruby**: `require` vs `require_relative`, gem dependencies.

### 5. Type Safety & Documentation
- Generate typed code whenever the language supports it.
- Include docstrings (Python), JSDoc/TSDoc (JS/TS), Go doc comments, Rust `///` docs, JavaDoc, XML docs (C#), YARD (Ruby).
- Document function parameters, return values, exceptions/errors, and side effects.

## Code Generation Workflow

### Step 1: Detect Context
1. If working in an existing project, list files in the current directory and subdirectories (max depth 2).
2. Identify the dominant language by file count and extension.
3. Look for framework signatures:
   - `package.json` + React/Vue/Next dependencies → JS/TS frontend
   - `manage.py` / `django` imports → Django
   - `main.py` + `fastapi` imports → FastAPI
   - `go.mod` + `gin` / `echo` / `fiber` → Go web framework
   - `pom.xml` / `build.gradle` + `spring` → Spring Boot
   - `Cargo.toml` + `actix-web` / `axum` / `rocket` → Rust web framework
4. Read 2-4 existing source files to capture style conventions.

### Step 2: Select or Build Template
1. Compare user request against template library (`references/template_library.md`).
2. If match found, load the template and identify customization points:
   - Entity/resource names
   - Field names and types
   - Route paths or method names
   - Database/table names
3. If no match, construct code from language idioms (`references/language_patterns.md`).

### Step 3: Generate Code
1. Write the primary code blocks following detected conventions.
2. Generate imports using dependency manager context.
3. Add type annotations, generics, or interfaces where idiomatic.
4. Generate tests alongside implementation when appropriate (TDD mode).
5. Add inline comments for complex logic; add docstrings for public APIs.

### Step 4: Validate & Output
1. Ensure generated code is syntactically plausible (balanced braces, correct indentation).
2. Ensure no placeholder strings remain (`TODO`, `FIXME` only where intentional).
3. Present the code in fenced blocks with language identifiers.
4. If multiple files are generated, label each block with the proposed file path.
5. Summarize what was generated and how to integrate it (imports, install commands, registration).

## Language Support Matrix

| Language | Type System | Style Enforcer | Doc Format | Package File |
|---|---|---|---|---|
| Python | Type hints (PEP 484) | PEP 8 | Google/NumPy docstrings | `requirements.txt`, `pyproject.toml` |
| JavaScript | JSDoc / TypeScript | ESLint (Prettier) | JSDoc / TSDoc | `package.json` |
| TypeScript | Static types | ESLint / tsconfig | TSDoc | `package.json` |
| Go | Static (interface-based) | gofmt / goimports | Go doc comments | `go.mod` |
| Rust | Static (trait-based) | rustfmt / clippy | `///` rustdoc | `Cargo.toml` |
| Java | Static (generics) | Checkstyle / Spotless | JavaDoc | `pom.xml`, `build.gradle` |
| C# | Static (generics) | .editorconfig / dotnet-format | XML docs | `.csproj`, `packages.config` |
| Ruby | Duck typing | RuboCop | YARD / RDoc | `Gemfile` |

## Best Practices & Conventions

### Idiomatic Code Rules
- **Python**: Prefer list comprehensions over `map/filter` for simple cases. Use `pathlib` for paths. Use `dataclasses` or `Pydantic` for DTOs. Handle errors with exceptions; use `try/except` narrowly.
- **JavaScript/TypeScript**: Prefer `async/await` over raw Promises. Use destructuring. Prefer `const`/`let` over `var`. Use optional chaining (`?.`) and nullish coalescing (`??`).
- **Go**: Return errors as the last value. Use `ctx context.Context` as first param for cancellable functions. Prefer composition over inheritance. Use `io.Reader`/`io.Writer` interfaces.
- **Rust**: Use `Result` and `Option` with `?` operator. Prefer iterator chains over explicit loops. Leverage `match` exhaustiveness. Use `Arc<Mutex<T>>` for shared state.
- **Java**: Use `Optional` for nullable returns. Prefer `Stream` APIs for collections. Use `record` for immutable DTOs (Java 16+). Use `var` for local variables (Java 10+).
- **C#**: Use `async/await` with `Task`/`Task<T>`. Use LINQ for collection operations. Use `record` for immutable DTOs. Prefer `IEnumerable<T>` over arrays for public APIs.
- **Ruby**: Use blocks and Enumerable methods. Prefer symbol keys in hashes. Use `&.` safe navigation operator. Follow `snake_case` everywhere.

### Security Defaults
- Sanitize user inputs near entry points.
- Use parameterized queries / ORM to prevent injection.
- Use constant-time comparison for secrets.
- Generate code that validates JWTs with proper expiration checks.
- Never hardcode secrets; always use environment variables or config loaders.

## Integration with References

- **`references/language_patterns.md`** — Deep-dive per-language idioms, naming conventions, type system patterns, error handling styles, and import organization rules. Load this when generating code in a specific language to ensure idiomatic output.
- **`references/template_library.md`** — Full template specifications with parameter lists, file structures, and customization instructions. Load this when the user request matches a known pattern (CRUD, auth, CLI, microservice, etc.).
- **`scripts/generate_code.py`** — Executable script for offline or automated code generation. Can analyze a local directory, detect language/framework, and emit scaffolded files.

## Example Usage Prompts

| User Prompt | Skill Action |
|---|---|
| "Create a FastAPI endpoint for user registration with email validation" | Detect FastAPI context → Load REST CRUD template → Generate router + Pydantic schema + service function + `httpx` test. |
| "Scaffold a Go CLI tool that reads YAML config and prints a table" | Detect Go → Load CLI template → Generate `cobra` command + `viper` config loader + `tablewriter` output. |
| "Write a Rust function that paginates a database query" | Detect Rust + `sqlx`/`diesel` → Generate generic `paginate` helper with `LimitOffset` trait, `Result` returns, and doc comments. |
| "Add JWT auth middleware to this Express app" | Read existing Express files → Load auth middleware template → Generate `passport` or `jsonwebtoken` middleware matching existing style. |

## File Outputs

When generating multi-file outputs, always provide:
1. **File path** relative to project root.
2. **Complete file content** in a code fence.
3. **Registration step** (how to wire the new file into the existing app: import, mount, register, or configure).
4. **Dependency install command** if new packages are required.
