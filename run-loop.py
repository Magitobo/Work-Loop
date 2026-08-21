#!/usr/bin/env python3
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path

from workloop.config import load_config
from workloop.constants import *
from workloop.utils import _is_data_row, _ts, _run
from workloop.harness import Harness, ClaudeHarness, OpenCodeHarness
from workloop.core import WorkLoop

def main() -> None:
    script_dir = Path(__file__).parent

    if len(sys.argv) > 1 and sys.argv[1] == "--init-vault":
        if len(sys.argv) < 3:
            print("Usage: run-loop.py --init-vault <vault_path_or_work_dir>")
            sys.exit(1)
        target = Path(sys.argv[2]).resolve()
        if (target / ".obsidian").exists() or target.name in ("02-Work-Loop-Items", "Work-Loop-Items"):
            work_dir = target if target.name.endswith("-Items") else target / "02-Work-Loop-Items"
            vault_dir = target if not target.name.endswith("-Items") else target.parent
        else:
            work_dir = target / "02-Work-Loop-Items"
            vault_dir = target
        from workloop.scaffold import scaffold_vault
        res = scaffold_vault(work_dir, script_dir, vault_dir=vault_dir)
        print(f"Vault initialized at: {vault_dir}")
        for p in res.get('created', []):
            print(f"  Created: {p}")
        for p in res.get('updated', []):
            print(f"  Updated: {p}")
        return

    config_path = script_dir / "config.json"
    if not config_path.exists():
        home_work = Path.home() / "MyNotebook" / "Work-Loop-Items"
        if home_work.exists():
            config_path = script_dir / "config.json"
    cfg = load_config(config_path)
    wl = WorkLoop(cfg, script_dir=script_dir)
    wl.run()

if __name__ == "__main__":
    main()
