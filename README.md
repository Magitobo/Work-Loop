# User's Guide

## Overview

Work-Loop is an automated harness that runs AI agents (Claude or OpenCode) on work items one at a time. Each item gets a fresh context, and items can run locally or be dispatched to remote hosts over SSH. The loop also supports **script items** — automated command dispatch to one or more machines with cron scheduling, multi-machine polling, and fan-in aggregation — **research items** — automated web research that fetches sources, compares against existing notes, and writes updated notes with per-run summaries — **child research agents** — parent items can spawn and manage sub-agents via a propose/approve workflow for focused, parallel research — and **verified research** — de novo web research with multi-angle search, claim extraction with confidence ratings, contradiction resolution, and a human gate (available as a loop-dispatched item or as a sub-agent invoked by the LOOP-PROMPT agent).

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
├── run-loop.py               ← the loop script
├── config.json               ← harness + directory settings
├── LOOP-PROMPT.md            ← prompt for analyze/ready/resolved items
├── IMPL-PROMPT.md            ← prompt for implement items
├── RESOLVE-PROMPT.md         ← prompt for resolved items (summary)
├── UPDATE-RESEARCH-PROMPT.md ← prompt for research items (parent + child modes)
├── VERIFIED-RESEARCH-PROMPT.md ← prompt for de novo verified research
├── .opencode/                ← OpenCode agent config + sub-agent definitions
│   └── agents/               ← sub-agent definitions (verified-research.md, etc.)
└── <work_dir>/               ← work items (path configured in config.json)
    ├── WORK.md               ← main work item table
    └── <item-id>/            ← one folder per item
        ├── CONVERSATION.md   ← thread between user and agent
        ├── _logs/            ← harness logs
        ├── background.md     ← (optional) internal context
        ├── WORK-CHILDREN.md  ← (optional) child agent registry
        ├── context/          ← (optional) shared research output
        └── children/         ← (optional) child agent directories
            └── {name}/      ← one folder per child agent
                ├── RUNS.md ← child config + run history
                └── runs/  ← per-run research summaries
```

## WORK.md Table

The work item table is the source of truth. Each row has these columns:

| Column | Description |
|---|---|
| ID | Folder name under `Work-Loop-Items/`; also the Jira key if it looks like one |
| Title | Item description (markdown link to `CONVERSATION.md` recommended) |
| Location | `local` or `user@hostname` for remote dispatch |
| Status | Controls loop behavior (see state machine below) |
| Last Updated | Date of last activity |
| Budget | Per-item override (e.g. `$5.0`); defaults to `max_budget_usd` |
| Log | Link to the harness log file |

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

## Child Research Agents

Parent items can spawn and manage child research agents — sub-agents that run focused research cycles and write results to the parent's shared `context/` directory. Children are managed through a **propose/approve** workflow: the parent agent proposes structural changes, the user approves, and the loop executes.

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
| `success` | Latest run completed successfully |
| `done` | One-off complete (parent can re-promote to `ready` to re-run) |
| `needs-review` | Latest run failed or needs user review |
| `paused` | Manually paused by parent agent |
| `abort` | User requested cancellation |

### State Transitions

```
ready ──(loop processes)──> running ──(completes)──>
    ├── success ──┬── scheduled (if cron)
    │             └── done (if no cron)
    └── needs-review

scheduled ──(cron fires)──> ready
paused / done ──(parent)──> ready     ← direct, no approval needed
running ──(user abort)──> abort       ← loop kills harness
```

### Managing Children (Propose/Approve Workflow)

The parent agent manages children through two tiers of actions:

**High-risk (requires user approval):**
- Create a new child agent
- Update a child's config (sources, note_path, topic, schedule type)
- Delete a child agent

The parent writes a proposal to `CONVERSATION.md` with the `RUNS.md` config to create/modify and the `WORK-CHILDREN.md` row to add. After user approval, the parent executes.

**Low-risk (direct — no approval needed):**
- Pause a child agent
- Resume a child agent
- Re-run a completed one-off child

The parent updates the child's status in `WORK-CHILDREN.md` directly and logs the action in `CONVERSATION.md`.

### Child Run Config

Child agents use `RUNS.md` (same format as top-level research items) with an additional `parent:` key:

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

- `parent: {ITEM_ID}` — required; links the child to its parent for discovery and orphan detection
- `note_path` — relative to the child's `children/{name}/` directory; typically `../context/...` to write to the parent's shared context
- Children write results to `runs/{run_id}/research.md`
- Children must have unique `note_path` values; the loop enforces this at process time

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
topic: AI Security
note_path: [[AI Security]]
sources:
  https://arxiv.org/list/cs.CR/recent
  https://openai.com/blog
schedule: 0 6 * * 1        # optional cron expression
timeout: 10                # optional: minutes before agent times out (default: 4)

## Research Context
Focus on: model vulnerabilities, alignment failures, supply chain risks
Exclude: consumer AI apps, chatbot features
Key papers to watch: [[AI Security/Papers]]
```

| Field | Required | Description |
|---|---|---|
| `type` | Yes | Must be `research` |
| `topic` | Yes | Human-readable topic name |
| `note_path` | Yes | Obsidian wiki link to the target note |
| `sources` | Yes | One or more URLs to fetch (indented list) |
| `schedule` | No | Cron expression; if present, status starts as `scheduled` |
| `timeout` | No | Minutes before agent times out (default: 4) |

Everything after `## Research Context` (until the next `##` header or EOF) is injected verbatim into the agent prompt as scope and guidance.

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

## Prompt Files

Five prompt files control agent behavior. They are injected automatically based on the item's status:

| File | Triggered By | Purpose |
|---|---|---|
| `LOOP-PROMPT.md` | `ready`, `analyze` | Multi-agent investigation with internal critic review + child agent management + verified-research sub-agent |
| `IMPL-PROMPT.md` | `implement` | Code implementation with code review |
| `RESOLVE-PROMPT.md` | `resolved` | Problem/resolution summary |
| `UPDATE-RESEARCH-PROMPT.md` | `research`, child research | Fetch sources, compare against note, write updated note and summary (unified for parent and child modes) |
| `VERIFIED-RESEARCH-PROMPT.md` | sub-agent (via LOOP-PROMPT Step 7) | De novo web research with multi-angle search, claim verification, and human gate |

Each prompt receives `ITEM_ID`, `WORK_LOOP_DIR`, and `ITEM_DIR` as variables. Research items also receive `topic`, `note_path`, `sources`, `research_context`, and `BACKLINK_TARGET`. Child research agents additionally receive `PARENT_ID`, `PARENT_DIR`, and `run_id`. The consolidated `UPDATE-RESEARCH-PROMPT.md` handles both parent and child modes — child mode is detected by the presence of `PARENT_ID`.

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
4. Initializes `new` items
5. Promotes `scheduled` script and research items whose cron fires now
6. Picks up `ready`/`analyze`/`implement`/`resolved`/`research` items and processes them
7. Processes child research agents for all parent items (including `done` parents with active scheduled children); re-scans for newly created children after processing each parent
