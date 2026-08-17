#!/usr/bin/env python3
"""Work-loop processor: runs Claude or OpenCode on ready work items, local or remote."""

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


# Harness base class
class Harness(ABC):
    """Abstract base for AI harness backends (Claude, OpenCode, etc.)."""

    @abstractmethod
    def run(self, prompt: str, budget: float, cwd: str | None, item_id: str | None, log_file: Path) -> int:
        """Run the harness with the given prompt. Returns exit code."""
        ...

    @abstractmethod
    def launcher_script(self, item_id: str, ts_str: str, budget: float, mode: str, work_dir: str | None, remote_work_dir: str) -> str:
        """Generate a bash launcher script for remote dispatch."""
        ...

    @abstractmethod
    def agent_dir_name(self) -> str:
        """Return the agent directory name (e.g. '.claude' or '.opencode')."""
        ...

    @abstractmethod
    def cost_injection(self, work_dir: Path, item_id: str, started_after: str = '') -> None:
        """Append cost info to CONVERSATION.md after a successful run."""
        ...


class ClaudeHarness(Harness):
    """Claude CLI harness."""

    def run(self, prompt: str, budget: float, cwd: str | None, item_id: str | None, log_file: Path) -> int:
        debug_file = log_file.with_suffix('.debug')
        cmd = [
            "claude", "--print",
            "--permission-mode", "auto",
            "--max-budget-usd", str(budget),
            "--debug-file", str(debug_file),
            prompt,
        ]
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=cwd or str(work_dir_from_config),
        )

        _stop_watcher = threading.Event()
        _abort_poll_interval = getattr(self, "_abort_poll_interval", 3)

        def _abort_watcher():
            while not _stop_watcher.wait(timeout=_abort_poll_interval):
                if item_id and work_loop_instance and work_loop_instance.get_col(item_id, COL_STATUS) == 'abort':
                    print(f"\n[{_ts()}] {item_id}: abort requested — terminating Claude")
                    proc.terminate()
                    return

        watcher = threading.Thread(target=_abort_watcher, daemon=True)
        watcher.start()

        with open(log_file, 'wb') as lf:
            while True:
                chunk = proc.stdout.read(4096)
                if not chunk:
                    break
                sys.stdout.buffer.write(chunk)
                sys.stdout.buffer.flush()
                lf.write(chunk)
        proc.wait()
        _stop_watcher.set()
        watcher.join(timeout=1)
        return proc.returncode

    def launcher_script(self, item_id: str, ts_str: str, budget: float, mode: str, work_dir: str | None, remote_work_dir: str) -> str:
        if mode == "implement":
            prompt_file = "prompts/IMPL-PROMPT.md"
            extra_vars = f"$'\\nITEM_ID: {item_id}\\nWORK_LOOP_DIR: {remote_work_dir}\\nITEM_DIR: {remote_work_dir}/{item_id}'"
            rwd_capture = 'RWD="$(pwd)"\n'
            cd_work = f"cd {work_dir}\n" if work_dir else ""
            debug_flag = f'--debug-file "$RWD/{item_id}/_logs/{ts_str}_{item_id}.debug" '
            log_redir = f'> "$RWD/{item_id}/_logs/{ts_str}_{item_id}.log" 2>&1'
            done_dir = '$RWD'
        elif mode == "resolved":
            prompt_file = "prompts/RESOLVE-PROMPT.md"
            extra_vars = f"$'\\nITEM_ID: {item_id}'"
            rwd_capture = ""
            cd_work = ""
            debug_flag = f'--debug-file "{item_id}/_logs/{ts_str}_{item_id}.debug" '
            log_redir = f'> "{item_id}/_logs/{ts_str}_{item_id}.log" 2>&1'
            done_dir = '.'
        else:
            prompt_file = "prompts/LOOP-PROMPT.md"
            extra_vars = f"$'\\nITEM_ID: {item_id}'"
            rwd_capture = ""
            cd_work = ""
            debug_flag = f'--debug-file "{item_id}/_logs/{ts_str}_{item_id}.debug" '
            log_redir = f'> "{item_id}/_logs/{ts_str}_{item_id}.log" 2>&1'
            done_dir = '.'
        return (
            "#!/bin/bash\n"
            'export NVM_DIR="$HOME/.nvm"\n'
            '[ -s "$NVM_DIR/nvm.sh" ] && \\. "$NVM_DIR/nvm.sh"\n'
            f"cd {remote_work_dir}\n"
            f"mkdir -p {item_id}/_logs\n"
            f"{rwd_capture}"
            'BASE_PROMPT=""\n'
            '[ -f prompts/BASE-PROMPT.md ] && BASE_PROMPT="$(cat prompts/BASE-PROMPT.md)"$\'\\n\\n\'\n'
            '[ -z "$BASE_PROMPT" ] && [ -f BASE-PROMPT.md ] && BASE_PROMPT="$(cat BASE-PROMPT.md)"$\'\\n\\n\'\n'
            f'PROMPT="${{BASE_PROMPT}}$(cat {prompt_file})"{extra_vars}\n'
            f"{cd_work}"
            f'claude --print --permission-mode auto --max-budget-usd {budget} {debug_flag}"$PROMPT" {log_redir} &\n'
            f'echo $! > {done_dir}/{item_id}/.pid\n'
            f"wait $!\n"
            f'echo $? > {done_dir}/{item_id}/.done\n'
        )

    def agent_dir_name(self) -> str:
        return ".claude"

    def cost_injection(self, work_dir: Path, item_id: str, started_after: str = '') -> None:
        try:
            result = subprocess.run(
                ["ccusage", "session", "-j"],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode != 0:
                return
            data = json.loads(result.stdout)
            sessions = data.get('session', [])
            if not sessions:
                return
            if started_after:
                sessions = [s for s in sessions
                            if s.get('metadata', {}).get('lastActivity', '') >= started_after]
            if not sessions:
                return
            latest = max(sessions, key=lambda s: s.get('metadata', {}).get('lastActivity', ''))
            cost = latest.get('totalCost', 0)
            if not cost:
                return
            conv_file = work_dir / item_id / "CONVERSATION.md"
            if not conv_file.exists():
                return
            content = conv_file.read_text()
            patched = re.sub(
                r'^(## \d{4}-\d{2}-\d{2} \| Claude[^—\n]*)$',
                rf'\1 — ${cost:.2f}',
                content,
                count=1,
                flags=re.MULTILINE,
            )
            if patched != content:
                conv_file.write_text(patched)
        except FileNotFoundError:
            pass
        except Exception as e:
            print(f"[{_ts()}] WARNING: cost_injection failed for {item_id}: {e}")


class OpenCodeHarness(Harness):
    """OpenCode CLI harness."""

    def run(self, prompt: str, budget: float, cwd: str | None, item_id: str | None, log_file: Path) -> int:
        model_arg = ""
        if hasattr(self, '_model') and self._model:
            model_arg = ["--model", self._model]
        cmd = [
            "opencode", "run",
            "--auto",
            "--format", "json",
            "--title", item_id or "work-loop",
        ] + model_arg
        if cwd:
            cmd.extend(["--dir", cwd])
        cmd.append(prompt)

        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=cwd or str(work_dir_from_config),
        )

        _stop_watcher = threading.Event()
        _abort_poll_interval = getattr(self, "_abort_poll_interval", 3)

        def _abort_watcher():
            while not _stop_watcher.wait(timeout=_abort_poll_interval):
                if item_id and work_loop_instance and work_loop_instance.get_col(item_id, COL_STATUS) == 'abort':
                    print(f"\n[{_ts()}] {item_id}: abort requested — terminating OpenCode")
                    proc.terminate()
                    return

        watcher = threading.Thread(target=_abort_watcher, daemon=True)
        watcher.start()

        with open(log_file, 'wb') as lf:
            while True:
                chunk = proc.stdout.read(4096)
                if not chunk:
                    break
                sys.stdout.buffer.write(chunk)
                sys.stdout.buffer.flush()
                lf.write(chunk)
        proc.wait()
        _stop_watcher.set()
        watcher.join(timeout=1)

        # Post-run budget check
        if budget > 0 and proc.returncode == 0:
            self._check_budget(item_id, budget, log_file)

        # Session cleanup
        self._cleanup_session(item_id)

        return proc.returncode


    def _check_budget(self, item_id: str | None, budget: float, log_file: Path) -> None:
        """Check opencode stats post-run and cap cost in CONVERSATION.md."""
        try:
            result = subprocess.run(
                ["opencode", "stats", "--project", item_id or "work-loop"],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode == 0:
                # Parse cost from stats output; format varies but typically has a dollar amount
                cost_match = re.search(r'\$([\d.]+)', result.stdout)
                if cost_match:
                    cost = float(cost_match.group(1))
                    if cost > budget:
                        print(f"[{_ts()}] {item_id}: OpenCode cost ${cost:.2f} exceeded budget ${budget:.2f}")
        except FileNotFoundError:
            pass  # opencode not installed
        except Exception as e:
            print(f"[{_ts()}] WARNING: budget check failed for {item_id}: {e}")

    def _cleanup_session(self, item_id: str | None) -> None:
        """Delete OpenCode session to avoid accumulation."""
        try:
            result = subprocess.run(
                ["opencode", "session", "list", "-j"],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode != 0:
                return
            sessions = json.loads(result.stdout).get('sessions', [])
            for sess in sessions:
                sess_id = sess.get('id', '')
                sess_title = sess.get('title', '')
                if item_id and (sess_id == item_id or sess_title == item_id):
                    subprocess.run(
                        ["opencode", "session", "delete", sess_id],
                        capture_output=True, timeout=10,
                    )
        except FileNotFoundError:
            pass
        except Exception:
            pass  # non-fatal

    def launcher_script(self, item_id: str, ts_str: str, budget: float, mode: str, work_dir: str | None, remote_work_dir: str) -> str:
        model_arg = ""
        if hasattr(self, '_model') and self._model:
            model_arg = f"--model {self._model} "
        if mode == "implement":
            prompt_file = "prompts/IMPL-PROMPT.md"
            extra_vars = f"$'\\nITEM_ID: {item_id}\\nWORK_LOOP_DIR: {remote_work_dir}\\nITEM_DIR: {remote_work_dir}/{item_id}'"
            rwd_capture = 'RWD="$(pwd)"\n'
            cd_work = f"cd {work_dir}\n" if work_dir else ""
            log_redir = f'> "$RWD/{item_id}/_logs/{ts_str}_{item_id}.log" 2>&1'
            done_dir = '$RWD'
        elif mode == "resolved":
            prompt_file = "prompts/RESOLVE-PROMPT.md"
            extra_vars = f"$'\\nITEM_ID: {item_id}'"
            rwd_capture = ""
            cd_work = ""
            log_redir = f'> "{item_id}/_logs/{ts_str}_{item_id}.log" 2>&1'
            done_dir = '.'
        else:
            prompt_file = "prompts/LOOP-PROMPT.md"
            extra_vars = f"$'\\nITEM_ID: {item_id}'"
            rwd_capture = ""
            cd_work = ""
            log_redir = f'> "{item_id}/_logs/{ts_str}_{item_id}.log" 2>&1'
            done_dir = '.'
        return (
            "#!/bin/bash\n"
            f"cd {remote_work_dir}\n"
            f"mkdir -p {item_id}/_logs\n"
            f"{rwd_capture}"
            'BASE_PROMPT=""\n'
            '[ -f prompts/BASE-PROMPT.md ] && BASE_PROMPT="$(cat prompts/BASE-PROMPT.md)"$\'\\n\\n\'\n'
            '[ -z "$BASE_PROMPT" ] && [ -f BASE-PROMPT.md ] && BASE_PROMPT="$(cat BASE-PROMPT.md)"$\'\\n\\n\'\n'
            f'PROMPT="${{BASE_PROMPT}}$(cat {prompt_file})"{extra_vars}\n'
            f"{cd_work}"
            f'opencode run --auto --format json --title {item_id} {model_arg}"$PROMPT" {log_redir} &\n'
            f'echo $! > {done_dir}/{item_id}/.pid\n'
            f"wait $!\n"
            f'echo $? > {done_dir}/{item_id}/.done\n'
        )

    def agent_dir_name(self) -> str:
        return ".opencode"

    def cost_injection(self, work_dir: Path, item_id: str, started_after: str = '') -> None:
        # OpenCode doesn't have a direct cost injection equivalent; skip silently
        pass


# Module-level references set by WorkLoop.__init__ for use in harness abort watchers
work_dir_from_config: Path = Path.home()
work_loop_instance = None

COL_ID = 1
COL_TITLE = 2
COL_LOCATION = 3
COL_STATUS = 4
COL_LAST_UPDATED = 5
COL_BUDGET = 6
COL_LOG = 7

# RUNS.md column indices
RUNS_COL_ID = 1
RUNS_COL_TITLE = 2
RUNS_COL_STATUS = 3
RUNS_COL_LAST_UPDATED = 4
RUNS_COL_LOG = 5

# WORK-CHILDREN.md column indices
CH_ID = 1
CH_TITLE = 2
CH_STATUS = 3
CH_LAST_UPDATED = 4
CH_BUDGET = 5
CH_LOG = 6

# Polling constants
POLL_INTERVAL_S = 5
POLL_CYCLES_PER_MIN = 60 // POLL_INTERVAL_S  # = 12
DEFAULT_TIMEOUT_MIN = 4


def _is_data_row(cols: list[str]) -> bool:
    """Return True if the row is a real data row (not header, separator, or empty)."""
    if len(cols) < COL_STATUS + 1:
        return False
    id_val = cols[COL_ID].strip()
    if not id_val or re.match(r'^[-\s]+$', id_val) or id_val == 'ID':
        return False
    return True


class WorkLoop:
    def __init__(self, config: dict, script_dir: Path | None = None):
        self.config = config
        self.work_dir = Path(config['work_dir'])
        self.script_dir = script_dir if script_dir is not None else self.work_dir
        self.harness_type = config['harness']['type']
        self.max_budget = config.get('harness', {}).get('max_budget_usd', 10.00)
        self.remote_work_dir = config.get('remote', {}).get('work_dir', '~/Work-Loop')
        self.work_file = self.work_dir / "WORK.md"
        self._stop = False

        # Build harness
        if self.harness_type == 'opencode':
            self.harness = OpenCodeHarness()
            self.harness._model = config['harness'].get('model', '')
        else:
            self.harness = ClaudeHarness()
        self.harness._abort_poll_interval = 3

        # Set module-level refs for harness abort watchers
        global work_dir_from_config, work_loop_instance
        work_dir_from_config = self.work_dir
        work_loop_instance = self

        # Prompt files — harness type determines agent dir but prompts stay the same
        self.prompts_dir = self.script_dir / "prompts"
        self.base_prompt_file = self._resolve_prompt("BASE-PROMPT.md")
        self.prompt_file = self._resolve_prompt("LOOP-PROMPT.md")
        self.impl_prompt_file = self._resolve_prompt("IMPL-PROMPT.md")
        self.resolve_prompt_file = self._resolve_prompt("RESOLVE-PROMPT.md")
        self.child_research_prompt_file = self._resolve_prompt("UPDATE-RESEARCH-PROMPT.md")

    def _resolve_prompt(self, filename: str) -> Path:
        """Resolve a prompt file path, checking prompts/ subdir first, then script_dir."""
        prompts_path = self.script_dir / "prompts" / filename
        if prompts_path.exists():
            return prompts_path
        return self.script_dir / filename

    def _read_base_prompt(self) -> str:
        """Return content of BASE-PROMPT.md with trailing newlines, or empty string if missing."""
        if hasattr(self, 'base_prompt_file') and self.base_prompt_file.exists():
            text = self.base_prompt_file.read_text().strip()
            if text:
                return text + "\n\n"
        return ""

    # -------------------------------------------------------------------------
    # WORK.md I/O
    # -------------------------------------------------------------------------

    def _read_lines(self) -> list[str]:
        with open(self.work_file, 'r') as f:
            return f.readlines()

    def _write_lines(self, lines: list[str]) -> None:
        tmp = str(self.work_file) + ".tmp"
        with open(tmp, 'w') as f:
            f.writelines(lines)
        Path(tmp).replace(self.work_file)

    def update_col(self, item_id: str, col_idx: int, value: str) -> None:
        lines = self._read_lines()
        new_lines = []
        for line in lines:
            stripped = line.rstrip('\n')
            if stripped.startswith('|'):
                cols = stripped.split('|')
                if _is_data_row(cols) and cols[COL_ID].strip() == item_id:
                    cols[col_idx] = f" {value} "
                    line = '|'.join(cols) + '\n'
            new_lines.append(line)
        self._write_lines(new_lines)

    def get_col(self, item_id: str, col_idx: int) -> str:
        for line in self._read_lines():
            stripped = line.rstrip('\n')
            if not stripped.startswith('|'):
                continue
            cols = stripped.split('|')
            if _is_data_row(cols) and cols[COL_ID].strip() == item_id:
                return cols[col_idx].strip() if col_idx < len(cols) else ''
        return ''

    # Status values that trigger processing (ready = backwards-compat alias for analyze)
    TRIGGER_STATUSES = {'ready', 'analyze', 'implement', 'resolved', 'research'}

    def get_ready_items(self) -> list[str]:
        items = []
        for line in self._read_lines():
            stripped = line.rstrip('\n')
            if stripped.startswith('## Done'):
                break
            if not stripped.startswith('|'):
                continue
            cols = stripped.split('|')
            if _is_data_row(cols) and cols[COL_STATUS].strip() in self.TRIGGER_STATUSES:
                items.append(cols[COL_ID].strip())
        return items

    def get_new_items(self) -> list[str]:
        items = []
        for line in self._read_lines():
            stripped = line.rstrip('\n')
            if stripped.startswith('## Done'):
                break
            if not stripped.startswith('|'):
                continue
            cols = stripped.split('|')
            if _is_data_row(cols) and cols[COL_STATUS].strip() == 'new':
                items.append(cols[COL_ID].strip())
        return items

    @staticmethod
    def _normalize_table_text(text: str) -> str:
        """Convert Obsidian table <br> line breaks to real newlines."""
        return re.sub(r'\s*<br\s*/?>\s*', '\n', text, flags=re.IGNORECASE)

    def initialize_new_item(self, item_id: str) -> None:
        """Create folder and seed CONVERSATION.md (or RUNS.md) from the Title, then set status."""
        item_dir = self.work_dir / item_id
        item_dir.mkdir(parents=True, exist_ok=True)

        if self.get_item_type(item_id) == 'research':
            config = self._parse_runs_md(item_id)
            self._initialize_research_item(item_id, config)
            return

        if self.get_item_type(item_id) == 'script':
            config = self._parse_runs_md(item_id)
            initial_status = 'scheduled' if config.get('schedule') else 'ready'
            self.update_col(item_id, COL_STATUS, initial_status)
            print(f"[{_ts()}] Initialized script item: {item_id} (status: {initial_status})")
            return

        raw_title = self.get_col(item_id, COL_TITLE)
        m = re.match(r'\[([^\]]+)\]', raw_title)
        prompt = self._normalize_table_text(m.group(1) if m else raw_title)

        conv_file = item_dir / "CONVERSATION.md"
        if not conv_file.exists():
            today = datetime.now().strftime('%Y-%m-%d')
            conv_file.write_text(f"## {today} | User\n\n{prompt}\n")

        self.update_col(item_id, COL_STATUS, "ready")
        print(f"[{_ts()}] Initialized new item: {item_id}")

    def _initialize_research_item(self, item_id: str, config: dict) -> None:
        """Create folder, seed CONVERSATION.md and RUNS.md for a research item."""
        item_dir = self.work_dir / item_id
        item_dir.mkdir(parents=True, exist_ok=True)

        conv_file = item_dir / "CONVERSATION.md"
        if not conv_file.exists():
            title = config.get('title', item_id)
            today = datetime.now().strftime('%Y-%m-%d')
            conv_file.write_text(f"## {today} | User\n\nResearch item: {title}\n")

        initial_status = 'scheduled' if config.get('schedule') else 'ready'
        self.update_col(item_id, COL_STATUS, initial_status)
        print(f"[{_ts()}] Initialized research item: {item_id} (status: {initial_status})")

    def _auto_init_conversation(self, item_id: str) -> None:
        """Seed CONVERSATION.md from Title if missing (no status change)."""
        conv_file = self.work_dir / item_id / "CONVERSATION.md"
        if conv_file.exists():
            return
        raw_title = self.get_col(item_id, COL_TITLE)
        m = re.match(r'\[([^\]]+)\]', raw_title)
        prompt = self._normalize_table_text(m.group(1) if m else raw_title)
        item_dir = self.work_dir / item_id
        item_dir.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime('%Y-%m-%d')
        conv_file.write_text(f"## {today} | User\n\n{prompt}\n")
        print(f"[{_ts()}] Auto-initialized CONVERSATION.md for: {item_id}")

    def move_done_items(self) -> None:
        lines = self._read_lines()

        done_section_start = next(
            (i for i, l in enumerate(lines) if l.rstrip('\n').startswith('## Done')), -1
        )
        done_table_insert_idx = -1
        if done_section_start >= 0:
            for i in range(done_section_start, len(lines)):
                if lines[i].rstrip('\n').startswith('| --'):
                    done_table_insert_idx = i + 1
                    break

        done_row_indices = []
        for i, line in enumerate(lines):
            if done_section_start >= 0 and i >= done_section_start:
                break
            stripped = line.rstrip('\n')
            if not stripped.startswith('|'):
                continue
            cols = stripped.split('|')
            if not _is_data_row(cols):
                continue
            if cols[COL_STATUS].strip() == 'done':
                done_row_indices.append(i)

        if not done_row_indices or done_table_insert_idx < 0:
            return

        done_rows_content = [lines[i] for i in done_row_indices]
        new_lines = [l for i, l in enumerate(lines) if i not in set(done_row_indices)]
        adjust = sum(1 for idx in done_row_indices if idx < done_table_insert_idx)
        insert_at = done_table_insert_idx - adjust

        for j, row in enumerate(done_rows_content):
            new_lines.insert(insert_at + j, row)

        self._write_lines(new_lines)

    def _move_row_to_done(self, item_id: str) -> None:
        """Move a specific row (by ID) from active section to Done section without changing its status value."""
        lines = self._read_lines()

        done_section_start = next(
            (i for i, l in enumerate(lines) if l.rstrip('\n').startswith('## Done')), -1
        )
        done_table_insert_idx = -1
        if done_section_start >= 0:
            for i in range(done_section_start, len(lines)):
                if lines[i].rstrip('\n').startswith('| --'):
                    done_table_insert_idx = i + 1
                    break

        # Find the row to move
        row_index = -1
        for i, line in enumerate(lines):
            if done_section_start >= 0 and i >= done_section_start:
                break
            stripped = line.rstrip('\n')
            if not stripped.startswith('|'):
                continue
            cols = stripped.split('|')
            if not _is_data_row(cols):
                continue
            if cols[COL_ID].strip() == item_id:
                row_index = i
                break

        if row_index < 0 or done_table_insert_idx < 0:
            return

        # Extract the row content
        row_content = lines[row_index]

        # Remove the row from its current position
        new_lines = [l for i, l in enumerate(lines) if i != row_index]

        # Adjust insert index if we removed a row before the insertion point
        adjust = 1 if row_index < done_table_insert_idx else 0
        insert_at = done_table_insert_idx - adjust

        # Insert the row at the correct position in the Done section
        new_lines.insert(insert_at, row_content)

        self._write_lines(new_lines)

    def insert_work_row(self, item_id: str, title: str, location: str) -> None:
        """Insert a new row after the active table separator."""
        lines = self._read_lines()
        insert_idx = -1
        in_active = True
        for i, line in enumerate(lines):
            stripped = line.rstrip('\n')
            if stripped.startswith('## Done'):
                in_active = False
            if in_active and stripped.startswith('| --'):
                insert_idx = i + 1
                break

        if insert_idx < 0:
            return

        row = f"| {item_id} | [{title}]({item_id}/CONVERSATION.md) | {location} | ready |  |  |  |\n"
        lines.insert(insert_idx, row)
        self._write_lines(lines)

    def remove_work_row(self, item_id: str) -> None:
        """Remove a row by ID from any section."""
        lines = self._read_lines()
        new_lines = []
        for line in lines:
            stripped = line.rstrip('\n')
            if stripped.startswith('|'):
                cols = stripped.split('|')
                if _is_data_row(cols) and cols[COL_ID].strip() == item_id:
                    continue
            new_lines.append(line)
        self._write_lines(new_lines)

    def get_item_title(self, item_id: str) -> str:
        raw = self.get_col(item_id, COL_TITLE)
        m = re.match(r'\[([^\]]+)\]', raw)
        return m.group(1) if m else raw

    def get_item_budget(self, item_id: str) -> float:
        """Return the budget for an item from its Budget column, falling back to max_budget."""
        raw = self.get_col(item_id, COL_BUDGET)
        m = re.match(r'\$\s*([\d.]+)', raw)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                pass
        return self.max_budget

    # -------------------------------------------------------------------------
    # Remote stub WORK.md
    # -------------------------------------------------------------------------

    def build_stub_work_md(self, item_id: str, title: str) -> str:
        return (
            "# Work Loop\n\n"
            "<!-- Status values: waiting | ready | in-progress | needs-review | blocked | done -->\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
            f"| {item_id} | {title} | local | ready |  |  |  |\n\n"
            "## Done\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
        )

    # -------------------------------------------------------------------------
    # Harness execution
    # -------------------------------------------------------------------------

    def extract_work_dir(self, item_id: str) -> str:
        """Scan CONVERSATION.md for 'work_dir: <path>' and return it expanded.

        Returns work_dir (the loop root) if not found — logs a warning for implement items.
        """
        conv_file = self.work_dir / item_id / "CONVERSATION.md"
        if conv_file.exists():
            for line in conv_file.read_text().splitlines():
                m = re.match(r'\s*work_dir:\s*(.+)', line, re.IGNORECASE)
                if m:
                    path = re.sub(r'\s*<br.*', '', m.group(1), flags=re.IGNORECASE).strip()
                    return os.path.expanduser(path)
        print(f"[{_ts()}] WARNING: no 'work_dir:' found in {item_id}/CONVERSATION.md — using loop root")
        return str(self.work_dir)

    def _sync_agent_dir(self, target_cwd: str) -> None:
        """Copy harness agent directory from script_dir to target workspace.

        Mirrors remote dispatch behaviour (rsync .opencode/ or .claude/ to remote
        work dir) for local execution, so subagent definitions are discoverable."""
        src = self.script_dir / self.harness.agent_dir_name()
        if not src.exists():
            return
        dst = Path(target_cwd) / self.harness.agent_dir_name()
        if src.resolve() == dst.resolve():
            return
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)

    def _run_harness(self, prompt: str, log_file: Path, budget: float, cwd: str | None = None, item_id: str | None = None) -> int:
        """Delegate to the configured harness."""
        target_cwd = cwd or str(self.work_dir)
        self._sync_agent_dir(target_cwd)
        return self.harness.run(prompt, budget, cwd, item_id, log_file)

    def _inject_session_cost(self, item_id: str, started_after: str = '') -> None:
        """Append cost info to CONVERSATION.md after a successful run."""
        self.harness.cost_injection(self.work_dir, item_id, started_after)

    def prepend_abort_notice(self, item_id: str, date_str: str, budget: float, cause: str = "budget exceeded") -> None:
        conv_file = self.work_dir / item_id / "CONVERSATION.md"
        if not conv_file.exists():
            return
        existing = conv_file.read_text()
        notice = f"## {date_str} | Script — Run aborted: {cause} (${budget})\n\n"
        conv_file.write_text(notice + existing)

    def _classify_failure(self, item_id: str, ts_str: str) -> str:
        """Return 'budget' or 'unknown' by inspecting the log file."""
        log_file = self.work_dir / item_id / "_logs" / f"{ts_str}_{item_id}.log"
        if not log_file.exists():
            return "unknown"
        try:
            lower = log_file.read_text(errors='replace').lower()
        except OSError:
            return "unknown"
        if any(p in lower for p in ("budget", "cost limit", "exceeded")):
            return "budget"
        return "unknown"

    # -------------------------------------------------------------------------
    # Local processing
    # -------------------------------------------------------------------------

    def process_local(self, item_id: str, budget: float) -> None:
        self._auto_init_conversation(item_id)
        item_dir = self.work_dir / item_id
        item_dir.mkdir(parents=True, exist_ok=True)
        (item_dir / "_logs").mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime('%Y-%m-%d')
        ts = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        run_start = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z')
        log_file = item_dir / "_logs" / f"{ts}_{item_id}.log"
        log_link = f"[Log]({item_id}/_logs/{ts}_{item_id}.debug)"

        mode = self.get_col(item_id, COL_STATUS)  # read trigger status BEFORE overwriting
        self.update_col(item_id, COL_STATUS, "in-progress")

        if mode == "research":
            config = self._parse_runs_md(item_id)
            research_prompt_file = self._resolve_prompt("UPDATE-RESEARCH-PROMPT.md")
            if research_prompt_file.exists():
                prompt_text = research_prompt_file.read_text()
            else:
                prompt_text = self.prompt_file.read_text()
                print(f"[{_ts()}] WARNING: UPDATE-RESEARCH-PROMPT.md not found, using LOOP-PROMPT.md")

            sources = config.get('sources', [])
            sources_str = '\n'.join(f'- {s.strip()}' for s in sources) if sources else '(none)'
            instruction = config.get('instruction', '')

            item_dir = str(self.work_dir / item_id)
            prompt = (
                f"{self._read_base_prompt()}"
                f"{prompt_text}\n\n"
                f"title: {config.get('title', '')}\n"
                f"note_path: {config.get('note_path', '')}\n"
                f"sources:\n{sources_str}\n"
                f"instruction:\n{instruction}\n"
                f"\nBACKLINK_TARGET: CONVERSATION\n"
                f"ITEM_ID: {item_id}\n"
                f"WORK_LOOP_DIR: {self.work_dir}\n"
                f"ITEM_DIR: {item_dir}"
            )
            cwd = str(self.work_dir)
        elif mode == "implement":
            impl_prompt_file = self._resolve_prompt("IMPL-PROMPT.md")
            if impl_prompt_file.exists():
                prompt_text = impl_prompt_file.read_text()
                cwd = self.extract_work_dir(item_id)
            else:
                prompt_text = self.prompt_file.read_text()
                cwd = str(self.work_dir)
        elif mode == "resolved":
            resolve_prompt_file = self._resolve_prompt("RESOLVE-PROMPT.md")
            if resolve_prompt_file.exists():
                prompt_text = resolve_prompt_file.read_text()
            else:
                prompt_text = self.prompt_file.read_text()
            cwd = str(self.work_dir)
        else:
            prompt_text = self.prompt_file.read_text()
            cwd = str(self.work_dir)

        if mode != "research":
            item_dir = str(self.work_dir / item_id)
            prompt = (
                f"{self._read_base_prompt()}"
                f"{prompt_text}\n\n"
                f"ITEM_ID: {item_id}\n"
                f"WORK_LOOP_DIR: {self.work_dir}\n"
                f"ITEM_DIR: {item_dir}"
            )

        print(f"[{_ts()}] Processing: {item_id} (mode: {mode}, budget: ${budget}, cwd: {cwd})")
        exit_code = self._run_harness(prompt, log_file, budget, cwd=cwd, item_id=item_id)

        # Re-read status: user may have set it to 'abort' while harness was running
        current_status = self.get_col(item_id, COL_STATUS)

        self.update_col(item_id, COL_LAST_UPDATED, today)
        self.update_col(item_id, COL_LOG, log_link)

        if current_status == 'abort':
            self.prepend_abort_notice(item_id, today, budget, "aborted by user")
            print(f"[{_ts()}] {item_id}: aborted by user — status left as abort")
        elif exit_code != 0:
            failure = self._classify_failure(item_id, ts)
            if failure == "budget":
                budget_label, cause, msg = f"${budget} - EXCEEDED", "budget exceeded", f"[{_ts()}] {item_id}: budget exceeded — marked needs-review"
            else:
                budget_label, cause, msg = f"${budget} - FAILED", "run failed", f"[{_ts()}] {item_id}: run failed — marked needs-review"
            self.update_col(item_id, COL_STATUS, "needs-review")
            self.update_col(item_id, COL_BUDGET, budget_label)
            self.prepend_abort_notice(item_id, today, budget, cause)
            print(msg)
        else:
            self.update_col(item_id, COL_BUDGET, f"${budget}")
            self._inject_session_cost(item_id, run_start)
            if mode == "research":
                config = self._parse_runs_md(item_id)
                run_dir = self.work_dir / item_id / "runs"
                latest_run = None
                if run_dir.exists():
                    dirs = [d for d in run_dir.iterdir() if d.is_dir()]
                    if dirs:
                        latest_run = sorted(dirs, reverse=True)[0].name
                if latest_run:
                    research_file = run_dir / latest_run / "research.md"
                    if research_file.exists():
                        lines = research_file.read_text().split('\n')
                        summary = lines[1].strip('# -').strip() if len(lines) > 1 else "Research complete"
                    else:
                        summary = "Research complete"
                    self._append_research_run(item_id, latest_run, summary)
                if config.get('schedule'):
                    self.update_col(item_id, COL_STATUS, "scheduled")
                else:
                    self.update_col(item_id, COL_STATUS, "done")
                print(f"[{_ts()}] {item_id}: research complete — status={'scheduled' if config.get('schedule') else 'done'}")
            elif mode == "resolved":
                self._move_row_to_done(item_id)
                print(f"[{_ts()}] {item_id}: resolved — moved to Done section")
            else:
                print(f"[{_ts()}] {item_id}: completed")

    # -------------------------------------------------------------------------
    # Remote launcher
    # -------------------------------------------------------------------------

    def build_launcher(self, item_id: str, ts_str: str, budget: float, mode: str = "analyze", work_dir: str | None = None) -> str:
        """Delegate to the configured harness for launcher script generation."""
        return self.harness.launcher_script(item_id, ts_str, budget, mode, work_dir, self.remote_work_dir)

    # -------------------------------------------------------------------------
    # Remote dispatch
    # -------------------------------------------------------------------------

    def dispatch_remote(self, item_id: str, ts_str: str, remote_host: str, budget: float, mode: str = "analyze") -> None:
        self._auto_init_conversation(item_id)
        rwd = self.remote_work_dir
        _run(["ssh", remote_host, f"rm -rf {rwd} && mkdir -p {rwd}/{item_id}/_logs {rwd}/prompts"])

        item_dir = self.work_dir / item_id
        _run(["rsync", "-avz", "--delete", "--exclude=.done", f"{item_dir}/", f"{remote_host}:{rwd}/{item_id}/"])
        if (self.script_dir / "prompts").exists():
            _run(["rsync", "-avz", str(self.script_dir / "prompts") + "/", f"{remote_host}:{rwd}/prompts/"])
        else:
            _run(["rsync", "-avz", str(self.prompt_file), f"{remote_host}:{rwd}/prompts/"])
            if self.base_prompt_file.exists():
                _run(["rsync", "-avz", str(self.base_prompt_file), f"{remote_host}:{rwd}/prompts/"])

            if mode == "implement":
                impl_prompt_file = self._resolve_prompt("IMPL-PROMPT.md")
                if impl_prompt_file.exists():
                    _run(["rsync", "-avz", str(impl_prompt_file), f"{remote_host}:{rwd}/prompts/"])
            elif mode == "resolved":
                resolve_prompt_file = self._resolve_prompt("RESOLVE-PROMPT.md")
                if resolve_prompt_file.exists():
                    _run(["rsync", "-avz", str(resolve_prompt_file), f"{remote_host}:{rwd}/prompts/"])

        agent_dir = self.script_dir / self.harness.agent_dir_name()
        if agent_dir.exists():
            _run(["ssh", remote_host, f"mkdir -p {rwd}/{self.harness.agent_dir_name()}"])
            _run(["rsync", "-avz", str(agent_dir) + "/", f"{remote_host}:{rwd}/{self.harness.agent_dir_name()}/"])

        title = self.get_item_title(item_id)
        stub = self.build_stub_work_md(item_id, title)
        proc = subprocess.run(
            ["ssh", remote_host, f"cat > {rwd}/WORK.md"],
            input=stub.encode(),
            check=True,
        )

        work_dir = None
        if mode == "implement":
            extracted = self.extract_work_dir(item_id)
            if extracted != str(self.work_dir):
                work_dir = extracted

        launcher_content = self.build_launcher(item_id, ts_str, budget, mode=mode, work_dir=work_dir)
        with tempfile.NamedTemporaryFile(
            mode='w', prefix=f".{self.harness_type}-launch-{item_id}-", suffix=".sh", delete=False
        ) as tmp:
            tmp.write(launcher_content)
            launcher_tmp = tmp.name

        try:
            _run(["rsync", "-avz", launcher_tmp, f"{remote_host}:{rwd}/.launch-{item_id}.sh"])
        finally:
            os.unlink(launcher_tmp)

        _run([
            "ssh", remote_host,
            f"nohup bash {rwd}/.launch-{item_id}.sh </dev/null >/dev/null 2>&1 &",
        ])

    # -------------------------------------------------------------------------
    # Remote polling / recovery
    # -------------------------------------------------------------------------

    def _sync_back_remote(
        self, item_id: str, ts_str: str, remote_host: str, budget: float, exit_str: str, mode: str = "analyze"
    ) -> None:
        """Sync files back from a completed remote job, update WORK.md, clean up remote."""
        rwd = self.remote_work_dir
        today = datetime.now().strftime('%Y-%m-%d')
        log_link = f"[Log]({item_id}/_logs/{ts_str}_{item_id}.debug)"

        item_dir = self.work_dir / item_id
        item_dir.mkdir(parents=True, exist_ok=True)
        _run(["rsync", "-avz", "--delete", "--exclude=.done", f"{remote_host}:{rwd}/{item_id}/", f"{item_dir}/"])
        _run([
            "rsync", "-avz",
            f"{remote_host}:{rwd}/{item_id}/_logs/{ts_str}_{item_id}.log",
            str(item_dir / "_logs") + "/",
        ], check=False)
        _run([
            "rsync", "-avz",
            f"{remote_host}:{rwd}/{item_id}/_logs/{ts_str}_{item_id}.debug",
            str(item_dir / "_logs") + "/",
        ], check=False)

        # Capture Claude's concise title before remote cleanup (written to stub WORK.md)
        remote_wmd = subprocess.run(
            ["ssh", remote_host, f"cat {rwd}/WORK.md"],
            capture_output=True, text=True, check=False,
        )
        if remote_wmd.returncode == 0:
            for _line in remote_wmd.stdout.splitlines():
                if _line.startswith('|'):
                    _cols = _line.split('|')
                    if _is_data_row(_cols) and _cols[COL_ID].strip() == item_id:
                        remote_title = _cols[COL_TITLE].strip()
                        if re.match(r'^\[', remote_title):
                            self.update_col(item_id, COL_TITLE, remote_title)
                        break

        subprocess.run(["ssh", remote_host, f"rm -rf {rwd}"], check=False)

        self.update_col(item_id, COL_LAST_UPDATED, today)
        self.update_col(item_id, COL_LOG, log_link)

        try:
            claude_exit = int(exit_str)
        except ValueError:
            claude_exit = 1

        if claude_exit != 0:
            failure = self._classify_failure(item_id, ts_str)
            if failure == "budget":
                budget_label, cause, msg = f"${budget} - EXCEEDED", "budget exceeded", f"[{_ts()}] {item_id}: remote budget exceeded — synced back, marked needs-review"
            else:
                budget_label, cause, msg = f"${budget} - FAILED", "run failed", f"[{_ts()}] {item_id}: remote run failed — synced back, marked needs-review"
            self.update_col(item_id, COL_STATUS, "needs-review")
            self.update_col(item_id, COL_BUDGET, budget_label)
            self.prepend_abort_notice(item_id, today, budget, cause)
            print(msg)
        else:
            self.update_col(item_id, COL_BUDGET, f"${budget}")
            if mode == "resolved":
                self._move_row_to_done(item_id)
                print(f"[{_ts()}] {item_id}: remote resolved — synced back, moved to Done section")
            else:
                self.update_col(item_id, COL_STATUS, "needs-review")
                print(f"[{_ts()}] {item_id}: remote completed — synced back, marked needs-review")

    def _ts_str_from_log_col(self, item_id: str, remote_host: str) -> str | None:
        """Return the dispatch ts_str for item_id, from Log column or by globbing the remote."""
        log_raw = self.get_col(item_id, COL_LOG)
        m = re.search(
            r'_logs/(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})_' + re.escape(item_id) + r'\.(log|debug)',
            log_raw,
        )
        if m:
            return m.group(1)
        # Fallback: find the log on the remote
        rwd = self.remote_work_dir
        result = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=5", remote_host,
             f"ls {rwd}/{item_id}/_logs/*_{item_id}.debug 2>/dev/null | head -1 || ls {rwd}/{item_id}/_logs/*_{item_id}.log 2>/dev/null | head -1"],
            capture_output=True, text=True,
        )
        if result.stdout.strip():
            log_filename = Path(result.stdout.strip()).name
            return log_filename.replace(f'_{item_id}.log', '')
        return None

    def get_inprogress_remote_items(self) -> list[tuple[str, str]]:
        """Return (item_id, remote_host) for in-progress remote items."""
        items = []
        for line in self._read_lines():
            stripped = line.rstrip('\n')
            if stripped.startswith('## Done'):
                break
            if not stripped.startswith('|'):
                continue
            cols = stripped.split('|')
            if _is_data_row(cols) and cols[COL_STATUS].strip() == 'in-progress':
                location = cols[COL_LOCATION].strip()
                if location != 'local':
                    items.append((cols[COL_ID].strip(), location))
        return items

    def check_stalled_remotes(self) -> None:
        """Recover any in-progress remote items whose remote job has since completed."""
        for item_id, remote_host in self.get_inprogress_remote_items():
            rwd = self.remote_work_dir
            result = subprocess.run(
                ["ssh", "-o", "ConnectTimeout=5", remote_host,
                 f"cat {rwd}/{item_id}/.done 2>/dev/null"],
                capture_output=True, text=True,
            )
            exit_str = result.stdout.strip()
            if not exit_str:
                continue
            ts_str = self._ts_str_from_log_col(item_id, remote_host)
            if not ts_str:
                print(f"[{_ts()}] {item_id}: remote done but log timestamp unknown — manual recovery needed")
                continue
            budget = self.get_item_budget(item_id)
            print(f"\n[{_ts()}] {item_id}: recovering stalled remote job...")
            self._sync_back_remote(item_id, ts_str, remote_host, budget, exit_str)

    def _abort_remote(self, item_id: str, ts_str: str, remote_host: str, budget: float) -> None:
        """Kill the remote Claude process (via .pid), sync back, leave status as abort."""
        rwd = self.remote_work_dir
        today = datetime.now().strftime('%Y-%m-%d')

        # Best-effort kill; ignore errors (process may have already exited)
        subprocess.run(
            ["ssh", remote_host,
             f"PID=$(cat {rwd}/{item_id}/.pid 2>/dev/null); [ -n \"$PID\" ] && kill $PID 2>/dev/null; true"],
            check=False,
        )

        # Sync back whatever was written before we killed it
        item_dir = self.work_dir / item_id
        item_dir.mkdir(parents=True, exist_ok=True)
        _run(["rsync", "-avz", "--delete", "--exclude=.done", "--exclude=.pid",
              f"{remote_host}:{rwd}/{item_id}/", f"{item_dir}/"], check=False)
        _run(["rsync", "-avz",
              f"{remote_host}:{rwd}/{item_id}/_logs/{ts_str}_{item_id}.log",
              str(item_dir / "_logs") + "/"], check=False)
        _run(["rsync", "-avz",
              f"{remote_host}:{rwd}/{item_id}/_logs/{ts_str}_{item_id}.debug",
              str(item_dir / "_logs") + "/"], check=False)

        subprocess.run(["ssh", remote_host, f"rm -rf {rwd}"], check=False)

        self.update_col(item_id, COL_LAST_UPDATED, today)
        self.prepend_abort_notice(item_id, today, budget, "aborted by user")
        # Status stays as abort — do NOT overwrite with needs-review
        print(f"[{_ts()}] {item_id}: remote abort — killed, synced back, status left as abort")

    def wait_for_remote(
        self,
        item_id: str,
        ts_str: str,
        remote_host: str,
        budget: float,
        mode: str = "analyze",
        poll_interval: int = 5,
        timeout: int = 600,
    ) -> None:
        rwd = self.remote_work_dir

        print(f"[{_ts()}] {item_id}: waiting for remote completion...")
        deadline = time.time() + timeout

        while time.time() < deadline:
            if self.get_col(item_id, COL_STATUS) == 'abort':
                print(f"\n[{_ts()}] {item_id}: abort requested — killing remote Claude")
                self._abort_remote(item_id, ts_str, remote_host, budget)
                return

            result = subprocess.run(
                ["ssh", remote_host, f"cat {rwd}/{item_id}/.done 2>/dev/null"],
                capture_output=True, text=True,
            )
            exit_str = result.stdout.strip()
            if exit_str:
                self._sync_back_remote(item_id, ts_str, remote_host, budget, exit_str, mode=mode)
                return

            print(f"\r[{_ts()}] {item_id}: remote running, waiting...   ", end="", flush=True)
            time.sleep(poll_interval)

        print(f"\n[{_ts()}] {item_id}: timeout waiting for remote — leaving as in-progress")

    # -------------------------------------------------------------------------
    # Script item support
    # -------------------------------------------------------------------------

    def get_item_type(self, item_id: str) -> str:
        """Return 'research', 'script', or 'conversation'."""
        runs_file = self.work_dir / item_id / "RUNS.md"
        if not runs_file.exists():
            return 'conversation'
        config = self._parse_runs_md(item_id)
        if config.get('type') == 'research':
            return 'research'
        return 'script'

    def _parse_config_block(self, text: str) -> dict:
        """Parse a ## Config block from text, return normalized dict."""
        config = {
            'command': '', 'params': '', 'schedule': '',
            'location': '', 'locations': [],
            'heartbeat_file': '', 'timeout': DEFAULT_TIMEOUT_MIN,
            'aggregation_script': '', 'analysis_prompt': '',
            'type': '', 'title': '', 'note_path': '', 'sources': [],
            'parent': '',
        }
        m = re.search(r'^## Config\s*\n(.*?)(?=^##|\Z)', text, re.MULTILINE | re.DOTALL)
        if not m:
            return config
        in_locations = False
        in_sources = False
        for line in m.group(1).splitlines():
            stripped = line.strip()
            if not stripped:
                in_locations = False
                in_sources = False
                continue
            if in_locations and line.startswith('  '):
                loc = stripped.strip('`')
                if loc:
                    config['locations'].append(loc)
                continue
            if in_sources and line.startswith('  '):
                src = stripped.strip('`')
                if src:
                    config['sources'].append(src)
                continue
            in_locations = False
            in_sources = False
            if ':' not in line:
                continue
            key, _, val = line.partition(':')
            key_n = key.strip().lower().replace(' ', '_').replace('-', '_')
            val = val.strip().strip('`')
            if key_n == 'command':
                config['command'] = val
            elif key_n == 'params':
                config['params'] = val
            elif key_n == 'schedule':
                config['schedule'] = val
            elif key_n == 'location':
                config['location'] = val
            elif key_n == 'locations':
                in_locations = True
            elif key_n == 'sources':
                in_sources = True
            elif key_n == 'heartbeat_file':
                config['heartbeat_file'] = val
            elif key_n == 'timeout':
                try:
                    config['timeout'] = int(val)
                except ValueError:
                    pass
            elif key_n == 'aggregation_script':
                config['aggregation_script'] = val.strip('`')
            elif key_n == 'analysis_prompt':
                config['analysis_prompt'] = val
            elif key_n == 'type':
                config['type'] = val
            elif key_n == 'title':
                config['title'] = val
            elif key_n == 'note_path':
                config['note_path'] = val
            elif key_n == 'parent':
                config['parent'] = val
        return config

    def _parse_runs_md(self, item_id: str) -> dict:
        """Parse RUNS.md — returns config dict with 'instruction' key."""
        runs_file = self.work_dir / item_id / "RUNS.md"
        if not runs_file.exists():
            return self._empty_config()
        text = runs_file.read_text()
        config = self._parse_config_block(text)
        # Parse Prompt block
        m = re.search(r'^## Prompt\s*\n(.*?)(?=^##|\Z)', text, re.MULTILINE | re.DOTALL)
        config['instruction'] = m.group(1).strip() if m else ''
        return config

    _parse_runs_md_config = _parse_runs_md  # alias for script item processing

    def _empty_config(self) -> dict:
        """Return a default/empty config dict."""
        return {
            'command': '', 'params': '', 'schedule': '',
            'location': '', 'locations': [],
            'heartbeat_file': '', 'timeout': DEFAULT_TIMEOUT_MIN,
            'aggregation_script': '', 'analysis_prompt': '',
            'type': '', 'title': '', 'note_path': '', 'sources': [],
            'parent': '', 'instruction': '',
        }

    def _cron_should_run(self, cron_str: str, now: datetime) -> bool:
        """Return True if cron_str (5-field) fires at the given datetime."""
        if not cron_str:
            return False
        parts = cron_str.strip().split()
        if len(parts) != 5:
            return False
        minute_s, hour_s, dom_s, month_s, dow_s = parts

        def _matches(field: str, value: int) -> bool:
            if field == '*':
                return True
            for part in field.split(','):
                if '/' in part:
                    base, step = part.split('/', 1)
                    b = 0 if base == '*' else int(base)
                    if value >= b and (value - b) % int(step) == 0:
                        return True
                elif '-' in part:
                    lo, hi = part.split('-', 1)
                    if int(lo) <= value <= int(hi):
                        return True
                elif int(part) == value:
                    return True
            return False

        cron_dow = (now.weekday() + 1) % 7  # Python Mon=0 → cron Sun=0
        return (
            _matches(minute_s, now.minute) and
            _matches(hour_s, now.hour) and
            _matches(dom_s, now.day) and
            _matches(month_s, now.month) and
            _matches(dow_s, cron_dow)
        )

    def _generate_run_id(self, item_id: str, runs_path: Path | None = None) -> str:
        """Generate YYYYMMDD-NNN run ID by scanning existing RUNS.md rows."""
        runs_file = runs_path if runs_path is not None else self.work_dir / item_id / "RUNS.md"
        today = datetime.now().strftime('%Y%m%d')
        max_n = 0
        if runs_file.exists():
            for line in runs_file.read_text().splitlines():
                if line.startswith('|'):
                    cols = line.split('|')
                    if len(cols) > 1:
                        cell = cols[1].strip()
                        mo = re.match(rf'^{today}-(\d+)$', cell)
                        if mo:
                            max_n = max(max_n, int(mo.group(1)))
        return f"{today}-{max_n + 1:03d}"

    def _parse_location(self, location: str) -> tuple[str, str, str]:
        """Parse 'linux:user@host' → ('linux', 'user@host', 'host')."""
        if ':' in location and not location.startswith('local') and not location.startswith('multi'):
            os_type, user_host = location.split(':', 1)
            hostname = user_host.split('@', 1)[1] if '@' in user_host else user_host
            return os_type, user_host, hostname
        return 'linux', location, location

    def _rsync_cmd_for_host(self, os_type: str, src: str, dst: str, extra_flags: list[str] | None = None) -> list[str]:
        """Build rsync command; win: hosts get --rsync-path."""
        cmd = ["rsync", "-avz"]
        if os_type == 'win':
            cmd.append('--rsync-path=~/Work-Loop/tools/rsync-win/rsync.exe')
        if extra_flags:
            cmd.extend(extra_flags)
        cmd.extend([src, dst])
        return cmd

    def _run_dir_local(self, item_id: str, run_id: str, hostname: str, is_multi: bool) -> Path:
        base = self.work_dir / item_id / "runs" / run_id
        return base / hostname if is_multi else base

    def _append_runs_md_row(self, item_id: str, run_id: str, title: str, status: str = 'running') -> None:
        """Append a new row to RUNS.md run history table."""
        runs_file = self.work_dir / item_id / "RUNS.md"
        today = datetime.now().strftime('%Y-%m-%d')
        log_link = f"[Log](runs/{run_id}/)"
        row = f"| {run_id} | {title} | {status} | {today} | {log_link} |\n"
        text = runs_file.read_text() if runs_file.exists() else ""
        lines = text.splitlines(keepends=True)
        table_sep_idx = -1
        last_data_idx = -1
        for i, line in enumerate(lines):
            stripped = line.lstrip()
            if stripped.startswith('| --') or stripped.startswith('|--'):
                if line.count('|') >= 4:
                    table_sep_idx = i
            elif table_sep_idx >= 0 and line.startswith('|'):
                last_data_idx = i
        if table_sep_idx < 0:
            header = "\n| ID | Title | Status | Last Updated | Log |\n|---|---|---|---|---|\n"
            text += header + row
            runs_file.write_text(text)
        else:
            insert_at = (last_data_idx + 1) if last_data_idx >= 0 else (table_sep_idx + 1)
            lines.insert(insert_at, row)
            runs_file.write_text("".join(lines))

    def _create_run_dir(self, item_id: str, run_id: str) -> Path:
        """Create runs/{run_id}/ directory and return its path."""
        run_dir = self.work_dir / item_id / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    def _append_research_run(self, item_id: str, run_id: str, summary: str, runs_path: Path | None = None) -> None:
        """Append a new row to RUNS.md run history table for research items."""
        runs_file = runs_path if runs_path is not None else self.work_dir / item_id / "RUNS.md"
        today = datetime.now().strftime('%Y-%m-%d')
        log_link = f"[Log](runs/{run_id}/)"
        summary_link = f"[{summary}](runs/{run_id}/)"
        row = f"| {run_id} | {summary_link} | running | {today} | {log_link} |\n"
        text = runs_file.read_text() if runs_file.exists() else ""
        lines = text.splitlines(keepends=True)
        table_sep_idx = -1
        last_data_idx = -1
        for i, line in enumerate(lines):
            stripped = line.lstrip()
            if stripped.startswith('| --') or stripped.startswith('|--'):
                if line.count('|') >= 4:
                    table_sep_idx = i
            elif table_sep_idx >= 0 and line.startswith('|'):
                last_data_idx = i
        if table_sep_idx < 0:
            header = "\n| ID | Summary | Status | Last Updated | Log |\n|---|---|---|---|---|\n"
            text += header + row
            runs_file.write_text(text)
        else:
            insert_at = (last_data_idx + 1) if last_data_idx >= 0 else (table_sep_idx + 1)
            lines.insert(insert_at, row)
            runs_file.write_text("".join(lines))

    def _update_runs_md_row_status(self, item_id: str, run_id: str, status: str, runs_path: Path | None = None) -> None:
        """Update Status and Last Updated for a given run_id in RUNS.md."""
        runs_file = runs_path if runs_path is not None else self.work_dir / item_id / "RUNS.md"
        if not runs_file.exists():
            return
        today = datetime.now().strftime('%Y-%m-%d')
        new_lines = []
        for line in runs_file.read_text().splitlines(keepends=True):
            if line.startswith('|'):
                cols = line.rstrip('\n').split('|')
                if len(cols) > RUNS_COL_STATUS and cols[RUNS_COL_ID].strip() == run_id:
                    cols[RUNS_COL_STATUS] = f" {status} "
                    if len(cols) > RUNS_COL_LAST_UPDATED:
                        cols[RUNS_COL_LAST_UPDATED] = f" {today} "
                    line = '|'.join(cols) + '\n'
            new_lines.append(line)
        runs_file.write_text("".join(new_lines))

    def _find_latest_runs_md_run(self, item_id: str, status: str | None = None, runs_path: Path | None = None) -> str | None:
        """Return the latest run_id with given status (None = any)."""
        runs_file = runs_path if runs_path is not None else self.work_dir / item_id / "RUNS.md"
        if not runs_file.exists():
            return None
        latest = None
        for line in runs_file.read_text().splitlines():
            if not line.startswith('|'):
                continue
            cols = line.split('|')
            if len(cols) <= RUNS_COL_STATUS:
                continue
            run_id = cols[RUNS_COL_ID].strip()
            if not re.match(r'^\d{8}-\d{3}$', run_id):
                continue
            row_status = cols[RUNS_COL_STATUS].strip() if len(cols) > RUNS_COL_STATUS else ''
            if status is None or row_status == status:
                latest = run_id
        return latest

    # -------------------------------------------------------------------------
    # Child agent support
    # -------------------------------------------------------------------------

    def _parse_child_runs_md(self, child_path: Path) -> dict:
        """Parse a child's RUNS.md from an arbitrary path."""
        if not child_path.exists():
            return self._empty_config()
        text = child_path.read_text()
        config = self._parse_config_block(text)
        m = re.search(r'^## Prompt\s*\n(.*?)(?=^##|\Z)', text, re.MULTILINE | re.DOTALL)
        config['instruction'] = m.group(1).strip() if m else ''
        return config

    def _get_all_item_ids(self) -> list[str]:
        """Return all item IDs in work_dir, including done items (filesystem scan)."""
        items = []
        for entry in sorted(self.work_dir.iterdir()):
            if entry.is_dir():
                if (entry / "RUNS.md").exists() or (entry / "CONVERSATION.md").exists():
                    items.append(entry.name)
        return items

    def _get_child_status(self, work_children_path: Path, child_name: str) -> str:
        """Read Status column for child_name from WORK-CHILDREN.md. Defaults to 'ready'."""
        if not work_children_path.exists():
            return 'ready'
        for line in work_children_path.read_text().splitlines():
            stripped = line.rstrip('\n')
            if not stripped.startswith('|'):
                continue
            cols = stripped.split('|')
            if len(cols) < CH_STATUS + 1:
                continue
            if cols[CH_ID].strip() == child_name:
                return cols[CH_STATUS].strip()
        return 'ready'

    @staticmethod
    def _get_parent_id(child_config: dict) -> str | None:
        """Read parent ID from child config dict."""
        return child_config.get('parent') or None

    def get_children(self, parent_id: str) -> list[tuple[str, str, dict]]:
        """Two-phase child discovery: WORK-CHILDREN.md for names/statuses, RUNS.md for config + orphan check."""
        work_children_path = self.work_dir / parent_id / "WORK-CHILDREN.md"
        if not work_children_path.exists():
            return []
        children = []
        for line in work_children_path.read_text().splitlines():
            stripped = line.rstrip('\n')
            if not stripped.startswith('|'):
                continue
            cols = stripped.split('|')
            if len(cols) < CH_STATUS + 1:
                continue
            child_name = cols[CH_ID].strip()
            if not child_name:
                continue
            child_runs_path = self.work_dir / parent_id / "children" / child_name / "RUNS.md"
            if not child_runs_path.exists():
                continue
            config = self._parse_child_runs_md(child_runs_path)
            parent = self._get_parent_id(config)
            if not parent or parent != parent_id:
                continue
            status = self._get_child_status(work_children_path, child_name)
            children.append((child_name, status, config))
        return children

    def _update_child_status(self, parent_id: str, child_name: str, status: str) -> None:
        """Update Status column for child_name in parent's WORK-CHILDREN.md."""
        work_children_path = self.work_dir / parent_id / "WORK-CHILDREN.md"
        if not work_children_path.exists():
            return
        today = datetime.now().strftime('%Y-%m-%d')
        new_lines = []
        for line in work_children_path.read_text().splitlines(keepends=True):
            stripped = line.rstrip('\n')
            if not stripped.startswith('|'):
                new_lines.append(line)
                continue
            cols = stripped.split('|')
            if len(cols) < CH_STATUS + 1:
                new_lines.append(line)
                continue
            if cols[CH_ID].strip() == child_name:
                cols[CH_STATUS] = f" {status} "
                if len(cols) > CH_LAST_UPDATED:
                    cols[CH_LAST_UPDATED] = f" {today} "
                line = '|'.join(cols) + '\n'
            new_lines.append(line)
        work_children_path.write_text(''.join(new_lines))

    def _update_child_budget(self, parent_id: str, child_name: str, budget: str) -> None:
        """Update Budget column for child_name in parent's WORK-CHILDREN.md."""
        work_children_path = self.work_dir / parent_id / "WORK-CHILDREN.md"
        if not work_children_path.exists():
            return
        new_lines = []
        for line in work_children_path.read_text().splitlines(keepends=True):
            stripped = line.rstrip('\n')
            if not stripped.startswith('|'):
                new_lines.append(line)
                continue
            cols = stripped.split('|')
            if len(cols) < CH_BUDGET + 1:
                new_lines.append(line)
                continue
            if cols[CH_ID].strip() == child_name:
                cols[CH_BUDGET] = f" {budget} "
                line = '|'.join(cols) + '\n'
            new_lines.append(line)
        work_children_path.write_text(''.join(new_lines))

    def _update_child_log(self, parent_id: str, child_name: str, log: str) -> None:
        """Update Log column for child_name in parent's WORK-CHILDREN.md."""
        work_children_path = self.work_dir / parent_id / "WORK-CHILDREN.md"
        if not work_children_path.exists():
            return
        new_lines = []
        for line in work_children_path.read_text().splitlines(keepends=True):
            stripped = line.rstrip('\n')
            if not stripped.startswith('|'):
                new_lines.append(line)
                continue
            cols = stripped.split('|')
            if len(cols) < CH_LOG + 1:
                new_lines.append(line)
                continue
            if cols[CH_ID].strip() == child_name:
                cols[CH_LOG] = f" {log} "
                line = '|'.join(cols) + '\n'
            new_lines.append(line)
        work_children_path.write_text(''.join(new_lines))

    def _get_child_budget(self, parent_id: str, child_name: str) -> float:
        """Return budget for a child from WORK-CHILDREN.md Budget column, falling back to max_budget."""
        work_children_path = self.work_dir / parent_id / "WORK-CHILDREN.md"
        if not work_children_path.exists():
            return self.max_budget
        for line in work_children_path.read_text().splitlines():
            stripped = line.rstrip('\n')
            if not stripped.startswith('|'):
                continue
            cols = stripped.split('|')
            if len(cols) < CH_BUDGET + 1:
                continue
            if cols[CH_ID].strip() == child_name:
                raw = cols[CH_BUDGET].strip()
                m = re.match(r'\$\s*([\d.]+)', raw)
                if m:
                    try:
                        return float(m.group(1))
                    except ValueError:
                        pass
                break
        return self.max_budget

    def _validate_note_path_uniqueness(self, parent_id: str, child_name: str) -> tuple[bool, str | None]:
        """Check for duplicate note_path among siblings. Returns (is_unique, conflicting_child_name)."""
        children = self.get_children(parent_id)
        target_note = None
        for cname, _, cfg in children:
            if cname == child_name:
                target_note = cfg.get('note_path', '')
        if not target_note:
            return True, None
        for cname, _, cfg in children:
            if cname == child_name:
                continue
            if cfg.get('note_path', '') == target_note:
                return False, cname
        return True, None

    def _update_parent_work_children(self, parent_id: str) -> None:
        """Rebuild non-status columns of WORK-CHILDREN.md from children's RUNS.md data."""
        children = self.get_children(parent_id)
        if not children:
            return
        work_children_path = self.work_dir / parent_id / "WORK-CHILDREN.md"
        if not work_children_path.exists():
            return
        existing_text = work_children_path.read_text()
        lines = existing_text.splitlines(keepends=True)
        new_lines = []
        in_table = False
        for line in lines:
            stripped = line.rstrip('\n')
            if stripped.startswith('| --') or stripped.startswith('|--'):
                in_table = True
                new_lines.append(line)
                continue
            if in_table and stripped.startswith('|'):
                cols = stripped.split('|')
                if len(cols) < CH_ID + 1:
                    new_lines.append(line)
                    continue
                cname = cols[CH_ID].strip()
                found = False
                for child_name, _, cfg in children:
                    if child_name == cname:
                        title = cfg.get('title', child_name)
                        cols[CH_TITLE] = f" [{title}](children/{child_name}/RUNS.md) "
                        line = '|'.join(cols) + '\n'
                        found = True
                        break
                if not found:
                    continue
                new_lines.append(line)
                continue
            if in_table and not stripped.startswith('|'):
                in_table = False
                new_lines.append(line)
                continue
            new_lines.append(line)
        work_children_path.write_text(''.join(new_lines))

    def process_child(self, parent_id: str, child_name: str) -> None:
        """Process a child agent (research or task). Does NOT touch top-level WORK.md."""
        child_dir = self.work_dir / parent_id / "children" / child_name
        runs_path = child_dir / "RUNS.md"
        config = self._parse_child_runs_md(runs_path)
        child_type = config.get('type', 'research')
        budget = self._get_child_budget(parent_id, child_name)
        today = datetime.now().strftime('%Y-%m-%d')
        ts = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')

        # Determine prompt file and validation
        if child_type == 'research':
            prompt_file = self.child_research_prompt_file
            summary_file = 'research.md'
        elif child_type == 'task':
            prompt_file = self._resolve_prompt("TASK-PROMPT.md")
            summary_file = 'task.md'
        else:
            self._update_child_status(parent_id, child_name, 'needs-review')
            print(f"[{_ts()}] {parent_id}/{child_name}: unknown type '{child_type}' — needs-review")
            return

        if not prompt_file.exists():
            self._update_child_status(parent_id, child_name, 'needs-review')
            print(f"[{_ts()}] {parent_id}/{child_name}: {prompt_file.name} not found — needs-review")
            return

        is_unique, conflict = self._validate_note_path_uniqueness(parent_id, child_name)
        if not is_unique:
            self._update_child_status(parent_id, child_name, 'needs-review')
            print(f"[{_ts()}] {parent_id}/{child_name}: note_path conflict with {conflict} — needs-review")
            return

        run_id = self._generate_run_id(child_name, runs_path=runs_path)
        run_dir = child_dir / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        self._update_child_status(parent_id, child_name, 'running')

        prompt_text = prompt_file.read_text()
        sources = config.get('sources', [])
        sources_str = '\n'.join(f'- {s.strip()}' for s in sources) if sources else '(none)'
        instruction = config.get('instruction', '')
        parent_dir = str(self.work_dir / parent_id)
        item_dir = str(child_dir)
        prompt = (
            f"{self._read_base_prompt()}"
            f"{prompt_text}\n\n"
            f"title: {config.get('title', '')}\n"
            f"note_path: {config.get('note_path', '')}\n"
            f"sources:\n{sources_str}\n"
            f"instruction:\n{instruction}\n"
            f"run_id: {run_id}\n"
            f"\nBACKLINK_TARGET: {parent_id}/CONVERSATION\n"
            f"PARENT_ID: {parent_id}\n"
            f"PARENT_DIR: {parent_dir}\n"
            f"ITEM_ID: {child_name}\n"
            f"WORK_LOOP_DIR: {self.work_dir}\n"
            f"ITEM_DIR: {item_dir}"
        )
        cwd = str(self.work_dir)

        logs_dir = self.work_dir / parent_id / "_logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        log_file = logs_dir / f"{ts}_{parent_id}_{child_name}.log"
        log_link = f"[Log]({parent_id}/_logs/{ts}_{parent_id}_{child_name}.debug)"
        print(f"[{_ts()}] Processing child: {parent_id}/{child_name} (type: {child_type}, budget: ${budget}, run_id: {run_id})")

        exit_code = self._run_harness(prompt, log_file, budget, cwd=cwd, item_id=f"{parent_id}/{child_name}")

        # Check for abort
        current_status = self._get_child_status(
            self.work_dir / parent_id / "WORK-CHILDREN.md", child_name
        )
        self._update_child_log(parent_id, child_name, log_link)

        if current_status == 'abort':
            self._update_child_status(parent_id, child_name, 'abort')
            print(f"[{_ts()}] {parent_id}/{child_name}: aborted by user")
            return

        if exit_code != 0:
            failure = self._classify_failure(f"{parent_id}_{child_name}", ts)
            if failure == "budget":
                budget_label, cause = f"${budget} - EXCEEDED", "budget exceeded"
            else:
                budget_label, cause = f"${budget} - FAILED", "run failed"
            self._update_child_status(parent_id, child_name, 'needs-review')
            self._update_child_budget(parent_id, child_name, budget_label)
            print(f"[{_ts()}] {parent_id}/{child_name}: {cause} — needs-review")
        else:
            self._update_child_budget(parent_id, child_name, f"${budget}")
            summary = f"{child_type.capitalize()} complete"
            summary_path = run_dir / summary_file
            if summary_path.exists():
                rlines = summary_path.read_text().split('\n')
                if len(rlines) > 1:
                    summary = rlines[1].strip('# -').strip()
            self._append_research_run(child_name, run_id, summary, runs_path=runs_path)

            if config.get('schedule'):
                self._update_child_status(parent_id, child_name, 'scheduled')
                print(f"[{_ts()}] {parent_id}/{child_name}: {child_type} complete — scheduled")
            else:
                self._update_child_status(parent_id, child_name, 'done')
                print(f"[{_ts()}] {parent_id}/{child_name}: {child_type} complete — done")

    def resume_running_children(self) -> None:
        """On startup, find running children and handle orphan recovery."""
        for parent_id in self._get_all_item_ids():
            children = self.get_children(parent_id)
            for child_name, child_status, _ in children:
                if child_status == 'running':
                    parent_status = self.get_col(parent_id, COL_STATUS)
                    if parent_status == 'done':
                        self._update_child_status(parent_id, child_name, 'needs-review')
                        print(f"[{_ts()}] {parent_id}/{child_name}: orphan recovery — parent is done, set to needs-review")
                    else:
                        print(f"[{_ts()}] {parent_id}/{child_name}: stale running status — parent agent should handle")

    # -------------------------------------------------------------------------
    # WORK.md child dashboard: report links + needs-attention
    # -------------------------------------------------------------------------

    _ATTENTION_RE = re.compile(r'<!--\s*attention:\s*yes\b(.*?)-->', re.IGNORECASE | re.DOTALL)
    _MARKDOWN_LINK_RE = re.compile(r'\[[^\]]+\]\([^)]+\)')
    _NA_BEGIN = '<!-- NEEDS-ATTENTION:BEGIN -->'
    _NA_END = '<!-- NEEDS-ATTENTION:END -->'

    def _resolve_child_note(self, parent_id: str, config: dict) -> Path | None:
        """Resolve a child's note_path to an absolute Path (or None if unset).

        Child note_path values are stored relative to the parent's `children/` directory,
        so `../context/file.md` resolves to `{parent_id}/context/file.md`.
        """
        note_path = config.get('note_path', '')
        if not note_path:
            return None
        base = self.work_dir / parent_id / "children"
        return (base / note_path).resolve()

    def _child_note_relpath(self, parent_id: str, resolved: Path) -> str:
        """Return a work_dir-relative path for a child note (used for WORK.md links)."""
        try:
            return resolved.relative_to(self.work_dir.resolve()).as_posix()
        except ValueError:
            return str(resolved)

    def _sync_parent_report_links(self, parent_id: str) -> bool:
        """Append one <br>-separated report link per child to the parent's WORK.md Title cell.

        Keeps the first markdown link (the CONVERSATION link) as the base and rebuilds the
        child-report links from scratch. Idempotent: only rewrites the cell when it changes.
        Returns True if the cell was changed.
        """
        children = self.get_children(parent_id)
        links = []
        seen = set()
        for child_name, _status, config in children:
            resolved = self._resolve_child_note(parent_id, config)
            if resolved is None:
                continue
            relpath = self._child_note_relpath(parent_id, resolved)
            if relpath in seen:
                continue
            seen.add(relpath)
            title = config.get('title', child_name)
            links.append(f"[{title}]({relpath})")

        current = self.get_col(parent_id, COL_TITLE)
        base_match = self._MARKDOWN_LINK_RE.search(current)
        base = base_match.group(0) if base_match else (current.split('<br>')[0].strip() or '')
        parts = ([base] if base else []) + links
        desired = '<br>'.join(parts)

        if desired != current:
            self.update_col(parent_id, COL_TITLE, desired)
            return True
        return False

    def _read_child_attention(self, resolved: Path | None) -> str | None:
        """Return the attention reason if a child note is flagged `<!-- attention: yes -->`."""
        if not resolved:
            return None
        note = Path(resolved)
        if not note.exists():
            return None
        try:
            text = note.read_text(errors='replace')
        except OSError:
            return None
        m = self._ATTENTION_RE.search(text)
        if not m:
            return None
        reason = m.group(1).strip().lstrip('—–-: ').strip()
        return reason or 'needs attention'

    def _build_needs_attention_lines(self) -> list[str]:
        """Build the bullet lines for the Needs Attention section."""
        lines = []
        # Top-level items in needs-review (active section only).
        for line in self._read_lines():
            stripped = line.rstrip('\n')
            if stripped.startswith('## Done'):
                break
            if not stripped.startswith('|'):
                continue
            cols = stripped.split('|')
            if not _is_data_row(cols) or cols[COL_STATUS].strip() != 'needs-review':
                continue
            item_id = cols[COL_ID].strip()
            lines.append(f"- **{item_id}** (needs-review). [Open conversation]({item_id}/CONVERSATION.md)")
        # Children that need attention.
        for parent_id in self._get_all_item_ids():
            for child_name, child_status, config in self.get_children(parent_id):
                resolved = self._resolve_child_note(parent_id, config)
                relpath = self._child_note_relpath(parent_id, resolved) if resolved else None
                link = f" [Open report]({relpath})" if relpath else ""
                if child_status == 'needs-review':
                    lines.append(f"- **{parent_id} / {child_name}** (needs-review).{link}")
                else:
                    reason = self._read_child_attention(resolved)
                    if reason:
                        lines.append(f"- **{parent_id} / {child_name}** — {reason}.{link}")
        return lines

    def _find_needs_attention_insert_idx(self, text: str) -> int:
        """Char index to insert the block: before ## Work Items, else ## Done, else end."""
        for marker in ('\n## Work Items', '\n## Done'):
            idx = text.find(marker)
            if idx != -1:
                return idx + 1
        return len(text)

    def _replace_needs_attention_block(self, text: str, block: str) -> str:
        """Insert/replace/remove the marker-fenced Needs Attention block.

        `block` is the full fenced block (incl. markers + trailing newline), or '' to remove.
        """
        begin_idx = text.find(self._NA_BEGIN)
        end_idx = text.find(self._NA_END)
        if begin_idx != -1 and end_idx != -1:
            end_idx += len(self._NA_END)
            if end_idx < len(text) and text[end_idx] != '\n':
                newline_idx = text.find('\n', end_idx)
                end_idx = len(text) if newline_idx == -1 else newline_idx + 1
            while end_idx < len(text) and text[end_idx] == '\n':
                end_idx += 1
            text = text[:begin_idx] + text[end_idx:]
        if not block:
            return text
        insert_idx = self._find_needs_attention_insert_idx(text)
        return text[:insert_idx] + block + text[insert_idx:]

    def _refresh_work_md_dashboard(self) -> None:
        """Maintain child report links and the Needs Attention section in WORK.md.

        Idempotent and write-only-on-change so idle cycles cause no file churn. Never raises.
        """
        if not self.work_file.exists():
            return
        try:
            for parent_id in self._get_all_item_ids():
                if self.get_children(parent_id):
                    self._sync_parent_report_links(parent_id)

            lines = self._build_needs_attention_lines()
            if lines:
                block = (
                    self._NA_BEGIN + "\n"
                    "## Needs Attention\n\n"
                    + "\n".join(lines)
                    + "\n"
                    + self._NA_END + "\n\n"
                )
            else:
                block = ""

            text = self.work_file.read_text()
            new_text = self._replace_needs_attention_block(text, block)
            if new_text != text:
                self._write_lines(new_text.splitlines(keepends=True))
        except Exception as e:
            print(f"[{_ts()}] WARNING: _refresh_work_md_dashboard failed: {e}")

    def _read_run_state(self, item_id: str, run_id: str) -> dict | None:
        state_file = self.work_dir / item_id / "runs" / run_id / "run_state.json"
        if not state_file.exists():
            return None
        try:
            return json.loads(state_file.read_text())
        except (OSError, json.JSONDecodeError):
            return None

    def _write_run_state(self, item_id: str, run_id: str, state: dict) -> None:
        run_dir = self.work_dir / item_id / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "run_state.json").write_text(json.dumps(state, indent=2))

    def build_test_dispatch_script(self, command: str, params: str, run_subdir: str) -> str:
        """Build the .sh dispatch script for a remote machine."""
        cmd_line = f"{command} {params}".strip()
        return (
            "#!/bin/bash\n"
            f"mkdir -p ~/Work-Loop/{run_subdir}\n"
            f"cd ~/Work-Loop/{run_subdir}\n"
            f"{cmd_line}\n"
            "echo $? > .done\n"
        )

    def _dispatch_machine(
        self, item_id: str, run_id: str, location: str, command: str, params: str, is_multi: bool
    ) -> bool:
        """SSH dispatch to one machine. Returns True on success."""
        os_type, user_host, hostname = self._parse_location(location)
        rwd = self.remote_work_dir
        run_subdir = f"{item_id}/runs/{run_id}/{hostname}" if is_multi else f"{item_id}/runs/{run_id}"
        try:
            result = subprocess.run(
                ["ssh", "-o", "ConnectTimeout=10", user_host,
                 f"mkdir -p {rwd}/{run_subdir}"],
                capture_output=True, timeout=30,
            )
            if result.returncode != 0:
                return False
            script_content = self.build_test_dispatch_script(command, params, run_subdir)
            script_name = f".dispatch-{run_id}.sh"
            remote_script = f"{rwd}/{item_id}/{script_name}"
            # Ensure item dir exists remotely
            subprocess.run(
                ["ssh", user_host, f"mkdir -p {rwd}/{item_id}"],
                capture_output=True, timeout=30,
            )
            proc = subprocess.run(
                ["ssh", user_host, f"cat > {remote_script}"],
                input=script_content.encode(),
                capture_output=True, timeout=30,
            )
            if proc.returncode != 0:
                return False
            subprocess.run(
                ["ssh", user_host,
                 f"nohup bash {remote_script} </dev/null >/dev/null 2>&1 &"],
                capture_output=True, timeout=30,
            )
            return True
        except (subprocess.TimeoutExpired, OSError):
            return False

    def _poll_machine_once(
        self, item_id: str, run_id: str, hostname: str, user_host: str, os_type: str,
        is_multi: bool, heartbeat_file: str, state: dict
    ) -> tuple[bool, bool]:
        """Rsync from remote, check .done, detect activity. Returns (done, changed)."""
        run_dir_local = self._run_dir_local(item_id, run_id, hostname, is_multi)
        run_dir_local.mkdir(parents=True, exist_ok=True)
        rwd = self.remote_work_dir
        if is_multi:
            remote_src = f"{user_host}:{rwd}/{item_id}/runs/{run_id}/{hostname}/"
        else:
            remote_src = f"{user_host}:{rwd}/{item_id}/runs/{run_id}/"
        local_dst = str(run_dir_local) + "/"
        try:
            subprocess.run(
                self._rsync_cmd_for_host(os_type, remote_src, local_dst),
                capture_output=True, timeout=60,
            )
        except (subprocess.TimeoutExpired, OSError):
            pass
        if (run_dir_local / ".done").exists():
            return True, True
        if heartbeat_file:
            hb_path = run_dir_local / heartbeat_file
            new_mtime = hb_path.stat().st_mtime if hb_path.exists() else None
            old_mtime = state.setdefault('heartbeat_mtimes', {}).get(hostname)
            # First poll records baseline; only subsequent polls detect change
            changed = old_mtime is not None and new_mtime is not None and new_mtime != old_mtime
            state['heartbeat_mtimes'][hostname] = new_mtime
        else:
            current_count = sum(1 for f in run_dir_local.rglob('*') if f.is_file())
            old_count = state.setdefault('file_counts', {}).get(hostname)
            # First poll records baseline; only subsequent polls detect change
            changed = old_count is not None and current_count > old_count
            state['file_counts'][hostname] = current_count
        return False, changed

    def _continue_polling(self, item_id: str, run_id: str, config: dict, state: dict) -> None:
        """Poll all dispatched machines until all done/timed-out, then fan in."""
        locations = config['locations'] if config['locations'] else (
            [config['location']] if config['location'] else []
        )
        is_multi = bool(config['locations'])
        heartbeat_file = config['heartbeat_file']
        timeout_cycles = config.get('timeout', DEFAULT_TIMEOUT_MIN) * POLL_CYCLES_PER_MIN
        host_to_loc = {self._parse_location(loc)[2]: loc for loc in locations}

        def _pending():
            done_s = set(state['done'])
            timed_s = set(state['timed_out'])
            failed_s = set(state['failed_dispatch'])
            return [h for h in state['dispatched'] if h not in done_s and h not in timed_s and h not in failed_s]

        while _pending():
            for hostname in list(_pending()):
                loc = host_to_loc.get(hostname)
                if not loc:
                    state['timed_out'].append(hostname)
                    continue
                os_type, user_host, _ = self._parse_location(loc)
                state.setdefault('no_update_counts', {}).setdefault(hostname, 0)
                done, changed = self._poll_machine_once(
                    item_id, run_id, hostname, user_host, os_type,
                    is_multi, heartbeat_file, state
                )
                if done:
                    state['done'].append(hostname)
                    print(f"[{_ts()}] {item_id}/{run_id}: {hostname} completed")
                elif changed:
                    state['no_update_counts'][hostname] = 0
                else:
                    state['no_update_counts'][hostname] += 1
                    if state['no_update_counts'][hostname] >= timeout_cycles:
                        state['timed_out'].append(hostname)
                        print(f"[{_ts()}] {item_id}/{run_id}: {hostname} timed out")
            self._write_run_state(item_id, run_id, state)
            if _pending():
                print(
                    f"\r[{_ts()}] {item_id}/{run_id}: "
                    f"{len(state['done'])} done, "
                    f"{len(state['timed_out'])} timed out, "
                    f"{len(_pending())} pending...   ",
                    end="", flush=True
                )
                time.sleep(POLL_INTERVAL_S)

        print(f"\n[{_ts()}] {item_id}/{run_id}: all machines complete, running fan-in")
        self._fan_in(item_id, run_id, config, state)

    def _run_aggregation_script(self, run_dir: Path, script_path: str) -> int:
        """Run aggregation script with run_dir as argument. Returns exit code."""
        try:
            result = subprocess.run(
                ["python3", script_path, str(run_dir)],
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                (run_dir / "aggregation_error.log").write_text(
                    result.stdout + result.stderr
                )
            return result.returncode
        except OSError as e:
            (run_dir / "aggregation_error.log").write_text(str(e))
            return 1

    def _run_analysis_prompt_for_run(
        self, item_id: str, run_id: str, analysis_prompt: str, budget: float
    ) -> int:
        ts = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        item_dir = self.work_dir / item_id
        item_dir.mkdir(parents=True, exist_ok=True)
        (item_dir / "_logs").mkdir(parents=True, exist_ok=True)
        log_file = item_dir / "_logs" / f"{ts}_{item_id}-analysis.log"
        actual_prompt = analysis_prompt.replace('{run-id}', run_id)
        prompt = f"{actual_prompt}\n\nITEM_ID: {item_id}\nRUN_ID: {run_id}"
        return self._run_harness(prompt, log_file, budget, cwd=str(self.work_dir / item_id))

    def _fan_in(self, item_id: str, run_id: str, config: dict, state: dict) -> None:
        """Aggregate results, run analysis, update statuses."""
        run_dir = self.work_dir / item_id / "runs" / run_id
        budget = self.get_item_budget(item_id)
        has_failures = bool(state.get('timed_out')) or bool(state.get('failed_dispatch'))
        agg_script = config.get('aggregation_script', '')
        if agg_script:
            if self._run_aggregation_script(run_dir, agg_script) != 0:
                self._update_runs_md_row_status(item_id, run_id, 'needs-review')
                self.update_col(item_id, COL_STATUS, 'needs-review')
                self.update_col(item_id, COL_LAST_UPDATED, datetime.now().strftime('%Y-%m-%d'))
                print(f"[{_ts()}] {item_id}/{run_id}: aggregation script failed")
                return
        analysis_prompt = config.get('analysis_prompt', '')
        if analysis_prompt:
            if self._run_analysis_prompt_for_run(item_id, run_id, analysis_prompt, budget) != 0:
                has_failures = True
        final_status = 'needs-review' if has_failures else 'success'
        self._update_runs_md_row_status(item_id, run_id, final_status)
        if final_status == 'success' and config.get('schedule'):
            self.update_col(item_id, COL_STATUS, 'scheduled')
        elif final_status == 'success':
            self.update_col(item_id, COL_STATUS, 'success')
        else:
            self.update_col(item_id, COL_STATUS, 'needs-review')
        self.update_col(item_id, COL_LAST_UPDATED, datetime.now().strftime('%Y-%m-%d'))
        print(f"[{_ts()}] {item_id}/{run_id}: fan-in complete, status={final_status}")

    def process_script_item(self, item_id: str) -> None:
        """Dispatch, poll, and fan-in for a ready/scheduled script item."""
        config = self._parse_runs_md_config(item_id)
        locations = config['locations'] if config['locations'] else (
            [config['location']] if config['location'] else []
        )
        if not locations:
            print(f"[{_ts()}] {item_id}: no Location/Locations in RUNS.md — skipping")
            self.update_col(item_id, COL_STATUS, 'needs-review')
            return
        run_id = self._generate_run_id(item_id)
        title = config['params'] if config['params'] else run_id
        self.update_col(item_id, COL_STATUS, 'running')
        self.update_col(item_id, COL_LAST_UPDATED, datetime.now().strftime('%Y-%m-%d'))
        self._append_runs_md_row(item_id, run_id, title, 'running')
        is_multi = bool(config['locations'])
        state: dict = {
            'dispatched': [], 'done': [], 'timed_out': [],
            'failed_dispatch': [], 'no_update_counts': {}, 'heartbeat_mtimes': {},
        }
        for loc in locations:
            _, _, hostname = self._parse_location(loc)
            print(f"[{_ts()}] {item_id}/{run_id}: dispatching to {hostname}")
            if self._dispatch_machine(item_id, run_id, loc, config['command'], config['params'], is_multi):
                state['dispatched'].append(hostname)
            else:
                state['failed_dispatch'].append(hostname)
                print(f"[{_ts()}] {item_id}/{run_id}: dispatch failed for {hostname}")
        self._write_run_state(item_id, run_id, state)
        if not state['dispatched']:
            self._update_runs_md_row_status(item_id, run_id, 'needs-review')
            self.update_col(item_id, COL_STATUS, 'needs-review')
            return
        self._continue_polling(item_id, run_id, config, state)

    def get_scheduled_items(self) -> list[str]:
        """Return item IDs whose cron fires now (both script and research items)."""
        now = datetime.now()
        items = []
        for line in self._read_lines():
            stripped = line.rstrip('\n')
            if stripped.startswith('## Done'):
                break
            if not stripped.startswith('|'):
                continue
            cols = stripped.split('|')
            if not _is_data_row(cols):
                continue
            item_id = cols[COL_ID].strip()
            if cols[COL_STATUS].strip() != 'scheduled':
                continue
            item_type = self.get_item_type(item_id)
            if item_type not in ('script', 'research'):
                continue
            config = self._parse_runs_md(item_id)
            if self._cron_should_run(config.get('schedule', ''), now):
                items.append(item_id)
        return items

    def resume_running_script_items(self) -> None:
        """On startup, find running script items and resume polling."""
        for line in self._read_lines():
            stripped = line.rstrip('\n')
            if stripped.startswith('## Done'):
                break
            if not stripped.startswith('|'):
                continue
            cols = stripped.split('|')
            if not _is_data_row(cols):
                continue
            item_id = cols[COL_ID].strip()
            if cols[COL_STATUS].strip() != 'running':
                continue
            if self.get_item_type(item_id) != 'script':
                continue
            run_id = self._find_latest_runs_md_run(item_id, 'running')
            if not run_id:
                continue
            config = self._parse_runs_md_config(item_id)
            state = self._read_run_state(item_id, run_id)
            if state is None:
                state = {
                    'dispatched': [], 'done': [], 'timed_out': [],
                    'failed_dispatch': [], 'no_update_counts': {}, 'heartbeat_mtimes': {},
                }
                print(f"[{_ts()}] {item_id}/{run_id}: run_state.json missing — treating as all-timed-out")
                self._fan_in(item_id, run_id, config, state)
            else:
                print(f"[{_ts()}] {item_id}/{run_id}: resuming polling")
                self._continue_polling(item_id, run_id, config, state)

    # -------------------------------------------------------------------------
    # Main loop
    # -------------------------------------------------------------------------

    def run(self, once: bool = False) -> None:
        def _handle_sigint(sig, frame):
            print(f"\n[{_ts()}] Work loop stopped.")
            self._stop = True
            sys.exit(0)

        signal.signal(signal.SIGINT, _handle_sigint)

        print(f"[{_ts()}] Work loop started. Default budget: ${self.max_budget} (override per item via Budget column). Press Ctrl+C to stop.")

        self.resume_running_script_items()
        self.resume_running_children()

        idle_shown = False

        while not self._stop:
            self.move_done_items()
            self.check_stalled_remotes()
            self._refresh_work_md_dashboard()

            for item_id in self.get_new_items():
                self.initialize_new_item(item_id)

            # Promote scheduled items whose cron fires now
            for item_id in self.get_scheduled_items():
                self.update_col(item_id, COL_STATUS, 'ready')

            # Promote scheduled children whose cron fires now
            now = datetime.now()
            for parent_id in self._get_all_item_ids():
                children = self.get_children(parent_id)
                for child_name, child_status, child_config in children:
                    if child_status == 'scheduled' and child_config.get('schedule'):
                        if self._cron_should_run(child_config['schedule'], now):
                            self._update_child_status(parent_id, child_name, 'ready')

            ready = self.get_ready_items()

            # Check if any children are ready (for idle detection)
            def _any_children_ready():
                for parent_id in self._get_all_item_ids():
                    for _, status, _ in self.get_children(parent_id):
                        if status == 'ready':
                            return True
                return False

            if not ready and not _any_children_ready():
                print(f"\r[{_ts()}] Work loop idle...   ", end="", flush=True)
                idle_shown = True
                time.sleep(5)
                continue

            if idle_shown:
                print("")
                idle_shown = False

            for item_id in ready:
                item_type = self.get_item_type(item_id)

                if item_type == 'research':
                    budget = self.get_item_budget(item_id)
                    self.process_local(item_id, budget)
                    print("---")
                    continue

                if item_type == 'script':
                    print(f"[{_ts()}] Processing script item: {item_id}")
                    self.process_script_item(item_id)
                    print("---")
                    continue

                location = self.get_col(item_id, COL_LOCATION)
                budget = self.get_item_budget(item_id)
                ts = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')

                if location != "local":
                    mode = self.get_col(item_id, COL_STATUS)
                    print(f"[{_ts()}] Dispatching to {location}: {item_id} (mode: {mode}, budget: ${budget})")
                    self.update_col(item_id, COL_STATUS, "in-progress")
                    self.update_col(item_id, COL_LOG, f"[Log]({item_id}/_logs/{ts}_{item_id}.debug)")
                    self.dispatch_remote(item_id, ts, location, budget, mode=mode)
                    self.wait_for_remote(item_id, ts, location, budget, mode=mode)
                else:
                    self.process_local(item_id, budget)

                print("---")

            # Process children after top-level items
            for parent_id in self._get_all_item_ids():
                children = self.get_children(parent_id)
                if not children:
                    continue
                processed_names = {c[0] for c in children}
                for child_name, child_status, _ in children:
                    if child_status == 'ready':
                        self.process_child(parent_id, child_name)
                # Re-scan for newly created children
                new_children = self.get_children(parent_id)
                newly_discovered = {c[0] for c in new_children} - processed_names
                for nd_name in newly_discovered:
                    nd_status = self._get_child_status(
                        self.work_dir / parent_id / "WORK-CHILDREN.md", nd_name
                    )
                    if nd_status == 'ready':
                        self.process_child(parent_id, nd_name)

            if once:
                break


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ts() -> str:
    return datetime.now().strftime('%H:%M:%S')


def _run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=check)


def main() -> None:
    # Discover config.json: look in SCRIPT_DIR first, then parent of work_dir
    script_dir = Path(__file__).parent
    config_path = script_dir / "config.json"
    if not config_path.exists():
        # Try to find it relative to where work_dir might be
        home_work = Path.home() / "MyNotebook" / "Work-Loop-Items"
        if home_work.exists():
            config_path = script_dir / "config.json"
    cfg = load_config(config_path)
    wl = WorkLoop(cfg, script_dir=script_dir)
    wl.run()


if __name__ == "__main__":
    main()
