# Work Loop Prompt — Implementation Mode

Each iteration implements ONE item with a fresh context. The script determines which item.

## Ground rules
- Your job is to **implement**, not just analyze. Take actions, write code, run shell commands, add new tests if needed, ensure all tests pass.
- Work methodically. Verify each step before continuing. If a step fails, diagnose and fix it.
- If you hit a hard blocker (missing prereq, auth failure, ambiguous spec), stop: document the
  blocker in CONVERSATION.md, set Status to "blocked", and exit — do not loop or retry endlessly.
- Always write to CONVERSATION.md, even on error. The user monitors that file.
- When referencing vault files in note content, use Obsidian wiki links `[[filename]]` (without extension).
- Any standalone report `.md` file created in ITEM_DIR must include a back-link to `[[CONVERSATION]]` near the top.
- Add wiki links to all files you modified or created. 

---

Use the ITEM_ID, WORK_LOOP_DIR, and ITEM_DIR passed at the end of this prompt.

1. Read `ITEM_DIR/CONVERSATION.md` for prior thread (newest first — read bottom-up for history).
   Any user entry after the latest AI Agent entry is updated guidance for this iteration.
   This file also contains the `work_dir:` path you are running from.
2. Read `ITEM_DIR/background.md` for internal context (if present).
3. Read all files in `ITEM_DIR/context/` for additional context (if present).
4. Read the implementation spec referenced in CONVERSATION.md (typically `ITEM_DIR/implementation-spec.md`
   or another file named in the conversation).
5. Execute the implementation tasks in order, verifying each step.
6. **Code Review** — if any code files were written or modified, spawn a `subagent_type="code-reviewer"` agent:

   ```
   Review code changes made for work item {ITEM_ID}.

   Code files modified or created:
   {list of code file paths}

   ITEM_DIR: {ITEM_DIR}

   Read each file, run any existing tests, and return your structured review.
   ```

   Wait for it to complete. Address any MUST-FIX findings before proceeding. Note
   SHOULD-FIX and SUGGESTION items in the CONVERSATION.md Issues section below.

7. Write a new entry to `ITEM_DIR/CONVERSATION.md` using a file write tool. You MUST actually
   write to the file — do NOT just include the text in your response:

---
## {YYYY-MM-DD} | AI Agent

### Summary
- [what was implemented / changed]

### Verification
- [steps taken to confirm correctness]

### Issues / Follow-up
- [blockers, deviations from spec, or remaining work]

---

8. Update `WORK_LOOP_DIR/WORK.md` using a file write tool. You MUST actually write to the file:
   find the row with ITEM_ID, set Status to "needs-review".
   If the Title cell is plain text (not a markdown link), replace it with
   `[concise title](ITEM_ID/CONVERSATION.md)`.
