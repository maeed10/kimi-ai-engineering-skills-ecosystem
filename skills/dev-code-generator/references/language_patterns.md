# Language Patterns Reference

Comprehensive per-language idioms, naming conventions, type system patterns, error handling styles, and import organization rules. Load the relevant section before generating code to ensure idiomatic, context-matching output.

---

## Python

### Naming Conventions
| Construct | Convention | Example |
|---|---|---|
| Modules / files | `snake_case.py` | `user_service.py` |
| Packages / directories | `lowercase` (no underscores if possible) | `authutils` |
| Classes | `PascalCase` | `UserRepository` |
| Functions | `snake_case` | `get_user_by_id` |
| Constants | `UPPER_SNAKE_CASE` | `MAX_RETRY_COUNT` |
| Variables | `snake_case` | `is_active` |
| Private / internal | `_leading_underscore` | `_internal_helper` |
| Dunder methods | `__dunder__` | `__init__`, `__repr__` |

### Type Patterns
- Use type hints for all function signatures (PEP 484).
- Prefer `from __future__ import annotations` for forward references (Python 3.7+).
- Use `Optional[T]` or `T | None` (Python 3.10+) for nullable values.
- Use `list[T]`, `dict[K, V]` (Python 3.9+) instead of `typing.List`, `typing.Dict`.
- Use `Protocol` for structural subtyping (duck typing with types).
- Use `NamedTuple` or `@dataclass` for simple data carriers.
- Use `TypedDict` for dictionary schemas with known keys.
- Use `NewType` to create distinct types from primitives.

### Error Handling
- Use exceptions for truly exceptional cases; use `Result` types only if the project already uses them.
- Catch specific exceptions, never bare `except:`.
- Use `try/except/else/finally` blocks; keep the `try` body minimal.
- Chain exceptions with `raise NewError from original`.
- Log at the boundary; re-raise or wrap for caller context.

### Import Organization
1. `__future__` imports
2. Standard library
3. Third-party
4. Local application / project imports
Separate each group with a blank line. Use `isort` / `ruff` ordering rules.

### Idiomatic Patterns
- **Context managers**: Use `@contextmanager` decorator for resource management.
- **Comprehensions**: Prefer `[x for x in items if cond]` over `filter(lambda ...)`.
- **Generators**: Use `yield` for streaming/large datasets; functions returning iterators should be typed as `Iterator[T]` or `Generator[T, None, None]`.
- **String formatting**: Use f-strings for interpolation; use `pathlib.Path` for filesystem paths.
- **Dataclasses / Pydantic**: Use Pydantic for API validation; use `@dataclass(frozen=True)` for immutable value objects.
- **Dependency injection**: Use function arguments and protocols, not global state.

---

## JavaScript / TypeScript

### Naming Conventions
| Construct | Convention | Example |
|---|---|---|
| Files (JS) | `camelCase.js` or `PascalCase.jsx` | `userService.js`, `UserCard.jsx` |
| Files (TS) | `camelCase.ts` or `PascalCase.tsx` | `userService.ts`, `UserCard.tsx` |
| Variables / functions | `camelCase` | `fetchUserData` |
| Classes / components | `PascalCase` | `UserRepository`, `LoginForm` |
| Constants | `UPPER_SNAKE_CASE` (true const) or `camelCase` | `API_BASE_URL` |
| Interfaces / types | `PascalCase` (prefix `I` optional, discouraged) | `User`, `UserProps` |
| Enums | `PascalCase` for enum, `PascalCase` for members | `Status { Active = 'active' }` |
| Private fields | `#privateField` or `_leadingUnderscore` | `#count`, `_helper` |

### Type Patterns (TypeScript)
- Prefer `interface` for object shapes that may be extended; use `type` for unions, tuples, mapped types.
- Use `strict` mode (`noImplicitAny`, `strictNullChecks`).
- Use `unknown` instead of `any` for truly unknown values; narrow with type guards.
- Use discriminated unions (`{ kind: 'A', ... } | { kind: 'B', ... }`) for complex state machines.
- Use generics with constraints: `function sort<T extends Comparable>(items: T[]): T[]`.
- Use `readonly` for immutable properties; use `Readonly<T>` and `ReadonlyArray<T>`.
- Use utility types: `Partial<T>`, `Pick<T, K>`, `Omit<T, K>`, `Record<K, V>`.
- Use `satisfies` operator (TS 4.9+) for inline validation without widening.

### Error Handling
- Prefer `async/await` with `try/catch` over `.then().catch()` chains.
- Use custom `Error` subclasses for domain errors: `class ValidationError extends Error {}`.
- In callbacks, use the Node.js convention `(err, result) => {}` only for legacy APIs.
- Use `Promise.allSettled` when partial failure is acceptable.
- In Express/NestJS, use error-handling middleware consistently.

### Import Organization
- Group: built-ins → third-party → internal (absolute aliases) → relative (`../../` last).
- Use path aliases (`@/`, `~/`) configured in `tsconfig.json` / `jsconfig.json`.
- Prefer named imports for tree-shaking: `import { useState } from 'react'`.
- Avoid default exports in libraries; prefer named exports for discoverability.

### Idiomatic Patterns
- **Nullish coalescing**: Use `value ?? defaultValue` instead of `||` for defaults.
- **Optional chaining**: `obj?.prop?.method?.()`.
- **Array methods**: Prefer `map`, `filter`, `reduce`, `find`, `some` over manual loops.
- **Destructuring**: Use in function params and assignments: `const { id, name } = user`.
- **Strict equality**: Always use `===` and `!==`; never `==` or `!=`.
- **Arrow functions**: Use for callbacks and non-method functions; preserve `this` context.
- **React**: Use functional components + hooks; avoid class components in new code.

---

## Go

### Naming Conventions
| Construct | Convention | Example |
|---|---|---|
| Files | `snake_case.go` (all lowercase) | `user_service.go` |
| Packages | `lowercase` (short, concise) | `userrepo`, `httputil` |
| Exported identifiers | `PascalCase` | `GetUserByID` |
| Unexported identifiers | `camelCase` | `validateEmail` |
| Constants | `CamelCase` or `PascalCase` (no `ALL_CAPS`) | `MaxBufferSize` |
| Acronyms | All same case (`URL`, `HTTP`, `ID`) | `ServeHTTP`, `userID` |
| Interface names | Method name + `-er` / `-or` | `Reader`, `Writer`, `Stringer` |
| Test files | `*_test.go` | `user_service_test.go` |

### Type Patterns
- Use `struct` for data carriers; embed structs for composition (not inheritance).
- Define interfaces where the consumer sits (accept interfaces, return structs).
- Use `any` (Go 1.18+) sparingly; prefer generics with type parameters for reusable containers.
- Use type aliases for clarity: `type UserID string`.
- Use `iota` for enumerated constants.

### Error Handling
- Return `(T, error)` with `error` as the last return value.
- Wrap errors with `fmt.Errorf("... %w", err)` for stack context.
- Use `errors.Is` and `errors.As` for error inspection.
- Panic only for programmer errors (unreachable code); recover at goroutine boundaries if necessary.
- Never ignore errors with `_` unless explicitly documented and safe.

### Import Organization
- Single import block: `import ("fmt"; "strings")`.
- Group stdlib first, then blank-line, then third-party.
- Never use dot imports (`. "package"`).
- Use `goimports` / `gofmt` for formatting.

### Idiomatic Patterns
- **Context propagation**: First param is `ctx context.Context` for cancellable operations.
- **Goroutines & channels**: Use `chan` for coordination; prefer `for range` over `for select` when possible.
- **Slices over arrays**: Use slices for dynamic collections; preallocate with `make([]T, 0, capacity)`.
- **Maps**: Check existence with `v, ok := m[key]`.
- **Defer**: Use `defer` for resource cleanup (files, mutex unlocks, response body close).
- **Methods on pointers**: Use pointer receivers for mutability or when struct is large.
- **JSON**: Use struct tags (`json:"field_name,omitempty"`) for API contracts.

---

## Rust

### Naming Conventions
| Construct | Convention | Example |
|---|---|---|
| Files | `snake_case.rs` | `user_service.rs` |
| Modules | `snake_case` | `auth_utils` |
| Structs / Enums / Traits | `PascalCase` | `UserRepository`, `ConnectionError` |
| Functions / methods | `snake_case` | `get_user_by_id` |
| Variables | `snake_case` | `is_active` |
| Constants / statics | `UPPER_SNAKE_CASE` | `MAX_RETRY_COUNT` |
| Lifetimes | `'lowercase` | `'a`, `'data` |
| Generic params | `PascalCase` (single letter or words) | `T`, `Item` |
| Macros | `snake_case!` | `println!`, `vec!` |

### Type Patterns
- Use `struct` for named fields; use tuple structs for newtypes (`struct UserId(String)`).
- Use `enum` for sum types with data; leverage `match` exhaustiveness.
- Use `Option<T>` for nullability; use `Result<T, E>` for fallible operations.
- Use `?` operator for early return of `Err` or `None`.
- Use `impl Trait` for return-position and argument-position type erasure.
- Use generics with trait bounds: `fn process<T: Serialize + Clone>(item: T)`.
- Use `Rc<RefCell<T>>` for single-threaded shared mutability; `Arc<Mutex<T>>` / `Arc<RwLock<T>>` for multi-threaded.
- Use `Cow<'a, str>` for efficient clone-on-write strings.

### Error Handling
- Define custom errors as `enum` implementing `std::error::Error` (use `thiserror` crate).
- Use `anyhow` for application code where error types are less critical.
- Chain errors with `.context()` (anyhow) or `#[source]` (thiserror).
- Use `panic!` only for bugs, not for expected failures.
- Validate invariants with `assert!`, `debug_assert!`, or `unreachable!`.

### Import Organization
- Group: std → third-party (crates.io) → local (`crate::`, `super::`, `self::`).
- Use `use crate::module::Item;` for absolute imports.
- Use nested imports: `use std::{collections::HashMap, io::Read}`.
- Prefer `use` over fully qualified names for readability.

### Idiomatic Patterns
- **Iterators**: Prefer iterator adapters (`.map`, `.filter`, `.collect`) over `for` loops.
- **Ownership**: Pass by reference (`&T`, `&mut T`) to avoid clones; use `.clone()` explicitly when needed.
- **Builders**: Use consuming builder pattern for complex struct initialization.
- **Drop trait**: Implement `Drop` for RAII resource management.
- **Traits**: Define small, composable traits; implement extension traits for foreign types.
- **Unsafe**: Isolate `unsafe` blocks; document invariants; keep minimal.
- **Async**: Use `async fn` + `await`; prefer `tokio` runtime for async execution.

---

## Java

### Naming Conventions
| Construct | Convention | Example |
|---|---|---|
| Files | `PascalCase.java` | `UserService.java` |
| Packages | `com.company.project.module` | `com.example.auth` |
| Classes / Interfaces | `PascalCase` | `UserRepository`, `UserService` |
| Interfaces (adjective-style) | `PascalCase` | `Serializable`, `Comparable` |
| Methods / variables | `camelCase` | `getUserById`, `isActive` |
| Constants | `UPPER_SNAKE_CASE` | `MAX_RETRY_COUNT` |
| Generic params | `Single uppercase letter` | `T`, `K`, `V`, `E` |
| Test classes | `PascalCaseTest` or `PascalCaseIT` | `UserServiceTest` |

### Type Patterns
- Use `var` for local variables (Java 10+) when type is obvious.
- Use `Optional<T>` for nullable returns; never return bare `null` from public APIs.
- Use `record` for immutable DTOs (Java 16+).
- Use `sealed` classes/interfaces (Java 17+) for controlled inheritance hierarchies.
- Use generics with bounds: `<T extends Comparable<? super T>>`.
- Use `Stream` API for collection transformations; prefer method references (`User::getName`).
- Use `Map.of`, `List.of`, `Set.of` for small immutable collections (Java 9+).
- Use `CompletableFuture` for async composition; use `HttpClient` (Java 11+) for HTTP.

### Error Handling
- Use checked exceptions for recoverable conditions; use unchecked (`RuntimeException`) for programming errors.
- Wrap low-level exceptions into domain exceptions at layer boundaries.
- Use `try-with-resources` for `AutoCloseable` types.
- Log exceptions at the appropriate layer; avoid swallowing with empty `catch` blocks.

### Import Organization
- Group: `java.*` / `javax.*` → third-party (`org.springframework`, `com.google`) → static imports (`java.util.Collections.*`).
- Use wildcard imports (`java.util.*`) only for deep utility classes; prefer explicit imports for clarity.
- No blank line between `java` and `javax` groups; blank line before third-party and static.

### Idiomatic Patterns
- **Builder pattern**: Use for classes with many optional fields (Lombok `@Builder` or manual).
- **Dependency injection**: Use constructor injection with Spring/CDI; avoid field injection.
- **Immutability**: Make fields `final` where possible; return unmodifiable collections.
- **Functional interfaces**: Use `Supplier`, `Function`, `Predicate`, `Consumer` from `java.util.function`.
- **Modules**: Use Java Platform Module System (`module-info.java`) for strong encapsulation when applicable.
- **Lombok**: Use sparingly; prefer records for DTOs. If used, annotate with `@Getter`, `@RequiredArgsConstructor`.

---

## C#

### Naming Conventions
| Construct | Convention | Example |
|---|---|---|
| Files | `PascalCase.cs` | `UserService.cs` |
| Namespaces | `PascalCase` (company/product hierarchy) | `MyCompany.Auth` |
| Classes / structs | `PascalCase` | `UserRepository` |
| Interfaces | `PascalCase` with `I` prefix | `IUserService` |
| Methods / properties | `PascalCase` | `GetUserById`, `IsActive` |
| Fields (private) | `_camelCase` or `_PascalCase` | `_userId`, `UserId` |
| Constants | `PascalCase` or `UPPER_SNAKE_CASE` | `MaxRetryCount` |
| Local variables / params | `camelCase` | `isActive` |
| Generic params | `T`, `TKey`, `TValue` | `T`, `TEntity` |
| Enums | `PascalCase` (members too) | `Status { Active, Inactive }` |

### Type Patterns
- Use `var` for local variables when type is obvious from the right-hand side.
- Use `record` (C# 9+) and `record struct` (C# 10+) for immutable value types.
- Use `nullable` reference types (`string?`, `T?`) with `<Nullable>enable</Nullable>`.
- Use `Span<T>` / `ReadOnlySpan<T>` for high-performance memory slicing.
- Use `async/await` with `Task` / `Task<T>` / `ValueTask<T>`.
- Use `IEnumerable<T>` / `IAsyncEnumerable<T>` for streaming sequences.
- Use `Dictionary<K,V>`, `HashSet<T>`, `List<T>` for collections; prefer interfaces in public APIs.
- Use `pattern matching` (`is`, `switch` expressions) for type/condition branching.

### Error Handling
- Use exceptions for exceptional conditions; use `Result<T>` types (language-ext, FluentResults) if project already uses them.
- Create custom exceptions inheriting from `Exception` or `ApplicationException`.
- Use `try/catch/finally` and `using` declarations (C# 8+) for disposal.
- Use `ConfigureAwait(false)` in library code to avoid deadlocks; avoid in UI/ASP.NET entry points.
- Validate arguments with `ArgumentNullException.ThrowIfNull(param)` (C# 10+ / .NET 6+).

### Import Organization
- `using` statements at top of file.
- Group: `System.*` → Microsoft / .NET → third-party NuGet → project aliases.
- Use global usings (`global using System;`) in .NET 6+ to reduce repetition in `csproj` or `GlobalUsings.cs`.
- Use static usings (`using static System.Math;`) for utility classes.

### Idiomatic Patterns
- **LINQ**: Prefer query syntax or method syntax for transformations; be mindful of `IQueryable` vs `IEnumerable`.
- **Expression-bodied members**: Use `=>` for simple methods and properties.
- **String interpolation**: `$"Hello, {name}"`; use `StringBuilder` for heavy concatenation.
- **Dependency injection**: Register services in `IServiceCollection` with lifetimes (`Transient`, `Scoped`, `Singleton`).
- **Configuration**: Use `IConfiguration`, `IOptions<T>`, and strongly-typed settings classes.
- **Attributes / reflection**: Use for cross-cutting concerns (validation, serialization, authorization).
- **Events**: Use `EventHandler<TEventArgs>` pattern for pub/sub within a component.

---

## Ruby

### Naming Conventions
| Construct | Convention | Example |
|---|---|---|
| Files | `snake_case.rb` | `user_service.rb` |
| Classes / modules | `PascalCase` (called CamelCase in Ruby) | `UserRepository`, `AuthUtils` |
| Methods / variables | `snake_case` | `get_user_by_id`, `is_active` |
| Constants | `UPPER_SNAKE_CASE` | `MAX_RETRY_COUNT` |
| Predicate methods | `snake_case?` | `active?`, `valid?` |
| Destructive / bang methods | `snake_case!` | `save!`, `compact!` |
| Instance variables | `@snake_case` | `@user_id` |
| Class variables | `@@snake_case` | `@@instance` (avoid if possible) |
| Global variables | `$snake_case` | `$logger` (avoid if possible) |
| Symbols | `snake_case` | `:status`, `:user_id` |

### Type Patterns
- Ruby is dynamically typed; use RBS or Sorbet (`sig`) for gradual typing in larger codebases.
- Use `duck typing` over explicit type checks (`is_a?`, `kind_of?`).
- Use `Struct` or `Data` (Ruby 3.2+) for simple data objects.
- Use `OpenStruct` sparingly; prefer explicit classes.
- Use `nil` for absence; use `&.`, `||`, `dig` for safe navigation.
- Use keyword arguments for clarity: `def greet(name:, greeting: "Hello")`.
- Use splat and double-splat for flexibility: `def log(*msgs, **opts)`.

### Error Handling
- Use `raise` / `rescue` / `ensure` for exception handling.
- Rescue specific exceptions; avoid bare `rescue` (defaults to `StandardError` — acceptable but explicit is better).
- Use custom exception classes inheriting from `StandardError`.
- Use `retry` with caution; always limit retry counts.
- Use `ensure` for cleanup (close files, release locks).

### Import Organization
- `require` for standard library and gems.
- `require_relative` for project-internal files.
- `autoload` for lazy loading in large libraries.
- No strict grouping rules; group by domain or alphabetically.
- Bundler manages gem dependencies via `Gemfile`.

### Idiomatic Patterns
- **Blocks, Procs, Lambdas**: Use blocks for iteration callbacks; use `&:` shorthand (`users.map(&:name)`).
- **Enumerable**: Prefer `map`, `select`, `reduce`, `find`, `any?` over `for` loops.
- **Module mixins**: Use `include` for instance methods, `extend` for class methods, `prepend` for overriding.
- **Metaprogramming**: Use `define_method`, `method_missing`, and `const_missing` sparingly; always document.
- **Monkey patching**: Avoid global core class patches; use refinements (`Module#refine`) for scoped changes.
- **Gems**: Use `bundler` for dependency management; use `rake` for task automation.
- **Testing**: Use `minitest` (standard) or `rspec`. Write descriptive specs with `describe`/`it` blocks.
- **Rails-specific**: Follow Rails conventions (fat model, skinny controller); use ActiveRecord wisely; use concerns for shared behavior.

---

## Quick Decision Table

| Concern | Python | JS/TS | Go | Rust | Java | C# | Ruby |
|---|---|---|---|---|---|---|---|
| Null handling | `None` / `Optional` | `null` / `undefined` / `?` | zero value / `nil` | `Option<T>` | `Optional<T>` / `null` | `null` / `?` | `nil` |
| Error primary style | Exceptions | `try/catch` + `Result` types | `error` return | `Result<T,E>` | Exceptions | Exceptions | `raise/rescue` |
| Async primitive | `async/await` | `Promise` / `async/await` | goroutines + channels | `async/await` + `Future` | `CompletableFuture` | `Task` / `async/await` | `Fiber` / `async` gem |
| Iteration | Comprehensions / generators | `.map`/`.filter` | `for range` | Iterator adapters | `Stream` API | LINQ | Enumerable |
| Immutable DTO | `@dataclass(frozen=True)` / Pydantic | `readonly` / `as const` | struct (copy) | `#[derive(Clone)]` | `record` | `record` | `Data.define` / `Struct` |
| String interpolation | f-strings | template literals / `${}` | `fmt.Sprintf` | `format!("{}", x)` | `String.format` | `$"..."` | `"#{var}"` |
