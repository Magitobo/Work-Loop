# Work Loop

## How to use

### How to Dispatch Work
- **Inside Note (Recommended):** Inside `CONVERSATION.md`, check the box in the Action Center callout (`[x] Continue Analyze`, `[x] Run Implement`, etc.).
- **From this Dashboard:** Change the `Status` column directly to `ready/analyze` or `implement` (requires `work_dir: <path>` in `CONVERSATION.md`)
- **Add New Item:** Add instructions under **Add New Item** and check the box [X]. The loop creates the folder, seeds CONVERSATION.md, and begins analysis.

### Child Agents & Research
- **Research items:** Set status to `scheduled`/`ready`, use `RUNS.md` with `type: research`, `topic:`, `note_path:`, `sources:` list, optional `schedule:` cron. Agent fetches sources, updates the note, writes per-run summary.
- **Script items:** Use `RUNS.md` with `command:`, optional `schedule:`, `locations:` for multi-machine, `analysis_prompt:` for AI fan-in.
- **Verified research:** During an `analyze` run, tell the agent "research [question]" — it spawns the verified-research sub-agent with multi-angle search, claim extraction, and confidence ratings.
- **Child agents:** During an `analyze` run, the agent can propose child agents (propose/approve workflow). Two types: `research` (fetches web sources, updates notes) and `task` (scans local files, proposes actions). Managed in `WORK-CHILDREN.md`.

## Add New Item
- [ ] _Add new instructions here and click the check box [X] when done. The loop creates the folder, seeds CONVERSATION.md, and moves it to Active Items_

## Active Items

| Task / Conversation | Status | Last Updated | Log | ID |
| ------------------- | :----: | :----------: | :-: | -- |

## Done

| Task / Conversation | Last Updated | Log | ID |
| ------------------- | :----------: | :-: | -- |
