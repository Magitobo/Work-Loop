# Verified Research v2 — flatter chain, separate recipes, bounded workers

Status: proposed (2026-09-30)

## Why

Evidence from the VR-REFRESH-TEST runs on 2026-09-30 (OpenCode, llama.cpp Qwen 3.8 27B thinking; llama-swap captures #101–#144):

- **The chain is three subagent levels deep:** the main session (or a skill) starts the `verified-research` agent, which starts `research-worker`s. In OpenCode this only works with a `task` permission on the orchestrator and `"subagent_depth": 2`. Without both, the orchestrator silently did all the research in its own context (14:49 run). Claude Code subagents cannot start subagents, so the design does not work there at all.
- **Layers confuse their roles.** In the 14:49 run the `verified-research` agent began by loading the `refresh-research` skill, whose instructions say to invoke the `verified-research` agent, i.e. itself.
- **Each handoff rewrites the brief and loses focus.** For a *refresh*, the orchestrator told the worker to copy the target note's frontmatter, outline and entire References section verbatim, and to scan all of `50 Raw/` for "MLX-related notes". The orchestrator had already read the note itself.
- **The vault scan took 48 minutes** (19:49–20:37) for one 13 KB note:
  - Two broad greps (`[Mm][Ll][Xx]` over `50 Raw/`) returned about 64k and 20k characters, most of it unrelated local-model notes.
  - Triage reads used `limit: 45` lines, but AI-export notes have very long lines, so a "short" read was up to 11k characters (TurboQuant, tax, Docling notes).
  - The context reached 106k tokens, compaction ran (#140), and the worker re-read the note to recover the verbatim details the summary dropped.
  - It then wrote `raw-vault.md` (28 KB) in one 15.7k-token response that took 13 minutes.
- **The web phase was heading the same way.** The orchestrator planned 4 serial web workers.
  - The first worker fetched raw GitHub releases API and PyPI JSON. Its context reached 60k tokens after one batch of fetches (#147–#148), and one step took almost 10 minutes.
  - The run was aborted at 21:02, 1h29m in, partway through the first web worker, with only `raw-vault.md` written.
- **Refresh and research share one mode switch.** `refresh` is a flag passed through skill → orchestrator → worker, and each layer has to apply it correctly. The brief above mixed refresh work (a claim inventory) with research behaviour (a scan of everything), and the worker did the expensive part.
- **Cold starts add up:** each new subagent costs a 10–12k-token prefill, about a minute on the Mac Studio. With `-np 2` and `--cache-ram 0`, the layers also evict each other's KV cache.

## Design

### 1. Two levels instead of three

- **The skills hold the orchestration steps and run in the main session**, both interactively and in the loop (LOOP-PROMPT Step 7 tells the agent to follow the skill).
- **The main session starts single-purpose workers directly.** It only ever reads their one-line confirmations, small structured inputs (a note's frontmatter and footnotes), and the final draft path. The context protection rule stays: no raw web pages or `50 Raw/` reads in the main session.
- **The `verified-research` agent is removed.** With it go the `task` permission and the dependency on `subagent_depth: 2`. The same flow runs in OpenCode and Claude Code.

### 2. One recipe per job, no mode switch

Each skill is a self-contained recipe. None of them passes a mode to anything.

**`verified-research` (new research)**
1. Check `03 Verified Research/` for an existing note on the topic: filenames and frontmatter `topic:` only. If one exists, stop and offer a refresh or an expansion instead.
2. Choose 3–6 specific search terms, not just the topic name.
3. Start a *vault scan* worker with those terms.
4. From its result, plan 2–4 web subtopics, and start one *web research* worker per subtopic, serially.
5. Start a *write note* worker to create the draft from the raw files.

**`refresh-research`**
1. Read the target note's frontmatter and footnote definitions yourself. These are structured and bounded; do not read the body.
2. Select the claims due for re-checking: past `review-due`, medium or low confidence, anecdotal or AI-sourced, or tagged volatile.
3. Start *re-verify* workers with those footnotes (URL, quote, fetch date), grouped by source or subtopic.
4. Check for raw notes created after `last-researched` (a frontmatter date filter). Only if there are any, start a *vault scan* worker limited to those notes.
5. Start a short *change sweep* worker for "what changed since `last-researched`" (releases, status changes).
6. Start a *write note* worker to apply the changes in place and add a Revision History line.

In the VR-REFRESH-TEST case, step 4 would have found no new notes and been skipped. That would have saved most of the 48 minutes.

**`synthesize-research`**
1. Collect the paths the user named (`50 Raw/` notes or folders, `context/research/raw-*.md`, the thread).
2. Start a *write note* worker with them. No new fetching.

### 3. Workers defined by task, with output contracts

There is one `research-worker` definition with explicit task types. Each has its own inputs, limits and output sections:

| Task | Input | Output file |
|---|---|---|
| `vault-scan` | search terms; optional `created-after` date | `raw-vault.md`: ranked notes, snapshot quotes (clips), leads (AI answers) |
| `web-research` | one subtopic, leads, questions | `raw-{subtopic}.md`: claims with verbatim quotes, URL, source type, fetch date |
| `re-verify` | list of footnotes (claim, URL, quote, fetch date) | `raw-reverify-{n}.md`: one row per footnote — confirmed / changed (new quote) / gone |
| `write-note` | raw file paths; target path or new path; `create` or `update` | `draft-{slug}.md` |

**Search and read rules for all tasks:**
- **Narrow before reading.** Search filenames and frontmatter first, and grep only for specific phrases. If a grep returns more than about 30 matches, refine the pattern instead of reading the results.
- **Triage by frontmatter.** Read about the first 15 lines (frontmatter and description) to judge relevance. Read at most 10 notes in full.
- **Write incrementally.** Append to the output file after each batch of notes or sources, so compaction or a crash does not lose results. The file is the worker's memory.
- **Fetch narrowly.** Prefer a release page, a PR page or a single API object, like `.../releases/latest` or `.../pulls/1547`, over list endpoints and full JSON dumps (`?per_page=15`, the PyPI JSON). Extract the few fields needed and drop the rest.
- **Return one line,** as today.

### 4. Single source for the rules

The verification rules and the note template stay in `templates/VERIFIED-RESEARCH-README.md`. The worker definition and the three skills include them through the existing `{{templates/...#N}}` anchors. The recipes are separate; the rules are not duplicated.

## Changes

- `templates/skills/{verified-research,refresh-research,synthesize-research}/SKILL.md`: rewrite as the recipes above.
- `templates/agents/{opencode,claude}/research-worker.md`: task types, output contracts, search and read rules.
  - OpenCode keeps `edit: allow`; drop the `task` rule.
  - Claude: add a `tools:` line, and teach the sync to drop it for OpenCode, as it does for `model:`.
- `templates/agents/*/verified-research.md`: remove.
- `prompts/LOOP-PROMPT.md` Step 7: follow the matching skill in the main session instead of invoking the `verified-research` agent. Drafts and promotion stay as they are.
- `prompts/BASE-PROMPT.md`, `templates/vault-AGENTS.md`, `README.md`, `AGENTS.md`: update the descriptions.
- Tests (`tests/test_prompt_subagents.py`, `tests/test_scaffold.py`): agent existence and permissions, skill contents, Step 7 wording, anchor rendering.
- Vault cleanup: delete the synced `verified-research.md` from `.opencode/agents/` and `.claude/agents/`, since the sync no longer removes files.
- agent-global-configs: `subagent_depth: 2` can be dropped again once nothing nests.

## Verification

- Rerun VR-REFRESH-TEST (refresh, small note). Expected:
  - no vault-scan worker, since there are no new raw notes;
  - re-verify workers only for the due claims;
  - a draft with a Revision History line;
  - well under the 48 minutes the vault scan alone took on 2026-09-30.
- Run one new-research item on a narrow topic. Check the vault-scan worker's context stays well below the compaction point, and that `raw-vault.md` grows during the run.
- Run the same refresh with the Claude harness to confirm it works without nesting.
- Check the llama-swap captures: agent identities, tool lists, context per step, and no compaction in workers.

## Open questions

- **Web search in OpenCode:** the workers only have `webfetch`. Does the `web-research` task need a search tool (e.g. `OPENCODE_ENABLE_EXA=1`), or are leads and known URLs enough?
- **Thinking vs non-thinking model for workers:** extraction work may not need thinking. A per-agent `model:` in the OpenCode definition could point workers at the non-thinking alias.
- **Parallel workers:** they stay serial for now. With `-np 2`, two parallel workers would evict the main session's cache.

## Related

- `workloop/llmcapture.py` truncates streamed tool-call arguments when it parses SSE responses. The orchestrator's `task` call in #133 could not be parsed. Fix separately; the log analyzer depends on these files.
