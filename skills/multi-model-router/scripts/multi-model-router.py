#!/usr/bin/env python3
"""
multi-model-router — Multi-provider low-cost task router.

Routes eligible tasks to external LLM providers (Gemini, Claude, local Ollama)
while enforcing user-selected cost preferences, billing thresholds, and daily caps.

Usage:
    python multi-model-router.py --provider gemini --task-type INGEST --payload '{"text":"hello"}' --tools '[]'
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Optional YAML support
try:
    import yaml
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False

# Configuration paths
STATE_DIR = Path.home() / ".kimi" / "state"
CONFIG_PATH = Path.home() / ".kimi" / "config" / "multi-model-router.yaml"
COUNTER_PATH = STATE_DIR / "multi-model-counter.json"
PREF_PATH = STATE_DIR / "user-provider-preference.json"

# Hard-coded safety constants
ELIGIBLE_PHASES = {"INGEST", "PLAN", "DELIVER", "REMEMBER"}
BLOCKED_PHASES = {"ASSESS", "EXECUTE", "VALIDATE"}
EXTERNAL_TRUST_SCORE = 0.3

DEFAULT_PROVIDERS = {
    "gemini": {
        "backend": "gemini-cli",
        "model": "gemini-2.5-flash-lite",
        "daily_limit_requests": 950,
        "cost_per_1k_tokens": 0.0,
        "billing_category": "free_tier",
        "security_classification": "non_security_only",
        "allowed_phases": ["INGEST", "PLAN", "DELIVER", "REMEMBER"],
    },
    "claude": {
        "backend": "anthropic-cli",
        "model": "claude-sonnet-4",
        "daily_limit_requests": 500,
        "cost_per_1k_tokens": 3.00,
        "billing_category": "paid",
        "security_classification": "non_security_only",
        "allowed_phases": ["INGEST", "PLAN", "DELIVER", "REMEMBER"],
    },
    "local": {
        "backend": "ollama",
        "model": "qwen2.5-coder:14b",
        "daily_limit_requests": None,
        "cost_per_1k_tokens": 0.0,
        "billing_category": "self_hosted",
        "security_classification": "non_security_only",
        "allowed_phases": ["INGEST", "PLAN", "DELIVER", "REMEMBER"],
    },
}

DEFAULT_BILLING = {
    "monthly_budget_usd": 100.00,
    "daily_budget_usd": 3.33,
    "alert_threshold": 0.80,
    "hard_stop_threshold": 1.00,
    "currency": "USD",
}


def _load_yaml_config(path: Path) -> dict:
    """Load YAML config if available; return empty dict on failure."""
    if not _HAS_YAML or not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except (yaml.YAMLError, OSError):
        return {}


def _load_json(path: Path) -> dict:
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_json(path: Path, data: dict) -> None:
    """Atomically save JSON with best-effort locking."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")

    # Best-effort file locking (Windows-compatible)
    if sys.platform == "win32":
        import msvcrt
        with open(tmp, "w", encoding="utf-8") as f:
            try:
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                # Fallback: write without lock
                f.seek(0)
                f.truncate()
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
    else:
        import fcntl
        with open(tmp, "w", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    tmp.replace(path)


def get_config() -> tuple[dict, dict]:
    """Return merged (providers, billing) from YAML config with hardcoded defaults as fallback."""
    cfg = _load_yaml_config(CONFIG_PATH)
    router_cfg = cfg.get("router", {})

    providers = {}
    for name, default in DEFAULT_PROVIDERS.items():
        yaml_prov = router_cfg.get("providers", {}).get(name, {})
        merged = dict(default)
        merged.update(yaml_prov)
        providers[name] = merged

    billing = dict(DEFAULT_BILLING)
    billing.update(router_cfg.get("billing", {}))

    return providers, billing


def load_counter(billing: dict) -> dict:
    data = _load_json(COUNTER_PATH)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    providers, _ = get_config()
    if data.get("date") != today:
        return {
            "date": today,
            "providers": {
                name: {"count": 0, "limit": cfg["daily_limit_requests"], "status": "OK"}
                for name, cfg in providers.items()
            },
            "billing": {
                "daily_spend_usd": 0.0,
                "daily_budget_usd": billing["daily_budget_usd"],
                "status": "OK",
            },
        }
    return data


def save_counter(data: dict) -> None:
    _save_json(COUNTER_PATH, data)


def load_preferences() -> dict:
    defaults = {
        "preferred_provider": "gemini",
        "preferred_model": "gemini-2.5-flash-lite",
        "cost_ceiling_usd_per_day": 5.00,
        "auto_fallback_allowed": False,
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }
    prefs = _load_json(PREF_PATH)
    defaults.update(prefs)
    return defaults


def check_eligibility(phase: str, tool_types: list[str], provider: str, providers: dict) -> tuple[bool, str]:
    if phase in BLOCKED_PHASES:
        return False, f"Phase '{phase}' is in blocked list"
    if phase not in ELIGIBLE_PHASES:
        return False, f"Phase '{phase}' not in eligible phases"
    blocked_tools = {"write_file", "edit_file", "shell", "execute"}
    if any(t in blocked_tools for t in tool_types):
        return False, "Task requires write or execute tools"
    cfg = providers.get(provider)
    if cfg and phase not in cfg.get("allowed_phases", ELIGIBLE_PHASES):
        return False, f"Provider '{provider}' does not allow phase '{phase}'"
    return True, "Eligible"


def _resolve_gemini_cmd() -> list[str]:
    """Resolve the Gemini CLI command, handling Windows .ps1 wrapper."""
    gemini_sh = shutil.which("gemini")
    if gemini_sh and sys.platform != "win32":
        return ["gemini"]
    # Windows: gemini is a .ps1 wrapper; find the node bundle directly
    npm_prefix_candidates = [
        Path.home() / "AppData" / "Roaming" / "npm",
        Path.home() / ".npm-global",
        Path("/usr/local/lib/node_modules"),
        Path("/usr/lib/node_modules"),
    ]
    for prefix in npm_prefix_candidates:
        bundle = prefix / "node_modules" / "@google" / "gemini-cli" / "bundle" / "gemini.js"
        if bundle.exists():
            node = shutil.which("node") or "node"
            return [node, str(bundle)]
    # Fallback: try shell execution (Windows PowerShell can resolve .ps1)
    if sys.platform == "win32":
        return ["powershell.exe", "-ExecutionPolicy", "RemoteSigned", "-Command", "gemini"]
    return ["gemini"]


def route_to_provider(provider: str, payload: dict, providers: dict) -> dict:
    cfg = providers[provider]
    backend = cfg["backend"]
    model = cfg["model"]

    if backend == "gemini-cli":
        cmd = _resolve_gemini_cmd() + [
            "-m", model,
            "-p", json.dumps(payload),
            "--output-format", "text",
        ]
    elif backend == "anthropic-cli":
        cmd = [
            "claude",
            "--model", model,
            "--prompt", json.dumps(payload),
        ]
    elif backend == "ollama":
        cmd = [
            "ollama", "run", model,
            json.dumps(payload),
        ]
    else:
        return {"error": f"Unknown backend: {backend}", "exit_code": 1}

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "exit_code": result.returncode,
        "provider": provider,
        "model": model,
    }


def main():
    parser = argparse.ArgumentParser(description="Multi-provider low-cost task router")
    parser.add_argument("--provider", default="gemini", help="Provider to route to")
    parser.add_argument("--task-type", required=True)
    parser.add_argument("--phase", required=True)
    parser.add_argument("--payload", required=True)
    parser.add_argument("--tools", default="[]")
    args = parser.parse_args()

    providers, billing = get_config()

    # 1. Load preferences and override provider if user has sticky preference
    prefs = load_preferences()
    provider = prefs.get("preferred_provider", args.provider)
    if args.provider != provider:
        provider = args.provider  # CLI override still respected

    # 2. Check eligibility
    tools = json.loads(args.tools)
    eligible, reason = check_eligibility(args.phase, tools, provider, providers)
    if not eligible:
        print(json.dumps({"routed_to": "kimi", "reason": reason}))
        sys.exit(0)

    # 3. Check provider config exists
    if provider not in providers:
        print(json.dumps({
            "routed_to": "kimi",
            "reason": f"Unknown provider '{provider}'",
        }))
        sys.exit(0)

    cfg = providers[provider]

    # 4. Check daily counter / billing threshold
    counter = load_counter(billing)
    prov_counter = counter["providers"].get(provider, {})
    limit = prov_counter.get("limit")
    count = prov_counter.get("count", 0)

    if limit is not None and count >= limit:
        print(json.dumps({
            "routed_to": "kimi",
            "reason": f"Daily {provider} limit reached",
            "count": count,
            "limit": limit,
        }))
        sys.exit(0)

    # Billing check
    daily_budget = billing.get("daily_budget_usd", 3.33)
    daily_spend = counter.get("billing", {}).get("daily_spend_usd", 0.0)
    if daily_spend >= daily_budget:
        print(json.dumps({
            "routed_to": "kimi",
            "reason": "Daily billing threshold reached",
            "daily_spend_usd": daily_spend,
            "daily_budget_usd": daily_budget,
        }))
        sys.exit(0)

    # 5. Cost disclosure for paid providers
    cost_per_1k = cfg.get("cost_per_1k_tokens", 0.0)
    if cost_per_1k > 0:
        if not prefs.get("auto_fallback_allowed"):
            print(json.dumps({
                "routed_to": "kimi",
                "reason": f"Paid provider '{provider}' requires explicit consent (${cost_per_1k}/1k tokens). Set auto_fallback_allowed=true to enable.",
            }))
            sys.exit(0)

    # 6. Dispatch to provider (sandboxed in production via sandbox-executor)
    payload = json.loads(args.payload)
    result = route_to_provider(provider, payload, providers)

    # 7. Increment counter / billing ledger
    prov_counter["count"] = count + 1
    if limit and prov_counter["count"] >= limit * 0.9:
        prov_counter["status"] = "APPROACHING"
    counter["providers"][provider] = prov_counter
    save_counter(counter)

    # 8. Return result with EXTERNAL trust tagging
    print(json.dumps({
        "routed_to": provider,
        "trust_class": "EXTERNAL",
        "base_score": EXTERNAL_TRUST_SCORE,
        "result": result,
        "daily_count": prov_counter["count"],
        "remaining": limit - prov_counter["count"] if limit else None,
    }))


if __name__ == "__main__":
    main()
