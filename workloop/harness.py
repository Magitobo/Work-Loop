import json
import re
import subprocess
import sys
import threading
from abc import ABC, abstractmethod
from pathlib import Path

from .constants import *
from .utils import _ts

# Harness base class
class Harness(ABC):
    """Abstract base for AI harness backends (Claude, OpenCode, etc.)."""

    @abstractmethod
    def run(self, prompt: str, budget: float, cwd: str | None, item_id: str | None, log_file: Path, abort_checker=None) -> int:
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

    def run(self, prompt: str, budget: float, cwd: str | None, item_id: str | None, log_file: Path, abort_checker=None) -> int:
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
            cwd=cwd,
        )

        _stop_watcher = threading.Event()
        _abort_poll_interval = getattr(self, "_abort_poll_interval", 3)

        def _abort_watcher():
            while not _stop_watcher.wait(timeout=_abort_poll_interval):
                if abort_checker and abort_checker():
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

    def run(self, prompt: str, budget: float, cwd: str | None, item_id: str | None, log_file: Path, abort_checker=None) -> int:
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
            cwd=cwd,
        )

        _stop_watcher = threading.Event()
        _abort_poll_interval = getattr(self, "_abort_poll_interval", 3)

        def _abort_watcher():
            while not _stop_watcher.wait(timeout=_abort_poll_interval):
                if abort_checker and abort_checker():
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


