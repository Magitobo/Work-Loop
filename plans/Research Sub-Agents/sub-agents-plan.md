π# Plan: Sub-Agents with Parent Agency
222
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
└── children/                       ← child agents (nesting depth: 1 only)
    ├── areas/                      ← child agent 1 (named after topic)
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
| `children.md` | Parent's dashboard of all children | **Parent agent** (lifecycle changes) / **Loop** (status transitions: cron promotions, run completions) | Parent agent |
| `children/{name}/RUNS.md` | Child agent config + run history | **Parent** (config) / **Loop** (run rows) | Loop, parent |
| `children/{name}/CONVERSATION.md` | Parent's management log for this child | **Parent agent** | Parent agent |
| `children/{name}/runs/` | Run summaries (research.md) | **Loop** (after child runs) | Parent agent |

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
- `note_path` — relative to child's cwd (`children/{name}/`), so `../context/` resolves to parent's `context/`
- `## Research Context` — same format as top-level; injected verbatim into agent prompt
- No `context/` folder under the child — parent's shared context is the only output target
- Run history table uses same format as top-level RUNS.md (including `Log` column for consistency)

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

Status values: `ready`, `scheduled`, `running`, `success`, `needs-review`, `done`, `paused`, `abort`

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
| `paused` | Manually paused by parent agent (low-risk; direct transition, no approval) |
| `abort` | User requested cancellation (loop kills harness; status left as `abort`) |

### Transitions:

```
ready ──(loop processes)──> running ──(completes)──>
    ├── success ──┬── scheduled (if cron)
    │             └── done (if no cron; parent re-promotes to ready to re-run)
    └── needs-review (user or parent promotes back to ready)

scheduled ──(cron fires)──> ready
paused ──(parent directly)──> ready        ← low-risk, no approval needed
done ──(parent directly)──> ready (re-run) ← low-risk, no approval needed
running ──(user sets abort)──> abort       ← loop kills harness, leaves status as abort
```

After a successful run:
- **Has schedule** → `scheduled` (cron loop will promote)
- **No schedule** → `done` (prevents infinite re-processing each loop iteration)

**Why `done` not `ready` for no-schedule children:** If a one-off child goes back to `ready`, the loop processes it every iteration until the parent marks it `done`. Since the parent processes its own items first, then children, a no-schedule child would be re-discovered immediately by the same loop iteration. Setting to `done` requires explicit parent re-promotion, preventing runaway processing.

## 4. Loop Changes

All changes are backwards-compatible — existing behavior is preserved but a few functions are extended with new keys/parameters.

**Modifying (backward-compatible):**
- `_parse_config_block()` — adds `parent` and `status` to the recognized keys dict; unrecognized keys are ignored so old RUNS.md files still parse cleanly
- `_empty_config()` — adds `parent` and `status` defaults alongside existing keys
- `_append_research_run()` — refactored to accept optional `runs_path: Path` parameter (defaults to top-level path, enabling reuse for child RUNS.md without duplicating the append logic)
- Top-level RUNS.md schema — adds `Log` column to research items for consistency (schema migration is a one-time append, no backward incompatibility)

**New methods:**
- All `_get_*`, `get_children`, `_update_child_status`, `process_child`, `resume_running_children`, `_validate_note_path_uniqueness`, `_get_all_item_ids`, `_update_parent_children_md`

### 4.1 New Methods

#### `_parse_child_runs_md(child_path: Path) -> dict`

Parses a child's RUNS.md using the same logic as top-level:
- Calls `_parse_config_block(text)` on the full file content
- Extracts `## Research Context` block via regex (same as top-level)
- Returns config dict with all standard keys plus `research_context`
- `parent` and `status` keys come from the Config block (defaults: `status=ready` if missing)

#### `_get_all_item_ids() -> list[str]`

Returns all item IDs in the work directory (folder names under `work_dir`), **including those in the `## Done` section**. Unlike `get_ready_items()` and `get_scheduled_items()` which stop scanning at `## Done`, this method scans the full filesystem:

```python
def _get_all_item_ids(self) -> list[str]:
    items = []
    for entry in sorted(self.work_dir.iterdir()):
        if entry.is_dir():
            # Check for RUNS.md or CONVERSATION.md to confirm it's a real item
            if (entry / "RUNS.md").exists() or (entry / "CONVERSATION.md").exists():
                items.append(entry.name)
    return items
```

This ensures children of completed parents continue to be discoverable — a `done` parent with scheduled children must keep those children firing.

#### `_get_child_status(child_config: dict) -> str`

`child_config.get('status', 'ready')` — reads status from config dict.

#### `_get_parent_id(child_config: dict) -> str | None`

`child_config.get('parent')` — reads parent ID from config dict.

#### `get_children(parent_id: str) -> list[tuple[str, str, dict]]`

Scans `{work_dir}/{parent_id}/children/*/RUNS.md`. For each found file:
- Calls `_parse_child_runs_md(child_path)` to get config dict
- If `config.get('parent')` is empty or `None`, **skips** (orphan detection — children must opt-in with `parent:` key; children without a parent key are invisible to all parents to prevent noise from orphaned items)
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
  - `ITEM_DIR` points to child's folder (`{ITEM_DIR}/children/{child_name}/`)
- On completion:
  - Calls `_update_child_status()` to set final status
  - Appends run row to child's RUNS.md history (reuse existing `_append_research_run()` with child path)
  - Updates `children.md`
  - If success + schedule → `scheduled`
  - If success + no schedule → `done`
  - If failure → `needs-review`

#### `_update_parent_children_md(parent_id: str) -> None`

Rebuilds `children.md` for a parent by scanning `get_children()` and writing a fresh table. Called by the loop after status transitions (cron promotions, run completions) and by the parent agent after lifecycle changes (create/delete/update). Ensures both writers stay in sync — the loop writes on status changes, the parent writes on structural changes.

#### `resume_running_children() -> None`

On startup, finds all `running` children across all parent items and **skips them** (does not re-process). Children that were interrupted mid-run would leave parent CONVERSATION.md in a partial state. The parent agent will see the stale `running` status on next iteration and can propose re-creating or re-promoting the child as needed. This is safer than attempting recovery of partial agent state.

> **Future:** If children move to remote dispatch (with separate harness processes), `resume_running_children()` could poll for `.done` sentinels the way script items do.

### 4.2 Main Loop Changes

In `run()` method, after processing top-level ready items:

```python
# Process children after top-level items
for parent_id in self._get_all_item_ids():       # includes done items
    for child_name, child_status, child_config in self.get_children(parent_id):
        child_path = self.work_dir / parent_id / "children" / child_name / "RUNS.md"
        if child_status == 'scheduled' and child_config.get('schedule'):
            if self._cron_should_run(child_config['schedule']):
                self._update_child_status(child_path, 'ready')
                # Loop owns status transitions — update children.md
                self._update_parent_children_md(parent_id)
        if child_status == 'ready':
            self.process_child(parent_id, child_name)
            # After child completes, refresh children.md with new status
            self._update_parent_children_md(parent_id)
```

The `_get_all_item_ids()` includes all items (even `done` ones), because a done parent might still have active scheduled children.

**Order:** Children are processed after top-level items each iteration. This ensures the parent's own results are fresh before children start.

**Performance note:** This is O(parents × children_per_parent) per loop iteration. For 50+ items each with 5+ children, this adds scan overhead. Future optimization: only scan items that have `children/` directories (check existence before globbing), or maintain a lightweight index.

### 4.3 `note_path` Resolution

For child agents, `note_path` is relative to the child's cwd (`children/{child_name}/`). The prompt includes `note_path` as-is, and the agent resolves it. For example:
- Child cwd: `{ITEM_DIR}/children/areas/`
- `note_path`: `../context/area-walkability.md`
- Resolves to: `{ITEM_DIR}/context/area-walkability.md` (parent's shared context)

### 4.4 `note_path` Uniqueness Enforcement

The loop validates that no two children under the same parent target the same `note_path`. Since the loop doesn't control child creation, uniqueness is enforced at **process time** — before dispatching a child, `process_child()` calls `_validate_note_path_uniqueness(parent_id)` which scans all siblings' RUNS.md files. If a conflict is detected, the child is skipped (status set to `needs-review`) and the parent is notified in its CONVERSATION.md on the next iteration to resolve the conflict. The parent agent's proposal workflow encourages unique paths, but the loop provides the hard enforcement.

## 5. Prompt Changes

### 5.1 LOOP-PROMPT.md — "Managing Child Agents" Section

Add a new section after Step 5 (Update WORK.md). Covers:

#### 5.1.1 Discovery

The parent agent reads:
- `children.md` — its current dashboard of children
- `children/*/CONVERSATION.md` — management logs for each child
- `children/*/RUNS.md` — child configs and latest run status
- `children/*/runs/*/research.md` — child run results

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
| Update child config (sources, note_path, schedule type) | Yes | CONVERSATION.md proposal |
| Delete child agent | Yes | CONVERSATION.md proposal |
| Pause child agent | No | children.md (direct) |
| Resume child agent | No | children.md (direct) |
| Mark child done | No | children.md (direct) |
| Update child schedule frequency | No | children.md (direct) |

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
1. Creates `children/areas-walkability/RUNS.md`
2. Creates `children/areas-walkability/CONVERSATION.md`
3. Updates `children.md` with new entry
4. (Loop picks it up on next iteration)

## 7. Edge Cases & Handling

| Case | Handling |
|---|---|
| Parent item deleted | Children become orphans. Loop skips them (`parent` key mismatch or folder missing). Parent agent can clean up via proposal. Orphaned children are invisible since they have no parent to claim them. |
| Child RUNS.md has no `status:` config key | Defaults to `ready` |
| Child RUNS.md has no `parent:` config key | **Skipped by all parents.** Children must opt-in with `parent: {ITEM_ID}` to be discoverable. Prevents noise from orphaned or misconfigured children. |
| Multiple parents writing to same `context/` file | Shouldn't happen — children only write to their own parent's `context/`. If two parents somehow have overlapping context, last write wins. |
| Child agent fails | Status set to `needs-review`. Parent sees this in next iteration and can propose re-run. |
| Cron fires while child is `running` | Skipped (only promotes `scheduled` → `ready`). Child completes first. |
| User directly edits child's RUNS.md | Loop reads user's edit. If `status:` changed, respects it. |
| Two children with same `note_path` | **Enforced at process time** — loop validates uniqueness before dispatching a child. Conflicts set child to `needs-review` and notify parent. |
| Child created while loop is running | Loop picks it up on next iteration. No mid-iteration discovery. |
| Parent has many children (50+) | Performance consideration — main loop scan is O(parents × children). Future optimization: only scan items with existing `children/` directories. |

## 8. Testing Strategy

### 8.1 Unit Tests (test_run_loop.py)

| Test | What |
|---|---|
| `_parse_child_runs_md` | Parses unified format, extracts config + research_context |
| `_get_child_status` | Reads `status:` from config dict, defaults to `ready` |
| `_get_parent_id` | Reads `parent:` from config dict |
| `_get_all_item_ids` | Returns all item folder names (including done items) |
| `get_children` (no children) | Empty parent folder returns [] |
| `get_children` (with children) | Returns list of (name, status, config) tuples |
| `get_children` (mixed statuses) | Returns all children regardless of status |
| `get_children` (orphan detection — wrong parent) | Skips children with wrong parent_id |
| `get_children` (orphan detection — missing parent) | Skips children with empty/None `parent:` key |
| `get_children` (done parent) | Finds children of done parents (filesystem scan, not WORK.md parse) |
| `process_child` (success + schedule) | Status transitions: ready → running → scheduled |
| `process_child` (success + no schedule) | Status transitions: ready → running → done |
| `process_child` (failure) | Status transitions: ready → running → needs-review |
| `_update_child_status` | Correctly updates `status:` line in Config block |
| `_update_child_status` (abort) | Correctly sets abort status |
| `_update_parent_children_md` | Rebuilds children.md table from get_children() results |
| `resume_running_children` | Skips running children on startup (no re-processing) |
| Child cron promotion | `scheduled` → `ready` when cron fires, children.md updated |
| `note_path` uniqueness validation | Detects duplicate note_paths within a parent's children |
| `process_child` (note_path conflict) | Child skipped, status set to needs-review |
| `process_child` (abort during run) | Loop kills harness, leaves status as abort |

### 8.2 Prompt Tests

| Test | What |
|---|---|
| RESEARCH-PROMPT.md child awareness | Prompt includes PARENT_ID section when applicable |
| LOOP-PROMPT.md child management | Prompt includes child agent management section |
| No hardcoded paths in child prompts | Prompt uses relative/variable paths |

## 9. Implementation Order

### Phase 1: Loop Infrastructure (run-loop.py)

1. **Extend `_parse_config_block()`** — add `parent` and `status` to the recognized keys in `_parse_config_block()` and `_empty_config()`, so `config.get('parent')` and `config.get('status')` work for child RUNS.md
2. `_parse_child_runs_md()` — parse unified format for child path, calls `_parse_config_block()` + extracts `research_context`
3. `_get_child_status()` — thin config read
4. `_get_parent_id()` — thin config read
5. `_get_all_item_ids()` — filesystem scan of all item folders under work_dir (including done items), returns list of item IDs
6. `get_children()` — uses `_parse_child_runs_md()`, skips children with missing/None `parent:` key (opt-in discovery)
7. `_update_child_status()` — one-line replacement in Config block
8. `_append_research_run()` — **refactor** existing method to accept optional `runs_path: Path` parameter (defaults to top-level path), enables reuse for children without duplicating append logic
9. `_update_parent_children_md(parent_id)` — rebuilds children.md table from `get_children()` results; called by both loop (status transitions) and parent agent (lifecycle changes)
10. `process_child()` — process child as research item with PARENT_ID/PARENT_DIR vars
11. **`_validate_note_path_uniqueness(parent_id)`** — scans children RUNS.md files for duplicate note_paths, returns conflicts
12. Main loop extension: child processing step after top-level items, calls `_update_parent_children_md()` after cron promotions and after `process_child()` completions
13. `resume_running_children()` — startup: skips running children (no re-processing) to avoid partial state issues

### Phase 2: Prompt Changes

14. LOOP-PROMPT.md — add "Managing Child Agents" section
15. RESEARCH-PROMPT.md — add "Child Agent Awareness" section

### Phase 3: Tests

16. Unit tests for child discovery, processing, lifecycle
17. Integration test: create child → loop processes → parent reads result

## 10. Design Decisions Summary

| Decision | Choice | Rationale |
|---|---|---|
| Nesting depth | 1 level only | Simplest to implement, clearest hierarchy |
| Child RUNS.md format | Unified with top-level (Log column included) | One parser, one format, zero new file conventions. Top-level research RUNS.md also gets Log column for consistency. |
| Output context | Parent's context only | No duplication, single source of truth |
| children.md | Kept | Parent's operational dashboard, analogous to WORK.md |
| Child CONVERSATION.md | Kept | Transparency — user can see parent's management actions per child |
| Remote dispatch | No for v1 | Adds complexity, can be added later |
| Cron for children | Yes (same as top-level) | Consistent behavior, children can be recurring |
| Status after success (no schedule) | `done` (not `ready`) | Prevents infinite re-processing each loop iteration. Parent explicitly re-promotes. |
| Hierarchy metadata | Config keys (`parent`, `status`) | Same mechanism as all other RUNS.md fields |
| Directory name | `children/` (not `agents/`) | Avoids confusion with harness agent terminology (`.claude/agents/`, `.opencode/agents/`) |
| Orphan detection | Opt-in: children without `parent:` key are invisible | Prevents noise from orphaned items appearing under every parent scan |
| `note_path` conflicts | Enforced at process time — unique per parent, validated before dispatch | Prevents race conditions when two children write to same file in same iteration; conflicts set child to `needs-review` |
| `resume_running_children` | Skips running children at startup | Partial agent state is unsafe to recover; parent proposes re-run on next iteration |
| Max children | Prompt-enforced limit (agent self-limiting) | Hard loop limit can be added later if needed |

## 11. Open Questions

1. **Should children be discoverable via a top-level registry?** Currently children are discovered by scanning all item folders. An alternative would be a `children` section in WORK.md. The current approach (scanning) is cleaner but means children aren't visible in the main work table. **Decision: scanning for v1.**

2. **Should the loop enforce a hard `max_children` limit per parent?** Currently prompt-enforced (agent self-limits). A hard limit would catch misbehaving agents but adds config complexity. **Decision: prompt-enforced for v1, loop-enforced later if needed.**

3. **Should the parent's own research runs be isolated from child runs?** If the parent item is also a research item (has `RUNS.md` with `type: research`), its runs would live in `{ITEM_ID}/runs/` while children live in `{ITEM_ID}/children/*/runs/`. This separation is clean, but the RESEARCH-PROMPT needs to clarify that the parent's `note_path` targets its own `context/` while children target the same shared `context/`. **Decision: accept current separation, document in RESEARCH-PROMPT.**

4. **Should children be promotable to top-level WORK.md items?** If a child becomes large enough or its research scope outgrows the parent, could it be "detached" — moved to WORK.md as a standalone item with a link back to the parent? **Deferred — not needed for v1.**

5. **What about concurrent children under the same parent?** If two children are both `ready` and the loop processes them sequentially, the parent sees results one at a time. If both write to `context/` concurrently (unlikely since loop is single-threaded), last write wins. **Decision: sequential processing is fine for v1.**

## 12. Critical Review & Fixes Applied

This section documents the design review findings and how they were addressed in the plan.

### 12.1 Renamed `agents/` → `children/`

**Problem:** `agents/` conflicts with harness terminology (`.claude/agents/`, `.opencode/agents/` refer to subagent definitions). A developer reading `{ITEM_ID}/agents/areas/RUNS.md` would confuse child research agents with harness subagents.

**Fix:** All references changed to `children/`. Child agent names are topic-based (e.g., `children/areas/`, `children/rules/`) rather than agent-type-based.

### 12.2 Added `abort` Status

**Problem:** The parent state machine includes `abort` but the child status table did not. If a user sets a child's status to `abort`, the loop had no way to handle it.

**Fix:** Added `abort` to child statuses. Loop checks `abort` during `process_child()` and leaves status as-is (same pattern as parent items).

### 12.3 Fixed No-Schedule Infinite Loop

**Problem:** After successful run with no schedule, status goes to `ready`. Since the loop processes children in the same iteration after the parent, a no-schedule child would be re-discovered and re-processed every iteration indefinitely.

**Fix:** Changed to `done` after success with no schedule. Parent must explicitly re-promote to `ready` to re-run. This matches the safety model of top-level research items. Propagated to Section 4.2 (`process_child` completion logic) and Section 3 (state machine).

### 12.4 Fixed Orphan Detection (Opt-In)

**Problem:** Children without a `parent:` key were included in every parent's scan (since `None != parent_id` was not the check — the original plan said `config.get('parent') != parent_id` which would match `None == None` only if parent_id was None). This meant orphaned children would appear under every parent.

**Fix:** Children with empty or missing `parent:` key are **skipped entirely** (opt-in discovery). A child must explicitly declare its parent to be discoverable.

### 12.5 Fixed Resume Semantics

**Problem:** `resume_running_children()` was described as "resumes polling" but for in-process children (conversation/research items), there's no polling mechanism. A child interrupted mid-run leaves the parent CONVERSATION.md in a partial state.

**Fix:** `resume_running_children()` now **skips** running children at startup. The parent sees the stale status and can propose re-creation/re-promotion. Remote dispatch support (future) could add polling recovery.

### 12.6 Fixed Resume/Transition Consistency

**Problem:** The state machine showed `paused ──(parent proposes)──> ready` but the agency model said pause/resume are low-risk (no approval needed). Contradiction.

**Fix:** Both `paused → ready` and `done → ready` are now direct parent actions (no proposal). Only create/update/delete require approval.

### 12.7 Added `note_path` Uniqueness Enforcement

**Problem:** Two children writing to the same `note_path` (last write wins) was acknowledged but not prevented. If the loop processes children sequentially in the same iteration, both could write to the same file.

**Fix:** Added `_validate_note_path_uniqueness()` to loop infrastructure. Enforced at process time — before dispatching a child, the loop scans all siblings' RUNS.md files for conflicts. Conflicting children are skipped (status → `needs-review`) and the parent agent is notified to resolve the conflict on the next iteration.

### 12.8 Fixed RUNS.md Schema Mismatch

**Problem:** Child RUNS.md had a `Log` column in the Run History table, but top-level research RUNS.md (per `research-agent.md`) does not. The plan claimed "Unified with top-level" but the schemas didn't match.

**Fix:** Child RUNS.md `Log` column retained. Top-level research RUNS.md also gets the `Log` column for consistency. One format, one parser.

### 12.9 Clarified `resume_running_children()` Future Path

Added note that remote dispatch support could add `.done` sentinel polling for children, matching the script item recovery pattern. This is deferred to when children move to remote dispatch.
