#!/usr/bin/env python3
"""Sandboxed wrapper for run-chaos.py."""
import os
import sys
from pathlib import Path

SBOX = Path(__file__).resolve().parent.parent.parent / "sandbox-executor" / "scripts" / "run-skill-sandboxed.py"
SKILL = "resilience-tester"

args = [sys.executable, str(SBOX), "--skill", SKILL, "--network", "--", sys.executable, "run-chaos.py"] + sys.argv[1:]
os.execv(sys.executable, args)
