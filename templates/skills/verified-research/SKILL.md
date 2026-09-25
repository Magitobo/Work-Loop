---
name: verified-research
description: Researches a topic or question and writes (or updates) a verified note in 03 Verified Research/ — checking existing verified notes first, then 50 Raw/, then the web — with verbatim quotes, confidence ratings and resolved contradictions.
---

# Verified Research (Research → Synthesize)

Use this skill when the user asks to research a topic, answer a research question, or expand what the vault knows about something, and wants a verified note in `03 Verified Research/`.

## Instructions

1. **Context Protection (Critical):**
   - NEVER execute raw multi-query web searches, or read multi-KB reference notes or `50 Raw/` folders, directly in the primary conversation thread.
   - Always delegate the workflow to the `verified-research` subagent.

2. **Delegation Workflow:**
   - Invoke `subagent_type="verified-research"` with:
     - `mode`: `research`
     - `question`: The user's research topic or question.
     - `target_path`: `03 Verified Research/{Topic}.md` only if the user named a note; otherwise the subagent finds an existing note on the topic or derives a new path.
   - The subagent scans the vault (existing verified notes, then `50 Raw/`), researches what the vault could not settle on the web via serial `research-worker` agents, and synthesizes one note — updating an existing note on the topic instead of creating a duplicate.

3. **Output:**
   - Return **ONLY** a concise 1-2 line confirmation with the wikilink to the note, and whether it was created or updated (e.g. `Done: Verified research note updated at [[03 Verified Research/{Topic}]]`).
