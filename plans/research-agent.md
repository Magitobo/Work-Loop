# Research Agent Extension for Work-Loop

**Session ID:** ses_research_agent
**Created:** 7/17/2026
**Updated:** 7/17/2026

---

## User

Build a research agent extension for Work-Loop that keeps Obsidian notes updated with the latest information from trusted web sources. Uses local LLMs, runs on a cron schedule, and produces both an updated note and per-run research summaries. Multiple specialized agents covering different topics.

---

## Overview

Research items are a new item type that sits between conversation items and script items. They use **RUNS.md for scheduling** (cron) but the **agent does the work via tool use** (web fetch, file I/O) rather than dispatching shell commands.

### What it does

1. On schedule, the agent fetches each source URL
2. Compares findings against the existing Obsidian note
3. Writes an updated version of the note (in-place)
4. Writes a research summary to `runs/{run_id}/research.md`
5. Appends a row to RUNS.md with a link to the summary
6. Updates WORK.md status to `needs-review` for human approval

### State machine

```
scheduled → ready (cron fires) → in-progress → needs-review
                                                         ↓
                                                   ready (next cycle)
```

On success with a schedule, the status returns to `scheduled`. The human reviews during `needs-review` and sets back to `ready` to trigger the next cycle.

---

## RUNS.md Format

See `research-agent-code.md` for the full RUNS.md example.

### Config fields

| Field | Required | Description |
|---|---|---|
| `type` | Yes | Must be `research` |
| `topic` | Yes | Human-readable topic name |
| `note_path` | Yes | Obsidian wiki link to the target note |
| `sources` | Yes | One or more URLs to fetch (indented list) |
| `schedule` | No | Cron expression; if present, status starts as `scheduled` |
| `timeout` | No | Minutes before agent times out (default: 4) |

### Research Context section

Everything after `## Research Context` (until next `##` header or EOF) is injected verbatim into the agent prompt. This is where you define scope, exclusions, key papers, and any other topic-specific guidance.

### Run history table

Each research cycle appends a row to the table:

| ID | Summary | Status | Last Updated |
|---|---|---|---|
| 20260717-001 | [Added 3 new papers on model vulnerabilities](runs/20260717-001/) | success | 2026-07-17 |

- **ID** — auto-generated `YYYYMMDD-NNN`
- **Summary** — markdown link to `runs/{run_id}/research.md`
- **Status** — `success`, `needs-review`, or `failed`
- **Last Updated** — date of the research cycle

---

## New file: `RESEARCH-PROMPT.md`

Full prompt content in `research-agent-code.md`. The prompt defines a 6-step workflow:

1. **Load Context** — Read CONVERSATION.md, background.md, context/, RUNS.md config, existing note, and prior run summaries
2. **Fetch Sources** — Fetch each URL, extract relevant info, note failures
3. **Compare and Identify Changes** — Find new info, outdated claims, gaps, confirmed stable items
4. **Write Updated Note** — Overwrite in-place preserving structure, add `## Recent Updates` section
5. **Write research.md** — Create `runs/{run_id}/research.md` with changes, sources, and notes
6. **Update WORK.md** — Set status to `needs-review`, derive concise title if needed

---

## `run-loop.py` changes

Full code snippets in `research-agent-code.md`. Summary of the 12 changes:

1. **Refactor `_parse_runs_md_config()`** → `_parse_config_block(text)` + `_parse_runs_md(item_id)` that adds `research_context` key
2. **Update `get_item_type()`** to return `'research'` when `type: research` in config
3. **Add `_initialize_research_item()`** method to create folder and seed CONVERSATION.md
4. **Update `initialize_new_item()`** to route research items to the new initializer
5. **Add `'research'` to `TRIGGER_STATUSES`** set
6. **Extend `process_local()`** to handle `research` mode with prompt injection (loads RESEARCH-PROMPT.md, injects topic/notes/sources/context)
7. **Add `_create_run_dir()`** method to create `runs/{run_id}/` directory
8. **Add `_append_research_run()`** method to append a row to RUNS.md with summary link
9. **Handle post-research status transition** — extract summary from research.md, append RUNS.md row, set `scheduled` if cron configured, otherwise `done`
10. **Rename `get_scheduled_script_items()` → `get_scheduled_items()`** and include research items in cron check
11. **Update main loop** to route research items to `process_local()` instead of `process_script_item()`
12. **Skip research items in `resume_running_script_items()`** — already handled since `get_item_type()` returns `'research'`

---

## Summary of changes

### New files

| File | Purpose |
|---|---|
| `RESEARCH-PROMPT.md` | Agent instructions for fetch→compare→update workflow |

### Modified files

| File | Changes |
|---|---|
| `run-loop.py` | ~90 lines added, ~10 lines refactored across 9 methods |
| `test_run_loop.py` | Tests for research item parsing, initialization, run tracking, and processing |
| `README.md` | Document research items, RUNS.md format, state machine |

### Line count estimate

- `RESEARCH-PROMPT.md`: ~80 lines
- `run-loop.py`: ~90 lines added, ~10 lines refactored
- `test_run_loop.py`: ~140 lines of tests
- `README.md`: ~40 lines added

---

## Execution order

1. **Refactor `_parse_runs_md_config()`** → `_parse_config_block(text)` + `_parse_runs_md(item_id)` that adds `research_context`
2. **Update `get_item_type()`** to return `'research'` when `type: research`
3. **Add `_initialize_research_item()`** method
4. **Update `initialize_new_item()`** to route research items
5. **Add `'research'` to `TRIGGER_STATUSES`**
6. **Extend `process_local()`** to handle `research` mode with prompt injection
7. **Add `_create_run_dir()` and `_append_research_run()`** methods
8. **Handle post-research status transition** (extract summary, append RUNS.md row, set scheduled/done)
9. **Rename `get_scheduled_script_items()` → `get_scheduled_items()`** and include research
10. **Update main loop** to route research items to `process_local()`
11. **Create `RESEARCH-PROMPT.md`**
12. **Add tests**
13. **Update README.md**

---

## Key design decisions

- **Research items use RUNS.md, not a new file format** — reuses the existing config + cron infrastructure
- **Research Context lives in RUNS.md after `## Research Context`** — one file for all item metadata, zero new file types
- **Research items run locally only** — no remote dispatch needed; the agent uses its own tools (web fetch, file I/O)
- **`needs-review` is the gate** — human must approve before the next cycle; this prevents uncontrolled note mutations
- **Per-run details are in `runs/{run_id}/research.md`** — one file per cycle with changes, sources, and notes; linked from RUNS.md table
- **No new status values** — reuses `scheduled`/`ready`/`in-progress`/`needs-review`; the `type: research` field in RUNS.md is what distinguishes it from script items
- **Prompt injection via config fields** — topic, note_path, sources, and research_context are injected into the prompt as variables, keeping the prompt file generic and reusable across items
