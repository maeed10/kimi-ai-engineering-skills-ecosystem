#!/usr/bin/env python3
"""
profile_app.py — Automated performance profiler, flame graph generator, and recommendation reporter.

Detects project type, runs language-appropriate CPU/memory profilers, converts results to flame graphs,
and produces ranked optimization recommendations.

Usage:
    python profile_app.py --cpu --duration 30 --output-dir ./profiling
    python profile_app.py --memory --output-dir ./profiling
    python profile_app.py --flamegraph cpu.prof --output flamegraph.svg
    python profile_app.py --recommend --profile-dir ./profiling
    python profile_app.py --compare before.json after.json --threshold 10
"""

import argparse
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

PROFILE_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# Project Detection
# ---------------------------------------------------------------------------

def detect_project_type(root: Path = Path(".")) -> str:
    """Detect primary language/runtime from filesystem markers."""
    markers = {
        "python": ["requirements.txt", "pyproject.toml", "setup.py", "Pipfile", "poetry.lock"],
        "go": ["go.mod"],
        "node": ["package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml"],
        "java": ["pom.xml", "build.gradle", "build.gradle.kts"],
        "rust": ["Cargo.toml"],
    }
    counts = {k: 0 for k in markers}
    for f in root.rglob("*"):
        if f.is_file():
            for lang, names in markers.items():
                if f.name in names:
                    counts[lang] += 1
    if not any(counts.values()):
        # heuristic by extension
        exts = {".py": "python", ".go": "go", ".js": "node", ".ts": "node", ".java": "java", ".rs": "rust"}
        for f in root.rglob("*"):
            if f.is_file() and f.suffix in exts:
                counts[exts[f.suffix]] += 1
    return max(counts, key=counts.get) if any(counts.values()) else "unknown"

# ---------------------------------------------------------------------------
# CPU Profiling
# ---------------------------------------------------------------------------

def run_cpu_profile(lang: str, duration: int, output_dir: Path, pid: Optional[int] = None) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    if lang == "python":
        return _run_python_cpu(duration, output_dir, pid)
    elif lang == "go":
        return _run_go_cpu(duration, output_dir, pid)
    elif lang == "node":
        return _run_node_cpu(duration, output_dir, pid)
    elif lang == "java":
        return _run_java_cpu(duration, output_dir, pid)
    elif lang == "rust":
        return _run_rust_cpu(duration, output_dir, pid)
    else:
        return _run_generic_perf(duration, output_dir, pid)

def _which(cmd: str) -> bool:
    return subprocess.run(["which", cmd], capture_output=True).returncode == 0

def _run_python_cpu(duration: int, output_dir: Path, pid: Optional[int]) -> Path:
    out = output_dir / "cpu.prof"
    if pid and _which("py-spy"):
        subprocess.run(["py-spy", "record", "-o", str(out), "-d", str(duration), "--pid", str(pid)], check=False)
    elif _which("python"):
        # fallback to cProfile via script injection
        print("[python] Using cProfile (py-spy not installed). Run your workload separately with:")
        print(f"   python -m cProfile -o {out} your_script.py")
    else:
        print("[python] python not found in PATH")
    return out

def _run_go_cpu(duration: int, output_dir: Path, pid: Optional[int]) -> Path:
    out = output_dir / "cpu.prof"
    if pid:
        url = f"http://localhost:6060/debug/pprof/profile?seconds={duration}"
        try:
            subprocess.run(["curl", "-s", "-o", str(out), url], check=True, timeout=duration + 10)
        except Exception as e:
            print(f"[go] Failed to fetch pprof: {e}")
    else:
        print("[go] Please run app with _ \"net/http/pprof\" imported and expose port 6060")
        print(f"   curl -o {out} http://localhost:6060/debug/pprof/profile?seconds={duration}")
    return out

def _run_node_cpu(duration: int, output_dir: Path, pid: Optional[int]) -> Path:
    out = output_dir / "cpu.cpuprofile"
    if _which("0x"):
        print("[node] 0x installed. Use: 0x -o flamegraph.html -- node app.js")
    if pid and _which("node"):
        # Generate via inspector protocol (simplified)
        print(f"[node] Attach Chrome DevTools to PID {pid} or use --inspect and take CPU profile manually.")
    else:
        print("[node] Use: node --inspect app.js  →  Chrome DevTools → Performance")
    return out

def _run_java_cpu(duration: int, output_dir: Path, pid: Optional[int]) -> Path:
    out = output_dir / "cpu.jfr"
    if pid and _which("jcmd"):
        subprocess.run(
            ["jcmd", str(pid), "JFR.start", f"duration={duration}s", "filename=" + str(out)],
            check=False,
        )
    elif _which("async-profiler"):
        print(f"[java] Using async-profiler: ./profiler.sh -d {duration} -f {out} <PID>")
    else:
        print("[java] Install async-profiler or use: jcmd <PID> JFR.start ...")
    return out

def _run_rust_cpu(duration: int, output_dir: Path, pid: Optional[int]) -> Path:
    out = output_dir / "perf.data"
    if _which("perf"):
        target = ["-p", str(pid)] if pid else ["-a"]
        subprocess.run(["perf", "record", "-F", "99", "-g"] + target + ["--", "sleep", str(duration)], check=False)
        if Path("perf.data").exists():
            Path("perf.data").rename(out)
    else:
        print("[rust] perf not found. Install linux-tools or use cargo-flamegraph.")
    return out

def _run_generic_perf(duration: int, output_dir: Path, pid: Optional[int]) -> Path:
    out = output_dir / "perf.data"
    if _which("perf"):
        target = ["-p", str(pid)] if pid else ["-a"]
        subprocess.run(["perf", "record", "-F", "99", "-g"] + target + ["--", "sleep", str(duration)], check=False)
        if Path("perf.data").exists():
            Path("perf.data").rename(out)
    return out

# ---------------------------------------------------------------------------
# Memory Profiling
# ---------------------------------------------------------------------------

def run_memory_profile(lang: str, output_dir: Path, pid: Optional[int] = None) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    if lang == "python":
        return _run_python_memory(output_dir, pid)
    elif lang == "go":
        return _run_go_memory(output_dir, pid)
    elif lang == "node":
        return _run_node_memory(output_dir, pid)
    elif lang == "java":
        return _run_java_memory(output_dir, pid)
    else:
        print(f"[{lang}] No built-in memory profiler script. See references/profiling_tools.md.")
        return output_dir / "memory.log"

def _run_python_memory(output_dir: Path, pid: Optional[int]) -> Path:
    out = output_dir / "memory.log"
    if pid and _which("py-spy"):
        subprocess.run(["py-spy", "top", "--pid", str(pid)], check=False)
    elif _which("python"):
        print("[python] Use tracemalloc or memory_profiler in your script. See references/profiling_tools.md.")
    return out

def _run_go_memory(output_dir: Path, pid: Optional[int]) -> Path:
    out = output_dir / "heap.prof"
    if pid:
        url = "http://localhost:6060/debug/pprof/heap"
        try:
            subprocess.run(["curl", "-s", "-o", str(out), url], check=False)
        except Exception:
            pass
    else:
        print("[go] Run app with pprof exposed, then: curl -o heap.prof http://localhost:6060/debug/pprof/heap")
    return out

def _run_node_memory(output_dir: Path, pid: Optional[int]) -> Path:
    out = output_dir / "heapsnapshot.heapsnapshot"
    print("[node] Generate heap snapshot via DevTools or --inspect and save to", out)
    return out

def _run_java_memory(output_dir: Path, pid: Optional[int]) -> Path:
    out = output_dir / "heap.hprof"
    if pid and _which("jcmd"):
        subprocess.run(["jcmd", str(pid), "GC.heap_dump", "filename=" + str(out)], check=False)
    else:
        print("[java] jcmd not found. Install JDK or use async-profiler heap profiling.")
    return out

# ---------------------------------------------------------------------------
# Flame Graph Generation
# ---------------------------------------------------------------------------

def generate_flamegraph(input_path: Path, output_path: Path) -> bool:
    """Attempt to generate an SVG flame graph from supported profile formats."""
    flamegraph_dir = os.environ.get("FLAMEGRAPH_DIR", "/opt/FlameGraph")
    if not Path(flamegraph_dir).exists():
        # try to auto-clone
        clone_dir = Path(tempfile.gettempdir()) / "FlameGraph"
        if not clone_dir.exists():
            subprocess.run(
                ["git", "clone", "--depth", "1", "https://github.com/brendangregg/FlameGraph.git", str(clone_dir)],
                capture_output=True,
            )
        if clone_dir.exists():
            flamegraph_dir = str(clone_dir)
    if not Path(flamegraph_dir).exists():
        print("[flamegraph] FlameGraph tools not found and could not be cloned.")
        return False

    collapsed = input_path.with_suffix(".collapsed")
    success = False

    if input_path.suffix in {".prof", ".pb.gz"} or "pprof" in input_path.name:
        # Go / generic pprof
        if _which("go"):
            subprocess.run(["go", "tool", "pprof", "-raw", "-output=" + str(collapsed), str(input_path)], check=False)
            success = _flamegraph_from_collapsed(collapsed, output_path, flamegraph_dir)
    elif input_path.suffix == ".data" or input_path.name == "perf.data":
        # perf
        subprocess.run(
            f"perf script -i {input_path} | {flamegraph_dir}/stackcollapse-perf.pl > {collapsed}",
            shell=True, check=False,
        )
        success = _flamegraph_from_collapsed(collapsed, output_path, flamegraph_dir)
    elif input_path.suffix in {".svg", ".html"}:
        print(f"[flamegraph] Input already looks like a flame graph: {input_path}")
        success = True
    else:
        print(f"[flamegraph] Unsupported input format: {input_path.suffix}. Use pprof, perf.data, or py-spy SVG output.")

    return success

def _flamegraph_from_collapsed(collapsed: Path, output: Path, fg_dir: str) -> bool:
    if not collapsed.exists() or collapsed.stat().st_size == 0:
        return False
    cmd = [f"{fg_dir}/flamegraph.pl", str(collapsed)]
    with open(output, "w") as f:
        r = subprocess.run(cmd, stdout=f)
    return r.returncode == 0 and output.exists()

# ---------------------------------------------------------------------------
# Recommendation Engine
# ---------------------------------------------------------------------------

def generate_recommendations(profile_dir: Path, lang: str) -> str:
    """Read profile artifacts and produce a Markdown recommendation report."""
    report_lines: List[str] = [
        "# Performance Optimization Recommendations",
        "",
        f"- **Profile dir**: `{profile_dir}`",
        f"- **Detected language**: `{lang}`",
        f"- **Version**: `{PROFILE_VERSION}`",
        "",
    ]

    # Try to parse top CPU hotspots from available files
    hotspots = _extract_hotspots(profile_dir, lang)
    if hotspots:
        report_lines.append("## CPU Hotspots")
        report_lines.append("")
        for i, (func, metric, pct) in enumerate(hotspots[:5], 1):
            report_lines.append(f"{i}. `{func}` — {metric} ({pct})")
        report_lines.append("")

    # Generic recommendations based on language
    recs = _language_recommendations(lang)
    report_lines.append("## Ranked Recommendations")
    report_lines.append("")
    for idx, rec in enumerate(recs, 1):
        report_lines.append(f"### {idx}. {rec['title']}")
        report_lines.append(f"- **Finding**: {rec['finding']}")
        report_lines.append(f"- **Impact**: {rec['impact']} | **Effort**: {rec['effort']} | **Risk**: {rec['risk']}")
        report_lines.append(f"- **Action**: {rec['action']}")
        report_lines.append(f"- **Expected Gain**: {rec['gain']}")
        report_lines.append("")

    # Append DB / I/O section if we can find any logs
    if any(profile_dir.glob("*.sql")) or any(profile_dir.glob("*trace*")):
        report_lines.append("## I/O & Database Notes")
        report_lines.append("- Review slow query logs and add composite indexes for top 3 queries.")
        report_lines.append("- Check for N+1 query patterns in ORM logs.")
        report_lines.append("")

    report = "\n".join(report_lines)
    out_file = profile_dir / "recommendations.md"
    out_file.write_text(report)
    return str(out_file)

def _extract_hotspots(profile_dir: Path, lang: str) -> List[Tuple[str, str, str]]:
    hotspots: List[Tuple[str, str, str]] = []
    # Python cProfile stats
    stats_file = profile_dir / "cpu.prof"
    if stats_file.exists() and lang == "python":
        try:
            import pstats
            s = pstats.Stats(str(stats_file))
            s.sort_stats("cumulative")
            for func, (cc, nc, tt, ct, callers) in s.stats.items():
                if len(hotspots) >= 10:
                    break
                name = f"{func[0]}:{func[1]}({func[2]})"
                hotspots.append((name, f"cumtime={ct:.3f}s", f"tottime={tt:.3f}s"))
        except Exception:
            pass
    # Go pprof text
    pprof_txt = profile_dir / "cpu.txt"
    if pprof_txt.exists():
        text = pprof_txt.read_text()
        for line in text.splitlines()[:10]:
            m = re.search(r'(\S+)\s+([\d.]+)\s+s\s+([\d.]+)%', line)
            if m:
                hotspots.append((m.group(1), f"{m.group(2)}s", f"{m.group(3)}%"))
    # perf report stub
    perf_data = profile_dir / "perf.data"
    if perf_data.exists() and not hotspots:
        hotspots.append(("See perf report", "run: perf report -i " + str(perf_data), ""))
    return hotspots

def _language_recommendations(lang: str) -> List[Dict[str, str]]:
    common = [
        {
            "title": "Add connection pooling",
            "finding": "New connections per request add latency and memory overhead",
            "impact": "High", "effort": "Small", "risk": "Low",
            "action": "Configure DB driver pool size (e.g., SQLAlchemy pool_size=20, pgxpool MaxConns=25).",
            "gain": "20–50% latency reduction under load; fewer connection spikes",
        },
        {
            "title": "Cache repeated reference lookups",
            "finding": "Hot paths re-fetch static or slowly changing data",
            "impact": "High", "effort": "Small", "risk": "Low",
            "action": "Add LRU cache (TTL 5 min) or Redis for top 5 most-queried reference datasets.",
            "gain": "30–60% reduction in DB read load and p95 latency",
        },
        {
            "title": "Batch inserts and updates",
            "finding": "Loop-based single-row writes dominate write path",
            "impact": "High", "effort": "Small", "risk": "Low",
            "action": "Replace N single INSERTs with executemany / COPY / bulk API.",
            "gain": "5–20× throughput increase for ingestion workloads",
        },
    ]
    if lang == "python":
        specific = [
            {
                "title": "Replace sync I/O with async drivers",
                "finding": "Thread pool saturation under concurrent load",
                "impact": "Medium", "effort": "Medium", "risk": "Medium",
                "action": "Use asyncpg / aiohttp / httpx async; limit event loop blocking calls.",
                "gain": "2–4× concurrency increase without process/thread explosion",
            },
            {
                "title": "Use generators for large data pipelines",
                "finding": "Large intermediate lists allocated in memory-heavy paths",
                "impact": "Medium", "effort": "Small", "risk": "Low",
                "action": "Refactor list comprehensions to generator expressions; use `yield` in producers.",
                "gain": "50–90% memory reduction for streaming workloads",
            },
        ]
    elif lang == "go":
        specific = [
            {
                "title": "Reuse buffers with sync.Pool",
                "finding": "High allocation rate in hot network/serialization paths",
                "impact": "Medium", "effort": "Small", "risk": "Medium",
                "action": "Pool byte slices or structs with `sync.Pool`; reset state before Put.",
                "gain": "30–50% reduction in allocations and GC CPU",
            },
            {
                "title": "Tune GOGC / GOMEMLIMIT",
                "finding": "GC pacing too aggressive or memory headroom unused",
                "impact": "Medium", "effort": "Small", "risk": "Medium",
                "action": "Set GOMEMLIMIT to ~80% of container memory limit; adjust GOGC if latency spikes.",
                "gain": "10–30% throughput improvement for allocation-heavy services",
            },
        ]
    elif lang == "node":
        specific = [
            {
                "title": "Offload CPU work to worker_threads",
                "finding": "Event loop blocking from crypto, JSON parse, or computation",
                "impact": "High", "effort": "Medium", "risk": "Medium",
                "action": "Move heavy sync tasks to worker_threads or external queue jobs.",
                "gain": "Eliminates event loop lag; p99 latency drops significantly",
            },
            {
                "title": "Add Redis caching for repeated DB reads",
                "finding": "MongoDB / Postgres queried for identical keys repeatedly",
                "impact": "High", "effort": "Small", "risk": "Low",
                "action": "Wrap hot read functions with LRU or ioredis GET/SETEX.",
                "gain": "40–70% latency reduction for read-heavy APIs",
            },
        ]
    elif lang == "java":
        specific = [
            {
                "title": "Enable G1GC with pause targets",
                "finding": "Long STW pauses from default Parallel GC or heap pressure",
                "impact": "High", "effort": "Small", "risk": "Medium",
                "action": "Add `-XX:+UseG1GC -XX:MaxGCPauseMillis=200 -XX:+UseStringDeduplication`.",
                "gain": "Predictable sub-200ms pauses instead of multi-second STW",
            },
            {
                "title": "Reduce lock contention with finer-grained locks",
                "finding": "JFR Lock events show high contention on single monitor",
                "impact": "Medium", "effort": "Medium", "risk": "High",
                "action": "Shard state by tenant/hash; replace synchronized with ConcurrentHashMap / StampedLock.",
                "gain": "2–5× throughput increase on highly concurrent writes",
            },
        ]
    elif lang == "rust":
        specific = [
            {
                "title": "Use arena / bump allocation for short-lived objects",
                "finding": "Allocator churn in tight loops (e.g., parsing, serialization)",
                "impact": "Medium", "effort": "Medium", "risk": "Medium",
                "action": "Integrate `bumpalo` or `typed-arena` for per-request scratch space.",
                "gain": "20–40% faster allocation-heavy paths; fewer global allocator calls",
            },
        ]
    else:
        specific = []

    return common + specific

# ---------------------------------------------------------------------------
# Benchmark Comparison
# ---------------------------------------------------------------------------

def compare_benchmarks(before_path: Path, after_path: Path, threshold_pct: float) -> Dict:
    before = _load_benchmark(before_path)
    after = _load_benchmark(after_path)
    results: List[Dict] = []
    all_keys = set(before.keys()) | set(after.keys())

    for key in sorted(all_keys):
        b = before.get(key, [])
        a = after.get(key, [])
        if not b or not a:
            continue
        b_median = _median(b)
        a_median = _median(a)
        change_pct = ((a_median - b_median) / b_median) * 100 if b_median else 0.0
        significant = abs(change_pct) >= threshold_pct
        results.append({
            "metric": key,
            "before_median": b_median,
            "after_median": a_median,
            "change_pct": round(change_pct, 2),
            "significant": significant,
            "regression": change_pct > threshold_pct,
            "improvement": change_pct < -threshold_pct,
        })

    regressions = [r for r in results if r["regression"]]
    report = {
        "threshold_pct": threshold_pct,
        "metrics_compared": len(results),
        "regressions": len(regressions),
        "details": results,
        "pass": len(regressions) == 0,
    }
    return report

def _load_benchmark(path: Path) -> Dict[str, List[float]]:
    data = json.loads(path.read_text())
    # Support { "latency_ms": [1.2, 1.5, ...], "memory_mb": [...] }
    if isinstance(data, dict):
        return {k: [float(v) for v in vals] for k, vals in data.items() if isinstance(vals, list)}
    return {}

def _median(values: List[float]) -> float:
    s = sorted(values)
    n = len(s)
    if n == 0:
        return 0.0
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2.0

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Profile app performance and generate recommendations")
    parser.add_argument("--detect", action="store_true", help="Detect project language and exit")
    parser.add_argument("--cpu", action="store_true", help="Run CPU profiler")
    parser.add_argument("--memory", action="store_true", help="Run memory profiler")
    parser.add_argument("--duration", type=int, default=30, help="Profiling duration in seconds")
    parser.add_argument("--pid", type=int, default=None, help="Target process PID")
    parser.add_argument("--output-dir", type=Path, default=Path("./profiling"), help="Directory for profile artifacts")
    parser.add_argument("--flamegraph", type=Path, default=None, help="Input profile file to convert to flame graph")
    parser.add_argument("--flamegraph-output", type=Path, default=Path("flamegraph.svg"), help="Output flame graph path")
    parser.add_argument("--recommend", action="store_true", help="Generate recommendation report from existing profiles")
    parser.add_argument("--compare", nargs=2, type=Path, metavar=("BEFORE", "AFTER"), help="Compare two benchmark JSON files")
    parser.add_argument("--threshold", type=float, default=10.0, help="Regression threshold percent")
    parser.add_argument("--json", action="store_true", help="Output comparison/recommendations as JSON")
    args = parser.parse_args()

    lang = detect_project_type()

    if args.detect:
        print(json.dumps({"language": lang}) if args.json else lang)
        return 0

    if args.flamegraph:
        ok = generate_flamegraph(args.flamegraph, args.flamegraph_output)
        print(f"Flame graph: {'generated' if ok else 'failed'} -> {args.flamegraph_output}")
        return 0 if ok else 1

    if args.cpu:
        print(f"[profile_app] Detected language: {lang}")
        out = run_cpu_profile(lang, args.duration, args.output_dir, args.pid)
        print(f"[profile_app] CPU profile artifact: {out}")

    if args.memory:
        print(f"[profile_app] Detected language: {lang}")
        out = run_memory_profile(lang, args.output_dir, args.pid)
        print(f"[profile_app] Memory profile artifact: {out}")

    if args.recommend:
        report_path = generate_recommendations(args.output_dir, lang)
        print(f"[profile_app] Recommendations written to: {report_path}")
        if args.json:
            # simple JSON wrapping
            content = Path(report_path).read_text()
            print(json.dumps({"report_path": str(report_path), "markdown": content}))

    if args.compare:
        before, after = args.compare
        report = compare_benchmarks(before, after, args.threshold)
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print(f"Benchmark Comparison (threshold={args.threshold}%)")
            print(f"Metrics: {report['metrics_compared']} | Regressions: {report['regressions']} | Pass: {report['pass']}")
            for d in report["details"]:
                status = "REGRESSION" if d["regression"] else ("IMPROVEMENT" if d["improvement"] else "stable")
                print(f"  {d['metric']}: {d['before_median']:.3f} -> {d['after_median']:.3f} ({d['change_pct']:+.1f}%) [{status}]")
        return 0 if report["pass"] else 1

    return 0

if __name__ == "__main__":
    sys.exit(main())
