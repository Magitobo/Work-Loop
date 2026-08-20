import os
import re
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path

from .constants import *
from .utils import _is_data_row, _run, _ts


class RemoteMixin:
    def dispatch_remote(self, item_id: str, ts_str: str, remote_host: str, budget: float, mode: str = "analyze") -> None:
        self._auto_init_conversation(item_id)
        self.update_col(item_id, COL_STATUS, "in-progress")
        self._inject_or_update_action_callout(
            item_id,
            "in-progress",
            budget=budget,
            last_run_ts=datetime.now().strftime('%Y-%m-%d %H:%M'),
            log_link=f"[Log](_logs/{ts_str}_{item_id}.log)",
        )
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
            _run(["rsync", "-avz", "--exclude=node_modules", "--exclude=.DS_Store", str(agent_dir) + "/", f"{remote_host}:{rwd}/{self.harness.agent_dir_name()}/"])

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

    def _sync_back_remote(
        self, item_id: str, ts_str: str, remote_host: str, budget: float, exit_str: str, mode: str = "analyze"
    ) -> None:
        """Sync files back from a completed remote job, update WORK.md, clean up remote."""
        rwd = self.remote_work_dir
        today = datetime.now().strftime('%Y-%m-%d')
        log_link = f"[Log]({item_id}/_logs/{ts_str}_{item_id}.log)"
        note_log_link = f"[Log](_logs/{ts_str}_{item_id}.log)"

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
            self._inject_or_update_action_callout(item_id, "needs-review", budget, log_link=note_log_link)
            print(msg)
        else:
            self.update_col(item_id, COL_BUDGET, f"${budget}")
            if mode == "resolved":
                self._move_row_to_done(item_id)
                self._inject_or_update_action_callout(item_id, "done", budget, log_link=note_log_link)
                print(f"[{_ts()}] {item_id}: remote resolved — synced back, moved to Done section")
            else:
                self.update_col(item_id, COL_STATUS, "needs-review")
                self._inject_or_update_action_callout(item_id, "needs-review", budget, log_link=note_log_link)
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

