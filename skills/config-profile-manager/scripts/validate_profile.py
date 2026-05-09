#!/usr/bin/env python3
"""
validate_profile.py

Validation gate for sandbox-executor environment profiles.
Enforces inheritance model, security constraints, and OBSIDIAN-001
compliance before deployment.

Usage:
    python validate_profile.py --profile profiles/production.yaml --base profiles/base.yaml
    python validate_profile.py --profile profiles/staging.yaml --base profiles/base.yaml --strict

Exit codes:
    0 - Validated successfully
    1 - Syntax or schema error
    2 - Security gate failure (non-negotiable)
    3 - OBSIDIAN-001 gate failure
    4 - General validation error
"""

import argparse
import copy
import json
import re
import sys
import textwrap
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML is required. Install: pip install pyyaml")
    sys.exit(4)


class ValidationError(Exception):
    """Raised when a validation gate fails."""
    def __init__(self, gate: str, message: str, severity: str = "error"):
        self.gate = gate
        self.message = message
        self.severity = severity
        super().__init__(f"[{gate}] {severity}: {message}")


def load_yaml(path: Path) -> Dict[str, Any]:
    """Load and parse a YAML file."""
    if not path.exists():
        raise ValidationError("SYNTAX", f"File not found: {path}", "error")
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        data = yaml.safe_load(content)
        if data is None:
            raise ValidationError("SYNTAX", f"Empty YAML file: {path}", "error")
        return data
    except yaml.YAMLError as exc:
        raise ValidationError("SYNTAX", f"Invalid YAML in {path}: {exc}", "error")
    except Exception as exc:
        raise ValidationError("SYNTAX", f"Failed to read {path}: {exc}", "error")


def merge(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
    """Deep-merge overlay into base. Lists are replaced."""
    result = copy.deepcopy(base)
    for key, value in overlay.items():
        if key.startswith("_"):
            # Metadata keys (_inherits, _environment) are copied directly.
            result[key] = value
            continue
        if isinstance(value, dict) and key in result and isinstance(result[key], dict):
            result[key] = merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def get_nested(data: Dict[str, Any], path: str, default: Any = None) -> Any:
    """Get a nested value by dot-separated path."""
    keys = path.split(".")
    current = data
    for key in keys:
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return default
    return current


def set_nested(data: Dict[str, Any], path: str, value: Any) -> None:
    """Set a nested value by dot-separated path."""
    keys = path.split(".")
    current = data
    for key in keys[:-1]:
        if key not in current or not isinstance(current[key], dict):
            current[key] = {}
        current = current[key]
    current[keys[-1]] = value


def is_weaker(base_val: Any, profile_val: Any, setting_name: str) -> bool:
    """
    Determine if profile_val is a security weakening relative to base_val.
    Returns True if the profile is strictly weaker.
    """
    # Boolean weakening: true -> false for security-positive booleans
    if isinstance(base_val, bool) and isinstance(profile_val, bool):
        # Security-positive booleans: true is stronger
        if base_val is True and profile_val is False:
            return True
        return False

    # String weakening for client_auth_mode
    if setting_name.endswith("client_auth_mode"):
        strength = {"none": 0, "optional": 1, "require": 2}
        return strength.get(profile_val, -1) < strength.get(base_val, -1)

    # String weakening for tls_version_min
    if setting_name.endswith("tls_version_min"):
        strength = {"1.0": 0, "1.1": 1, "1.2": 2, "1.3": 3}
        return strength.get(profile_val, -1) < strength.get(base_val, -1)

    # List weakening for capability_additions (non-empty in dev is weaker)
    if setting_name.endswith("capability_additions"):
        base_list = base_val if isinstance(base_val, list) else []
        prof_list = profile_val if isinstance(profile_val, list) else []
        # Adding capabilities weakens security
        return len(prof_list) > len(base_list)

    # Policy weakening: deny -> allow
    if setting_name.endswith("default_decision"):
        return profile_val == "allow" and base_val == "deny"

    # Egress policy weakening: restricted -> unrestricted
    if setting_name.endswith("egress_policy"):
        return profile_val == "unrestricted" and base_val == "restricted"

    # Log level weakening: higher verbosity in prod-like environments
    if setting_name.endswith("log_level"):
        strength = {"DEBUG": 0, "INFO": 1, "WARN": 2, "ERROR": 3}
        return strength.get(profile_val, -1) < strength.get(base_val, -1)

    # verify_signatures weakening: true -> false
    if setting_name.endswith("verify_signatures"):
        return base_val is True and profile_val is False

    return False


class ProfileValidator:
    """Runs all validation gates against a merged profile."""

    def __init__(self, base: Dict[str, Any], merged: Dict[str, Any], strict: bool = False):
        self.base = base
        self.merged = merged
        self.strict = strict
        self.warnings: List[str] = []
        self.errors: List[str] = []
        self.environment: str = merged.get("_environment", "unknown")

    def run_all(self) -> Tuple[bool, List[str], List[str]]:
        """Run all gates and return (passed, warnings, errors)."""
        gates = [
            self.gate_schema,
            self.gate_inheritance,
            self.gate_security,
            self.gate_production,
            self.gate_obsidian_001,
        ]
        for gate in gates:
            try:
                gate()
            except ValidationError as exc:
                if exc.severity == "warn":
                    self.warnings.append(str(exc))
                else:
                    self.errors.append(str(exc))
        return len(self.errors) == 0, self.warnings, self.errors

    def gate_schema(self) -> None:
        """Gate 1: Validate required top-level keys and types."""
        required_keys = ["version", "description", "_inherits", "_environment"]
        for key in required_keys:
            if key not in self.merged:
                raise ValidationError("SCHEMA", f"Missing required key: {key}")

        if self.merged["_inherits"] != "base.yaml":
            raise ValidationError("SCHEMA", f"_inherits must be 'base.yaml', got '{self.merged['_inherits']}'")

        env = self.merged["_environment"]
        if env not in ("development", "staging", "production"):
            raise ValidationError("SCHEMA", f"_environment must be one of [development, staging, production], got '{env}'")

        # Validate that sandbox and security sections exist
        if "sandbox" not in self.merged:
            raise ValidationError("SCHEMA", "Missing 'sandbox' section")
        if "security" not in self.merged:
            raise ValidationError("SCHEMA", "Missing 'security' section")

    def gate_inheritance(self) -> None:
        """Gate 2: Verify inheritance is correctly applied."""
        # Ensure base values are present unless explicitly overridden
        base_keys = set(self.base.keys())
        merged_keys = set(self.merged.keys())

        # Check that base structure is preserved (extra keys allowed in overlay)
        for key in base_keys:
            if key not in merged_keys and not key.startswith("_"):
                raise ValidationError("INHERITANCE", f"Inherited key '{key}' missing from merged profile")

    def gate_security(self) -> None:
        """Gate 3: Security setting audit. Flags any profile where settings are weaker than base."""
        security_paths = [
            ("security.sandbox_escape_prevention", bool),
            ("security.read_only_rootfs", bool),
            ("security.no_new_privileges", bool),
            ("security.image_verification.verify_signatures", bool),
            ("security.network.client_auth_mode", str),
            ("security.network.tls_version_min", str),
            ("policy_engine.default_decision", str),
            ("network.egress_policy", str),
            ("observability.log_level", str),
            ("security.capability_additions", list),
        ]

        for path, _ in security_paths:
            base_val = get_nested(self.base, path)
            profile_val = get_nested(self.merged, path)
            if base_val is not None and profile_val is not None:
                if is_weaker(base_val, profile_val, path):
                    msg = f"Security weakening detected: {path} base={base_val} profile={profile_val}"
                    if self.environment in ("staging", "production"):
                        raise ValidationError("SECURITY", msg, "error")
                    else:
                        # In development, weakenings are expected but must be documented
                        raise ValidationError("SECURITY", msg + " (acceptable in development with risk acceptance)", "warn")

    def gate_production(self) -> None:
        """Gate 4: Non-negotiable production controls."""
        if self.environment != "production":
            return

        non_negotiable = {
            "security.capability_additions": [],
            "security.read_only_rootfs": True,
            "security.no_new_privileges": True,
            "security.image_verification.verify_signatures": True,
            "security.network.client_auth_mode": "require",
            "security.network.tls_version_min": "1.3",
            "policy_engine.default_decision": "deny",
            "vault.obsidian.mount_policy.mode": "production",
            "vault.obsidian.mount_policy.allow_mock_secrets": False,
            "vault.obsidian.mount_policy.require_approval": True,
            "vault.obsidian.mount_policy.audit_reads": True,
            "vault.obsidian.mount_policy.audit_writes": True,
            "observability.log_level": ("WARN", "ERROR"),  # Tuple means one of
            "network.egress_policy": "restricted",
        }

        for path, expected in non_negotiable.items():
            actual = get_nested(self.merged, path)
            if actual is None:
                raise ValidationError("PRODUCTION", f"Missing non-negotiable setting: {path}")
            if isinstance(expected, tuple):
                if actual not in expected:
                    raise ValidationError("PRODUCTION", f"{path} must be one of {expected}, got {actual}")
            elif actual != expected:
                raise ValidationError("PRODUCTION", f"{path} must be {expected}, got {actual}")

        # Additional production-only checks
        hot_reload = get_nested(self.merged, "sandbox.executor.hot_reload")
        if hot_reload is True:
            raise ValidationError("PRODUCTION", "sandbox.executor.hot_reload must not be true in production")

        capability_drops = get_nested(self.merged, "security.capability_drops", [])
        if "ALL" not in capability_drops:
            raise ValidationError("PRODUCTION", "security.capability_drops MUST include 'ALL'")

    def gate_obsidian_001(self) -> None:
        """Gate 5: OBSIDIAN-001 production vault mount policy enforcement."""
        if self.environment != "production":
            # Non-production environments must still explicitly define mount_policy
            mount_policy = get_nested(self.merged, "vault.obsidian.mount_policy")
            if mount_policy is None or not isinstance(mount_policy, dict):
                raise ValidationError("OBSIDIAN-001", "vault.obsidian.mount_policy must be explicitly defined in all environments")
            return

        mount_policy = get_nested(self.merged, "vault.obsidian.mount_policy")
        if mount_policy is None or not isinstance(mount_policy, dict):
            raise ValidationError("OBSIDIAN-001", "Production MUST explicitly define vault.obsidian.mount_policy (OBSIDIAN-001)")

        # Required keys for production
        required_keys = [
            "mode",
            "allowed_paths",
            "require_approval",
            "audit_reads",
            "audit_writes",
        ]
        for key in required_keys:
            if key not in mount_policy:
                raise ValidationError("OBSIDIAN-001", f"Production mount_policy missing required key: {key}")

        if mount_policy.get("mode") != "production":
            raise ValidationError("OBSIDIAN-001", f"mount_policy.mode must be 'production', got '{mount_policy.get('mode')}'")

        allowed_paths = mount_policy.get("allowed_paths", [])
        if not isinstance(allowed_paths, list) or len(allowed_paths) == 0:
            raise ValidationError("OBSIDIAN-001", "mount_policy.allowed_paths must be a non-empty list")

        # Verify allowed_paths are production-prefixed (or explicitly documented)
        for path in allowed_paths:
            if not path.startswith("production/") and not path.startswith("production"):
                self.warnings.append(
                    f"[OBSIDIAN-001] Warning: mount_policy.allowed_paths entry '{path}' does not start with 'production/'"
                )

        if mount_policy.get("allow_mock_secrets") is not False:
            raise ValidationError("OBSIDIAN-001", "mount_policy.allow_mock_secrets must be false in production")

        if mount_policy.get("audit_immutable_log") is not True:
            raise ValidationError("OBSIDIAN-001", "mount_policy.audit_immutable_log must be true in production")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate a sandbox-executor environment profile against base + security constraints."
    )
    parser.add_argument("--profile", "-p", required=True, help="Path to the environment profile YAML")
    parser.add_argument("--base", "-b", default="profiles/base.yaml", help="Path to base.yaml")
    parser.add_argument("--strict", "-s", action="store_true", help="Treat warnings as errors")
    parser.add_argument("--json", "-j", action="store_true", help="Output results as JSON")
    parser.add_argument("--verbose", "-v", action="store_true", help="Print merged config")
    args = parser.parse_args()

    profile_path = Path(args.profile)
    base_path = Path(args.base)

    try:
        base_data = load_yaml(base_path)
        profile_data = load_yaml(profile_path)
    except ValidationError as exc:
        print(str(exc))
        return 1

    # Merge base + overlay
    merged = merge(base_data, profile_data)

    if args.verbose:
        print("=== Merged Configuration ===")
        print(yaml.dump(merged, default_flow_style=False, sort_keys=False))
        print("=== Validation Results ===")

    validator = ProfileValidator(base_data, merged, strict=args.strict)
    passed, warnings, errors = validator.run_all()

    result = {
        "profile": str(profile_path),
        "base": str(base_path),
        "environment": validator.environment,
        "passed": passed and (not args.strict or len(warnings) == 0),
        "warnings": warnings,
        "errors": errors,
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Profile:  {profile_path}")
        print(f"Base:     {base_path}")
        print(f"Environment: {validator.environment}")
        print(f"Status:   {'PASS' if result['passed'] else 'FAIL'}")
        if warnings:
            print(f"\nWarnings ({len(warnings)}):")
            for w in warnings:
                print(textwrap.indent(w, "  - "))
        if errors:
            print(f"\nErrors ({len(errors)}):")
            for e in errors:
                print(textwrap.indent(e, "  - "))

    if not result["passed"]:
        if any("PRODUCTION" in e for e in errors):
            return 2
        if any("OBSIDIAN-001" in e for e in errors):
            return 3
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
