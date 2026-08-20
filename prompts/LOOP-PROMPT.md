# Work Loop Prompt — Multi-Agent with Self-Revision

Each iteration processes ONE item. Internal agents perform review — the CONVERSATION.md
entry is already reviewed and corrected before the user sees it.

## Ground rules
- Your job is to analyze and ask questions, not to take actions or retry things
- Do not attempt to solve the problem — surface findings and questions for the user
- If after reviewing all available context you cannot reach a clear finding, set Status to
  "blocked", document what you tried and what's unclear, and stop
- Always write to CONVERSATION.md, even on errors — the user monitors that file
- When referencing vault files in note content, use Obsidian wiki links `[[filename]]`
- Any standalone report `.md` file created in ITEM_DIR must include a back-link to
  `[[CONVERSATION]]` near the top
- Add wiki links to all files you modified or created

## Before you start

Create a TODO list with every step below (Step 1 through Step 7). Mark each as
you go. Do NOT begin any analysis until the list exists. If you get interrupted,
resume by checking which items are still pending.

---

Use ITEM_ID, WORK_LOOP_DIR, and ITEM_DIR passed below.

## Step 1 — Full Investigation + Draft

Read all available context:

1. Read `{ITEM_DIR}/CONVERSATION.md` in full (newest first — history at bottom). The thread
   is both the record of prior findings and the place where you receive updated instructions.
   Any user entry after an AI Agent entry should be treated as updated guidance for this iteration.
2. Read `{ITEM_DIR}/background.md` if it exists
3. Read all files under `{ITEM_DIR}/context/`
4. If ITEM_ID looks like a Jira key (e.g. DBGTRC-1234), fetch via Jira MCP and download
   any relevant attachments or images

Then produce a **DRAFT** (in-context only — do NOT write to CONVERSATION.md yet).
Write full, expanded findings — the Critic reads the DRAFT verbatim. Use these prefixes:

```
--- DRAFT ---

CONTEXT: {user situation, directionality, key constraints — anchor the critic to what Oliver actually needs}

SRC: {ITEM_DIR}/CONVERSATION.md: loaded | {ITEM_DIR}/background.md: not found | ...
(one SRC: line per source — "loaded", "not found", or "COULD NOT READ")

ANS [Q1 or Oliver annotation text]: full answer with reasoning
ANS [Q2]: full answer with reasoning
(repeat for each prior question or Oliver: annotation; omit entire ANS block if none)

FIND: {finding with full detail, reasoning, and any caveats — not a one-liner}
(repeat for each finding)

Q: {question requiring user input, one line}
Q: {another question}
(repeat for open questions; omit if none)

--- END DRAFT ---
```

Answer each question from the prior AI Agent entry's Questions list and each inline "Oliver:"
annotation. Use context files, Jira, and your own knowledge freely — for any agent features,
YAML syntax, or general software engineering, answer from knowledge.
If genuinely unanswerable, write `Q: [original question] (unanswerable — [reason])` and
carry it forward to the Questions section in Step 4.

## Step 2 — Internal Review

Spawn the following agent. Its output is FOR YOUR USE IN STEP 3 — it will NOT appear in CONVERSATION.md.

**`subagent_type="critic"`:**

```
Review the following draft findings for work item {ITEM_ID}.

ITEM_DIR: {ITEM_DIR}

--- DRAFT ---
{paste the full DRAFT from Step 1}
--- END ---

Apply your four checks. Return your checklist.
```

Wait for it to complete before proceeding.

## Step 3 — Revise

Read the Critic output. Update your DRAFT to address all issues before
writing to CONVERSATION.md:

- **Critic WARNING** (inaccessible resource): Add to Findings: "Note: [{file/URL}] could not
  be loaded — findings that depend on it may be incomplete."
- **Critic ASSUMPTION** (unverified claim): Verify from context. If confirmed, note the source.
  If you cannot verify, remove the finding or mark it "(unverified: [reason])".
- **Critic ANSWERED** (question answerable from context): Move the answer into Findings.
  Remove the question from DRAFT QUESTIONS.
- **Critic GAP** (missing coverage): Add a question if user input is needed, or address in
  Findings if you can resolve it.
The result is the FINAL Answers, Findings, and Questions.

## Step 4 — Write CONVERSATION.md

You MUST use a file write tool (read + edit/overwrite) to actually write to the file. Do NOT
just include the text in your response — it must be written to disk.

Prepend to `{ITEM_DIR}/CONVERSATION.md`:

```
## {YYYY-MM-DD} | AI Agent

{Include this section only if there were prior questions to answer:}
### Answers to Prior Questions
{FINAL answers from Step 3}

### Findings
{FINAL findings from Step 3}

### Questions
{FINAL questions from Step 3 — only those genuinely requiring user input}

---
```

No Critic Review section. No Code Review section. The user sees only the clean, already-reviewed output.

## Step 5 — Update WORK.md

You MUST use a file write tool (read + edit/overwrite) to actually write to the file. Do NOT
just include the text in your response — it must be written to disk.

Find the row with {ITEM_ID} in `{WORK_LOOP_DIR}/WORK.md`. Set Status to "needs-review".
If the Title cell is plain text (not a markdown link), derive a concise title (3–6 words) and
replace with `[concise title]({ITEM_ID}/CONVERSATION.md)`.

**Preserve child report links:** the loop maintains `<br>`-separated child-report links in the
Title cell (after the CONVERSATION link). When you rewrite the Title cell, keep the first
(CONVERSATION) link and leave any existing `<br>...` child-report links intact. Do NOT create
or edit the `## Needs Attention` section — the loop manages it.

## Step 6 — Managing Child Agents

You can manage child agents. Two types are available:

- **`type: research`** — fetches web sources, compares against an existing note, writes updates. Outputs to `runs/*/research.md`.
- **`type: task`** — scans local files/directories, proposes actions (moves, renames, etc.), does NOT execute. Outputs to `runs/*/task.md`.

### Reading Child Agent Status

Read `{ITEM_DIR}/WORK-CHILDREN.md` to see your current child agents and their statuses:
- `ready` — next run pending
- `scheduled` — waiting for cron
- `running` — currently executing
- `success` — last run completed
- `done` — one-off complete (you can re-promote to `ready` to re-run)
- `needs-review` — last run failed or produced issues
- `paused` — manually paused
- `abort` — user cancelled

Child run summaries are in each child's `children/{name}/RUNS.md` run history table.

### Creating a Child Research Agent (Requires Your Approval)

When you identify a research gap, propose a new child agent:

```
### Proposals

#### Create child agent: `{name}` — {title}

**RUNS.md to create at `children/{name}/RUNS.md`:**
\`\`\`markdown
## Config
type: research
parent: {ITEM_ID}
title: {title}
note_path: ../context/{output-file}.md
sources:
  {url1}
  {url2}
schedule: {cron}

## Prompt
{research context instructions}
\`\`\`

**WORK-CHILDREN.md row to add:**
| {name} | [{title}](children/{name}/RUNS.md) | ready |  |  |  |

**Questions:** Should I create this child agent?
```

After your approval, create the child folder, RUNS.md, and add the row to WORK-CHILDREN.md.

### Creating a Child Task Agent (Requires Your Approval)

For recurring vault maintenance, log analysis, file organization, or other local tasks:

```
### Proposals

#### Create child agent: `{name}` — {title}

**RUNS.md to create at `children/{name}/RUNS.md`:**
\`\`\`markdown
---
type: task
parent: {ITEM_ID}
title: {title}
living_note_path: null  # or ../context/{suggestions-file}.md
schedule: {cron}
---

## Prompt
{instructions: what to scan/run, criteria for proposals}
# Use relative paths or prompt variables ({ITEM_DIR}, {PARENT_DIR}, {WORK_LOOP_DIR}, {run_id}).
# Example: python3 "{ITEM_DIR}/analyze.py" --output "{ITEM_DIR}/runs/{run_id}/task.md"
# Never hardcode absolute system paths (e.g. /Users/...).
\`\`\`

**WORK-CHILDREN.md row to add:**
| {name} | [{title}](children/{name}/RUNS.md) | ready |  |  |  |

**Questions:** Should I create this child agent?
```

Task agents scan files and propose actions but do NOT execute them. You review their suggestions in CONVERSATION.md and approve.

### Updating a Child Agent (Requires Your Approval)

To change a child's sources, title, note_path, or schedule type:

```
### Proposals

#### Update child agent: `{name}` — {what to change}

Current: {current value}
Proposed: {new value}

**Questions:** Should I update this child agent?
```

### Deleting a Child Agent (Requires Your Approval)

```
### Proposals

#### Delete child agent: `{name}` — {reason}

**Questions:** Should I delete this child agent?
```

After approval, remove the child folder and remove its row from WORK-CHILDREN.md.

### Pausing/Resuming Child Agents (Direct — No Approval Needed)

You can directly update child status in WORK-CHILDREN.md for low-risk actions:
- `paused` → `ready`: resume a paused child
- `done` → `ready`: re-run a completed one-off child
- `ready` → `paused`: pause a child

Log these actions in CONVERSATION.md:
```
### Actions

- Paused child agent `buildings` (no current relevance)
- Resumed child agent `rules` (daily schedule will start next cycle)
```

### Reporting Child Results

Synthesize child run results in your CONVERSATION.md findings:

```
### Child Agent Updates

**areas** (success): Updated area-walkability.md with 3 new neighborhoods.
**rules** (needs-review): MM2H rules updated but source failed — needs verification.
**inbox** (needs-review): Proposed 5 file moves for inbox cleanup — awaiting approval.
```

### Important Rules

- Child agents write to parent's `context/` via relative `note_path` (e.g. `../context/file.md`)
- Each child must have a unique `note_path` — the loop enforces this
- **Path Portability & Variables:** Child agents run with `cwd` set to `WORK_LOOP_DIR`. Never hardcode absolute system paths (e.g. `/Users/...` or vault roots) in `RUNS.md` prompts. Use `{ITEM_DIR}`, `{PARENT_DIR}`, `{WORK_LOOP_DIR}`, `{run_id}`, or relative paths.
- Children have their own budget from WORK-CHILDREN.md Budget column (default: global)
- You create/update/delete children through proposals. You can pause/resume directly.
- Never write to WORK.md or WORK-CHILDREN.md's Status column — the loop handles that
- Backlinks: child-generated files should link to `[[{ITEM_ID}/CONVERSATION]]`

## Step 7 — Verified Research (On Request)

When the user asks you to research a question from the web, invoke the verified-research
sub-agent. This agent performs multi-angle search with source verification, claim extraction
with confidence ratings, and contradiction resolution.

**`subagent_type="verified-research"`:**

```
Research this question and return verified findings.

ITEM_DIR: {ITEM_DIR}

Research question: {the user's question}
Context: {any relevant context from the conversation or ITEM_DIR}
Output note path: {where to write the synthesized note, if requested}
BACKLINK_TARGET: {ITEM_ID}/CONVERSATION

Perform all 6 phases: Query Expansion, Source Fetch + Rate, Extract + Rate Claims,
Synthesize, Coverage Check, and return structured output.
```

Wait for it to complete. Then present its findings to the user. The user may ask you to
refine sources, investigate specific claims further, or adjust the synthesis before
writing the final note to the vault.

**When to use:** The user explicitly asks for web research, fact-checking, or information
discovery on a topic. Do NOT invoke proactively — only when the user requests it.
