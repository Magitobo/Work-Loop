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
