# Plan: Sub-Agents with Parent Agency

## 1. Goal

Enable work items to spawn and manage child research agents (sub-agents) through a propose/approve workflow. The parent agent acts as a delegated manager — it proposes structural changes to the Work-Loop, the user approves, and the agent executes.

## 2. File Structure

```
{ITEM_ID}/                          ← parent item
├── CONVERSATION.md                 ← parent conversation thread
├── WORK-CHILDREN.md               ← child registry (WORK.md analog for children)
├── background.md                   ← user-owned requirements
├── context/                        ← shared research output (parent + children write here)
│   ├── area-comparison.md
│   └── mm2h-rules.md
└── children/                       ← child agents (nesting depth: 1 only)
    ├── areas/                      ← child agent 1 (named after topic)
    │   ├── RUNS.md                 ← child config + run history; parent writes config, loop writes run rows
    │   └── runs/                   ← run history (loop writes)
    │       └── 20250726-001/
    │           └── research.md
    └── rules/                      ← child agent 2
        ├── RUNS.md
        └── runs/
            └── 20250725-003/
                └── research.md
```

### File Ownership

| File | Purpose | Who Writes | Who Reads |
|---|---|---|---|
| `CONVERSATION.md` | Main conversation thread | **Both** | Both |
| `WORK-CHILDREN.md` | Child registry (status, discovery) | **Parent agent** (create/update/delete rows) / **Loop** (status transitions) | Parent agent, loop, user |
| `background.md` | User requirements/constraints | **User only** | Parent agent |
| `context/*.md` | Shared research artifacts | **Parent + children** | Parent agent |
| `children/{name}/RUNS.md` | Child config + run history | **Parent** (config block) / **Loop** (run history rows) | Loop, parent |
| `children/{name}/runs/` | Run summaries (research.md) | **Loop** (after child runs) | Parent agent |

### Child RUNS.md Format

Unified with top-level research RUNS.md — same Config block, same `## Research Context` block, same Run History table. Two additional config keys for hierarchy:

```markdown
## Config
type: research
parent: KL-MM2H
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
- Status lives in WORK-CHILDREN.md (not in RUNS.md config)
- `note_path` — relative to child's cwd (`children/{name}/`), so `../context/` resolves to parent's `context/`
- `## Research Context` — same format as top-level; injected verbatim into agent prompt
- No `context/` folder under the child — parent's shared context is the only output target
- Run history table uses same format as top-level RUNS.md (including `Log` column for consistency)

### WORK-CHILDREN.md Format

Same concept as top-level WORK.md — a markdown table that serves as the child registry. The parent agent creates/updates it when managing children; the loop reads/writes status transitions. Column indices are 0-based:

```markdown
# Child Agents

| ID | Title | Status | Last Updated | Budget | Log |
|---|---|---|---|---|---|
| areas | [Walkability analysis](children/areas/RUNS.md) | ready | 2025-07-26 |  |  |
| rules | [MM2H property rules](children/rules/RUNS.md) | scheduled | 2025-07-25 |  |  |
| buildings | [Condo building shortlist](children/buildings/RUNS.md) | paused |  |  |  |
```

Column indices: `CH_ID=1`, `CH_TITLE=2`, `CH_STATUS=3`, `CH_LAST_UPDATED=4`, `CH_BUDGET=5`, `CH_LOG=6`

Notes:
- No `Location` column — children are always local (v1)
- `ID` = child folder name (e.g. `areas`, `rules`)
- `Title` = markdown link to child's RUNS.md for user navigation
- `Status` = same values as RUNS.md: `ready`, `scheduled`, `running`, `success`, `needs-review`, `done`, `paused`, `abort`
- `Budget` = per-child override (e.g. `$3.0`); empty means global default
- The parent agent creates this file when creating the first child
- The loop uses it for child discovery (same pattern as top-level WORK.md scanning)

## 3. Status System

### Child statuses (in WORK-CHILDREN.md Status column):

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
- `_parse_config_block()` — adds `parent` to the recognized keys dict; unrecognized keys are ignored so old RUNS.md files still parse cleanly
- `_empty_config()` — adds `parent` default alongside existing keys
- `_append_research_run()` — refactored to accept optional `runs_path: Path` parameter (defaults to top-level path)
- `_generate_run_id()` — refactored to accept optional `runs_path: Path` parameter
- `_update_runs_md_row_status()` — refactored to accept optional `runs_path: Path` parameter
- `_find_latest_runs_md_run()` — refactored to accept optional `runs_path: Path` parameter
- Top-level RUNS.md schema — adds `Log` column to research items for consistency (schema migration is a one-time append, no backward incompatibility)

**New methods:**
- All `_get_*`, `get_children`, `_update_child_status`, `process_child`, `resume_running_children`, `_validate_note_path_uniqueness`, `_get_all_item_ids`, `_update_parent_work_children`

### 4.1 New Methods

#### `_parse_child_runs_md(child_path: Path) -> dict`

Parses a child's RUNS.md using the same logic as top-level:
- Calls `_parse_config_block(text)` on the full file content
- Extracts `## Research Context` block via regex (same as top-level)
- Returns config dict with all standard keys plus `research_context`
- `parent` key comes from the Config block

#### `_get_all_item_ids() -> list[str]`

Returns all item IDs in the work directory (folder names under `work_dir`), **including those in the `## Done` section**. Unlike `get_ready_items()` and `get_scheduled_items()` which stop scanning at `## Done`, this method scans the full filesystem:

```python
def _get_all_item_ids(self) -> list[str]:
    items = []
    for entry in sorted(self.work_dir.iterdir()):
        if entry.is_dir():
            if (entry / "RUNS.md").exists() or (entry / "CONVERSATION.md").exists():
                items.append(entry.name)
    return items
```

This ensures children of completed parents continue to be discoverable — a `done` parent with scheduled children must keep those children firing.

#### `_get_child_status(work_children_path: Path, child_name: str) -> str`

Reads the Status column for `child_name` from the parent's WORK-CHILDREN.md. Defaults to `ready` if the row doesn't exist or WORK-CHILDREN.md doesn't exist.

#### `_get_parent_id(child_config: dict) -> str | None`

`child_config.get('parent')` — reads parent ID from child's RUNS.md config.

#### `get_children(parent_id: str) -> list[tuple[str, str, dict]]`

Two-phase discovery:
1. Scan WORK-CHILDREN.md for registered children (get child names and statuses)
2. For each registered child, verify `children/{name}/RUNS.md` exists and parse config
3. If `config.get('parent')` is empty or `None`, **skips** (orphan detection)
4. If `config.get('parent') != parent_id`, skips (orphan detection)
5. Returns `(child_name, status, config)` tuples

This mirrors the top-level pattern: WORK.md for discovery + RUNS.md for config.

#### `_update_child_status(parent_id: str, child_name: str, status: str) -> None`

Updates the Status column for `child_name` in the parent's WORK-CHILDREN.md. Same pattern as existing `update_col()`.

#### `process_child(parent_id: str, child_name: str) -> None`

Processes a child as a research item. Does NOT call into `process_local()` (which mutates top-level WORK.md). Instead, implements the research code path inline with child-specific state management:

- Calls `_parse_child_runs_md()` to get config
- Determines budget: per-child value from WORK-CHILDREN.md Budget column, or `self.max_budget` if empty
- Calls `_validate_note_path_uniqueness(parent_id)` — if conflict, skip child (status → `needs-review`)
- Generates run ID via `_generate_run_id(child_name, runs_path=...)`
- Calls `_update_child_status()` to set status to `running` in WORK-CHILDREN.md
- Constructs research prompt with `PARENT_ID`/`PARENT_DIR` env vars
- `ITEM_DIR` points to child's folder (`{parent_dir}/children/{child_name}/`)
- Runs harness via `self._run_harness()`
- On completion:
  - Reads `research.md` from latest run dir for summary
  - Calls `_append_research_run(child_name, run_id, summary, runs_path=...)` on child's RUNS.md
  - If success + schedule → `scheduled`
  - If success + no schedule → `done`
  - If failure → `needs-review`
  - If abort (checked via WORK-CHILDREN.md) → leave as `abort`
  - Updates Last Updated and Log columns in WORK-CHILDREN.md
- Does NOT touch top-level WORK.md

#### `_validate_note_path_uniqueness(parent_id: str) -> list[tuple[str, str]]`

Scans all registered children's RUNS.md files for duplicate `note_path`. Returns list of `(child_name, note_path)` conflicts. Called by `process_child()` before dispatch.

#### `_update_parent_work_children(parent_id: str) -> None`

Rebuilds the non-status columns of WORK-CHILDREN.md from RUNS.md data (title from `topic:` config, schedule display from `schedule:` config). Called after structural changes (create/delete child). The loop updates status in-place via `_update_child_status()` to avoid clobbering.

#### `resume_running_children() -> None`

On startup, finds all `running` children across all parent items:
- If parent is `done` or item is otherwise inactive → auto-transition to `needs-review` (orphan recovery)
- Otherwise → skip (do not re-process). The parent agent will see the stale `running` status on next iteration and can propose re-creation or re-promotion.

> **Future:** If children move to remote dispatch (with separate harness processes), `resume_running_children()` could poll for `.done` sentinels the way script items do.

### 4.2 Main Loop Changes

In `run()` method, after processing top-level ready items:

```python
# Process children after top-level items
for parent_id in self._get_all_item_ids():
    children = self.get_children(parent_id)
    if not children:
        continue
    for child_name, child_status, child_config in children:
        child_runs_path = self.work_dir / parent_id / "children" / child_name / "RUNS.md"
        if child_status == 'scheduled' and child_config.get('schedule'):
            if self._cron_should_run(child_config['schedule']):
                self._update_child_status(parent_id, child_name, 'ready')
        if child_status == 'ready':
            self.process_child(parent_id, child_name)

    # Re-scan children after processing — a parent run may have created new children
    new_children = self.get_children(parent_id)
    newly_discovered = {c[0] for c in new_children} - {c[0] for c in children}
    for child_name in newly_discovered:
        child_status = self._get_child_status(self.work_dir / parent_id / "WORK-CHILDREN.md", child_name)
        if child_status == 'ready':
            self.process_child(parent_id, child_name)
```

Key behaviors:
- `_get_all_item_ids()` includes all items (even `done` ones), because a done parent might still have active scheduled children
- **Same-iteration discovery**: After processing a parent's existing children, the loop re-scans for newly created children. If the parent's own run (processed earlier in the same iteration) created new children via the propose/approve workflow, they are discovered and processed immediately
- Children are processed after top-level items each iteration. This ensures the parent's own results are fresh before children start
- The re-scan is a single pass — it doesn't loop indefinitely. Newly created children during the re-scan pass are picked up on the next iteration

**Performance note:** This is O(parents × children_per_parent) per loop iteration. For 50+ items each with 5+ children, this adds scan overhead. Future optimization: only scan items that have `children/` directories (check existence before scanning), or maintain a lightweight index.

### 4.3 RUNS.md Path Refactoring

These existing methods are refactored to accept an optional `runs_path: Path` parameter (defaulting to the current hardcoded behavior for backward compatibility):

| Method | New Signature | Purpose |
|---|---|---|
| `_generate_run_id` | `(item_id: str, runs_path: Path \| None = None) -> str` | Generate run ID from RUNS.md history |
| `_append_research_run` | `(item_id: str, run_id: str, summary: str, runs_path: Path \| None = None) -> None` | Append run row to RUNS.md |
| `_update_runs_md_row_status` | `(item_id: str, run_id: str, status: str, runs_path: Path \| None = None) -> None` | Update run row status |
| `_find_latest_runs_md_run` | `(item_id: str, status: str \| None = None, runs_path: Path \| None = None) -> str \| None` | Find latest run by status |

When `runs_path` is `None`, each method defaults to `self.work_dir / item_id / "RUNS.md"`. For children, the caller passes the child-specific path.

### 4.4 `note_path` Resolution

For child agents, `note_path` is relative to the child's cwd (`children/{child_name}/`). The prompt includes `note_path` as-is, and the agent resolves it. For example:
- Child cwd: `{ITEM_DIR}/children/areas/`
- `note_path`: `../context/area-walkability.md`
- Resolves to: `{ITEM_DIR}/context/area-walkability.md` (parent's shared context)

### 4.5 `note_path` Uniqueness Enforcement

The loop validates that no two children under the same parent target the same `note_path`. Since the loop doesn't control child creation, uniqueness is enforced at **process time** — before dispatching a child, `process_child()` calls `_validate_note_path_uniqueness(parent_id)` which scans all siblings' RUNS.md files. If a conflict is detected, the child is skipped (status set to `needs-review`) and the parent is notified in its CONVERSATION.md on the next iteration to resolve the conflict. The parent agent's proposal workflow encourages unique paths, but the loop provides the hard enforcement.

### 4.6 Child Budget

Child budget follows this resolution order:
1. Per-child `Budget` column in WORK-CHILDREN.md (e.g. `$3.0`)
2. Falls back to `self.max_budget` (global default from config.json)

`process_child()` reads the Budget column for the child row, parses it the same way as `get_item_budget()`, and falls back to the global default if empty.

## 5. Prompt Changes

### 5.1 LOOP-PROMPT.md — "Managing Child Agents" Section

Add a new section after Step 5 (Update WORK.md). Covers:

#### 5.1.1 Discovery

The parent agent reads:
- `WORK-CHILDREN.md` — its current registry of children (status, budget, log)
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
topic: Neighborhood walkability analysis
note_path: ../context/area-walkability.md
sources:
  https://www.walkscore.com/score/Kuala-Lumpur
schedule: 0 */6 * * *

## Research Context
Evaluate walkability for top 5 KL neighborhoods.
```

**WORK-CHILDREN.md row to add:**
| areas | [Walkability analysis](children/areas/RUNS.md) | ready |  |  |  |

**Questions:** Should I create this child agent?
```

User responds with approval/denial/modification. Parent executes after approval.

#### 5.1.3 Updating Child Agents

Proposed changes to existing children:

```markdown
## Proposals

### Update child agent: `rules` — Change schedule to daily

Current: schedule: 0 9 * * *
Proposed: schedule: 0 */6 * * *

**Questions:** Should I update this child agent's schedule?
```

#### 5.1.4 Deleting Child Agents

```markdown
## Proposals

### Delete child agent: `buildings` — No longer needed

**Questions:** Should I delete this child agent?
```

#### 5.1.5 Pausing/Resuming Child Agents

Parent can directly update child status in WORK-CHILDREN.md without user approval (low-risk action):

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

#### 5.1.7 Maintaining WORK-CHILDREN.md

After any child lifecycle change (create/update/delete), the parent updates WORK-CHILDREN.md. The loop handles status transitions (running, scheduled, done, needs-review). The parent handles structural changes (adding/removing rows, updating titles and budget).

### 5.2 CHILD-RESEARCH-PROMPT.md — Separate prompt for child agents

A standalone prompt file (`CHILD-RESEARCH-PROMPT.md`) loaded by `process_child()` instead of RESEARCH-PROMPT.md. This avoids fragile "override Step X" instructions that the model may not follow correctly.

**Differences from RESEARCH-PROMPT.md:**
- **Step 1 (simplified):** No CONVERSATION.md, no background.md, no parent context directory. Agent reads only its own RUNS.md config (topic, sources, note_path, Research Context) and prior run summaries.
- **Steps 2-5 (identical):** Fetch sources, compare, write note, write research.md — same as parent prompt.
- **No Step 6:** Agent does NOT update WORK.md or WORK-CHILDREN.md. Explicitly told: "Do not attempt to modify any WORK-*.md file. Status tracking is handled automatically."

```markdown
# Work Loop Prompt — Child Research Agent

Each iteration runs a research cycle on ONE topic. The script determines which topic.

## Ground rules
- Your job is to **research and update**, not to implement or analyze broadly
- Fetch and read each source URL listed in the research config
- Compare findings against the existing note — identify new information, outdated claims, and gaps
- Write an updated version of the note (overwrite in-place)
- Write a research summary to `{ITEM_DIR}/runs/{run_id}/research.md`
- Use Obsidian wiki links `[[filename]]` for all references
- Any file you create must include a back-link to `[[{PARENT_ID}/CONVERSATION]]` near the top
- Be concise in the note — bullet points, not essays
- In the research summary, list each change with a date, description, and source URL

Use PARENT_ID, PARENT_DIR, WORK_LOOP_DIR, and ITEM_DIR passed at the end of this prompt.

## Step 1 — Load Your Config

1. Read `{ITEM_DIR}/RUNS.md` — extract topic, sources, note_path, and `## Research Context`.
2. Read the existing note at `note_path` (resolve the relative path from `{ITEM_DIR}`).
3. Read prior run summaries from `{ITEM_DIR}/runs/` (newest first) for context on what was already found.

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

Include a back-link to `[[{PARENT_ID}/CONVERSATION]]` at the top of the file if it's a new file.

That's all. Do not attempt to modify any WORK-*.md file. Status tracking is handled automatically.
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
    f"\n[PARENT_ID block if child]\n"
    f"PARENT_ID: {parent_id}\n"
    f"PARENT_DIR: {parent_dir}\n"
    f"ITEM_ID: {child_name}\n"
    f"WORK_LOOP_DIR: {self.work_dir}\n"
    f"ITEM_DIR: {item_dir}"
)
```

## 6. Parent Agent Agency Model

The propose/approve workflow is the core interaction pattern:

```
1. Parent agent identifies a need (new child, update, delete, etc.)
2. Parent writes proposal to CONVERSATION.md (with RUNS.md config and WORK-CHILDREN.md row)
3. User responds: "Oliver: Yes, create it." or "Oliver: no, do X instead"
4. Parent executes: creates child folder, RUNS.md, adds row to WORK-CHILDREN.md
5. Loop discovers and processes changes on next iteration (or same iteration if parent ran first)
```

### Agency Levels:

| Action | Requires Approval? | Where Logged |
|---|---|---|
| Create child agent | Yes | CONVERSATION.md proposal |
| Update child config (sources, note_path, schedule type) | Yes | CONVERSATION.md proposal |
| Delete child agent | Yes | CONVERSATION.md proposal |
| Pause child agent | No | WORK-CHILDREN.md (direct status update) |
| Resume child agent | No | WORK-CHILDREN.md (direct status update) |
| Mark child done | No | WORK-CHILDREN.md (direct status update) |
| Update child schedule frequency | No | WORK-CHILDREN.md (direct status update) |

Low-risk actions (pause/resume/update schedule) don't require explicit approval — the parent can update the child's status in WORK-CHILDREN.md directly. Higher-risk actions (create/delete/update config) require user approval via CONVERSATION.md.

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
1. Creates `children/areas-walkability/` directory
2. Creates `children/areas-walkability/RUNS.md` with config
3. Adds row to `WORK-CHILDREN.md`
4. (Loop picks it up on same or next iteration)

## 7. Edge Cases & Handling

| Case | Handling |
|---|---|
| Parent item deleted | Children become orphans. Loop skips them (`parent` key mismatch). Parent agent can clean up via proposal. |
| Child RUNS.md has no `parent:` config key | **Skipped by all parents.** Children must opt-in with `parent: {ITEM_ID}` to be discoverable. |
| WORK-CHILDREN.md missing | `get_children()` returns empty list. Parent agent creates it on first child creation. |
| WORK-CHILDREN.md row exists but RUNS.md missing | `get_children()` skips (RUNS.md verification step). Child is effectively dead. |
| Multiple parents writing to same `context/` file | Shouldn't happen — children only write to their own parent's `context/`. |
| Child agent fails | Status set to `needs-review` in WORK-CHILDREN.md. Parent sees this in next iteration. |
| Cron fires while child is `running` | Skipped (only promotes `scheduled` → `ready`). Child completes first. |
| User directly edits child's RUNS.md | Loop reads user's edit. Config changes take effect on next run. |
| Two children with same `note_path` | **Enforced at process time** — loop validates uniqueness before dispatching. Conflicts set child to `needs-review` in WORK-CHILDREN.md. |
| Child created while loop is running | Discovered in same-iteration re-scan (after parent's children are processed). |
| Parent has many children (50+) | Performance consideration — main loop scan is O(parents × children). Future optimization: only scan items with existing `children/` directories. |
| Orphaned child stuck in `running` | `resume_running_children()` auto-transitions to `needs-review` if parent is `done`. |

## 8. Testing Strategy

### 8.1 Unit Tests (test_run_loop.py)

| Test | What |
|---|---|
| `_parse_child_runs_md` | Parses unified format, extracts config + research_context |
| `_get_child_status` | Reads status from WORK-CHILDREN.md, defaults to `ready` if missing |
| `_get_parent_id` | Reads `parent:` from config dict |
| `_get_all_item_ids` | Returns all item folder names (including done items) |
| `get_children` (no children) | No WORK-CHILDREN.md returns [] |
| `get_children` (with children) | Returns list of (name, status, config) tuples |
| `get_children` (mixed statuses) | Returns all children regardless of status |
| `get_children` (orphan detection — wrong parent) | Skips children with wrong parent_id |
| `get_children` (orphan detection — missing parent) | Skips children with empty/None `parent:` key |
| `get_children` (done parent) | Finds children of done parents (filesystem scan) |
| `get_children` (WORK-CHILDREN.md row but no RUNS.md) | Skips child (RUNS.md verification) |
| `_update_child_status` | Correctly updates Status column in WORK-CHILDREN.md |
| `_update_child_status` (abort) | Correctly sets abort status |
| `process_child` (success + schedule) | Status transitions: ready → running → scheduled |
| `process_child` (success + no schedule) | Status transitions: ready → running → done |
| `process_child` (failure) | Status transitions: ready → running → needs-review |
| `process_child` (WORK.md NOT modified) | **Mocks harness, verifies top-level WORK.md is untouched** |
| `_update_parent_work_children` | Rebuilds WORK-CHILDREN.md non-status columns from RUNS.md |
| `resume_running_children` | Skips running children on startup (no re-processing) |
| `resume_running_children` (orphan recovery) | Auto-transitions `running` child to `needs-review` if parent is `done` |
| Child cron promotion | `scheduled` → `ready` when cron fires |
| `note_path` uniqueness validation | Detects duplicate note_paths within a parent's children |
| `process_child` (note_path conflict) | Child skipped, status set to needs-review |
| `process_child` (abort during run) | Loop kills harness, leaves status as abort |
| `process_child` (budget from WORK-CHILDREN.md) | Uses per-child budget from Budget column |
| `process_child` (budget fallback to global) | Uses `self.max_budget` when Budget column is empty |
| `_generate_run_id` with runs_path | Generates ID from child RUNS.md, not parent |
| `_append_research_run` with runs_path | Appends to child RUNS.md, not parent |
| Same-iteration child discovery | New child created by parent is discovered in re-scan pass |

### 8.2 Prompt Tests

| Test | What |
|---|---|
| RESEARCH-PROMPT.md child override | Child prompt includes PARENT_ID block that overrides Step 6 |
| RESEARCH-PROMPT.md top-level unchanged | Top-level research prompt still has Step 6 (WORK.md update) |
| LOOP-PROMPT.md child management | Prompt includes child agent management section |
| No hardcoded paths in child prompts | Prompt uses relative/variable paths |

## 9. Implementation Order

### Phase 1: Loop Infrastructure (run-loop.py)

1. **Extend `_parse_config_block()`** — add `parent` to the recognized keys in `_parse_config_block()` and `_empty_config()`
2. **Refactor RUNS.md path-dependent methods** — add optional `runs_path: Path` parameter to `_generate_run_id`, `_append_research_run`, `_update_runs_md_row_status`, `_find_latest_runs_md_run`
3. `_parse_child_runs_md()` — parse child RUNS.md from arbitrary path
4. `_get_child_status()` — read status from WORK-CHILDREN.md
5. `_get_parent_id()` — thin config read
6. `_get_all_item_ids()` — filesystem scan of all item folders (including done items)
7. `get_children()` — two-phase: WORK-CHILDREN.md for discovery, RUNS.md for config + orphan detection
8. `_update_child_status()` — update Status column in WORK-CHILDREN.md
9. `process_child()` — inline research processing path; manages WORK-CHILDREN.md status; does NOT touch top-level WORK.md
10. `_validate_note_path_uniqueness(parent_id)` — scan siblings' RUNS.md for duplicate note_paths
11. `_update_parent_work_children(parent_id)` — rebuild non-status columns from RUNS.md data
12. Main loop extension: child processing step after top-level items, with same-iteration re-scan for newly created children
13. `resume_running_children()` — startup: skip running children; auto-transition to `needs-review` if parent is `done`

### Phase 2: Prompt Changes

14. LOOP-PROMPT.md — add "Managing Child Agents" section (WORK-CHILDREN.md references)
15. Create CHILD-RESEARCH-PROMPT.md — simplified Steps 1-5 for child agents (no Step 6)

### Phase 3: Tests

16. Unit tests for child discovery, processing, lifecycle, WORK.md isolation
17. Integration test: create child → loop processes → parent reads result

## 10. Design Decisions Summary

| Decision | Choice | Rationale |
|---|---|---|
| Nesting depth | 1 level only | Simplest to implement, clearest hierarchy |
| Child RUNS.md format | Unified with top-level (Log column included) | One parser, one format, zero new file conventions |
| Status location | WORK-CHILDREN.md (not RUNS.md config) | Reuse the WORK.md pattern: registry for status, RUNS.md for config |
| Child registry file | WORK-CHILDREN.md | Same concept as WORK.md — one file for discovery + status tracking |
| Output context | Parent's context only | No duplication, single source of truth |
| Child CONVERSATION.md | Removed | Unnecessary — child research agents write to `runs/*/research.md`, not a conversation thread |
| Remote dispatch | No for v1 | Adds complexity, can be added later |
| Cron for children | Yes (same as top-level) | Consistent behavior, children can be recurring |
| Status after success (no schedule) | `done` (not `ready`) | Prevents infinite re-processing each loop iteration |
| Hierarchy metadata | `parent` config key in RUNS.md | Same mechanism as all other RUNS.md fields |
| Directory name | `children/` (not `agents/`) | Avoids confusion with harness agent terminology |
| Orphan detection | Opt-in: children without `parent:` key are invisible | Prevents noise from orphaned items |
| `note_path` conflicts | Enforced at process time | Prevents race conditions; conflicts set child to `needs-review` |
| `resume_running_children` | Skip running; orphan recovery for done parents | Partial agent state is unsafe; orphaned children need cleanup |
| Child budget | Per-child in WORK-CHILDREN.md, fallback to global | Flexibility where needed, sensible default |
| Same-iteration discovery | Re-scan after parent's children process | Parent-created children available immediately |
| Max children | Prompt-enforced limit (agent self-limiting) | Hard loop limit can be added later if needed |
| Child prompt strategy | Separate file (CHILD-RESEARCH-PROMPT.md) | Cleaner than override blocks; avoids model confusing parent/child instructions |

## 11. Open Questions

1. **Should the loop enforce a hard `max_children` limit per parent?** Currently prompt-enforced (agent self-limits). A hard limit would catch misbehaving agents but adds config complexity. **Decision: prompt-enforced for v1, loop-enforced later if needed.**

2. **Should the parent's own research runs be isolated from child runs?** If the parent item is also a research item (has `RUNS.md` with `type: research`), its runs would live in `{ITEM_ID}/runs/` while children live in `{ITEM_ID}/children/*/runs/`. This separation is clean, but the RESEARCH-PROMPT needs to clarify that the parent's `note_path` targets its own `context/` while children target the same shared `context/`. **Decision: accept current separation, document in RESEARCH-PROMPT.**

3. **Should children be promotable to top-level WORK.md items?** If a child becomes large enough or its research scope outgrows the parent, could it be "detached" — moved to WORK.md as a standalone item with a link back to the parent? **Deferred — not needed for v1.**

4. **What about concurrent children under the same parent?** If two children are both `ready` and the loop processes them sequentially, the parent sees results one at a time. If both write to `context/` concurrently (unlikely since loop is single-threaded), last write wins. **Decision: sequential processing is fine for v1.**

5. **Should WORK-CHILDREN.md support a `## Done` section?** Top-level WORK.md moves done items to a separate section. For children, the `done` status in the table may be sufficient without a separate section. **Decision: no separate section for v1 — `done` status in the main table is clear enough.**

## 12. Critical Review & Fixes Applied

This section documents the design review findings and how they were addressed in the plan.

### 12.1 Renamed `agents/` → `children/`

**Problem:** `agents/` conflicts with harness terminology (`.claude/agents/`, `.opencode/agents/` refer to subagent definitions).

**Fix:** All references changed to `children/`.

### 12.2 Replaced `children.md` with `WORK-CHILDREN.md`

**Problem:** `children.md` was a custom dashboard format, duplicating the WORK.md concept. Two writers (loop + parent agent) updating the same file risked clobbering. Status was tracked in both RUNS.md config and children.md.

**Fix:** Replaced with WORK-CHILDREN.md — the same WORK.md concept scoped to children. The parent agent creates/updates structural rows; the loop updates status columns. Status lives in one place (WORK-CHILDREN.md, not RUNS.md config). Discovery uses WORK-CHILDREN.md + RUNS.md verification (two-phase, same pattern as top-level).

### 12.3 Removed Child CONVERSATION.md

**Problem:** Child research agents don't have conversations — they fetch sources and write to `runs/*/research.md`. A CONVERSATION.md per child is unnecessary overhead.

**Fix:** Removed from file structure. Child agents write research summaries to `runs/{run_id}/research.md` only.

### 12.4 Added `abort` Status

**Problem:** The parent state machine includes `abort` but the child status table did not.

**Fix:** Added `abort` to child statuses. Loop checks abort during `process_child()` and leaves status as-is.

### 12.5 Fixed No-Schedule Infinite Loop

**Problem:** After successful run with no schedule, status goes to `ready`, causing infinite re-processing.

**Fix:** Changed to `done` after success with no schedule. Parent must explicitly re-promote to `ready`.

### 12.6 Fixed Orphan Detection (Opt-In)

**Problem:** Children without a `parent:` key could appear under every parent scan.

**Fix:** Children with empty or missing `parent:` key are skipped entirely.

### 12.7 Fixed Resume/Transition Consistency

**Problem:** The state machine showed `paused ──(parent proposes)──> ready` but the agency model said pause/resume are low-risk.

**Fix:** Both `paused → ready` and `done → ready` are direct parent actions. Only create/update/delete require approval.

### 12.8 Added `note_path` Uniqueness Enforcement

**Problem:** Two children writing to the same `note_path` was acknowledged but not prevented.

**Fix:** Added `_validate_note_path_uniqueness()` to loop infrastructure. Enforced at process time.

### 12.9 Fixed RUNS.md Schema Mismatch

**Problem:** Child RUNS.md had a `Log` column, but top-level research RUNS.md did not.

**Fix:** Top-level research RUNS.md also gets the `Log` column for consistency.

### 13.0 Fixed process_child WORK.md Mutation

**Problem:** `process_child()` was described as "processes exactly like `process_local()`" but `process_local()` mutates top-level WORK.md via `update_col()`. Children don't have WORK.md rows.

**Fix:** `process_child()` implements the research code path inline. It manages state through WORK-CHILDREN.md and child RUNS.md only. Never touches top-level WORK.md.

### 13.1 Added Child Budget Handling

**Problem:** Budget for children was not specified.

**Fix:** Per-child budget from WORK-CHILDREN.md Budget column, fallback to global `self.max_budget`.

### 13.2 Added Same-Iteration Discovery

**Problem:** A parent's run could create new children, but they wouldn't be discovered until the next loop iteration.

**Fix:** After processing a parent's existing children, the loop re-scans for newly created children. Single pass (no infinite loop). Newly created children during re-scan are picked up on next iteration.

### 13.3 Added RUNS.md Path Refactoring

**Problem:** Multiple methods (`_generate_run_id`, `_append_research_run`, etc.) hardcode `self.work_dir / item_id / "RUNS.md"`. They can't work with child paths.

**Fix:** All four methods accept optional `runs_path: Path` parameter. Default to existing behavior for backward compatibility.

### 13.4 Fixed RESEARCH-PROMPT Step 6 Conflict

**Problem:** RESEARCH-PROMPT Step 6 tells agents to update WORK.md. Child agents would try to update top-level WORK.md for themselves.

**Fix:** The loop appends a "Child Agent Mode" block to the prompt that explicitly overrides Step 6 for child agents. Top-level research items are unaffected.

### 13.5 Added Orphan Recovery in resume_running_children

**Problem:** Running children of done parents would sit in `running` status forever.

**Fix:** `resume_running_children()` auto-transitions `running` children to `needs-review` when the parent is `done`.

### 13.6 Clarified `resume_running_children()` Future Path

Added note that remote dispatch support could add `.done` sentinel polling for children, matching the script item recovery pattern.

### 13.7 Replaced RESEARCH-PROMPT Child Override with CHILD-RESEARCH-PROMPT.md

**Problem:** The original plan used an "override Step 6" block appended to RESEARCH-PROMPT.md. This approach is fragile — the model may not correctly suppress Steps 1 (read CONVERSATION.md, background.md) and Step 6 (update WORK.md) when told to "override." Additionally, Step 1 references files (CONVERSATION.md, background.md) that children don't have.

**Fix:** Created a separate CHILD-RESEARCH-PROMPT.md with only child-relevant instructions. Step 1 reads only RUNS.md config and prior run summaries. Steps 2-5 are identical to parent prompt. No Step 6 exists. The prompt explicitly tells the agent not to modify WORK-*.md files.
