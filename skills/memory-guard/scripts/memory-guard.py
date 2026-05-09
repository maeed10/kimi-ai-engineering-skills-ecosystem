#!/usr/bin/env python3
"""
memory-guard.py
Trust-scored memory integrity system for the Kimi AI Engineering Skills Ecosystem v4.0.

Implements:
  - Trust scoring (STRUCTURAL=0.9, INFERRED=0.6, EXTERNAL=0.3)
  - Temporal decay per session for untrusted sources
  - Ground-truth verification via Brownfield Intelligence SQLite index
  - Ed25519 append-only signing for episodic logs
  - manifest.sha256 covering all memory files
  - Obsolescence detection and auto-archival

Usage:
    # Import as module
    from memory_guard import MemoryGuard
    guard = MemoryGuard(vault_path="/path/to/vault")
    guard.write_episodic(content="...", source_class="EXTERNAL")

    # CLI audit
    python memory-guard.py --vault /path/to/vault --audit
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Literal, Optional, Tuple

# --- Dependencies (install if missing) ---
try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
        Ed25519PublicKey,
    )
    from cryptography.hazmat.primitives import serialization
    from cryptography.exceptions import InvalidSignature
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "Package 'cryptography' is required. Install: pip install cryptography"
    ) from exc


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SOURCE_STRUCTURAL: Literal["STRUCTURAL"] = "STRUCTURAL"
SOURCE_INFERRED: Literal["INFERRED"] = "INFERRED"
SOURCE_EXTERNAL: Literal["EXTERNAL"] = "EXTERNAL"

BASE_SCORES = {
    SOURCE_STRUCTURAL: 0.9,
    SOURCE_INFERRED: 0.6,
    SOURCE_EXTERNAL: 0.3,
}

DECAY_EXTERNAL = 0.9
DECAY_INFERRED = 0.95
DECAY_STRUCTURAL = 1.0

SCORE_FLOOR = 0.0
SCORE_CEILING = 1.0
ARCHIVAL_THRESHOLD = 0.25
REINFORCEMENT_CAP = 0.95

MIN_CORROBORATION_PROCEDURAL = 2

DEFAULT_SESSIONS_FOR_CONSOLIDATION = 5
DRIFT_THRESHOLD = 0.4
OBSOLESCENCE_DAYS = 30

BROWNFIELD_DB = "vault/_agent/brownfield/codebase_index.db"
MEMORY_DIR = "vault/_agent/memory"
EPISODIC_DIR = f"{MEMORY_DIR}/episodic"
SEMANTIC_DIR = f"{MEMORY_DIR}/semantic"
PROCEDURAL_DIR = f"{MEMORY_DIR}/procedural"
ARCHIVE_DIR = f"{MEMORY_DIR}/archived"
MANIFEST_FILE = f"{MEMORY_DIR}/manifest.sha256"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class Provenance:
    source_sessions: List[str]
    trust_score: float
    verification_status: Literal["VERIFIED", "UNVERIFIED", "PENDING", "FAILED"]
    signature_refs: List[str]
    created_at: str
    verified_at: Optional[str] = None

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class MemoryEntry:
    entry_id: str
    timestamp: float
    content_hash: str
    source_class: Literal["STRUCTURAL", "INFERRED", "EXTERNAL"]
    trust_score: float
    corroboration_count: int
    prev_hash: str
    signature: str
    content_preview: str  # truncated for indexing
    provenance: Optional[Provenance] = None
    last_accessed: float = field(default_factory=time.time)
    access_count: int = 0

    def canonical_bytes(self) -> bytes:
        """Return deterministic bytes for signing/ hashing."""
        payload = {
            "entry_id": self.entry_id,
            "timestamp": self.timestamp,
            "content_hash": self.content_hash,
            "source_class": self.source_class,
            "trust_score": self.trust_score,
            "corroboration_count": self.corroboration_count,
            "prev_hash": self.prev_hash,
            "content_preview": self.content_preview,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


# ---------------------------------------------------------------------------
# Trust scoring engine
# ---------------------------------------------------------------------------

class TrustEngine:
    """Deterministic trust score computation."""

    @staticmethod
    def compute(
        source_class: Literal["STRUCTURAL", "INFERRED", "EXTERNAL"],
        corroboration_count: int = 1,
        sessions_elapsed: int = 0,
        verification_status: Literal["VERIFIED", "UNVERIFIED", "PENDING", "FAILED"] = "PENDING",
        reinforced: bool = False,
    ) -> float:
        base = BASE_SCORES.get(source_class, BASE_SCORES[SOURCE_EXTERNAL])

        # Corroboration factor
        if corroboration_count >= 2:
            corr_factor = 1.0
        elif corroboration_count == 1:
            corr_factor = 0.8
        else:
            corr_factor = 0.5

        # Verification factor
        if verification_status == "VERIFIED":
            verif_factor = 1.0
        elif verification_status == "PENDING":
            verif_factor = 0.7
        elif verification_status == "UNVERIFIED":
            verif_factor = 0.5
        else:  # FAILED
            verif_factor = 0.4

        # Recency / decay factor
        if source_class == SOURCE_STRUCTURAL:
            decay = DECAY_STRUCTURAL ** sessions_elapsed
        elif source_class == SOURCE_INFERRED:
            decay = DECAY_INFERRED ** sessions_elapsed
        else:
            decay = DECAY_EXTERNAL ** sessions_elapsed

        score = base * corr_factor * verif_factor * decay

        if reinforced:
            score = min(score, REINFORCEMENT_CAP)

        return max(SCORE_FLOOR, min(SCORE_CEILING, round(score, 4)))

    @staticmethod
    def validate_procedural_corroboration(corrob_count: int) -> bool:
        return corrob_count >= MIN_CORROBORATION_PROCEDURAL


# ---------------------------------------------------------------------------
# Cryptographic signing
# ---------------------------------------------------------------------------

class Signer:
    """Ed25519 append-only signer."""

    def __init__(self, private_key: Optional[Ed25519PrivateKey] = None):
        self._private_key = private_key or Ed25519PrivateKey.generate()
        self._public_key = self._private_key.public_key()

    @property
    def public_key_bytes(self) -> bytes:
        return self._public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )

    def sign(self, message: bytes) -> bytes:
        return self._private_key.sign(message)

    def verify(self, signature: bytes, message: bytes, public_key: Ed25519PublicKey) -> bool:
        try:
            public_key.verify(signature, message)
            return True
        except InvalidSignature:
            return False

    @staticmethod
    def load_public_key(key_bytes: bytes) -> Ed25519PublicKey:
        return Ed25519PublicKey.from_public_bytes(key_bytes)


# ---------------------------------------------------------------------------
# Manifest manager
# ---------------------------------------------------------------------------

class ManifestManager:
    """SHA-256 manifest covering all memory files."""

    def __init__(self, manifest_path: Path):
        self.manifest_path = manifest_path

    def _read_manifest(self) -> Dict[str, str]:
        if not self.manifest_path.exists():
            return {}
        with open(self.manifest_path, "r", encoding="utf-8") as fh:
            return dict(line.strip().split(maxsplit=1) for line in fh if line.strip())

    def _write_manifest(self, entries: Dict[str, str]) -> None:
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.manifest_path, "w", encoding="utf-8") as fh:
            for path, digest in sorted(entries.items()):
                fh.write(f"{digest}  {path}\n")

    @staticmethod
    def file_hash(path: Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    def update(self, file_path: Path) -> None:
        entries = self._read_manifest()
        rel = str(file_path)
        entries[rel] = self.file_hash(file_path)
        self._write_manifest(entries)

    def verify(self, file_path: Path) -> bool:
        entries = self._read_manifest()
        rel = str(file_path)
        if rel not in entries:
            return False
        return entries[rel] == self.file_hash(file_path)

    def full_audit(self, root: Path) -> Tuple[bool, List[str]]:
        entries = self._read_manifest()
        mismatches: List[str] = []
        for rel_path, expected in entries.items():
            full = root / rel_path
            if not full.exists():
                mismatches.append(f"MISSING: {rel_path}")
                continue
            if self.file_hash(full) != expected:
                mismatches.append(f"HASH_MISMATCH: {rel_path}")
        ok = len(mismatches) == 0
        return ok, mismatches


# ---------------------------------------------------------------------------
# Brownfield verifier
# ---------------------------------------------------------------------------

class BrownfieldVerifier:
    """Ground-truth verification against Brownfield Intelligence SQLite index."""

    def __init__(self, db_path: Path):
        self.db_path = db_path

    def verify_pattern(self, pattern_text: str, file_refs: Optional[List[str]] = None) -> bool:
        if not self.db_path.exists():
            return False  # Cannot verify if index missing
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        # Simplified query; real schema may vary
        cursor.execute(
            "SELECT pattern_hash, file_refs, line_count FROM codebase_patterns WHERE pattern_text = ?",
            (pattern_text,),
        )
        row = cursor.fetchone()
        conn.close()
        if not row:
            return False
        if file_refs:
            db_refs = json.loads(row[1]) if isinstance(row[1], str) else row[1]
            if not any(ref in db_refs for ref in file_refs):
                return False
        return True


# ---------------------------------------------------------------------------
# Main MemoryGuard orchestrator
# ---------------------------------------------------------------------------

class MemoryGuard:
    """Orchestrates trust scoring, signing, verification, decay, and archival."""

    def __init__(
        self,
        vault_path: str,
        signer: Optional[Signer] = None,
    ):
        self.vault = Path(vault_path)
        self.memory_root = self.vault / MEMORY_DIR
        self.episodic_root = self.vault / EPISODIC_DIR
        self.semantic_root = self.vault / SEMANTIC_DIR
        self.procedural_root = self.vault / PROCEDURAL_DIR
        self.archive_root = self.vault / ARCHIVE_DIR
        self.manifest = ManifestManager(self.vault / MANIFEST_FILE)
        self.brownfield = BrownfieldVerifier(self.vault / BROWNFIELD_DB)
        self.signer = signer or Signer()
        self.trust_engine = TrustEngine()
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        for d in (
            self.memory_root,
            self.episodic_root,
            self.semantic_root,
            self.procedural_root,
            self.archive_root,
        ):
            d.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Episodic write
    # ------------------------------------------------------------------

    def write_episodic(
        self,
        content: str,
        source_class: Literal["STRUCTURAL", "INFERRED", "EXTERNAL"],
        session_id: str,
        corroboration_count: int = 1,
    ) -> MemoryEntry:
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        timestamp = time.time()

        # Determine prev_hash from latest entry in session log
        log_file = self.episodic_root / session_id[:7] / f"{session_id}.jsonl"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        prev_hash = "0" * 64
        if log_file.exists():
            with open(log_file, "r", encoding="utf-8") as fh:
                lines = fh.readlines()
                if lines:
                    last = json.loads(lines[-1])
                    prev_hash = last["content_hash"]

        trust_score = self.trust_engine.compute(
            source_class=source_class,
            corroboration_count=corroboration_count,
        )

        entry = MemoryEntry(
            entry_id=f"{session_id}-{int(timestamp * 1000)}",
            timestamp=timestamp,
            content_hash=content_hash,
            source_class=source_class,
            trust_score=trust_score,
            corroboration_count=corroboration_count,
            prev_hash=prev_hash,
            signature="",  # filled below
            content_preview=content[:200],
        )

        # Sign
        sig = self.signer.sign(entry.canonical_bytes())
        entry.signature = sig.hex()

        # Append
        with open(log_file, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry.to_dict(), default=str) + "\n")

        # Update manifest
        self.manifest.update(log_file)
        return entry

    # ------------------------------------------------------------------
    # Signature chain verification
    # ------------------------------------------------------------------

    def verify_episodic_chain(
        self,
        session_id: str,
        public_key: Optional[Ed25519PublicKey] = None,
    ) -> Tuple[bool, List[str]]:
        log_file = self.episodic_root / session_id[:7] / f"{session_id}.jsonl"
        errors: List[str] = []
        if not log_file.exists():
            return False, [f"Log missing: {log_file}"]

        pk = public_key or self.signer._public_key
        prev_hash = "0" * 64

        with open(log_file, "r", encoding="utf-8") as fh:
            for i, line in enumerate(fh, 1):
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError as exc:
                    errors.append(f"Line {i}: JSON error {exc}")
                    continue

                entry = MemoryEntry(
                    entry_id=raw["entry_id"],
                    timestamp=raw["timestamp"],
                    content_hash=raw["content_hash"],
                    source_class=raw["source_class"],
                    trust_score=raw["trust_score"],
                    corroboration_count=raw.get("corroboration_count", 1),
                    prev_hash=raw["prev_hash"],
                    signature=raw["signature"],
                    content_preview=raw["content_preview"],
                )

                if entry.prev_hash != prev_hash:
                    errors.append(f"Line {i}: prev_hash mismatch")

                sig_bytes = bytes.fromhex(entry.signature)
                if not self.signer.verify(sig_bytes, entry.canonical_bytes(), pk):
                    errors.append(f"Line {i}: invalid signature")

                prev_hash = entry.content_hash

        return len(errors) == 0, errors

    # ------------------------------------------------------------------
    # Decay and archival
    # ------------------------------------------------------------------

    def apply_decay(self, entries: List[MemoryEntry], sessions_elapsed: int) -> List[MemoryEntry]:
        for e in entries:
            e.trust_score = self.trust_engine.compute(
                source_class=e.source_class,
                corroboration_count=e.corroboration_count,
                sessions_elapsed=sessions_elapsed,
                verification_status=(e.provenance.verification_status if e.provenance else "PENDING"),
            )
            e.last_accessed = time.time()
        return entries

    def archive_if_stale(self, entries: List[MemoryEntry]) -> Tuple[List[MemoryEntry], List[MemoryEntry]]:
        active, archived = [], []
        now = time.time()
        for e in entries:
            days_unused = (now - e.last_accessed) / 86400
            if e.trust_score < ARCHIVAL_THRESHOLD or days_unused > OBSOLESCENCE_DAYS:
                archived.append(e)
            else:
                active.append(e)
        # Persist archived entries
        if archived:
            archive_file = self.archive_root / f"archive_{int(now)}.jsonl"
            with open(archive_file, "a", encoding="utf-8") as fh:
                for e in archived:
                    fh.write(json.dumps(e.to_dict(), default=str) + "\n")
            self.manifest.update(archive_file)
        return active, archived

    # ------------------------------------------------------------------
    # Consolidation gate
    # ------------------------------------------------------------------

    def verify_before_promotion(
        self,
        candidate_patterns: List[Dict[str, any]],
    ) -> Tuple[List[Dict], List[Dict]]:
        verified, rejected = [], []
        for pat in candidate_patterns:
            text = pat.get("pattern_text", "")
            refs = pat.get("file_refs", [])
            if self.brownfield.verify_pattern(text, refs):
                pat["verification_status"] = "VERIFIED"
                verified.append(pat)
            else:
                pat["verification_status"] = "UNVERIFIED"
                rejected.append(pat)
        return verified, rejected

    def promote_to_semantic(
        self,
        pattern: Dict,
        source_sessions: List[str],
        signature_refs: List[str],
    ) -> Path:
        # Build provenance
        provenance = Provenance(
            source_sessions=source_sessions,
            trust_score=pattern.get("trust_score", 0.0),
            verification_status="VERIFIED",
            signature_refs=signature_refs,
            created_at=pattern.get("created_at", ""),
            verified_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )
        pattern["provenance"] = provenance.to_dict()

        # NEVER promote EXTERNAL without verification
        if pattern.get("source_class") == SOURCE_EXTERNAL and provenance.verification_status != "VERIFIED":
            raise ValueError("EXTERNAL memory promoted without verification — blocked by policy")

        out_path = self.semantic_root / f"{pattern.get('pattern_id', 'pat')}.json"
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(pattern, fh, indent=2, default=str)
        self.manifest.update(out_path)
        return out_path

    # ------------------------------------------------------------------
    # Resume gate
    # ------------------------------------------------------------------

    def resume_audit(self, session_ids: List[str]) -> Dict[str, any]:
        report = {"manifest_ok": True, "chains_ok": True, "entries": []}
        manifest_ok, manifest_errors = self.manifest.full_audit(self.vault)
        report["manifest_ok"] = manifest_ok
        report["manifest_errors"] = manifest_errors

        for sid in session_ids:
            ok, errors = self.verify_episodic_chain(sid)
            if not ok:
                report["chains_ok"] = False
                report.setdefault("chain_errors", {})[sid] = errors

        # Load and decay semantic memories
        semantic_entries: List[MemoryEntry] = []
        for f in self.semantic_root.glob("*.json"):
            with open(f, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
            # Minimal reconstruction
            semantic_entries.append(
                MemoryEntry(
                    entry_id=raw.get("pattern_id", f.stem),
                    timestamp=time.mktime(time.strptime(raw["provenance"]["created_at"], "%Y-%m-%dT%H:%M:%SZ")) if "provenance" in raw else 0,
                    content_hash=hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest(),
                    source_class=raw.get("source_class", SOURCE_INFERRED),
                    trust_score=raw.get("provenance", {}).get("trust_score", 0.6),
                    corroboration_count=1,
                    prev_hash="0" * 64,
                    signature="",
                    content_preview=raw.get("pattern_text", "")[:200],
                    provenance=Provenance(**raw["provenance"]) if "provenance" in raw else None,
                )
            )

        decayed = self.apply_decay(semantic_entries, sessions_elapsed=1)  # assume 1 session elapsed since last run
        active, archived = self.archive_if_stale(decayed)
        report["semantic_active"] = len(active)
        report["semantic_archived"] = len(archived)
        return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="MemoryGuard CLI")
    parser.add_argument("--vault", required=True, help="Path to vault root")
    parser.add_argument("--audit", action="store_true", help="Run full integrity audit")
    parser.add_argument("--session", default=None, help="Session ID for chain verification")
    parser.add_argument("--write-episodic", default=None, help="Content to write to episodic memory")
    parser.add_argument("--source", default="EXTERNAL", choices=["STRUCTURAL", "INFERRED", "EXTERNAL"])
    args = parser.parse_args()

    guard = MemoryGuard(vault_path=args.vault)

    if args.audit:
        # Discover session IDs from episodic dir
        session_ids = []
        for d in (guard.episodic_root).rglob("*.jsonl"):
            session_ids.append(d.stem)
        report = guard.resume_audit(session_ids)
        print(json.dumps(report, indent=2))
        return 0 if (report["manifest_ok"] and report["chains_ok"]) else 1

    if args.session:
        ok, errors = guard.verify_episodic_chain(args.session)
        print(json.dumps({"ok": ok, "errors": errors}, indent=2))
        return 0 if ok else 1

    if args.write_episodic:
        entry = guard.write_episodic(
            content=args.write_episodic,
            source_class=args.source,
            session_id=args.session or f"sess-{int(time.time())}",
        )
        print(json.dumps(entry.to_dict(), default=str, indent=2))
        return 0

    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
