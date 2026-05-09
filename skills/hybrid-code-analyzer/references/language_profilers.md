# Language Profilers Reference

Setup instructions per language for dynamic call-graph collection.

## Python — `sys.monitoring` (preferred) / `sys.settrace`

### `sys.monitoring` (Python 3.12+)

```python
# hybrid_tracer.py
import sys, sys.monitoring, json, atexit

_TOOL_ID = sys.monitoring.DEBUGGER
_events = []

def _call_handler(code, instruction_offset, callable_obj, arg0):
    caller = sys._getframe(1)
    _events.append({
        "caller": f"{caller.f_code.co_filename}:{caller.f_code.co_name}",
        "callee": f"{getattr(callable_obj, '__module__', '?')}"
                  f".{getattr(callable_obj, '__qualname__', repr(callable_obj))}",
        "ts": sys.time()
    })

sys.monitoring.use_tool_id(_TOOL_ID, "hybrid-analyzer")
sys.monitoring.set_events(_TOOL_ID, sys.monitoring.events.PY_CALL)
sys.monitoring.register_callback(_TOOL_ID, sys.monitoring.events.PY_CALL, _call_handler)

def _flush():
    with open(".hybrid/traces/py_trace.jsonl", "a") as f:
        for ev in _events:
            f.write(json.dumps(ev) + "\n")

atexit.register(_flush)
```

### `sys.settrace` (fallback for < 3.12)

```python
import sys, json, atexit
_events = []

def _tracer(frame, event, arg):
    if event == 'call':
        caller = sys._getframe(1) if event == 'call' else frame.f_back
        if caller:
            _events.append({
                "caller": f"{caller.f_code.co_filename}:{caller.f_code.co_name}",
                "callee": f"{frame.f_code.co_filename}:{frame.f_code.co_name}"
            })
    return _tracer

sys.settrace(_tracer)

def _flush():
    with open(".hybrid/traces/py_trace.jsonl", "a") as f:
        for ev in _events:
            f.write(json.dumps(ev) + "\n")

atexit.register(_flush)
```

### Injection

Add to test runner entry point:

```python
# conftest.py (pytest) or __main__ guard
import os
if os.environ.get("HYBRID_COLLECT"):
    exec(open(".hybrid/hybrid_tracer.py").read())
```

Run: `HYBRID_COLLECT=1 pytest tests/ -x`

## Java — JVMTI / ByteBuddy Agent

### ByteBuddy Agent (recommended)

```java
// HybridTracerAgent.java
import net.bytebuddy.agent.builder.AgentBuilder;
import net.bytebuddy.asm.Advice;
import java.lang.instrument.Instrumentation;
import java.nio.file.*;

public class HybridTracerAgent {
    static final Path OUT = Path.of(".hybrid/traces/java_trace.jsonl");

    public static void premain(String args, Instrumentation inst) {
        Files.createDirectories(OUT.getParent());
        new AgentBuilder.Default()
            .type(ElementMatchers.any())
            .transform((builder, td, cl, module) ->
                builder.visit(Advice.to(CallAdvice.class)
                    .on(ElementMatchers.any())))
            .installOn(inst);
    }

    static class CallAdvice {
        @Advice.OnMethodEnter
        static void enter(@Advice.Origin String method) {
            StackWalker.getInstance().walk(frames -> {
                String caller = frames.skip(1).findFirst()
                    .map(f -> f.getDeclaringClass() + "." + f.getMethodName())
                    .orElse("?");
                Files.writeString(OUT,
                    String.format("{\"caller\":\"%s\",\"callee\":\"%s\"}\n", caller, method),
                    StandardOpenOption.APPEND, StandardOpenOption.CREATE);
                return null;
            });
        }
    }
}
```

### Maven/Gradle Integration

```xml
<!-- pom.xml profile -->
<profile>
  <id>hybrid-collect</id>
  <build>
    <plugins>
      <plugin>
        <groupId>org.apache.maven.plugins</groupId>
        <artifactId>maven-surefire-plugin</artifactId>
        <configuration>
          <argLine>-javaagent:${project.basedir}/.hybrid/HybridTracerAgent.jar</argLine>
        </configuration>
      </plugin>
    </plugins>
  </build>
</profile>
```

Run: `mvn test -Phybrid-collect`

## JavaScript / TypeScript — V8 Coverage / Node Inspector

### V8 Precise Coverage

```javascript
// hybrid_tracer.js
const fs = require('fs');
const inspector = require('inspector');
const session = new inspector.Session();
session.connect();

const events = [];
session.on('Debugger.paused', () => session.post('Debugger.resume'));

// Enable precise coverage
session.post('Profiler.enable');
session.post('Profiler.startPreciseCoverage', { callCount: true, detailed: true });

async function collect() {
  return new Promise((resolve) => {
    session.post('Profiler.takePreciseCoverage', (err, coverage) => {
      const out = fs.createWriteStream('.hybrid/traces/js_trace.jsonl', { flags: 'a' });
      for (const script of coverage.result) {
        for (const fn of script.functions) {
          if (fn.functionName && fn.ranges.some(r => r.count > 0)) {
            out.write(JSON.stringify({
              caller: 'unknown', // resolved via source-map post-process
              callee: `${script.url}:${fn.functionName}`,
              hits: fn.ranges.reduce((s, r) => s + r.count, 0)
            }) + '\n');
          }
        }
      }
      out.end();
      resolve();
    });
  });
}

process.on('exit', () => collect());
```

### Run

```bash
node --inspect-brk=0 --require ./.hybrid/hybrid_tracer.js \
  $(npm bin)/jest --runInBand
curl -s http://localhost:9229/json/list | jq -r '.[0].id' | \
  xargs -I{} node -e "require('./hybrid_tracer').collect()"
```

### Post-Process Source Maps

Static graph uses transpiled names; dynamic trace uses runtime names. Run source-map resolution before merge:

```bash
npx source-map-resolve .hybrid/traces/js_trace.jsonl \
  --out .hybrid/traces/js_trace_resolved.jsonl
```

## Go — `runtime/trace` + `runtime/pprof`

### Custom Tracer

```go
// hybrid_tracer.go
package hybrid

import (
    "encoding/json"
    "os"
    "runtime"
    "runtime/pprof"
    "runtime/trace"
)

type Edge struct {
    Caller string `json:"caller"`
    Callee string `json:"callee"`
    Hits   int    `json:"hits"`
}

func StartTrace(tracePath, profPath string) (func(), error) {
    tf, err := os.Create(tracePath)
    if err != nil { return nil, err }
    trace.Start(tf)

    pf, err := os.Create(profPath)
    if err != nil { return nil, err }
    pprof.StartCPUProfile(pf)

    return func() {
        trace.Stop()
        pprof.StopCPUProfile()
        tf.Close()
        pf.Close()
        _extractEdges(tracePath, ".hybrid/traces/go_trace.jsonl")
    }, nil
}

func _extractEdges(tracePath, outPath string) {
    // Parse trace file to extract goroutine create/transition edges
    // Go trace format is binary; use golang.org/x/tools/go/trace or
    // github.com/felixge/traceutils for parsing
}
```

### Test Integration

```go
// TestMain injection
func TestMain(m *testing.M) {
    if os.Getenv("HYBRID_COLLECT") != "" {
        stop, err := hybrid.StartTrace(".hybrid/traces/go.raw", ".hybrid/traces/go.prof")
        if err != nil { panic(err) }
        defer stop()
    }
    os.Exit(m.Run())
}
```

Run: `HYBRID_COLLECT=1 go test ./...`

## Coverage Requirements

| Coverage | Action |
|----------|--------|
| `>= 80%` | Optimal — dynamic graph highly reliable |
| `60-80%` | Acceptable — flag `INCOMPLETE_TRACES` warning |
| `30-60%` | Risky — require manual confirmation before merge |
| `< 30%`  | Abort — insufficient data for meaningful merge |

To increase coverage before profiling:
- Run integration tests, not just unit tests
- Enable all feature flags / configuration profiles
- Execute CLI entry points and background job handlers
