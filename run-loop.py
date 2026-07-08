#!/usr/bin/env python3
"""Work-loop processor: runs Claude on ready work items, local or remote."""

import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

WORK_DIR = Path.home() / "MyNotebook" / "Work-Loop-Items"
SCRIPT_DIR = Path(__file__).parent
MAX_BUDGET = 10.00
REMOTE_WORK_DIR = "~/Work-Loop"

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
    def __init__(self, work_dir: Path, max_budget: float, script_dir: Path | None = None):
        self.work_dir = work_dir
        self.script_dir = script_dir if script_dir is not None else work_dir
        self.max_budget = max_budget
        self.remote_work_dir = REMOTE_WORK_DIR
        self.work_file = work_dir / "WORK.md"
        self.prompt_file = self.script_dir / "LOOP-PROMPT.md"
        self.log_dir = work_dir / ".logs"
        self._stop = False

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
    TRIGGER_STATUSES = {'ready', 'analyze', 'implement', 'resolved'}

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

        if self.get_item_type(item_id) == 'script':
            config = self._parse_runs_md_config(item_id)
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
    # Claude execution
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

    def run_claude(self, prompt: str, log_file: Path, budget: float, cwd: str | None = None) -> int:
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
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=cwd or str(self.work_dir),
        )
        with open(log_file, 'wb') as lf:
            while True:
                chunk = proc.stdout.read(4096)
                if not chunk:
                    break
                sys.stdout.buffer.write(chunk)
                sys.stdout.buffer.flush()
                lf.write(chunk)
        proc.wait()
        return proc.returncode

    def prepend_abort_notice(self, item_id: str, date_str: str, budget: float, cause: str = "budget exceeded") -> None:
        conv_file = self.work_dir / item_id / "CONVERSATION.md"
        if not conv_file.exists():
            return
        existing = conv_file.read_text()
        notice = f"## {date_str} | Script — Run aborted: {cause} (${budget})\n\n"
        conv_file.write_text(notice + existing)

    def _classify_failure(self, item_id: str, ts_str: str) -> str:
        """Return 'auth', 'budget', or 'unknown' by inspecting the log file."""
        log_file = self.log_dir / f"{ts_str}_{item_id}.log"
        if not log_file.exists():
            return "unknown"
        try:
            lower = log_file.read_text(errors='replace').lower()
        except OSError:
            return "unknown"
        if any(p in lower for p in ("apikeyhelper failed", "no valid kerberos", "failed to authenticate")):
            return "auth"
        if any(p in lower for p in ("budget", "cost limit", "exceeded")):
            return "budget"
        return "unknown"

    # -------------------------------------------------------------------------
    # Local processing
    # -------------------------------------------------------------------------

    def process_local(self, item_id: str, budget: float) -> None:
        self._auto_init_conversation(item_id)
        today = datetime.now().strftime('%Y-%m-%d')
        ts = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        log_file = self.log_dir / f"{ts}_{item_id}.log"
        log_link = f"[Log](.logs/{ts}_{item_id}.debug)"

        mode = self.get_col(item_id, COL_STATUS)  # read trigger status BEFORE overwriting
        self.update_col(item_id, COL_STATUS, "in-progress")

        if mode == "implement":
            impl_prompt_file = self.script_dir / "IMPL-PROMPT.md"
            if impl_prompt_file.exists():
                prompt_text = impl_prompt_file.read_text()
                cwd = self.extract_work_dir(item_id)
            else:
                prompt_text = self.prompt_file.read_text()
                cwd = str(self.work_dir)
        elif mode == "resolved":
            resolve_prompt_file = self.script_dir / "RESOLVE-PROMPT.md"
            if resolve_prompt_file.exists():
                prompt_text = resolve_prompt_file.read_text()
            else:
                prompt_text = self.prompt_file.read_text()
            cwd = str(self.work_dir)
        else:
            prompt_text = self.prompt_file.read_text()
            cwd = str(self.work_dir)

        item_dir = str(self.work_dir / item_id)
        prompt = (
            f"{prompt_text}\n\n"
            f"ITEM_ID: {item_id}\n"
            f"WORK_LOOP_DIR: {self.work_dir}\n"
            f"ITEM_DIR: {item_dir}"
        )

        print(f"[{_ts()}] Processing: {item_id} (mode: {mode}, budget: ${budget}, cwd: {cwd})")
        exit_code = self.run_claude(prompt, log_file, budget, cwd=cwd)

        self.update_col(item_id, COL_LAST_UPDATED, today)
        self.update_col(item_id, COL_LOG, log_link)

        if exit_code != 0:
            failure = self._classify_failure(item_id, ts)
            if failure == "auth":
                budget_label, cause, msg = f"${budget} - AUTH-EXPIRED", "Kerberos auth expired", f"[{_ts()}] {item_id}: Kerberos auth expired — marked needs-review"
            else:
                budget_label, cause, msg = f"${budget} - EXCEEDED", "budget exceeded", f"[{_ts()}] {item_id}: budget exceeded — marked needs-review"
            self.update_col(item_id, COL_STATUS, "needs-review")
            self.update_col(item_id, COL_BUDGET, budget_label)
            self.prepend_abort_notice(item_id, today, budget, cause)
            print(msg)
        else:
            self.update_col(item_id, COL_BUDGET, f"${budget}")
            if mode == "resolved":
                self._move_row_to_done(item_id)
                print(f"[{_ts()}] {item_id}: resolved — moved to Done section")
            else:
                print(f"[{_ts()}] {item_id}: completed")

    # -------------------------------------------------------------------------
    # Remote launcher
    # -------------------------------------------------------------------------

    def build_launcher(self, item_id: str, ts_str: str, budget: float, mode: str = "analyze", work_dir: str | None = None) -> str:
        rwd = self.remote_work_dir
        if mode == "implement":
            prompt_file = "IMPL-PROMPT.md"
            extra_vars = f"$'\\nITEM_ID: {item_id}\\nWORK_LOOP_DIR: {rwd}\\nITEM_DIR: {rwd}/{item_id}'"
            rwd_capture = 'RWD="$(pwd)"\n'
            cd_work = f"cd {work_dir}\n" if work_dir else ""
            debug_flag = f'--debug-file "$RWD/.logs/{ts_str}_{item_id}.debug" '
            log_redir = f' > "$RWD/.logs/{ts_str}_{item_id}.log" 2>&1\n'
            done_write = f'echo $? > "$RWD/{item_id}/.done"\n'
        elif mode == "resolved":
            prompt_file = "RESOLVE-PROMPT.md"
            extra_vars = f"$'\\nITEM_ID: {item_id}'"
            rwd_capture = ""
            cd_work = ""
            debug_flag = f'--debug-file ".logs/{ts_str}_{item_id}.debug" '
            log_redir = f' > ".logs/{ts_str}_{item_id}.log" 2>&1\n'
            done_write = f'echo $? > "{item_id}/.done"\n'
        else:
            prompt_file = "LOOP-PROMPT.md"
            extra_vars = f"$'\\nITEM_ID: {item_id}'"
            rwd_capture = ""
            cd_work = ""
            debug_flag = f'--debug-file ".logs/{ts_str}_{item_id}.debug" '
            log_redir = f' > ".logs/{ts_str}_{item_id}.log" 2>&1\n'
            done_write = f'echo $? > "{item_id}/.done"\n'
        return (
            "#!/bin/bash\n"
            # nvm is initialized in .bashrc which non-interactive SSH sessions skip.
            # Load it explicitly so claude is on PATH regardless of shell mode.
            'export NVM_DIR="$HOME/.nvm"\n'
            '[ -s "$NVM_DIR/nvm.sh" ] && \\. "$NVM_DIR/nvm.sh"\n'
            f"cd {rwd}\n"
            "mkdir -p .logs\n"
            f"{rwd_capture}"
            f'PROMPT="$(cat {prompt_file})"{extra_vars}\n'
            f"{cd_work}"
            f'claude --print --permission-mode auto --max-budget-usd {budget} {debug_flag}"$PROMPT"'
            f"{log_redir}"
            f"{done_write}"
        )

    # -------------------------------------------------------------------------
    # Remote dispatch
    # -------------------------------------------------------------------------

    def dispatch_remote(self, item_id: str, ts_str: str, remote_host: str, budget: float, mode: str = "analyze") -> None:
        self._auto_init_conversation(item_id)
        rwd = self.remote_work_dir
        _run(["ssh", remote_host, f"rm -rf {rwd} && mkdir -p {rwd}/.logs"])

        item_dir = self.work_dir / item_id
        _run(["rsync", "-avz", "--delete", "--exclude=.done", f"{item_dir}/", f"{remote_host}:{rwd}/{item_id}/"])
        _run(["rsync", "-avz", str(self.prompt_file), f"{remote_host}:{rwd}/"])

        if mode == "implement":
            impl_prompt_file = self.script_dir / "IMPL-PROMPT.md"
            if impl_prompt_file.exists():
                _run(["rsync", "-avz", str(impl_prompt_file), f"{remote_host}:{rwd}/"])
        elif mode == "resolved":
            resolve_prompt_file = self.script_dir / "RESOLVE-PROMPT.md"
            if resolve_prompt_file.exists():
                _run(["rsync", "-avz", str(resolve_prompt_file), f"{remote_host}:{rwd}/"])

        settings_file = self.script_dir / ".claude" / "settings.json"
        if settings_file.exists():
            _run(["ssh", remote_host, f"mkdir -p {rwd}/.claude"])
            _run(["rsync", "-avz", str(settings_file), f"{remote_host}:{rwd}/.claude/"])

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
            mode='w', prefix=f".claude-launch-{item_id}-", suffix=".sh", delete=False
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
        log_link = f"[Log](.logs/{ts_str}_{item_id}.debug)"

        item_dir = self.work_dir / item_id
        _run(["rsync", "-avz", "--delete", "--exclude=.done", f"{remote_host}:{rwd}/{item_id}/", f"{item_dir}/"])
        _run([
            "rsync", "-avz",
            f"{remote_host}:{rwd}/.logs/{ts_str}_{item_id}.log",
            str(self.log_dir) + "/",
        ], check=False)
        _run([
            "rsync", "-avz",
            f"{remote_host}:{rwd}/.logs/{ts_str}_{item_id}.debug",
            str(self.log_dir) + "/",
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
            if failure == "auth":
                budget_label, cause, msg = f"${budget} - AUTH-EXPIRED", "Kerberos auth expired", f"[{_ts()}] {item_id}: Kerberos auth expired — synced back, marked needs-review"
            else:
                budget_label, cause, msg = f"${budget} - EXCEEDED", "budget exceeded", f"[{_ts()}] {item_id}: remote budget exceeded — synced back, marked needs-review"
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

    def _remote_has_kerberos(self, remote_host: str) -> bool:
        """Return True if the remote host has a valid Kerberos ticket."""
        result = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=5", remote_host, "klist -s"],
            capture_output=True,
        )
        return result.returncode == 0

    def _ts_str_from_log_col(self, item_id: str, remote_host: str) -> str | None:
        """Return the dispatch ts_str for item_id, from Log column or by globbing the remote."""
        log_raw = self.get_col(item_id, COL_LOG)
        m = re.search(
            r'\.logs/(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})_' + re.escape(item_id) + r'\.(log|debug)',
            log_raw,
        )
        if m:
            return m.group(1)
        # Fallback for dispatches made before this fix: find the log on the remote
        rwd = self.remote_work_dir
        result = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=5", remote_host,
             f"ls {rwd}/.logs/*_{item_id}.debug 2>/dev/null | head -1 || ls {rwd}/.logs/*_{item_id}.log 2>/dev/null | head -1"],
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
        """Return 'script' if RUNS.md exists for this item, else 'conversation'."""
        return 'script' if (self.work_dir / item_id / "RUNS.md").exists() else 'conversation'

    def _parse_runs_md_config(self, item_id: str) -> dict:
        """Parse the ## Config block from RUNS.md, return normalized dict."""
        config = {
            'command': '', 'params': '', 'schedule': '',
            'location': '', 'locations': [],
            'heartbeat_file': '', 'timeout': DEFAULT_TIMEOUT_MIN,
            'aggregation_script': '', 'analysis_prompt': '',
        }
        runs_file = self.work_dir / item_id / "RUNS.md"
        if not runs_file.exists():
            return config
        text = runs_file.read_text()
        m = re.search(r'^## Config\s*\n(.*?)(?=^##|\Z)', text, re.MULTILINE | re.DOTALL)
        if not m:
            return config
        in_locations = False
        for line in m.group(1).splitlines():
            stripped = line.strip()
            if not stripped:
                in_locations = False
                continue
            if in_locations and line.startswith('  '):
                loc = stripped.strip('`')
                if loc:
                    config['locations'].append(loc)
                continue
            in_locations = False
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
        return config

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

    def _generate_run_id(self, item_id: str) -> str:
        """Generate YYYYMMDD-NNN run ID by scanning existing RUNS.md rows."""
        today = datetime.now().strftime('%Y%m%d')
        max_n = 0
        runs_file = self.work_dir / item_id / "RUNS.md"
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

    def _update_runs_md_row_status(self, item_id: str, run_id: str, status: str) -> None:
        """Update Status and Last Updated for a given run_id in RUNS.md."""
        runs_file = self.work_dir / item_id / "RUNS.md"
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

    def _find_latest_runs_md_run(self, item_id: str, status: str | None = None) -> str | None:
        """Return the latest run_id with given status (None = any)."""
        runs_file = self.work_dir / item_id / "RUNS.md"
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
        log_file = self.log_dir / f"{ts}_{item_id}-analysis.log"
        actual_prompt = analysis_prompt.replace('{run-id}', run_id)
        prompt = f"{actual_prompt}\n\nITEM_ID: {item_id}\nRUN_ID: {run_id}"
        return self.run_claude(prompt, log_file, budget, cwd=str(self.work_dir / item_id))

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
        for loc in locations:
            _, user_host, _ = self._parse_location(loc)
            if not self._remote_has_kerberos(user_host):
                self.update_col(item_id, COL_STATUS, 'blocked')
                print(f"[{_ts()}] {item_id}: Kerberos expired on {user_host} — marked blocked")
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

    def get_scheduled_script_items(self) -> list[str]:
        """Return script item IDs whose Schedule cron fires now (status: scheduled)."""
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
            if self.get_item_type(item_id) != 'script':
                continue
            config = self._parse_runs_md_config(item_id)
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
        self.log_dir.mkdir(parents=True, exist_ok=True)

        print(f"[{_ts()}] Work loop started. Default budget: ${self.max_budget} (override per item via Budget column). Press Ctrl+C to stop.")

        self.resume_running_script_items()

        idle_shown = False

        while not self._stop:
            self.move_done_items()
            self.check_stalled_remotes()

            for item_id in self.get_new_items():
                self.initialize_new_item(item_id)

            # Promote scheduled script items whose cron fires now
            for item_id in self.get_scheduled_script_items():
                self.update_col(item_id, COL_STATUS, 'ready')

            ready = self.get_ready_items()

            if not ready:
                print(f"\r[{_ts()}] Work loop idle...   ", end="", flush=True)
                idle_shown = True
                time.sleep(5)
                continue

            if idle_shown:
                print("")
                idle_shown = False

            kerberos_ok: dict[str, bool] = {}

            for item_id in ready:
                if self.get_item_type(item_id) == 'script':
                    print(f"[{_ts()}] Processing script item: {item_id}")
                    self.process_script_item(item_id)
                    print("---")
                    continue

                location = self.get_col(item_id, COL_LOCATION)
                budget = self.get_item_budget(item_id)
                ts = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')

                if location != "local":
                    if location not in kerberos_ok:
                        kerberos_ok[location] = self._remote_has_kerberos(location)
                    if not kerberos_ok[location]:
                        self.update_col(item_id, COL_STATUS, "blocked")
                        print(f"[{_ts()}] {item_id}: Kerberos ticket expired on {location} — marked blocked (run: kinit on {location}, then set ready)")
                        continue
                    mode = self.get_col(item_id, COL_STATUS)
                    print(f"[{_ts()}] Dispatching to {location}: {item_id} (mode: {mode}, budget: ${budget})")
                    self.update_col(item_id, COL_STATUS, "in-progress")
                    self.update_col(item_id, COL_LOG, f"[Log](.logs/{ts}_{item_id}.debug)")
                    self.dispatch_remote(item_id, ts, location, budget, mode=mode)
                    self.wait_for_remote(item_id, ts, location, budget, mode=mode)
                else:
                    self.process_local(item_id, budget)

                print("---")

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
    wl = WorkLoop(WORK_DIR, MAX_BUDGET, script_dir=SCRIPT_DIR)
    wl.run()


if __name__ == "__main__":
    main()
