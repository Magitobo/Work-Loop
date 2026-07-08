## Remote Dispatch
### Pre-requisite
Add your public ssh key to authorized_keys file on the remote
### Dispatch
When a work item's Location is set to a remote host (e.g. xgemuadm@tgleh-ublts-08) instead of local, the loop handles it like this.
  1. Wipes ~/Work-Loop on the remote (cleans up any previous aborted run)
  2. Rsyncs the item folder, LOOP-PROMPT.md, and .claude/settings.json to the remote
  3. Writes a minimal stub WORK.md so Claude can update the item's status when it finishes
  4. Uploads and launches a bash script via nohup — Claude runs detached, survives SSH disconnect
### Polling
  The local loop SSH-polls {item_id}/.done every 5 seconds. The remote launcher writes the Claude exit code there when it finishes.
### Sync-back
  Once .done appears, the loop rsyncs the item folder back (picks up Claude's changes to CONVERSATION.md etc.), copies the log, then wipes the entire
  ~/Work-Loop on the remote. Local WORK.md is updated with date, budget, and status.
### Key properties
  - The remote folder only exists while a job is actively running — no stale state
  - LOOP-PROMPT.md and .claude/settings.json are always synced fresh; nothing needs to be pre-installed on the remote beyond Claude itself
  - If the local loop crashes mid-job, the remote Claude keeps running; the next dispatch to that host wipes and starts clean
