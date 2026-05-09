# Stack Trace Parsing Patterns

Language-specific recipes for programmatically parsing stack traces, resolving symbols, and extracting debug context across production runtime environments.

## Python Traceback Parsing

**Standard library** [^374^]:
```python
import traceback
import sys

def parse_traceback(exc):
    """Extract structured frame data from an exception."""
    tb = exc.__traceback__
    frames = traceback.extract_tb(tb)
    # frames is a StackSummary of FrameSummary objects:
    #   filename, lineno, name, line (source text), locals (if available)
    return [
        {
            "file": f.filename,
            "line": f.lineno,
            "function": f.name,
            "source": f.line,
        }
        for f in frames
    ]
```

**Enhanced extraction with locals** [^365^][^369^]:
```python
import stack_data  # Alex Mojaki's library

def extract_with_locals(tb):
    frame = tb.tb_frame
    data = stack_data.FrameInfo(frame, tb.tb_lineno)
    return {
        "file": data.filename,
        "line": data.lineno,
        "function": data.code.co_name,
        "source": data.executing.text(),
        "variables": {
            name: repr(value)
            for name, value in data.frame.f_locals.items()
        }
    }
```

**Frame filtering** — distinguish application from library code:
```python
import pathlib

def is_application_frame(frame, project_root="/app"):
    path = pathlib.Path(frame.filename).resolve()
    root = pathlib.Path(project_root).resolve()
    # Include frames under project root, exclude site-packages, venv, stdlib
    return root in path.parents and "site-packages" not in str(path)
```

**Key libraries**:
| Library | Purpose | Production-Ready |
|---------|---------|-----------------|
| `traceback` | Standard parsing | Yes (stdlib) |
| `stackprinter` | Pretty-print with locals | Yes |
| `better-exceptions` | Colorized output with variables | Yes |
| `tbvaccine` | Highlight app code, print locals | Yes [^369^] |
| `better-exchook` | Full stack traces with locals/globals | Yes (since 2011) [^365^] |
| `stack_data` | Data extraction (used by others) | Yes [^365^] |
| `friendly-traceback` | Beginner-friendly explanations | Educational |

---

## JavaScript Stack Trace Parsing

**Engine formats** [^350^]:

V8 (Chrome, Node.js):
```
Error: Something failed
    at functionName (file.js:42:15)
    at Object.method (file.js:100:5)
    at <anonymous> (file.js:200:3)
    at Array.forEach (<anonymous>)
```

Firefox:
```
functionName@file.js:42:15
Object.method@file.js:100:5
file.js:200:3
```

Safari:
```
functionName
    at file.js:42:15
```

**Universal parser skeleton**:
```javascript
const V8_FRAME = /^\s*at\s+(?:(.+?)\s+\()?([^)]+):(\d+):(\d+)\)?$/;
const FIREFOX_FRAME = /^(.*)@(.+):(\d+):(\d+)$/;

function parseStack(error) {
    const lines = (error.stack || "").split("\n");
    const frames = [];
    for (const line of lines) {
        let m = V8_FRAME.exec(line) || FIREFOX_FRAME.exec(line);
        if (m) {
            frames.push({
                function: m[1] || "<anonymous>",
                file: m[2],
                line: parseInt(m[3], 10),
                column: parseInt(m[4], 10),
            });
        }
    }
    return { message: error.message, frames };
}
```

**Source map resolution** [^344^][^346^]:
```javascript
const { SourceMapConsumer } = require("source-map");

async function symbolicateFrame(frame, sourceMapContent) {
    const consumer = await new SourceMapConsumer(sourceMapContent);
    const original = consumer.originalPositionFor({
        line: frame.line,
        column: frame.column,
    });
    consumer.destroy();
    return {
        file: original.source,
        line: original.line,
        column: original.column,
        function: original.name || frame.function,
    };
}
```

**Source map best practices** [^344^][^346^]:
- Do NOT ship source maps to production (4x size increase, source exposure risk)
- Upload source maps to error tracking service during CI/CD build
- Use debug IDs for unambiguous matching between minified code and source maps
- Upload as "artifact bundles" with release/dist metadata for version correlation

---

## JVM (Java/Kotlin/Scala) Stack Trace Parsing

**Standard parsing**:
```java
Throwable t = ...;
for (StackTraceElement e : t.getStackTrace()) {
    String className = e.getClassName();      // "com.example.Service"
    String method = e.getMethodName();          // "processOrder"
    String file = e.getFileName();            // "Service.java"
    int line = e.getLineNumber();             // 42
    boolean isNative = e.isNativeMethod();    // false
}
```

**ProGuard/R8 deobfuscation** [^344^]:
```bash
# Using ProGuard's retrace tool
retrace -verbose mapping.txt stacktrace.txt > symbolicated.txt

# Mapping file format:
# com.example.a.a -> com.example.Service:
#     1:1:void processOrder(java.lang.String) -> a
```

**Programmatic deobfuscation**:
```java
import proguard.retrace.ReTrace;

public List<StackTraceElement> deobfuscate(
    List<StackTraceElement> obfuscated,
    File mappingFile
) {
    // Use ReTrace API or parse mapping.txt manually
    // Line numbers preserved by default in ProGuard with -keepattributes LineNumberTable
}
```

**Key considerations**:
- Line numbers may be preserved or stripped; check `mapping.txt` for `-1` line entries
- Inner classes, lambdas, and synthetic methods complicate mapping
- Always verify deobfuscated class exists in source repository at reported version

---

## Native Code (C/C++/Rust/Go) Stack Trace Parsing

**Minidump stackwalking** [^344^]:
```cpp
// Breakpad / Crashpad minidump processing
google_breakpad::Minidump minidump(minidump_file);
minidump.Read();
google_breakpad::MinidumpThreadList* threads = minidump.GetThreadList();
for (int i = 0; i < threads->thread_count(); i++) {
    google_breakpad::MinidumpThread* thread = threads->GetThreadAtIndex(i);
    google_breakpad::MinidumpStackFrame* frame = thread->GetFrame(0);
    // Symbolicate via Symbolicator or local symbol store
}
```

**DWARF symbol resolution** (Linux):
```bash
# Using addr2line
addr2line -e binary -f -C -i 0x00012345

# Using llvm-symbolizer
llvm-symbolizer --obj=binary 0x00012345
```

**PDB symbol resolution** (Windows):
```bash
# Using cvdump or DIA SDK
# Symbol path: SRV*c:\symbols*https://msdl.microsoft.com/download/symbols
```

**Sentry Symbolicator service** [^344^]:
- Accepts minidump + debug files → returns symbolicated JSON
- Supports: native (DWARF/PDB), JavaScript (source maps), JVM (ProGuard)
- Debug IDs provide unambiguous artifact matching

---

## OpenTelemetry Trace Structure

**Canonical span attributes for code linkage** [^342^]:
```
code.function.name    - "processPayment"
code.namespace        - "com.example.billing"
code.filepath         - "src/billing/payment.rs"
code.lineno           - 142
code.column           - 8
code.stacktrace       - "..."   // Full symbolicated trace
```

**OTel data model for trace parsing** [^258^]:
```protobuf
message ResourceSpans {
  Resource resource = 1;           // service.name, service.version
  repeated ScopeSpans scope_spans = 2;
}
message ScopeSpans {
  InstrumentationScope scope = 1;  // library name/version
  repeated Span spans = 2;
}
message Span {
  bytes trace_id = 1;
  bytes span_id = 2;
  string name = 5;                 // operation name
  SpanKind kind = 6;
  Status status = 15;
  repeated Event events = 11;      // exception events with stacktrace
  repeated Link links = 12;
}
```

**Trace-to-code mapping requires**:
1. Instrumentation that captures `code.*` attributes at span creation
2. Source repository accessible at version matching trace timestamp
3. Source maps / debug info for minified/obfuscated production code

---

## Debug Artifact Requirements by Platform

| Platform | Build Artifact | Upload Target | Matching Key |
|----------|---------------|-------------|--------------|
| JS (V8) | `.js.map` | Sentry/Datadog | Debug ID [^344^] |
| JS (Vite/Webpack) | `sourcemap/*.js.map` | Error tracking | Release + dist [^360^] |
| JVM (ProGuard) | `mapping.txt` | Sentry | UUID in mapping file |
| Native (Linux) | DWARF in binary or `.debug` | Symbolicator | Build ID |
| Native (Windows) | `.pdb` | Symbol server / Symbolicator | Signature + age |
| .NET | `.pdb` | Symbol server | GUID |

**CI upload patterns**:
```bash
# Sentry — JS source maps with debug IDs
sentry-cli sourcemaps upload --release=$VERSION --dist=$BUILD dist/

# Datadog — JS source maps during build
npx @datadog/datadog-ci sourcemaps upload dist/ \
  --service=my-service --release-version=$VERSION --minified-path-prefix=https://app.example.com

# Generic — store debug artifacts with build metadata
aws s3 cp mapping.txt s3://debug-artifacts/$VERSION/mapping.txt
aws s3 cp app.debug s3://debug-artifacts/$VERSION/app.debug
```

---

## Cross-Language Frame Filtering

**Heuristics for application vs. library frame classification**:

```python
def classify_frame(frame, project_config):
    file = frame.get("file", "")
    func = frame.get("function", "")

    # Library patterns
    if any(p in file for p in project_config["library_paths"]):
        return "library"

    # Runtime / system patterns
    if file.startswith("/usr/") or file.startswith("<"):
        return "system"

    # Application patterns
    if any(p in file for p in project_config["source_paths"]):
        return "application"

    # Default based on function naming conventions
    if func.startswith("_") or func == "<anonymous>":
        return "library"

    return "unknown"
```

**Filtering strategy**:
- Retain all frames for complete traces
- Focus diagnosis on topmost application frame (crash site) and entry-point application frame (request handler)
- Mark library frames as collapsed by default in UI views
- Never discard frames during storage — filtering is a presentation concern

---

## Two-Tier Localization (T2L) Implementation Notes

**Coarse-grained detection** [^339^]:
1. Extract all application frames from crash trace
2. Map each to a code chunk (function or class body)
3. Score chunks by: frame frequency in trace, recency of modification, static analysis risk flags
4. Flag top-N chunks as suspicious

**Fine-grained localization**:
1. For each suspicious chunk, run divergence tracing: explore parallel reasoning branches from same evidence
2. Rank lines by: stack frame exact line match, static analysis vulnerability flags, git blame recency
3. Aggregate rankings across branches; output top-K candidate lines

**Research benchmark**: With Agentic Trace Analyzer (ATA) component fusing runtime evidence, baseline achieves 58.0% chunk-level detection and 54.8% exact line-level localization [^339^]. Without runtime evidence, detection drops to 0.0%.

---

**Sources**: Python traceback docs [^374^], stackprinter/better-exceptions [^365^], tbvaccine [^369^], JS stack trace formats [^350^], Sentry Symbolicator [^344^], Sentry source maps [^346^][^347^][^352^], Datadog source maps [^360^], OpenTelemetry semantic conventions [^342^], OTel tracing [^258^], T2L framework [^339^]
