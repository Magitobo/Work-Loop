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
   - One topic, one note: when a note on the topic already exists, **update it** instead of creating a second one.
2. **Flat, Topic-Driven Structure:**
   - Organize notes directly under `03 Verified Research/{Topic}.md` or `03 Verified Research/{Topic}/` for multi-aspect domains.
   - Do **not** build deep upfront folder hierarchies. Create subfolders only on-demand when topic complexity warrants it.
3. **Relationship to `50 Raw/`:**
   - [`50 Raw/`](../50%20Raw) holds unprocessed, immutable reference material, sorted into topic folders. It contains two kinds of notes:
     - **AI answers** — Perplexity exports and clipped AI chats (Gemini, ChatGPT, Claude, Copilot…). Useful **leads**, never evidence.
     - **Web clips** — pages clipped from the original site. A **snapshot** of that source as of the clip date.
   - `03 Verified Research/` extracts, rates, verifies, and synthesizes information from `50 Raw/` notes and live web sources.
4. **Two Steps: Research → Synthesize:**
   - **Research** gathers verbatim, dated, rated quotes — from the vault first, then the web — into raw staging files.
   - **Synthesize** turns raw material into one note. It can also run on its own, over material gathered separately (a `50 Raw/` note or folder, a work-loop thread, an interactive chat).
   - **Refresh** re-runs both steps on an existing note to keep it current.

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

[^1]: [Source Name](https://...) (primary/secondary/anecdotal, fetched YYYY-MM-DD) — "{Verbatim quote}" · **high/medium/low confidence**
[^2]: [Source Name](https://...) (secondary, clipped YYYY-MM-DD via [[50 Raw/Folder/Clip Note|clip]]) — "{Verbatim quote}" · **medium confidence**
[^3]: [Source Name](https://...) (primary, fetched YYYY-MM-DD · [archived copy](https://web.archive.org/web/...)) — "{Verbatim quote}" · **medium confidence** · live page changed YYYY-MM-DD

## Revision History

- YYYY-MM-DD — created ({research | synthesize})
- YYYY-MM-DD — refreshed: {N} claims re-verified, {N} updated, {N} added, {N} removed
```

---

## 3. Verification Rules for Authors & Agents

1. **No Assertion Without a Verbatim Quote From the Original Source:**
   - Every factual claim is backed by an exact quote from the **original** source (the web page, document, or dataset), never from memory and never from an AI's summary of it.
   - **Research / refresh:** fetch the source and quote it.
   - **Synthesize (on its own):** verbatim quotes and URLs already established in the input (a thread, a chat log, a web clip) are valid grounding when they quote the original source; do not re-fetch them. Only dispatch an out-of-band worker when a critical quote is missing. Claims that exist only as AI prose in the input are leads: give them **low confidence** and list them under **Open Questions** for a later research or refresh run.
2. **Source Hierarchy:**
   - **Primary Sources** (Official government portals, bank terms of service, technical specs, direct API docs): Highest priority.
   - **Secondary Sources** (Reputable news outlets, established industry blogs): Moderate priority; require corroboration where possible.
   - **Anecdotal Sources** (Forums, Reddit, community discussions): Treat as leads or low-confidence indicators, never as authoritative proof.
   - **AI answers** (Perplexity, Gemini, ChatGPT, Claude, Copilot output — including clipped chats): **never** a source. Follow the links they cite and quote the original instead.
3. **Research Order — Vault First, Then Web:**
   1. **Existing verified notes (`03 Verified Research/`):** find notes on the topic (filenames, frontmatter, summaries). If one covers the topic, the result is an **update of that note**. Reuse a claim as-is only when it is **high confidence**, from a **primary or secondary** source, and the note is **not past `review-due`** — carry over its original footnote (source, quote, fetch date). Everything else (medium/low confidence, anecdotal source, past `review-due`) becomes a target for re-verification on the web.
   2. **Raw material (`50 Raw/`):** search by title, tags and content across **all** folders — the folder name is only a hint. Classify each hit from its frontmatter:
      - **AI answer:** `url:` on perplexity.ai, or `model:`/`mode:` keys, or `source:` on gemini.google.com, chatgpt.com, chat.openai.com, claude.ai, copilot.microsoft.com or perplexity.ai. Extract its claims and cited links as **leads** to trace.
      - **Web clip:** any other `source:` URL. Quote the clip as a snapshot of that URL: cite the original URL, "clipped {created}", and wikilink the clip. For volatile topics, also check the live page.
   3. **Web:** targeted at what the vault could not settle — gaps, stale or weak claims, untraced leads — plus one sweep for recent changes or contradictions, even when the vault seems to cover the question.
   - Never cite a `03` note as the evidence for a claim — carry over its original source. Link vault notes you drew on (the `03` note being updated, `50 Raw/` notes used as leads or snapshots) as provenance below the frontmatter.
4. **Surface Contradictions Honestly:**
   - If sources conflict, do not silently discard one. Discuss both perspectives inline where the contradiction naturally arises, citing each source via footnotes, and articulate the resolution based on source authority and recency.
5. **Auditability & Provenance:**
   - When citing a web clip in the vault, give the original URL and link the clip: `(secondary, clipped YYYY-MM-DD via [[50 Raw/Topic/Note-Name|clip]])`.
   - When citing live web sources, provide the full URL, source type, and fetch date.
6. **Freshness, Review Dates & Refresh:**
   - Set `review-due` on every note: typically 30–90 days out for volatile topics (immigration rules, banking regulations, API pricing), 6–12 months for stable ones. Lower overall confidence → earlier review.
   - A refresh re-checks every claim that is past due, medium/low confidence or anecdotal, picks up `50 Raw/` notes created after `last-researched`, and sweeps for changes. It updates the note in place, keeps the original fetch date of claims it did not re-check, bumps `last-researched` and `review-due`, and adds a **Revision History** line.
   - **Dead or changed links:** if a cited URL is gone or no longer contains the quote, look up the Wayback Machine snapshot closest to the original fetch date (`https://archive.org/wayback/available?url={URL}&timestamp={YYYYMMDD}`). If the snapshot still has the quote, keep the claim, add `[archived copy](...)` and "live page changed YYYY-MM-DD" to the footnote, and re-verify against current sources when the topic is volatile. If there is no snapshot, lower the claim's confidence and list it under **Open Questions**.
7. **Readable Prose with Footnotes & Sequential Indexing:**
   - Write flowing, Wikipedia-style prose organized by sub-topic.
   - Cite sources using footnotes numbered sequentially (`[^1]`, `[^2]`, ...) in the exact order they appear in the body prose.
   - Keep verbatim quotes in footnotes concise (1–2 key sentences backing the claim, ≤40 words) rather than reproducing full paragraphs.
   - In the `## References` section, list matching `[^N]` definitions in exact numerical order, each carrying the verbatim quote, source type, confidence, and fetch (or clip) date.
