# Work-Loop

## What This Is

An automated loop that runs an AI harness (Claude or OpenCode) on work items one at a time. Each item gets a fresh context. Items can run locally or be dispatched to a remote host over SSH. The loop also supports **script items** — automated command dispatch to one or more machines with cron scheduling, multi-machine polling, and fan-in aggregation — **child agents** — parallel background research and task workers — and **vault auto-scaffolding** — automated folder initialization, template provisioning, and marker-fenced rule synchronization for any Obsidian vault.

## Directory Layout

Scripts (this repo) and work items live in separate sibling directories:

```
MyNotebook/
├── Work-Loop/              ← scripts repo (this directory)
│   ├── run-loop.py         ← execution shim
│   ├── workloop/           ← core package (core, remote, scripts, children, outline, harness, scaffold)
│   ├── test_run_loop.py
│   ├── config.json         ← harness, work_dir, budget settings
│   ├── prompts/            ← prompt templates directory
│   │   ├── BASE-PROMPT.md  ← base execution rules (reasoning budget, fast-path) prepended to all prompts
│   │   ├── LOOP-PROMPT.md  ← prompt for analyze/ready/resolved items
│   │   ├── IMPL-PROMPT.md  ← prompt for implement items
│   │   ├── RESOLVE-PROMPT.md ← prompt for resolved items
│   │   ├── UPDATE-RESEARCH-PROMPT.md ← prompt for research items + child research
│   │   ├── TASK-PROMPT.md  ← prompt for child task agents
│   │   └── LOOP-PROMPT-v1.0.md ← legacy prompt
│   ├── templates/          ← master vault templates & single sources of truth
│   │   ├── vault-AGENTS.md ← marker-fenced vault rules (Obsidian CLI & Verified Research)
│   │   ├── VERIFIED-RESEARCH-README.md ← single source of truth for 03 Verified Research
│   │   └── WORK.md         ← master dashboard outline template
│   └── .claude/ or .opencode/  ← agent config (harness-dependent)
│       └── agents/         ← subagent definitions (critic.md, code-reviewer.md, verified-research.md, research-worker.md)
└── Work-Loop-Items/        ← work items (part of the vault, not the scripts repo)
    ├── WORK.md             ← main work item table / dashboard
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
        ├── context/        ← (optional) shared context notes (child reports & research staging live here)
        │   └── research/   ← (optional) in-flight raw research extracts (raw-*.md)
        └── runs/           ← (script/research items) per-run directories
```

## Key Files

| File | Purpose |
|---|---|
| `run-loop.py` | The executable shim that initializes and runs the `WorkLoop` (supports `--init-vault <path>`) |
| `workloop/` | The core Python package (`core.py`, `harness.py`, `remote.py`, `scripts.py`, `children.py`, `outline.py`, `scaffold.py`). |
| `workloop/scaffold.py` | Vault auto-scaffolding, marker-fenced `AGENTS.md` sync, and dynamic template anchor rendering. |
| `config.json` | Harness type, work_dir, model, budget, remote settings |
| `templates/` | Single sources of truth for vault rules (`vault-AGENTS.md`), research guidelines (`VERIFIED-RESEARCH-README.md`), and dashboard schema (`WORK.md`). |
| `../Work-Loop-Items/WORK.md` | The work item table / dashboard (source of truth for status) |
| `prompts/BASE-PROMPT.md` | Base execution rules (reasoning budget, fast-path, and interactive research delegation) prepended to all prompts |
| `prompts/LOOP-PROMPT.md` | Prompt injected for `analyze`/`ready`/`resolved` items (includes Step 7 Verified Research) |
| `prompts/IMPL-PROMPT.md` | Prompt injected for `implement` items |
| `prompts/RESOLVE-PROMPT.md` | Prompt injected for `resolved` items (summarize problem/resolution) |
| `prompts/UPDATE-RESEARCH-PROMPT.md` | Prompt for `research` items + child research (unified parent/child modes) |
| `prompts/TASK-PROMPT.md` | Prompt for child task agents (scan + propose, never execute) |
| `test_run_loop.py` | Unit tests (+ optional remote integration test) |
| `tests/test_scaffold.py` | Unit tests for vault scaffolding, marker sync, and anchor resolution |
| `tests/test_e2e.py` | E2E tests (run the real harness; opt-in via `ENABLE_E2E_TESTS`) |

## WORK.md Table Schema

The active dashboard uses the modern outline format with separate sections:

```markdown
# Work Loop

## How to use
...

## Add New Item
- [ ] Add instructions here...

## Active Items
| Task / Conversation | Status | Last Updated | Log | ID |

## Done
| Task / Conversation | Last Updated | Log | ID |
```

- **ID** — folder name under `Work-Loop-Items/`; also the Jira key if it looks like one
- **Task / Conversation** — first link is the CONVERSATION link; the loop appends one `<br>`-separated link per child report.
- **Status** — controls what the loop does (`ready`, `analyze`, `implement`, `resolved`, `in-progress`, `needs-review`, `done`, `abort`).
- **Budget** — per-item override (e.g. `$5.0`); defaults to `max_budget_usd` (10.00).

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

## Vault Auto-Scaffolding & Portability

The loop automatically provisions and maintains the vault environment it is attached to:

1. **Startup Auto-Scaffolding (`workloop/scaffold.py`):**
   - Automatically ensures `00 Inbox/`, `03 Verified Research/`, `50 Raw/`, and the work items directory exist.
   - Copies missing starter files: `03 Verified Research/README.md` and `WORK.md`.
2. **Marker-Fenced `AGENTS.md` Sync:**
   - Synchronizes the managed block between `<!-- WORK-LOOP:START -->` and `<!-- WORK-LOOP:END -->` in the target vault's root `AGENTS.md`.
   - Never overwrites custom user instructions outside the markers.
3. **Explicit CLI Bootstrap:**
   - Initialize any vault on-demand: `python3 run-loop.py --init-vault "/path/to/Vault"`.

## Subagents & 2x2 Research Orchestration

Work-Loop equips the LLM harness with specialized subagents to keep the primary reasoning context clean and ensure rigor:

| Subagent | Role | Model / Permissions | Purpose |
|---|---|---|---|
| `critic` | Reviewer | Subagent (Read-only, no bash/edit) | Evaluates draft findings for unverified assertions, inaccessible links, and logical gaps before the user sees them. |
| `code-reviewer` | Reviewer | Subagent (Bash allowed for running tests, edit denied) | Evaluates code changes for correctness, edge cases, and test coverage. |
| `verified-research` | Orchestrator | Subagent (Read/write, dynamically templated) | Coordinates multi-topic deep research (Path A) or synthesizes existing conversation findings (Path B). |
| `research-worker` | Leaf Worker | Subagent (Write/read allowed, bash/edit denied) | Executes focused searches for a single subtopic, writes raw extracts directly to a staging file, and returns a 1-line confirmation. |

### Dynamic Subagent Templating

To maintain a strict **Single Source of Truth**, subagent definitions in `.opencode/agents/` and `.claude/agents/` use dynamic anchor tags referencing master templates in `templates/`:

* **`{{templates/VERIFIED-RESEARCH-README.md#1}}`** → Section 1: Core Architecture & Philosophy (Layered single-note model).
* **`{{templates/VERIFIED-RESEARCH-README.md#2}}`** → Section 2: Standard Note Template (YAML frontmatter, claims, tables).
* **`{{templates/VERIFIED-RESEARCH-README.md#3}}`** → Section 3: Verification Rules (Source hierarchy, quote mandate, wikilink provenance).

**Resolution:** When `_sync_agent_dir` copies agent definitions to the active workspace (`02-Work-Loop-Items/.opencode/agents/`) or remote dispatch stages them, Work-Loop automatically resolves these anchors on-the-fly, giving the running LLM a 100% self-contained system prompt without filesystem overhead.

### The 2x2 Research Matrix & Local Hardware Guardrails

To prevent 128k RoPE context window exhaustion and avoid KV cache memory thrashing on Apple Silicon Unified Memory (e.g. MLX / llama.cpp on Mac Studio M3 Ultra), research follows the **2x2 Matrix**:

| Mode \ Environment | **1. Automated Work-Loop** (`run-loop.py`) | **2. Interactive Session** (`opencode` TUI) |
|---|---|---|
| **Path A: Upfront (De Novo)**<br>*(Explicit request for new deep web research)* | Triggered via `LOOP-PROMPT.md` Step 7.<br>Orchestrator breaks topic into 2–4 subtopics $\rightarrow$ dispatches `research-worker` **serially** to local staging (`{ITEM_DIR}/context/research/raw-*.md`) $\rightarrow$ synthesizes standard note for `needs-review`. | Triggered by user prompt.<br>Main agent dispatches `verified-research` $\rightarrow$ worker fetches out-of-band $\rightarrow$ writes `03 Verified Research/{Topic}.md` $\rightarrow$ returns 1-line confirmation. |
| **Path B: Retrospective (Synthesis)**<br>*(Compiling an established dialogue into a note)* | Item has discussed findings across multiple iterations in `CONVERSATION.md`.<br>Agent invokes `verified-research` with conversation summary $\rightarrow$ synthesizes note using in-context quotes without re-fetching cited web pages. | User and agent explored a topic over a long interactive chat.<br>Main agent **never re-fetches web pages in the main thread**; it delegates synthesis to `verified-research` or compiles directly from in-context quotes. |

#### Architectural Guardrails:
1. **Primary Context Protection**: The main thread must never fetch raw HTML or read full multi-KB reference notes. Note creation is always delegated out-of-band.
2. **Context-Isolated Leaf Workers**: `research-worker` subagents write raw findings to disk and return *only* `Done: Raw research written to {OUTPUT_FILE}`, freeing their KV cache instantly.
3. **Serial Execution on Apple Silicon**: Subagents are dispatched one at a time to prevent concurrent slot thrashing and keep GPU memory flat (~24GB).
4. **Staging $\rightarrow$ Promotion Lifecycle**: Raw extracts remain in `{ITEM_DIR}/context/research/raw-*.md` during analysis and are promoted to `03 Verified Research/` only upon human approval.

## Loop Execution

```bash
python3 run-loop.py      # runs forever, Ctrl+C to stop
```

Each iteration:
1. Performs startup auto-scaffolding and AGENTS.md sync (on first run)
2. Moves `done` rows to the Done section
3. Resumes any running script items (polling recovery)
4. Recovers any stalled remote jobs (polls `.done` sentinel)
5. Refreshes the WORK.md child dashboard (report links + `## Needs Attention`)
6. Initializes `new` items
7. Promotes `scheduled` script and research items whose cron fires now
8. Picks up `ready`/`analyze`/`implement`/`resolved`/`research` items and processes them
9. Processes child agents (research and task) for all parent items

For **conversation items** (local):
1. Syncs agent definitions to the target workspace via `_sync_agent_dir`, resolving any `{{templates/...#anchor}}` placeholders
2. Runs configured harness (Claude or OpenCode) with prompt + variables.

For **conversation items** (remote):
1. Wipes `~/Work-Loop` on the remote
2. Rsyncs item folder + prompt files + rendered harness agent config (`.claude/` or `.opencode/`)
3. Uploads and launches a bash script via `nohup` (harness runs detached)
4. Polls `{ITEM_ID}/.done` every 5 seconds for the exit code
5. Rsyncs results back, reads concise title from remote `WORK.md`, wipes remote

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
python3 -m pytest tests/ -v
# Remote integration test runs automatically if remote is reachable
```

E2E tests (`tests/test_e2e.py`) run the real harness and are opt-in:

```bash
ENABLE_E2E_TESTS=1 pytest tests/test_e2e.py -v   # run e2e in the foreground
ENABLE_BACKGROUND_E2E=1 pytest             # dispatch e2e in background after the unit suite
```
