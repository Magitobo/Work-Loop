# Work Loop

## How to use
New to Work-Loop? See the Tutorial (`docs/TUTORIAL.md` in the Work-Loop repo).

- **Start a thread:** write your request under **Add New Item** and tick the box. The loop creates the folder and `CONVERSATION.md`, and the agent replies at the top of that note.
- **Your turn:** `needs-review` means the agent is waiting for you. Add a `## YYYY-MM-DD | User` entry at the top of the thread, then tick **Continue Analyze**.
- **Action Center** (top of every thread): *Continue Analyze* runs another analysis round. *Run Implement* makes the agent act; it needs a `work_dir: <path>` line in the thread. *Mark Resolved* writes a summary and moves the row to Done. *Abort* stops the run.
- **Verified research:** in a thread, ask *"Do verified research on X"* or *"Compile what we found into a verified research note"*. The result goes to `03 Verified Research/` after you review it.
- **Attached routines:** ask a thread to repeat something, e.g. *"check these sites every Monday"* or *"suggest where inbox notes should go each morning"*. The agent proposes a routine, you approve it, and its report link appears under the thread.
- **Standalone routines:** create `<ID>/RUNS.md` yourself and add a row here. Use `type: research` + `sources:` to keep a note updated from the web (status `research`), or `command:` to run a shell command on machines (status `ready` or `scheduled`).
- **Needs Attention** (managed by the loop) lists everything waiting for you.

## Add New Item
- [ ] _Add new instructions here and click the check box [X] when done. The loop creates the folder, seeds CONVERSATION.md, and moves it to Active Items_

## Active Items

| Task / Conversation | Status | Last Updated | Log | ID |
| ------------------- | :----: | :----------: | :-: | -- |

## Done

| Task / Conversation | Last Updated | Log | ID |
| ------------------- | :----------: | :-: | -- |
