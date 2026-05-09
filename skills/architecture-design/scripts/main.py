#!/usr/bin/env python3
"""Architecture Design — generate architecture recommendations with weighted scoring."""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Generate architecture recommendations with weighted scoring."
    )
    parser.add_argument("--requirements", required=True, help="Path to requirements text file")
    parser.add_argument("--output", default=".", help="Output directory for design artifacts")
    parser.add_argument("--use-llm", action="store_true", help="Use external LLM for reasoning")
    parser.add_argument(
        "--attributes",
        default="performance,security,maintainability,scalability,cost,operability",
        help="Comma-separated quality attributes",
    )
    return parser.parse_args()


def _call_llm(prompt: str) -> str:
    """Call an external LLM API using environment variables for configuration."""
    api_key = os.environ.get("LLM_API_KEY")
    base_url = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1")
    model = os.environ.get("LLM_MODEL", "gpt-4")

    if not api_key:
        return "[LLM skipped: LLM_API_KEY not set]"

    try:
        import requests
        resp = requests.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
            },
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except Exception as exc:
        return f"[LLM error: {exc}]"


def generate_alternatives(requirements: str, use_llm: bool) -> list[dict[str, Any]]:
    """Generate architectural alternatives including status quo."""
    if use_llm:
        prompt = (
            f"Given the following requirements, propose 3 architectural alternatives "
            f"including a 'status quo / do nothing' option. Return ONLY a JSON list of objects "
            f"with keys: name, description, pros (list), cons (list).\n\nRequirements:\n{requirements}"
        )
        llm_response = _call_llm(prompt)
        try:
            # Attempt to extract JSON from markdown code blocks if present
            raw = llm_response
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0]
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0]
            alts = json.loads(raw.strip())
            if isinstance(alts, list) and len(alts) >= 2:
                return alts
        except Exception:
            pass

    # Fallback deterministic alternatives
    return [
        {
            "name": "Status Quo",
            "description": "Keep the current architecture unchanged.",
            "pros": ["Zero migration cost", "No learning curve", "Proven stability"],
            "cons": ["Tech debt accumulates", "May not meet new requirements"],
        },
        {
            "name": "Modular Monolith",
            "description": "Decompose into well-bounded modules within a single deployable unit.",
            "pros": ["Lower operational complexity", "Easier testing", "Faster refactoring"],
            "cons": ["Limited independent scalability", "Tight coupling risk if boundaries blur"],
        },
        {
            "name": "Microservices",
            "description": "Split into independently deployable services around DDD bounded contexts.",
            "pros": ["Independent scaling", "Polyglot persistence", "Team autonomy"],
            "cons": ["High operational complexity", "Network latency", "Distributed debugging"],
        },
    ]


def score_alternatives(
    alternatives: list[dict[str, Any]],
    attributes: list[str],
    use_llm: bool,
    requirements: str,
) -> dict[str, Any]:
    """Score each alternative against quality attributes with equal default weights."""
    weights = {attr: round(1.0 / len(attributes), 4) for attr in attributes}

    if use_llm:
        prompt = (
            f"Score these architectural alternatives against {', '.join(attributes)}. "
            f"Return ONLY a JSON object mapping alternative names to attribute scores (1-10).\n"
            f"Requirements: {requirements}\n"
            f"Alternatives: {json.dumps([a['name'] for a in alternatives])}"
        )
        llm_response = _call_llm(prompt)
        try:
            raw = llm_response
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0]
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0]
            scores = json.loads(raw.strip())
        except Exception:
            scores = {}
    else:
        scores = {}

    matrix = []
    for alt in alternatives:
        row = {"alternative": alt["name"]}
        total = 0.0
        for attr in attributes:
            if scores and alt["name"] in scores and attr in scores[alt["name"]]:
                val = float(scores[alt["name"]][attr])
            else:
                # Deterministic heuristic scoring based on name keywords
                val = _heuristic_score(alt["name"], attr)
            row[attr] = val
            total += val * weights[attr]
        row["weighted_score"] = round(total, 2)
        matrix.append(row)

    # Sort by weighted score descending
    matrix.sort(key=lambda r: r["weighted_score"], reverse=True)
    return {"weights": weights, "matrix": matrix}


def _heuristic_score(alt_name: str, attribute: str) -> float:
    """Generate a simple heuristic score when LLM is unavailable."""
    name = alt_name.lower()
    attr = attribute.lower()
    if attr == "cost" and "status quo" in name:
        return 9.0
    if attr == "scalability" and "microservice" in name:
        return 9.0
    if attr == "maintainability" and "monolith" in name:
        return 8.0
    if attr == "security" and "status quo" in name:
        return 7.0
    if attr == "operability" and "microservice" in name:
        return 4.0
    return 6.0


def generate_adr(
    requirements: str,
    alternatives: list[dict[str, Any]],
    scoring: dict[str, Any],
) -> str:
    """Generate a MADR-style Architecture Decision Record."""
    winner = scoring["matrix"][0]["alternative"] if scoring["matrix"] else "Undetermined"
    lines = [
        "# ADR-0001: Architecture Recommendation",
        "",
        "## Status",
        "Proposed",
        "",
        "## Context",
        requirements,
        "",
        "## Decision",
        f"Recommended alternative: **{winner}**",
        "",
        "## Consequences",
        "- Positive: aligned with highest weighted score across quality attributes.",
        "- Negative: trade-offs documented in scoring matrix.",
        "",
        "## Options Considered",
        "| Option | Pros | Cons |",
        "|--------|------|------|",
    ]
    for alt in alternatives:
        pros = "; ".join(alt.get("pros", []))
        cons = "; ".join(alt.get("cons", []))
        lines.append(f"| {alt['name']} | {pros} | {cons} |")
    lines.append("")
    lines.append("## Scoring Matrix")
    lines.append("")
    headers = ["Alternative"] + list(scoring["weights"].keys()) + ["Weighted Score"]
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
    for row in scoring["matrix"]:
        cells = [row["alternative"]] + [str(row.get(k, "")) for k in list(scoring["weights"].keys())] + [str(row["weighted_score"])]
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    """Main entry point."""
    args = parse_args()
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    req_path = Path(args.requirements)
    if not req_path.exists():
        print(json.dumps({"success": False, "error": f"Requirements file not found: {args.requirements}"}), file=sys.stderr)
        return 1

    requirements_text = req_path.read_text(encoding="utf-8")
    attributes = [a.strip() for a in args.attributes.split(",") if a.strip()]

    alternatives = generate_alternatives(requirements_text, args.use_llm)
    scoring = score_alternatives(alternatives, attributes, args.use_llm, requirements_text)
    adr_text = generate_adr(requirements_text, alternatives, scoring)

    report = {
        "success": True,
        "requirements_summary": requirements_text[:500],
        "alternatives": alternatives,
        "scoring": scoring,
        "adr_path": str(output_dir / "adr.md"),
    }

    (output_dir / "adr.md").write_text(adr_text, encoding="utf-8")
    (output_dir / "architecture_design.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
