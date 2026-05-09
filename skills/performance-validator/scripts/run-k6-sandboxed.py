#!/usr/bin/env python3
"""Sandboxed wrapper for run-k6-loadtest.py."""
import os
import sys
from pathlib import Path

SBOX = Path(__file__).resolve().parent.parent.parent / "sandbox-executor" / "scripts" / "run-skill-sandboxed.py"
SKILL = "performance-validator"

args = [sys.executable, str(SBOX), "--skill", SKILL, "--network", "--", sys.executable, "run-k6-loadtest.py"] + sys.argv[1:]
os.execv(sys.executable, args)
