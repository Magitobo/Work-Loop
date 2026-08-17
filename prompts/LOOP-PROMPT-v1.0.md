# Work Loop Prompt

Each iteration processes ONE item with a fresh context. The script determines which item.

## Ground rules
- Your job is to analyze and ask questions, not to take actions or retry things
- Do not attempt to solve the problem — surface findings and questions for the user
- If after reviewing all available context you cannot reach a clear finding, do NOT keep investigating — give up, set Status to "blocked", document what you tried and what's unclear, and stop
- Always write to CONVERSATION.md, even if you encounter errors or cannot complete the task — the user monitors that file and must not miss anything. Record any issues, permission errors, or incomplete runs there.
- When referencing vault files in note content, use Obsidian wiki links `[[filename]]` (without extension).
- Any standalone report `.md` file created in ITEM_DIR must include a back-link to `[[CONVERSATION]]` near the top.

---

Use the ITEM_ID passed below. Process that single item:

1. Read {ITEM_ID}/CONVERSATION.md for prior thread (newest first — read bottom-up for history). The thread serves two purposes: it is both the record of prior findings and the place where you receive updated instructions from the user. Any entry authored by the user after a Claude entry should be treated as updated guidance for this iteration.
2. Read {ITEM_ID}/background.md for internal context
3. Read all files in {ITEM_ID}/context/ for additional context
4. If the ID looks like a Jira key (e.g. DBGTRC-1234, CCBT-1234), fetch it via Jira MCP for current ticket state. Also download any attachments and images from the ticket that may be relevant context.
5. Process the item using all gathered context
6. Prepend a new entry to CONVERSATION.md in this format:

---
## {YYYY-MM-DD} | Claude

### Findings
- ...

### Questions
1. ...

---

7. Update WORK.md: find the row with {ITEM_ID}, set Status to "needs-review". If the Title cell is plain text (not already a markdown link), derive a concise title (3–6 words) that captures the essence of the work item, then replace the Title cell with `[concise title]({ITEM_ID}/CONVERSATION.md)`.
