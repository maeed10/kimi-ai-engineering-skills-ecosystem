# Python-Specific Blast Radius Analysis

Language-specific guidance for impact analysis in Python codebases.

## Dependency Detection

### Import Resolution Patterns
- **Absolute imports**: `import module`, `from package import module` — follow `sys.path`, affected by `PYTHONPATH`
- **Relative imports**: `from . import module`, `from ..package import module` — resolved at runtime, break if module executed directly
- **Dynamic imports**: `__import__()`, `importlib.import_module()`, `importlib.reload()` — static analysis cannot trace; flag for manual review
- **Conditional imports**: imports inside `if` blocks or `try/except` — call graph may be incomplete

### Key Detection Strategies
- Parse `ast.Import` and `ast.ImportFrom` nodes for static import graphs
- Use `jedi` or `pyright` for symbol resolution and reference finding
- Detect dynamic imports via regex search for `__import__`, `importlib` — mark as analysis gaps
- Check `requirements.txt`, `pyproject.toml`, `setup.py` for external dependency changes

### Framework-Specific Routing Patterns

**Flask**:
- Route handlers registered via `@app.route()` — change to a route handler affects URL mapping
- Blueprint registration: `app.register_blueprint()` — changes to blueprints affect all routes within
- Before/after request hooks: global middleware affects all routes
- URL builders (`url_for()`) break if route signatures change

**Django**:
- URLconf patterns in `urls.py` — change to a view function affects reverse URL resolution
- Model changes trigger migration requirements and QuerySet API impacts
- Middleware in `MIDDLEWARE` setting — order matters, insertion affects request/response pipeline
- Signal handlers: decoupled but critical to trace — model `post_save` signals affect all save paths

**FastAPI**:
- Dependency injection via `Depends()` — trace both direct and nested dependency chains
- Router inclusion: `app.include_router()` — changes propagate to all included routes
- Pydantic model changes affect request validation, response serialization, and OpenAPI schema

## Dynamic Analysis Limitations

Python's dynamic nature creates specific blast radius blind spots:

- **Monkey patching**: Any module can replace functions/classes at runtime. Static analysis cannot predict monkey-patched code paths.
- **Duck typing**: Functions accept any object with the right methods. Call graphs miss type-specific code paths unless type hints are present and checked.
- **Metaclasses and descriptors**: `__get__`, `__set__`, metaclass `__new__` — behavior changes in these affect every instance of the class.
- `**kwargs` and `*args`: Parameter additions/removals may break callers using positional or keyword expansion.
- **Property decorators**: Changing a method to a property (or vice versa) breaks all callers.
- **Decorators**: `@wraps` preserves metadata but changes runtime behavior; undecorated functions lose traceability.

### Mitigation Strategies
- Enforce type hints (`mypy` / `pyright` strict mode) to improve static analysis accuracy
- Use `bandit` for security-focused static analysis
- Run `pytest` with coverage to validate dynamic paths missed by static tools
- Document all monkey-patching and metaclass usage as high-risk areas
- Prefer explicit interfaces over duck typing for critical paths

## Tool Recommendations

| Purpose | Tool | Command / Config |
|---------|------|-------------------|
| Static dependency graph | `pydeps`, `modulegraph` | `pydeps --show-deps package_name` |
| Import analysis | `ast` module, `jedi` | Custom AST traversal for import nodes |
| Call graph | `pycallgraph2`, CodeQL for Python | `pycallgraph2 graphviz --output-file=callgraph.png` |
| Type checking | `mypy`, `pyright` | `mypy --strict package_name` |
| Security scan | `bandit` | `bandit -r package_name` |
| Test coverage | `pytest-cov` | `pytest --cov=package_name --cov-report=json` |
| Complexity | `radon`, `xenon` | `radon cc package_name -a` |
