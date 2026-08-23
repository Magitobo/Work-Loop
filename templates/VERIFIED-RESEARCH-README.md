# Verified Research Guidelines & Standards

> [!warning] Auto-generated — do not edit
> This file is generated and maintained by Work-Loop from `templates/VERIFIED-RESEARCH-README.md`. Local edits will be overwritten on the next loop run. To change this file, edit the template in the Work-Loop repo.

This directory contains curated, high-confidence, verified research notes. It serves as the authoritative knowledge layer in the vault, bridging raw inputs and actionable decisions.

Any contributor—whether **human** or **AI agent** (such as the `verified-research` subagent)—must follow the rules and format described below when creating or updating notes here.

---

## 1. Core Architecture & Philosophy

1. **Layered Single-Note Model:**
   - Avoid creating separate atomic files for individual claims, sources, and critiques.
   - Instead, encapsulate all layers of a research topic (Synthesis, Extracted Claims, Quotes, Contradiction Analysis, Uncertainties, and Source Catalog) within a single comprehensive note.
2. **Flat, Topic-Driven Structure:**
   - Organize notes directly under `03 Verified Research/{Topic}.md` or `03 Verified Research/{Topic}/` for multi-aspect domains.
   - Do **not** build deep upfront folder hierarchies. Create subfolders only on-demand when topic complexity warrants it.
3. **Relationship to `50 Raw/`:**
   - [`50 Raw/`](../50%20Raw) holds unprocessed, immutable reference dumps (Perplexity exports, web clips, chat logs, raw scrape text).
   - `03 Verified Research/` extracts, rates, verifies, and synthesizes information from `50 Raw/` notes and live web sources.

---

## 2. Standard Note Template

Every research note created in this folder **must** adhere to this template structure:

```markdown
---
topic: {Topic Name}
last-researched: YYYY-MM-DD
review-due: YYYY-MM-DD
confidence: high # high | medium | low (overall assessment)
tags:
  - research
---

[[02-Work-Loop-Items/{Optional-Item-ID}/CONVERSATION]]

## Summary
> [!summary] Confidence: {high/medium/low} · {N} sources
> One-paragraph overall conclusion answering the core research question.

## {Sub-Topic 1}

Readable prose synthesizing findings for this sub-topic. Every factual
claim must cite a footnote.[^1] When sources disagree, present both
perspectives inline with their respective citations — Source A reports
X,[^2] while Source B found Y.[^3] Assess which view the evidence
favors based on source authority and recency.

## {Sub-Topic 2}

Continue with flowing prose for each sub-topic...

## Open Questions

- {Unresolved points, missing details, or edge cases with suggested next steps}

## References

[^1]: [Source Name](https://...) or [[50 Raw/...|Source Name]] (primary/secondary/anecdotal, fetched YYYY-MM-DD) — "{Verbatim quote}" · **high/medium/low confidence**
[^2]: [Source Name](https://...) (primary, fetched YYYY-MM-DD) — "{Verbatim quote}" · **high confidence**
[^3]: [[50 Raw/...|Source Name]] (anecdotal, fetched YYYY-MM-DD) — "{Verbatim quote}" · **low confidence**
```

---

## 3. Verification Rules for Authors & Agents

1. **No Assertion Without Fetching & Quoting (Path A & Path B):**
   - **Path A (De Novo Research):** When researching a new topic, always fetch the source content and extract exact verbatim quotes. Never assert facts from ungrounded memory.
   - **Path B (Discussion Synthesis):** When synthesizing findings from an existing in-depth conversation or work item, use the verbatim quotes and URLs already established in the dialogue as valid primary grounding inputs. Do not perform redundant re-fetches in the primary session context; only dispatch an out-of-band worker if critical quotes are missing.
2. **Source Hierarchy:**
   - **Primary Sources** (Official government portals, bank terms of service, technical specs, direct API docs): Highest priority.
   - **Secondary Sources** (Reputable news outlets, established industry blogs): Moderate priority; require corroboration where possible.
   - **Anecdotal Sources** (Forums, Reddit, community discussions): Treat as leads or low-confidence indicators, never as authoritative proof.
3. **Surface Contradictions Honestly:**
   - If sources conflict, do not silently discard one. Discuss both perspectives inline where the contradiction naturally arises, citing each source via footnotes, and articulate the resolution based on source authority and recency.
4. **Auditability & Provenance:**
   - When citing a source existing in the vault, use Obsidian wikilinks: `[[50 Raw/Topic/Note-Name|Note Title]]`.
   - When citing live web sources, provide the full URL, source type, and fetch date.
5. **Freshness & Review Dates:**
   - For volatile or time-sensitive topics (e.g. immigration rules, banking regulations, API pricing), set `review-due` (typically 30–90 days out) so outdated facts can be surfaced via Dataview queries.
6. **Readable Prose with Footnotes & Sequential Indexing:**
   - Write flowing, Wikipedia-style prose organized by sub-topic.
   - Cite sources using footnotes numbered sequentially (`[^1]`, `[^2]`, ...) in the exact order they appear in the body prose.
   - Keep verbatim quotes in footnotes concise (1–2 key sentences backing the claim, ≤40 words) rather than reproducing full paragraphs.
   - In the `## References` section, list matching `[^N]` definitions in exact numerical order, each carrying the verbatim quote, source type, confidence, and fetch date.
