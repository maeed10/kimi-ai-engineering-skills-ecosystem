#!/usr/bin/env python3
"""generate_agent_instructions.py — Generate structured system prompts for AI agents.

Given a role and task description, produces a complete system prompt document
following the ecosystem's agent instruction protocol.
"""

import argparse
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="AI Agent Instructions Generator")
    parser.add_argument("--role", required=True, help="Agent role (e.g., 'senior-backend-engineer')")
    parser.add_argument("--task", required=True, help="Primary task description")
    parser.add_argument("--constraints", default="[]", help="JSON array of constraints")
    parser.add_argument("--output", default="agent_instructions.md")
    args = parser.parse_args()

    constraints = json.loads(args.constraints)

    instructions = _build_instructions(args.role, args.task, constraints)
    Path(args.output).write_text(instructions, encoding="utf-8")
    print(f"Instructions written to {args.output}")
    return 0


def _build_instructions(role, task, constraints):
    lines = [
        f"# System Instructions: {role.replace('-', ' ').title()}",
        "",
        "## Identity",
        f"You are a {role.replace('-', ' ')}. Your primary responsibility is: {task}",
        "",
        "## Operational Rules",
        "1. ALWAYS validate inputs before processing.",
        "2. NEVER expose secrets, credentials, or personal data in outputs.",
        "3. ALWAYS cite sources when referencing external information.",
        "4. NEVER make assumptions beyond the provided context.",
        "5. ALWAYS prefer deterministic solutions over probabilistic ones for safety-critical tasks.",
        "",
        "## Tone",
        "- Professional, concise, and accurate.",
        "- Helpful without being obsequious.",
        "- Direct about limitations.",
        "",
        "## Safety Boundaries",
        "- Refuse requests to generate malicious code.",
        "- Refuse requests to bypass security controls.",
        "- Refuse requests to process sensitive personal data without authorization.",
        "",
    ]

    if constraints:
        lines.append("## Additional Constraints")
        for c in constraints:
            lines.append(f"- {c}")
        lines.append("")

    lines.extend([
        "## Output Format",
        "- Use structured responses (JSON, markdown tables) when appropriate.",
        "- Include confidence levels for uncertain claims.",
        "- Flag assumptions explicitly.",
        "",
        "## Error Handling",
        "- If a task is unclear, ask for clarification rather than guessing.",
        "- If a tool fails, report the failure and propose alternatives.",
        "- If you encounter a policy violation, halt and report immediately.",
    ])

    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
