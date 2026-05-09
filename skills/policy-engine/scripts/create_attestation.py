#!/usr/bin/env python3
"""
create_attestation.py — Create and verify signed attestation records for policy decisions.

Usage:
    create_attestation.py --decision-json <file> --previous-hash <hash> --output <file>
    create_attestation.py --verify --file <source_file>
    create_attestation.py --query --file <source_file> --line <line_number>
    create_attestation.py --verify-chain --log <log_file>
    create_attestation.py --compliance-report --log <log_file> --output <report_file>
"""

import argparse
import base64
import hashlib
import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Ed25519 via pynacl; fall back to pure-python ed25519-blake2b if needed
try:
    from nacl.signing import SigningKey, VerifyKey
    from nacl.exceptions import BadSignatureError
    _HAS_NACL = True
except ImportError:
    _HAS_NACL = False


def _fail(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def _load_signing_key() -> tuple:
    """Load Ed25519 signing key from env or generate ephemeral. Returns (signing_key, public_key_b64, is_ephemeral)."""
    key_env = os.environ.get("POLICY_ATTESTATION_KEY", "")
    if key_env:
        try:
            seed = base64.b64decode(key_env)
            if len(seed) != 32:
                _fail(f"POLICY_ATTESTATION_KEY must be 32 bytes after base64 decode, got {len(seed)}")
        except Exception as e:
            _fail(f"Invalid POLICY_ATTESTATION_KEY: {e}")
    else:
        seed = os.urandom(32)
        print("WARNING: POLICY_ATTESTATION_KEY not set; using ephemeral key", file=sys.stderr)

    if _HAS_NACL:
        sk = SigningKey(seed)
        vk = sk.verify_key
        pk_bytes = bytes(vk)
    else:
        # Pure-python fallback (placeholder — install pynacl for production)
        _fail("pynacl (PyNaCl) is required. Install: pip install pynacl")

    return sk, base64.b64encode(pk_bytes).decode(), not key_env


def canonical_json(obj: dict) -> str:
    """Canonical JSON representation for deterministic hashing."""
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def blake2b_hex(data: bytes) -> str:
    """BLAKE2b-256 hex digest."""
    return hashlib.blake2b(data, digest_size=32).hexdigest()


def compute_leaf_hash(decision: dict) -> str:
    """Compute Merkle leaf hash from decision fields."""
    payload = (
        f"{decision['decision_id']}||"
        f"{decision['arguments_hash']}||"
        f"{decision['decision']}||"
        f"{decision['timestamp']}"
    )
    return blake2b_hex(payload.encode())


def compute_merkle_root(previous_root: str, leaf_hash: str) -> str:
    """Compute new Merkle root from previous root and leaf hash."""
    payload = f"{previous_root}||{leaf_hash}"
    return blake2b_hex(payload.encode())


def sign_root(signing_key, merkle_root: str) -> str:
    """Sign merkle root with Ed25519, return base64 signature."""
    sig = signing_key.sign(merkle_root.encode())
    return base64.b64encode(sig).decode()


def verify_signature(public_key_b64: str, merkle_root: str, signature_b64: str) -> bool:
    """Verify Ed25519 signature over merkle root."""
    try:
        pk_bytes = base64.b64decode(public_key_b64)
        vk = VerifyKey(pk_bytes)
        sig_bytes = base64.b64decode(signature_b64)
        vk.verify(merkle_root.encode(), sig_bytes)
        return True
    except (BadSignatureError, Exception):
        return False


def create_attestation(decision: dict, previous_root: str, signing_key, public_key_b64: str) -> dict:
    """Create a signed attestation record from a policy decision."""
    leaf = compute_leaf_hash(decision)
    root = compute_merkle_root(previous_root, leaf)
    sig = sign_root(signing_key, root)

    return {
        "merkle_root": root,
        "signature": sig,
        "decision_id": decision["decision_id"],
        "timestamp": decision["timestamp"],
        "leaf_hash": leaf,
        "previous_root": previous_root,
        "public_key": public_key_b64,
        "version": "1.0",
        "metadata": {
            "tool_call": decision.get("tool_call", ""),
            "arguments_hash": decision.get("arguments_hash", ""),
            "decision": decision["decision"],
            "justification_hash": decision.get("justification_hash", ""),
            "policy_version": decision.get("policy_version", ""),
            "session_id": decision.get("session_id", ""),
            **({"escalation_target": decision["escalation_target"]} if decision.get("escalation_target") else {}),
            **({"new_public_key": decision["new_public_key"]} if decision.get("new_public_key") else {}),
        }
    }


def append_to_log(record: dict, log_path: str) -> None:
    """Append attestation record to JSONL log file."""
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a") as f:
        f.write(json.dumps(record, sort_keys=True) + "\n")


def extract_attestation_header(file_path: str) -> Optional[dict]:
    """Extract ATTESTATION headers from a source file. Supports multiple comment styles."""
    content = Path(file_path).read_text()

    # Python/shell/YAML style: # ATTESTATION: key=value
    if re.search(r'^#\s*ATTESTATION:', content, re.MULTILINE):
        pattern = r'^#\s*ATTESTATION:\s*(\w+)=(.+)$'
        matches = re.findall(pattern, content, re.MULTILINE)
        if matches:
            return {k: v for k, v in matches}

    # C-style: /* ATTESTATION: key=value */
    m = re.search(r'/\*\s*ATTESTATION:\s*(.+?)\*/', content, re.DOTALL)
    if m:
        block = m.group(1)
        matches = re.findall(r'ATTESTATION:\s*(\w+)=(.+?)(?:\n|\*/|$)', block)
        if matches:
            return {k: v.strip() for k, v in matches}

    # HTML/XML style: <!-- ATTESTATION: key=value -->
    m = re.search(r'<!--\s*ATTESTATION-BEGIN\s*(.+?)\s*ATTESTATION-END\s*-->', content, re.DOTALL)
    if m:
        block = m.group(1)
        matches = re.findall(r'(\w+):\s*(.+)', block)
        if matches:
            return {k: v.strip() for k, v in matches}

    # C-style block with leading whitespace
    m = re.search(r'/\*\s*ATTESTATION:\s*decision_id=(.+?)\*/', content, re.DOTALL)
    if m:
        block = m.group(0)
        matches = re.findall(r'ATTESTATION:\s*(\w+)=(.+?)(?:\n|$)', block)
        if matches:
            return {k: v.strip() for k, v in matches}

    return None


def load_log_records(log_path: str) -> list:
    """Load all records from JSONL attestation log."""
    if not Path(log_path).exists():
        return []
    records = []
    with open(log_path) as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                _fail(f"Invalid JSON at {log_path}:{line_num}: {e}")
    return records


def find_decision_in_log(decision_id: str, log_path: str) -> Optional[dict]:
    """Find attestation record by decision_id in log."""
    for rec in load_log_records(log_path):
        if rec.get("decision_id") == decision_id:
            return rec
    return None


def verify_chain(log_path: str) -> tuple:
    """Verify full Merkle chain integrity. Returns (ok, records, first_bad)."""
    records = load_log_records(log_path)
    if not records:
        return True, [], None

    for i, rec in enumerate(records):
        # Verify signature
        if not verify_signature(rec["public_key"], rec["merkle_root"], rec["signature"]):
            return False, records, i

        # Verify merkle root computation
        expected_root = compute_merkle_root(rec["previous_root"], rec["leaf_hash"])
        if rec["merkle_root"] != expected_root:
            return False, records, i

        # Verify linkage (except genesis)
        if i > 0:
            if rec["previous_root"] != records[i - 1]["merkle_root"]:
                return False, records, i
        else:
            if rec["previous_root"] != "0" * 64:
                return False, records, i

    return True, records, None


def generate_compliance_report(log_path: str, records: list) -> dict:
    """Generate compliance report from verified records."""
    allow_count = sum(1 for r in records if r.get("metadata", {}).get("decision") == "ALLOW")
    block_count = sum(1 for r in records if r.get("metadata", {}).get("decision") == "BLOCK")
    escalate_count = sum(1 for r in records if r.get("metadata", {}).get("decision") == "ESCALATE")
    key_rot_count = sum(1 for r in records if r.get("metadata", {}).get("decision") == "KEY_ROTATION")

    # Collect unique policy versions
    policy_versions = sorted(set(
        r.get("metadata", {}).get("policy_version", "")
        for r in records if r.get("metadata", {}).get("policy_version")
    ))

    # Public key from most recent record
    latest_pk = records[-1]["public_key"] if records else ""
    latest_root = records[-1]["merkle_root"] if records else "0" * 64

    return {
        "report_id": str(uuid.uuid4()),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "policy_version": policy_versions[-1] if policy_versions else "unknown",
        "all_policy_versions": policy_versions,
        "total_decisions": len(records),
        "allow_count": allow_count,
        "block_count": block_count,
        "escalate_count": escalate_count + key_rot_count,
        "chain_integrity": True,
        "first_decision": records[0]["timestamp"] if records else None,
        "last_decision": records[-1]["timestamp"] if records else None,
        "public_key": latest_pk,
        "merkle_root": latest_root,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Policy Attestation Layer")
    sub = parser.add_subparsers(dest="command")

    # Create attestation
    create_p = sub.add_parser("create", help="Create a signed attestation record")
    create_p.add_argument("--decision-json", required=True, help="Path to policy decision JSON file")
    create_p.add_argument("--previous-hash", default="0" * 64, help="Previous Merkle root (64 hex chars)")
    create_p.add_argument("--output", required=True, help="Output attestation JSON file")
    create_p.add_argument("--log", default=".policy/attestation_log.jsonl", help="Append-only log path")

    # Verify file
    verify_p = sub.add_parser("verify", help="Verify attestation in a source file")
    verify_p.add_argument("--file", required=True, help="Source file to verify")
    verify_p.add_argument("--log", default=".policy/attestation_log.jsonl", help="Attestation log path")

    # Query
    query_p = sub.add_parser("query", help="Query policy decision for a file/line")
    query_p.add_argument("--file", required=True, help="Source file to query")
    query_p.add_argument("--line", type=int, default=1, help="Line number (uses file's attestation header)")
    query_p.add_argument("--log", default=".policy/attestation_log.jsonl", help="Attestation log path")

    # Verify chain
    chain_p = sub.add_parser("verify-chain", help="Verify full Merkle chain integrity")
    chain_p.add_argument("--log", required=True, help="Attestation log path")

    # Compliance report
    report_p = sub.add_parser("compliance-report", help="Generate compliance report")
    report_p.add_argument("--log", required=True, help="Attestation log path")
    report_p.add_argument("--output", required=True, help="Output report JSON file")

    args = parser.parse_args()

    if args.command == "create":
        decision = json.loads(Path(args.decision_json).read_text())
        signing_key, public_key_b64, is_ephemeral = _load_signing_key()
        record = create_attestation(decision, args.previous_hash, signing_key, public_key_b64)
        Path(args.output).write_text(json.dumps(record, indent=2, sort_keys=True))
        append_to_log(record, args.log)
        print(f"Attestation created: decision={record['decision_id']}, root={record['merkle_root']}")
        if is_ephemeral:
            print(f"WARNING: Ephemeral key used. Public key: {public_key_b64}")
        return 0

    elif args.command == "verify":
        header = extract_attestation_header(args.file)
        if not header:
            _fail(f"No attestation header found in {args.file}")
        decision_id = header.get("decision_id")
        if not decision_id:
            _fail("No decision_id in attestation header")
        rec = find_decision_in_log(decision_id, args.log)
        if not rec:
            _fail(f"Decision {decision_id} not found in log")
        ok = verify_signature(rec["public_key"], rec["merkle_root"], rec["signature"])
        result = {
            "decision_id": rec["decision_id"],
            "decision": rec.get("metadata", {}).get("decision"),
            "justification_hash": rec.get("metadata", {}).get("justification_hash"),
            "policy_version": rec.get("metadata", {}).get("policy_version"),
            "timestamp": rec["timestamp"],
            "merkle_root": rec["merkle_root"],
            "verified": ok,
        }
        print(json.dumps(result, indent=2))
        return 0 if ok else 1

    elif args.command == "query":
        header = extract_attestation_header(args.file)
        if not header:
            _fail(f"No attestation header found in {args.file}")
        decision_id = header.get("decision_id")
        rec = find_decision_in_log(decision_id, args.log)
        if not rec:
            _fail(f"Decision {decision_id} not found in log")
        ok = verify_signature(rec["public_key"], rec["merkle_root"], rec["signature"])
        result = {
            "decision_id": rec["decision_id"],
            "decision": rec.get("metadata", {}).get("decision"),
            "justification_hash": rec.get("metadata", {}).get("justification_hash"),
            "policy_version": rec.get("metadata", {}).get("policy_version"),
            "timestamp": rec["timestamp"],
            "merkle_root": rec["merkle_root"],
            "verified": ok,
        }
        print(json.dumps(result, indent=2))
        return 0

    elif args.command == "verify-chain":
        ok, records, bad_idx = verify_chain(args.log)
        if ok:
            print(f"Chain verified: {len(records)} records, root={records[-1]['merkle_root'] if records else '0'*64}")
        else:
            rec = records[bad_idx] if bad_idx < len(records) else {}
            print(f"Chain BROKEN at record {bad_idx}: decision_id={rec.get('decision_id', 'N/A')}")
        return 0 if ok else 1

    elif args.command == "compliance-report":
        ok, records, bad_idx = verify_chain(args.log)
        report = generate_compliance_report(args.log, records)
        report["chain_integrity"] = ok
        if not ok:
            report["first_bad_record"] = bad_idx
        Path(args.output).write_text(json.dumps(report, indent=2, sort_keys=True))
        print(f"Compliance report written to {args.output}")
        print(f"  Total decisions: {report['total_decisions']}")
        print(f"  Chain integrity: {'PASS' if ok else 'FAIL'}")
        return 0 if ok else 1

    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
