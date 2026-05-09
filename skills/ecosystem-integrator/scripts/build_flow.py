#!/usr/bin/env python3
"""
Builds the interactive flow path based on user choices.

Maps user selections from each step to the next set of questions/skills.
Ensures the flow is always driven by user input, never automated.

Usage:
    python build_flow.py --step 0 --choice "1"
    python build_flow.py --step 2 --skills "dev-code-generator,dev-test-automation"
    python build_flow.py --step 5 --action "generate_code" --language python
"""

import argparse
import json
import sys
from typing import Dict, List, Optional

# Flow definition: each step maps to a function that returns the next step
FLOW_STEPS = {
    0: {
        "name": "Task Discovery",
        "question": "What would you like to do today?",
        "choices": {
            "1": {"label": "Start a coding task", "next_step": 1, "context": "coding"},
            "2": {"label": "Set up CI/CD", "next_step": 1, "context": "cicd"},
            "3": {"label": "Design API or database", "next_step": 1, "context": "design"},
            "4": {"label": "Debug or investigate", "next_step": 1, "context": "debug"},
            "5": {"label": "Security scan", "next_step": 1, "context": "security"},
            "6": {"label": "Performance profiling", "next_step": 1, "context": "performance"},
            "7": {"label": "Infrastructure", "next_step": 1, "context": "infrastructure"},
            "8": {"label": "Observability", "next_step": 1, "context": "observability"},
            "9": {"label": "Documentation", "next_step": 1, "context": "docs"},
            "10": {"label": "Check health", "next_step": 7, "context": "health"},
            "11": {"label": "Manage dependencies", "next_step": 1, "context": "dependencies"},
            "12": {"label": "Other", "next_step": 1, "context": "custom"},
        }
    },
    1: {
        "name": "Task Clarification",
        "question": "Let me ask a few questions to narrow down the right skills.",
        "next_step": 2,  # Goes to recommendation step after clarification
    },
    2: {
        "name": "Skill Recommendation",
        "question": "Based on your answers, here are my recommendations:",
        "next_step": 3,  # Safety configuration after user picks skills
    },
    3: {
        "name": "Safety Configuration",
        "question": "Please review the safety configuration:",
        "choices": {
            "yes": {"label": "Proceed", "next_step": 4},
            "change": {"label": "Customize", "next_step": 3},  # Loop back
            "strict": {"label": "Maximum security", "next_step": 4},
        }
    },
    4: {
        "name": "Skill Loading",
        "question": "Loading skills one at a time. Confirm each:",
        "next_step": 5,  # Execute after all confirmed
    },
    5: {
        "name": "Task Execution",
        "question": "Skills are active. What would you like to do?",
        "choices": {
            "execute": {"label": "Run primary action", "next_step": 6},
            "review": {"label": "Review loaded skills", "next_step": 5},
            "add": {"label": "Load more skills", "next_step": 2},
            "done": {"label": "End session", "next_step": 7},
        }
    },
    6: {
        "name": "Phase Transition",
        "question": "Do you want to proceed to the next phase?",
        "choices": {
            "yes": {"label": "Yes", "next_step": 5},
            "no": {"label": "Stay here", "next_step": 5},
            "customize": {"label": "Customize", "next_step": 4},
        }
    },
    7: {
        "name": "Session End",
        "question": "Session complete. What next?",
        "choices": {
            "save": {"label": "Save and exit", "next_step": None},
            "continue": {"label": "New task", "next_step": 0},
            "log": {"label": "View attestation log", "next_step": 7},
            "export": {"label": "Export report", "next_step": 7},
        }
    },
}


def get_step(step_num: int) -> Dict:
    """Get the step definition."""
    return FLOW_STEPS.get(step_num, {"name": "Unknown", "question": "Invalid step", "next_step": 0})


def build_flow_path(choices: List[Dict]) -> List[Dict]:
    """Build the flow path from a series of user choices."""
    path = []
    current_step = 0

    for choice in choices:
        step_def = get_step(current_step)
        path.append({
            "step": current_step,
            "name": step_def["name"],
            "question": step_def["question"],
            "user_choice": choice,
        })

        # Determine next step
        if "choices" in step_def and choice.get("value") in step_def["choices"]:
            next_step = step_def["choices"][choice["value"]].get("next_step", current_step + 1)
        elif "next_step" in step_def:
            next_step = step_def["next_step"]
        else:
            next_step = current_step + 1

        if next_step is None:
            break  # End of flow
        current_step = next_step

    return path


def format_flow_prompt(step_num: int, context: Optional[str] = None) -> str:
    """Format the interactive prompt for a given step."""
    step = get_step(step_num)
    lines = [
        f"",
        f"[Step {step_num}: {step['name']}]",
        f"",
        f"{step['question']}",
        f"",
    ]

    if "choices" in step:
        for key, choice in step["choices"].items():
            lines.append(f"  [{key}] {choice['label']}")
        lines.append("")
        lines.append("Enter your choice: _")

    if context:
        lines.append(f"\n[Context: {context}]")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Build interactive flow")
    parser.add_argument("--step", "-s", type=int, default=0, help="Current step number")
    parser.add_argument("--choice", "-c", help="User's choice at this step")
    parser.add_argument("--context", "-x", help="Additional context (language, framework, etc.)")
    parser.add_argument("--json", "-j", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    # Build a path from the single choice provided
    if args.choice:
        path = build_flow_path([{"value": args.choice, "context": args.context}])
    else:
        # Just format the prompt for the current step
        prompt = format_flow_prompt(args.step, args.context)
        if args.json:
            step_def = get_step(args.step)
            print(json.dumps({
                "step": args.step,
                "name": step_def["name"],
                "question": step_def["question"],
                "choices": step_def.get("choices", {}),
                "prompt": prompt,
            }, indent=2))
        else:
            print(prompt)
        return 0

    if args.json:
        print(json.dumps(path, indent=2))
    else:
        for entry in path:
            print(f"Step {entry['step']}: {entry['name']} — {entry['user_choice']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
