---
name: refresh-research
description: Re-verifies an existing note in 03 Verified Research/ — re-checks stale or weak claims, picks up new 50 Raw/ material, falls back to archived copies for dead links — and updates it in place.
---

# Refresh Research (Keep a Verified Note Current)

Use this skill when the user asks to refresh, re-verify or update an existing note in `03 Verified Research/`, or when a note is past its `review-due` date.

## Instructions

1. **Context Protection (Critical):** do not read the note's sources, the web, or `50 Raw/` folders in the primary conversation thread. Delegate.

2. **Delegation Workflow:**
   - Invoke `subagent_type="verified-research"` with:
     - `mode`: `refresh`
     - `target_path`: `03 Verified Research/{Topic}.md`
   - The subagent keeps high-confidence claims that are still in date, re-checks everything past due, medium/low confidence or anecdotal, adds `50 Raw/` notes created since `last-researched`, sweeps for recent changes, and updates the note in place with a Revision History line.

3. **Output:**
   - Return **ONLY** a concise 1-2 line confirmation with the wikilink and the Revision History summary (e.g. `Done: Refreshed [[03 Verified Research/{Topic}]] — 5 re-verified, 1 updated, 2 added`).
