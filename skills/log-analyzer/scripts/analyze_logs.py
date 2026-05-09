#!/usr/bin/env python3
"""analyze_logs.py — Parse logs, identify error patterns, correlate with code.

Ingests error logs and stack traces, traces failures back to code locations.
"""

import argparse
import json
import re
import sys
from pathlib import Path
from collections import Counter


def main():
    parser = argparse.ArgumentParser(description="Log Analyzer")
    parser.add_argument("--log", required=True, help="Log file path")
    parser.add_argument("--source-dir", default=".", help="Source code directory for correlation")
    parser.add_argument("--output", default="log_analysis.json")
    args = parser.parse_args()

    log_text = Path(args.log).read_text(encoding="utf-8", errors="replace")
    lines = log_text.splitlines()

    errors = []
    for i, line in enumerate(lines):
        if _is_error_line(line):
            errors.append({
                "line_number": i + 1,
                "timestamp": _extract_timestamp(line),
                "level": _extract_level(line),
                "message": line.strip(),
                "stack_trace": _extract_stack_trace(lines, i),
            })

    patterns = Counter(e["message"][:80] for e in errors)
    correlated = _correlate_with_source(errors, Path(args.source_dir))

    report = {
        "log_file": args.log,
        "total_lines": len(lines),
        "errors_found": len(errors),
        "top_patterns": [{"pattern": p, "count": c} for p, c in patterns.most_common(10)],
        "errors": correlated[:50],  # Limit detail
    }

    Path(args.output).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Analyzed {report['total_lines']} lines, found {report['errors_found']} errors.")
    if report["top_patterns"]:
        print(f"Top pattern: {report['top_patterns'][0]['pattern']} ({report['top_patterns'][0]['count']}x)")
    return 0


def _is_error_line(line):
    return bool(re.search(r"\b(ERROR|CRITICAL|FATAL|Exception|Traceback)\b", line))


def _extract_timestamp(line):
    m = re.search(r"(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})", line)
    return m.group(1) if m else ""


def _extract_level(line):
    m = re.search(r"\b(DEBUG|INFO|WARNING|ERROR|CRITICAL)\b", line)
    return m.group(1) if m else "UNKNOWN"


def _extract_stack_trace(lines, start_idx):
    trace = []
    for j in range(start_idx + 1, min(start_idx + 20, len(lines))):
        if lines[j].startswith("  File ") or "Traceback" in lines[j]:
            trace.append(lines[j].strip())
        elif lines[j].strip() and not lines[j].startswith(" "):
            break
    return trace


def _correlate_with_source(errors, source_dir):
    for err in errors:
        # Look for file:line references in the error or stack trace
        refs = re.findall(r"File \"([^\"]+)\", line (\d+)", "\n".join(err["stack_trace"]))
        if not refs:
            m = re.search(r"(\S+\.py):(\d+)", err["message"])
            if m:
                refs = [(m.group(1), m.group(2))]
        err["code_references"] = refs
    return errors


if __name__ == "__main__":
    sys.exit(main())
