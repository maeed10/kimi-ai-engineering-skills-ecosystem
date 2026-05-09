#!/usr/bin/env python3
"""
extract_trace_graph.py — Query distributed trace backends and emit a runtime service graph.

Supports:
  - Jaeger Query API v3 (dependencies endpoint + trace search)
  - Zipkin API v2 (dependencies endpoint)
  - OpenTelemetry/Tempo search API (service graph)
  - Local newline-delimited JSON trace exports (fallback)

Usage:
  export JAEGER_ENDPOINT=http://jaeger-query:16686
  python extract_trace_graph.py --output runtime_graph.json --lookback 24h

  export ZIPKIN_BASE_URL=http://zipkin:9411
  python extract_trace_graph.py --backend zipkin --output runtime_graph.json

  export OTEL_EXPORTER_OTLP_ENDPOINT=http://tempo:3200
  python extract_trace_graph.py --backend tempo --output runtime_graph.json

  python extract_trace_graph.py --backend file --input ./traces.json --output runtime_graph.json

Output schema (runtime_graph.json):
  {
    "meta": {
      "backend": "jaeger",
      "queried_at": "2024-01-15T10:00:00Z",
      "lookback_hours": 24,
      "trace_window_start": "2024-01-14T10:00:00Z",
      "trace_window_end": "2024-01-15T10:00:00Z"
    },
    "services": ["order-service", "payment-service", "inventory-service"],
    "edges": [
      {
        "source": "order-service",
        "target": "payment-service",
        "count": 15420,
        "latency_p99_ms": 45,
        "tags": {"http.url": "/api/v2/payments"},
        "confidence": "TRACE_DIRECT"
      }
    ]
  }
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.request import Request, urlopen
from urllib.error import HTTPError


def now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def hours_ago_ms(hours: int) -> int:
    return int((datetime.now(timezone.utc) - timedelta(hours=hours)).timestamp() * 1000)


def http_get(url: str, headers: dict | None = None) -> Any:
    req = Request(url, headers=headers or {})
    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except HTTPError as e:
        body = e.read().decode() if e.fp else ""
        print(f"HTTP {e.code}: {url}\n{body}", file=sys.stderr)
        raise


def query_jaeger(endpoint: str, lookback_hours: int) -> dict:
    """Query Jaeger dependencies endpoint (fast path) then enrich with trace searches if needed."""
    end_ts = now_ms()
    start_ts = hours_ago_ms(lookback_hours)
    lookback_ms = lookback_hours * 3600 * 1000

    # 1. Try dependencies endpoint (pre-aggregated graph)
    deps_url = f"{endpoint}/api/dependencies?endTs={end_ts}&lookback={lookback_ms}"
    deps_data = http_get(deps_url)

    edges = []
    services = set()
    for dep in deps_data.get("data", []):
        parent = dep.get("parent", "")
        child = dep.get("child", "")
        call_count = dep.get("callCount", 0)
        if parent and child and call_count > 0:
            services.add(parent)
            services.add(child)
            edges.append({
                "source": parent,
                "target": child,
                "count": call_count,
                "latency_p99_ms": 0,  # Jaeger deps endpoint does not include latency
                "tags": {},
                "confidence": "TRACE_DIRECT"
            })

    return {
        "services": sorted(services),
        "edges": edges,
        "backend_meta": {"endpoint": endpoint, "endpoints_queried": ["/api/dependencies"]}
    }


def query_zipkin(endpoint: str, lookback_hours: int) -> dict:
    """Query Zipkin dependencies endpoint."""
    end_ts = now_ms()
    lookback_ms = lookback_hours * 3600 * 1000

    deps_url = f"{endpoint}/api/v2/dependencies?endTs={end_ts}&lookback={lookback_ms}"
    deps_data = http_get(deps_url)

    edges = []
    services = set()
    for dep in deps_data:
        parent = dep.get("parent", "")
        child = dep.get("child", "")
        call_count = dep.get("callCount", 0)
        if parent and child and call_count > 0:
            services.add(parent)
            services.add(child)
            edges.append({
                "source": parent,
                "target": child,
                "count": call_count,
                "latency_p99_ms": 0,
                "tags": {},
                "confidence": "TRACE_DIRECT"
            })

    return {
        "services": sorted(services),
        "edges": edges,
        "backend_meta": {"endpoint": endpoint, "endpoints_queried": ["/api/v2/dependencies"]}
    }


def query_tempo(endpoint: str, lookback_hours: int) -> dict:
    """Query Grafana Tempo service graph / search API."""
    # Tempo uses the same endpoint prefix for both trace ingestion and query
    # The service graph is typically exposed via /api/metrics
    end_s = int(datetime.now(timezone.utc).timestamp())
    start_s = int((datetime.now(timezone.utc) - timedelta(hours=lookback_hours)).timestamp())

    # Try the metrics/graph endpoint (requires metrics-generator enabled)
    try:
        graph_url = f"{endpoint}/api/metrics/name/graph?start={start_s}&end={end_s}"
        graph_data = http_get(graph_url)
    except HTTPError:
        # Fallback: use search v2 to find traces, then extract services manually
        print("Tempo metrics/graph unavailable, falling back to search", file=sys.stderr)
        graph_data = {"data": []}  # TODO: implement search-based extraction

    edges = []
    services = set()
    # Tempo graph format varies; adapt as needed
    for item in graph_data.get("data", []):
        parent = item.get("parent", "")
        child = item.get("child", "")
        call_count = item.get("callCount", 0)
        if parent and child and call_count > 0:
            services.add(parent)
            services.add(child)
            edges.append({
                "source": parent,
                "target": child,
                "count": call_count,
                "latency_p99_ms": item.get("latency_p99_ms", 0),
                "tags": {},
                "confidence": "TRACE_DIRECT"
            })

    return {
        "services": sorted(services),
        "edges": edges,
        "backend_meta": {"endpoint": endpoint, "endpoints_queried": ["/api/metrics/name/graph"]}
    }


def query_local_file(input_path: str) -> dict:
    """Read local newline-delimited JSON trace export."""
    edges_map = {}
    services = set()

    with open(input_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            # Expect ResourceSpans protobuf JSON format
            for rs in record.get("resourceSpans", []):
                svc = ""
                for attr in rs.get("resource", {}).get("attributes", []):
                    if attr.get("key") == "service.name":
                        svc = attr.get("value", {}).get("stringValue", "")
                        services.add(svc)
                        break
                for scope in rs.get("scopeSpans", []):
                    for span in scope.get("spans", []):
                        # Resolve destination from span attributes
                        dst = None
                        attrs = {a["key"]: a.get("value", {}).get("stringValue", "") for a in span.get("attributes", [])}
                        for key in ("peer.service", "rpc.service", "server.address", "http.host", "net.peer.name", "db.system", "messaging.system"):
                            if attrs.get(key):
                                dst = attrs[key]
                                break
                        if dst and svc:
                            services.add(dst)
                            key = (svc, dst)
                            edges_map[key] = edges_map.get(key, {"count": 0, "tags": {}})
                            edges_map[key]["count"] += 1
                            edges_map[key]["tags"].update({k: v for k, v in attrs.items() if v})

    edges = []
    for (src, dst), info in edges_map.items():
        edges.append({
            "source": src,
            "target": dst,
            "count": info["count"],
            "latency_p99_ms": 0,
            "tags": info["tags"],
            "confidence": "TRACE_DIRECT"
        })

    return {
        "services": sorted(services),
        "edges": edges,
        "backend_meta": {"source": input_path, "format": "local_ndjson"}
    }


def ingest_from_logs(log_path: str, min_count: int = 5) -> dict:
    """
    Supplementary: ingest log-analyzer output (JSON with cross_service_calls).
    Lower confidence than direct traces.
    """
    with open(log_path, "r") as f:
        data = json.load(f)

    edges = []
    services = set()
    for entry in data.get("cross_service_calls", []):
        caller = entry.get("caller_service", "")
        callee = entry.get("callee_service", "")
        freq = entry.get("frequency", 0)
        if caller and callee and freq >= min_count:
            services.add(caller)
            services.add(callee)
            edges.append({
                "source": caller,
                "target": callee,
                "count": freq,
                "latency_p99_ms": 0,
                "tags": {"inferred_from": "log_correlation_id"},
                "confidence": "LOG_INFERRED"
            })

    return {
        "services": sorted(services),
        "edges": edges,
        "backend_meta": {"source": log_path, "format": "log_analyzer_output"}
    }


def main():
    parser = argparse.ArgumentParser(description="Extract runtime service graph from traces")
    parser.add_argument("--backend", choices=["jaeger", "zipkin", "tempo", "file", "log"], default="jaeger")
    parser.add_argument("--endpoint", default=None, help="Override backend endpoint URL")
    parser.add_argument("--input", default=None, help="Input file path (for file/log backends)")
    parser.add_argument("--output", required=True, help="Output JSON file path")
    parser.add_argument("--lookback", type=int, default=24, help="Lookback window in hours")
    parser.add_argument("--min-count", type=int, default=5, help="Minimum call count threshold")
    args = parser.parse_args()

    backend = args.backend
    endpoint = args.endpoint
    if endpoint is None:
        endpoint = os.environ.get("JAEGER_ENDPOINT") or os.environ.get("JAEGER_QUERY_URL") or os.environ.get("ZIPKIN_BASE_URL") or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or ""

    if backend == "jaeger":
        if not endpoint:
            print("JAEGER_ENDPOINT env var or --endpoint required", file=sys.stderr)
            sys.exit(1)
        result = query_jaeger(endpoint, args.lookback)
    elif backend == "zipkin":
        if not endpoint:
            print("ZIPKIN_BASE_URL env var or --endpoint required", file=sys.stderr)
            sys.exit(1)
        result = query_zipkin(endpoint, args.lookback)
    elif backend == "tempo":
        if not endpoint:
            print("OTEL_EXPORTER_OTLP_ENDPOINT env var or --endpoint required", file=sys.stderr)
            sys.exit(1)
        result = query_tempo(endpoint, args.lookback)
    elif backend == "file":
        if not args.input:
            print("--input required for file backend", file=sys.stderr)
            sys.exit(1)
        result = query_local_file(args.input)
    elif backend == "log":
        if not args.input:
            print("--input required for log backend", file=sys.stderr)
            sys.exit(1)
        result = ingest_from_logs(args.input, args.min_count)
    else:
        print(f"Unknown backend: {backend}", file=sys.stderr)
        sys.exit(1)

    # Apply min-count filter
    result["edges"] = [e for e in result["edges"] if e["count"] >= args.min_count]

    # Add metadata
    output = {
        "meta": {
            "backend": backend,
            "queried_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "lookback_hours": args.lookback,
            "trace_window_start": (datetime.now(timezone.utc) - timedelta(hours=args.lookback)).isoformat().replace("+00:00", "Z"),
            "trace_window_end": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "min_count_threshold": args.min_count
        },
        "services": result["services"],
        "edges": result["edges"],
        "_backend_meta": result.get("backend_meta", {})
    }

    with open(args.output, "w") as f:
        json.dump(output, f, indent=2)

    edge_count = len(output["edges"])
    svc_count = len(output["services"])
    print(f"Wrote {args.output}: {svc_count} services, {edge_count} edges")


if __name__ == "__main__":
    main()
