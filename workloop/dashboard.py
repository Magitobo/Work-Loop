import re
from datetime import datetime

from .constants import *
from .utils import _is_data_row, _ts


class DashboardMixin:
    def _build_needs_attention_lines(self) -> list[str]:
        """Build the bullet lines for the Needs Attention section."""
        lines = []
        if self._is_outline_format():
            items = self._parse_outline_blocks()
            for item_id, item in items.items():
                if item["status"] == "needs-review":
                    lines.append(f"- **{item_id}** (needs-review). [Open conversation]({item_id}/CONVERSATION.md)")
        else:
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
        """Char index to insert the block: before ## Active Items, ## Work Items, else ## Done, else end."""
        for marker in ('\n## Active Items', '\n## Work Items', '\n## Done'):
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
            if self._is_outline_format():
                self._refresh_outline_dashboard()
                return

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

    def _scan_in_note_actions(self) -> list[str]:
        """Scan all item CONVERSATION.md files for checked action boxes.

        Triggers:
        - [x] Continue Analyze / Analyze / Ready -> ready
        - [x] Run Implement / Implement -> implement
        - [x] Mark Resolved / Resolved -> resolved
        - [x] Abort -> abort
        - [x] Run Now -> research (research items)

        When detected, unchecks the box, updates status in the note's action callout
        and in WORK.md / WORK-NEW.md, and returns list of promoted item_ids.
        """
        promoted = []
        if not self.work_dir.exists():
            return promoted
        for item_dir in sorted(self.work_dir.iterdir()):
            if not item_dir.is_dir() or item_dir.name.startswith('.'):
                continue
            conv_file = item_dir / "CONVERSATION.md"
            if not conv_file.exists():
                continue
            try:
                text = conv_file.read_text(errors='replace')
            except OSError:
                continue

            pattern = re.compile(
                r'^[ \t]*>?[ \t]*-\s*\[([xX])\]\s*(?:\*\*)?(?:(Continue\s+Analyze|Analyze|Ready)|(Run\s+Implement|Implement)|(Mark\s+Resolved(?:\s*\(Move to Done\))?|Resolved)|(Abort)|(Run\s+Now))(?:\*\*)?',
                re.MULTILINE | re.IGNORECASE
            )
            match = pattern.search(text)
            if not match:
                continue

            if match.group(2):
                new_status = "ready"
            elif match.group(3):
                new_status = "implement"
            elif match.group(4):
                new_status = "resolved"
            elif match.group(5):
                new_status = "abort"
            elif match.group(6):
                new_status = "research"
            else:
                continue

            item_id = item_dir.name

            def _uncheck(m):
                return m.group(0).replace(f"[{m.group(1)}]", "[ ]")

            new_text = pattern.sub(_uncheck, text)
            new_text = re.sub(
                r'(>\s*Status:\s*`)[^`]+(`)',
                rf'\g<1>{new_status}\g<2>',
                new_text,
                flags=re.IGNORECASE
            )
            conv_file.write_text(new_text)
            self.update_col(item_id, COL_STATUS, new_status)
            print(f"[{_ts()}] {item_id}: in-note action triggered -> {new_status}")
            promoted.append(item_id)
        return promoted

    def _inject_or_update_action_callout(
        self,
        item_id: str,
        status: str,
        budget: float | str | None = None,
        last_run_ts: str | None = None,
        log_link: str | None = None,
    ) -> None:
        """Ensure CONVERSATION.md begins with an updated, text-only Action Center callout.

        While status is 'in-progress':
        - Shows Status: `in-progress`
        - Shows Log link to current running log
        - Only shows the Abort action: - [ ] **Abort**

        When status is not in-progress:
        - Shows full actions: Continue Analyze, Run Implement, Mark Resolved, Abort
        - Research items only show Run Now and Abort
        """
        conv_file = self.work_dir / item_id / "CONVERSATION.md"
        if not conv_file.exists():
            return
        try:
            text = conv_file.read_text(errors='replace')
        except OSError:
            return

        ts_str = last_run_ts or datetime.now().strftime('%Y-%m-%d %H:%M')

        # Resolve log link if not provided
        if not log_link:
            log_col = self.get_col(item_id, COL_LOG) if hasattr(self, 'get_col') else ""
            if log_col:
                m_log = re.search(r'\[Log\]\((?:[^/)]+/)?(_logs/[^)]+|\.logs/[^)]+)\)', log_col)
                if m_log:
                    log_link = f"[Log]({m_log.group(1)})"
                elif log_col.startswith("[Log]"):
                    log_link = log_col
            if not log_link:
                logs_dir = self.work_dir / item_id / "_logs"
                if logs_dir.exists():
                    log_files = sorted(logs_dir.glob("*.log"), reverse=True)
                    if log_files:
                        log_link = f"[Log](_logs/{log_files[0].name})"
                if not log_link:
                    dots_dir = self.work_dir / item_id / ".logs"
                    if dots_dir.exists():
                        log_files = sorted(dots_dir.glob("*.log"), reverse=True)
                        if log_files:
                            log_link = f"[Log](.logs/{log_files[0].name})"

        log_str = f" | {log_link}" if log_link else ""

        if status == "in-progress":
            callout_block = (
                "> [!action] **Work-Loop Action Center**\n"
                f"> Status: `in-progress` | Last Run: {ts_str}{log_str}\n"
                "> - [ ] **Abort**"
            )
        elif self.get_item_type(item_id) == 'research':
            callout_block = (
                "> [!action] **Work-Loop Action Center**\n"
                f"> Status: `{status}` | Last Run: {ts_str}{log_str}\n"
                "> - [ ] **Run Now**\n"
                "> - [ ] **Abort**"
            )
        else:
            callout_block = (
                "> [!action] **Work-Loop Action Center**\n"
                f"> Status: `{status}` | Last Run: {ts_str}{log_str}\n"
                "> - [ ] **Continue Analyze**\n"
                "> - [ ] **Run Implement**\n"
                "> - [ ] **Mark Resolved (Move to Done)**\n"
                "> - [ ] **Abort**"
            )

        callout_re = re.compile(
            r'>\s*\[!action\]\s*\*\*Work-Loop Action Center\*\*.*?(?=\n\n|\n[^\>]|\Z)',
            re.DOTALL | re.IGNORECASE
        )
        if callout_re.search(text):
            new_text = callout_re.sub(callout_block, text)
        else:
            new_text = callout_block + "\n\n" + text.lstrip()

        if new_text != text:
            conv_file.write_text(new_text)

