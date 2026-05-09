#!/usr/bin/env python3
"""
Supply Chain Verifier — Signature Verification Script

Verifies a full skill-package signature chain (TUF + detached signatures),
container image cosign signatures, or policy/config file signatures.

Returns structured JSON: {"valid": bool, "role": str, "errors": [...]}

Usage:
    python verify_signature.py skill \
        --tuf-repo https://tuf-repo.skills.internal \
        --skill-name supply-chain-verifier \
        --version 1.0.0 \
        --tarball supply-chain-verifier-1.0.0.tar.gz \
        --root-key-fingerprint sha256:abcd...

    python verify_signature.py image \
        --image-ref ghcr.io/skills/sandbox-executor@sha256:abcd... \
        --cosign-pub-key cosign.pub \
        --rekor-url https://rekor.sigstore.dev

    python verify_signature.py policy \
        --file sandbox-config.yaml \
        --sig-file sandbox-config.yaml.sig \
        --tuf-repo https://tuf-repo.skills.internal \
        --target-name policy/sandbox-config.yaml \
        --root-key-fingerprint sha256:abcd...
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

# Hardcoded root-of-trust fingerprint (SHA-256 of root public key).
# This constant is intended to be overridden at build time or via a trusted
# secondary config file that is itself signed by this root.
DEFAULT_ROOT_KEY_FP = "sha256:0000000000000000000000000000000000000000000000000000000000000000"


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _result(valid: bool, role: str, errors: list[str]) -> dict[str, Any]:
    return {"valid": valid, "role": role, "errors": errors}


def _run_cmd(cmd: list[str], capture: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        capture_output=capture,
        text=True,
        check=False,
    )


def verify_tuf_metadata(
    tuf_repo: str,
    root_key_fp: str,
    max_root_version: int = 5,
) -> dict[str, Any]:
    """
    Fetch and verify the TUF metadata chain: root -> targets -> snapshot -> timestamp.
    This is a lightweight verifier using standard tuf/ngclient when available,
    or manual verification as fallback.
    """
    errors: list[str] = []

    # Validate root key fingerprint format
    if not root_key_fp.startswith("sha256:") or len(root_key_fp) != 71:
        errors.append(f"Invalid root-key-fingerprint format: {root_key_fp}")
        return _result(False, "root", errors)

    # Attempt to use tuf.ngclient for a full update
    try:
        from tuf.ngclient import Updater
    except ImportError:
        errors.append("tuf.ngclient not installed; falling back to manual verification")
        return _verify_tuf_manual(tuf_repo, root_key_fp, max_root_version)

    try:
        metadata_dir = tempfile.mkdtemp(prefix="tuf_metadata_")
        updater = Updater(
            metadata_dir=metadata_dir,
            metadata_base_url=f"{tuf_repo}/metadata/",
            target_base_url=f"{tuf_repo}/targets/",
        )
        updater.refresh()
    except Exception as exc:
        errors.append(f"TUF updater refresh failed: {exc}")
        return _result(False, "root", errors)

    # If ngclient succeeds, we still want to confirm the root key fingerprint
    # matches the hardcoded expectation by inspecting the trusted root metadata.
    root_path = Path(metadata_dir) / "root.json"
    if root_path.exists():
        try:
            with open(root_path, "r") as f:
                root_meta = json.load(f)
            # Extract root public key values and compute fingerprint
            root_keys = root_meta.get("signed", {}).get("keys", {})
            matched = False
            for keyid, keydata in root_keys.items():
                pubkey_val = keydata.get("keyval", {}).get("public", "")
                if not pubkey_val:
                    continue
                fp = "sha256:" + hashlib.sha256(pubkey_val.encode()).hexdigest()
                if fp == root_key_fp:
                    matched = True
                    break
            if not matched:
                errors.append(
                    f"Trusted root key fingerprint does not match hardcoded value: {root_key_fp}"
                )
                return _result(False, "root", errors)
        except Exception as exc:
            errors.append(f"Root fingerprint check failed: {exc}")
            return _result(False, "root", errors)

    return _result(True, "root", errors)


def _verify_tuf_manual(
    tuf_repo: str, root_key_fp: str, max_root_version: int
) -> dict[str, Any]:
    """Fallback manual verification using securesystemslib when ngclient unavailable."""
    errors: list[str] = []

    try:
        import securesystemslib.keys as sslib_keys
    except ImportError:
        errors.append(
            "securesystemslib not installed; cannot perform manual TUF verification"
        )
        return _result(False, "root", errors)

    # Fetch root.json (start from version 1, iterate up to max_root_version)
    import urllib.request

    root_meta: dict[str, Any] | None = None
    version_found = 0
    for v in range(1, max_root_version + 1):
        url = f"{tuf_repo}/metadata/{v}.root.json"
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                root_meta = data
                version_found = v
        except Exception:
            break  # assume no higher version exists

    if root_meta is None:
        errors.append(f"Could not fetch any root.json up to version {max_root_version}")
        return _result(False, "root", errors)

    if version_found > max_root_version:
        errors.append(
            f"Root version {version_found} exceeds MAX_ROOT_VERSION {max_root_version}"
        )
        return _result(False, "root", errors)

    signed = root_meta.get("signed", {})
    sigs = root_meta.get("signatures", [])
    keys = signed.get("keys", {})
    roles = signed.get("roles", {})
    root_role = roles.get("root", {})
    threshold = root_role.get("threshold", 3)
    keyids = root_role.get("keyids", [])

    # Verify self-signatures on root
    valid_sigs = 0
    for sig in sigs:
        keyid = sig.get("keyid")
        if keyid not in keyids:
            continue
        keydata = keys.get(keyid)
        if not keydata:
            continue
        try:
            pubkey = sslib_keys.format_keyval_to_metadata(
                keydata["keytype"], keydata["scheme"], keydata["keyval"]
            )
            canonical = json.dumps(signed, sort_keys=True, separators=(",", ":"))
            if sslib_keys.verify_signature(pubkey, sig["sig"], canonical.encode()):
                valid_sigs += 1
        except Exception as exc:
            errors.append(f"Signature verification failed for keyid {keyid}: {exc}")

    if valid_sigs < threshold:
        errors.append(
            f"Root self-signature threshold not met: {valid_sigs}/{threshold}"
        )
        return _result(False, "root", errors)

    # Verify fingerprint against hardcoded expectation
    matched = False
    for keyid in keyids:
        keydata = keys.get(keyid, {})
        pubkey_val = keydata.get("keyval", {}).get("public", "")
        if not pubkey_val:
            continue
        fp = "sha256:" + hashlib.sha256(pubkey_val.encode()).hexdigest()
        if fp == root_key_fp:
            matched = True
            break

    if not matched:
        errors.append(
            f"No root key matches hardcoded fingerprint: {root_key_fp}"
        )
        return _result(False, "root", errors)

    return _result(True, "root", errors)


def verify_skill_package(
    tuf_repo: str,
    skill_name: str,
    version: str,
    tarball_path: str,
    root_key_fp: str,
    max_root_version: int = 5,
) -> dict[str, Any]:
    """
    Verify a skill package tarball against TUF targets metadata and detached signatures.
    """
    errors: list[str] = []

    # Step 1: Verify TUF chain
    tuf_result = verify_tuf_metadata(tuf_repo, root_key_fp, max_root_version)
    if not tuf_result["valid"]:
        errors.extend(tuf_result["errors"])
        return _result(False, "skill-package", errors)

    # Step 2: Verify tarball exists and compute digest
    if not os.path.isfile(tarball_path):
        errors.append(f"Tarball not found: {tarball_path}")
        return _result(False, "skill-package", errors)

    actual_digest = _sha256_file(tarball_path)
    actual_length = os.path.getsize(tarball_path)

    # Step 3: Look up target in TUF metadata (using ngclient when available)
    try:
        from tuf.ngclient import Updater

        metadata_dir = tempfile.mkdtemp(prefix="tuf_verify_")
        updater = Updater(
            metadata_dir=metadata_dir,
            metadata_base_url=f"{tuf_repo}/metadata/",
            target_base_url=f"{tuf_repo}/targets/",
        )
        updater.refresh()

        target_path = f"skills/{skill_name}-{version}.tar.gz"
        target_info = updater.get_targetinfo(target_path)
        if target_info is None:
            errors.append(f"Target not found in TUF metadata: {target_path}")
            return _result(False, "skill-package", errors)

        expected_length = target_info.length
        expected_hashes = target_info.hashes
        expected_sha256 = expected_hashes.get("sha256", "")

        if actual_length != expected_length:
            errors.append(
                f"Length mismatch: expected {expected_length}, got {actual_length}"
            )

        if actual_digest != expected_sha256:
            errors.append(
                f"Digest mismatch: expected {expected_sha256}, got {actual_digest}"
            )

        if errors:
            return _result(False, "skill-package", errors)

        # Step 4: Verify detached package signatures in custom metadata
        custom = target_info.unrecognized_fields.get("custom", {})
        sigs = custom.get("signatures", [])
        if not sigs:
            errors.append("No detached signatures found in custom metadata")
            return _result(False, "skill-package", errors)

        # Load targets keys from trusted root metadata
        root_path = Path(metadata_dir) / "root.json"
        with open(root_path, "r") as f:
            root_meta = json.load(f)
        keys = root_meta.get("signed", {}).get("keys", {})
        roles = root_meta.get("signed", {}).get("roles", {})
        targets_keyids = roles.get("targets", {}).get("keyids", [])
        targets_threshold = roles.get("targets", {}).get("threshold", 2)

        # The payload signed is: canonical JSON of {name, version, sha256, length}
        payload = json.dumps(
            {
                "name": skill_name,
                "version": version,
                "sha256": actual_digest,
                "length": actual_length,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()

        valid_sigs = 0
        try:
                            import securesystemslib.keys as sslib_keys

                            for sig in sigs:
                                keyid = sig.get("keyid")
                                if keyid not in targets_keyids:
                                    continue
                                keydata = keys.get(keyid)
                                if not keydata:
                                    continue
                                try:
                                    pubkey = sslib_keys.format_keyval_to_metadata(
                                        keydata["keytype"],
                                        keydata["scheme"],
                                        keydata["keyval"],
                                    )
                                    if sslib_keys.verify_signature(
                                        pubkey, sig["sig"], payload
                                    ):
                                        valid_sigs += 1
                                except Exception:
                                    pass
        except ImportError:
            errors.append(
                "securesystemslib not installed; cannot verify detached signatures"
            )
            return _result(False, "skill-package", errors)

        if valid_sigs < targets_threshold:
            errors.append(
                f"Detached signature threshold not met: {valid_sigs}/{targets_threshold}"
            )
            return _result(False, "skill-package", errors)

    except Exception as exc:
        errors.append(f"Skill-package verification error: {exc}")
        return _result(False, "skill-package", errors)

    return _result(True, "skill-package", errors)


def verify_container_image(
    image_ref: str,
    cosign_pub_key: str,
    rekor_url: str = "https://rekor.sigstore.dev",
) -> dict[str, Any]:
    """
    Verify a container image digest-pin reference with cosign.
    Rejects tag-only references.
    """
    errors: list[str] = []

    # Enforce digest-pin
    if "@sha256:" not in image_ref:
        errors.append(
            "Image reference must be digest-pinned (sha256:...); tag-only is rejected"
        )
        return _result(False, "image", errors)

    if not os.path.isfile(cosign_pub_key):
        errors.append(f"Cosign public key not found: {cosign_pub_key}")
        return _result(False, "image", errors)

    # Run cosign verify
    cmd = [
        "cosign",
        "verify",
        "--key", cosign_pub_key,
        "--rekor-url", rekor_url,
        image_ref,
    ]
    proc = _run_cmd(cmd)
    if proc.returncode != 0:
        errors.append(f"cosign verify failed: {proc.stderr or proc.stdout}")
        return _result(False, "image", errors)

    # Optional: verify SBOM attestation presence
    att_cmd = [
        "cosign",
        "verify-attestation",
        "--key", cosign_pub_key,
        "--rekor-url", rekor_url,
        "--type", "spdx",
        image_ref,
    ]
    att_proc = _run_cmd(att_cmd)
    if att_proc.returncode != 0:
        # Non-fatal: treat as warning
        errors.append(
            f"SBOM attestation missing or invalid (warning): {att_proc.stderr or att_proc.stdout}"
        )
        # We still consider image valid, but flag the warning
        return _result(True, "image", errors)

    return _result(True, "image", errors)


def verify_policy_file(
    tuf_repo: str,
    file_path: str,
    sig_path: str,
    target_name: str,
    root_key_fp: str,
    max_root_version: int = 5,
) -> dict[str, Any]:
    """
    Verify a policy/config file against TUF targets metadata and a detached signature.
    """
    errors: list[str] = []

    if not os.path.isfile(file_path):
        errors.append(f"Policy file not found: {file_path}")
        return _result(False, "policy", errors)

    if not os.path.isfile(sig_path):
        errors.append(f"Signature file not found: {sig_path}")
        return _result(False, "policy", errors)

    # Step 1: Verify TUF chain
    tuf_result = verify_tuf_metadata(tuf_repo, root_key_fp, max_root_version)
    if not tuf_result["valid"]:
        errors.extend(tuf_result["errors"])
        return _result(False, "policy", errors)

    # Step 2: Compute file digest and verify against targets
    actual_digest = _sha256_file(file_path)
    actual_length = os.path.getsize(file_path)

    try:
        from tuf.ngclient import Updater

        metadata_dir = tempfile.mkdtemp(prefix="tuf_policy_")
        updater = Updater(
            metadata_dir=metadata_dir,
            metadata_base_url=f"{tuf_repo}/metadata/",
            target_base_url=f"{tuf_repo}/targets/",
        )
        updater.refresh()

        target_info = updater.get_targetinfo(target_name)
        if target_info is None:
            errors.append(f"Policy target not found in TUF metadata: {target_name}")
            return _result(False, "policy", errors)

        expected_sha256 = target_info.hashes.get("sha256", "")
        if actual_digest != expected_sha256:
            errors.append(
                f"Policy digest mismatch: expected {expected_sha256}, got {actual_digest}"
            )
            return _result(False, "policy", errors)

        if actual_length != target_info.length:
            errors.append(
                f"Policy length mismatch: expected {target_info.length}, got {actual_length}"
            )
            return _result(False, "policy", errors)

    except Exception as exc:
        errors.append(f"Policy TUF lookup failed: {exc}")
        return _result(False, "policy", errors)

    # Step 3: Verify detached signature file
    try:
        with open(sig_path, "rb") as f:
            raw_sig = f.read()

        # Try base64 decode; if it fails, treat raw bytes as signature
        import base64

        try:
            decoded_sig = base64.b64decode(raw_sig)
        except Exception:
            decoded_sig = raw_sig

        # Load targets public keys from cached root
        root_path = Path(metadata_dir) / "root.json"
        with open(root_path, "r") as f:
            root_meta = json.load(f)
        keys = root_meta.get("signed", {}).get("keys", {})
        roles = root_meta.get("signed", {}).get("roles", {})
        targets_keyids = roles.get("targets", {}).get("keyids", [])
        targets_threshold = roles.get("targets", {}).get("threshold", 2)

        payload = Path(file_path).read_bytes()

        import securesystemslib.keys as sslib_keys

        valid_sigs = 0
        for keyid in targets_keyids:
            keydata = keys.get(keyid)
            if not keydata:
                continue
            try:
                pubkey = sslib_keys.format_keyval_to_metadata(
                    keydata["keytype"], keydata["scheme"], keydata["keyval"]
                )
                if sslib_keys.verify_signature(pubkey, decoded_sig, payload):
                    valid_sigs += 1
                    break  # single detached sig suffices if from trusted key
            except Exception:
                pass

        if valid_sigs < targets_threshold:
            errors.append(
                f"Policy signature threshold not met: {valid_sigs}/{targets_threshold}"
            )
            return _result(False, "policy", errors)

    except ImportError:
        errors.append("securesystemslib not installed; cannot verify policy signature")
        return _result(False, "policy", errors)
    except Exception as exc:
        errors.append(f"Policy signature verification error: {exc}")
        return _result(False, "policy", errors)

    return _result(True, "policy", errors)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Supply Chain Verifier: verify signatures for skills, images, and policies."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # skill subcommand
    skill_parser = subparsers.add_parser("skill", help="Verify a skill package")
    skill_parser.add_argument("--tuf-repo", required=True)
    skill_parser.add_argument("--skill-name", required=True)
    skill_parser.add_argument("--version", required=True)
    skill_parser.add_argument("--tarball", required=True)
    skill_parser.add_argument("--root-key-fingerprint", default=DEFAULT_ROOT_KEY_FP)
    skill_parser.add_argument("--max-root-version", type=int, default=5)

    # image subcommand
    image_parser = subparsers.add_parser("image", help="Verify a container image")
    image_parser.add_argument("--image-ref", required=True)
    image_parser.add_argument("--cosign-pub-key", required=True)
    image_parser.add_argument("--rekor-url", default="https://rekor.sigstore.dev")

    # policy subcommand
    policy_parser = subparsers.add_parser("policy", help="Verify a policy/config file")
    policy_parser.add_argument("--tuf-repo", required=True)
    policy_parser.add_argument("--file", required=True)
    policy_parser.add_argument("--sig-file", required=True)
    policy_parser.add_argument("--target-name", required=True)
    policy_parser.add_argument("--root-key-fingerprint", default=DEFAULT_ROOT_KEY_FP)
    policy_parser.add_argument("--max-root-version", type=int, default=5)

    args = parser.parse_args()
    result: dict[str, Any] = {}

    if args.command == "skill":
        result = verify_skill_package(
            tuf_repo=args.tuf_repo,
            skill_name=args.skill_name,
            version=args.version,
            tarball_path=args.tarball,
            root_key_fp=args.root_key_fingerprint,
            max_root_version=args.max_root_version,
        )
    elif args.command == "image":
        result = verify_container_image(
            image_ref=args.image_ref,
            cosign_pub_key=args.cosign_pub_key,
            rekor_url=args.rekor_url,
        )
    elif args.command == "policy":
        result = verify_policy_file(
            tuf_repo=args.tuf_repo,
            file_path=args.file,
            sig_path=args.sig_file,
            target_name=args.target_name,
            root_key_fp=args.root_key_fingerprint,
            max_root_version=args.max_root_version,
        )

    print(json.dumps(result, indent=2))
    return 0 if result.get("valid") else 1


if __name__ == "__main__":
    sys.exit(main())
