---
name: synthesize-research
description: Dumps interactive conversation context into 50 Raw/ and synthesizes an authoritative note in 03 Verified Research/.
---

# Synthesize Research (Discussion Compilation)

Use this skill when compiling findings from an interactive exploration into a verified research note in `03 Verified Research/`.

## Instructions

1. **Dump Raw Conversation to `50 Raw/`**:
   - Write the conversation dialogue, backend logs, and user-provided inputs to:
     `50 Raw/{Category}/{YYYY-MM-DD}-{topic-slug}.md`
   - Select an appropriate existing category folder under `50 Raw/` (e.g. `Local AI`, `AI-Coding-Assistants`, `Software-Engineering`, `Relocation`, etc.).

2. **Delegate to Subagent**:
   - Invoke `subagent_type="verified-research"` with:
     - `topic`: Clean topic title
     - `raw_source`: `50 Raw/{Category}/{YYYY-MM-DD}-{topic-slug}.md`
     - `target_path`: `03 Verified Research/{Topic}.md`
     - `mode`: `discussion_synthesis`
   - Pass ONLY these parameters (the subagent will read the raw note directly from disk).

3. **Output**:
   - The subagent reads the raw source, links to `[[50 Raw/...]]`, and writes the note.
   - Return **ONLY** a concise 1-line confirmation with the active wikilink:
     `Done: Compiled discussion findings to [[03 Verified Research/{Topic}]]`
