# E2E test background dispatcher.
#
# After the main test suite completes, spawns test_e2e.py as a detached
# process so the user gets immediate feedback while e2e tests run in
# the background.  Results are surfaced at the top of the next test run.

import json
import os
import subprocess
import sys
import time
from pathlib import Path

_E2E_LOG = "e2e_results.log"
_E2E_STATE = "e2e_state.json"


def pytest_configure(config):
    """Report stale e2e results at the top of every test run."""
    if os.environ.get("PYTEST_E2E"):
        return  # We ARE the e2e process

    state_file = Path(_E2E_STATE)
    if not state_file.exists():
        return

    try:
        state = json.loads(state_file.read_text())
    except (json.JSONDecodeError, OSError):
        return

    pid = state.get("pid")
    if pid:
        try:
            os.kill(pid, 0)
            return  # Still running
        except OSError:
            pass  # Process finished

    # Process is done — read results from the log
    log_file = Path(_E2E_LOG)
    if not log_file.exists():
        return

    import re
    content = log_file.read_text()
    m = re.search(
        r"(\d+)\s+passed,\s*(\d+)\s+failed?\s*,\s*(\d+)\s+error",
        content,
        re.IGNORECASE,
    )
    if not m:
        m = re.search(
            r"(\d+)\s+passed,\s*(\d+)\s+failed?\s*($|,)",
            content,
            re.IGNORECASE,
        )

    passed = int(m.group(1)) if m else "?"
    failed = int(m.group(2)) if m else "?"
    errors = int(m.group(3)) if m and m.lastindex >= 3 else 0

    ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(state.get("ts", 0)))
    status = "FAIL" if failed or errors else "OK"
    print(f"\n{'='*60}")
    print(f"  E2E Results ({ts}): {passed} passed, {failed} failed, {errors} errors")
    if failed or errors:
        print(f"  {status} — details: {_E2E_LOG}")
    print(f"{'='*60}\n")


def pytest_sessionfinish(session, exitstatus):
    """Spawn e2e tests in a background process after the main suite."""
    if os.environ.get("PYTEST_E2E"):
        return  # Don't recurse

    e2e_cmd = [sys.executable, "-m", "pytest", "test_e2e.py", "-v", "--tb=short"]
    with open(_E2E_LOG, "w") as log:
        proc = subprocess.Popen(
            e2e_cmd,
            stdout=log,
            stderr=subprocess.STDOUT,
            env={**os.environ, "PYTEST_E2E": "1"},
        )

    state = {"ts": time.time(), "pid": proc.pid}
    Path(_E2E_STATE).write_text(json.dumps(state))
    print(f"\n[background] E2E tests dispatched (PID {proc.pid}) -> {_E2E_LOG}")
