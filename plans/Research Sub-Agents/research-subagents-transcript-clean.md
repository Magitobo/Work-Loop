# KL Neighborhood Research for MM2H Visa

---

## User

We just implemented a research agent which is great. I wonder now how to get started with this. I realized my first need is more of exploratory research: finding a good neighbourhood to live and invest in Kuala Lumpur on MM2H visa. It's complex due to
- regulatory restrictions on what properties qualify to satisfy MM2H rule.
- budget limitations we have but still satisfying the minimums required
- amenities and feel of the neighbourhood
- condo building needs to be well constructed and maintained
- access to parks (we like walking) and malls (we like shopping)
- access to KL airport as we need to travel every month to Chennai to visit aging parents
- condo large enough to have space for our hobbies (3 bed would be minimum I think)

This research and decision making could go on for months. We have only been to KL for 4 days and learned the rest from Internet and YouTube. We are going again in 6 weeks and would like to have at least an idea which KL areas and condo buildings to consider to visit./

How can our new research agent help here? Let's brainstorm ideas!

---

## Assistant

Great question. Let me first understand what your research agent setup looks like, then brainstorm how to use it effectively for this KL property research.

---

Great — I now have a solid picture of what the research agent can do. Here's my brainstorm on how to structure this:

---

## How the Research Agent Can Help

Your agent has two relevant modes: **conversation items** (analysis + critic review) and **research items** (fetch URLs, compare, update notes iteratively). For this use case, I'd combine both.

### Proposed Structure: A Research "Hub" with Focused Sub-Items

Instead of one giant item trying to cover everything, you get a **parent research item** that maintains the big picture, with **focused sub-items** that dive into specific areas. This gives you breadth without blinders, and depth without paralysis.

```
KL-MM2H-Research/
├── CONVERSATION.md          ← master research log, decision framework
├── background.md            ← your personal prefs, budget range, travel dates
├── context/
│   ├── mm2h-rules.md        ← MM2H property requirements
│   ├── budget-analysis.md   ← your numbers + what they buy in KL
│   └── areas-to-consider.md ← evolving shortlist
└── (sub-items in WORK.md)
```

### Phase 1: Frame the Problem (Week 1-2)

**Item: `KL-MM2H-01` — "Define research scope & constraints"**

Run this as a **conversation/analyze** item. The agent would:

1. Read your background.md (budget, hobbies, travel frequency to Chennai, must-haves vs nice-to-haves)
2. Fetch current MM2H property rules (the RM300k/500k threshold, foreign ownership rules, rental restrictions)
3. Produce a **decision framework** — a structured comparison matrix of what matters, weighted by importance
4. Surface gaps: "You haven't specified commute patterns within KL, pet policy needs, or whether you plan to rent it out when not in Malaysia"

This is where the **critic subagent** is valuable — it would flag assumptions like "assuming all KLCC-area condos meet MM2H thresholds" without verifying.

### Phase 2: Area Research (Week 2-3)

**Item: `KL-MM2H-02` — "Research KL neighborhoods against criteria"**

This is where **research items** shine. You'd define sources and research context to focus the agent on areas within 45 min of airport, with parks and malls within 10 min walk, filtering for condos with RM300k+ units (MM2H minimum).

Each run fetches those URLs, compares against existing notes, and updates the area comparison. You can run this **iteratively** — each cycle adds new sources and refines the analysis.

### Phase 3: Building Deep-Dives (Week 3-4)

**Items: `KL-MM2H-03a`, `03b`, etc. — "Evaluate specific condo buildings"**

Once areas narrow to 3-5, you spawn focused items on individual buildings covering construction quality, unit availability and pricing, and actual walkability to parks/malls.

### Phase 4: Site Visit Prep (Week 5-6)

**Item: `KL-MM2H-04` — "Build visit itinerary for 6-week trip"**

Synthesizes everything into a practical plan: which buildings to visit, in what order, what questions to ask agents, what to look for during walkthroughs.

---

## Key Design Principles for Your Setup

**1. Keep background.md alive** — This is your evolving requirements doc. As you learn and reconsider, you update it. Each research item reads it. This is how you handle the "we don't have full goals yet" problem — the agent always works from your current understanding.

**2. Use the critic subagent aggressively** — For research items, the critic will catch things like outdated sources, unverified claims, or missing considerations.

**3. Research items with scheduled runs** — You could set a cron schedule to have the agent refresh market data and flag changes. Each run produces a `research.md` changelog so you see what's new.

**4. The "adjacent areas" problem** — Instead of narrowing too fast, keep a "watchlist" section in your areas note. When the agent evaluates one area, it also notes similar alternatives without going deep. You revisit watchlist items when the primary options are exhausted.

**5. Budget discipline** — With a $10/item budget, you need to be strategic. Conversation items with critic review cost more but catch errors early. Research items are cheaper per cycle.

---

## What I'd Recommend Starting With

A single **conversation/analyze** item to:
1. Establish your decision framework (weighted criteria)
2. Do initial MM2H regulatory research
3. Produce a first-pass area shortlist (broad)
4. Identify the specific URLs/sources to feed into research items

Then spin up 2-3 **research items** in parallel on the top area candidates.

---

A few questions for you:

1. **What's your approximate budget range?** This determines whether we're looking at RM300k-500k (entry MM2H tier) or RM500k+ (higher-end, more options)
2. **Do you have a preferred harness** (Claude vs OpenCode) for research items? The critic subagent uses Claude models, so conversation items get that quality gate. Research items run with whatever your default harness is.
3. **Should we create the first work item now**, or do you want to refine the approach first?

---

## User

Interesting idea having the research agent contribute to the context/ in a work item. I think what we need to better define is who owns which md: me only, collaboration between agent(s) and me, agent only.

---

## Assistant

Good point. Let me look at what the system currently does and think through a clean protocol.

---

Here's what I see from the current system, and my thinking on a clean ownership protocol:

---

## Current Behavior (Implicit)

| File | Who Writes | Who Reads |
|---|---|---|
| `CONVERSATION.md` | **Both** — agent prepends, user appends | Both |
| `background.md` | **User only** (agent never writes) | Agent |
| `context/` | **User only** (agent never writes) | Agent |
| `RUNS.md` | **User** (config) + **Agent** (run rows) | Both |
| `WORK.md` | **User** (structure) + **Agent** (status cells) | Both |
| `runs/{id}/*.md` | **Agent only** | User |

The gap: there's no explicit rule about whether the agent can write to `context/`. Right now it can't, but for your KL research, you want it to contribute there.

---

## Proposed Ownership Protocol

I'd suggest a **three-tier model** based on what each file is:

### Tier 1: User-Only (Requirements & Decisions)
**`background.md`** — Your personal requirements, preferences, budget, constraints. The agent reads this but never writes. You update it as your understanding evolves.

**`WORK.md`** — You control the table structure, item creation, status changes, and final decisions.

### Tier 2: Collaborative (Conversation Thread)
**`CONVERSATION.md`** — Already works well. Agent prepends findings/questions, you append answers/decisions/annotations. The "Oliver:" annotation pattern is a good mechanism for you to interject.

### Tier 3: Agent-Owned (Research Artifacts)
**`context/`** — This is where I'd change the current behavior. The agent writes here as research outputs. You review and can override.

Examples:
- `context/mm2h-rules.md` — Agent fetches and maintains current MM2H property rules with sources
- `context/area-comparison.md` — Agent builds and updates a comparison matrix of neighborhoods
- `context/building-shortlist.md` — Agent tracks specific condos with pros/cons
- `context/glossary.md` — Agent maintains KL property terminology

### Tier 4: Agent-Only (Internal)
**`runs/{id}/*.md`** — Research summaries, internal artifacts. You don't need to read these unless debugging.

---

## Key Design Decisions

**1. Agent writes to `context/` but marks its own contributions**

Every agent-written section in a `context/` file gets a header like:
```markdown
## Area Comparison (agent, 2025-07-19)
- Bangsar: ...
- Mont Kiara: ...
```

And you can add your own sections:
```markdown
## My Notes (Oliver)
- Bangsar feels too expensive for what you get
- Need to verify Mont Kiara walkability to parks
```

This makes it immediately clear what's agent research vs your judgment.

**2. Agent reads everything, but only writes to its tier**

The agent always reads `background.md`, `context/`, and `CONVERSATION.md` for full context. But it only writes to `context/` and `CONVERSATION.md`. This prevents the agent from accidentally overwriting your requirements.

**3. You can "promote" agent findings to `background.md`**

When the agent surfaces something in `context/` that changes your thinking, you move it to `background.md`. This is how requirements evolve — the agent proposes, you dispose.

**4. Research items write to `context/` directly**

The RESEARCH-PROMPT.md currently writes to a single `note_path`. For your use case, you'd set `note_path` to something like `[[context/area-comparison]]` and the agent updates that file each cycle.

**5. Conversation items can create new `context/` files**

The LOOP-PROMPT.md already allows creating standalone `.md` files in `ITEM_DIR`. Extend this to explicitly allow `context/` as a target.

---

## What This Looks Like in Practice

```
KL-MM2H/
├── CONVERSATION.md          ← collaborative thread
├── background.md            ← YOUR requirements (you own)
├── context/
│   ├── mm2h-rules.md        ← agent-maintained, with your annotations
│   ├── area-comparison.md   ← agent-maintained, with your annotations
│   └── building-shortlist.md← agent-maintained
└── runs/
    └── 20250719-001/
        └── research.md      ← agent internal
```

Agent run produces findings and questions. You respond with annotations like:
```
Oliver: RM500k is soft ceiling — could stretch to 600k for the right place.
Oliver: Mont Kiara looks promising, add Damansara Heights to comparison.
Oliver: I don't care about building age, just want it well-maintained.
```

---

## Tradeoffs to Consider

**Option A: Agent writes to `context/`** — Agent does the heavy lifting of research synthesis, you review and annotate.

**Option B: Agent creates separate `research/` directory, never touches `context/`** — Clean separation, you decide what to promote. More manual work for you.

**Option C: Agent writes to `context/` but you must approve before it "commits"** — Maximum control. Slows down the research loop.

I'd recommend **Option A** with the annotation convention. The agent is the research engine — you're the decision engine. Let it do what it's good at.

---

A few questions:

1. **Does this three-tier model feel right**, or do you see files that don't fit cleanly?
2. **Should the annotation convention be explicit in the prompt files**, or do you want to keep it informal?
3. **For the KL research specifically**, do you want to start with a conversation item (to frame the problem) or a research item (to immediately start fetching sources)?

---

## User

I think I like this. So the CONVERSATION.md is our thread where we decide and interact. And the LOOP agent (or IMPL agent?) would be able to set up the recurring research agents via RUNS.md? But I think we would want multiple RUNS.md research agents, one for each area of research, right? How would that fit in?

---

## Assistant

Good question. Here's what I see from the code:

---

## Current System: No Auto-Spawning

The agent **cannot create new work items in WORK.md**. It can only:
- Update existing items (status, budget, last-updated, log)
- Write files within its own item folder (`CONVERSATION.md`, `context/`, `runs/`)

So the current flow is:
1. **You** add items to WORK.md (with their RUNS.md configs for research items)
2. **The loop** picks them up and processes them
3. **The agent** updates its own files and the item's status

---

## What You're Describing: Hub-and-Spoke

You want:
```
KL-MM2H (conversation item)
  ├── KL-MM2H-AREAS (research item)
  ├── KL-MM2H-RULES (research item)
  ├── KL-MM2H-BUILDINGS (research item)
  └── KL-MM2H-COSTS (research item)
```

The conversation item is the **hub** — it frames the problem, maintains the decision framework, and synthesizes findings. The research items are **spokes** — each runs independently on a recurring schedule, updating its own `context/` file.

---

## How It Would Work Today (Without Code Changes)

**You** manually create the items in WORK.md. Then the **conversation item** (KL-MM2H) reads all the `context/` files from the research items and synthesizes them. The research items run on their own schedules, updating their own notes.

**Problem**: The conversation item can't *read* files from other item folders. It only reads its own `context/`. So it can't automatically pull in findings from the spokes.

---

## What Would Need to Change

### Option A: Shared Context Directory

All items read/write to a **shared** context directory. The conversation item and all research items share this space.
- Pros: Simple, no code changes needed
- Cons: Blurs item boundaries, potential for conflicts

### Option B: Agent Can Create Items

The conversation item's agent can write new rows to WORK.md and create RUNS.md files for research items. This is the "auto-spawning" model.
- Pros: True hub-and-spoke — the agent identifies research gaps and creates items
- Cons: Requires code changes to the loop

### Option C: Hybrid (Recommended for Now)

You create the research items manually (or with a one-time setup), and the conversation item **references** them explicitly. The conversation item doesn't read the research item files directly, but it **tracks their status** by reading WORK.md and noting which items are `needs-review` (meaning new findings are waiting for your review).

---

## My Recommendation

Start with **Option C** — it's the lowest friction and gives you 80% of the value. The workflow:

1. You create 3-4 research items in WORK.md with their RUNS.md configs
2. The loop runs them on schedule (e.g., weekly)
3. Each research item updates its own `context/` file
4. The conversation item checks WORK.md for `needs-review` items and mentions them
5. You review the research item outputs, annotate them, and feed insights back to the conversation item

When you want the agent to **auto-create** research items, that's Option B — a future enhancement.

---

## For Your KL Research Specifically

Here's what I'd suggest creating manually:

| ID | Topic | Schedule | Note Path |
|---|---|---|---|
| KL-MM2H | Master research thread | — | CONVERSATION.md |
| KL-MM2H-RULES | MM2H property rules | Weekly | `[[context/mm2h-rules]]` |
| KL-MM2H-AREAS | Area comparison | Weekly | `[[context/area-comparison]]` |
| KL-MM2H-BUILDINGS | Building shortlist | On-demand | `[[context/building-shortlist]]` |
| KL-MM2H-COSTS | Cost of living / ROI | Monthly | `[[context/cost-analysis]]` |

The first run of KL-MM2H (conversation) would:
1. Define the criteria and decision framework
2. Identify the initial source URLs for each research item
3. Tell you which areas to start comparing

Then the research items run independently, and KL-MM2H synthesizes.

---

A few questions:

1. **Do you want to try Option C first** (manual item creation, conversation item tracks status), or **build Option B** (agent can create items)?
2. **For the research items' sources** — do you already have URLs you want to track, or should the first conversation run identify them?
3. **Should the research items run on a schedule** (weekly/monthly) or only when you set them to `ready`?

---

## User

I think what would make sense to me would be enhancing the Work Loop so that each work item can spawn multiple research agents as needed. That would need changes to allow multiple RUNS.md and runs/ subfolders — one for each agent. Conceptually I think that would be a nice enhancement and generic enough. LOOP agent can create sub research agents with my permission and manage them. What do you think?

---

## Assistant

This is a solid architectural idea. Let me think through the design carefully.

---

This is a solid architectural idea. Here's my thinking on the design:

---

## File Structure

Child research agents live as subdirectories within the parent item folder:

```
{ITEM_ID}/
├── CONVERSATION.md          ← parent's conversation thread
├── background.md            ← parent's background (you own)
├── context/                 ← parent's context (shared with child agents)
│   ├── area-comparison.md
│   └── mm2h-rules.md
├── research-agents/         ← child research agents
│   ├── areas/               ← child agent 1
│   │   ├── RUNS.md          ← config (same format as top-level research items)
│   │   ├── context/         ← child's own context (optional)
│   │   └── runs/            ← run history
│   │       └── 20250719-001/
│   │           └── research.md
│   ├── rules/               ← child agent 2
│   │   ├── RUNS.md
│   │   └── runs/
│   └── buildings/           ← child agent 3
│       ├── RUNS.md
│       └── runs/
```

Each child agent has its own RUNS.md and runs/ folder. The parent agent can read/write to these folders.

---

## Loop Changes

The loop needs to:

1. **Discover child agents** — scan all item folders for `research-agents/*/RUNS.md`
2. **Process child agents** — like top-level research items, but with different paths
3. **Handle child agent scheduling** — same cron logic as top-level research items

The loop already has logic to parse RUNS.md for research items. We reuse this for child agents. For child agents, the status is tracked in the child's RUNS.md (same as top-level).

---

## Prompt Changes

**LOOP-PROMPT.md**: Add section on child research agents with instructions for:
- Proposing child agents (with RUNS.md config) for user approval
- Reading child agent results (runs/ summaries)
- Updating child agent config (sources, schedule, note_path, budget)
- Deleting child agents (propose, user approves, remove folder)
- Pausing/resuming child agents (change status)

**RESEARCH-PROMPT.md**: Add parent awareness — the agent knows its parent item and can optionally write to parent's context/.

---

## Agent Workflow

1. **Create**: Parent agent proposes child agent in CONVERSATION.md (with RUNS.md config). User approves. Agent creates `research-agents/{name}/RUNS.md`. Loop discovers and processes on next iteration.

2. **Read**: Parent agent reads child agent's runs/ summaries during its processing.

3. **Update**: Parent agent proposes updates in CONVERSATION.md. User approves. Agent modifies child RUNS.md.

4. **Delete**: Parent agent proposes deletion in CONVERSATION.md. User approves. Agent removes the folder.

5. **Pause/Resume**: Parent agent can directly update the status in child RUNS.md.

---

## Key Design Decisions

1. **Child agents are discovered by the loop** — scan all item folders for `research-agents/*/RUNS.md`. No metadata in WORK.md needed.

2. **Child agents are processed like top-level research items** — same processing logic, different paths. The loop doesn't need to know about parent-child relationships — it just processes folders.

3. **Child agents have their own budget** — specified in child RUNS.md (e.g., `budget: 3.00`). The parent agent sets the budget when creating the child.

4. **Child agents can write to parent's context/** — the note_path in child RUNS.md can point to parent's context/ (e.g., `[[../context/area-comparison]]`).

5. **Parent agents manage child agents** — create, update, delete, pause/resume. The "propose, user approve" flow for create/delete keeps the user in control.

6. **Generic** — works for any parent item type (conversation, implement, resolved). Child agents are always research type.

---

## Code Changes Summary

**run-loop.py**:
- `get_child_agents(item_id)` — scan `research-agents/` for RUNS.md files
- `get_all_items()` — returns top-level items from WORK.md + child agents
- `process_child_agent(parent_id, agent_name, budget)` — process a child agent
- Modify main loop to process child items

**LOOP-PROMPT.md**:
- Add section on child research agents
- Instructions for creating/updating/deleting child agents
- Instructions for reading child agent results

**RESEARCH-PROMPT.md**:
- Add parent awareness
- Instructions for writing to parent's context/ (optional)

---

## Edge Cases

- **Child agent fails** — Status set to `needs-review`, parent agent can see this during processing
- **Parent item deleted** — Child agents are orphaned. The loop should handle gracefully.
- **Multiple parents writing to same context/** — Shouldn't happen if the parent agent manages it properly.

---

This design is clean, generic, and gives you the hub-and-spoke model you're looking for. The parent agent proposes, you approve, the loop discovers and runs.

OK, I've analyzed the codebase thoroughly. Here's my thinking on the design:

---

## Current State

Each item has exactly **one** `RUNS.md` at `work_dir/{item_id}/RUNS.md`. The loop hardcodes this path everywhere:
- `_parse_runs_md(item_id)` → reads from fixed path
- `_append_runs_md_row(item_id, ...)` → writes to fixed path
- `_generate_run_id(item_id)` → scans fixed path
- `_create_run_dir(item_id, run_id)` → creates `runs/{run_id}/` under item dir

## Two Design Options

### Option A: Sub-agents as separate WORK.md entries (simplest)

```
KL-MM2H/
├── CONVERSATION.md          ← parent thread
├── KL-MM2H-areas/           ← sub-agent (separate item)
│   ├── CONVERSATION.md
│   ├── RUNS.md
│   └── runs/
└── KL-MM2H-rules/           ← sub-agent (separate item)
    ├── CONVERSATION.md
    ├── RUNS.md
    └── runs/
```

**Pros:**
- **Zero changes to run-loop.py** — the loop already handles research items
- Full visibility in WORK.md — user can manage sub-agents directly
- Each sub-agent is a first-class item

**Cons:**
- Sub-agents aren't visually grouped under the parent in WORK.md
- Parent agent has to create items in a sibling directory (not under its own folder)

**Changes needed:**
- `LOOP-PROMPT.md`: Add instructions for the agent to create new items in WORK.md and write RUNS.md files
- That's it. The agent already has file system access through the harness.

---

### Option B: Sub-agents nested under parent (your preference)

```
KL-MM2H/
├── CONVERSATION.md          ← parent thread
├── context/                 ← shared context
├── agents/                  ← sub-agent configs
│   ├── areas/
│   │   ├── RUNS.md
│   │   └── runs/
│   └── rules/
│       ├── RUNS.md
│       └── runs/
└── runs/                    ← parent's own runs (if it's also a research item)
```

**Pros:**
- Visually grouped under parent — matches your mental model
- Parent agent manages everything from one directory
- Shared `context/` directory for cross-referencing

**Cons:**
- Requires changes to run-loop.py to discover and process nested sub-agents
- Sub-agents aren't visible in WORK.md unless we auto-create entries

**Changes needed:**
- `run-loop.py`: Add scanning for `agents/*/RUNS.md`, modify `_parse_runs_md()` to accept a path
- `LOOP-PROMPT.md`: Add instructions for creating sub-agents
- `RESEARCH-PROMPT.md`: Add support for reading parent's `context/` directory

---

## My Recommendation: Option A (for now)

Here's why:

1. **It works today** — no run-loop.py changes needed. The parent agent just needs instructions in LOOP-PROMPT.md to:
   - Append a new row to WORK.md
   - Create the sub-agent directory and RUNS.md
   - Reference the sub-agent by ID in CONVERSATION.md

2. **Full visibility** — you see all sub-agents in WORK.md, can manage them directly, and the loop handles them normally.

3. **Parent agent reads sub-agent outputs** — the parent's CONVERSATION.md entry can reference sub-agent findings:
   ```
   ## Sub-Agent Status
   - KL-MM2H-areas: needs-review (updated area comparison with 3 new areas)
   - KL-MM2H-rules: success (no changes to MM2H thresholds)
   
   ## Synthesis
   Mont Kiara remains the top candidate based on area research...
   ```

4. **You can always add Option B later** as an enhancement if you want visual grouping.

---

## The Workflow (Option A)

```
1. Parent agent identifies a research gap
2. Proposes sub-agent in CONVERSATION.md:
   
   ## Proposed Sub-Agent
   - ID: KL-MM2H-areas-walkability
   - Topic: Walkability analysis for top 5 areas
   - Sources: Google Maps, WalkScore, local forums
   - Schedule: Weekly
   - Output: [[context/area-walkability]]
   
   ## Questions
   - Should I create this sub-agent?

3. You respond: "Oliver: Yes, create it."

4. Parent agent:
   - Appends row to WORK.md: `| KL-MM2H-areas-walkability | Walkability analysis | local | research |`
   - Creates KL-MM2H-areas-walkability/RUNS.md with config
   - Creates KL-MM2H-areas-walkability/CONVERSATION.md

5. Loop picks up KL-MM2H-areas-walkability as a research item
6. Sub-agent runs, updates its context/ files
7. Parent agent reads sub-agent outputs and synthesizes in its CONVERSATION.md
```

---

## Key Questions

1. **Option A (separate WORK.md entries) or Option B (nested under parent)?** Option A is simpler and works today. Option B matches your mental model but needs run-loop.py changes.

2. **Should sub-agents write to a shared `context/` directory or their own?** With Option A, each sub-agent has its own `context/`. The parent reads from all of them. With Option B, they could share the parent's `context/`.

3. **Should the parent agent auto-create sub-agents, or propose them for your approval?** I'd recommend propose-then-create (as shown in the workflow above) so you maintain control.

What do you think?

---

## User

A couple of comments on Option A: 
- I don't think that folder structure with a parent work item exsists today and would require code changes. 
- Each sub-agent would have its own CONVERSATIION.md. It might be more flexible but might get confusing with multiple sub-threads going on.
- WORK.md table might be getting messy with all subagents. In future we may have many work items each with their own sub agents. 
