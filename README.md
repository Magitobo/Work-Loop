# User's Guide

## Overview

Work-Loop is an automated harness that runs AI agents (Claude or OpenCode) on work items one at a time. Each item gets a fresh context, and items can run locally or be dispatched to remote hosts over SSH. The loop also supports **script items** — automated command dispatch to one or more machines with cron scheduling, multi-machine polling, and fan-in aggregation.

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
├── .claude/ or .opencode/    ← agent config (harness-dependent)
└── <work_dir>/               ← work items (path configured in config.json)
    ├── WORK.md               ← main work item table
    ├── .logs/                ← harness logs
    └── <item-id>/            ← one folder per item
        ├── CONVERSATION.md   ← thread between user and agent
        ├── background.md     ← (optional) internal context
        └── context/          ← (optional) additional context files
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

Three prompt files control agent behavior. They are injected automatically based on the item's status:

| File | Triggered By | Purpose |
|---|---|---|
| `LOOP-PROMPT.md` | `ready`, `analyze` | Multi-agent investigation with internal critic review |
| `IMPL-PROMPT.md` | `implement` | Code implementation with code review |
| `RESOLVE-PROMPT.md` | `resolved` | Problem/resolution summary |

Each prompt receives `ITEM_ID`, `WORK_LOOP_DIR`, and `ITEM_DIR` as variables.

## Loop Execution Order

Each iteration of the loop:

1. Moves `done` rows to the Done section
2. Resumes any running script items (polling recovery)
3. Recovers any stalled remote jobs (polls `.done` sentinel)
4. Initializes `new` items
5. Promotes `scheduled` script items whose cron fires now
6. Picks up `ready`/`analyze`/`implement`/`resolved` items and processes them
