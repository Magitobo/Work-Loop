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
   - Extract a structured summary of:
     - Core topic and summary conclusion
     - Subtopics with factual claims and their verbatim quotes
     - Cited URLs and source metadata
     - Open questions / uncertainties
   - Delegate compilation to `subagent_type="verified-research"` with `mode: discussion_synthesis` and `target_path: 03 Verified Research/{Topic}.md`.
   - If a critical quote is missing, the subagent will dispatch a single `research-worker` out-of-band to fetch only the missing quote.

3. **Output:**
   - The note is written to `03 Verified Research/{Topic}.md` adhering to the standard template.
   - Return **ONLY** a concise 1-2 line confirmation with the note link:
     `Done: Compiled discussion findings to [[03 Verified Research/{Topic}]]`
