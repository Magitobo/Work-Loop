# Plan: Sub-Agents with Parent Agency

## 1. Goal

Enable work items to spawn and manage child research agents (sub-agents) through a propose/approve workflow. The parent agent acts as a delegated manager — it proposes structural changes to the Work-Loop, the user approves, and the agent executes.

## 2. File Structure

```
{ITEM_ID}/                          ← parent item
├── CONVERSATION.md                 ← parent conversation thread
├── background.md                   ← user-owned requirements
├── context/                        ← shared research output (parent + children write here)
│   ├── area-comparison.md
│   └── mm2h-rules.md
├── children.md                     ← parent's dashboard of children
└── agents/                         ← child agents (nesting depth: 1 only)
    ├── areas/                      ← child agent 1
    │   ├── RUNS.md                 ← loop reads this; parent writes/updates it
    │   ├── CONVERSATION.md         ← parent's management log for this child
    │   └── runs/                   ← run history (loop writes)
    │       └── 20250726-001/
    │           └── research.md
    └── rules/                      ← child agent 2
        ├── RUNS.md
        ├── CONVERSATION.md
        └── runs/
            └── 20250725-003/
                └── research.md
```

### File Ownership

| File | Purpose | Who Writes | Who Reads |
|---|---|---|---|
| `CONVERSATION.md` | Main conversation thread | **Both** | Both |
| `background.md` | User requirements/constraints | **User only** | Parent agent |
| `context/*.md` | Shared research artifacts | **Parent + children** | Parent agent |
| `children.md` | Parent's dashboard of all children | **Parent agent** | Parent agent |
| `agents/{name}/RUNS.md` | Child agent config + run history | **Parent** (config) / **Loop** (run rows) | Loop, parent |
| `agents/{name}/CONVERSATION.md` | Parent's management log for this child | **Parent agent** | Parent agent |
| `agents/{name}/runs/` | Run summaries (research.md) | **Loop** (after child runs) | Parent agent |

### Child RUNS.md Format

Unified with top-level research RUNS.md — same Config block, same `## Research Context` block, same Run History table. Two additional config keys for hierarchy:

```markdown
## Config
type: research
parent: KL-MM2H
status: ready
topic: Neighborhood walkability analysis
note_path: ../context/area-walkability.md
sources:
  https://www.walkscore.com/score/Kuala-Lumpur
schedule: 0 */6 * * *

## Research Context
Evaluate walkability for top 5 KL neighborhoods.

## Run History

| ID | Summary | Status | Last Updated | Log |
|---|---|---|---|---|
```

Key points:
- `type: research` — loop identifies this as a research item (same as top-level)
- `parent: {ITEM_ID}` — loop reads this for orphan detection
- `status: {status}` — loop reads this for scheduling/dispatch decisions; defaults to `ready` if missing
- `note_path` — relative to child's cwd (`agents/{name}/`), so `../context/` resolves to parent's `context/`
- `## Research Context` — same format as top-level; injected verbatim into agent prompt
- No `context/` folder under the child — parent's shared context is the only output target
- Run history table uses same format as top-level RUNS.md

### children.md Format

Parent's dashboard — a markdown table summarizing child agent state:

```markdown
# Child Agents

| Agent | Topic | Status | Schedule | Last Run |
|-------|-------|--------|----------|----------|
| areas | Walkability analysis | ready | Weekly | 2025-07-26 |
| rules | MM2H property rules | success | Weekly | 2025-07-25 |
| buildings | Condo building shortlist | paused | — | — |
```

Status values: `ready`, `scheduled`, `running`, `success`, `needs-review`, `done`, `paused`

This file is analogous to WORK.md in function — it's the parent agent's operational view of its managed agents. The user reads this to understand what's happening.

## 3. Status System

### Child statuses (in `status:` config key of RUNS.md):

| Status | Meaning |
|---|---|
| `ready` | Ready to run (one-off) or cron-promoted |
| `scheduled` | Has cron; waiting for cron to fire |
| `running` | Currently being processed by loop |
| `success` | Latest run completed successfully |
| `needs-review` | Latest run failed or needs user review |
| `done` | One-off complete (parent can re-promote to `ready` to re-run) |
| `paused` | Manually paused by parent agent |

### Transitions:

```
ready ──(loop processes)──> running ──(completes)──>
    ├── success ──┬── scheduled (if cron)
    │             └── ready (if no cron, parent decides)
    └── needs-review (user or parent promotes back to ready)

scheduled ──(cron fires)──> ready
paused ──(parent proposes)──> ready
done ──(parent proposes)──> ready (re-run)
```

After a successful run:
- **Has schedule** → `scheduled` (cron loop will promote)
- **No schedule** → `ready` (parent decides whether to re-run or mark done)

This matches top-level research item behavior: scheduled items loop, one-offs complete once.

## 4. Loop Changes

All changes are additive — no existing behavior is modified.

### 4.1 New Methods

#### `_parse_child_runs_md(child_path: Path) -> dict`

Parses a child's RUNS.md using the same logic as top-level:
- Calls `_parse_config_block(text)` on the full file content
- Extracts `## Research Context` block via regex (same as top-level)
- Returns config dict with all standard keys plus `research_context`
- `parent` and `status` keys come from the Config block (defaults: `status=ready` if missing)

#### `_get_child_status(child_config: dict) -> str`

`child_config.get('status', 'ready')` — reads status from config dict.

#### `_get_parent_id(child_config: dict) -> str | None`

`child_config.get('parent')` — reads parent ID from config dict.

#### `get_children(parent_id: str) -> list[tuple[str, str, dict]]`

Scans `{work_dir}/{parent_id}/agents/*/RUNS.md`. For each found file:
- Calls `_parse_child_runs_md(child_path)` to get config dict
- If `config.get('parent') != parent_id`, skips (orphan detection)
- Returns `(child_name, status, config)` where `status = _get_child_status(config)`
- Returns empty list if no children found

#### `_update_child_status(child_path: Path, status: str) -> None`

Parses child RUNS.md text, replaces the `status:` line in the Config block with the new value, writes file back. Same pattern as existing status update logic.

#### `process_child(parent_id: str, child_name: str) -> None`

Processes a child as a research item:
- Calls `_parse_child_runs_md()` to get config
- Generates run ID
- Calls `_update_child_status()` to set status to `running`
- Updates `children.md` to reflect running state
- Processes exactly like `process_local()` in research mode, with:
  - `PARENT_ID` and `PARENT_DIR` env vars passed in prompt
  - `ITEM_DIR` points to child's folder (`agents/{child_name}/`)
- On completion:
  - Calls `_update_child_status()` to set final status
  - Appends run row to child's RUNS.md history (reuse existing `_append_research_run()` with child path)
  - Updates `children.md`
  - If success + schedule → `scheduled`
  - If success + no schedule → `ready`
  - If failure → `needs-review`

#### `resume_running_children() -> None`

On startup, finds all running children across all parent items and resumes polling (same pattern as `resume_running_script_items()`).

### 4.2 Main Loop Changes

In `run()` method, after processing top-level ready items:

```python
# Process children after top-level items
for parent_id in self._get_all_item_ids():       # includes done items
    for child_name, child_status, child_config in self.get_children(parent_id):
        if child_status == 'scheduled' and child_config.get('schedule'):
            if self._cron_should_run(child_config['schedule']):
                self._update_child_status(child_path, 'ready')
        if child_status == 'ready':
            self.process_child(parent_id, child_name)
```

The `_get_all_item_ids()` includes all items (even `done` ones), because a done parent might still have active scheduled children.

**Order:** Children are processed after top-level items each iteration. This ensures the parent's own results are fresh before children start.

### 4.3 Note on `note_path` Resolution

For child agents, `note_path` is relative to the child's cwd (`agents/{child_name}/`). The prompt includes `note_path` as-is, and the agent resolves it. For example:
- Child cwd: `{ITEM_DIR}/agents/areas/`
- `note_path`: `../context/area-walkability.md`
- Resolves to: `{ITEM_DIR}/context/area-walkability.md` (parent's shared context)

No special handling needed in the loop — this is handled by the agent in RESEARCH-PROMPT.md.

## 5. Prompt Changes

### 5.1 LOOP-PROMPT.md — "Managing Child Agents" Section

Add a new section after Step 5 (Update WORK.md). Covers:

#### 5.1.1 Discovery

The parent agent reads:
- `children.md` — its current dashboard of children
- `agents/*/CONVERSATION.md` — management logs for each child
- `agents/*/RUNS.md` — child configs and latest run status
- `agents/*/runs/*/research.md` — child run results

#### 5.1.2 Proposing Child Agents

When the parent identifies a research gap, it proposes a new child:

```markdown
## Proposals

### Create child agent: `areas` — Neighborhood walkability analysis

**RUNS.md to create:**
```markdown
## Config
type: research
parent: {ITEM_ID}
status: ready
topic: Neighborhood walkability analysis
note_path: ../context/area-walkability.md
sources:
  https://www.walkscore.com/score/Kuala-Lumpur
schedule: 0 */6 * * *

## Research Context
Evaluate walkability for top 5 KL neighborhoods.
```

**Questions:** Should I create this child agent?
```

User responds with approval/denial/modification. Parent executes after approval.

#### 5.1.3 Updating Child Agents

Proposed changes to existing children:

```markdown
## Proposals

### Update child agent: `rules` — Change schedule to daily

Current: schedule: Weekly
Proposed: schedule: Daily

**Questions:** Should I update this child agent's schedule?
```

#### 5.1.4 Deleting Child Agents

```markdown
## Proposals

### Delete child agent: `buildings` — No longer needed

**Questions:** Should I delete this child agent?
```

#### 5.1.5 Pausing/Resuming Child Agents

Parent can directly update child status without user approval (low-risk action):

```markdown
## Actions

- Paused child agent `buildings` (no current relevance)
- Resumed child agent `rules` (daily schedule will start next cycle)
```

#### 5.1.6 Reading Child Results

The parent agent synthesizes child run results into its own CONVERSATION.md entries:

```markdown
### Child Agent Updates

**areas** (success): Updated area-walkability.md with 3 new neighborhoods.
**rules** (needs-review): MM2H rules updated but source failed — needs verification.
```

#### 5.1.7 Maintaining children.md

After any child lifecycle change (create/update/delete/pause/resume/run complete), the parent updates `children.md`.

### 5.2 RESEARCH-PROMPT.md — Child Agent Awareness

Add a section at the top after "Use ITEM_ID, WORK_LOOP_DIR, and ITEM_DIR passed below":

```markdown
## Child Agent Awareness

If PARENT_ID is set, you are a child research agent. Your results feed into
your parent's shared context — not your own private output.

- Your note_path points to your parent's context/ (relative path, e.g. ../context/file.md)
- Write your research summary to {ITEM_DIR}/research.md (under runs/{run_id}/)
- Your parent agent reads your results and synthesizes them
- You do NOT modify WORK.md or CONVERSATION.md at the parent level
- If note_path contains `../`, it resolves to your parent's {ITEM_DIR}/
- If note_path contains `context/`, it resolves to your own {ITEM_DIR}/context/ 
  (but prefer `../context/` to write to parent's shared context)
```

The loop passes `PARENT_ID` and `PARENT_DIR` env vars:
- `PARENT_ID` — the parent item's ID
- `PARENT_DIR` — the parent item's folder path (`{WORK_LOOP_DIR}/{PARENT_ID}`)

### 5.3 Prompt Variable Changes

In `process_child()`, the prompt is constructed with additional variables:

```python
prompt = (
    f"{prompt_text}\n\n"
    f"topic: {config.get('topic', '')}\n"
    f"note_path: {config.get('note_path', '')}\n"
    f"sources:\n{sources_str}\n"
    f"research_context:\n{context}\n"
    f"\nPARENT_ID: {parent_id}\n"
    f"PARENT_DIR: {parent_dir}\n"
    f"ITEM_ID: {item_id}\n"
    f"WORK_LOOP_DIR: {self.work_dir}\n"
    f"ITEM_DIR: {item_dir}"
)
```

## 6. Parent Agent Agency Model

The propose/approve workflow is the core interaction pattern:

```
1. Parent agent identifies a need (new child, update, delete, etc.)
2. Parent writes proposal to CONVERSATION.md (or children.md for low-risk)
3. User responds: "Oliver: Yes, create it." or "Oliver: no, do X instead"
4. Parent executes: modifies files, creates/updates children
5. Loop discovers and processes changes on next iteration
```

### Agency Levels:

| Action | Requires Approval? | Where Logged |
|---|---|---|
| Create child agent | Yes | CONVERSATION.md proposal |
| Update child config | Yes | CONVERSATION.md proposal |
| Delete child agent | Yes | CONVERSATION.md proposal |
| Pause child agent | No | children.md (direct) |
| Resume child agent | No | children.md (direct) |
| Update child schedule | No | children.md (direct) |

Low-risk actions (pause/resume/update schedule) don't require explicit approval — the parent can do these directly and log in children.md. Higher-risk actions (create/delete/update config) require user approval via CONVERSATION.md.

### Example Workflow:

**Parent in CONVERSATION.md:**
```markdown
### Findings

Based on the area comparison, I notice we have no walkability analysis for the top 3 areas.
This is a gap in our research.

### Proposals

Create child agent: `areas-walkability` — Walkability analysis for top 3 areas.
Sources: WalkScore, Google Maps local search, local forum reviews.
note_path: ../context/area-walkability.md
Schedule: Weekly (until we have enough data)

### Questions

Should I create this child agent?
```

**User:**
```
Oliver: Yes, create it. Also make it run daily instead of weekly.
```

**Parent executes:**
1. Creates `agents/areas-walkability/RUNS.md`
2. Creates `agents/areas-walkability/CONVERSATION.md`
3. Updates `children.md` with new entry
4. (Loop picks it up on next iteration)

## 7. Edge Cases & Handling

| Case | Handling |
|---|---|
| Parent item deleted | Children become orphans. Loop skips them (`parent` key mismatch). Parent agent can clean up via proposal. |
| Child RUNS.md has no `status:` config key | Defaults to `ready` |
| Child RUNS.md has no `parent:` config key | Included in all parents' scans (`parent` = None). Parent agent can detect and fix via proposal. |
| Multiple parents writing to same `context/` file | Shouldn't happen if parent manages it. If it does, last write wins (standard file behavior). |
| Child agent fails | Status set to `needs-review`. Parent sees this in next iteration and can propose re-run. |
| Cron fires while child is `running` | Skipped (only promotes `scheduled` → `ready`). Child completes first. |
| User directly edits child's RUNS.md | Loop reads user's edit. If `status:` changed, respects it. |

## 8. Testing Strategy

### 8.1 Unit Tests (test_run_loop.py)

| Test | What |
|---|---|
| `_parse_child_runs_md` | Parses unified format, extracts config + research_context |
| `_get_child_status` | Reads `status:` from config dict, defaults to `ready` |
| `_get_parent_id` | Reads `parent:` from config dict |
| `get_children` (no children) | Empty parent folder returns [] |
| `get_children` (with children) | Returns list of (name, status, config) tuples |
| `get_children` (mixed statuses) | Returns all children regardless of status |
| `get_children` (orphan detection) | Skips children with wrong parent_id |
| `process_child` (success + schedule) | Status transitions: ready → running → scheduled |
| `process_child` (success + no schedule) | Status transitions: ready → running → ready |
| `process_child` (failure) | Status transitions: ready → running → needs-review |
| `_update_child_status` | Correctly updates `status:` line in Config block |
| `resume_running_children` | Resumes running children on startup |
| Child cron promotion | `scheduled` → `ready` when cron fires |
| Child in `done` parent | `get_children` still finds children of done parents |

### 8.2 Prompt Tests

| Test | What |
|---|---|
| RESEARCH-PROMPT.md child awareness | Prompt includes PARENT_ID section when applicable |
| LOOP-PROMPT.md child management | Prompt includes child agent management section |
| No hardcoded paths in child prompts | Prompt uses relative/variable paths |

## 9. Implementation Order

### Phase 1: Loop Infrastructure (run-loop.py)

1. `_parse_child_runs_md()` — parse unified format for child path, calls `_parse_config_block()` + extracts `research_context`
2. `_get_child_status()` — thin config read
3. `_get_parent_id()` — thin config read
4. `get_children()` — uses `_parse_child_runs_md()`, orphan detection via config
5. `_update_child_status()` — one-line replacement in Config block
6. `_append_research_run_for_child()` — reuse existing `_append_research_run()` with child path
7. `process_child()` — process child as research item with PARENT_ID/PARENT_DIR vars
8. Main loop extension: child processing step after top-level items
9. `resume_running_children()` — startup recovery for running children

### Phase 2: Prompt Changes

10. LOOP-PROMPT.md — add "Managing Child Agents" section
11. RESEARCH-PROMPT.md — add "Child Agent Awareness" section

### Phase 3: Tests

12. Unit tests for child discovery, processing, lifecycle
13. Integration test: create child → loop processes → parent reads result

## 10. Design Decisions Summary

| Decision | Choice | Rationale |
|---|---|---|
| Nesting depth | 1 level only | Simplest to implement, clearest hierarchy |
| Child RUNS.md format | Unified with top-level | One parser, one format, zero new file conventions |
| Output context | Parent's context only | No duplication, single source of truth |
| children.md | Kept | Parent's operational dashboard, analogous to WORK.md |
| Child CONVERSATION.md | Kept | Transparency — user can see parent's management actions per child |
| Remote dispatch | No for v1 | Adds complexity, can be added later |
| Cron for children | Yes (same as top-level) | Consistent behavior, children can be recurring |
| Status after success (no schedule) | `ready` (not `done`) | Parent decides whether to re-run or mark done |
| Hierarchy metadata | Config keys (`parent`, `status`) | Same mechanism as all other RUNS.md fields |

## 11. Open Questions

1. **Should children be discoverable via a top-level registry?** Currently children are discovered by scanning all item folders. An alternative would be a `children` section in WORK.md. The current approach (scanning) is cleaner but means children aren't visible in the main work table.

2. **What if a child's `note_path` conflicts with another child?** e.g., two children both write to `../context/area-comparison.md`. The last write wins. The parent agent should coordinate this — the LOOP-PROMPT.md should instruct the parent to ensure unique note_paths per child.

3. **Should there be a limit on child agent count?** e.g., max 10 children per parent. This prevents runaway proliferation. Could be enforced by the prompt (agent self-limiting) or by the loop (hard limit).

4. **Should the loop enforce a parent-child hierarchy invariant?** e.g., reject child RUNS.md where `parent:` doesn't match the folder's parent. Currently the loop just checks for a match and skips mismatches.
