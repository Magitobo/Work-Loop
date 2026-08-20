# User's Guide

## Overview

Work-Loop is an automated harness that runs AI agents (Claude or OpenCode) on work items one at a time. Each item gets a fresh context, and items can run locally or be dispatched to remote hosts over SSH. The loop also supports **script items** — automated command dispatch to one or more machines with cron scheduling, multi-machine polling, and fan-in aggregation — **research items** — automated web research that fetches sources, compares against existing notes, and writes updated notes with per-run summaries — **child agents** — parent items can spawn and manage sub-agents (research and task) via a propose/approve workflow for focused, parallel work — and **verified research** — de novo web research with multi-angle search, claim extraction with confidence ratings, contradiction resolution, and a human gate (available as a sub-agent invoked by the LOOP-PROMPT agent).

## Quick Start

```bash
# 1. Configure your setup
cp config-example.json config.json   # if available, or edit config.json
# 2. Start the loop
python3 run-loop.py
```

The loop runs indefinitely. Press `Ctrl+C` to stop.

## Configuration

`config.json` controls the harness, directories, and budget:

```json
{
  "work_dir": "/path/to/Work-Loop-Items",
  "harness": {
    "type": "opencode",
    "model": "anthropic/claude-sonnet-4-5",
    "max_budget_usd": 10.00
  },
  "remote": {
    "work_dir": "~/Work-Loop"
  }
}
```

| Key | Required | Description |
|---|---|---|
| `work_dir` | Yes | Absolute path to the items directory (where `WORK.md` lives) |
| `harness.type` | Yes | `"claude"` or `"opencode"` |
| `harness.model` | No | Model string for OpenCode; ignored for Claude |
| `harness.max_budget_usd` | No | Default per-item budget (default: `10.00`) |
| `remote.work_dir` | No | Remote path for SSH dispatch (default: `~/Work-Loop`) |

## Directory Layout

```
Work-Loop/                    ← scripts repo
├── run-loop.py               ← executable shim
├── workloop/                 ← core loop package
├── test_run_loop.py          ← tests
├── config.json               ← harness + directory settings
├── prompts/                  ← prompt templates directory
│   ├── BASE-PROMPT.md        ← base execution rules (reasoning budget & fast-path)
│   ├── LOOP-PROMPT.md        ← prompt for analyze/ready/resolved items
│   ├── IMPL-PROMPT.md        ← prompt for implement items
│   ├── RESOLVE-PROMPT.md     ← prompt for resolved items (summary)
│   ├── UPDATE-RESEARCH-PROMPT.md ← prompt for research items (parent + child modes)
│   └── TASK-PROMPT.md        ← prompt for child task agents
├── .opencode/                ← OpenCode agent config + sub-agent definitions
│   └── agents/               ← sub-agent definitions (verified-research.md, etc.)
└── <work_dir>/               ← work items (path configured in config.json)
    ├── WORK.md               ← main work item table
    └── <item-id>/            ← one folder per item
        ├── CONVERSATION.md   ← thread between user and agent
        ├── _logs/            ← harness logs
        ├── background.md     ← (optional) internal context
        ├── WORK-CHILDREN.md  ← (optional) child agent registry
        ├── context/          ← (optional) shared context notes (child reports live here)
        └── children/         ← (optional) child agent directories
            └── {name}/      ← one folder per child agent
                ├── RUNS.md ← child config + run history
                └── runs/  ← per-run summaries (research.md / task.md)
```

## WORK.md Table

The work item table is the source of truth. Each row has these columns:

| Column | Description |
|---|---|
| ID | Folder name under `Work-Loop-Items/`; also the Jira key if it looks like one |
| Title | Item description (first link to `CONVERSATION.md`; child report links appended after) |
| Location | `local` or `user@hostname` for remote dispatch |
| Status | Controls loop behavior (see state machine below) |
| Last Updated | Date of last activity |
| Budget | Per-item override (e.g. `$5.0`); defaults to `max_budget_usd` |
| Log | Link to the harness log file |

The loop also maintains a `## Needs Attention` bullet section near the top of `WORK.md`
(marker-fenced, omitted when empty) listing items and children needing review. It uses bullets
rather than table rows so it never interferes with table parsing.

## Conversation Items — State Machine

```
new → ready/analyze/implement/resolved → in-progress → needs-review
                 abort ←──────────────────── in-progress (kill running job)
                 abort  (set before dispatch; loop skips without starting)
                                done  (auto-moved to Done section)
```

| Status | Meaning |
|---|---|
| `new` | Loop creates folder + `CONVERSATION.md` from Title, then sets `ready` |
| `ready` / `analyze` | Triggers LOOP-PROMPT.md run (investigation mode) |
| `implement` | Triggers IMPL-PROMPT.md run; reads `work_dir:` from CONVERSATION.md |
| `resolved` | Triggers RESOLVE-PROMPT.md run; moves row to Done section on success |
| `in-progress` | Set by loop before harness starts; prevents double-dispatch |
| `needs-review` | Harness finished (or failed); human review needed |
| `abort` | Set by human to cancel: skips un-started items; kills running harness |
| `done` | Human marks complete; loop moves row to Done section |

## Child Agents

Parent items can spawn and manage child agents — sub-agents that run focused cycles and write results to the parent's shared `context/` directory. Children are managed through a **propose/approve** workflow: the parent agent proposes structural changes, the user approves, and the loop executes.

Two child types are available:
- **`type: research`** — fetches web sources, compares against a note, writes updates
- **`type: task`** — scans local files/directories, proposes actions (moves, renames), does NOT execute

### Registry: WORK-CHILDREN.md

Child agents are tracked in `WORK-CHILDREN.md` within the parent item folder. The parent agent creates and maintains this file; the loop manages status transitions.

```markdown
| ID | Title | Status | Last Updated | Budget | Log |
|---|---|---|---|---|---|
| areas | [Walkability analysis](children/areas/RUNS.md) | ready | 2025-07-26 |  |  |
| rules | [MM2H rules](children/rules/RUNS.md) | scheduled | 2025-07-25 |  |  |
```

| Column | Description |
|---|---|
| ID | Child folder name (e.g. `areas`, `rules`) |
| Title | Markdown link to child's `RUNS.md` |
| Status | Child status (see state machine below) |
| Budget | Per-child budget override (e.g. `$3.0`); empty = global default |

### Child Agent States

| Status | Meaning |
|---|---|
| `ready` | Ready to run (one-off or cron-promoted) |
| `scheduled` | Has a cron schedule; waiting for cron to fire |
| `running` | Currently being processed by the loop |
| `done` | One-off complete (parent can re-promote to `ready` to re-run) |
| `needs-review` | Latest run failed or needs user review |
| `paused` | Manually paused by parent agent |
| `abort` | User requested cancellation |

### State Transitions

```
ready ──(loop processes)──> running ──(completes)──┬── scheduled (if cron)
                                                   └── done (if no cron)
                            └──(fails)──> needs-review

scheduled ──(cron fires)──> ready
paused / done ──(parent)──> ready     ← direct, no approval needed
running ──(user abort)──> abort       ← loop kills harness
```

### Managing Children (Propose/Approve Workflow)

The parent agent manages children through two tiers of actions:

**High-risk (requires user approval):**
- Create a new child agent
- Update a child's config (sources, note_path, title, schedule type)
- Delete a child agent

The parent writes a proposal to `CONVERSATION.md` with the `RUNS.md` config to create/modify and the `WORK-CHILDREN.md` row to add. After user approval, the parent executes.

**Low-risk (direct — no approval needed):**
- Pause a child agent
- Resume a child agent
- Re-run a completed one-off child

The parent updates the child's status in `WORK-CHILDREN.md` directly and logs the action in `CONVERSATION.md`.

### Research Child Config

```markdown
## Config
type: research
parent: {ITEM_ID}
title: Neighborhood walkability analysis
note_path: ../context/area-walkability.md
sources:
  https://www.walkscore.com/score/Kuala-Lumpur
schedule: 0 */6 * * *

## Prompt
Evaluate walkability for top 5 KL neighborhoods.
```

### Task Child Config

```markdown
## Config
type: task
parent: {ITEM_ID}
title: Inbox cleanup
note_path: ../context/inbox-suggestions.md
schedule: 0 8 * * *

## Prompt
Scan the 00 Inbox folder. Suggest which folder each file should move to:
- Business → 01-Work
- Personal → 02-Personal
- Notes → 03-Notes
```

- `parent: {ITEM_ID}` — required; links the child to its parent for discovery and orphan detection
- `note_path` — relative to the parent's `children/` directory; use `../context/...` to write to the parent's shared context
- Research children write results to `runs/{run_id}/research.md`; task children to `runs/{run_id}/task.md`
- Children must have unique `note_path` values; the loop enforces this at process time

### WORK.md Dashboard (Report Links + Needs Attention)

The loop maintains two child-facing surfaces in top-level `WORK.md` each iteration (idempotent,
write-only-on-change, so idle cycles cause no churn):

- **Report links** — each parent with children gets one `<br>`-separated link per child report
  in its Title cell, after the CONVERSATION link. The link points at the child's `note_path`
  (the always-current note), so a child's report is one click away:
  `[Parent title]({parent}/CONVERSATION.md)<br>[{child title}]({parent}/context/{note}.md)`.
- **`## Needs Attention` section** — a bullet list near the top of `WORK.md` (omitted when empty)
  listing what needs review: top-level items in `needs-review`, children in `needs-review`, and
  children whose report is flagged with an attention marker. Each entry links straight to the
  report. It is a bullet list (not a table), so it never disturbs the loop's table parsing.

**Attention marker:** a child writes a single HTML comment as the first line of its `note_path`
note — `<!-- attention: yes — {one-line reason} -->` when the user's decision is needed, else
`<!-- attention: no -->`. It is invisible in Obsidian but read by the loop to drive the section.

## Script Items

Script items run arbitrary commands on remote machines instead of invoking an AI harness. They use `RUNS.md` instead of `CONVERSATION.md`.

### Config Block

Add a `## Config` section to `RUNS.md`:

```markdown
## Config
command: python3 script.py
params: --input data.csv
schedule: 0 2 * * *        # optional cron expression
location: user@host         # or use 'locations:' for multi-machine
locations:
  linux:user@host1
  linux:user@host2
heartbeat_file: output.txt  # optional: file to monitor for activity
timeout: 4                  # optional: minutes before timing out (default: 4)
aggregation_script: /path/to/aggregate.py  # optional: run after all machines complete
analysis_prompt: Summarize the results    # optional: AI prompt to analyze aggregated output
```

### Script Item States

| Status | Meaning |
|---|---|
| `scheduled` | Has a cron schedule; promoted to `ready` when cron fires |
| `ready` | Dispatched to target machine(s) |
| `running` | Dispatched and polling in progress |
| `success` | All machines completed, fan-in succeeded |
| `needs-review` | Aggregation/analysis failed or some machines timed out |

### Fan-in

After all machines complete, the loop optionally:
1. Runs an **aggregation script** (Python, receives run directory as argument)
2. Runs an **AI analysis prompt** (via the configured harness)

If either fails, the run status becomes `needs-review`.

## Research Items

Research items run an AI agent that fetches web sources, compares findings against an existing Obsidian note, and writes an updated version. They use `RUNS.md` for configuration (like script items) but the agent does the work via tool use (web fetch, file I/O) rather than dispatching shell commands.

### Config Block

Add a `## Config` section to `RUNS.md`:

```markdown
## Config
type: research
title: AI Security
note_path: [[AI Security]]
sources:
  https://arxiv.org/list/cs.CR/recent
  https://openai.com/blog
schedule: 0 6 * * 1        # optional cron expression
timeout: 10                # optional: minutes before agent times out (default: 4)

## Prompt
Focus on: model vulnerabilities, alignment failures, supply chain risks
Exclude: consumer AI apps, chatbot features
Key papers to watch: [[AI Security/Papers]]
```

| Field | Required | Description |
|---|---|---|
| `type` | Yes | Must be `research` |
| `title` | Yes | Human-readable title |
| `note_path` | Yes | Obsidian wiki link to the target note |
| `sources` | Yes | One or more URLs to fetch (indented list) |
| `schedule` | No | Cron expression; if present, status starts as `scheduled` |
| `timeout` | No | Minutes before agent times out (default: 4) |

Everything after `## Prompt` (until the next `##` header or EOF) is injected verbatim into the agent prompt as scope and guidance.

### Research Item States

| Status | Meaning |
|---|---|
| `scheduled` | Has a cron schedule; promoted to `ready` when cron fires |
| `ready` | Agent runs: fetches sources, updates note, writes summary |
| `in-progress` | Agent is running |
| `needs-review` | Agent finished; human must approve before next cycle |
| `done` | No schedule configured and agent finished successfully |

On success with a schedule, the status returns to `scheduled`. The human reviews during `needs-review` and sets back to `ready` to trigger the next cycle.

### Run History

Each research cycle appends a row to the table in `RUNS.md`:

| ID | Summary | Status | Last Updated |
|---|---|---|---|
| 20260717-001 | [Added 3 new papers on model vulnerabilities](runs/20260717-001/) | success | 2026-07-17 |

Per-run details are written to `runs/{run_id}/research.md` with changes, sources, and notes.

## Remote Dispatch

When an item's Location is set to a remote host (e.g. `user@hostname`), the loop:

1. **Wipes** `~/Work-Loop` on the remote (cleans up previous aborted runs)
2. **Rsyncs** the item folder, prompt files, and agent config (`.claude/` or `.opencode/`)
3. **Writes** a minimal stub `WORK.md` so the agent can update status
4. **Launches** a detached bash script via `nohup` (survives SSH disconnect)
5. **Polls** `{item_id}/.done` every 5 seconds for the exit code
6. **Syncs back** results, updates local `WORK.md`, then wipes the remote folder

### Prerequisites

- SSH key-based authentication must be configured on the remote host
- The remote host needs the same harness CLI installed (Claude or OpenCode)
- NVM is auto-loaded on remote hosts for harness availability

### Key Properties

- The remote folder only exists while a job is actively running — no stale state
- Prompt files and agent config are always synced fresh
- If the local loop crashes mid-job, the remote agent keeps running; the next dispatch to that host wipes and starts clean

## Failure Handling

When the harness exits non-zero, the loop classifies the failure:

| Type | Trigger | Budget Column | Status |
|---|---|---|---|
| `budget` | Log contains "budget", "cost limit", or "exceeded" | `$N - EXCEEDED` | `needs-review` |
| `unknown` | Other non-zero exit | `$N - FAILED` | `needs-review` |

A failure notice is prepended to `CONVERSATION.md`.

## Abort Handling

- **Local**: A background thread polls the status column every 3 seconds; if set to `abort`, the harness process is terminated
- **Remote**: The wait loop checks status before each poll; if `abort`, sends `kill` to the remote PID (from `.pid` file), syncs back partial results, and leaves status as `abort`

## Running Tests

```bash
python3 -m pytest test_run_loop.py -v
# Remote integration test runs automatically if remote is reachable
```

E2E tests (`tests/test_e2e.py`) run the real harness and are opt-in:

```bash
ENABLE_E2E_TESTS=1 pytest tests/test_e2e.py -v   # run e2e in the foreground
ENABLE_BACKGROUND_E2E=1 pytest             # dispatch e2e in background after the unit suite
```

Background results are written to `e2e_results.log` and reported at the top of the next test run.

## Prompt Files

Prompt files live in the `prompts/` directory. They control agent behavior and are injected automatically based on the item's status:

| File | Triggered By | Purpose |
|---|---|---|
| `prompts/LOOP-PROMPT.md` | `ready`, `analyze` | Multi-agent investigation with internal critic review + child agent management + verified-research sub-agent |
| `prompts/IMPL-PROMPT.md` | `implement` | Code implementation with code review |
| `prompts/RESOLVE-PROMPT.md` | `resolved` | Problem/resolution summary |
| `prompts/UPDATE-RESEARCH-PROMPT.md` | `research`, child research | Fetch sources, compare against note, write updated note and summary (unified for parent and child modes) |
| `prompts/TASK-PROMPT.md` | child task | Scan local files, propose actions (never executes), write note + task summary |
Each prompt receives `ITEM_ID`, `WORK_LOOP_DIR`, and `ITEM_DIR` as variables. Research items also receive `topic`, `note_path`, `sources`, `research_context`, and `BACKLINK_TARGET`. Child agents additionally receive `PARENT_ID`, `PARENT_DIR`, and `run_id`. The consolidated `UPDATE-RESEARCH-PROMPT.md` handles both parent and child modes — child mode is detected by the presence of `PARENT_ID`.

### Sub-Agents

In addition to prompt-driven agents, the loop supports **sub-agents** that the LOOP-PROMPT agent can spawn during its work:

| Sub-Agent | Purpose |
|---|---|
| `critic` | Reviews draft findings for unverified claims, inaccessible resources, and gaps |
| `code-reviewer` | Reviews code changes for correctness, edge cases, and test coverage |
| `verified-research` | Performs verified web research with multi-angle search, claim extraction, and confidence ratings (invoked on user request) |

Sub-agent definitions live in `.opencode/agents/`.

## Loop Execution Order

Each iteration of the loop:

1. Moves `done` rows to the Done section
2. Resumes any running script items (polling recovery)
3. Recovers any stalled remote jobs (polls `.done` sentinel)
4. Refreshes the WORK.md child dashboard (report links + `## Needs Attention`)
5. Initializes `new` items
6. Promotes `scheduled` script and research items whose cron fires now
7. Picks up `ready`/`analyze`/`implement`/`resolved`/`research` items and processes them
8. Processes child agents (research and task) for all parent items (including `done` parents with active scheduled children); re-scans for newly created children after processing each parent
