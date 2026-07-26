# Research Agent — Code Snippets

State: IMPLEMENTED

**Reference for:** `plans/research-agent.md`

---

## RUNS.md Format

```markdown
# AI Security Research

## Config
type: research
topic: AI Security
note_path: [[AI Security]]
sources:
  https://arxiv.org/list/cs.CR/recent
  https://openai.com/blog
  https://www.anthropic.com/research
schedule: 0 6 * * 1        # every Monday 6am
timeout: 10                # minutes before agent times out (default: 4)

## Research Context
Focus on: model vulnerabilities, alignment failures, supply chain risks
Exclude: consumer AI apps, chatbot features
Key papers to watch: [[AI Security/Papers]]

## Run History

| ID | Summary | Status | Last Updated |
|---|---|---|---|
| 20260717-001 | [Added 3 new papers on model vulnerabilities](runs/20260717-001/) | success | 2026-07-17 |
```

---

## RESEARCH-PROMPT.md (full content)

```markdown
# Work Loop Prompt — Research Agent

Each iteration runs a research cycle on ONE item. The script determines which item.

## Ground rules
- Your job is to **research and update**, not to implement or analyze broadly
- Fetch and read each source URL listed in the research config
- Compare findings against the existing note — identify new information, outdated claims, and gaps
- Write an updated version of the note (overwrite in-place)
- Write a research summary to `{ITEM_DIR}/runs/{run_id}/research.md`
- Use Obsidian wiki links `[[filename]]` for all references
- Any file you create must include a back-link to `[[CONVERSATION]]` near the top
- Be concise in the note — bullet points, not essays
- In the research summary, list each change with a date, description, and source URL

---

Use ITEM_ID, WORK_LOOP_DIR, and ITEM_DIR passed at the end of this prompt.

## Step 1 — Load Context

1. Read `{ITEM_DIR}/CONVERSATION.md` for prior research thread (newest first — read bottom-up for history).
2. Read `{ITEM_DIR}/background.md` for internal context (if present).
3. Read `{ITEM_DIR}/context/` for additional context (if present).
4. Read the research config from `{ITEM_DIR}/RUNS.md` — extract sources, note_path, and Research Context.
5. Read the existing note at the target path (resolve the wiki link to a file path).
6. Read prior run summaries from `{ITEM_DIR}/runs/` (newest first) for context on what was already found.

## Step 2 — Fetch Sources

For each source URL in the config:
1. Fetch the URL content
2. Extract key information relevant to the topic and research context
3. Discard irrelevant content
4. Note which sources were accessible and which failed

## Step 3 — Compare and Identify Changes

Compare findings against the existing note:
- **New information** — facts, developments, or links not in the current note
- **Outdated claims** — information in the note that is no longer accurate
- **Gaps** — topics the research context says to cover but the note doesn't address
- **Confirmed stable** — information that remains accurate

## Step 4 — Write Updated Note

Overwrite the note at `note_path` with the updated content:
- Preserve the note's existing structure and formatting
- Add new information in relevant sections
- Update or remove outdated claims
- Add a `## Recent Updates` section at the top with the date and a brief summary
- Use wiki links `[[filename]]` for all cross-references
- Keep it concise — bullet points, not essays

## Step 5 — Write Research Summary

Create `{ITEM_DIR}/runs/{run_id}/research.md`:

```markdown
## {YYYY-MM-DD} — {topic}

### Changes
- [Added/Updated/Removed] [description] — [source URL]

### Sources Fetched
- [URL] — [status: OK / FAILED]

### Notes
- [Any gaps, questions, or follow-ups]
```

Include a back-link to `[[CONVERSATION]]` at the top of the file if it's a new file.

## Step 6 — Update WORK.md

Find the row with `{ITEM_ID}` in `{WORK_LOOP_DIR}/WORK.md`. Set Status to "needs-review".
If the Title cell is plain text (not a markdown link), derive a concise title and replace with `[concise title]({ITEM_ID}/CONVERSATION.md)`.
```

---

## run-loop.py Code Snippets

### 1. Refactor `_parse_runs_md_config()` → `_parse_config_block(text)` + `_parse_runs_md(item_id)`

```python
def _parse_config_block(self, text: str) -> dict:
    """Parse a ## Config block from text, return normalized dict."""
    config = {
        'command': '', 'params': '', 'schedule': '',
        'location': '', 'locations': [],
        'heartbeat_file': '', 'timeout': DEFAULT_TIMEOUT_MIN,
        'aggregation_script': '', 'analysis_prompt': '',
        'type': '', 'topic': '', 'note_path': '', 'sources': [],
    }
    m = re.search(r'^## Config\s*\n(.*?)(?=^##|\Z)', text, re.MULTILINE | re.DOTALL)
    if not m:
        return config
    # ... existing parsing logic ...
    return config

def _parse_runs_md(self, item_id: str) -> dict:
    """Parse RUNS.md — returns config dict with 'research_context' key."""
    runs_file = self.work_dir / item_id / "RUNS.md"
    if not runs_file.exists():
        return self._empty_config()
    text = runs_file.read_text()
    config = self._parse_config_block(text)
    # Parse Research Context block
    m = re.search(r'^## Research Context\s*\n(.*?)(?=^##|\Z)', text, re.MULTILINE | re.DOTALL)
    config['research_context'] = m.group(1).strip() if m else ''
    return config
```

All existing callers of `_parse_runs_md_config()` switch to `_parse_runs_md()`.

### 2. Update `get_item_type()` to return `'research'`

```python
def get_item_type(self, item_id: str) -> str:
    """Return 'research', 'script', or 'conversation'."""
    runs_file = self.work_dir / item_id / "RUNS.md"
    if not runs_file.exists():
        return 'conversation'
    config = self._parse_runs_md(item_id)
    if config.get('type') == 'research':
        return 'research'
    return 'script'
```

### 3. Add `_initialize_research_item()` method

```python
def _initialize_research_item(self, item_id: str, config: dict) -> None:
    """Create folder, seed CONVERSATION.md and RUNS.md for a research item."""
    item_dir = self.work_dir / item_id
    item_dir.mkdir(parents=True, exist_ok=True)
    
    conv_file = item_dir / "CONVERSATION.md"
    if not conv_file.exists():
        topic = config.get('topic', item_id)
        today = datetime.now().strftime('%Y-%m-%d')
        conv_file.write_text(f"## {today} | User\n\nResearch item: {topic}\n")
    
    initial_status = 'scheduled' if config.get('schedule') else 'ready'
    self.update_col(item_id, COL_STATUS, initial_status)
    print(f"[{_ts()}] Initialized research item: {item_id} (status: {initial_status})")
```

### 4. Update `initialize_new_item()` to route research items

```python
def initialize_new_item(self, item_id: str) -> None:
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

    # ... existing conversation item logic ...
```

### 5. Add `'research'` to `TRIGGER_STATUSES`

```python
TRIGGER_STATUSES = {'ready', 'analyze', 'implement', 'resolved', 'research'}
```

### 6. Extend `process_local()` to handle `research` mode

In `process_local()`, after reading the mode, inject the research prompt + config:

```python
mode = self.get_col(item_id, COL_STATUS)

if mode == "research":
    config = self._parse_runs_md(item_id)
    research_prompt_file = self.script_dir / "RESEARCH-PROMPT.md"
    if research_prompt_file.exists():
        prompt_text = research_prompt_file.read_text()
    else:
        prompt_text = self.prompt_file.read_text()
        print(f"[{_ts()}] WARNING: RESEARCH-PROMPT.md not found, using LOOP-PROMPT.md")
    
    # Build sources list
    sources = config.get('sources', [])
    sources_str = '\n'.join(f'- {s.strip()}' for s in sources) if sources else '(none)'
    context = config.get('research_context', '')
    
    item_dir = str(self.work_dir / item_id)
    prompt = (
        f"{prompt_text}\n\n"
        f"topic: {config.get('topic', '')}\n"
        f"note_path: {config.get('note_path', '')}\n"
        f"sources:\n{sources_str}\n"
        f"research_context:\n{context}\n"
        f"\nITEM_ID: {item_id}\n"
        f"WORK_LOOP_DIR: {self.work_dir}\n"
        f"ITEM_DIR: {item_dir}"
    )
else:
    # ... existing prompt loading logic (implement, resolved, default) ...
```

### 7. Add `_create_run_dir()` method

```python
def _create_run_dir(self, item_id: str, run_id: str) -> Path:
    """Create runs/{run_id}/ directory and return its path."""
    run_dir = self.work_dir / item_id / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir
```

### 8. Add `_append_research_run()` method

```python
def _append_research_run(self, item_id: str, run_id: str, summary: str) -> None:
    """Append a new row to RUNS.md run history table for research items."""
    runs_file = self.work_dir / item_id / "RUNS.md"
    today = datetime.now().strftime('%Y-%m-%d')
    summary_link = f"[{summary}](runs/{run_id}/)"
    row = f"| {run_id} | {summary_link} | running | {today} |\n"
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
        header = "\n| ID | Summary | Status | Last Updated |\n|---|---|---|---|\n"
        text += header + row
        runs_file.write_text(text)
    else:
        insert_at = (last_data_idx + 1) if last_data_idx >= 0 else (table_sep_idx + 1)
        lines.insert(insert_at, row)
        runs_file.write_text("".join(lines))
```

### 9. Handle post-research status transition

After the harness completes in `process_local()`, handle the research-specific status transition:

```python
# After exit_code check, before the existing success/failure handling:
if mode == "research":
    if exit_code == 0:
        config = self._parse_runs_md(item_id)
        # Find the latest run directory and extract summary from research.md
        run_dir = self.work_dir / item_id / "runs"
        latest_run = None
        if run_dir.exists():
            dirs = [d for d in run_dir.iterdir() if d.is_dir()]
            if dirs:
                latest_run = sorted(dirs, reverse=True)[0].name
        if latest_run:
            research_file = run_dir / latest_run / "research.md"
            if research_file.exists():
                # Extract first line after the header as summary
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
    # ... existing failure handling ...
```

### 10. Extend `get_scheduled_items()` to include research items

Rename `get_scheduled_script_items()` to `get_scheduled_items()` and include research:

```python
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
```

Update the main loop to call `get_scheduled_items()` instead of `get_scheduled_script_items()`.

### 11. Update main loop to route research items

In `run()`, the main loop currently dispatches script items to `process_script_item()`. Add research routing:

```python
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
    
    # ... existing conversation item logic (remote/local) ...
```

### 12. Skip research items in `resume_running_script_items()`

Research items don't need resume/polling (they run synchronously via the harness). The existing check `if self.get_item_type(item_id) != 'script': continue` already handles this since `get_item_type()` now returns `'research'` for research items.
