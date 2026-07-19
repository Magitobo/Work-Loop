# Work Loop Prompt — Research Agent

Each iteration runs a research cycle on ONE item. The script determines which item.

## Ground rules
- Your job is to **research and update**, not to implement or analyze broadly
- Fetch and read each source URL listed in the research config
- Compare findings against the existing note — identify new information, outdated claims, and gaps
- Write an updated version of the note (overwrite in-place)
- Write a research summary to `{ITEM_DIR}/runs/{run_id}/research.md`
- Use Obsidian wiki links `[[filename]]` for all references
- Any file you create must include a back-link to `[[CONVERSATION]]` near the top
- Be concise in the note — bullet points, not essays
- In the research summary, list each change with a date, description, and source URL

---

Use ITEM_ID, WORK_LOOP_DIR, and ITEM_DIR passed at the end of this prompt.

## Step 1 — Load Context

1. Read `{ITEM_DIR}/CONVERSATION.md` for prior research thread (newest first — read bottom-up for history).
2. Read `{ITEM_DIR}/background.md` for internal context (if present).
3. Read `{ITEM_DIR}/context/` for additional context (if present).
4. Read the research config from `{ITEM_DIR}/RUNS.md` — extract sources, note_path, and Research Context.
5. Read the existing note at the target path (resolve the wiki link to a file path).
6. Read prior run summaries from `{ITEM_DIR}/runs/` (newest first) for context on what was already found.

## Step 2 — Fetch Sources

For each source URL in the config:
1. Fetch the URL content
2. Extract key information relevant to the topic and research context
3. Discard irrelevant content
4. Note which sources were accessible and which failed

## Step 3 — Compare and Identify Changes

Compare findings against the existing note:
- **New information** — facts, developments, or links not in the current note
- **Outdated claims** — information in the note that is no longer accurate
- **Gaps** — topics the research context says to cover but the note doesn't address
- **Confirmed stable** — information that remains accurate

## Step 4 — Write Updated Note

Overwrite the note at `note_path` with the updated content:
- Preserve the note's existing structure and formatting
- Add new information in relevant sections
- Update or remove outdated claims
- Add a `## Recent Updates` section at the top with the date and a brief summary
- Use wiki links `[[filename]]` for all cross-references
- Keep it concise — bullet points, not essays

## Step 5 — Write Research Summary

Create `{ITEM_DIR}/runs/{run_id}/research.md`:

```markdown
## {YYYY-MM-DD} — {topic}

### Changes
- [Added/Updated/Removed] [description] — [source URL]

### Sources Fetched
- [URL] — [status: OK / FAILED]

### Notes
- [Any gaps, questions, or follow-ups]
```

Include a back-link to `[[CONVERSATION]]` at the top of the file if it's a new file.

## Step 6 — Update WORK.md

Find the row with `{ITEM_ID}` in `{WORK_LOOP_DIR}/WORK.md`. Set Status to "needs-review".
If the Title cell is plain text (not a markdown link), derive a concise title and replace with `[concise title]({ITEM_ID}/CONVERSATION.md)`.
