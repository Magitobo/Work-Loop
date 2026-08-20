import os
import re
import shutil
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


from .children import ChildrenMixin
from .constants import *
from .dashboard import DashboardMixin
from .harness import ClaudeHarness, OpenCodeHarness
from .outline import OutlineMixin
from .remote import RemoteMixin
from .scripts import ScriptsMixin
from .utils import _is_data_row, _ts, _is_table_separator


class WorkLoop(OutlineMixin, ChildrenMixin, ScriptsMixin, RemoteMixin, DashboardMixin):
    _ATTENTION_RE = re.compile(r'<!--\s*attention:\s*yes\b(.*?)-->', re.IGNORECASE | re.DOTALL)
    _MARKDOWN_LINK_RE = re.compile(r'\[[^\]]+\]\([^)]+\)')
    _NA_BEGIN = '<!-- NEEDS-ATTENTION:BEGIN -->'
    _NA_END = '<!-- NEEDS-ATTENTION:END -->'
    TRIGGER_STATUSES = {"ready", "analyze", "implement", "resolved", "research"}

    def __init__(self, config: dict, script_dir: Path | None = None):
        self.config = config
        self.work_dir = Path(config['work_dir'])
        self.script_dir = script_dir if script_dir is not None else self.work_dir
        self.harness_type = config['harness']['type']
        self.max_budget = config.get('harness', {}).get('max_budget_usd', 10.00)
        self.remote_work_dir = config.get('remote', {}).get('work_dir', '~/Work-Loop')
        self.work_file_name = config.get('work_file')
        if not self.work_file_name:
            if (self.work_dir / "WORK.md").exists():
                self.work_file_name = "WORK.md"
            elif (self.work_dir / "WORK-NEW.md").exists():
                self.work_file_name = "WORK-NEW.md"
            else:
                self.work_file_name = "WORK.md"
        self.work_file = self.work_dir / self.work_file_name
        self._stop = False

        # Build harness
        if self.harness_type == 'opencode':
            self.harness = OpenCodeHarness()
            self.harness._model = config['harness'].get('model', '')
        else:
            self.harness = ClaudeHarness()
        self.harness._abort_poll_interval = 3



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

    def _read_lines(self) -> list[str]:
        with open(self.work_file, 'r') as f:
            return f.readlines()

    def _write_lines(self, lines: list[str]) -> None:
        tmp = str(self.work_file) + ".tmp"
        with open(tmp, 'w') as f:
            f.writelines(lines)
        Path(tmp).replace(self.work_file)

    @staticmethod
    def _slugify_title(title: str) -> str:
        clean = re.sub(r'[^\w\s-]', '', title).strip()
        words = clean.split()
        if len(words) > 4:
            words = words[:4]
        slug = "-".join(words)
        return slug or f"ITEM-{datetime.now().strftime('%m%d%H%M')}"

    def update_col(self, item_id: str, col_idx: int, value: str) -> None:
        if self._is_outline_format():
            self._update_col_outline(item_id, col_idx, value)
            return
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
        if self._is_outline_format():
            return self._get_col_outline(item_id, col_idx)
        for line in self._read_lines():
            stripped = line.rstrip('\n')
            if not stripped.startswith('|'):
                continue
            cols = stripped.split('|')
            if _is_data_row(cols) and cols[COL_ID].strip() == item_id:
                return cols[col_idx].strip() if col_idx < len(cols) else ''
        return ''

    def get_ready_items(self) -> list[str]:
        self._scan_in_note_actions()
        if self._is_outline_format():
            self._scan_outline_actions()
            return self._get_ready_items_outline()
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
        if self._is_outline_format():
            return self._get_new_items_outline()
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

        if self._is_outline_format():
            prompt = self._extract_prompt_from_new_outline(item_id)
        else:
            raw_title = self.get_col(item_id, COL_TITLE)
            m = re.match(r'\[([^\]]+)\]', raw_title)
            prompt = self._normalize_table_text(m.group(1) if m else raw_title)

        conv_file = item_dir / "CONVERSATION.md"
        today = datetime.now().strftime('%Y-%m-%d')
        if not conv_file.exists():
            action_callout = (
                "> [!action] **Work-Loop Action Center**\n"
                f"> Status: `ready` | Budget: `${self.max_budget}` | Last Run: {today}\n"
                "> - [ ] **Continue Analyze**\n"
                "> - [ ] **Run Implement**\n"
                "> - [ ] **Mark Resolved (Move to Done)**\n"
                "> - [ ] **Abort**\n\n"
            )
            conv_file.write_text(f"{action_callout}## {today} | User\n\n{prompt}\n")

        if self._is_outline_format():
            self._promote_new_item_outline(item_id, prompt)
        else:
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
            action_callout = (
                "> [!action] **Work-Loop Action Center**\n"
                f"> Status: `ready` | Budget: `${self.max_budget}` | Last Run: {today}\n"
                "> - [ ] **Continue Analyze**\n"
                "> - [ ] **Run Implement**\n"
                "> - [ ] **Mark Resolved (Move to Done)**\n"
                "> - [ ] **Abort**\n\n"
            )
            conv_file.write_text(f"{action_callout}## {today} | User\n\nResearch item: {title}\n")

        initial_status = 'scheduled' if config.get('schedule') else 'ready'
        self.update_col(item_id, COL_STATUS, initial_status)
        print(f"[{_ts()}] Initialized research item: {item_id} (status: {initial_status})")

    def _auto_init_conversation(self, item_id: str) -> None:
        """Seed CONVERSATION.md from Title if missing (no status change)."""
        conv_file = self.work_dir / item_id / "CONVERSATION.md"
        if conv_file.exists():
            return
        if self._is_outline_format():
            prompt = self.get_item_title(item_id)
        else:
            raw_title = self.get_col(item_id, COL_TITLE)
            m = re.match(r'\[([^\]]+)\]', raw_title)
            prompt = self._normalize_table_text(m.group(1) if m else raw_title)
        item_dir = self.work_dir / item_id
        item_dir.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime('%Y-%m-%d')
        action_callout = (
            "> [!action] **Work-Loop Action Center**\n"
            f"> Status: `ready` | Budget: `${self.max_budget}` | Last Run: {today}\n"
            "> - [ ] **Continue Analyze**\n"
            "> - [ ] **Run Implement**\n"
            "> - [ ] **Mark Resolved (Move to Done)**\n"
            "> - [ ] **Abort**\n\n"
        )
        conv_file.write_text(f"{action_callout}## {today} | User\n\n{prompt}\n")
        print(f"[{_ts()}] Auto-initialized CONVERSATION.md for: {item_id}")

    def move_done_items(self) -> None:
        if self._is_outline_format():
            self._move_done_items_outline()
            return
        lines = self._read_lines()

        done_section_start = next(
            (i for i, l in enumerate(lines) if l.rstrip('\n').startswith('## Done')), -1
        )
        done_table_insert_idx = -1
        if done_section_start >= 0:
            for i in range(done_section_start, len(lines)):
                if _is_table_separator(lines[i]):
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
        if self._is_outline_format():
            self._move_row_to_done_outline(item_id)
            return
        lines = self._read_lines()

        done_section_start = next(
            (i for i, l in enumerate(lines) if l.rstrip('\n').startswith('## Done')), -1
        )
        done_table_insert_idx = -1
        if done_section_start >= 0:
            for i in range(done_section_start, len(lines)):
                if _is_table_separator(lines[i]):
                    done_table_insert_idx = i + 1
                    break

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

        row_content = lines[row_index]
        new_lines = [l for i, l in enumerate(lines) if i != row_index]
        adjust = 1 if row_index < done_table_insert_idx else 0
        insert_at = done_table_insert_idx - adjust

        new_lines.insert(insert_at, row_content)
        self._write_lines(new_lines)

    def insert_work_row(self, item_id: str, title: str, location: str) -> None:
        """Insert a new row after the active table separator."""
        if self._is_outline_format():
            self._insert_work_row_outline(item_id, title, location)
            return
        lines = self._read_lines()
        insert_idx = -1
        in_active = True
        for i, line in enumerate(lines):
            stripped = line.rstrip('\n')
            if stripped.startswith('## Done'):
                in_active = False
            if in_active and _is_table_separator(stripped):
                insert_idx = i + 1
                break

        if insert_idx < 0:
            return

        row = f"| {item_id} | [{title}]({item_id}/CONVERSATION.md) | {location} | ready |  |  |  |\n"
        lines.insert(insert_idx, row)
        self._write_lines(lines)

    def remove_work_row(self, item_id: str) -> None:
        """Remove a row by ID from any section."""
        if self._is_outline_format():
            self._remove_work_row_outline(item_id)
            return
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

        ignore_names = {"node_modules", ".DS_Store", "__pycache__", ".git"}

        def _sync_tree(s: Path, d: Path) -> None:
            d.mkdir(parents=True, exist_ok=True)
            src_entries = {p.name: p for p in s.iterdir() if p.name not in ignore_names}

            if d.exists():
                for p in d.iterdir():
                    if p.name in ignore_names:
                        continue
                    if p.name not in src_entries:
                        try:
                            if p.is_dir() and not p.is_symlink():
                                shutil.rmtree(p, ignore_errors=True)
                            else:
                                p.unlink(missing_ok=True)
                        except OSError:
                            pass

            for name, src_path in src_entries.items():
                dst_path = d / name
                if src_path.is_dir() and not src_path.is_symlink():
                    _sync_tree(src_path, dst_path)
                else:
                    try:
                        shutil.copy2(src_path, dst_path)
                    except OSError:
                        pass

        _sync_tree(src, dst)

    def _run_harness(self, prompt: str, log_file: Path, budget: float, cwd: str | None = None, item_id: str | None = None) -> int:
        """Delegate to the configured harness."""
        target_cwd = cwd or str(self.work_dir)
        self._sync_agent_dir(target_cwd)
        def abort_checker() -> bool:
            return bool(item_id and self.get_col(item_id, COL_STATUS) == 'abort')
        return self.harness.run(prompt, budget, target_cwd, item_id, log_file, abort_checker=abort_checker)

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

    def process_local(self, item_id: str, budget: float) -> None:
        self._auto_init_conversation(item_id)
        item_dir = self.work_dir / item_id
        item_dir.mkdir(parents=True, exist_ok=True)
        (item_dir / "_logs").mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime('%Y-%m-%d')
        ts = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        run_start = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z')
        log_file = item_dir / "_logs" / f"{ts}_{item_id}.log"
        log_link = f"[Log]({item_id}/_logs/{ts}_{item_id}.log)"

        mode = self.get_col(item_id, COL_STATUS)  # read trigger status BEFORE overwriting
        self.update_col(item_id, COL_STATUS, "in-progress")
        self._inject_or_update_action_callout(
            item_id,
            "in-progress",
            budget=budget,
            last_run_ts=datetime.now().strftime('%Y-%m-%d %H:%M'),
            log_link=f"[Log](_logs/{ts}_{item_id}.log)",
        )

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
            title = config.get('title', '')
            living_note_path = config.get('living_note_path') or config.get('note_path', '')
            prompt = (
                f"{self._read_base_prompt()}"
                f"{prompt_text}\n\n"
                f"title: {title}\n"
                f"living_note_path: {living_note_path}\n"
                f"note_path: {living_note_path}\n"
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

        note_log_link = f"[Log](_logs/{ts}_{item_id}.log)"
        if current_status == 'abort':
            self.prepend_abort_notice(item_id, today, budget, "aborted by user")
            self._inject_or_update_action_callout(item_id, "abort", budget, log_link=note_log_link)
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
            self._inject_or_update_action_callout(item_id, "needs-review", budget, log_link=note_log_link)
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
                        non_empty = [
                            l.strip('# -').strip()
                            for l in research_file.read_text().splitlines()
                            if l.strip() and not l.strip().startswith(('[[', '<!--'))
                        ]
                        summary = non_empty[0] if non_empty else "Research complete"
                    else:
                        summary = "Research complete"
                    self._append_research_run(item_id, latest_run, summary, status='done')
                if config.get('schedule'):
                    self.update_col(item_id, COL_STATUS, "scheduled")
                    self._inject_or_update_action_callout(item_id, "scheduled", budget, log_link=note_log_link)
                else:
                    self.update_col(item_id, COL_STATUS, "done")
                    self._inject_or_update_action_callout(item_id, "done", budget, log_link=note_log_link)
                print(f"[{_ts()}] {item_id}: research complete — status={'scheduled' if config.get('schedule') else 'done'}")
            elif mode == "resolved":
                self._move_row_to_done(item_id)
                self._inject_or_update_action_callout(item_id, "done", budget, log_link=note_log_link)
                print(f"[{_ts()}] {item_id}: resolved — moved to Done section")
            else:
                final_status = self.get_col(item_id, COL_STATUS) or "needs-review"
                self._inject_or_update_action_callout(item_id, final_status, budget, log_link=note_log_link)
                print(f"[{_ts()}] {item_id}: completed")

    def build_launcher(self, item_id: str, ts_str: str, budget: float, mode: str = "analyze", work_dir: str | None = None) -> str:
        """Delegate to the configured harness for launcher script generation."""
        return self.harness.launcher_script(item_id, ts_str, budget, mode, work_dir, self.remote_work_dir)

    def get_item_type(self, item_id: str) -> str:
        """Return 'research', 'script', or 'conversation'."""
        runs_file = self.work_dir / item_id / "RUNS.md"
        if not runs_file.exists():
            return 'conversation'
        config = self._parse_runs_md(item_id)
        if config.get('type') == 'research':
            return 'research'
        return 'script'

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
                print()
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
                    self.update_col(item_id, COL_LOG, f"[Log]({item_id}/_logs/{ts}_{item_id}.log)")
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

