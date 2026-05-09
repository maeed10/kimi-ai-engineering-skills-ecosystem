#!/usr/bin/env python3
"""Sandboxed wrapper for run-sast.py."""
import os
import sys
from pathlib import Path

SBOX = Path(__file__).resolve().parent.parent.parent / "sandbox-executor" / "scripts" / "run-skill-sandboxed.py"
SKILL = "security-auditor"

args = [sys.executable, str(SBOX), "--skill", SKILL, "--network", "--", sys.executable, "run-sast.py"] + sys.argv[1:]
os.execv(sys.executable, args)
