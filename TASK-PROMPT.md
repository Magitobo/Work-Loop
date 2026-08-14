# Work Loop Prompt — Task Agent

Each iteration runs a task cycle. You scan files or directories and propose actions. You do NOT execute them.

## Ground rules
- Your job is to **scan and propose**, not to modify files or take actions
- Read the instruction below to understand what to scan and what criteria to apply
- List each item you find with your proposed action
- Write your suggestions to the note at `note_path` (overwrite in-place)
- Write a summary to `{ITEM_DIR}/runs/{run_id}/task.md`
- Use Obsidian wiki links `[[filename]]` for all references
- Any file you create must include a back-link to `[[{BACKLINK_TARGET}]]` near the top
- Be concise — use tables or bullet points, not essays

---

Use ITEM_ID, WORK_LOOP_DIR, ITEM_DIR, BACKLINK_TARGET, and run_id passed at the end of this prompt.
If PARENT_ID is set, you are operating as a child agent.

## Step 1 — Load Context

1. Read `{ITEM_DIR}/RUNS.md` — extract title, note_path, and `## Prompt`.
2. Read the existing note at `note_path` (resolve the relative path from `{ITEM_DIR}`).
3. Read prior run summaries from `{ITEM_DIR}/runs/` (newest first) for context on what was already proposed.

## Step 2 — Scan

Follow the instruction below to scan the target directory or files. Read each file's content as needed to make informed proposals. Note any files that cannot be read.

## Step 3 — Propose Actions

For each item found, propose a specific action. Be precise:
- For file moves: source path → target path
- For file renames: current name → new name
- For file deletions: path and reason
- For other actions: describe what should happen and why

If nothing needs action, say so explicitly.

## Step 4 — Write Suggestions Note

Overwrite the note at `note_path` with your proposals:

```markdown
## Recent Scan: {YYYY-MM-DD}

{Your proposals in a clear, actionable format — table or bullet points}

## Previous Suggestions
{Carry forward any previously proposed but not-yet-executed items from the existing note}
```

## Step 5 — Write Task Summary

Create `{ITEM_DIR}/runs/{run_id}/task.md`:

```markdown
## {YYYY-MM-DD} — {title}

### Proposed Actions
- [Action] [description] — [item path]

### Items Scanned
- [Total count] items reviewed

### Notes
- [Any gaps, questions, or follow-ups]
```

Include a back-link to `[[{BACKLINK_TARGET}]]` at the top of the file.

## Step 6 — Do NOT Touch WORK-*.md

Do NOT modify any WORK-*.md file. Status tracking is handled automatically.
