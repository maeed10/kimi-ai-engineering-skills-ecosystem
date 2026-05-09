#!/usr/bin/env python3
"""
setup_observability.py

Generates complete observability stack configuration from a service inventory YAML.

Usage:
    python setup_observability.py --inventory services.yaml --output ./observability/

Outputs:
    - prometheus_rules.yaml           # Recording + alerting rules
    - grafana_dashboards/              # One JSON dashboard per service
    - otel_collector_config.yaml       # OTel Collector pipeline config
    - alertmanager_routes.yaml         # Routing snippet for Alertmanager
    - servicemonitors.yaml             # Kubernetes ServiceMonitor manifests
    - loki_promtail_config.yaml        # Promtail scrape config snippets
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    print("PyYAML is required. Install: pip install pyyaml")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

def render_prometheus_recording_rules(services: list[dict]) -> str:
    """Generate Prometheus recording rules for RED metrics per service."""
    groups = [
        {
            "name": "service_red_recording",
            "interval": "15s",
            "rules": [],
        }
    ]

    for svc in services:
        name = svc["name"]
        labels = svc.get("labels", {})
        label_selectors = ",".join(
            [f'{k}="{v}"' for k, v in labels.items()]
        )
        selector = f"{{{label_selectors}}}" if label_selectors else ""

        groups[0]["rules"].extend(
            [
                {
                    "record": f"service:{name}:requests_rate5m",
                    "expr": f"sum(rate(http_requests_total{selector}[5m]))",
                },
                {
                    "record": f"service:{name}:error_rate5m",
                    "expr": f"sum(rate(http_requests_total{{status=~\"5..\"{',' + label_selectors if label_selectors else ''}}}[5m]))",
                },
                {
                    "record": f"service:{name}:error_ratio5m",
                    "expr": f"service:{name}:error_rate5m / service:{name}:requests_rate5m",
                },
                {
                    "record": f"service:{name}:latency_p99_5m",
                    "expr": f"histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket{selector}[5m])) by (le))",
                },
                {
                    "record": f"service:{name}:latency_p95_5m",
                    "expr": f"histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{selector}[5m])) by (le))",
                },
                {
                    "record": f"service:{name}:latency_p50_5m",
                    "expr": f"histogram_quantile(0.50, sum(rate(http_request_duration_seconds_bucket{selector}[5m])) by (le))",
                },
            ]
        )

    return yaml.dump({"groups": groups}, sort_keys=False)


def render_slo_recording_rules(services: list[dict]) -> str:
    """Generate SLO burn-rate recording rules for each service with an SLO."""
    groups = [{"name": "slo_burn_rate_recording", "interval": "30s", "rules": []}]

    for svc in services:
        slo = svc.get("slo")
        if not slo:
            continue
        name = svc["name"]
        labels = svc.get("labels", {})
        label_selectors = ",".join(
            [f'{k}="{v}"' for k, v in labels.items()]
        )
        selector = f"{{{label_selectors}}}" if label_selectors else ""
        budget = 1 - slo["target"]

        windows = [
            ("5m", "5m"),
            ("30m", "30m"),
            ("1h", "1h"),
            ("6h", "6h"),
            ("3d", "3d"),
        ]
        for label, window in windows:
            groups[0]["rules"].append(
                {
                    "record": f"service:{name}:error_ratio_{label}",
                    "expr": (
                        f"sum(rate(http_requests_total{{status=~\"5..\"{',' + label_selectors if label_selectors else ''}}}[{window}])) "
                        f"/ sum(rate(http_requests_total{selector}[{window}]))"
                    ),
                }
            )

        # budget remaining
        groups[0]["rules"].append(
            {
                "record": f"service:{name}:error_budget_remaining_30d",
                "expr": (
                    f"({budget} - (sum(increase(http_requests_total{{status=~\"5..\"{',' + label_selectors if label_selectors else ''}}}[30d])) "
                    f"/ sum(increase(http_requests_total{selector}[30d])))) / {budget}"
                ),
            }
        )

    return yaml.dump({"groups": groups}, sort_keys=False)


def render_alerting_rules(services: list[dict]) -> str:
    """Generate alerting rules including burn-rate and standard alerts."""
    groups = []

    # Standard RED alerts
    red_group = {"name": "service_red_alerts", "rules": []}
    for svc in services:
        name = svc["name"]
        labels = svc.get("labels", {})
        label_selectors = ",".join(
            [f'{k}="{v}"' for k, v in labels.items()]
        )
        selector = f"{{{label_selectors}}}" if label_selectors else ""

        red_group["rules"].append(
            {
                "alert": f"{name.title().replace('-', '')}HighErrorRate",
                "expr": f"service:{name}:error_ratio5m > 0.01",
                "for": "2m",
                "labels": {"severity": "critical", "service": name},
                "annotations": {
                    "summary": f"High error rate on {name}",
                    "description": f"Error rate is {{{{ $value | humanizePercentage }}}} over the last 5m",
                    "runbook_url": f"https://wiki.internal/runbooks/{name}/high-error-rate",
                },
            }
        )

        latency_threshold = svc.get("latency_threshold_seconds", 0.5)
        red_group["rules"].append(
            {
                "alert": f"{name.title().replace('-', '')}HighLatencyP99",
                "expr": f"service:{name}:latency_p99_5m > {latency_threshold}",
                "for": "5m",
                "labels": {"severity": "warning", "service": name},
                "annotations": {
                    "summary": f"P99 latency > {latency_threshold}s for {name}",
                    "description": "Current P99: {{ $value }}s",
                },
            }
        )

    groups.append(red_group)

    # Burn-rate alerts
    burn_group = {"name": "slo_burn_rate_alerts", "rules": []}
    for svc in services:
        slo = svc.get("slo")
        if not slo:
            continue
        name = svc["name"]
        target = slo["target"]
        budget = round(1 - target, 6)

        # 14.4x fast burn (page)
        burn_group["rules"].append(
            {
                "alert": f"{name.title().replace('-', '')}ErrorBudgetBurn14x",
                "expr": (
                    f"(service:{name}:error_ratio_1h > ({14.4 * budget})) "
                    f"and (service:{name}:error_ratio_5m > ({14.4 * budget}))"
                ),
                "for": "2m",
                "labels": {"severity": "critical", "service": name, "slo": str(target)},
                "annotations": {
                    "summary": f"High error budget burn rate on {name}",
                    "description": f"1h error rate exceeds 14.4x burn for {target} SLO",
                    "runbook_url": f"https://wiki.internal/runbooks/{name}/error-budget-burn",
                },
            }
        )

        # 6x burn (page)
        burn_group["rules"].append(
            {
                "alert": f"{name.title().replace('-', '')}ErrorBudgetBurn6x",
                "expr": (
                    f"(service:{name}:error_ratio_6h > ({6 * budget})) "
                    f"and (service:{name}:error_ratio_30m > ({6 * budget}))"
                ),
                "for": "5m",
                "labels": {"severity": "critical", "service": name, "slo": str(target)},
                "annotations": {
                    "summary": f"Moderate error budget burn on {name}",
                    "description": f"6h error rate exceeds 6x burn for {target} SLO",
                },
            }
        )

        # 2x burn (ticket)
        burn_group["rules"].append(
            {
                "alert": f"{name.title().replace('-', '')}ErrorBudgetBurn2x",
                "expr": (
                    f"(service:{name}:error_ratio_3d > ({2 * budget})) "
                    f"and (service:{name}:error_ratio_6h > ({2 * budget}))"
                ),
                "for": "10m",
                "labels": {"severity": "warning", "service": name, "slo": str(target)},
                "annotations": {
                    "summary": f"Slow error budget burn on {name}",
                    "description": f"3d error rate exceeds 2x burn for {target} SLO. Investigate within 3 days.",
                },
            }
        )

    groups.append(burn_group)
    return yaml.dump({"groups": groups}, sort_keys=False)


def render_grafana_dashboard(svc: dict) -> dict:
    """Generate a Grafana 10+ RED/SLO dashboard JSON for a single service."""
    name = svc["name"]
    labels = svc.get("labels", {})
    label_selectors = ",".join([f'{k}="{v}"' for k, v in labels.items()])
    selector = f"{{{label_selectors}}}" if label_selectors else ""

    slo = svc.get("slo")
    latency_threshold = svc.get("latency_threshold_seconds", 0.5)

    panels = []

    # Row: Summary
    panels.append(
        _row_panel("Summary", len(panels) * 2)
    )

    panels.append(
        _timeseries_panel(
            title="Request Rate",
            expr=f"sum(rate(http_requests_total{selector}[5m]))",
            legend="RPS",
            unit="reqps",
            grid_y=1,
            grid_x=0,
        )
    )
    panels.append(
        _timeseries_panel(
            title="Error Rate",
            expr=f"sum(rate(http_requests_total{{status=~\"5..\"{',' + label_selectors if label_selectors else ''}}}[5m])) / sum(rate(http_requests_total{selector}[5m]))",
            legend="Error %",
            unit="percentunit",
            grid_y=1,
            grid_x=8,
        )
    )
    panels.append(
        _timeseries_panel(
            title="Latency",
            exprs=[
                f"histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket{selector}[5m])) by (le))",
                f"histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{selector}[5m])) by (le))",
                f"histogram_quantile(0.50, sum(rate(http_request_duration_seconds_bucket{selector}[5m])) by (le))",
            ],
            legends=["p99", "p95", "p50"],
            unit="s",
            grid_y=1,
            grid_x=16,
        )
    )

    # Row: SLO (if defined)
    if slo:
        target = slo["target"]
        budget = round(1 - target, 6)
        panels.append(_row_panel("SLO / Error Budget", 9))

        panels.append(
            _stat_panel(
                title="30d SLI (Availability)",
                expr=f"1 - (sum(increase(http_requests_total{{status=~\"5..\"{',' + label_selectors if label_selectors else ''}}}[30d])) / sum(increase(http_requests_total{selector}[30d])))",
                unit="percentunit",
                thresholds=[
                    {"color": "red", "value": None},
                    {"color": "yellow", "value": target - 0.002},
                    {"color": "green", "value": target},
                ],
                grid_y=10,
                grid_x=0,
            )
        )
        panels.append(
            _stat_panel(
                title="Error Budget Remaining",
                expr=f"({budget} - (sum(increase(http_requests_total{{status=~\"5..\"{',' + label_selectors if label_selectors else ''}}}[30d])) / sum(increase(http_requests_total{selector}[30d])))) / {budget}",
                unit="percentunit",
                thresholds=[
                    {"color": "red", "value": None},
                    {"color": "orange", "value": 0},
                    {"color": "yellow", "value": 0.25},
                    {"color": "green", "value": 0.5},
                ],
                grid_y=10,
                grid_x=8,
            )
        )
        panels.append(
            _gauge_panel(
                title="1h Burn Rate",
                expr=f"(sum(rate(http_requests_total{{status=~\"5..\"{',' + label_selectors if label_selectors else ''}}}[1h])) / sum(rate(http_requests_total{selector}[1h]))) / {budget}",
                unit="short",
                max_val=20,
                thresholds=[
                    {"color": "green", "value": None},
                    {"color": "yellow", "value": 2},
                    {"color": "orange", "value": 6},
                    {"color": "red", "value": 14.4},
                ],
                grid_y=10,
                grid_x=16,
            )
        )

    # Row: Infrastructure
    panels.append(_row_panel("Infrastructure", 18 if slo else 9))
    y = 19 if slo else 10
    panels.append(
        _timeseries_panel(
            title="CPU Usage",
            expr=f"rate(container_cpu_usage_seconds_total{{pod=~\"{name}-.*\"}}[5m])",
            legend="{{pod}}",
            unit="percentunit",
            grid_y=y,
            grid_x=0,
        )
    )
    panels.append(
        _timeseries_panel(
            title="Memory Usage",
            expr=f"container_memory_working_set_bytes{{pod=~\"{name}-.*\"}}",
            legend="{{pod}}",
            unit="bytes",
            grid_y=y,
            grid_x=8,
        )
    )
    panels.append(
        _timeseries_panel(
            title="Pod Restarts",
            expr=f"increase(kube_pod_container_status_restarts_total{{pod=~\"{name}-.*\"}}[1h])",
            legend="{{pod}}",
            unit="short",
            grid_y=y,
            grid_x=16,
        )
    )

    dashboard = {
        "annotations": {"list": []},
        "editable": True,
        "fiscalYearStartMonth": 0,
        "graphTooltip": 1,
        "links": [],
        "liveNow": False,
        "panels": panels,
        "refresh": "30s",
        "schemaVersion": 38,
        "style": "dark",
        "tags": ["red", "slo", name],
        "templating": {
            "list": [
                {
                    "current": {
                        "selected": False,
                        "text": "Prometheus",
                        "value": "Prometheus",
                    },
                    "hide": 0,
                    "includeAll": False,
                    "label": "Prometheus",
                    "multi": False,
                    "name": "datasource",
                    "options": [],
                    "query": "prometheus",
                    "refresh": 1,
                    "regex": "",
                    "skipUrlSync": False,
                    "type": "datasource",
                }
            ]
        },
        "time": {"from": "now-1h", "to": "now"},
        "timezone": "browser",
        "title": f"{name} — RED / SLO",
        "uid": f"red-slo-{name}",
        "version": 1,
    }

    return dashboard


def render_otel_collector_config(services: list[dict]) -> str:
    """Generate OpenTelemetry Collector configuration."""
    config = {
        "receivers": {
            "otlp": {
                "protocols": {
                    "grpc": {"endpoint": "0.0.0.0:4317"},
                    "http": {"endpoint": "0.0.0.0:4318"},
                }
            },
            "prometheus": {
                "config": {
                    "scrape_configs": [
                        {
                            "job_name": "otel-collector",
                            "static_configs": [
                                {"targets": ["0.0.0.0:8888"]}
                            ],
                        }
                    ]
                }
            },
        },
        "processors": {
            "batch": {"timeout": "1s", "send_batch_size": 1024},
            "memory_limiter": {
                "limit_mib": 512,
                "spike_limit_mib": 128,
                "check_interval": "5s",
            },
            "resource": {
                "attributes": [
                    {"key": "cluster", "value": "prod", "action": "upsert"},
                    {"key": "environment", "value": "production", "action": "upsert"},
                ]
            },
            "tail_sampling": {
                "decision_wait": "10s",
                "num_traces": 100000,
                "expected_new_traces_per_sec": 1000,
                "policies": [
                    {
                        "name": "errors",
                        "type": "status_code",
                        "status_code": {"status_codes": ["ERROR"]},
                    },
                    {
                        "name": "slow",
                        "type": "latency",
                        "latency": {"threshold_ms": 1000},
                    },
                    {
                        "name": "probabilistic",
                        "type": "probabilistic",
                        "probabilistic": {"sampling_percentage": 5},
                    },
                ],
            },
        },
        "exporters": {
            "prometheusremotewrite": {
                "endpoint": "http://prometheus:9090/api/v1/write"
            },
            "otlp/jaeger": {
                "endpoint": "jaeger-collector:4317",
                "tls": {"insecure": True},
            },
            "loki": {
                "endpoint": "http://loki:3100/loki/api/v1/push",
                "labels": {
                    "attributes": {
                        "service.name": "service",
                        "severity": "level",
                    }
                },
            },
        },
        "extensions": {
            "health_check": {"endpoint": "0.0.0.0:13133"},
            "pprof": {"endpoint": "0.0.0.0:1777"},
            "zpages": {"endpoint": "0.0.0.0:55679"},
        },
        "service": {
            "extensions": ["health_check", "pprof", "zpages"],
            "pipelines": {
                "metrics": {
                    "receivers": ["otlp", "prometheus"],
                    "processors": ["memory_limiter", "resource", "batch"],
                    "exporters": ["prometheusremotewrite"],
                },
                "traces": {
                    "receivers": ["otlp"],
                    "processors": [
                        "memory_limiter",
                        "resource",
                        "tail_sampling",
                        "batch",
                    ],
                    "exporters": ["otlp/jaeger"],
                },
                "logs": {
                    "receivers": ["otlp"],
                    "processors": ["memory_limiter", "resource", "batch"],
                    "exporters": ["loki"],
                },
            },
        },
    }
    return yaml.dump(config, sort_keys=False)


def render_alertmanager_routes(services: list[dict]) -> str:
    """Generate Alertmanager route snippet for the services."""
    routes = []
    for svc in services:
        name = svc["name"]
        team = svc.get("team", "sre")
        routes.append(
            {
                "match": {"service": name, "severity": "critical"},
                "receiver": f"pagerduty-{team}",
                "continue": True,
                "group_wait": "10s",
                "repeat_interval": "4h",
            }
        )
        routes.append(
            {
                "match": {"service": name, "severity": "warning"},
                "receiver": f"slack-{team}",
                "continue": True,
            }
        )

    config = {
        "route": {
            "receiver": "default",
            "group_by": ["alertname", "cluster", "service", "severity"],
            "group_wait": "30s",
            "group_interval": "5m",
            "repeat_interval": "12h",
            "routes": routes,
        },
        "receivers": [
            {"name": "default"},
        ],
    }

    # Add unique receiver definitions
    teams = {svc.get("team", "sre") for svc in services}
    for team in teams:
        config["receivers"].append({"name": f"pagerduty-{team}"})
        config["receivers"].append({"name": f"slack-{team}"})

    return yaml.dump(config, sort_keys=False)


def render_servicemonitors(services: list[dict]) -> str:
    """Generate Kubernetes ServiceMonitor manifests."""
    monitors = []
    for svc in services:
        name = svc["name"]
        namespace = svc.get("namespace", "default")
        port = svc.get("metrics_port", "metrics")
        path = svc.get("metrics_path", "/metrics")
        monitors.append(
            {
                "apiVersion": "monitoring.coreos.com/v1",
                "kind": "ServiceMonitor",
                "metadata": {
                    "name": name,
                    "namespace": "monitoring",
                },
                "spec": {
                    "namespaceSelector": {
                        "matchNames": [namespace]
                    },
                    "selector": {
                        "matchLabels": {"app": name}
                    },
                    "endpoints": [
                        {
                            "port": port,
                            "path": path,
                            "interval": "15s",
                            "scrapeTimeout": "10s",
                            "honorLabels": False,
                            "metricRelabelings": [
                                {
                                    "sourceLabels": ["__name__"],
                                    "regex": "go_memstats_.*",
                                    "action": "drop",
                                },
                                {
                                    "regex": "trace_id|span_id|request_id",
                                    "action": "labeldrop",
                                },
                            ],
                        }
                    ],
                },
            }
        )

    return "\n---\n".join([yaml.dump(m, sort_keys=False) for m in monitors])


def render_loki_promtail(services: list[dict]) -> str:
    """Generate Promtail scrape_config snippets for application logs."""
    scrape_configs = []
    for svc in services:
        name = svc["name"]
        log_path = svc.get("log_path", f"/var/log/{name}/*.json.log")
        scrape_configs.append(
            {
                "job_name": name,
                "static_configs": [
                    {
                        "targets": ["localhost"],
                        "labels": {
                            "job": name,
                            "service": name,
                            "environment": "production",
                            "__path__": log_path,
                        },
                    }
                ],
                "pipeline_stages": [
                    {"json": {"expressions": {
                        "timestamp": "timestamp",
                        "level": "level",
                        "message": "message",
                        "trace_id": "trace_id",
                    }}},
                    {
                        "timestamp": {
                            "source": "timestamp",
                            "format": "RFC3339",
                        }
                    },
                    {"labels": {"level": None, "trace_id": None}},
                    {"output": {"source": "message"}},
                ],
            }
        )

    config = {"scrape_configs": scrape_configs}
    return yaml.dump(config, sort_keys=False)


# ---------------------------------------------------------------------------
# Panel Helpers
# ---------------------------------------------------------------------------

def _row_panel(title: str, grid_y: int) -> dict:
    return {
        "collapsed": False,
        "gridPos": {"h": 1, "w": 24, "x": 0, "y": grid_y},
        "id": hash(title + str(grid_y)) % 100000,
        "title": title,
        "type": "row",
    }


def _timeseries_panel(
    title: str,
    expr: str | None = None,
    exprs: list[str] | None = None,
    legend: str | None = None,
    legends: list[str] | None = None,
    unit: str = "short",
    grid_y: int = 0,
    grid_x: int = 0,
) -> dict:
    targets = []
    expressions = exprs if exprs else ([expr] if expr else [])
    legend_labels = legends if legends else ([legend] if legend else [""])
    for i, e in enumerate(expressions):
        targets.append(
            {
                "expr": e,
                "legendFormat": legend_labels[i] if i < len(legend_labels) else "",
                "refId": chr(ord("A") + i),
            }
        )

    return {
        "datasource": {"type": "prometheus", "uid": "${datasource}"},
        "fieldConfig": {
            "defaults": {
                "custom": {
                    "drawStyle": "line",
                    "lineInterpolation": "linear",
                    "pointSize": 5,
                    "showPoints": "never",
                },
                "unit": unit,
                "min": 0,
            },
            "overrides": [],
        },
        "gridPos": {"h": 8, "w": 8, "x": grid_x, "y": grid_y},
        "id": hash(title + str(grid_y) + str(grid_x)) % 100000,
        "options": {
            "tooltip": {"mode": "multi"},
            "legend": {
                "displayMode": "table",
                "placement": "right",
                "calcs": ["mean", "max"],
            },
        },
        "pluginVersion": "10.0.0",
        "targets": targets,
        "title": title,
        "type": "timeseries",
    }


def _stat_panel(
    title: str,
    expr: str,
    unit: str,
    thresholds: list[dict],
    grid_y: int,
    grid_x: int,
) -> dict:
    return {
        "datasource": {"type": "prometheus", "uid": "${datasource}"},
        "fieldConfig": {
            "defaults": {
                "unit": unit,
                "min": -0.5,
                "max": 1,
                "thresholds": {"mode": "absolute", "steps": thresholds},
            },
            "overrides": [],
        },
        "gridPos": {"h": 8, "w": 8, "x": grid_x, "y": grid_y},
        "id": hash(title + str(grid_y) + str(grid_x)) % 100000,
        "options": {
            "colorMode": "background",
            "graphMode": "area",
            "justifyMode": "auto",
            "orientation": "auto",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "showPercentChange": False,
            "textMode": "auto",
            "wideLayout": True,
        },
        "pluginVersion": "10.0.0",
        "targets": [
            {
                "expr": expr,
                "legendFormat": title,
                "refId": "A",
            }
        ],
        "title": title,
        "type": "stat",
    }


def _gauge_panel(
    title: str,
    expr: str,
    unit: str,
    max_val: float,
    thresholds: list[dict],
    grid_y: int,
    grid_x: int,
) -> dict:
    return {
        "datasource": {"type": "prometheus", "uid": "${datasource}"},
        "fieldConfig": {
            "defaults": {
                "unit": unit,
                "min": 0,
                "max": max_val,
                "thresholds": {"mode": "absolute", "steps": thresholds},
            },
            "overrides": [],
        },
        "gridPos": {"h": 8, "w": 8, "x": grid_x, "y": grid_y},
        "id": hash(title + str(grid_y) + str(grid_x)) % 100000,
        "options": {
            "orientation": "auto",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "showThresholdLabels": True,
            "showThresholdMarkers": True,
        },
        "pluginVersion": "10.0.0",
        "targets": [
            {
                "expr": expr,
                "legendFormat": title,
                "refId": "A",
            }
        ],
        "title": title,
        "type": "gauge",
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def load_inventory(path: str) -> list[dict]:
    with open(path, "r") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, list):
        raise ValueError("Inventory YAML must be a list of service definitions")
    for svc in data:
        if "name" not in svc:
            raise ValueError("Every service must have a 'name' field")
    return data


def write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        f.write(content)
    print(f"  Created: {path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate observability stack configs from service inventory"
    )
    parser.add_argument(
        "--inventory",
        required=True,
        help="Path to YAML inventory file (list of service definitions)",
    )
    parser.add_argument(
        "--output",
        default="./observability",
        help="Output directory for generated configs",
    )
    args = parser.parse_args()

    out_dir = Path(args.output)
    services = load_inventory(args.inventory)

    print(f"Loaded {len(services)} service(s) from {args.inventory}")
    print(f"Generating configs into {out_dir.absolute()}")

    # 1. Prometheus rules
    recording = render_prometheus_recording_rules(services)
    slo_recording = render_slo_recording_rules(services)
    alerting = render_alerting_rules(services)
    write_file(out_dir / "prometheus_rules.yaml", recording + "\n" + slo_recording + "\n" + alerting)

    # 2. Grafana dashboards
    dashboards_dir = out_dir / "grafana_dashboards"
    for svc in services:
        dashboard = render_grafana_dashboard(svc)
        filename = f"{svc['name']}_dashboard.json"
        write_file(dashboards_dir / filename, json.dumps(dashboard, indent=2))

    # 3. OTel Collector config
    otel_config = render_otel_collector_config(services)
    write_file(out_dir / "otel_collector_config.yaml", otel_config)

    # 4. Alertmanager routes
    am_routes = render_alertmanager_routes(services)
    write_file(out_dir / "alertmanager_routes.yaml", am_routes)

    # 5. ServiceMonitors
    sm = render_servicemonitors(services)
    write_file(out_dir / "servicemonitors.yaml", sm)

    # 6. Promtail config
    promtail = render_loki_promtail(services)
    write_file(out_dir / "loki_promtail_config.yaml", promtail)

    print("\nDone. Review generated configs before applying to production.")


if __name__ == "__main__":
    main()
