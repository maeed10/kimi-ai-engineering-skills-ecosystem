#!/usr/bin/env python3
"""
ipi-screener.py — Multi-Stage Indirect Prompt Injection (IPI) Detection Engine
================================================================================
Reference implementation template for the `ipi-defender` skill (v4.0.0).

Stages:
  1. Pattern Scan      — regex fingerprinting of known injection signatures
  2. Entropy Analysis  — detection of encoding tricks via character distribution
  3. Semantic Shift    — PPL-W embedding divergence vs. task baseline

Outputs:
  - Composite threat score
  - Deterministic action: pass | tag_high | quarantine
  - Immutable audit log entry

DO NOT use this as a standalone security product without operational review.
This is a TEMPLATE — adapt thresholds, models, and signatures to your environment.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import unicodedata
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Dict, List, Literal, Optional, Tuple

# ---------------------------------------------------------------------------
# Optional dependencies: provide graceful degradation if unavailable.
# ---------------------------------------------------------------------------
try:
    import numpy as np
    HAS_NUMPY = True
except Exception:  # pragma: no cover
    HAS_NUMPY = False
    np = None  # type: ignore

try:
    from sentence_transformers import SentenceTransformer
    HAS_ST = True
except Exception:  # pragma: no cover
    HAS_ST = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_CRITICAL_THRESHOLD = 0.85
DEFAULT_WARNING_THRESHOLD = 0.45
DEFAULT_WINDOW_SIZE = 512
DEFAULT_STRIDE = 256
DEFAULT_BASELINE_WINDOW = 1024
SCAN_VERSION = "4.0.0"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("ipi-defender")

# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

class Action(str, Enum):
    PASS = "pass"
    TAG_HIGH = "tag_high"
    QUARANTINE = "quarantine"


@dataclass(frozen=True)
class ScreeningResult:
    action: Action
    tag: str
    pattern_score: float
    entropy_score: float
    semantic_divergence: float
    composite_score: float
    content_hash: str
    matched_signatures: Tuple[str, ...]
    timestamp: str
    scan_version: str
    source: str = ""
    content_type: str = ""

    def to_dict(self) -> Dict:
        d = asdict(self)
        d["action"] = self.action.value
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, default=str)


# ---------------------------------------------------------------------------
# Stage 1 — Pattern Scanner
# ---------------------------------------------------------------------------

class PatternScanner:
    """
    Regex-based detection of known IPI signatures.

    Design notes:
      - Signatures are loaded from an external catalog (injection-patterns.md
        parsed into this structure). The regexes below are the mandatory
        built-in baseline.
      - Unicode normalization is applied before matching.
      - Each match contributes weighted mass to the pattern_score.
    """

    BUILTIN_SIGNATURES: List[Tuple[str, re.Pattern, float]] = [
        # (name, compiled_pattern, severity_weight)
        ("INSTRUCTION_OVERRIDE", re.compile(
            r"(ignore\s+(all\s+)?(previous|prior|earlier)\s+(instructions?|commands?|directives?)|"
            r"override\s+(previous|prior)\s+(instructions?|commands?)|"
            r"new\s+(instructions?|command|directive)\s*(is|:)|"
            r"you\s+(are\s+now|must\s+act\s+as)|"
            r"system\s*mode\s*(is|:)|"
            r"enter\s+(developer|admin|root|DAN|jailbreak)\s+mode)",
            re.IGNORECASE | re.MULTILINE
        ), 1.0),
        ("DELIMITER_CONFUSION", re.compile(
            r"(\n\n---\s*\n\s*(system|user|assistant|developer)\s*[:\-]|"
            r"```\s*\n\s*(system|user|assistant)|"
            r"<\|im_start\|>|<\|im_end\|>|<\|endoftext\|>|<\|endofmessage\|>|"
            r"\]\]>|<!\[CDATA\[|<?xml\s+version|\]\]\s*>|"
            r"\`\`\`\`\`)",
            re.IGNORECASE | re.MULTILINE
        ), 0.9),
        ("ROLE_SWITCH", re.compile(
            r"\b(system|user|assistant|developer)\s*[:\-]\s*\n",
            re.IGNORECASE | re.MULTILINE
        ), 0.7),
        ("TOOL_HIJACK", re.compile(
            r"(\{\s*\"tool\s*\"\s*:\s*\"|\{\s*\"function\s*\"\s*:\s*\"|"
            r"call\s+(the\s+)?(delete|remove|drop|exec|eval|shell)\s+(tool|function)|"
            r"send\s+(the\s+)?(api\s*key|token|secret|password|credential)\s+to)",
            re.IGNORECASE | re.MULTILINE
        ), 1.0),
        ("CONTEXT_ESCAPE", re.compile(
            r"(<script\b|javascript:|on\w+\s*=|&lt;script|"
            r"\x00|\x01|\x02|\x03|\x04|\x05|\x06|\x07|\x08|\x0b|\x0c|\x0e|\x0f)",
            re.IGNORECASE | re.MULTILINE
        ), 0.8),
    ]

    def __init__(
        self,
        signatures: Optional[List[Tuple[str, re.Pattern, float]]] = None,
        case_sensitive: bool = False,
        unicode_normalize: bool = True,
    ):
        self.signatures = signatures or list(self.BUILTIN_SIGNATURES)
        self.case_sensitive = case_sensitive
        self.unicode_normalize = unicode_normalize

    def _prepare(self, text: str) -> str:
        if self.unicode_normalize:
            text = unicodedata.normalize("NFKC", text)
        if not self.case_sensitive:
            text = text.lower()
        return text

    def scan(self, text: str) -> Tuple[float, List[str]]:
        """
        Returns (pattern_score ∈ [0.0, 1.0], matched_signature_names).

        Score calculation:
          - Sum severity weights of unique matched signatures.
          - Divide by total possible weight (sum of all signature weights).
          - Clamp to [0.0, 1.0].
        """
        prepared = self._prepare(text)
        matched: List[str] = []
        total_weight = sum(w for _, _, w in self.signatures)
        accumulated = 0.0

        for name, pattern, weight in self.signatures:
            if pattern.search(prepared):
                matched.append(name)
                accumulated += weight

        score = min(1.0, accumulated / total_weight) if total_weight > 0 else 0.0
        return score, matched


# ---------------------------------------------------------------------------
# Stage 2 — Entropy Analyzer
# ---------------------------------------------------------------------------

class EntropyAnalyzer:
    """
    Detects encoding tricks and obfuscation via character distribution analysis.

    Checks:
      - Shannon entropy over character and byte distributions
      - Homoglyph density (confusable Unicode characters)
      - Zero-width character presence
      - BiDi override characters
      - Mixed script detection
    """

    ZERO_WIDTH_CHARS = {
        "\u200B", "\u200C", "\u200D", "\u2060", "\uFEFF",
        "\u180E", "\u200E", "\u200F", "\u202A", "\u202B",
        "\u202C", "\u202D", "\u202E",
    }

    BIDI_OVERRIDES = {
        "\u202A", "\u202B", "\u202C", "\u202D", "\u202E",
        "\u2066", "\u2067", "\u2068", "\u2069",
    }

    HOMOGLYPH_RANGES = [
        (0x0430, 0x044F),   # Cyrillic range overlapping Latin visually
    ]

    def __init__(self, baseline_window: int = DEFAULT_BASELINE_WINDOW):
        self.baseline_window = baseline_window

    @staticmethod
    def _shannon_entropy(data: str) -> float:
        if not data:
            return 0.0
        freq: Dict[str, int] = {}
        for ch in data:
            freq[ch] = freq.get(ch, 0) + 1
        length = len(data)
        entropy = 0.0
        for count in freq.values():
            p = count / length
            entropy -= p * math.log2(p)
        return entropy

    @staticmethod
    def _byte_entropy(data: bytes) -> float:
        if not data:
            return 0.0
        freq: Dict[int, int] = {}
        for b in data:
            freq[b] = freq.get(b, 0) + 1
        length = len(data)
        entropy = 0.0
        for count in freq.values():
            p = count / length
            entropy -= p * math.log2(p)
        return entropy

    def _encoding_tricks_score(self, text: str) -> float:
        """Returns score ∈ [0.0, 1.0] based on presence of encoding trick indicators."""
        if not text:
            return 0.0

        checks = 0.0
        total_checks = 5.0

        # 1. Zero-width characters
        zw_count = sum(1 for ch in text if ch in self.ZERO_WIDTH_CHARS)
        if zw_count > 0:
            checks += min(1.0, zw_count / 5.0)

        # 2. BiDi overrides
        bidi_count = sum(1 for ch in text if ch in self.BIDI_OVERRIDES)
        if bidi_count > 0:
            checks += min(1.0, bidi_count / 3.0)

        # 3. Homoglyph density (naive: Cyrillic lookalikes in Latin text)
        cyrillic_count = sum(1 for ch in text if "\u0430" <= ch <= "\u044F")
        if cyrillic_count > 0:
            checks += min(1.0, cyrillic_count / 10.0)

        # 4. Mixed scripts
        scripts: set = set()
        for ch in text:
            script = unicodedata.name(ch, "UNKNOWN").split()[0]
            scripts.add(script)
        if len(scripts) > 2:
            checks += min(1.0, (len(scripts) - 2) / 5.0)

        # 5. Unusual byte entropy vs char entropy gap
        char_ent = self._shannon_entropy(text)
        byte_ent = self._byte_entropy(text.encode("utf-8"))
        gap = abs(char_ent - byte_ent)
        if gap > 1.5:
            checks += min(1.0, (gap - 1.5) / 2.0)

        return min(1.0, checks / total_checks)

    def analyze(self, text: str, expected_content_type: str = "text") -> float:
        """
        Returns entropy_score ∈ [0.0, 1.0].

        Higher score = more suspicious character-level distribution.
        """
        if not text:
            return 0.0

        char_entropy = self._shannon_entropy(text)
        max_entropy_for_size = math.log2(max(1, len(set(text))))
        normalized_char_entropy = char_entropy / max(1.0, max_entropy_for_size)

        encoding_score = self._encoding_tricks_score(text)

        # Weighted blend: encoding tricks are stronger signal than raw entropy
        score = (0.35 * normalized_char_entropy) + (0.65 * encoding_score)
        return round(min(1.0, max(0.0, score)), 4)


# ---------------------------------------------------------------------------
# Stage 3 — Semantic Shift Detector (PPL-W)
# ---------------------------------------------------------------------------

class SemanticShiftDetector:
    """
    Perplexity-windowed semantic shift detection.

    Computes embeddings for sliding windows of the incoming text and compares
    them to the task baseline embedding. Flags cosine divergence above threshold.

    If sentence-transformers is unavailable, the detector degrades gracefully
    and raises a warning. The caller is responsible for adjusting the composite
    score formula when semantic data is missing.
    """

    ADAPTIVE_THRESHOLDS = {
        "code_comments": 0.35,
        "api_response": 0.25,
        "log_content": 0.30,
        "pr_comment": 0.20,
        "file_content": 0.30,
        "default": 0.30,
    }

    def __init__(
        self,
        model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
        window_size: int = DEFAULT_WINDOW_SIZE,
        stride: int = DEFAULT_STRIDE,
    ):
        self.model_name = model_name
        self.window_size = window_size
        self.stride = stride
        self._model: Optional[SentenceTransformer] = None  # type: ignore
        self._baseline: Optional[np.ndarray] = None  # type: ignore
        self._available = HAS_ST and HAS_NUMPY

        if self._available:
            try:
                self._model = SentenceTransformer(model_name)
                logger.info("SemanticShiftDetector loaded model: %s", model_name)
            except Exception as exc:
                logger.warning("Failed to load embedding model: %s. Semantic scan degraded.", exc)
                self._available = False
        else:
            logger.warning("SemanticShiftDetector unavailable (missing sentence-transformers or numpy).")

    def register_baseline(self, baseline_text: str) -> None:
        """Register the task baseline from a known-safe description."""
        if not self._available or self._model is None:
            logger.warning("Baseline requested but semantic detector is unavailable.")
            return
        self._baseline = self._model.encode(baseline_text, convert_to_numpy=True)

    def _cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        """Compute cosine similarity between two vectors."""
        if not HAS_NUMPY:
            return 0.0
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))

    def detect(
        self,
        text: str,
        content_type: str = "default",
    ) -> Tuple[float, bool]:
        """
        Returns (semantic_divergence ∈ [0.0, 1.0], is_available).

        Divergence is computed as max window-level cosine distance from baseline.
        If no baseline is registered, falls back to a generic neutral comparison.
        """
        if not self._available or self._model is None or not HAS_NUMPY:
            return 0.0, False

        if not text:
            return 0.0, True

        threshold = self.ADAPTIVE_THRESHOLDS.get(content_type, self.ADAPTIVE_THRESHOLDS["default"])

        windows: List[str] = []
        for i in range(0, max(1, len(text) - self.window_size + 1), self.stride):
            windows.append(text[i:i + self.window_size])
        if not windows:
            windows = [text]

        if self._baseline is None:
            # No baseline yet; use a zero-vector fallback (will flag high divergence)
            self._baseline = np.zeros(self._model.encode(text[:64]).shape)

        max_divergence = 0.0
        for window in windows:
            if not window.strip():
                continue
            emb = self._model.encode(window, convert_to_numpy=True)
            sim = self._cosine_similarity(emb, self._baseline)
            divergence = 1.0 - max(0.0, min(1.0, sim))
            if divergence > max_divergence:
                max_divergence = divergence

        # Normalize: divergence above threshold maps into alarm range
        normalized = min(1.0, max_divergence / max(threshold, 0.01))
        return round(normalized, 4), True


# ---------------------------------------------------------------------------
# Composite Screener — Orchestrator
# ---------------------------------------------------------------------------

class IPIScreener:
    """
    Main entry point for the IPI defense pipeline.

    Usage:
        screener = IPIScreener()
        screener.register_baseline("Refactor the auth module to use OAuth2.")
        result = screener.screen(pr_comment_text, source="github/pr/42#comment-7", content_type="pr_comment")
    """

    def __init__(
        self,
        critical_threshold: float = DEFAULT_CRITICAL_THRESHOLD,
        warning_threshold: float = DEFAULT_WARNING_THRESHOLD,
        pattern_scanner: Optional[PatternScanner] = None,
        entropy_analyzer: Optional[EntropyAnalyzer] = None,
        semantic_detector: Optional[SemanticShiftDetector] = None,
    ):
        self.critical_threshold = critical_threshold
        self.warning_threshold = warning_threshold
        self.pattern = pattern_scanner or PatternScanner()
        self.entropy = entropy_analyzer or EntropyAnalyzer()
        self.semantic = semantic_detector or SemanticShiftDetector()
        self._quarantine_count = 0

    def register_baseline(self, baseline_text: str) -> None:
        """Register the session's task baseline for semantic comparison."""
        self.semantic.register_baseline(baseline_text)

    def _compute_hash(self, content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _quarantine_stub(self, content_hash: str, composite_score: float) -> str:
        return (
            f"[QUARANTINED: content_hash={content_hash} "
            f"reason=IPI_CRITICAL score={composite_score:.4f} "
            f"version={SCAN_VERSION}]"
        )

    def screen(
        self,
        content: str,
        source: str,
        content_type: str = "text",
    ) -> ScreeningResult:
        """
        Run the full 3-stage pipeline and return a deterministic screening result.
        """
        if content is None:
            content = ""

        content_hash = self._compute_hash(content)
        timestamp = datetime.now(timezone.utc).isoformat()

        # Stage 1: Pattern
        pattern_score, matched = self.pattern.scan(content)

        # Stage 2: Entropy
        entropy_score = self.entropy.analyze(content, content_type)

        # Stage 3: Semantic
        semantic_divergence, semantic_available = self.semantic.detect(content, content_type)

        # Composite score
        if semantic_available:
            composite = pattern_score * entropy_score * (1.0 + semantic_divergence)
        else:
            # Degraded mode: semantic unavailable
            composite = pattern_score * entropy_score

        composite = round(min(1.0, composite), 4)

        # Decision (deterministic — LLM has no vote)
        if composite > self.critical_threshold:
            action = Action.QUARANTINE
            tag = "[QUARANTINED]"
            self._quarantine_count += 1
            logger.critical(
                "IPI QUARANTINE source=%s score=%.4f signatures=%s",
                source, composite, matched,
            )
        elif composite > self.warning_threshold:
            action = Action.TAG_HIGH
            tag = "[EXTERNAL_UNTRUSTED_HIGH]"
            logger.warning(
                "IPI HIGH RISK source=%s score=%.4f signatures=%s",
                source, composite, matched,
            )
        else:
            action = Action.PASS
            tag = "[EXTERNAL_UNTRUSTED]"
            logger.info(
                "IPI PASS source=%s score=%.4f",
                source, composite,
            )

        result = ScreeningResult(
            action=action,
            tag=tag,
            pattern_score=pattern_score,
            entropy_score=entropy_score,
            semantic_divergence=semantic_divergence,
            composite_score=composite,
            content_hash=content_hash,
            matched_signatures=tuple(matched),
            timestamp=timestamp,
            scan_version=SCAN_VERSION,
            source=source,
            content_type=content_type,
        )

        # Immutable audit log entry
        self._write_audit_log(result)
        return result

    def _write_audit_log(self, result: ScreeningResult) -> None:
        """Append a single-line JSON audit entry. Override for structured logging integration."""
        # In production, route this to your immutable audit sink (e.g., append-only log store).
        audit_line = json.dumps({
            "event": "ipi_screen",
            "timestamp": result.timestamp,
            "scan_version": result.scan_version,
            "source": result.source,
            "content_type": result.content_type,
            "content_hash": result.content_hash,
            "pattern_score": result.pattern_score,
            "entropy_score": result.entropy_score,
            "semantic_divergence": result.semantic_divergence,
            "composite_score": result.composite_score,
            "action": result.action.value,
            "matched_signatures": list(result.matched_signatures),
        })
        logger.info("AUDIT | %s", audit_line)

    def get_context_payload(
        self,
        content: str,
        result: ScreeningResult,
    ) -> str:
        """
        Return the string that should actually be inserted into the LLM context.
        For quarantined content, this is the quarantine stub (original hidden).
        For all other content, the tag is prepended as a header.
        """
        if result.action == Action.QUARANTINE:
            return self._quarantine_stub(result.content_hash, result.composite_score)

        header = (
            f"{result.tag}\n"
            f"<!-- IPI-DEFENDER SCREENED | "
            f"score={result.composite_score:.4f} "
            f"sig_count={len(result.matched_signatures)} "
            f"hash={result.content_hash[:16]}… "
            f"time={result.timestamp} "
            f"ver={result.scan_version} -->\n"
        )
        return header + content

    @property
    def quarantine_count(self) -> int:
        return self._quarantine_count


# ---------------------------------------------------------------------------
# CLI / Standalone Example
# ---------------------------------------------------------------------------

def main() -> None:  # pragma: no cover
    import argparse

    parser = argparse.ArgumentParser(description="IPI Screener — standalone scan")
    parser.add_argument("file", nargs="?", help="Path to file to scan")
    parser.add_argument("--text", default="", help="Raw text to scan")
    parser.add_argument("--source", default="cli", help="Source identifier")
    parser.add_argument("--type", default="file_content", help="Content type")
    parser.add_argument("--baseline", default="", help="Task baseline text")
    parser.add_argument("--critical", type=float, default=DEFAULT_CRITICAL_THRESHOLD)
    parser.add_argument("--warning", type=float, default=DEFAULT_WARNING_THRESHOLD)
    args = parser.parse_args()

    content = args.text
    if args.file:
        content = Path(args.file).read_text(encoding="utf-8")
    if not content:
        print("No content provided. Use --text or provide a file path.")
        return

    screener = IPIScreener(
        critical_threshold=args.critical,
        warning_threshold=args.warning,
    )
    if args.baseline:
        screener.register_baseline(args.baseline)

    result = screener.screen(content, source=args.source, content_type=args.type)
    print(result.to_json())
    print("\n--- Context Payload ---")
    print(screener.get_context_payload(content, result))


if __name__ == "__main__":
    main()
