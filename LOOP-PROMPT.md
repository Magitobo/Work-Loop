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

---

Use ITEM_ID, WORK_LOOP_DIR, and ITEM_DIR passed below.

## Step 1 — Full Investigation + Draft

Read all available context:

1. Read `{ITEM_DIR}/CONVERSATION.md` in full (newest first — history at bottom). The thread
   is both the record of prior findings and the place where you receive updated instructions.
   Any user entry after a Claude entry should be treated as updated guidance for this iteration.
2. Read `{ITEM_DIR}/background.md` if it exists
3. Read all files under `{ITEM_DIR}/context/`
4. If ITEM_ID looks like a Jira key (e.g. DBGTRC-1234), fetch via Jira MCP and download
   any relevant attachments or images

Then produce a **DRAFT** (in-context only — do NOT write to CONVERSATION.md yet):

```
--- DRAFT ---

SOURCES:
- {ITEM_DIR}/CONVERSATION.md: loaded / COULD NOT READ
- {ITEM_DIR}/background.md: loaded / not found
- {ITEM_DIR}/context/{file}: loaded / COULD NOT READ
- Jira {ITEM_ID}: loaded / not applicable
(list every source attempted and whether it loaded)

ANSWERS TO PRIOR QUESTIONS:
For each question in the prior Claude entry's Questions list, and each inline "Oliver:"
annotation in CONVERSATION.md: answer it directly here. Use context files, Jira, and
your own knowledge freely — for questions about Claude Code features, YAML syntax, or
general software engineering, answer from knowledge without needing a file source.
If genuinely unanswerable, note it here and carry it forward to DRAFT QUESTIONS.

DRAFT FINDINGS:
- ...

DRAFT QUESTIONS:
1. ...

--- END DRAFT ---
```

## Step 2 — Internal Review

Spawn the following agent. Its output is FOR YOUR USE IN STEP 3 — it will NOT appear in CONVERSATION.md.

**`subagent_type="critic"`:**

```
Review the following draft findings for work item {ITEM_ID}.

ITEM_DIR: {ITEM_DIR}

--- DRAFT ---
{paste the full DRAFT from Step 1, including SOURCES, DRAFT FINDINGS, and DRAFT QUESTIONS}
--- END ---

Apply your four checks. Return your checklist.
```

Wait for it to complete before proceeding.

## Step 3 — Revise

Read the Critic and Code Reviewer outputs. Update your DRAFT to address all issues before
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

Prepend to `{ITEM_DIR}/CONVERSATION.md`:

```
## {YYYY-MM-DD} | Claude

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

Find the row with {ITEM_ID} in `{WORK_LOOP_DIR}/WORK.md`. Set Status to "needs-review".
If the Title cell is plain text (not a markdown link), derive a concise title (3–6 words) and
replace with `[concise title]({ITEM_ID}/CONVERSATION.md)`.
