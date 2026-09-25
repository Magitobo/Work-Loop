# User's Guide

## Overview

Work-Loop watches a Markdown dashboard (`WORK.md`) in your Obsidian vault and runs an AI agent (Claude or OpenCode) whenever an item asks for work. Each run gets a fresh context and writes its results back into the vault. Runs happen locally or on a remote host over SSH.

| You want to… | Use a… | Configured in |
|---|---|---|
| Work through a problem with an agent, and optionally have it write code | **Thread** | `CONVERSATION.md` |
| Keep a note current from a fixed list of web sources | **Routine: track sources** | `RUNS.md` with `type: research` |
| Periodically scan local folders and get suggested actions | **Routine: scan files** (attached only) | `RUNS.md` with `type: task` |
| Run a shell command on one or more machines, with optional AI summary | **Routine: run command** | `RUNS.md` with `command:` |
| Get a one-off, fully sourced answer saved as a vetted note | **Verified research** (ask inside a thread) | output in `03 Verified Research/` |

A routine is either **standalone** (its own row in `WORK.md`) or **attached** to a thread. The code calls attached routines *child agents*.

**New here? Start with the [Tutorial](docs/TUTORIAL.md).** It walks through each of these with examples. This guide is the reference.

## Quick Start

```bash
# 1. Configure your setup
cp config-example.json config.json   # then edit work_dir and harness
# 2. Scaffold the vault (optional; the loop also does this on startup)
python3 run-loop.py --init-vault "/path/to/Vault"
# 3. Start the loop
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
├── tests/                    ← tests
├── docs/TUTORIAL.md          ← step-by-step introduction
├── config.json               ← harness + directory settings
├── prompts/                  ← prompt templates (see Prompt Files)
├── templates/                ← vault scaffolding templates (AGENTS.md, WORK.md, Verified Research README)
├── .opencode/ / .claude/     ← agent config + sub-agent definitions
└── <work_dir>/               ← work items (path configured in config.json)
    ├── WORK.md               ← the dashboard
    └── <item-id>/            ← one folder per thread or standalone routine
        ├── CONVERSATION.md   ← thread between you and the agent
        ├── RUNS.md           ← (standalone routines) config + run history
        ├── runs/             ← (standalone routines) per-run output
        ├── _logs/            ← harness logs
        ├── background.md     ← (optional) internal context
        ├── context/          ← (optional) shared notes: attached-routine reports, research staging
        │   └── research/     ← (optional) in-flight raw research extracts (raw-*.md)
        ├── WORK-CHILDREN.md  ← (optional) list of attached routines
        └── children/         ← (optional) one folder per attached routine
            └── {name}/
                ├── RUNS.md   ← config + run history
                └── runs/     ← per-run summaries (research.md / task.md)
```

## The Dashboard: WORK.md

`WORK.md` is the source of truth for status. The scaffolded template uses the outline format:

```markdown
## Add New Item
- [ ] Describe what you want and tick the box

## Active Items
| Task / Conversation | Status | Last Updated | Log | ID |

## Done
| Task / Conversation | Last Updated | Log | ID |
```

| Section / column | Description |
|---|---|
| **Add New Item** | Tick a bullet to start a new thread. The ID is the first four words, slugified; use `- [x] **MY-ID** text` to choose it |
| Task / Conversation | Link to `CONVERSATION.md` (or `RUNS.md`). The loop appends one `<br>`-separated report link per attached routine |
| Status | Controls what the loop does (see the state tables below) |
| Last Updated / Log | Maintained by the loop |
| ID | Folder name under `work_dir`; also the Jira key if it looks like one |

**Location and budget.** A row runs locally with `max_budget_usd` unless its Task / Conversation cell says otherwise. To set a remote host or a per-item budget, add `location:` and/or `budget:` after the link:

```markdown
| [Title](ITEM-ID/CONVERSATION.md) · location: user@host · budget: $5 | ready | … | … | ITEM-ID |
```

Both tokens are optional and are dropped when the row moves to Done. If a run fails, the loop records it in the same cell as `budget: $N - EXCEEDED` or `budget: $N - FAILED`. Bullet rows in Active Items accept the same tokens:

```markdown
- [ ] [Title](ITEM-ID/CONVERSATION.md) · status: ready · location: user@host · budget: $5
```

The legacy single-table format (`| ID | Title | Location | Status | Last Updated | Budget | Log |`, with `new` as the status for new rows) is still supported.

**Needs Attention.** The loop maintains a marker-fenced `## Needs Attention` bullet list near the top. It is omitted when empty and lists threads in `needs-review`, attached routines in `needs-review`, and attached routines whose report is flagged with an attention marker. It uses bullets, not a table, so it never interferes with table parsing.

## Threads

A thread is a conversation between you and the agent in `<ID>/CONVERSATION.md`. It is seeded from your request, and the agent adds each reply at the top (newest first). Each thread starts with an **Action Center** callout whose checkboxes set the status for you: *Continue Analyze* (`ready`), *Run Implement* (`implement`), *Mark Resolved* (`resolved`) and *Abort* (`abort`).

### Thread States

```
new → ready/analyze/implement/resolved → in-progress → needs-review
                 abort ←──────────────────── in-progress (kill running job)
                 abort  (set before dispatch; loop skips without starting)
                                done  (auto-moved to Done section)
```

| Status | Meaning |
|---|---|
| `new` | (Legacy table) Loop creates folder + `CONVERSATION.md` from Title, then sets `ready` |
| `ready` / `analyze` | Analysis round: `LOOP-PROMPT.md` (investigate, internal critic review, ask questions) |
| `implement` | Implementation round: `IMPL-PROMPT.md`; runs in the `work_dir:` given in CONVERSATION.md |
| `resolved` | `RESOLVE-PROMPT.md` writes a Problem/Resolution summary; row moves to Done on success |
| `in-progress` | Set by loop before harness starts; prevents double-dispatch |
| `needs-review` | Harness finished (or failed); your turn |
| `blocked` | Agent could not proceed; reason is in the thread |
| `abort` | Set by you to cancel: skips un-started items; kills running harness |
| `done` | You mark complete; loop moves row to Done section |

## Routines

A routine is a repeatable job configured by a `## Config` block in `RUNS.md`. Everything after `## Prompt` (until the next `##` header or EOF) is passed to the agent verbatim as scope and guidance. The optional `schedule:` field takes a cron expression.

| Kind | Config | Prompt | Standalone | Attached |
|---|---|---|---|---|
| Track sources | `type: research` | `UPDATE-RESEARCH-PROMPT.md` | yes | yes |
| Scan files | `type: task` | `TASK-PROMPT.md` | — | yes |
| Run command | `command:` | (none; optional `analysis_prompt:`) | yes | — |

### Attached Routines (Child Agents)

A thread's agent can set up routines that run in the background and write results into the thread's `context/` directory. It uses a **propose/approve** workflow: the agent proposes a change, you approve it in the thread, and the agent makes it.

**High-risk (needs your approval):** create, update (sources, note_path, title, schedule type) or delete a routine. The agent writes a proposal to `CONVERSATION.md` containing the `RUNS.md` config and the `WORK-CHILDREN.md` row.

**Low-risk (the agent does these directly and records them in the thread):** pause, resume, or re-run a finished one-off routine.

#### Registry: WORK-CHILDREN.md

```markdown
| ID | Title | Status | Last Updated | Budget | Log |
|---|---|---|---|---|---|
| areas | [Walkability analysis](children/areas/RUNS.md) | ready | 2025-07-26 |  |  |
| rules | [MM2H rules](children/rules/RUNS.md) | scheduled | 2025-07-25 |  |  |
```

| Column | Description |
|---|---|
| ID | Folder name under `children/` |
| Title | Markdown link to the routine's `RUNS.md` |
| Status | See states below |
| Budget | Per-routine budget override (e.g. `$3.0`); empty = global default |

#### Attached Routine States

| Status | Meaning |
|---|---|
| `ready` | Ready to run (one-off or cron-promoted) |
| `scheduled` | Has a cron schedule; waiting for cron to fire |
| `running` | Currently being processed by the loop |
| `done` | One-off complete (set to `ready` to re-run) |
| `needs-review` | Latest run failed or needs your review |
| `paused` | Paused by the thread's agent |
| `abort` | You requested cancellation |

```
ready ──(loop processes)──> running ──(completes)──┬── scheduled (if cron)
                                                   └── done (if no cron)
                            └──(fails)──> needs-review

scheduled ──(cron fires)──> ready
paused / done ──(agent)──> ready     ← direct, no approval needed
running ──(user abort)──> abort      ← loop kills harness
```

#### Attached Track-Sources Config

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

#### Attached Scan-Files Config

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

- `parent: {ITEM_ID}` is required. It links the routine to its thread and is used for orphan detection.
- `note_path` is the living note the routine keeps current. It is relative to the thread's `children/` directory, so use `../context/...` to write into the thread's shared context. Each attached routine needs its own `note_path`, and the loop checks this before each run.
- Track-sources runs write `runs/{run_id}/research.md`; scan-files runs write `runs/{run_id}/task.md`.
- Scan-files routines only propose actions, unless the `## Prompt` explicitly authorizes executing some of them.

#### Report Links and the Attention Marker

The loop keeps two things in `WORK.md` up to date on every pass. Each pass is idempotent and only writes when something changed.

- **Report links:** each thread with attached routines gets one `<br>`-separated link per routine in its Title cell, after the CONVERSATION link, pointing at the routine's `note_path`:
  `[Thread title]({parent}/CONVERSATION.md)<br>[{routine title}]({parent}/context/{note}.md)`.
- **Attention marker:** a routine writes an HTML comment as the first line of its note: `<!-- attention: yes — {one-line reason} -->` when your decision is needed, else `<!-- attention: no -->`. Obsidian doesn't display it, but the loop reads it to fill `## Needs Attention`.

### Standalone Track-Sources Routine

Create `<ID>/RUNS.md` and add an Active Items row with status `research`. The agent fetches the sources, compares them with the note, writes the updated note, and records a per-run summary.

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

| Status | Meaning |
|---|---|
| `research` | Run one track-sources cycle now |
| `scheduled` | Has a cron schedule; promoted to `ready` when cron fires (see known issue below) |
| `in-progress` | Agent is running |
| `needs-review` | Run failed; your review needed |
| `done` | No schedule configured and the run succeeded |

On success, the status becomes `scheduled` if the config has a schedule, otherwise `done`. Each run appends a row to the run history in `RUNS.md`, with details in `runs/{run_id}/research.md`:

| ID | Summary | Status | Last Updated |
|---|---|---|---|
| 20260717-001 | [Added 3 new papers on model vulnerabilities](runs/20260717-001/) | success | 2026-07-17 |

> **Known issue:** cron promotion (and first-time initialization) sets the status to `ready`, which currently runs `LOOP-PROMPT.md` instead of `UPDATE-RESEARCH-PROMPT.md`. For scheduled source tracking, use an attached routine, or trigger standalone runs by hand with `research`.

### Run-Command Routine (Script Item)

Runs arbitrary commands on remote machines. There is no AI step unless you configure `analysis_prompt:`.

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

| Status | Meaning |
|---|---|
| `scheduled` | Has a cron schedule; promoted to `ready` when cron fires |
| `ready` | Dispatched to target machine(s) |
| `running` | Dispatched and polling in progress |
| `success` | All machines completed, fan-in succeeded (returns to `scheduled` if a schedule is set) |
| `needs-review` | Aggregation/analysis failed or some machines timed out |

**Fan-in:** after all machines complete, the loop optionally runs the **aggregation script** (Python, receives the run directory as argument), then the **AI analysis prompt** via the configured harness. If either fails, the run status becomes `needs-review`.

## Verified Research

Verified research is an action you ask for inside a thread, not an item type. Ask in your reply, e.g. *"Do verified research on X and create a note in 03 Verified Research/"*, or *"Compile what we've found into a verified research note"*, then tick **Continue Analyze**.

- **New research:** the agent splits the question into 2–4 subtopics and researches each one. Raw extracts are staged in `{ITEM_DIR}/context/research/raw-*.md`. It then writes one structured note (claims with confidence ratings, quotes, sources) and sets `needs-review` so you can check it.
- **Compile from the thread:** builds the note from quotes and URLs already in `CONVERSATION.md`, without fetching the web again.

Notes follow the rules in `03 Verified Research/README.md` (scaffolded from `templates/VERIFIED-RESEARCH-README.md`). Verified research runs only when you ask for it. For interactive sessions in the vault, the scaffold also installs two skills from `templates/skills/`: `verified-research` (new research) and `synthesize-research` (saves the chat to `50 Raw/`, then compiles a note from it). See [Under the Hood](#under-the-hood) for how it is orchestrated.

## Remote Dispatch

When an item's location is a remote host (e.g. `user@hostname`), the loop:

1. **Wipes** `~/Work-Loop` on the remote (cleans up previous aborted runs)
2. **Rsyncs** the item folder, prompt files, and agent config (`.claude/` or `.opencode/`)
3. **Writes** a minimal stub `WORK.md` so the agent can update status
4. **Launches** a detached bash script via `nohup` (survives SSH disconnect)
5. **Polls** `{item_id}/.done` every 5 seconds for the exit code
6. **Syncs back** results, updates local `WORK.md`, then wipes the remote folder

**Prerequisites:** SSH key-based authentication; the same harness CLI (Claude or OpenCode) installed on the remote. NVM is auto-loaded on remote hosts.

**Key properties:**
- The remote folder only exists while a job is actively running, so no stale state is left behind
- Prompt files and agent config are always synced fresh
- If the local loop crashes mid-job, the remote agent keeps running; the next dispatch to that host wipes and starts clean

## Failure Handling

When the harness exits non-zero, the loop classifies the failure:

| Type | Trigger | Budget | Status |
|---|---|---|---|
| `budget` | Log contains "budget", "cost limit", or "exceeded" | `$N - EXCEEDED` | `needs-review` |
| `unknown` | Other non-zero exit | `$N - FAILED` | `needs-review` |

A failure notice is prepended to `CONVERSATION.md`.

## Abort Handling

- **Local**: A background thread polls the status every 3 seconds; if set to `abort`, the harness process is terminated
- **Remote**: The wait loop checks status before each poll; if `abort`, sends `kill` to the remote PID (from `.pid` file), syncs back partial results, and leaves status as `abort`

## Reference

### Prompt Files

Prompt files live in `prompts/` and are chosen based on the item's status or type. `BASE-PROMPT.md` is prepended to all of them.

| File | Used for | Purpose |
|---|---|---|
| `LOOP-PROMPT.md` | thread: `ready`, `analyze` | Investigation with internal critic review, attached-routine management, verified research on request |
| `IMPL-PROMPT.md` | thread: `implement` | Code implementation with code review |
| `RESOLVE-PROMPT.md` | thread: `resolved` | Problem/resolution summary |
| `UPDATE-RESEARCH-PROMPT.md` | track sources (standalone `research` + attached `type: research`) | Fetch sources, compare against note, write updated note and summary |
| `TASK-PROMPT.md` | scan files (attached `type: task`) | Scan local files, propose actions, write note + task summary |

Each prompt receives `ITEM_ID`, `WORK_LOOP_DIR`, and `ITEM_DIR`. Track-sources runs also receive `title`, `note_path`, `sources`, `instruction`, and `BACKLINK_TARGET`. Attached routines additionally receive `PARENT_ID`, `PARENT_DIR`, and `run_id`. `UPDATE-RESEARCH-PROMPT.md` handles both standalone and attached modes; attached mode is detected by the presence of `PARENT_ID`.

### Loop Execution Order

Each iteration of the loop:

1. Moves `done` rows to the Done section
2. Resumes any running run-command routines (polling recovery)
3. Recovers any stalled remote jobs (polls `.done` sentinel)
4. Refreshes the WORK.md dashboard (report links + `## Needs Attention`)
5. Initializes new items
6. Promotes `scheduled` standalone routines whose cron fires now
7. Picks up `ready`/`analyze`/`implement`/`resolved`/`research` items and processes them
8. Processes attached routines for all threads (including `done` threads with active scheduled routines); re-scans for newly created routines after processing each thread

### Vault Auto-Scaffolding

Work-Loop bootstraps and syncs standard folders and agent rules in any vault it points to:

- **Startup Auto-Scaffolding:** on start, it ensures `00 Inbox/`, `03 Verified Research/`, `50 Raw/`, `WORK.md`, and `03 Verified Research/README.md` exist. Existing files are never overwritten, so an older vault's `WORK.md` keeps its old "How to use" text.
- **Skills:** copies `templates/skills/*` into the vault's `.claude/skills/`, `.opencode/skills/` and `.agents/skills/`.
- **Marker-Fenced `AGENTS.md` Sync:** manages a block (`<!-- WORK-LOOP:START --> ... <!-- WORK-LOOP:END -->`) inside the vault root `AGENTS.md` without touching your own instructions outside it.
- **Explicit Bootstrap:** `python3 run-loop.py --init-vault "/path/to/NewVault"`

### Running Tests

```bash
python3 -m pytest tests/ -v
# Remote integration test runs automatically if remote is reachable
```

E2E tests (`tests/test_e2e.py`) run the real harness and are opt-in:

```bash
ENABLE_E2E_TESTS=1 pytest tests/test_e2e.py -v   # run e2e in the foreground
ENABLE_BACKGROUND_E2E=1 pytest             # dispatch e2e in background after the unit suite
```

Background results are written to `e2e_results.log` and reported at the top of the next test run.

## Under the Hood

### Sub-Agents

Prompt-driven agents delegate focused work to sub-agents:

| Sub-Agent | Role | Purpose |
|---|---|---|
| `critic` | Reviewer | Reviews draft findings for unverified claims, inaccessible resources, and gaps |
| `code-reviewer` | Reviewer | Reviews code changes for correctness, edge cases, and test coverage |
| `verified-research` | Orchestrator | Runs verified research: new research (Path A) or compiling from the thread (Path B) |
| `research-worker` | Leaf Worker | Performs targeted web search for a single subtopic, writes raw extracts to a staging file, and returns a 1-line confirmation |

Sub-agent definitions live in `.opencode/agents/` (and `.claude/agents/`). The `verified-research` sub-agent is compiled from `templates/VERIFIED-RESEARCH-README.md` at dispatch time, so the human guidelines and the agent's behaviour stay in sync.

### Verified Research Orchestration (2x2 Matrix)

To prevent context window exhaustion (e.g. 128k RoPE boundaries on local models) and avoid memory thrashing on Apple Silicon Unified Memory, verified research operates on a **2x2 Matrix**:

| Mode \ Environment | **Automated Work-Loop** (`run-loop.py`) | **Interactive Session** (`opencode` TUI) |
|---|---|---|
| **Path A: Upfront (De Novo)**<br>*(Explicit request for new deep research)* | Triggered via `LOOP-PROMPT.md` Step 7.<br>Orchestrator breaks question into 2–4 subtopics $\rightarrow$ dispatches `research-worker` **serially** to local staging (`{ITEM_DIR}/context/research/raw-*.md`) $\rightarrow$ synthesizes standard note for Human Gate review (`needs-review`). | Triggered by direct user prompt.<br>Main agent delegates to `verified-research` subagent $\rightarrow$ worker fetches out-of-band $\rightarrow$ writes `03 Verified Research/{Topic}.md` $\rightarrow$ returns 1-line confirmation. |
| **Path B: Retrospective (Synthesis)**<br>*(Compiling an established dialogue into a note)* | Item has discussed findings across multiple iterations in `CONVERSATION.md`.<br>Agent invokes `verified-research` with conversation summary $\rightarrow$ synthesizes note using in-context quotes without re-fetching cited web pages. | User and agent explored a topic over a long interactive chat.<br>Main agent **never re-fetches web pages in the main thread**; it delegates synthesis to `verified-research` or compiles directly from in-context quotes. |

#### Key Architectural Guardrails
1. **Zero Raw Ingestion in Main Context**: The main conversation thread (in both interactive sessions and work-loop turns) must never fetch raw HTML or read full 500-line sample notes into its working context.
2. **Context-Isolated Leaf Workers**: `research-worker` subagents execute with minimal permissions, write raw extracts to disk (`{ITEM_DIR}/context/research/raw-*.md`), and return *only* `Done: Raw research written to {OUTPUT_FILE}`, freeing their KV cache memory immediately.
3. **Serial Execution on Local Hardware**: Workers are dispatched one at a time (serially) rather than concurrently, maintaining a flat memory footprint (~24GB weights + ~1–2GB active KV cache) on Apple Silicon / MLX.
4. **Staging $\rightarrow$ Promotion Lifecycle**: Raw extracts stay isolated in local staging (`{ITEM_DIR}/context/research/`) during research. Only the finalized, approved synthesis note is promoted to `03 Verified Research/`.
