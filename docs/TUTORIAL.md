# Work-Loop Tutorial

This tutorial walks you through everything Work-Loop can do, one small example at a time. Each section builds on the previous one, and most take about five minutes against a scratch vault.

## The idea in one minute

Work-Loop watches one Markdown file, `WORK.md`, and runs an AI agent (Claude or OpenCode) whenever something in it asks for work. Each run starts with a fresh context and writes its results back into your vault, and then it's your turn again.

You work with just two things, plus one action you can ask for:

| You want to… | Use a… | Where it lives |
|---|---|---|
| Work through a problem with an agent, and optionally have it write code | **Thread** | `<ID>/CONVERSATION.md` |
| Repeat a job on a schedule: keep a note up to date from web sources, scan folders for tidy-up suggestions, or run a shell command on some machines | **Routine** | `RUNS.md` |
| Get a one-off, fully sourced answer saved as a vetted note | **Verified research**, which you ask for inside a thread | `03 Verified Research/<Topic>.md` |

Routines come in three kinds:

| Routine kind | What it does | Config value |
|---|---|---|
| **Track sources** | Re-reads a fixed list of URLs and updates one living note with what changed | `type: research` |
| **Scan files** | Looks through local folders and writes suggested actions (moves, renames…). It doesn't carry them out unless you explicitly allow it | `type: task` |
| **Run command** | Runs a shell command on one or more machines, then optionally aggregates the output and has the AI summarise it | `command:` |

A routine can be **standalone**, with its own row in `WORK.md`, or **attached** to a thread. An attached routine belongs to that thread: its report link appears under the thread, and the thread's agent proposes, pauses and resumes it. The code and config files call attached routines *children*.

> [!note] Why the docs say "Routine" and not "research item"
> The config keys and prompt file names are older than this tutorial. "Research" in the code can mean a *track sources* routine (`type: research`, `UPDATE-RESEARCH-PROMPT.md`). It is **not** the same as *verified research*. The [Glossary](#9-glossary) at the end maps every docs term to its code name.

---

## 1. Setup

1. Copy the example config and edit it:
   ```bash
   cp config-example.json config.json
   ```
   Set `work_dir` to the folder where your items should live, for example `/path/to/Vault/02-Work-Loop-Items`. Also set `harness.type` to `claude` or `opencode`.
2. Scaffold the vault. This creates `00 Inbox/`, `03 Verified Research/`, `50 Raw/`, a starter `WORK.md`, and a managed block in the vault's `AGENTS.md`:
   ```bash
   python3 run-loop.py --init-vault "/path/to/Vault"
   ```
3. Start the loop and leave it running. `Ctrl+C` stops it.
   ```bash
   python3 run-loop.py
   ```

Open `WORK.md` in Obsidian. It has four parts:

| Section | What it's for |
|---|---|
| **Add New Item** | Type a request as a checkbox bullet and tick it to start a new thread |
| **Needs Attention** | Maintained by the loop and only shown when something is waiting for you: threads in `needs-review`, and attached routines that failed or flagged something |
| **Active Items** | One row per thread or standalone routine, with its status, last update and log |
| **Done** | Finished items. Rows move here automatically |

> [!tip] Already have a vault?
> The scaffold only creates `WORK.md` when it doesn't exist yet, so older vaults keep their old "How to use" text. To get the current wording, copy the section from `templates/WORK.md` by hand.

---

## 2. Your first thread

1. Under **Add New Item**, write a request and tick the box:
   ```markdown
   - [x] Compare the three cheapest ways to back up my photo library offsite
   ```
2. Within a few seconds the loop:
   - creates a folder for the item. The ID is made from the first four words of your text; to choose it yourself, write `- [x] **MY-ID** …`
   - seeds `CONVERSATION.md` with your request
   - adds a row under **Active Items** with status `ready`
   - starts the agent. The status changes to `in-progress`.
3. The agent investigates, has its draft checked by an internal critic, and then writes a reply at the top of `CONVERSATION.md` with **Findings** and **Questions**. The status becomes `needs-review`, which means it's your turn. The item also shows up under **Needs Attention**.
4. Reply by adding your own entry at the top of the thread, just below the Action Center box (newest entries go first):
   ```markdown
   ## 2026-09-24 | User

   I already pay for iCloud 200GB. Does that change the answer?
   ```
5. Tick **Continue Analyze** in the Action Center box at the top of `CONVERSATION.md`. The loop picks the thread up again.

The **Action Center** box at the top of every thread is how you control it without leaving the note:

| Checkbox | Status it sets | What happens |
|---|---|---|
| Continue Analyze | `ready` | Another analysis round (`LOOP-PROMPT.md`). The agent finds things out and asks questions, but doesn't act |
| Run Implement | `implement` | The agent acts: writes code and runs commands (`IMPL-PROMPT.md`). See §3 |
| Mark Resolved (Move to Done) | `resolved` | The agent writes a short Problem / Resolution summary, then the row moves to **Done** |
| Abort | `abort` | Stops a running agent, or cancels a run that hasn't started |

You can also edit the **Status** cell in `WORK.md` directly. `analyze` does the same as `ready`. To close a thread without a summary, set the status to `done`.

---

## 3. From analysis to code

When a thread has settled on a plan, let the agent carry it out:

1. Add a `work_dir:` line anywhere in `CONVERSATION.md`, pointing at the repository it should work in:
   ```markdown
   work_dir: /Users/me/code/photo-backup
   ```
2. Tick **Run Implement**.

The agent runs from inside `work_dir`, follows the plan from the thread (or an `implementation-spec.md` in the item folder), and runs the tests. If it changed code, a `code-reviewer` sub-agent reviews the changes first. The agent then adds **Summary / Verification / Issues** to the thread and sets `needs-review`. If it hits something it can't resolve, it sets `blocked` and explains why.

---

## 4. Asking for verified research

Normal analysis rounds use whatever the agent can find quickly. When you need an answer you can trust later, with every claim backed by a quoted source, ask for **verified research** in your reply and tick **Continue Analyze**.

There are two ways to phrase it:

- **Research something new:**
  > Do verified research on the tax treatment of MM2H visa holders and create a note in 03 Verified Research/.

  The agent splits the question into 2–4 subtopics and researches each one separately. Raw extracts are staged in `<ID>/context/research/raw-*.md`. The agent then writes one structured note (summary, claims with confidence, sources) and sets `needs-review`, so you check it before relying on it.

- **Turn what the thread already found into a note:**
  > Compile what we've found so far into a verified research note.

  The agent builds the note from the quotes and links already in the thread. It doesn't fetch the web again.

The note format and sourcing rules are in `03 Verified Research/README.md` in your vault.

You can do the same outside the loop. The vault scaffold installs two skills for interactive Claude or OpenCode sessions opened in your vault: `verified-research` researches something new, and `synthesize-research` saves the current chat to `50 Raw/` and compiles a note from it. Verified research only runs when you ask for it. It is a one-off action, not a routine. To keep a topic up to date over time, use a *track sources* routine (§5 and §6).

---

## 5. Attached routines

Attached routines let a thread keep working in the background after you've stopped talking to it.

### Ask for one

In your reply, describe what should repeat:

> Keep an eye on the MM2H rule changes. Check the official page and two news sites every Monday and tell me if anything affects me.

On its next round, the agent **proposes** a routine instead of creating it straight away. The proposal includes the full config it wants to write:

```markdown
#### Create child agent: `rules` — MM2H rule changes

**RUNS.md to create at `children/rules/RUNS.md`:**
## Config
type: research
parent: MM2H-PLAN
title: MM2H rule changes
note_path: ../context/mm2h-rules.md
sources:
  https://www.mm2h.gov.my/
schedule: 0 7 * * 1

## Prompt
Flag any change to income, deposit or tax requirements.
```

Reply "yes" (or ask for changes) and tick **Continue Analyze**. The agent then creates:

```
MM2H-PLAN/
├── WORK-CHILDREN.md          ← list of this thread's attached routines and their status
├── children/rules/RUNS.md    ← the config above, plus a run history table
└── context/mm2h-rules.md     ← the living note the routine keeps up to date
```

Creating, changing or deleting a routine always needs your approval. The agent can pause, resume or re-run one without asking, and it records that in the thread.

### What you see afterwards

- A **report link** appears under the thread's title in `WORK.md`. It points to the living note, which always has the latest version.
- Each run adds a row to `children/rules/RUNS.md` and writes details to `children/rules/runs/<run_id>/research.md`.
- If a run finds something that needs your decision, it flags the note and the routine appears under **Needs Attention** with a one-line reason. Failed runs show up there too.
- On the thread's next analysis round, the agent reads the routine's results and summarises them under **Child Agent Updates**.

### A scan-files example

Scan-files routines are always attached. For example, in an "Inbox hygiene" thread:

> Every morning, look through `00 Inbox` and suggest where each note should go.

The proposed config looks like this:

```markdown
## Config
type: task
parent: INBOX-HYGIENE
title: Inbox cleanup
note_path: ../context/inbox-suggestions.md
schedule: 0 8 * * *

## Prompt
Scan the 00 Inbox folder. Suggest which folder each file should move to:
- Business → 01-Work
- Personal → 02-Personal
```

Each run rewrites `context/inbox-suggestions.md` with proposed moves. It **does not move anything** unless the `## Prompt` explicitly allows it, for example "move files you are highly confident about using the obsidian CLI".

### Attached routine statuses

These appear in the **Status** column of `WORK-CHILDREN.md`:

| Status | Meaning |
|---|---|
| `scheduled` | Waiting for its `schedule:` cron to fire |
| `ready` | Will run on the next loop pass |
| `running` | Running now |
| `done` | One-off run finished. Set it back to `ready` to run it again |
| `needs-review` | The last run failed or needs you |
| `paused` | Paused by the thread's agent |
| `abort` | You cancelled it |

---

## 6. Standalone routines

Use a standalone routine when the job doesn't belong to any conversation. You create these by hand: make a folder with a `RUNS.md`, then add a row to **Active Items**.

### Track sources

Create `AI-SECURITY/RUNS.md`:

```markdown
## Config
type: research
title: AI Security
note_path: [[AI Security]]
sources:
  https://arxiv.org/list/cs.CR/recent
  https://openai.com/blog

## Prompt
Focus on: model vulnerabilities, alignment failures, supply chain risks
Exclude: consumer AI apps, chatbot features
```

Add a row under **Active Items** with status `research`:

```markdown
| [AI Security](AI-SECURITY/RUNS.md) | research | | | AI-SECURITY |
```

The agent fetches each source, compares it with the note, rewrites the note with a **Recent Updates** section, and logs the run in `RUNS.md`. When it finishes, the status becomes `done`, or `scheduled` if the config has a `schedule:`, and the next run happens automatically when the cron fires.

To run it again by hand, tick **Run Now** in the Action Center of the item's `CONVERSATION.md`, or set the status back to `research`. A track-sources routine's Action Center only has **Run Now** and **Abort**; the thread actions don't apply to it.

### Run command

Run commands have no AI step unless you ask for one. Create `DISK-REPORT/RUNS.md`:

```markdown
## Config
command: python3 disk_report.py
params: --top 20
schedule: 0 2 * * *
locations:
  linux:me@server1
  linux:me@server2
timeout: 10
aggregation_script: /path/to/merge_reports.py
analysis_prompt: Summarise which machines are close to full
```

Add a row with status `scheduled`, or `ready` to run it straight away. The loop:

1. sends the command to every machine
2. waits for each one to finish, time out (`timeout:` minutes), or go quiet (`heartbeat_file:`)
3. then runs the optional fan-in: your `aggregation_script`, then the `analysis_prompt` through the AI

Each run gets a row in `RUNS.md` and a folder under `runs/`. The status goes `running` → `success`, or straight back to `scheduled` if the config has a `schedule:`. It becomes `needs-review` instead if a machine timed out or the fan-in failed.

---

## 7. Running a thread on another machine

Threads can run on a remote host over SSH instead of locally. You need key-based SSH and the same harness CLI installed on the remote. To run remotely, give the item a location. In the **Active Items** table, add it to the Task / Conversation cell after the link. A per-item budget goes in the same place:

```markdown
| [Photo backup](PHOTO-BACKUP/CONVERSATION.md) · location: me@mac-studio · budget: $5 | ready | 2026-09-25 | | PHOTO-BACKUP |
```

The loop copies the item folder and prompts to the remote, starts the agent detached (so it survives SSH drops), waits for it, copies the results back, and cleans up the remote folder. **Abort** works for remote runs too.

> Both tokens are optional. Without `location:` the thread runs locally. Without `budget:` it uses `max_budget_usd` from `config.json`. Bullet rows (`- [ ] [Title](ID/CONVERSATION.md) · status: ready · location: … · budget: …`) and the legacy table's Location and Budget columns also work.

---

## 8. Status cheat sheet

### Threads and standalone routines (the Status cell in `WORK.md`)

| Status | Set by | Applies to | What happens next |
|---|---|---|---|
| `new` | you | legacy table format only | Loop creates the folder and `CONVERSATION.md`, then sets `ready` |
| `ready` / `analyze` | you | thread | Analysis round |
| `implement` | you | thread | Implementation round in `work_dir` |
| `resolved` | you | thread | Summary written, row moved to Done |
| `research` | you (or **Run Now**) | track sources | One track-sources run |
| `scheduled` | loop (or you) | routines | Waits for the cron, then becomes `ready` |
| `in-progress` | loop | thread, track sources | An agent is running now |
| `running` | loop | run command | Commands are running on the machines |
| `needs-review` | loop / agent | all | **Your turn.** Read the result and reply |
| `blocked` | agent | thread | The agent couldn't continue. The reason is in the thread |
| `success` | loop | run command | All machines finished and the fan-in succeeded |
| `done` | you or loop | all | Row moves to Done |
| `abort` | you | all | Cancels, or kills a running agent |

If a run fails or hits its budget, the status becomes `needs-review`, a notice is added to the top of the thread, and the budget shows `$N - FAILED` or `$N - EXCEEDED`.

### Attached routines

See the table at the end of [§5](#attached-routine-statuses).

---

## 9. Glossary

| Docs term | Name in code / config / files |
|---|---|
| Thread | conversation item. `get_item_type() == 'conversation'`, `CONVERSATION.md` |
| Analysis round | `ready` / `analyze` status, `prompts/LOOP-PROMPT.md` |
| Implementation round | `implement` status, `prompts/IMPL-PROMPT.md` |
| Resolve | `resolved` status, `prompts/RESOLVE-PROMPT.md` |
| Routine | anything configured by a `RUNS.md` |
| Track sources routine | "research item" or "child research": `type: research`, `prompts/UPDATE-RESEARCH-PROMPT.md` |
| Scan files routine | "child task": `type: task`, `prompts/TASK-PROMPT.md` |
| Run command routine | "script item": `RUNS.md` with `command:`, `get_item_type() == 'script'` |
| Attached routine | child / child agent: `children/<name>/RUNS.md`, listed in `WORK-CHILDREN.md` |
| Standalone routine | top-level `RUNS.md` item with its own row in `WORK.md` |
| Living note | `note_path` (also `living_note_path`) |
| Verified research | the `verified-research` sub-agent (with `research-worker` helpers), output in `03 Verified Research/` |
| Research something new / compile from the thread | "Path A (de novo)" / "Path B (discussion synthesis)" in agent prompts |
| Action Center | the `[!action]` callout at the top of `CONVERSATION.md` |

For configuration details, remote dispatch internals and how the sub-agents are arranged, see the [README](../README.md).
