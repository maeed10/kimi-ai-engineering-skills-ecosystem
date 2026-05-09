#!/usr/bin/env python3
"""
analyze_error.py

Parse stack traces and logs to extract structured error context.
Supports Python, JavaScript/Node, Java, Go, Rust stack traces,
plus structured (JSON) and unstructured log files.

Usage:
    python analyze_error.py --stack-trace stack.txt
    python analyze_error.py --logs app.log --since "2024-01-01T00:00:00"
    cat error.txt | python analyze_error.py --stdin
    python analyze_error.py --text "TypeError: Cannot read..."

Output:
    JSON with extracted error signatures, frames, log entries, and hypotheses.
"""

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def _regex(pattern: str, flags: int = 0) -> re.Pattern:
    return re.compile(pattern, flags)


# ---------------------------------------------------------------------------
# Stack Trace Parsers
# ---------------------------------------------------------------------------

PYTHON_FRAME_RE = _regex(
    r'^  File "([^"]+)", line (\d+), in (.+)\n    (.+)$',
    re.MULTILINE,
)
PYTHON_EXCEPTION_RE = _regex(
    r'^([\w.]+(?:Error|Exception|Warning|Panic|Exit)):\s*(.*?)$',
    re.MULTILINE,
)
PYTHON_CAUSED_RE = _regex(r'(?:Caused by|During handling)[^\n]*\n', re.IGNORECASE)

JS_FRAME_RE = _regex(
    r'^\s+at\s+(?:(.+?)\s+\()?(.+?):(\d+):(\d+)\)?$',
    re.MULTILINE,
)
JS_EXCEPTION_RE = _regex(
    r'^([\w]+(?:Error|Exception|TypeError|ReferenceError|RangeError|SyntaxError)):\s*(.*?)$',
    re.MULTILINE,
)

JAVA_FRAME_RE = _regex(
    r'^\s+at\s+([\w.$<>]+)\(([^:]+)?:(\d+)?\)$',
    re.MULTILINE,
)
JAVA_EXCEPTION_RE = _regex(
    r'^([\w.]+(?:Exception|Error|Throwable)):\s*(.*?)$',
    re.MULTILINE,
)

GO_FRAME_RE = _regex(
    r'^(\S+)\((0x[0-9a-f]+)\)\n\s+(.+?):(\d+)\s+\+0x[0-9a-f]+$',
    re.MULTILINE,
)
GO_EXCEPTION_RE = _regex(
    r'^panic:\s*(.*?)$',
    re.MULTILINE,
)

RUST_FRAME_RE = _regex(
    r'^\s+\d+:\s+(.+?)\s+at\s+(.+?):(\d+):(\d+)$',
    re.MULTILINE,
)
RUST_PANIC_RE = _regex(
    r'^thread\s+\'[^\']+\'\s+panicked\s+at\s+[\']?(.*?)[\']?,\s+(.*?):(\d+):(\d+)$',
    re.MULTILINE,
)


def _looks_like_python(text: str) -> bool:
    return 'Traceback (most recent call last)' in text or 'File "' in text


def _looks_like_js(text: str) -> bool:
    return 'Error: ' in text and ('at ' in text and (':' in text and '/' in text))


def _looks_like_java(text: str) -> bool:
    return 'Exception:' in text or 'Error:' in text and 'at ' in text and '.java' in text


def _looks_like_go(text: str) -> bool:
    return 'goroutine ' in text or ('panic:' in text and 'main.' in text)


def _looks_like_rust(text: str) -> bool:
    return 'panicked at' in text or ('stack backtrace:' in text and 'RUST_BACKTRACE' not in text)


def detect_language(text: str) -> str:
    if _looks_like_python(text):
        return 'python'
    if _looks_like_go(text):
        return 'go'
    if _looks_like_java(text):
        return 'java'
    if _looks_like_rust(text):
        return 'rust'
    if _looks_like_js(text):
        return 'javascript'
    return 'unknown'


def parse_python_trace(text: str) -> dict[str, Any]:
    frames = []
    for m in PYTHON_FRAME_RE.finditer(text):
        file_path, line_no, func_name, code = m.groups()
        is_user = not any(
            file_path.startswith(p)
            for p in ('/usr/lib', '/usr/local/lib', 'site-packages', 'lib/python', 'venv/', '.venv/', 'virtualenv')
        ) and '/lib/' not in file_path
        frames.append(
            {
                'file': file_path,
                'line': int(line_no),
                'function': func_name,
                'code': code,
                'is_user_code': is_user,
            }
        )

    exceptions = []
    for m in PYTHON_EXCEPTION_RE.finditer(text):
        exceptions.append({'type': m.group(1), 'message': m.group(2).strip()})

    return {
        'language': 'python',
        'frames': frames,
        'exceptions': exceptions,
        'caused_by_count': len(PYTHON_CAUSED_RE.findall(text)),
        'user_frames': [f for f in frames if f['is_user_code']],
        'library_frames': [f for f in frames if not f['is_user_code']],
    }


def parse_js_trace(text: str) -> dict[str, Any]:
    frames = []
    for m in JS_FRAME_RE.finditer(text):
        func_name, file_path, line_no, col_no = m.groups()
        is_user = not any(
            p in (file_path or '')
            for p in ('node_modules', '/usr/lib', 'webpack', 'vendor', '<anonymous>')
        )
        frames.append(
            {
                'function': func_name or '<anonymous>',
                'file': file_path,
                'line': int(line_no) if line_no else None,
                'column': int(col_no) if col_no else None,
                'is_user_code': is_user,
            }
        )

    exceptions = []
    for m in JS_EXCEPTION_RE.finditer(text):
        exceptions.append({'type': m.group(1), 'message': m.group(2).strip()})

    return {
        'language': 'javascript',
        'frames': frames,
        'exceptions': exceptions,
        'user_frames': [f for f in frames if f['is_user_code']],
        'library_frames': [f for f in frames if not f['is_user_code']],
    }


def parse_java_trace(text: str) -> dict[str, Any]:
    frames = []
    for m in JAVA_FRAME_RE.finditer(text):
        func_name, file_path, line_no = m.groups()
        is_user = file_path and not any(
            p in file_path for p in ('java.base', 'jdk.internal', 'springframework', 'apache', 'com.google')
        )
        frames.append(
            {
                'function': func_name,
                'file': file_path,
                'line': int(line_no) if line_no else None,
                'is_user_code': bool(is_user and file_path),
            }
        )

    exceptions = []
    for m in JAVA_EXCEPTION_RE.finditer(text):
        exceptions.append({'type': m.group(1), 'message': m.group(2).strip()})

    return {
        'language': 'java',
        'frames': frames,
        'exceptions': exceptions,
        'user_frames': [f for f in frames if f['is_user_code']],
        'library_frames': [f for f in frames if not f['is_user_code']],
    }


def parse_go_trace(text: str) -> dict[str, Any]:
    frames = []
    for m in GO_FRAME_RE.finditer(text):
        func_name, _, file_path, line_no = m.groups()
        is_user = not func_name.startswith(('runtime.', 'sync.', 'net/http.', 'database/sql.', 'fmt.'))
        frames.append(
            {
                'function': func_name,
                'file': file_path,
                'line': int(line_no),
                'is_user_code': is_user,
            }
        )

    exceptions = []
    for m in GO_EXCEPTION_RE.finditer(text):
        exceptions.append({'type': 'panic', 'message': m.group(1).strip()})

    return {
        'language': 'go',
        'frames': frames,
        'exceptions': exceptions,
        'user_frames': [f for f in frames if f['is_user_code']],
        'library_frames': [f for f in frames if not f['is_user_code']],
    }


def parse_rust_trace(text: str) -> dict[str, Any]:
    frames = []
    for m in RUST_FRAME_RE.finditer(text):
        func_name, file_path, line_no, col_no = m.groups()
        is_user = not any(
            p in file_path for p in ('/rustc/', 'core::', 'std::', 'alloc::')
        )
        frames.append(
            {
                'function': func_name,
                'file': file_path,
                'line': int(line_no),
                'column': int(col_no),
                'is_user_code': is_user,
            }
        )

    exceptions = []
    for m in RUST_PANIC_RE.finditer(text):
        exceptions.append(
            {
                'type': 'panic',
                'message': m.group(1).strip(),
                'file': m.group(2),
                'line': int(m.group(3)),
                'column': int(m.group(4)),
            }
        )

    return {
        'language': 'rust',
        'frames': frames,
        'exceptions': exceptions,
        'user_frames': [f for f in frames if f['is_user_code']],
        'library_frames': [f for f in frames if not f['is_user_code']],
    }


def parse_stack_trace(text: str) -> dict[str, Any]:
    text = text.strip()
    if not text:
        return {'language': 'unknown', 'frames': [], 'exceptions': []}

    lang = detect_language(text)
    if lang == 'python':
        return parse_python_trace(text)
    if lang == 'javascript':
        return parse_js_trace(text)
    if lang == 'java':
        return parse_java_trace(text)
    if lang == 'go':
        return parse_go_trace(text)
    if lang == 'rust':
        return parse_rust_trace(text)

    return {'language': 'unknown', 'frames': [], 'exceptions': []}


# ---------------------------------------------------------------------------
# Log Parsers
# ---------------------------------------------------------------------------

LOG_LEVELS = ['FATAL', 'ERROR', 'WARN', 'WARNING', 'INFO', 'DEBUG', 'TRACE', 'PANIC']
UNSTRUCTURED_TIMESTAMP_RE = _regex(
    r'^(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)'
)
UNSTRUCTURED_LEVEL_RE = _regex(
    r'\b(' + '|'.join(LOG_LEVELS) + r')\b',
    re.IGNORECASE,
)


def parse_json_log_line(line: str) -> dict[str, Any] | None:
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return None

    if not isinstance(obj, dict):
        return None

    timestamp = None
    for key in ('timestamp', 'ts', 'time', '@timestamp'):
        if key in obj:
            timestamp = obj[key]
            break

    level = None
    for key in ('level', 'severity', 'loglevel', 'lvl'):
        if key in obj:
            level = str(obj[key]).upper()
            break

    message = None
    for key in ('message', 'msg', 'log', 'text', 'error'):
        if key in obj:
            message = obj[key]
            break

    service = obj.get('service') or obj.get('service_name') or obj.get('app')
    trace_id = obj.get('trace_id') or obj.get('traceId') or obj.get('trace.id')
    span_id = obj.get('span_id') or obj.get('spanId')

    return {
        'type': 'json',
        'timestamp': timestamp,
        'level': level,
        'message': str(message) if message is not None else None,
        'service': service,
        'trace_id': trace_id,
        'span_id': span_id,
        'raw': obj,
    }


def parse_unstructured_log_line(line: str) -> dict[str, Any]:
    ts_match = UNSTRUCTURED_TIMESTAMP_RE.search(line)
    level_match = UNSTRUCTURED_LEVEL_RE.search(line)

    return {
        'type': 'unstructured',
        'timestamp': ts_match.group(1) if ts_match else None,
        'level': level_match.group(1).upper() if level_match else None,
        'message': line.strip(),
        'service': None,
        'trace_id': None,
        'span_id': None,
    }


def parse_logs(text: str, since: str | None = None, until: str | None = None) -> list[dict[str, Any]]:
    lines = text.splitlines()
    entries = []
    cutoff_since = _parse_iso(since) if since else None
    cutoff_until = _parse_iso(until) if until else None

    for line in lines:
        line = line.strip()
        if not line:
            continue
        entry = parse_json_log_line(line)
        if entry is None:
            entry = parse_unstructured_log_line(line)

        ts = _parse_iso(entry.get('timestamp')) if entry.get('timestamp') else None
        if cutoff_since and ts and ts < cutoff_since:
            continue
        if cutoff_until and ts and ts > cutoff_until:
            continue

        entries.append(entry)

    return entries


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    value = str(value)
    formats = [
        '%Y-%m-%dT%H:%M:%S.%fZ',
        '%Y-%m-%dT%H:%M:%SZ',
        '%Y-%m-%dT%H:%M:%S.%f%z',
        '%Y-%m-%dT%H:%M:%S%z',
        '%Y-%m-%d %H:%M:%S.%f',
        '%Y-%m-%d %H:%M:%S',
        '%Y-%m-%d',
    ]
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    # Try unix timestamp
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    except (ValueError, OSError, OverflowError):
        pass
    return None


# ---------------------------------------------------------------------------
# Analysis & Hypotheses
# ---------------------------------------------------------------------------

ERROR_SIGNATURES = {
    'python': {
        r"NoneType.*has no attribute": {
            'category': 'null-safety',
            'hypothesis': 'A function returned None unexpectedly. Check upstream for missing validation or API response parsing.',
        },
        r"KeyError: '([^']+)'": {
            'category': 'data-structure',
            'hypothesis': 'Dictionary/DataFrame missing expected key. Validate schema or use .get() with default.',
        },
        r"IndexError: .*index out of range": {
            'category': 'bounds-check',
            'hypothesis': 'List/collection shorter than expected. Add length check before indexing.',
        },
        r"ModuleNotFoundError": {
            'category': 'dependency',
            'hypothesis': 'Missing package, wrong virtualenv, or local file shadowing a standard module name.',
        },
        r"RecursionError": {
            'category': 'algorithm',
            'hypothesis': 'Missing base case or infinite recursion in __getattr__/__getattribute__. Convert to iteration.',
        },
    },
    'javascript': {
        r"Cannot read propert[^']*'([^']+)'": {
            'category': 'null-safety',
            'hypothesis': 'Accessing property on undefined/null. Add optional chaining or loading guard.',
        },
        r"is not a function": {
            'category': 'type-mismatch',
            'hypothesis': 'Variable is not what caller expected. Check import name, prototype, or CommonJS/ESM interop.',
        },
        r"UnhandledPromiseRejection": {
            'category': 'async',
            'hypothesis': 'Promise rejected without .catch() or try/catch. Add error handling to async path.',
        },
        r"is not defined": {
            'category': 'scope',
            'hypothesis': 'Variable used before declaration, misspelled, or missing import/polyfill.',
        },
    },
    'java': {
        r"NullPointerException": {
            'category': 'null-safety',
            'hypothesis': 'Unvalidated null passed to method or autounboxed. Use Objects.requireNonNull or Optional.',
        },
        r"ClassNotFoundException|NoClassDefFoundError": {
            'category': 'dependency',
            'hypothesis': 'Missing JAR or classpath issue. Check dependency tree, shading, or packaging.',
        },
        r"ConcurrentModificationException": {
            'category': 'concurrency',
            'hypothesis': 'Collection modified while iterating or from another thread. Use concurrent collections or synchronize.',
        },
    },
    'go': {
        r"nil pointer dereference": {
            'category': 'null-safety',
            'hypothesis': 'Called method on nil struct or accessed field of nil pointer. Add nil guard in constructor/usage.',
        },
    },
    'rust': {
        r"unwrap\(\).*None": {
            'category': 'null-safety',
            'hypothesis': 'Option::unwrap() called on None. Use ? operator, match, or ok_or_else with context.',
        },
        r"unwrap\(\).*Err": {
            'category': 'error-handling',
            'hypothesis': 'Result::unwrap() on Err value. Propagate with ? or handle error explicitly.',
        },
    },
}


def generate_hypotheses(trace_result: dict[str, Any], log_entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    hypotheses = []
    lang = trace_result.get('language', 'unknown')
    exceptions = trace_result.get('exceptions', [])
    messages = [e.get('message', '') for e in exceptions] + [e.get('message', '') for e in log_entries if e.get('level') in ('ERROR', 'FATAL', 'PANIC')]

    signatures = ERROR_SIGNATURES.get(lang, {})
    seen_categories = set()

    for pattern, info in signatures.items():
        for msg in messages:
            if re.search(pattern, msg, re.IGNORECASE):
                if info['category'] not in seen_categories:
                    seen_categories.add(info['category'])
                    hypotheses.append(
                        {
                            'category': info['category'],
                            'confidence': 'high',
                            'hypothesis': info['hypothesis'],
                            'matched_pattern': pattern,
                        }
                    )
                break

    # Add structural hypotheses based on frame analysis
    user_frames = trace_result.get('user_frames', [])
    if user_frames:
        top_user = user_frames[0]
        hypotheses.append(
            {
                'category': 'location',
                'confidence': 'medium',
                'hypothesis': f"Error originates in user code at {top_user.get('file')}:{top_user.get('line')} in `{top_user.get('function')}`. Inspect recent changes to this function.",
            }
        )

    if trace_result.get('caused_by_count', 0) > 0:
        hypotheses.append(
            {
                'category': 'wrapped-exception',
                'confidence': 'medium',
                'hypothesis': f"Exception chain has {trace_result['caused_by_count']} 'caused by' wrapper(s). The root cause is likely deeper in the chain, not the outermost exception.",
            }
        )

    # Log-derived hypotheses
    services = {e['service'] for e in log_entries if e.get('service')}
    if len(services) > 1:
        hypotheses.append(
            {
                'category': 'distributed',
                'confidence': 'medium',
                'hypothesis': f"Errors span multiple services ({', '.join(services)}). Correlate by trace_id to find the first failing service in the cascade.",
            }
        )

    error_counts = {}
    for e in log_entries:
        if e.get('level') in ('ERROR', 'FATAL', 'PANIC'):
            sig = _extract_signature(e.get('message', ''))
            error_counts[sig] = error_counts.get(sig, 0) + 1

    if error_counts:
        most_common = max(error_counts, key=error_counts.get)
        if error_counts[most_common] > 1:
            hypotheses.append(
                {
                    'category': 'frequency',
                    'confidence': 'medium',
                    'hypothesis': f"Most frequent error signature appears {error_counts[most_common]} times: '{most_common[:120]}...'. Focus on this pattern first.",
                }
            )

    if not hypotheses:
        hypotheses.append(
            {
                'category': 'unknown',
                'confidence': 'low',
                'hypothesis': 'No known pattern matched. Apply backward tracing from stack trace and inspect variable state at failure site.',
            }
        )

    return hypotheses


def _extract_signature(message: str) -> str:
    # Normalize variable parts to create a rough signature
    sig = re.sub(r'0x[0-9a-f]+', '<addr>', message)
    sig = re.sub(r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}\S*', '<ts>', sig)
    sig = re.sub(r'\d+\.\d+\.\d+\.\d+(:\d+)?', '<ip>', sig)
    sig = re.sub(r'\d+', '<n>', sig)
    return sig[:200]


# ---------------------------------------------------------------------------
# Breakpoint Suggestions
# ---------------------------------------------------------------------------

def suggest_breakpoints(trace_result: dict[str, Any]) -> list[dict[str, Any]]:
    suggestions = []
    user_frames = trace_result.get('user_frames', [])

    if not user_frames:
        return suggestions

    # Top user frame: just before the crash
    top = user_frames[0]
    suggestions.append(
        {
            'reason': 'error-site',
            'location': f"{top['file']}:{top['line']}",
            'note': 'Inspect variable state immediately before the failing line.',
        }
    )

    # Entry frame: where user code is first called
    if len(user_frames) > 1:
        entry = user_frames[-1]
        suggestions.append(
            {
                'reason': 'data-entry',
                'location': f"{entry['file']}:{entry['line']}",
                'note': 'Check input parameters entering the failing call chain.',
            }
        )

    # If exception type suggests state corruption, suggest intermediate mutation points
    exceptions = trace_result.get('exceptions', [])
    if any('NoneType' in str(e.get('message', '')) for e in exceptions):
        if len(user_frames) > 2:
            mid = user_frames[len(user_frames) // 2]
            suggestions.append(
                {
                    'reason': 'state-mutation',
                    'location': f"{mid['file']}:{mid['line']}",
                    'note': 'Trace where the None value originated in the intermediate frames.',
                }
            )

    return suggestions


# ---------------------------------------------------------------------------
# CLI / Main
# ---------------------------------------------------------------------------

def build_report(stack_text: str | None, log_text: str | None, since: str | None, until: str | None) -> dict[str, Any]:
    report: dict[str, Any] = {
        'analysis_timestamp': datetime.now(timezone.utc).isoformat(),
        'stack_trace': None,
        'logs': None,
        'hypotheses': [],
        'breakpoints': [],
    }

    if stack_text:
        trace = parse_stack_trace(stack_text)
        report['stack_trace'] = trace

    log_entries = []
    if log_text:
        log_entries = parse_logs(log_text, since=since, until=until)
        report['logs'] = {
            'total_lines': len(log_text.splitlines()),
            'parsed_entries': len(log_entries),
            'error_count': sum(1 for e in log_entries if e.get('level') in ('ERROR', 'FATAL', 'PANIC')),
            'services': sorted({e['service'] for e in log_entries if e.get('service')}) or None,
            'trace_ids': sorted({e['trace_id'] for e in log_entries if e.get('trace_id')}) or None,
            'entries': log_entries[:500],  # limit output
        }

    report['hypotheses'] = generate_hypotheses(report.get('stack_trace') or {}, log_entries)

    if stack_text:
        report['breakpoints'] = suggest_breakpoints(report['stack_trace'])

    return report


def main() -> int:
    parser = argparse.ArgumentParser(description='Parse stack traces and logs to extract error context.')
    parser.add_argument('--stack-trace', '-s', type=Path, help='File containing a stack trace')
    parser.add_argument('--logs', '-l', type=Path, help='Log file (JSON or unstructured)')
    parser.add_argument('--since', help='ISO timestamp filter for logs (inclusive)')
    parser.add_argument('--until', help='ISO timestamp filter for logs (inclusive)')
    parser.add_argument('--text', '-t', help='Raw stack trace text string')
    parser.add_argument('--stdin', action='store_true', help='Read stack trace from stdin')
    parser.add_argument('--output', '-o', type=Path, help='Write JSON output to file (default: stdout)')
    parser.add_argument('--pretty', action='store_true', default=True, help='Pretty-print JSON')

    args = parser.parse_args()

    stack_text = None
    log_text = None

    if args.text:
        stack_text = args.text
    elif args.stdin:
        stdin_data = sys.stdin.read()
        if not args.logs:
            # If no --logs, assume stdin is a stack trace unless it looks like logs
            stack_text = stdin_data
    elif args.stack_trace:
        stack_text = args.stack_trace.read_text(encoding='utf-8', errors='replace')

    if args.logs:
        log_text = args.logs.read_text(encoding='utf-8', errors='replace')
    elif args.stdin and not stack_text:
        log_text = stdin_data

    report = build_report(stack_text, log_text, args.since, args.until)

    json_output = json.dumps(report, indent=2 if args.pretty else None, default=str)

    if args.output:
        args.output.write_text(json_output, encoding='utf-8')
        print(f'Report written to {args.output}', file=sys.stderr)
    else:
        print(json_output)

    return 0


if __name__ == '__main__':
    sys.exit(main())
