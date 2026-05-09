# JavaScript/TypeScript-Specific Blast Radius Analysis

Language-specific guidance for impact analysis in JavaScript and TypeScript codebases.

## Dependency Detection

### Module Resolution Patterns
- **ESM imports**: `import { foo } from './module.js'` — static, tree-shakeable, resolved at build time
- **CommonJS requires**: `const foo = require('./module')` — dynamic, can be conditional, harder to statically analyze
- **Dynamic imports**: `import('./module')` — returns Promise, conditionally loaded, static analysis may miss
- ** Barrel exports**: `export * from './submodule'` — centralizes API surface but obscures direct dependencies
- **Glob / path imports**: `require.context()` (Webpack), `import.meta.glob()` (Vite) — bulk imports that resist static tracing

### Key Detection Strategies
- Parse `import` / `export` declarations via `@babel/parser` or `typescript` compiler API
- Use `dependency-cruiser` for architecture validation and import tracing
- Detect `require()` chains in CommonJS — flag dynamic `require(variable)` as analysis gaps
- Check `package.json` dependencies, `package-lock.json` / `yarn.lock` / `pnpm-lock.yaml` for external library changes

### Framework-Specific Routing Patterns

**Express.js**:
- Route handlers: `app.get('/path', handler)` — changes to `handler` affect that HTTP endpoint
- Router mounting: `app.use('/api', router)` — changes to `router` affect all sub-routes
- Middleware chain: `app.use(middleware)` — insertion order matters, global middleware affects all routes
- `next()` propagation: error-handling middleware with 4-arity `(err, req, res, next)` — changes affect error response paths

**NestJS**:
- Module imports/exports: `@Module({ imports, exports })` — module graph changes affect dependency injection
- Controllers and providers: decorator metadata drives the DI container — changing `@Injectable()` scope (DEFAULT vs REQUEST) changes lifecycle
- Guards, interceptors, pipes: global vs controller-scoped vs route-scoped — trace all levels
- Database entity changes in TypeORM/Prisma affect repository layer and all queries

**React/Next.js**:
- Component trees: prop changes at high-level components affect all children
- Context providers: `React.createContext()` — changes to context value type affect all consumers
- Route changes in Next.js App Router: `page.js`, `layout.js` files affect rendering tree
- Server Actions: changes affect both server execution and client-side optimistic updates

## Dynamic Analysis Limitations

JavaScript's dynamic nature creates specific blast radius blind spots:

- **Prototype mutation**: `Object.prototype`, `Array.prototype` extensions affect all instances globally
- **`eval()` and `Function()` constructor**: Code executed via `eval` is invisible to static analysis
- **Property access via bracket notation**: `obj[dynamicKey]` — cannot determine which property is accessed statically
- **`this` binding**: `.call()`, `.apply()`, `.bind()` change function context — affects closure and method behavior
- **Polymorphic functions**: Functions that accept varying argument types/shapes — each shape is a separate code path
- **Event emitters**: Decoupled pub/sub patterns (Node.js `EventEmitter`, browser `CustomEvent`) — trace all `on`/`emit` pairs
- **Proxy objects**: `new Proxy(target, handler)` — intercepts all property access, static analysis cannot trace through

### TypeScript-Specific Considerations
- Type-only imports (`import type`) do not affect runtime but affect compilation — include in blast radius for build-time impact
- Declaration merging: `interface` and `namespace` merging across files — changes in one file affect merged declarations
- Generic constraints: tightening generic constraints breaks all callers with looser types
- `satisfies` operator: changing a `satisfies` target type does not change the runtime value but affects downstream type inference
- Module resolution differences: `Node` vs `NodeNext` vs `Bundler` — affects which files are included in the build

### Mitigation Strategies
- Use `dependency-cruiser` with architectural rules to enforce module boundaries
- Enable TypeScript `strict` mode to catch more issues at compile time
- Use ESLint with `no-eval`, `no-implied-eval` rules to limit dynamic code
- Document all `eval()`, proxy usage, and prototype extensions as high-risk areas
- Run `jest --coverage` or `vitest --coverage` to validate paths missed by static analysis

## Tool Recommendations

| Purpose | Tool | Command / Config |
|---------|------|-------------------|
| Import/dependency graph | `dependency-cruiser` | `depcruise --output-type dot src` |
| Static analysis | ESLint, `@typescript-eslint` | `eslint . --ext .ts,.tsx` |
| Call graph | CodeQL for JS/TS | Custom CodeQL queries |
| Type checking | `tsc --noEmit` | `npx tsc --noEmit --project tsconfig.json` |
| Test coverage | `jest --coverage`, `vitest --coverage`, `c8` | `jest --coverage --coverageReporters=json-summary` |
| Bundle analysis | `webpack-bundle-analyzer`, `rollup-plugin-visualizer` | Analyze chunk dependencies |
| Security scan | `eslint-plugin-security`, `npm audit` | `npm audit --audit-level=moderate` |
