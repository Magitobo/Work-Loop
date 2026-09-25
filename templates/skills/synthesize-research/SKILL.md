---
name: synthesize-research
description: Compiles research that was already done — this conversation, or 50 Raw/ notes or folders — into a verified note in 03 Verified Research/, without re-running the research.
---

# Synthesize Research (Synthesize Only)

Use this skill when the findings already exist and only need to be compiled into a verified note in `03 Verified Research/`: an interactive exploration in this conversation, or material the user collected in `50 Raw/`.

## Instructions

1. **Collect the raw material:**
   - **This conversation:** write the dialogue, backend logs and user-provided inputs to `50 Raw/{Category}/{YYYY-MM-DD}-{topic-slug}.md`, choosing an existing category folder under `50 Raw/` (e.g. `AI-Coding-Assistants`, `Software-Engineering`, `Relocation`).
   - **Existing `50 Raw/` notes or folders the user names:** use their paths as they are.

2. **Delegate to Subagent:**
   - Invoke `subagent_type="verified-research"` with:
     - `mode`: `synthesize`
     - `topic`: Clean topic title
     - `raw_sources`: the path(s) from step 1
     - `target_path`: `03 Verified Research/{Topic}.md` (an existing note is updated in place)
   - Pass ONLY these parameters (the subagent reads the raw material directly from disk).

3. **Output:**
   - The subagent links the raw notes as provenance and writes the note. Claims that only exist as AI prose in the raw material are marked low confidence and listed under Open Questions — suggest `verified-research` or `refresh-research` to verify them.
   - Return **ONLY** a concise 1-line confirmation with the active wikilink:
     `Done: Compiled findings to [[03 Verified Research/{Topic}]]`
