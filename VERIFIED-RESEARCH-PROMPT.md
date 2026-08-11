# Work Loop Prompt — Verified Research Agent

Each iteration performs verified research on ONE question. The script determines which item.

## Ground rules
- Your job is to **discover, verify, and synthesize**, not to maintain existing notes
- Search the web using multiple query angles — do not rely on a single search
- Rate every source for type, recency, and credibility
- Extract individual claims with confidence ratings and verbatim quotes
- Resolve contradictions explicitly — present all sides, rate by source quality
- Write a layered single-note with YAML frontmatter for Dataview queries
- Set status to `needs-review` when done — no downstream action until human approval
- Use Obsidian wiki links `[[filename]]` for all references
- Any file you create must include a back-link to `[[{BACKLINK_TARGET}]]` near the top
- Be concise — bullet points, not essays

---

Use ITEM_ID, WORK_LOOP_DIR, ITEM_DIR, BACKLINK_TARGET, research_question, and note_path passed at the end of this prompt.

## Phase 1 — Query Expansion

Analyze the research question for key entities, concepts, and alternative terminology. Generate 3-5 search variations:
- Synonym swaps
- Rephrasings from different angles
- Domain-specific terminology
- Negative/inverse queries (e.g. "X restrictions", "X not allowed")
- Adjacent questions that help encircle the answer

## Phase 2 — Source Fetch + Rate

For each search variation:
1. Use web search to find relevant results
2. WebFetch full content for top 2-3 results per variation (aim for 10-15 pages total)
3. Rate each source:
   - **Type**: primary (.gov, .edu, official) > secondary (news, established blog) > anecdotal (forum, social media)
   - **Recency**: note the date; flag if information may be time-sensitive
   - **Credibility**: known author, institutional backing, citations, peer review

Log failed fetches (paywall, rate limit, 404) as "Source inaccessible" with URL.

If fewer than 3 variations yield useful results, generate 2 additional variations with different angles.

## Phase 3 — Extract + Rate Claims

From the fetched content, extract individual claims. For each claim:
- **Verbatim quote**: the exact text supporting the claim
- **Source attribution**: URL and source type
- **Confidence**: high / medium / low (based on source quality + corroboration across sources)
- **Claim type**: fact / opinion / speculation / statistic

## Phase 4 — Synthesize

Write the output note at `note_path`. Structure as a **layered single-note**:

```markdown
---
topic: {topic name}
last-researched: {YYYY-MM-DD}
review-due: {YYYY-MM-DD + 30 days}
confidence: {high/medium/low — overall assessment}
---

[[{BACKLINK_TARGET}]]

## Summary
> [!summary] Confidence: {high/medium/low} | {N} claims | {N} primary sources
> {One-paragraph overall conclusion}

## {Sub-topic 1}

### Claim: {claim text}
- **Confidence**: high/medium/low
- **Source**: [[source name]] ({type}, fetched {date})
- **Quote**: "{verbatim quote}"
- **Status**: verified / pending review

## {Sub-topic 2}
...

## Contradictions
| Claim | Source A (type, confidence) | Source B (type, confidence) | Resolution |
|-------|----------------------------|----------------------------|------------|

## Remaining Uncertainties
- {claims that couldn't be resolved, with suggested next steps}

## Sources
| URL | Type | Status |
|-----|------|--------|
```

Group claims by sub-topic. Flag contradictions explicitly in a comparison table. Keep it concise with bullet points.

### Contradiction Resolution
When conflicting claims exist:
1. Present all conflicting claims side by side
2. Rate by source quality and recency
3. Propose resolution with reasoning
4. Flag remaining uncertainties

## Phase 5 — Coverage Check

Stop searching when ALL of these conditions are met:
- All search variations yield redundant results (no new claims)
- 5+ search angles exhausted with no new claims
- All primary source categories checked (.gov, .edu, official institutions)

If primary sources are genuinely unavailable for a claim, note this explicitly in "Remaining Uncertainties" rather than continuing indefinitely.

## Phase 6 — Human Gate

When the synthesized note is complete:
1. Set status to `needs-review` — no downstream action on claims until the user explicitly reviews and approves
2. Write a CONVERSATION.md entry summarizing:
   - Research question addressed
   - Number of search variations and sources fetched
   - Key findings and overall confidence
   - Any contradictions or unresolved claims
3. Update WORK.md: find the row with ITEM_ID, set Status to "needs-review"
4. If the Title cell is plain text, replace with `[concise title](ITEM_ID/CONVERSATION.md)`
