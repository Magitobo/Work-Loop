import re
from datetime import datetime

from .constants import *
from .utils import _ts, _is_table_separator, _is_table_header


class OutlineMixin:
    def _is_outline_format(self) -> bool:
        """Return True if self.work_file uses the outline format rather than table format."""
        if self.work_file_name.endswith("-NEW.md") or self.work_file_name.endswith(".outline.md"):
            return True
        if not self.work_file.exists():
            return False
        try:
            text = self.work_file.read_text(errors='replace')
        except OSError:
            return False
        return "## Active Items" in text or "## Add New Item" in text

    def _parse_outline_blocks(self) -> dict[str, dict]:
        """Parse all items in WORK-NEW.md into structured dict keyed by item_id."""
        if not self.work_file.exists():
            return {}
        lines = self._read_lines()
        items = {}
        current_section = None
        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            if stripped.startswith("## Active Items"):
                current_section = "active"
                i += 1
                continue
            elif stripped.startswith("## Add New Item"):
                current_section = "new"
                i += 1
                continue
            elif stripped.startswith("## Done"):
                current_section = "done"
            elif stripped.startswith("## ") or stripped.startswith("# "):
                current_section = None
                i += 1
                continue

            if current_section == "active":
                # Case 1: Table row in Active Items
                is_separator = _is_table_separator(stripped)
                is_header = _is_table_header(stripped)
                if stripped.startswith("|") and not is_separator and not is_header:
                    cells = [c.strip() for c in stripped.split("|")[1:-1]]
                    if len(cells) >= 3:
                        start_idx = i
                        item_lines = [line]
                        end_idx = i + 1

                        if cells[0] in ("[ ]", "[x]", "[X]", ""):
                            task_cell = cells[1] if len(cells) > 1 else ""
                            status_cell = cells[2] if len(cells) > 2 else "ready"
                            if len(cells) >= 6:
                                last_updated = cells[3]
                                log_cell = cells[4]
                                id_cell = cells[5]
                            elif len(cells) == 5:
                                last_updated = cells[3] if re.match(r'^\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2})?$', cells[3]) else ""
                                log_cell = cells[3] if not last_updated else cells[4]
                                id_cell = cells[4] if not last_updated else ""
                            else:
                                last_updated = ""
                                log_cell = cells[3] if len(cells) > 3 else ""
                                id_cell = cells[4] if len(cells) > 4 else ""
                        else:
                            task_cell = cells[0]
                            status_cell = cells[1] if len(cells) > 1 else "ready"
                            if len(cells) >= 5:
                                last_updated = cells[2]
                                log_cell = cells[3]
                                id_cell = cells[4]
                            elif len(cells) == 4:
                                last_updated = cells[2] if re.match(r'^\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2})?$', cells[2]) else ""
                                log_cell = cells[2] if not last_updated else cells[3]
                                id_cell = cells[3] if not last_updated else ""
                            else:
                                last_updated = ""
                                log_cell = ""
                                id_cell = cells[2] if len(cells) > 2 else ""

                        m_id = re.search(r'(?:`|\*\*|\b)([A-Za-z0-9_.-]+)(?:`|\*\*|\b)', id_cell)
                        item_id = m_id.group(1).strip() if m_id and m_id.group(1).strip() else id_cell.strip('`* ')
                        if not item_id or item_id in ("-", ""):
                            m_link = re.search(r'\[[^\]]+\]\((?:.+/)?([^/)]+)/CONVERSATION\.md\)', task_cell)
                            item_id = m_link.group(1).strip() if m_link else "ITEM-UNKNOWN"

                        m_stat = re.search(r'`?([a-z-]+)`?', status_cell, re.IGNORECASE)
                        status = m_stat.group(1).strip() if m_stat else "ready"

                        m_thread = re.search(r'(\[[^\]]+\]\([^)]*CONVERSATION\.md\))', task_cell)
                        thread = m_thread.group(1).strip() if m_thread else task_cell

                        items[item_id] = {
                            "id": item_id,
                            "section": "active",
                            "status": status,
                            "budget": f"${self.max_budget}",
                            "location": "local",
                            "last_updated": last_updated,
                            "thread": thread,
                            "log": log_cell,
                            "start": start_idx,
                            "end": end_idx,
                            "lines": item_lines,
                            "format": "table",
                        }
                        i += 1
                        continue

                # Case 2: Bullet item in Active Items
                elif (
                    stripped.startswith("- [ ]")
                    or stripped.startswith("- [x]")
                    or stripped.startswith("- **")
                    or (stripped.startswith("- [") and not stripped.startswith("- [ ]"))
                ):
                    start_idx = i
                    item_lines = [line]
                    i += 1
                    while i < len(lines):
                        next_line = lines[i]
                        if next_line.startswith("  ") or next_line.startswith("\t"):
                            item_lines.append(next_line)
                            i += 1
                        else:
                            break
                    end_idx = i
                    block = "".join(item_lines)
                    m_end_id = re.search(r'(?:`|\*\*)\s*([A-Za-z0-9_.-]+)\s*(?:`|\*\*)\s*$', item_lines[0].strip())
                    if m_end_id:
                        item_id = m_end_id.group(1).strip()
                    else:
                        m_link = re.search(r'\[[^\]]+\]\((?:.+/)?([^/)]+)/CONVERSATION\.md\)', block)
                        if m_link:
                            item_id = m_link.group(1).strip()
                        else:
                            m_id = re.search(r'(?:\*\*|`)([^*`]+)(?:\*\*|`)', block)
                            item_id = m_id.group(1).strip() if m_id else stripped.split()[2].strip('*`')

                    m_status = re.search(r"status:\s*`?([^\s·|`]+)`?", block, re.IGNORECASE)
                    status = m_status.group(1).strip() if m_status else "ready"
                    m_budget = re.search(r"budget:\s*`?(\$?[0-9.]+(?:\s*-\s*[A-Za-z]+)?)`?", block, re.IGNORECASE)
                    budget = m_budget.group(1).strip() if m_budget else f"${self.max_budget}"
                    m_loc = re.search(r"location:\s*`?([^\s·|`]+)`?", block, re.IGNORECASE)
                    location = m_loc.group(1).strip() if m_loc else "local"
                    m_date = re.search(r"\b(20\d{2}-\d{2}-\d{2}(?:\s+\d{2}:\d{2})?)\b", block)
                    last_updated = m_date.group(1) if m_date else ""
                    m_thread = re.search(r'(?:—\s*|\bThread:\s*)(\[[^\]]+\]\([^)]+\))', block)
                    if not m_thread:
                        m_thread = re.search(r'(\[[^\]]+\]\([^)]*CONVERSATION\.md\))', block)
                    thread = m_thread.group(1).strip() if m_thread else ""

                    m_log = re.search(r'(?:Log:\s*|·\s*)(\[[^\]]+\]\([^)]*\.(?:log|debug)\))', block)
                    if not m_log:
                        m_log = re.search(r'Log:\s*(\[[^\]]+\]\([^)]+\)|\S+)', block)
                    log_link = m_log.group(1).strip() if m_log else ""

                    items[item_id] = {
                        "id": item_id,
                        "section": "active",
                        "status": status,
                        "budget": budget,
                        "location": location,
                        "last_updated": last_updated,
                        "thread": thread,
                        "log": log_link,
                        "start": start_idx,
                        "end": end_idx,
                        "lines": item_lines,
                        "format": "bullet",
                    }
                    continue
            i += 1
        return items

    def _scan_outline_actions(self) -> list[str]:
        """Scan WORK-NEW.md for checked action checkboxes [x] under ## Active Items."""
        if not self.work_file.exists():
            return []
        lines = self._read_lines()
        items = self._parse_outline_blocks()
        promoted = []
        action_pattern = re.compile(
            r'\[([xX])\]\s*(ready|analyze|implement|resolved|abort)',
            re.IGNORECASE
        )
        changed = False

        for item_id, item in items.items():
            main_line = item["lines"][0]
            if item.get("format") == "table":
                m_tbl_check = re.search(r'\|\s*\[([xX])\]\s*\|', main_line)
                if m_tbl_check:
                    item["lines"][0] = re.sub(r'\|\s*\[([xX])\]\s*\|', '| [ ] |', main_line, count=1)
                    cur_status = item["status"]
                    new_status = cur_status if cur_status in self.TRIGGER_STATUSES else "ready"
                    cells = [c.strip() for c in item["lines"][0].split("|")[1:-1]]
                    if len(cells) >= 3 and cells[0] in ("[ ]", "[x]", "[X]", ""):
                        cells[2] = f"{new_status}"
                        item["lines"][0] = "| " + " | ".join(cells) + " |\n"
                    changed = True
                    promoted.append(item_id)
                    print(f"[{_ts()}] {item_id}: table checkbox triggered -> {new_status}")
                    continue
            else:
                m_main = re.search(r'^[ \t]*-\s*\[([xX])\]', main_line)
                if m_main:
                    item["lines"][0] = re.sub(r'^[ \t]*-\s*\[([xX])\]', '- [ ]', main_line)
                    cur_status = item["status"]
                    new_status = cur_status if cur_status in self.TRIGGER_STATUSES else "ready"
                    if new_status != cur_status:
                        item["lines"][0] = re.sub(
                            r'status:\s*`?[^\s·|`]+`?',
                            f'status: {new_status}',
                            item["lines"][0],
                            flags=re.IGNORECASE
                        )
                    changed = True
                    promoted.append(item_id)
                    print(f"[{_ts()}] {item_id}: main outline checkbox triggered -> {new_status}")
                    continue

                for idx, line in enumerate(item["lines"]):
                    m = action_pattern.search(line)
                    if m:
                        new_status = m.group(2).lower()
                        item["lines"][idx] = action_pattern.sub(lambda match: f"[ ] {match.group(2)}", line)
                        item["lines"][0] = re.sub(
                            r'status:\s*`?[^\s·|`]+`?',
                            f'status: {new_status}',
                            item["lines"][0],
                            flags=re.IGNORECASE
                        )
                        changed = True
                        promoted.append(item_id)
                        print(f"[{_ts()}] {item_id}: outline action triggered -> {new_status}")
                        break

        if changed:
            rebuilt = []
            cur_idx = 0
            for item_id, item in items.items():
                rebuilt.extend(lines[cur_idx:item["start"]])
                rebuilt.extend(item["lines"])
                cur_idx = item["end"]
            rebuilt.extend(lines[cur_idx:])
            self._write_lines(rebuilt)

        return promoted

    def _get_ready_items_outline(self) -> list[str]:
        items = self._parse_outline_blocks()
        ready = []
        for item_id, item in items.items():
            if item["status"] in self.TRIGGER_STATUSES:
                ready.append(item_id)
        return ready

    def _get_new_items_outline(self) -> list[str]:
        if not self.work_file.exists():
            return []
        lines = self._read_lines()
        new_items = []
        in_new_section = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("## Add New Item"):
                in_new_section = True
                continue
            elif stripped.startswith("## "):
                in_new_section = False
                continue
            if in_new_section and (stripped.startswith("- [x]") or stripped.startswith("- [X]")):
                if stripped.startswith("<!--"):
                    continue
                m = re.match(r'^[ \t]*-\s*\[[xX]\]\s*(?:\*\*(?P<id>[^*]+)\*\*)?\s*(?P<prompt>.+)', stripped)
                if m and m.group('prompt'):
                    prompt = m.group('prompt').strip()
                    if prompt.startswith("<!--"):
                        continue
                    item_id = m.group('id').strip() if m.group('id') else self._slugify_title(prompt)
                    new_items.append(item_id)
        return new_items

    def _extract_prompt_from_new_outline(self, item_id: str) -> str:
        if not self.work_file.exists():
            return item_id
        lines = self._read_lines()
        in_new_section = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("## Add New Item"):
                in_new_section = True
                continue
            elif stripped.startswith("## "):
                in_new_section = False
                continue
            if in_new_section and (stripped.startswith("- [x]") or stripped.startswith("- [X]")):
                if stripped.startswith("<!--"):
                    continue
                m = re.match(r'^[ \t]*-\s*\[[xX]\]\s*(?:\*\*(?P<id>[^*]+)\*\*)?\s*(?P<prompt>.+)', stripped)
                if m and m.group('prompt'):
                    prompt = m.group('prompt').strip()
                    matched_id = m.group('id').strip() if m.group('id') else self._slugify_title(prompt)
                    if matched_id == item_id or item_id in prompt:
                        return prompt
        return item_id

    def _promote_new_item_outline(self, item_id: str, prompt: str) -> None:
        if not self.work_file.exists():
            return
        lines = self._read_lines()
        new_lines = []
        in_new_section = False
        removed = False

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("## Add New Item"):
                in_new_section = True
                new_lines.append(line)
                continue
            elif stripped.startswith("## "):
                in_new_section = False

            if in_new_section and not removed and (stripped.startswith("- [x]") or stripped.startswith("- [X]")):
                if item_id in stripped or prompt in stripped:
                    removed = True
                    continue
            new_lines.append(line)

        active_idx = -1
        active_has_table = False
        for i, l in enumerate(new_lines):
            if l.strip().startswith("## Active Items"):
                active_idx = i + 1
                for j in range(i + 1, min(i + 5, len(new_lines))):
                    if new_lines[j].strip().startswith("|"):
                        active_has_table = True
                        break
                break
        if active_idx < 0:
            active_idx = len(new_lines)

        today = datetime.now().strftime('%Y-%m-%d %H:%M')
        if active_has_table:
            row = f"| [{prompt}]({item_id}/CONVERSATION.md) | ready | {today} | | {item_id} |\n"
            insert_pos = active_idx
            while insert_pos < len(new_lines):
                s = new_lines[insert_pos].strip()
                if not s or _is_table_header(s) or _is_table_separator(s):
                    insert_pos += 1
                else:
                    break
            new_lines.insert(insert_pos, row)
        else:
            block = f"\n- [ ] [{prompt}]({item_id}/CONVERSATION.md) · status: ready · {item_id}\n"
            new_lines.insert(active_idx, block)

        self._write_lines(new_lines)
        self._sort_active_items_outline()

    def _get_col_outline(self, item_id: str, col_idx: int) -> str:
        items = self._parse_outline_blocks()
        if item_id in items:
            item = items[item_id]
            if col_idx == COL_ID:
                return item["id"]
            elif col_idx == COL_TITLE:
                return item["thread"] or f"[{item_id}]({item_id}/CONVERSATION.md)"
            elif col_idx == COL_LOCATION:
                return item["location"]
            elif col_idx == COL_STATUS:
                return item["status"]
            elif col_idx == COL_LAST_UPDATED:
                return item["last_updated"]
            elif col_idx == COL_BUDGET:
                return item["budget"]
            elif col_idx == COL_LOG:
                return item["log"]
        if self.work_file.exists():
            for line in self._read_lines():
                if item_id in line:
                    if col_idx == COL_ID:
                        return item_id
                    elif col_idx == COL_STATUS:
                        return "done"
        return ""

    def _update_col_outline(self, item_id: str, col_idx: int, value: str) -> None:
        if col_idx == COL_STATUS and value == "done":
            self._move_row_to_done_outline(item_id)
            return

        lines = self._read_lines()
        items = self._parse_outline_blocks()
        if item_id not in items:
            return

        item = items[item_id]
        item_lines = item["lines"]

        if item.get("format") == "table":
            cells = [c.strip() for c in item_lines[0].split("|")[1:-1]]
            has_trigger = len(cells) >= 3 and cells[0] in ("[ ]", "[x]", "[X]", "")
            if has_trigger:
                task_idx = 1
                stat_idx = 2
                date_idx = 3 if len(cells) >= 5 else -1
                log_idx = 4 if len(cells) >= 5 else 3
                id_idx = 5 if len(cells) >= 6 else (4 if len(cells) >= 5 else -1)
            else:
                task_idx = 0
                stat_idx = 1
                date_idx = 2 if len(cells) >= 5 else -1
                log_idx = 3 if len(cells) >= 5 else 2
                id_idx = 4 if len(cells) >= 5 else 3

            if col_idx == COL_STATUS and stat_idx < len(cells):
                cells[stat_idx] = value
            elif col_idx == COL_LAST_UPDATED:
                if date_idx >= 0 and date_idx < len(cells):
                    cells[date_idx] = value
            elif col_idx == COL_LOG:
                if log_idx >= 0:
                    while len(cells) <= log_idx:
                        cells.append("")
                    cells[log_idx] = value
            elif col_idx == COL_TITLE and task_idx < len(cells):
                if "<br>" in cells[task_idx]:
                    parts = cells[task_idx].split("<br>", 1)
                    cells[task_idx] = value + "<br>" + parts[1]
                else:
                    cells[task_idx] = value
            elif col_idx == COL_ID and id_idx >= 0 and id_idx < len(cells):
                cells[id_idx] = value

            item_lines[0] = "| " + " | ".join(cells) + " |\n"
        else:
            if col_idx == COL_STATUS:
                item_lines[0] = re.sub(
                    r'status:\s*`?[^\s·|`]+`?',
                    f'status: {value}',
                    item_lines[0],
                    flags=re.IGNORECASE
                )
            elif col_idx == COL_BUDGET:
                if "budget:" in item_lines[0]:
                    item_lines[0] = re.sub(
                        r'budget:\s*`?[^\s·|`]+`?',
                        f'budget: {value}',
                        item_lines[0],
                        flags=re.IGNORECASE
                    )
            elif col_idx == COL_LOCATION:
                if "location:" in item_lines[0]:
                    item_lines[0] = re.sub(
                        r'location:\s*`?[^\s·|`]+`?',
                        f'location: {value}',
                        item_lines[0],
                        flags=re.IGNORECASE
                    )
            elif col_idx == COL_LAST_UPDATED:
                if re.search(r'\b(20\d{2}-\d{2}-\d{2}(?:\s+\d{2}:\d{2})?)\b', item_lines[0]):
                    item_lines[0] = re.sub(r'\b(20\d{2}-\d{2}-\d{2}(?:\s+\d{2}:\d{2})?)\b', value, item_lines[0])
            elif col_idx == COL_LOG:
                updated = False
                for idx, l in enumerate(item_lines):
                    if re.search(r'(\[Log\]\([^)]+\)|Log:\s*\[[^\]]+\]\([^)]+\)|·\s*\[[^\]]+\]\([^)]*\.(?:log|debug)\))', l):
                        item_lines[idx] = re.sub(r'(\[Log\]\([^)]+\)|Log:\s*\[[^\]]+\]\([^)]+\)|\[[^\]]+\]\([^)]*\.(?:log|debug)\))', value, l)
                        updated = True
                        break
                if not updated:
                    if f"`{item_id}`" in item_lines[0]:
                        item_lines[0] = re.sub(rf'\s*·\s*`{re.escape(item_id)}`', f' · {value} · `{item_id}`', item_lines[0])
                    else:
                        item_lines[0] = item_lines[0].rstrip('\n') + f" · {value}\n"
            elif col_idx == COL_TITLE:
                updated = False
                for idx, l in enumerate(item_lines):
                    if re.search(r'(\[[^\]]+\]\([^)]*CONVERSATION\.md\))', l):
                        item_lines[idx] = re.sub(r'(\[[^\]]+\]\([^)]*CONVERSATION\.md\))', value, l)
                        updated = True
                        break
                    elif "Thread:" in l:
                        item_lines[idx] = f"  - Thread: {value}\n"
                        updated = True
                        break

        new_lines = lines[:item["start"]] + item_lines + lines[item["end"]:]
        self._write_lines(new_lines)
        self._sort_active_items_outline()

    def _move_done_items_outline(self) -> None:
        items = self._parse_outline_blocks()
        for item_id, item in items.items():
            if item["status"] == "done":
                self._move_row_to_done_outline(item_id)

    def _move_row_to_done_outline(self, item_id: str) -> None:
        if not self.work_file.exists():
            return
        lines = self._read_lines()
        items = self._parse_outline_blocks()
        if item_id not in items:
            return
        item = items[item_id]

        new_lines = lines[:item["start"]] + lines[item["end"]:]
        title = item["thread"] or f"[{item_id}]({item_id}/CONVERSATION.md)"
        log_str = item['log'] if item['log'] else ""
        last_updated = item.get('last_updated', '') or datetime.now().strftime('%Y-%m-%d %H:%M')

        done_idx = -1
        done_has_table = False
        for i, l in enumerate(new_lines):
            if l.strip().startswith("## Done"):
                done_idx = i + 1
                for j in range(i + 1, min(i + 5, len(new_lines))):
                    if new_lines[j].strip().startswith("|"):
                        done_has_table = True
                        break
                break

        if item.get("format") == "table" or done_has_table:
            done_line = f"| {title} | {last_updated} | {log_str} | {item_id} |\n"
        else:
            log_suffix = f" · {log_str}" if log_str else ""
            done_line = f"- [x] {title}{log_suffix} · {item_id}\n"

        if done_idx >= 0:
            if done_has_table:
                insert_pos = done_idx
                while insert_pos < len(new_lines):
                    s = new_lines[insert_pos].strip()
                    if not s or _is_table_header(s) or _is_table_separator(s):
                        insert_pos += 1
                    else:
                        break
                new_lines.insert(insert_pos, done_line)
            else:
                new_lines.insert(done_idx, done_line)
        else:
            if item.get("format") == "table":
                new_lines.append("\n## Done\n\n| Task / Conversation | Last Updated | Log | ID |\n|---|:---:|:---:|---|\n" + done_line)
            else:
                new_lines.append("\n## Done\n\n" + done_line)

        self._write_lines(new_lines)

    def _insert_work_row_outline(self, item_id: str, title: str, location: str) -> None:
        if not self.work_file.exists():
            return
        lines = self._read_lines()
        active_idx = -1
        active_has_table = False
        for i, l in enumerate(lines):
            if l.strip().startswith("## Active Items"):
                active_idx = i + 1
                for j in range(i + 1, min(i + 5, len(lines))):
                    if lines[j].strip().startswith("|"):
                        active_has_table = True
                        break
                break
        if active_idx < 0:
            active_idx = len(lines)

        today = datetime.now().strftime('%Y-%m-%d %H:%M')
        if active_has_table:
            row = f"| [{title}]({item_id}/CONVERSATION.md) | ready | {today} | | {item_id} |\n"
            insert_pos = active_idx
            while insert_pos < len(lines):
                s = lines[insert_pos].strip()
                if not s or _is_table_header(s) or _is_table_separator(s):
                    insert_pos += 1
                else:
                    break
            lines.insert(insert_pos, row)
        else:
            block = f"\n- [ ] [{title}]({item_id}/CONVERSATION.md) · status: ready · {item_id}\n"
            lines.insert(active_idx, block)
        self._write_lines(lines)
        self._sort_active_items_outline()

    def _remove_work_row_outline(self, item_id: str) -> None:
        if not self.work_file.exists():
            return
        lines = self._read_lines()
        items = self._parse_outline_blocks()
        if item_id in items:
            item = items[item_id]
            new_lines = lines[:item["start"]] + lines[item["end"]:]
            self._write_lines(new_lines)

    def _extract_date_from_outline_row(self, line: str) -> str:
        """Extract the Last Updated date/time (YYYY-MM-DD or YYYY-MM-DD HH:MM) from a table row or bullet line."""
        stripped = line.strip()
        if stripped.startswith("|"):
            cells = [c.strip() for c in stripped.split("|")[1:-1]]
            if cells:
                if cells[0] in ("[ ]", "[x]", "[X]", ""):
                    if len(cells) >= 6:
                        date_cell = cells[3]
                    elif len(cells) == 5:
                        date_cell = cells[3] if re.match(r'^\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2})?$', cells[3]) else ""
                    else:
                        date_cell = ""
                else:
                    if len(cells) >= 5:
                        date_cell = cells[2]
                    elif len(cells) == 4:
                        date_cell = cells[2] if re.match(r'^\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2})?$', cells[2]) else ""
                    else:
                        date_cell = ""
                m = re.search(r'\b(\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2})?)\b', date_cell)
                if m:
                    return m.group(1)
        m = re.search(r'\b(\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2})?)\b', line)
        return m.group(1) if m else ""

    def _sort_active_items_outline(self) -> None:
        """Sort rows under ## Active Items by Last Updated descending (latest on top)."""
        if not self.work_file.exists():
            return
        lines = self._read_lines()
        active_start = -1
        active_end = len(lines)
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("## Active Items"):
                active_start = i
            elif active_start != -1 and (stripped.startswith("## ") or stripped.startswith("# ")):
                active_end = i
                break

        if active_start == -1:
            return

        section_lines = lines[active_start:active_end]

        has_table = any(l.strip().startswith("|") for l in section_lines)
        if has_table:
            data_rows = []
            pre_data_lines = []
            post_data_lines = []
            found_sep = False
            for line in section_lines:
                s = line.strip()
                if not found_sep:
                    pre_data_lines.append(line)
                    if _is_table_separator(s):
                        found_sep = True
                else:
                    if s.startswith("|") and not _is_table_separator(s) and not _is_table_header(s) and not post_data_lines:
                        data_rows.append(line)
                    else:
                        post_data_lines.append(line)

            if len(data_rows) > 1:
                def _row_sort_key(row_line: str):
                    d = self._extract_date_from_outline_row(row_line)
                    return (1, d) if d else (0, "")

                sorted_rows = sorted(data_rows, key=_row_sort_key, reverse=True)
                if sorted_rows != data_rows:
                    new_section = pre_data_lines + sorted_rows + post_data_lines
                    new_lines = lines[:active_start] + new_section + lines[active_end:]
                    self._write_lines(new_lines)
        else:
            bullet_blocks = []
            pre_lines = []
            post_lines = []
            cur_block = []
            in_bullets = False
            for line in section_lines:
                stripped = line.strip()
                if (
                    stripped.startswith("- [ ]")
                    or stripped.startswith("- [x]")
                    or stripped.startswith("- **")
                    or (stripped.startswith("- [") and not stripped.startswith("- [ ]"))
                ):
                    if cur_block:
                        bullet_blocks.append(cur_block)
                    cur_block = [line]
                    in_bullets = True
                elif in_bullets and (line.startswith("  ") or line.startswith("\t")):
                    cur_block.append(line)
                elif in_bullets and not stripped:
                    if cur_block:
                        bullet_blocks.append(cur_block)
                        cur_block = []
                    post_lines.append(line)
                else:
                    if cur_block:
                        bullet_blocks.append(cur_block)
                        cur_block = []
                    if not in_bullets:
                        pre_lines.append(line)
                    else:
                        post_lines.append(line)
            if cur_block:
                bullet_blocks.append(cur_block)

            if len(bullet_blocks) > 1:
                def _bullet_sort_key(block):
                    text = "".join(block)
                    m = re.search(r'\b(\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2})?)\b', text)
                    d = m.group(1) if m else ""
                    return (1, d) if d else (0, "")

                sorted_blocks = sorted(bullet_blocks, key=_bullet_sort_key, reverse=True)
                if sorted_blocks != bullet_blocks:
                    flattened = [l for b in sorted_blocks for l in b]
                    new_section = pre_lines + flattened + post_lines
                    new_lines = lines[:active_start] + new_section + lines[active_end:]
                    self._write_lines(new_lines)

    def _refresh_outline_dashboard(self) -> None:
        """Refresh child agent report lines in WORK-NEW.md."""
        lines = self._read_lines()
        items = self._parse_outline_blocks()
        changed = False

        for parent_id, item in items.items():
            children = self.get_children(parent_id)
            if not children:
                continue
            for child_name, child_status, config in children:
                resolved = self._resolve_child_note(parent_id, config)
                relpath = self._child_note_relpath(parent_id, resolved) if resolved else ""
                sched = config.get('schedule', '')
                reason = self._read_child_attention(resolved)
                reason_str = f" — {reason}" if reason else ""
                sched_str = f" ({sched})" if sched else ""
                title = config.get('title', child_name)
                target_str = f" → [{title}]({relpath})" if relpath else ""

                if item.get("format") == "table":
                    child_badge = f"<br>↳ [{child_name}]({parent_id}/children/{child_name}/RUNS.md){sched_str}{reason_str}{target_str}"
                    cells = [c.strip() for c in item["lines"][0].split("|")[1:-1]]
                    task_idx = 1 if len(cells) >= 3 and cells[0] in ("[ ]", "[x]", "[X]", "") else 0
                    if task_idx < len(cells):
                        task_val = cells[task_idx]
                        if f"{child_name}" in task_val:
                            task_val = re.sub(rf"<br>↳\s*`?\[?{re.escape(child_name)}\]?(?:\([^)]*\))?[^<]*", child_badge, task_val)
                        else:
                            task_val += child_badge
                        cells[task_idx] = task_val
                        new_row = "| " + " | ".join(cells) + " |\n"
                        if new_row != item["lines"][0]:
                            item["lines"][0] = new_row
                            changed = True
                else:
                    child_line = f"  - Child: **[{child_name}]({parent_id}/children/{child_name}/RUNS.md)** `status: {child_status}`{sched_str}{reason_str}{target_str}\n"
                    found = False
                    for idx, l in enumerate(item["lines"]):
                        if re.search(rf"Child:\s*\*\*\[?{re.escape(child_name)}\]?", l):
                            if item["lines"][idx] != child_line:
                                item["lines"][idx] = child_line
                                changed = True
                            found = True
                            break
                    if not found:
                        item["lines"].append(child_line)
                        changed = True

        if changed:
            rebuilt = []
            cur_idx = 0
            for item_id, item in items.items():
                rebuilt.extend(lines[cur_idx:item["start"]])
                rebuilt.extend(item["lines"])
                cur_idx = item["end"]
            rebuilt.extend(lines[cur_idx:])
            lines = rebuilt

        text = "".join(lines)
        new_text = self._replace_needs_attention_block(text, "")
        if new_text != text:
            self._write_lines([l + "\n" for l in new_text.splitlines()])
        elif changed:
            self._write_lines(lines)

        self._sort_active_items_outline()

