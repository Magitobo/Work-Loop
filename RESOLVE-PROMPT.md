# Work Loop Prompt — Resolved Mode

Each iteration creates ONE resolution summary with a fresh context. The script determines which item.

## Ground rules
- Your job is to **summarize**, not implement. Write a brief, clear problem/resolution summary.
- Read the entire conversation thread to understand what the problem was and how it was resolved.
- If the conversation does not contain enough information to write a meaningful summary, note that in the Resolution block.
- Always write to CONVERSATION.md. The user monitors that file.
- When referencing vault files in note content, use Obsidian wiki links `[[filename]]` (without extension).
- Any standalone report `.md` file created in ITEM_DIR must include a back-link to `[[CONVERSATION]]` near the top.

---

Use the ITEM_ID, WORK_LOOP_DIR, and ITEM_DIR passed at the end of this prompt.

1. Read `ITEM_DIR/CONVERSATION.md` for the full thread (newest first — read bottom-up for history).
2. Read `ITEM_DIR/background.md` for internal context (if present).
3. Read all files in `ITEM_DIR/context/` for additional context (if present).
4. From the conversation, identify: what the problem was, and how it was resolved.
5. Prepend a new entry to `ITEM_DIR/CONVERSATION.md` in this format:

---
## {YYYY-MM-DD} | Claude

## Resolution
**Problem:** [1–2 sentence summary of what the problem or task was]
**Resolution:** [how it was resolved — key decisions, changes made, or outcome]

---

6. Update `WORK_LOOP_DIR/WORK.md`: find the row with ITEM_ID, and move the row to the Done section
   (keep the Status as 'resolved' — do not change it).
   If the Title cell is plain text (not a markdown link), replace it with
   `[concise title](ITEM_ID/CONVERSATION.md)`.
