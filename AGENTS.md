# Work-Loop

## What This Is

An automated loop that runs an AI harness (Claude or OpenCode) on work items one at a time. Each item gets a fresh context. Items can run locally or be dispatched to a remote host over SSH. The loop also supports **script items** — automated command dispatch to one or more machines with cron scheduling, multi-machine polling, and fan-in aggregation.

## Directory Layout

Scripts (this repo) and work items live in separate sibling directories:

```
MyNotebook/
├── Work-Loop/              ← scripts repo (this directory)
│   ├── run-loop.py
│   ├── test_run_loop.py
│   ├── config.json         ← harness, work_dir, budget settings
│   ├── LOOP-PROMPT.md      ← prompt for analyze/ready/resolved items
│   ├── IMPL-PROMPT.md      ← prompt for implement items
│   ├── RESOLVE-PROMPT.md   ← prompt for resolved items
│   ├── UPDATE-RESEARCH-PROMPT.md ← prompt for research items + child research
│   ├── TASK-PROMPT.md      ← prompt for child task agents
│   ├── LOOP-PROMPT-v1.0.md ← legacy prompt
│   └── .claude/ or .opencode/  ← agent config (harness-dependent)
│       └── agents/         ← subagent definitions (critic.md, code-reviewer.md)
└── Work-Loop-Items/        ← work items (part of the vault, not the scripts repo)
    ├── WORK.md             ← main work item table
    └── <item-id>/          ← one folder per work item
        ├── CONVERSATION.md ← thread between user and agent
        ├── WORK-CHILDREN.md← (optional) child agent registry table
        ├── _logs/          ← harness logs
        ├── children/       ← (optional) one folder per child agent
        │   └── <child>/
        │       ├── RUNS.md ← child config (type, parent, note_path, …)
        │       └── runs/   ← per-run summaries (research.md / task.md)
        ├── RUNS.md         ← (script/research items) run history + config
        ├── background.md   ← (optional) internal context
        ├── context/        ← (optional) shared context notes (child reports live here)
        └── runs/           ← (script/research items) per-run directories
```

## Key Files

| File | Purpose |
|---|---|
| `run-loop.py` | The loop script — `WorkLoop` class + `main()` + harness implementations |
| `config.json` | Harness type, work_dir, model, budget, remote settings |
| `../Work-Loop-Items/WORK.md` | The work item table (source of truth for status) |
| `LOOP-PROMPT.md` | Prompt injected for `analyze`/`ready`/`resolved` items |
| `IMPL-PROMPT.md` | Prompt injected for `implement` items |
| `RESOLVE-PROMPT.md` | Prompt injected for `resolved` items (summarize problem/resolution) |
| `UPDATE-RESEARCH-PROMPT.md` | Prompt for `research` items + child research (unified parent/child modes) |
| `TASK-PROMPT.md` | Prompt for child task agents (scan + propose, never execute) |
| `test_run_loop.py` | Unit tests (+ optional remote integration test) |
| `test_e2e.py` | E2E tests (run the real harness; opt-in via `ENABLE_E2E_TESTS`) |

## WORK.md Table Schema

```
| ID | Title / Initial Prompt | Location | Status | Last Updated | Budget | Log |
```

- **ID** — folder name under `Work-Loop-Items/`; also the Jira key if it looks like one
- **Title** — first link is the CONVERSATION link; the loop appends one `<br>`-separated link per child report (see README, Child Agents). The first link is used to seed CONVERSATION.md for `new` items.
- **Location** — `local` or `user@hostname` for remote SSH dispatch; for script items: `linux:user@host` or `win:user@host`
- **Status** — controls what the loop does (see below)
- **Budget** — per-item override (e.g. `$5.0`); defaults to `MAX_BUDGET` (10.00)

The loop also maintains a `## Needs Attention` bullet section near the top of WORK.md
(marker-fenced, omitted when empty) listing items/children needing review. It is bullets, not a
table, so table parsers ignore it.

## Status State Machine

### Conversation Items (CONVERSATION.md)

```
new → ready/analyze/implement/resolved → in-progress → needs-review
                 abort ←──────────────────── in-progress (kill running job)
                 abort  (set before dispatch; loop skips without starting)
                                done  (auto-moved to Done section)
```

| Status | Meaning |
|---|---|
| `new` | Loop creates folder + `CONVERSATION.md` from Title, then sets `ready` |
| `ready` / `analyze` | Triggers LOOP-PROMPT.md run |
| `implement` | Triggers IMPL-PROMPT.md run; reads `work_dir:` from CONVERSATION.md |
| `resolved` | Triggers RESOLVE-PROMPT.md run; moves row to Done section on success |
| `in-progress` | Set by loop before harness starts; prevents double-dispatch |
| `needs-review` | Harness finished (or failed); human review needed |
| `abort` | Set by human to cancel: skips un-started items; kills running harness |
| `done` | Human marks complete; loop moves row to Done section |

### Script Items (RUNS.md)

| Status | Meaning |
|---|---|
| `scheduled` | Has a cron schedule; promoted to `ready` when cron fires |
| `ready` | Dispatched to target machine(s) |
| `running` | Dispatched and polling in progress |
| `success` | All machines completed, fan-in succeeded |
| `needs-review` | Aggregation/analysis failed or some machines timed out |

## Work Item Types

### Conversation Items

Each item lives in `{ITEM_ID}/`:
```
{ITEM_ID}/
├── CONVERSATION.md     # Thread between user and agent (newest entry first)
├── background.md       # (optional) internal context for agent
└── context/            # (optional) additional context files
```

`CONVERSATION.md` doubles as the initial prompt (seeded from the Title column if missing) and the running conversation log. The agent prepends new entries; user adds replies below.

For `implement` mode, the file must contain a `work_dir: /path/to/repo` line so the loop sets the agent's working directory correctly.

### Script Items

Script items use `RUNS.md` instead of `CONVERSATION.md`. They define a command to run on remote machines:

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

The loop dispatches the command to each machine, polls for completion (via `.done` sentinel, heartbeat file, or file count changes), then runs an optional aggregation script and/or AI analysis prompt (fan-in).

### Research Items

Research items use `RUNS.md` with `type: research` and an optional `schedule: <cron>`. They run `UPDATE-RESEARCH-PROMPT.md` to fetch web sources, update a specified `note_path`, and append run logs to `RUNS.md` and `runs/{run_id}/research.md`.

### Child Agents

Parent conversation items can delegate background work to child agents defined in `{ITEM_ID}/children/{child_name}/RUNS.md` and tracked in `{ITEM_ID}/WORK-CHILDREN.md`:
- **`type: research`** — fetches sources, updates `note_path`, writes `runs/{run_id}/research.md`
- **`type: task`** — scans local files, proposes actions (never executes), writes `runs/{run_id}/task.md`
- Children set an attention marker (`<!-- attention: yes — {reason} -->` or `<!-- attention: no -->`) on line 1 of their target note to feed into the top-level `## Needs Attention` dashboard in `WORK.md`.

## Loop Execution

```bash
python3 run-loop.py      # runs forever, Ctrl+C to stop
```

Each iteration:
1. Moves `done` rows to the Done section
2. Resumes any running script items (polling recovery)
3. Recovers any stalled remote jobs (polls `.done` sentinel)
4. Refreshes the WORK.md child dashboard (report links + `## Needs Attention`)
5. Initializes `new` items
6. Promotes `scheduled` script and research items whose cron fires now
7. Picks up `ready`/`analyze`/`implement`/`resolved`/`research` items and processes them
8. Processes child agents (research and task) for all parent items

For **conversation items** (local): runs the configured harness (Claude or OpenCode) with the prompt + `ITEM_ID`/`WORK_LOOP_DIR`/`ITEM_DIR` appended.

For **conversation items** (remote):
1. Wipes `~/Work-Loop` on the remote
2. Rsyncs item folder + prompt files + harness agent config (`.claude/` or `.opencode/`)
3. Uploads and launches a bash script via `nohup` (harness runs detached)
4. Polls `{ITEM_ID}/.done` every 5 seconds for the exit code
5. Rsyncs results back, reads the harness's concise title from remote `WORK.md`, wipes remote

For **script items** (local or remote):
1. Generates a run ID (YYYYMMDD-NNN) and appends a row to RUNS.md
2. Dispatches the command to each target machine via SSH
3. Polls each machine for completion (`.done` sentinel, heartbeat file, or file count changes)
4. On timeout, marks the machine as timed out
5. Runs optional aggregation script, then optional AI analysis prompt (fan-in)
6. Updates RUNS.md row status and WORK.md status

## Harness Configuration

`config.json` controls the harness type, model, budget, and directories:

```json
{
  "work_dir": "/absolute/path/to/Work-Loop-Items",
  "harness": {
    "type": "opencode",          // "claude" | "opencode"
    "model": "anthropic/claude-sonnet-4-5",  // for opencode; ignored for claude
    "max_budget_usd": 10.00
  },
  "remote": {
    "work_dir": "~/Work-Loop"
  }
}
```

- **Claude harness**: uses `claude --print --permission-mode auto --max-budget-usd <budget>`
- **OpenCode harness**: uses `opencode run --auto --format json --title <item_id> --dir <path>`
- Agent config directory: `.claude/` for Claude, `.opencode/` for OpenCode

### Harness-Specific Features

**Claude**:
- Post-run cost injection: uses `ccusage session -j` to read session cost and append to CONVERSATION.md header
- Debug file: writes `.debug` file alongside log

**OpenCode**:
- Post-run budget check: uses `opencode stats --project <item_id>` to verify cost didn't exceed budget
- Session cleanup: deletes completed sessions via `opencode session list/delete` to prevent accumulation

## Failure Handling

When the harness exits non-zero, `_classify_failure()` inspects the log:
- **budget** — cost limit hit; Budget column gets `$N - EXCEEDED`
- **unknown** — other failure (Budget column gets `$N - FAILED`)

All failures set status to `needs-review` and prepend an abort notice to `CONVERSATION.md`.

## Abort Handling

- **Local**: a background thread polls the status column every 3 seconds; if set to `abort`, the harness process is terminated
- **Remote**: the wait loop checks status before each poll; if `abort`, sends `kill` to the remote PID (from `.pid` file), syncs back partial results, and leaves status as `abort`

## Remote Features

- **Title readback**: after remote completion, the loop reads the remote WORK.md and updates the local Title cell if the agent wrote a concise title (markdown link format)
- **Stub WORK.md**: remote hosts receive a minimal WORK.md with just the item row
- **NVM loading**: launcher scripts source NVM before running the harness
- **Windows support**: rsync commands use `--rsync-path` for Windows hosts

## Running Tests

```bash
python3 -m pytest test_run_loop.py -v
# Remote integration test runs automatically if remote is reachable
```

E2E tests (`test_e2e.py`) run the real harness and are opt-in:

```bash
ENABLE_E2E_TESTS=1 pytest test_e2e.py -v   # run e2e in the foreground
ENABLE_BACKGROUND_E2E=1 pytest             # dispatch e2e in background after the unit suite
```
