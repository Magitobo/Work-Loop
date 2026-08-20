import json
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path

from .constants import *
from .utils import _is_data_row, _ts


class ScriptsMixin:
    def process_script_item(self, item_id: str) -> None:
        """Dispatch, poll, and fan-in for a ready/scheduled script item."""
        config = self._parse_runs_md(item_id)
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
            config = self._parse_runs_md(item_id)
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
        """Insert a new row to RUNS.md run history table with recent on top."""
        runs_file = self.work_dir / item_id / "RUNS.md"
        today = datetime.now().strftime('%Y-%m-%d %H:%M')
        log_link = f"[Log](runs/{run_id}/)"
        row = f"| {run_id} | {title} | {status} | {today} | {log_link} |\n"
        text = runs_file.read_text() if runs_file.exists() else ""
        lines = text.splitlines(keepends=True)
        table_sep_idx = -1
        for i, line in enumerate(lines):
            stripped = line.lstrip()
            if stripped.startswith('| --') or stripped.startswith('|--'):
                if line.count('|') >= 4:
                    table_sep_idx = i
                    break
        if table_sep_idx < 0:
            header = "\n| ID | Title | Status | Last Updated | Log |\n|---|---|---|---|---|\n"
            text += header + row
            runs_file.write_text(text)
        else:
            lines.insert(table_sep_idx + 1, row)
            runs_file.write_text("".join(lines))

    def _create_run_dir(self, item_id: str, run_id: str) -> Path:
        """Create runs/{run_id}/ directory and return its path."""
        run_dir = self.work_dir / item_id / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    def _append_research_run(self, item_id: str, run_id: str, summary: str, status: str = 'done', runs_path: Path | None = None) -> None:
        """Insert a new row to RUNS.md run history table for research/task items with recent on top."""
        runs_file = runs_path if runs_path is not None else self.work_dir / item_id / "RUNS.md"
        today = datetime.now().strftime('%Y-%m-%d %H:%M')
        log_link = f"[Log](runs/{run_id}/)"
        summary_text = summary.strip() or f"{run_id} run"
        summary_link = f"[{summary_text}](runs/{run_id}/)"
        row = f"| {run_id} | {summary_link} | {status} | {today} | {log_link} |\n"
        text = runs_file.read_text() if runs_file.exists() else ""
        lines = text.splitlines(keepends=True)
        table_sep_idx = -1
        for i, line in enumerate(lines):
            stripped = line.lstrip()
            if stripped.startswith('| --') or stripped.startswith('|--'):
                if line.count('|') >= 4:
                    table_sep_idx = i
                    break
        if table_sep_idx < 0:
            header = "\n| ID | Summary | Status | Last Updated | Log |\n|---|---|---|---|---|\n"
            text += header + row
            runs_file.write_text(text)
        else:
            lines.insert(table_sep_idx + 1, row)
            runs_file.write_text("".join(lines))

    def _update_runs_md_row_status(self, item_id: str, run_id: str, status: str, runs_path: Path | None = None) -> None:
        """Update Status and Last Updated for a given run_id in RUNS.md."""
        runs_file = runs_path if runs_path is not None else self.work_dir / item_id / "RUNS.md"
        if not runs_file.exists():
            return
        today = datetime.now().strftime('%Y-%m-%d %H:%M')
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
                if latest is None or run_id > latest:
                    latest = run_id
        return latest

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

    def _parse_config_block(self, text: str) -> dict:
        """Parse YAML frontmatter (---) or ## Config block from text, return normalized dict."""
        config = self._empty_config()
        fm_match = re.match(r'^---\s*\n(.*?)\n---(?:\s*\n|\Z)', text, re.DOTALL)
        if fm_match:
            block_text = fm_match.group(1)
        else:
            m = re.search(r'^## Config\s*\n(.*?)(?=^##|\Z)', text, re.MULTILINE | re.DOTALL)
            if not m:
                return config
            block_text = m.group(1)

        in_locations = False
        in_sources = False
        for line in block_text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith('#'):
                continue
            if in_locations and (line.startswith('  ') or stripped.startswith('- ')):
                loc = stripped.lstrip('- ').strip().strip('`').strip('\'"')
                if loc:
                    config['locations'].append(loc)
                continue
            if in_sources and (line.startswith('  ') or stripped.startswith('- ')):
                src = stripped.lstrip('- ').strip().strip('`').strip('\'"')
                if src:
                    config['sources'].append(src)
                continue
            in_locations = False
            in_sources = False
            if ':' not in line:
                continue
            key, _, val = line.partition(':')
            key_n = key.strip().lower().replace(' ', '_').replace('-', '_')
            val = val.strip().strip('`').strip('\'"')
            if val.lower() in ('null', 'none', '~'):
                val = ''
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
                config['aggregation_script'] = val
            elif key_n == 'analysis_prompt':
                config['analysis_prompt'] = val
            elif key_n == 'type':
                config['type'] = val
            elif key_n == 'title':
                config['title'] = val
            elif key_n in ('living_note_path', 'note_path'):
                config['living_note_path'] = val
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
        if m:
            config['instruction'] = m.group(1).strip()
        elif text.startswith('---'):
            fm_end = re.search(r'^---\s*\n.*?\n---\s*\n(.*)', text, re.DOTALL)
            config['instruction'] = fm_end.group(1).strip() if fm_end else ''
        else:
            config['instruction'] = ''
        return config

    def _empty_config(self) -> dict:
        """Return a default/empty config dict."""
        return {
            'command': '', 'params': '', 'schedule': '',
            'location': '', 'locations': [],
            'heartbeat_file': '', 'timeout': DEFAULT_TIMEOUT_MIN,
            'aggregation_script': '', 'analysis_prompt': '',
            'type': '', 'title': '', 'living_note_path': '', 'note_path': '', 'sources': [],
            'parent': '', 'instruction': '',
        }

