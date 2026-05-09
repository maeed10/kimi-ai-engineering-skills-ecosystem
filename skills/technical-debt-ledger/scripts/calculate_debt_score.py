#!/usr/bin/env python3
"""
calculate_debt_score.py

Compute composite cost-of-delay scores for technical debt items in a ledger file.

Usage:
    python3 calculate_debt_score.py ledger.yml --output ledger_scored.yml
    python3 calculate_debt_score.py ledger.yml --output ledger_scored.yml --dry-run

Reads a YAML ledger of debt entries, computes cost_of_delay for each open item
using the weighted scoring model, and writes the updated ledger.
"""

import argparse
import math
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    print("error: PyYAML required. Install: pip install pyyaml", file=sys.stderr)
    sys.exit(1)

# ---- Scoring Tables ---------------------------------------------------------

REACH_TABLE = [
    (0, 1),    # 0 call-sites
    (3, 2),    # 1-2
    (6, 4),    # 3-5
    (11, 6),   # 6-10
    (21, 8),   # 11-20
    (51, 10),  # 21-50
]

VOLATILITY_TABLE = [
    (0, 1),    # 0-1 commits
    (2, 3),    # 2-5
    (6, 5),    # 6-15
    (16, 7),   # 16-30
    (31, 9),   # 31-50
]

GROWTH_TABLE = [
    (-20, 1),  # improving
    (-5, 2),   # stable-negative
    (5, 3),    # flat
    (16, 5),   # growing
    (31, 7),   # accelerating
]

ALIGNMENT_PENALTY = {
    1: 10,   # core domain -> highest penalty
    2: 7,
    3: 5,
    4: 3,
    5: 1,    # peripheral -> lowest penalty
}

WEIGHTS = {
    "reach": 0.30,
    "volatility": 0.25,
    "growth": 0.25,
    "alignment": 0.20,
}

# ---- Tier Lookup ------------------------------------------------------------

def lookup_tier(value: int, table: list[tuple[int, int]]) -> int:
    """Return the score for the first threshold > value; default to max."""
    for threshold, score in table:
        if value < threshold:
            return score
    return table[-1][1] if table else 1


def reach_score(blast_radius: int) -> int:
    return lookup_tier(blast_radius, REACH_TABLE)


def volatility_score(change_frequency: int) -> int:
    return lookup_tier(change_frequency, VOLATILITY_TABLE)


def growth_score(complexity_trend: int) -> int:
    """complexity_trend is integer % change."""
    for threshold, score in GROWTH_TABLE:
        if complexity_trend <= threshold:
            return score
    return 10  # >30% -> exploding


def alignment_penalty_score(alignment: int) -> int:
    return ALIGNMENT_PENALTY.get(alignment, 5)

# ---- Composite Score --------------------------------------------------------

def compute_raw_product(entry: dict[str, Any]) -> float:
    """Compute the weighted product of the four factors."""
    reach = reach_score(entry.get("blast_radius", 0))
    volatility = volatility_score(entry.get("change_frequency", 0))
    growth = growth_score(entry.get("complexity_trend", 0))
    alignment = alignment_penalty_score(entry.get("alignment", 3))

    # Weighted geometric mean as product of powers
    product = (
        math.pow(reach, WEIGHTS["reach"])
        * math.pow(volatility, WEIGHTS["volatility"])
        * math.pow(growth, WEIGHTS["growth"])
        * math.pow(alignment, WEIGHTS["alignment"])
    )

    entry["_debug_factors"] = {
        "reach": reach,
        "volatility": volatility,
        "growth": growth,
        "alignment_penalty": alignment,
        "raw_product": round(product, 4),
    }
    return product


def normalize(product: float, ledger_max: float) -> float:
    """Map raw product to 0..1 range using observed ledger maximum."""
    if ledger_max <= 1.0:
        return 0.5
    return min(1.0, max(0.0, (product - 1.0) / (ledger_max - 1.0)))


def cost_of_delay(entry: dict[str, Any], ledger_max: float) -> float:
    """Compute final 1.0-10.0 cost-of-delay score."""
    raw = compute_raw_product(entry)
    norm = normalize(raw, ledger_max)
    return round(1.0 + 9.0 * norm, 2)

# ---- Ledger Processing ------------------------------------------------------

def load_ledger(path: Path) -> list[dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if data is None:
        return []
    if isinstance(data, dict) and "items" in data:
        return data["items"]
    return list(data)


def score_ledger(items: list[dict[str, Any]], dry_run: bool = False) -> list[dict[str, Any]]:
    """Compute cost_of_delay for all open items."""
    # Compute raw products for open items to establish normalization baseline
    open_items = [it for it in items if it.get("status", "open") == "open"]

    raw_products = []
    for item in open_items:
        raw = compute_raw_product(item)
        raw_products.append(raw)

    # Use 95th percentile as ledger_max for normalization
    if raw_products:
        sorted_raws = sorted(raw_products)
        idx = int(math.ceil(0.95 * len(sorted_raws))) - 1
        idx = max(0, idx)
        ledger_max = sorted_raws[idx]
    else:
        ledger_max = 10.0  # default theoretical max

    if dry_run:
        print(f"# Calibration: ledger_max (95th pct) = {ledger_max:.4f}")
        print(f"# Open items scored: {len(open_items)}")
        print("")

    # Apply scores
    for item in items:
        if item.get("status") == "open":
            cod = cost_of_delay(item, ledger_max)
            item["cost_of_delay"] = cod
            if dry_run:
                factors = item.pop("_debug_factors", {})
                print(
                    f"{item.get('id', '?')}  CoD={cod:>5.2f}  "
                    f"R={factors.get('reach', '?')} V={factors.get('volatility', '?')} "
                    f"G={factors.get('growth', '?')} A={factors.get('alignment_penalty', '?')}  "
                    f"raw={factors.get('raw_product', '?'):.2f}  "
                    f"{item.get('files', ['?'])[0] if item.get('files') else '?'!s}"
                )
        elif "_debug_factors" in item:
            del item["_debug_factors"]

    return items


def save_ledger(items: list[dict[str, Any]], path: Path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(items, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

# ---- CLI --------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compute cost-of-delay scores for a technical debt ledger."
    )
    parser.add_argument("ledger", type=Path, help="Path to ledger YAML file")
    parser.add_argument("-o", "--output", type=Path, default=None, help="Output path")
    parser.add_argument(
        "--dry-run", action="store_true", help="Print scores without writing file"
    )
    args = parser.parse_args()

    if not args.ledger.exists():
        print(f"error: ledger not found: {args.ledger}", file=sys.stderr)
        return 1

    items = load_ledger(args.ledger)
    items = score_ledger(items, dry_run=args.dry_run)

    if args.dry_run:
        return 0

    out_path = args.output or args.ledger
    save_ledger(items, out_path)
    print(f"Scored {len([i for i in items if i.get('status') == 'open'])} open items -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
