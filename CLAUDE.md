# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

@AGENTS.md

`AGENTS.md` (imported above) is the canonical project overview: directory layout, WORK.md schema, status state machines, item types, scaffolding, subagents, and harness config. `README.md` is the end-user guide. The notes below cover what those files don't.

## Commands

Run tests with system `python3` (pytest is not installed in `venv/`); `ruff` lives in `venv/bin/`.

```bash
python3 -m pytest tests/ -v                          # unit suite (test_e2e.py is auto-ignored)
python3 -m pytest tests/test_core.py -v              # one file
python3 -m pytest tests/test_core.py -k "move_done"  # one test / pattern
ENABLE_E2E_TESTS=1 python3 -m pytest tests/test_e2e.py -v   # e2e, runs the real harness
venv/bin/ruff check .                                         # lint
python3 run-loop.py                                           # run the loop (needs config.json)
python3 run-loop.py --init-vault "/path/to/Vault"             # scaffold a vault and exit
```

`conftest.py` controls e2e behavior: `tests/test_e2e.py` is in `collect_ignore` unless `ENABLE_E2E_TESTS` is set. With `ENABLE_BACKGROUND_E2E=1`, the e2e suite is spawned detached after the unit run (state in `e2e_state.json`, output in `e2e_results.log`), and its results are reported at the top of the *next* pytest run.

## Code architecture

- `WorkLoop` (`workloop/core.py`) is composed from mixins: `OutlineMixin` (outline.py), `ChildrenMixin` (children.py), `ScriptsMixin` (scripts.py), `RemoteMixin` (remote.py), `DashboardMixin` (dashboard.py). Mixins share state and helpers through `self`, so a method called in one file is often defined in another. Grep across `workloop/` before assuming a helper is missing.
- `WorkLoop.run()` is the main iteration loop; `process_local()` and the remote mixin handle per-item dispatch. `harness.py` holds the `Harness` ABC with `ClaudeHarness` / `OpenCodeHarness`, which build the CLI invocation, check cost afterwards, and clean up.
- WORK.md is parsed in two formats. The modern outline format (`## Active Items` / `## Done` sections) goes through `OutlineMixin` (`_is_outline_format`, `_parse_outline_blocks`). The legacy single pipe table is addressed by column index constants in `workloop/constants.py` (`COL_*` for WORK.md, `RUNS_COL_*` for RUNS.md, `CH_*` for WORK-CHILDREN.md). Many methods branch on `_is_outline_format()`, so changes to row reading or writing usually need to handle both.
- `run-loop.py` is a thin shim. It loads config via `workloop/config.py`, handles `--init-vault`, and constructs `WorkLoop`.
- Prompts in `prompts/` and agent definitions in `.claude/agents/` and `.opencode/agents/` are product code, not dev config: they are synced into the target vault or remote host at runtime. `{{templates/FILE.md#N}}` anchors inside them are resolved by `workloop/scaffold.py`, so edit the source in `templates/` rather than duplicating text into agent files.
- `config.json` is gitignored and machine-specific; `config-example.json` is the template.
