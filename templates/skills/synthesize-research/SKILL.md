---
name: synthesize-research
description: Synthesizes findings, verbatim quotes, and URLs from the preceding conversation into an authoritative, layered research note in 03 Verified Research/ without re-fetching cited web pages into the primary thread.
---

# Synthesize Research (Discussion Compilation)

Use this skill when a user has explored a topic interactively across multiple turns and wants to save or compile the findings into a verified note in `03 Verified Research/`.

## Instructions

1. **Context Protection & In-Context Grounding:**
   - Do NOT re-fetch cited web pages into the primary session context.
   - Use the verbatim quotes, URLs, and factual claims already established in the conversation dialogue as primary grounding inputs.

2. **Delegation Workflow:**
   - Extract clean, structured data (no conversational dialogue or transcript noise):
     - `topic`: Topic name and 1-paragraph summary conclusion.
     - `subtopics`: List of subtopics, each containing items with `[claim, verbatim quote, source url/path, confidence]`.
     - `open_questions`: Unresolved points or uncertainties.
   - Delegate compilation to `subagent_type="verified-research"` with `mode: discussion_synthesis` and `target_path: 03 Verified Research/{Topic}.md`.
   - Pass ONLY the structured data payload (the subagent already has vault rules and note templates).

3. **Output:**
   - The subagent writes `03 Verified Research/{Topic}.md`.
   - Return **ONLY** a concise 1-line confirmation:
     `Done: Compiled discussion findings to [[03 Verified Research/{Topic}]]`
