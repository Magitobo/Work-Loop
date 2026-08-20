import re
from datetime import datetime
from pathlib import Path

from .constants import *
from .utils import _ts


class ChildrenMixin:
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
        log_link = f"[Log]({parent_id}/_logs/{ts}_{parent_id}_{child_name}.log)"
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

