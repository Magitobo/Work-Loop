#!/usr/bin/env python3
"""Stub aggregation script for Work-Loop unit tests.
Usage: stub_aggregate.py <run_dir>
Writes aggregated.txt to run_dir. Exits 0 normally, 1 if --fail flag in argv."""
import sys
import os
from pathlib import Path

run_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
should_fail = "--fail" in sys.argv

(run_dir / "aggregated.txt").write_text("stub aggregation output\n")
sys.exit(1 if should_fail else 0)
