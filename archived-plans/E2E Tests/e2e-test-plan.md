# E2E Test Plan

## Goal

Add end-to-end tests that run the real `opencode` harness (with `--format json`) against a synthetic workspace, then inspect the resulting NDJSON logs and workspace files for correct behavior.

## Why

Unit tests mock `harness.run()` and only verify WORK.md state changes. They miss:
- Agent directory not synced to workspace (caught the critic bug post-hoc)
- Prompt not injecting variables correctly
- Model failing to emit tool calls (e.g. critic subagent never spawned)
- Log format changes breaking failure classification

E2E tests exercise the full dispatch pipeline: agent sync -> prompt assembly -> harness invocation -> log capture -> post-run state.

## Architecture

### 1. Switch Harness to `--format json`

**File**: `run-loop.py` — `OpenCodeHarness.run()` (line ~207)

Change local:
```python
cmd = [
    "opencode", "run", "--auto", "--format", "json",
    "--title", item_id or "work-loop",
] + model_arg
```

Also update `OpenCodeHarness.launcher_script()` for remote dispatch (line ~306) — same change.

### 2. Background Execution via `conftest.py`

**New file**: `conftest.py`

- `pytest_configure()`: if a previous e2e run completed, surface its results at the top of the test output
- `pytest_sessionfinish()`: spawn `test_e2e.py` as a detached background process via `subprocess.Popen`, unless `PYTEST_E2E=1` is set (prevents recursion)
- Results go to `e2e_results.log` and `e2e_state.json` (exit code, passed/failed/error counts, timestamp)

### 3. Log Parser

**New module**: `test_e2e.py` — `JsonLogParser` class

JSON log format (from real opencode output):
```json
{"type":"tool_use", "part":{"tool":"task", "state":{"input":{"subagent_type":"critic"}, "status":"completed"}}}
{"type":"tool_use", "part":{"tool":"read", "state":{"input":{"filePath":"..."}, "status":"completed"}}}
{"type":"tool_use", "part":{"tool":"edit", "state":{"input":{"filePath":"..."}, "status":"completed"}}}
{"type":"step_finish", "part":{"reason":"stop"}}
```

Parser methods:
- `tool_calls()` -> list of {tool, input, status}
- `has_subagent_spawn("critic")` -> bool
- `has_file_edit("CONVERSATION.md")` -> bool
- `has_webfetch(url_prefix)` -> bool
- `has_step_stop()` -> bool (session ended cleanly)

### 4. Workspace Fixture

Each test creates an isolated `tempfile.TemporaryDirectory()`:

```
tmp/
├── WORK.md                    <- item table
├── LOOP-PROMPT.md             <- copied from repo
├── IMPL-PROMPT.md             <- copied from repo
├── RESOLVE-PROMPT.md          <- copied from repo
├── RESEARCH-PROMPT.md         <- copied from repo
├── CHILD-RESEARCH-PROMPT.md   <- copied from repo
├── .opencode/
│   └── agents/
│       ├── critic.md          <- copied from repo
│       └── code-reviewer.md   <- copied from repo
└── ITEM-001/
    ├── CONVERSATION.md        <- pre-populated
    └── context/               <- optional
```

### 5. Test Classes (~14 tests)

**TestAnalyzeMode** (4)
- `test_critic_subagent_spawned` — JSON log has `task(subagent_type="critic")`, status=completed
- `test_conversation_md_written` — JSON log has `edit(.../CONVERSATION.md)`
- `test_work_md_updated` — WORK.md status = `needs-review`
- `test_prompt_variables_injected` — prompt contains ITEM_ID, WORK_LOOP_DIR, ITEM_DIR

**TestImplementMode** (2)
- `test_code_reviewer_spawned` — JSON log has `task(subagent_type="code-reviewer")`
- `test_work_dir_extracted` — `--dir` points to extracted work_dir from CONVERSATION.md

**TestResolvedMode** (2)
- `test_no_subagent_spawn` — JSON log has NO `task` tool calls
- `test_row_moved_to_done` — WORK.md Done section contains the item

**TestResearchMode** (2)
- `test_webfetch_for_sources` — JSON log has `webfetch` calls matching RUNS.md sources
- `test_research_summary_written` — JSON log has `write(.../runs/{id}/research.md)`

**TestChildResearch** (2)
- `test_parent_vars_in_prompt` — prompt contains PARENT_ID, PARENT_DIR
- `test_child_status_updated` — WORK-CHILDREN.md status transitions correctly

**TestAgentSync** (2)
- `test_agent_dir_copied_to_workspace` — `.opencode/agents/` exists in target cwd
- `test_no_error_when_agent_dir_missing` — graceful no-op

### 6. Prompt Strategy

Real prompts are used, copied from the repo. CONVERSATION.md fixtures are short (1-2 entries). This keeps model processing fast (1-3 min per test) while exercising real tool call paths.

### 7. Files to Create/Modify

| File | Action |
|---|---|
| `run-loop.py` | `--format json` in `OpenCodeHarness.run()` + `launcher_script()` |
| `test_e2e.py` | New — ~400 lines, 14 tests, JsonLogParser, fixture helpers |
| `conftest.py` | New — ~60 lines, background dispatch + result surfacing |
| `.gitignore` | Add `e2e_results.log`, `e2e_state.json` |

### 8. Execution

```bash
# Normal run — e2e dispatched in background:
python3 -m pytest test_run_loop.py test_prompt_subagents.py
# -> 272 tests in 0.7s, background e2e running

# Check results:
cat e2e_results.log

# Run e2e directly (foreground):
PYTEST_E2E=1 python3 -m pytest test_e2e.py -v
```

### 9. Risks

| Risk | Mitigation |
|---|---|
| Llama server down | Tests have timeouts; failures surfaced next run |
| Tests too slow | Minimal fixtures, no extra context files |
| Prompt changes break expectations | Tests verify structure (tool names, paths), not content |
| Background process leaks | PID tracked; stale processes detected |