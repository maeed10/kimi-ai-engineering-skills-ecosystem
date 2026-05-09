#!/usr/bin/env python3
"""
run-phase.py — Phase-Aware Workflow Runner for the Skill Orchestrator

Executes a single workflow phase by loading the correct skills,
reporting token budget before and after, and offering post-phase
integration hooks. Safe: only suggests, never executes destructive
operations without explicit confirmation.

Usage:
    python run-phase.py --phase understand [--hooks-enabled] [--dry-run]
    python run-phase.py --phase plan [--budget-target 15000]
    python run-phase.py --list-phases

Phases: understand, plan, assess, execute, deliver, remember
"""

import argparse
import sys
from enum import Enum
from dataclasses import dataclass, field
from typing import List, Optional

# --- Phase definitions ---

class Phase(str, Enum):
    UNDERSTAND = "understand"
    PLAN = "plan"
    ASSESS = "assess"
    EXECUTE = "execute"
    DELIVER = "deliver"
    REMEMBER = "remember"

@dataclass
class PhaseConfig:
    name: str
    skills: List[str]
    goal: str
    duration_turns: str
    prerequisite: str
    hooks_available: List[str] = field(default_factory=list)

PHASES = {
    Phase.UNDERSTAND: PhaseConfig(
        name="UNDERSTAND",
        skills=["graphify", "brownfield-intelligence"],
        goal="Build structural knowledge of the codebase",
        duration_turns="1-3",
        prerequisite="None",
        hooks_available=["graphify->brownfield"],
    ),
    Phase.PLAN: PhaseConfig(
        name="PLAN",
        skills=["architecture-design", "boundary-enforcer"],
        goal="Produce design + constraint check",
        duration_turns="2-4",
        prerequisite="PLAN.md or AGENTS.md exists",
        hooks_available=["architecture->boundary"],
    ),
    Phase.ASSESS: PhaseConfig(
        name="ASSESS",
        skills=["blast-radius-calculator"],
        goal="Calculate impact of planned changes",
        duration_turns="1",
        prerequisite="Dependency graph indexed (run UNDERSTAND first)",
        hooks_available=["blast-radius->code-tester"],
    ),
    Phase.EXECUTE: PhaseConfig(
        name="EXECUTE",
        skills=["code-tester"],
        goal="Generate/validate tests",
        duration_turns="2-5",
        prerequisite="Source-under-test loaded",
        hooks_available=["code-tester->style"],
    ),
    Phase.DELIVER: PhaseConfig(
        name="DELIVER",
        skills=["style-enforcer"],
        goal="Commit + review response",
        duration_turns="1-2",
        prerequisite="Git diff loaded",
        hooks_available=[],
    ),
    Phase.REMEMBER: PhaseConfig(
        name="REMEMBER",
        skills=["obsidian-setup"],
        goal="Save session to vault",
        duration_turns="1",
        prerequisite="Vault path configured",
        hooks_available=[],
    ),
}

# --- Skill token estimates (must match SKILL.md) ---

SKILL_TOKENS = {
    "graphify": 7200,
    "obsidian-setup": 7600,
    "brownfield-intelligence": 8400,
    "architecture-design": 4900,
    "blast-radius-calculator": 5600,
    "boundary-enforcer": 5500,
    "code-tester": 5800,
    "address-pr-comments": 6200,
    "style-enforcer": 6200,
    "skill-orchestrator": 5600,
}

# --- Budget constants ---

CONTEXT_LIMIT = 262100
SYSTEM_OVERHEAD = 5000
METADATA_RESERVE = 1500
BUDGET_CEILING = 25000
BUDGET_TARGET = 18000

# --- Reporter ---

class BudgetReporter:
    def __init__(self, budget_target: int = BUDGET_TARGET):
        self.budget_target = budget_target
        self.running_total = 0  # Would be loaded from session state

    def report(self, phase: PhaseConfig, active_hooks: Optional[List[str]] = None):
        tokens = [SKILL_TOKENS.get(s, 6000) for s in phase.skills]
        phase_total = sum(tokens)
        proposed = self.running_total + phase_total + SYSTEM_OVERHEAD + METADATA_RESERVE

        print("=" * 60)
        print(f"  SKILL ORCHESTRATOR — Phase Runner")
        print("=" * 60)
        print(f"  Phase      : {phase.name}")
        print(f"  Goal       : {phase.goal}")
        print(f"  Duration   : {phase.duration_turns} turns")
        print(f"  Prereq     : {phase.prerequisite}")
        print("-" * 60)
        print(f"  Skills     : {', '.join(phase.skills)}")
        for s in phase.skills:
            t = SKILL_TOKENS.get(s, 6000)
            print(f"    - {s:<30} ~{t:,} tokens")
        print(f"  Phase total: ~{phase_total:,} tokens")
        print("-" * 60)
        print(f"  BUDGET REPORT")
        print(f"    Current usage : {self.running_total:,} tokens")
        print(f"    Proposed total: {proposed:,} tokens")
        print(f"    Ceiling       : {BUDGET_CEILING:,} tokens")
        print(f"    Target        : {self.budget_target:,} tokens")
        print(f"    Status        : {'OK' if proposed <= self.budget_target else 'WARNING' if proposed <= BUDGET_CEILING else 'EXCEEDS CEILING'}")
        print("-" * 60)

        if phase.hooks_available:
            print(f"  Hooks available:")
            for h in phase.hooks_available:
                print(f"    - {h} (disabled by default; use --hooks-enabled to offer)")
        else:
            print(f"  Hooks available: none")
        print("=" * 60)

        if active_hooks:
            print(f"\n  Hooks to offer: {', '.join(active_hooks)}")
            print("  (Hooks are suggestions only — user must confirm each)")

        # Safety checks
        if proposed > BUDGET_CEILING:
            print(f"\n  [SAFETY] Proposed total exceeds ceiling. Options:")
            print(f"    A) Reduce to 1 skill and offer second as post-phase hook")
            print(f"    B) Request user confirmation to proceed")
            print(f"    C) Split into sub-phases")
            return False

        return True

# --- Main ---

def main():
    parser = argparse.ArgumentParser(
        description="Execute a workflow phase for the Skill Orchestrator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run-phase.py --phase understand
  python run-phase.py --phase assess --hooks-enabled --dry-run
  python run-phase.py --list-phases
        """,
    )
    parser.add_argument("--phase", type=str, choices=[p.value for p in Phase],
                        help="Workflow phase to execute")
    parser.add_argument("--hooks-enabled", action="store_true",
                        help="Offer integration hooks after phase completes")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report only; do not suggest activation")
    parser.add_argument("--budget-target", type=int, default=BUDGET_TARGET,
                        help=f"Custom budget target in tokens (default: {BUDGET_TARGET})")
    parser.add_argument("--list-phases", action="store_true",
                        help="List all available phases and exit")

    args = parser.parse_args()

    if args.list_phases:
        print("Available phases:")
        for p, cfg in PHASES.items():
            print(f"  {p.value:<12} — {cfg.goal} ({cfg.duration_turns} turns)")
        sys.exit(0)

    if not args.phase:
        parser.error("--phase is required (unless using --list-phases)")

    phase_enum = Phase(args.phase)
    config = PHASES[phase_enum]

    reporter = BudgetReporter(budget_target=args.budget_target)
    hooks = config.hooks_available if args.hooks_enabled else []

    print(f"\n[Phase Runner] Preparing phase: {config.name}\n")

    can_proceed = reporter.report(config, active_hooks=hooks if hooks else None)

    if args.dry_run:
        print("\n  [DRY RUN] No activation suggested. Report complete.")
        sys.exit(0)

    if can_proceed:
        print(f"\n  Phase '{config.name}' is ready. To activate:")
        for s in config.skills:
            print(f"    /activate {s}")
        if hooks:
            print(f"\n  After phase completes, hooks will be offered:")
            for h in hooks:
                print(f"    - {h}")
    else:
        print(f"\n  Phase '{config.name}' blocked by budget ceiling.")
        print("  Resolve budget conflict before proceeding.")
        sys.exit(1)

if __name__ == "__main__":
    main()
