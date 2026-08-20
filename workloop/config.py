import json
import sys
from pathlib import Path


def load_config(config_path: Path) -> dict:
    """Read config.json, validate required keys, fail fast with clear error."""
    if not config_path.exists():
        print(f"ERROR: config.json not found at {config_path}")
        print("Create one from config.json.example and update work_dir / harness settings.")
        sys.exit(1)
    try:
        with open(config_path, 'r') as f:
            cfg = json.load(f)
    except json.JSONDecodeError as e:
        print(f"ERROR: config.json is not valid JSON: {e}")
        sys.exit(1)
    # Validate required keys
    for key in ('work_dir', 'harness'):
        if key not in cfg:
            print(f"ERROR: config.json missing required key: '{key}'")
            sys.exit(1)
    harness = cfg.get('harness', {})
    if 'type' not in harness:
        print("ERROR: config.json 'harness' missing required key: 'type'")
        sys.exit(1)
    if harness['type'] not in ('claude', 'opencode'):
        print(f"ERROR: harness.type must be 'claude' or 'opencode', got: {harness['type']!r}")
        sys.exit(1)
    return cfg


