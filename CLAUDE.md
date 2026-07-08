# Work-Loop

## What This Is

An automated loop that runs Claude (`claude --print`) on work items one at a time. Each item gets a fresh Claude context. Items can run locally or be dispatched to a remote host over SSH.

## Directory Layout

Scripts (this repo) and work items live in separate sibling directories:

```
MyNotebook/
├── Work-Loop/          ← scripts repo (this directory)
│   ├── run-loop.py
│   ├── test_run_loop.py
│   ├── LOOP-PROMPT.md
│   ├── IMPL-PROMPT.md
│   ├── RESOLVE-PROMPT.md
│   └── .claude/settings.json
└── Work-Loop-Items/    ← work items (part of the vault, not the scripts repo)
    ├── WORK.md
    ├── .logs/
    └── <item-id>/      ← one folder per work item
```

## Key Files

| File | Purpose |
|---|---|
| `run-loop.py` | The loop script — `WorkLoop` class + `main()` |
| `../Work-Loop-Items/WORK.md` | The work item table (source of truth for status) |
| `LOOP-PROMPT.md` | Prompt injected for `analyze`/`ready` items |
| `IMPL-PROMPT.md` | Prompt injected for `implement` items |
| `test_run_loop.py` | Unit tests (+ optional remote integration test) |

## WORK.md Table Schema

```
| ID | Title / Initial Prompt | Location | Status | Last Updated | Budget | Log |
```

- **ID** — folder name under `Work-Loop/`; also the Jira key if it looks like one
- **Location** — `local` or `user@hostname` for remote SSH dispatch
- **Status** — controls what the loop does (see below)
- **Budget** — per-item override (e.g. `$5.0`); defaults to `MAX_BUDGET` (10.00)

## Status State Machine

```
new → ready/analyze/implement → in-progress → needs-review
                                             → blocked
                                done  (auto-moved to Done section)
```

| Status | Meaning |
|---|---|
| `new` | Loop creates folder + `CONVERSATION.md` from Title, then sets `ready` |
| `ready` / `analyze` | Triggers LOOP-PROMPT.md run |
| `implement` | Triggers IMPL-PROMPT.md run; reads `work_dir:` from CONVERSATION.md |
| `in-progress` | Set by loop before Claude starts; prevents double-dispatch |
| `needs-review` | Claude finished (or failed); human review needed |
| `blocked` | Kerberos expired on remote, or Claude hit a hard blocker |
| `done` | Human marks complete; loop moves row to Done section |

## Work Item Structure

Each item lives in `{ITEM_ID}/`:
```
{ITEM_ID}/
├── CONVERSATION.md     # Thread between user and Claude (newest entry first)
├── background.md       # (optional) internal context for Claude
└── context/            # (optional) additional context files
```

`CONVERSATION.md` doubles as the initial prompt (seeded from the Title column if missing) and the running conversation log. Claude prepends new entries; user adds replies below.

For `implement` mode, the file must contain a `work_dir: /path/to/repo` line so the loop sets Claude's working directory correctly.

## Loop Execution

```bash
python3 run-loop.py      # runs forever, Ctrl+C to stop
```

Each iteration:
1. Moves `done` rows to the Done section
2. Recovers any stalled remote jobs (polls `.done` sentinel)
3. Initializes `new` items
4. Picks up `ready`/`analyze`/`implement` items and processes them

For **local** items: runs `claude --print --permission-mode auto --max-budget-usd <budget>` with the prompt + `ITEM_ID`/`WORK_LOOP_DIR`/`ITEM_DIR` appended.

For **remote** items:
1. Wipes `~/Work-Loop` on the remote
2. Rsyncs item folder + `LOOP-PROMPT.md` + `.claude/settings.json`
3. Uploads and launches a bash script via `nohup` (Claude runs detached)
4. Polls `{ITEM_ID}/.done` every 5 seconds for the exit code
5. Rsyncs results back, reads Claude's title from remote `WORK.md`, wipes remote

## Failure Handling

When Claude exits non-zero, `_classify_failure()` inspects the log:
- **auth** — Kerberos ticket expired; Budget column gets `$N - AUTH-EXPIRED`
- **budget** — cost limit hit; Budget column gets `$N - EXCEEDED`
- **unknown** — other failure

All failures set status to `needs-review` and prepend an abort notice to `CONVERSATION.md`. For remote items, Kerberos is checked *before* dispatch; expired ticket sets status to `blocked` immediately.

## Running Tests

```bash
python3 -m pytest test_run_loop.py -v
# Remote integration test runs automatically if remote is reachable and kinit'd
```
