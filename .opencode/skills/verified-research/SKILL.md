---
name: verified-research
description: Conducts verified deep web research on a topic, extracts verbatim claims with confidence ratings, resolves contradictions, and creates an authoritative Wikipedia-style note in 03 Verified Research/.
---

# Verified Research (De Novo / Upfront)

Use this skill when the user asks to research a new topic, answer a complex research question, or create a verified research note from the web.

## Instructions

1. **Context Protection (Critical):**
   - NEVER execute raw multi-query web searches or read multi-KB reference notes directly in the primary conversation thread.
   - Always delegate the research workflow to the `verified-research` subagent (or spawn leaf workers out-of-band).

2. **Delegation Workflow:**
   - Invoke `subagent_type="verified-research"` with:
     - `question`: The user's research topic or question.
     - `target_path`: `03 Verified Research/{Topic}.md`
     - `mode`: `de_novo`
   - The orchestrator will decompose the topic into subtopics and dispatch `research-worker` leaf agents serially to staging files.

3. **Output:**
   - The subagent compiles the layered single-note directly to `03 Verified Research/{Topic}.md`.
   - Return **ONLY** a concise 1-2 line confirmation with the wikilink to the created note (e.g. `Done: Verified research note created at [[03 Verified Research/{Topic}]]`).
