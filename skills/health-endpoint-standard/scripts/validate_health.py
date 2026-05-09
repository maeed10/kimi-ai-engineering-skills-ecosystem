#!/usr/bin/env python3
"""validate_health.py — Validate service health endpoint compliance.

Checks that a service implements /health, /ready, and /metrics per the
standard schema.
"""

import argparse
import json
import sys
import urllib.request


def main():
    parser = argparse.ArgumentParser(description="Health Endpoint Validator")
    parser.add_argument("--base-url", required=True, help="Service base URL")
    parser.add_argument("--output", default="health_validation.json")
    args = parser.parse_args()

    endpoints = {
        "/health": {"required_fields": ["status"], "valid_statuses": ["ok", "healthy", "up"]},
        "/ready": {"required_fields": ["status", "checks"], "valid_statuses": ["ready", "ok"]},
        "/metrics": {"required_fields": [], "valid_statuses": [], "content_type": "text/plain"},
    }

    results = {}
    all_pass = True
    for path, spec in endpoints.items():
        url = args.base_url.rstrip("/") + path
        result = _check_endpoint(url, spec)
        results[path] = result
        if not result["pass"]:
            all_pass = False

    report = {
        "base_url": args.base_url,
        "all_pass": all_pass,
        "results": results,
    }

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(f"Health validation: {'PASS' if all_pass else 'FAIL'}")
    for path, res in results.items():
        print(f"  {path}: {'OK' if res['pass'] else res.get('error', 'FAIL')}")
    return 0 if all_pass else 1


def _check_endpoint(url, spec):
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            status = resp.status
            content_type = resp.headers.get("Content-Type", "")
            body = resp.read().decode("utf-8")
    except Exception as exc:
        return {"pass": False, "error": str(exc)}

    if status != 200:
        return {"pass": False, "error": f"HTTP {status}"}

    if path == "/metrics" and spec.get("content_type"):
        if spec["content_type"] not in content_type:
            return {"pass": False, "error": f"Wrong content type: {content_type}"}
        return {"pass": True, "status": status, "samples": body.count("\n")}

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return {"pass": False, "error": "Invalid JSON"}

    for field in spec["required_fields"]:
        if field not in data:
            return {"pass": False, "error": f"Missing field: {field}"}

    if spec["valid_statuses"] and data.get("status") not in spec["valid_statuses"]:
        return {"pass": False, "error": f"Invalid status: {data.get('status')}"}

    return {"pass": True, "status": status, "response": data}


if __name__ == "__main__":
    sys.exit(main())
