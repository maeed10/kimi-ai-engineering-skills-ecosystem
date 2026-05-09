# Code Review Checklist

## Universal Checks (All Languages)

Apply these checks to every pull request regardless of language or framework.

### Correctness
- [ ] Logic matches the stated intent of the PR
- [ ] Edge cases handled (null, empty, overflow, underflow)
- [ ] Error paths are tested and do not leave system in inconsistent state
- [ ] No off-by-one errors in loops or array access
- [ ] Concurrency handled safely (race conditions, deadlocks)
- [ ] Idempotency maintained where required

### Maintainability
- [ ] Functions/methods are cohesive and do one thing
- [ ] Naming is clear, consistent with codebase conventions, and pronounceable
- [ ] No duplicated logic (DRY); refactor opportunities noted
- [ ] Comments explain "why", not "what"; no commented-out code
- [ ] Complexity is appropriate (cyclomatic complexity < 10 ideally)
- [ ] Magic numbers and strings extracted to named constants

### Testing
- [ ] New code has corresponding unit/integration tests
- [ ] Tests cover happy path, error paths, and boundary conditions
- [ ] Tests are deterministic (no flakes)
- [ ] No tests are skipped without a tracked ticket
- [ ] Test names describe behavior, not implementation
- [ ] Mocking is appropriate; no mocking what you don't own

### Documentation
- [ ] Public APIs have docstrings/comments
- [ ] README/docs updated for user-visible changes
- [ ] Complex algorithms have inline explanation or linked reference
- [ ] Breaking changes documented with migration path

---

## Security Checklist

### Input & Data Handling
- [ ] All user inputs validated (type, length, format, range)
- [ ] SQL queries use parameterized statements (no string concatenation)
- [ ] No user input rendered directly into HTML/JS (XSS prevention)
- [ ] File uploads restricted by type, size, and scanned for malware
- [ ] Path traversal prevented (normalize paths, restrict base directories)
- [ ] Deserialization of untrusted data is safe or avoided

### Authentication & Authorization
- [ ] New endpoints require authentication unless explicitly public
- [ ] Authorization checks verify resource ownership (not just authentication)
- [ ] Sensitive operations require re-authentication or MFA
- [ ] Session/tokens have reasonable expiration and secure storage
- [ ] Passwords handled with bcrypt/Argon2/scrypt (never plain or MD5/SHA1)
- [ ] API keys not logged or exposed in error messages

### Cryptography
- [ ] Randomness uses cryptographically secure generators
- [ ] Encryption at rest uses approved algorithms (AES-256-GCM)
- [ ] Encryption in transit uses TLS 1.2+ with strong cipher suites
- [ ] Keys/credentials stored in vaults, not code or config files
- [ ] No custom crypto implementations; use well-vetted libraries

### Secrets & Leakage
- [ ] No hardcoded passwords, tokens, or private keys in source
- [ ] No `.env` files or secrets committed to repository
- [ ] Logging does not include PII, credentials, or session tokens
- [ ] Error messages are informative to developers but not to attackers
- [ ] Stack traces hidden from production API responses

---

## Performance Checklist

### Algorithmic Efficiency
- [ ] No nested loops producing O(n^2) or worse without justification
- [ ] Database queries do not run in loops (N+1 query problem)
- [ ] Pagination used for large result sets
- [ ] Expensive computations cached where appropriate
- [ ] No unnecessary data serialization/deserialization

### Resource Management
- [ ] Database connections, file handles, and sockets closed reliably
- [ ] Memory-intensive operations bounded (streaming, not buffering)
- [ ] No memory leaks in long-running processes (event listeners, caches)
- [ ] Thread pool sizes are bounded and tunable
- [ ] Circuit breakers and timeouts on external service calls

### Frontend / Client-Side
- [ ] Large assets lazy-loaded or code-split
- [ ] Images optimized and served in modern formats where possible
- [ ] Debounce/throttle high-frequency events (scroll, resize, input)
- [ ] No main-thread blocking computations
- [ ] Bundle size impact assessed for new dependencies

---

## Language-Specific Checklists

### Python
- [ ] Type hints present for function signatures and public APIs
- [ ] No bare `except:` clauses; catch specific exceptions
- [ ] Context managers (`with`) used for resource cleanup
- [ ] `isinstance` preferred over `type() ==` for type checking
- [ ] Mutable default arguments avoided in function definitions
- [ ] F-strings or proper formatting used; no `%` formatting in new code
- [ ] `__eq__` and `__hash__` defined together when customizing equality
- [ ] Imports ordered (stdlib, third-party, local) and unused imports removed
- [ ] `if __name__ == "__main__":` guard present in executable scripts
- [ ] No `print()` debugging left in production code; use logging
- [ ] Dataclasses or attrs used where plain classes store data
- [ ] Async code: await used correctly; no blocking calls in async functions

### JavaScript / TypeScript
- [ ] `===` and `!==` used instead of `==` and `!=`
- [ ] `async/await` preferred over raw Promise chains
- [ ] No `var`; use `let` or `const` appropriately
- [ ] TypeScript: no `any` without justification; strict null checks enabled
- [ ] Null/undefined handled explicitly (optional chaining where appropriate)
- [ ] Event listeners removed when components unmount
- [ ] No `eval()`, `new Function()`, or dynamic script injection
- [ ] JSON parsed safely with try/catch when source is untrusted
- [ ] React/Vue/Angular: keys provided in lists; effects have correct deps
- [ ] No floating promises; all async calls awaited or handled
- [ ] Dependencies locked; `package-lock.json` or `yarn.lock` updated

### Java / Kotlin
- [ ] Null safety: `Optional` or null checks; Kotlin null-safety enforced
- [ ] Streams/collections used idiomatically; no manual accumulation loops
- [ ] Exceptions used for exceptional cases, not control flow
- [ ] `equals()` and `hashCode()` overridden together
- [ ] `toString()` implemented for value objects
- [ ] Resource management with try-with-resources or `@PreDestroy`
- [ ] Thread safety: immutable objects preferred; synchronization explicit
- [ ] Spring: constructor injection used; no field injection
- [ ] Logging framework used (SLF4J); no `System.out.println`
- [ ] Lombok or records used judiciously; not overused

### Go
- [ ] Errors handled explicitly; no ignored return values
- [ ] Context propagated through call chains
- [ ] Goroutines have recover() or are supervised
- [ ] Channels closed by sender, not receiver
- [ ] Slice bounds checked when indexing externally provided data
- [ ] `defer` used for cleanup
- [ ] No global mutable state
- [ ] Interfaces defined by consumer, not producer
- [ ] Tests use table-driven patterns
- [ ] `go vet` and `gofmt` pass

### Rust
- [ ] `Result` and `Option` propagated or unwrapped with justification
- [ ] No `unsafe` blocks without documented invariants
- [ ] Lifetimes minimized; `'static` avoided where possible
- [ ] `Clone` implemented only when needed
- [ ] Iterators preferred over manual indexing
- [ ] Panics reserved for unrecoverable states
- [ ] `Drop` implemented for resources requiring cleanup
- [ ] Concurrency: `Send`/`Sync` correctness verified

### C / C++
- [ ] Buffer sizes checked; no `strcpy`, `sprintf`, `gets`
- [ ] Memory allocations have matching free
- [ ] Smart pointers (`unique_ptr`, `shared_ptr`) preferred in C++
- [ ] RAII used for resource management
- [ ] No undefined behavior (aliasing, strict overflow, alignment)
- [ ] `const` correctness applied
- [ ] Thread synchronization correct (lock ordering, no data races)
- [ ] Valgrind/ASAN clean for new allocations

### Ruby
- [ ] No monkey-patching of core classes
- [ ] `&.` safe navigation used where appropriate
- [ ] Exceptions rescued specifically; no bare `rescue`
- [ ] Symbols vs strings used intentionally
- [ ] Blocks, procs, and lambdas used correctly
- [ ] ActiveRecord queries not executed in views
- [ ] Migrations are reversible

### Shell / Bash
- [ ] Scripts start with `set -euo pipefail`
- [ ] Variables quoted: `"$var"` not `$var`
- [ ] No parsing of `ls` output; use globs or `find`
- [ ] Temporary files created with `mktemp`
- [ ] No secrets in command-line arguments (visible in `ps`)
- [ ] Scripts are idempotent where possible

---

## Database & Data Layer

- [ ] Schema migrations are backward-compatible (or deployed in phases)
- [ ] Indexes added for new query patterns
- [ ] Migrations do not lock tables excessively
- [ ] Transactions scoped correctly; not too broad or too narrow
- [ ] Soft deletes preferred over hard deletes for auditability
- [ ] Data integrity enforced at DB level (constraints, foreign keys)
- [ ] Sensitive data encrypted or tokenized at rest
- [ ] Query plans reviewed for large-scale changes (EXPLAIN ANALYZE)

---

## Infrastructure & DevOps

- [ ] IaC changes have `plan` output reviewed before apply
- [ ] No hardcoded IPs, ARNs, or resource IDs
- [ ] Secrets referenced from vault/parameter store, not inline
- [ ] Least-privilege IAM policies applied
- [ ] Resource tagging strategy followed
- [ ] Health checks and graceful shutdown configured
- [ ] Logging and monitoring alerts updated for new components

---

## Review Etiquette

### For Reviewers
- [ ] Review within 24 hours for routine PRs; 4 hours for hotfixes
- [ ] Separate blocking concerns from suggestions/nits
- [ ] Explain the "why" behind requested changes
- [ ] Acknowledge good patterns, not just issues
- [ ] Approve if minor nits remain, with trust that author will fix

### For Authors
- [ ] Keep PRs small and focused (< 400 lines when possible)
- [ ] Self-review before requesting others
- [ ] Respond to all comments, even if just with an emoji or resolution note
- [ ] Re-request review after significant changes, don't assume reviewer will notice
