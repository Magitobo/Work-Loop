# TODO

## Open

- [ ] **Separate llama-swap model instances for Work-Loop vs. interactive chat.**
  Work-Loop uses `llama-swap/mlx/Qwen3.8-27B-6bit-thinking` (changed 2026-09-29) and interactive OpenCode sessions default to `llama-swap/mlx/Qwen3.8-27B-6bit`. The thinking model is only an alias of the same llama-swap model, so both share one instance. Sharing it means the loop's prompt-cache churn can evict the chat session's KV cache.
  - Define two explicitly named instances in the llama-swap config on mac-studio (e.g. `mlx/Qwen3.8-27B-6bit-workloop` and `mlx/Qwen3.8-27B-6bit-chat`), and check both fit in unified memory at the same time.
  - Point `harness.model` in `config.json` at the Work-Loop instance, and the default in `opencode.json` at the chat instance.

- [ ] **Align code and config names with the user-facing terms (parked 2026-09-25).**
  The docs (`README.md`, `docs/TUTORIAL.md`, `templates/WORK.md`) now say *thread* and *routine*: track sources / scan files / run command, either standalone or attached. The code still uses the older names; see the glossary in `AGENTS.md`. Accept every old name as an alias so existing vaults keep working.
  - Put all routine kinds under one `RUNS.md` key, e.g. `kind: track | scan | command`. It would replace `type: research`, `type: task`, and the rule that a `command:` line makes a script item. `get_item_type()` and `process_child` would read it.
  - Rename the prompts to match: `UPDATE-RESEARCH-PROMPT.md` → `TRACK-SOURCES-PROMPT.md`, `TASK-PROMPT.md` → `SCAN-FILES-PROMPT.md`.
  - Rename *children* to attached routines in code and files, e.g. `WORK-CHILDREN.md` → `ROUTINES.md`. Update the LOOP-PROMPT Step 6 wording ("child agent") to match.
  - Let scan-files routines run standalone as well, not only attached.
  - Merge the `ready` / `analyze` synonyms into one status. Also use one word each for "running" (`in-progress` vs `running`) and "finished" (`success` vs `done`) across threads and routines.
  - Add a **Verified Research** checkbox to the thread Action Center, so it doesn't depend on phrasing the request in the reply.
