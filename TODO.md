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

- [ ] **Consider replacing `work_dir:` with an `add_dir:` concept (noted 2026-09-30).**
  Today `work_dir:` in an item's `CONVERSATION.md` moves the harness start directory to another repo, and only in implement mode. The run then treats that repo as the project and the vault as an external directory, so it can't reach its own `CONVERSATION.md` and context files without a permission. `external_directory: allow` was removed from all OpenCode configs on 2026-09-30, and Work-Loop development is now interactive-only. So `work_dir:` items would currently prompt or fail.
  - Keep every run starting in the vault, and let an item list extra directories it may use (`add_dir: <path>`, like Claude Code's `--add-dir`). Apply it in every mode, not only implement.
  - OpenCode: grant each listed path per run, e.g. an `external_directory` allow rule injected via `OPENCODE_CONFIG_CONTENT`; check that this is supported. Claude: pass `--add-dir`.
  - Side benefit: the agent sync would no longer write the loop's agents into the target repo's `.opencode/agents/`.
