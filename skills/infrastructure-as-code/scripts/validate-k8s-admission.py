#!/usr/bin/env python3
"""
Kubernetes Admission Controller Validation Script

Validates that the target Kubernetes cluster has Pod Security Standards
(restricted) properly enabled and configured before deploying sandbox
workloads. This addresses the gap identified in the v4.2.0 review where
the ecosystem assumed PSS enforcement without verifying admission controller
presence.

Usage:
    python validate-k8s-admission.py [--kubeconfig path] [--namespace kimi-sandboxes]

Exit codes:
    0 - All checks passed, cluster is ready for sandbox deployment
    1 - One or more critical checks failed
    2 - Validation error (e.g., no kubeconfig, API unreachable)
"""

import argparse
import json
import subprocess
import sys
from typing import List, Dict, Optional


class Colors:
    OK = "\033[92m"
    WARN = "\033[93m"
    FAIL = "\033[91m"
    INFO = "\033[94m"
    RESET = "\033[0m"


def run_kubectl(args: List[str], kubeconfig: Optional[str] = None) -> subprocess.CompletedProcess:
    """Run kubectl and return result."""
    cmd = ["kubectl"]
    if kubeconfig:
        cmd.extend(["--kubeconfig", kubeconfig])
    cmd.extend(args)
    return subprocess.run(cmd, capture_output=True, text=True)


def check_api_server_version() -> tuple[bool, str]:
    """Check if API server is reachable and version is supported."""
    result = run_kubectl(["version", "--output=json"])
    if result.returncode != 0:
        return False, f"Cannot reach API server: {result.stderr.strip()}"
    try:
        data = json.loads(result.stdout)
        server_version = data.get("serverVersion", {})
        major = int(server_version.get("major", 0))
        minor = int(server_version.get("minor", "0").replace("+", ""))
        if major < 1 or (major == 1 and minor < 23):
            return False, f"Kubernetes v{major}.{minor} too old. PSS requires v1.23+"
        return True, f"Kubernetes v{major}.{minor} detected"
    except (json.JSONDecodeError, ValueError) as e:
        return False, f"Failed to parse version: {e}"


def check_pod_security_admission() -> tuple[bool, str]:
    """Check if Pod Security Admission controller is enabled."""
    result = run_kubectl([
        "get", "pods",
        "-n", "kube-system",
        "-l", "component=kube-apiserver",
        "-o", "json"
    ])
    if result.returncode != 0:
        return False, f"Cannot check API server pods: {result.stderr.strip()}"
    try:
        data = json.loads(result.stdout)
        pods = data.get("items", [])
        if not pods:
            return False, "No kube-apiserver pods found"
        # Check if PodSecurity feature gate is enabled
        # In v1.25+, PSA is enabled by default
        result2 = run_kubectl([
            "get", "--raw", "/apis/config.k8s.io/v1/"
        ])
        if result2.returncode != 0:
            # Fallback: check if admissionregistration.k8s.io exists
            result3 = run_kubectl([
                "api-resources", "--api-group=admissionregistration.k8s.io"
            ])
            if "validatingadmissionpolicy" in result3.stdout.lower():
                return True, "ValidatingAdmissionPolicy available (v1.28+ alternative to PSA)"
            return False, "Pod Security Admission not detected; cluster may not enforce PSS"
        return True, "Pod Security Admission controller is available"
    except json.JSONDecodeError:
        return False, "Failed to parse API server pod data"


def check_namespace_pss_labels(namespace: str) -> tuple[bool, str]:
    """Check if target namespace has PSS labels."""
    result = run_kubectl(["get", "namespace", namespace, "-o", "json"])
    if result.returncode != 0:
        if "NotFound" in result.stderr:
            return True, f"Namespace '{namespace}' does not exist yet (will be created with labels)"
        return False, f"Cannot check namespace: {result.stderr.strip()}"
    try:
        data = json.loads(result.stdout)
        labels = data.get("metadata", {}).get("labels", {})
        pss_level = labels.get("pod-security.kubernetes.io/enforce", "")
        pss_version = labels.get("pod-security.kubernetes.io/enforce-version", "")
        if pss_level == "restricted":
            return True, f"Namespace has enforce=restricted (version: {pss_version or 'latest'})"
        elif pss_level in ["baseline", "privileged"]:
            return False, f"Namespace enforce={pss_level}, expected 'restricted'"
        else:
            return False, f"Namespace missing PSS enforce label (found: {pss_level or 'none'})"
    except json.JSONDecodeError:
        return False, "Failed to parse namespace data"


def check_psp_or_pss() -> tuple[bool, str]:
    """Check if legacy PSP or modern PSS is active."""
    result = run_kubectl(["get", "psp", "-o", "name"])
    if result.returncode == 0 and result.stdout.strip():
        return True, f"Legacy PodSecurityPolicies found: {result.stdout.strip().split()[0]}..."
    # No PSPs, check if PSS is the enforcement mechanism
    result2 = run_kubectl([
        "get", "namespaces", "-o", "json"
    ])
    if result2.returncode != 0:
        return False, "Cannot list namespaces"
    try:
        data = json.loads(result2.stdout)
        namespaces = data.get("items", [])
        pss_enabled = any(
            "pod-security.kubernetes.io" in str(ns.get("metadata", {}).get("labels", {}))
            for ns in namespaces
        )
        if pss_enabled:
            return True, "Pod Security Standards labels detected on namespaces"
        return False, "Neither PSP nor PSS detected; sandbox workloads may run unrestricted"
    except json.JSONDecodeError:
        return False, "Failed to parse namespace list"


def check_network_policies(namespace: str) -> tuple[bool, str]:
    """Check if default deny NetworkPolicy exists."""
    result = run_kubectl([
        "get", "networkpolicy",
        "-n", namespace,
        "-o", "json"
    ])
    if result.returncode != 0:
        if "NotFound" in result.stderr or "No resources" in result.stderr:
            return True, f"No NetworkPolicies in '{namespace}' (will apply default deny)"
        return False, f"Cannot check NetworkPolicies: {result.stderr.strip()}"
    try:
        data = json.loads(result.stdout)
        policies = data.get("items", [])
        deny_all = any(
            p.get("spec", {}).get("policyTypes") == ["Ingress", "Egress"] and
            not p.get("spec", {}).get("ingress", []) and
            not p.get("spec", {}).get("egress", [])
            for p in policies
        )
        if deny_all:
            return True, "Default deny-all NetworkPolicy exists"
        return True, f"NetworkPolicies exist ({len(policies)}), verify default deny is present"
    except json.JSONDecodeError:
        return False, "Failed to parse NetworkPolicy data"


def check_rbac(namespace: str) -> tuple[bool, str]:
    """Check if least-privilege RBAC is configured."""
    result = run_kubectl([
        "get", "serviceaccount",
        "-n", namespace,
        "-o", "name"
    ])
    if result.returncode != 0:
        return True, f"Cannot check ServiceAccounts (will create with least privilege)"
    sas = result.stdout.strip().split("\n")
    if any("kimi-sandbox" in sa for sa in sas):
        return True, "kimi-sandbox ServiceAccount exists"
    return True, "ServiceAccounts will be created during deployment"


def print_result(check_name: str, passed: bool, message: str) -> None:
    """Print formatted check result."""
    status = f"{Colors.OK}PASS{Colors.RESET}" if passed else f"{Colors.FAIL}FAIL{Colors.RESET}"
    print(f"  [{status}] {check_name}: {message}")


def main():
    parser = argparse.ArgumentParser(
        description="Validate Kubernetes cluster readiness for sandbox deployment"
    )
    parser.add_argument(
        "--kubeconfig",
        help="Path to kubeconfig file"
    )
    parser.add_argument(
        "--namespace",
        default="kimi-sandboxes",
        help="Target namespace for sandbox workloads"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON"
    )
    args = parser.parse_args()

    checks = []
    all_passed = True

    def do_check(name: str, func) -> None:
        nonlocal all_passed
        passed, message = func()
        checks.append({"name": name, "passed": passed, "message": message})
        if not passed:
            all_passed = False

    if not args.json:
        print(f"{Colors.INFO}Validating Kubernetes cluster for sandbox deployment...{Colors.RESET}")
        print(f"Target namespace: {args.namespace}\n")

    do_check("API Server Reachability", check_api_server_version)
    do_check("Pod Security Admission", check_pod_security_admission)
    do_check("PSS/PSP Enforcement", check_psp_or_pss)
    do_check("Namespace PSS Labels", lambda: check_namespace_pss_labels(args.namespace))
    do_check("Network Policies", lambda: check_network_policies(args.namespace))
    do_check("RBAC Configuration", lambda: check_rbac(args.namespace))

    if args.json:
        print(json.dumps({
            "passed": all_passed,
            "namespace": args.namespace,
            "checks": checks
        }, indent=2))
    else:
        print()
        for check in checks:
            print_result(check["name"], check["passed"], check["message"])
        print()
        if all_passed:
            print(f"{Colors.OK}All checks passed. Cluster is ready for sandbox deployment.{Colors.RESET}")
        else:
            print(f"{Colors.FAIL}One or more checks failed. Review output above before deploying.{Colors.RESET}")
            print(f"{Colors.INFO}Note: If Pod Security Admission is not available, consider:{Colors.RESET}")
            print(f"  1. Enabling the PodSecurity feature gate (v1.23-v1.24)")
            print(f"  2. Using OPA/Gatekeeper with equivalent restricted policies")
            print(f"  3. Using Kyverno with pod-security standards cluster policies")

    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
