# Configurable repo for OpenCode, Claude, Work_Dir

**Session ID:** ses_0971c3e5cffe3b0QcrCNndLLua
**Created:** 7/15/2026, 11:06:24 PM
**Updated:** 7/15/2026, 11:59:04 PM

---

## User

The repo was developed on another Linux machine and copied here to Mac. It was designed to work with Claude and with other assumptions. I would like to make it configurable so that it can:
- work with other harnesses, in particular OpenCode and Claude
- Work_Dir is configurable
- Remove Kerberos entirely
- Keep eveything else
Come up with a detailed implementation plan. Ask me any clarifying questions. 

---

**Behavioral differences — `claude --print` vs `opencode run`:**

|             | Claude                            | OpenCode                                                        |
| ----------- | --------------------------------- | --------------------------------------------------------------- |
| Output      | Raw text to stdout                | Formatted text by default; `--format json` for machine-readable |
| Session     | None                              | Creates a persistent session (must be cleaned up)               |
| Budget      | Hard limit via `--max-budget-usd` | No flag — must check `opencode stats` post-run                  |
| Permissions | `--permission-mode auto`          | `--auto`                                                        |
| Working dir | `subprocess.Popen(cwd=...)`       | `--dir <path>`                                                  |
| Model       | Global CLI config                 | `--model provider/model`                                        |
| Debug       | `--debug-file`                    | None                                                            |
| Subagents   | `.claude/agents/*.md`             | `.opencode/agents/*.md`                                         |
| MCP         | None by default                   | Reads from `opencode.json`                                      |

---

Here's the detailed implementation plan:

## Implementation Plan: Harness-Agnostic Work-Loop

### 1. New file: `Work-Loop-Items/config.json`

```jsonc
{
  "work_dir": "/absolute/path/to/Work-Loop-Items",
  "harness": {
    "type": "claude",          // "claude" | "opencode"
    "model": "anthropic/claude-sonnet-4-5",  // for opencode; ignored for claude
    "max_budget_usd": 10.00
  },
  "remote": {
    "work_dir": "~/Work-Loop"
  }
}
```

### 2. `run-loop.py` changes

**2a. Config loading**
- Add `load_config(config_path: Path) -> dict` — reads `config.json`, validates required keys, fails fast with clear error if missing/invalid
- `WorkLoop.__init__` takes `config: dict` instead of individual params
- `main()` discovers `SCRIPT_DIR`, looks for `config.json` in `work_dir`, loads it, passes to `WorkLoop`

**2b. Harness abstraction**
- New `Harness` base class with `run(prompt, budget, cwd, item_id) -> int` and `launcher_script(...)` methods
- `ClaudeHarness(Harness)` — current `run_claude()` + `build_launcher()` logic
- `OpenCodeHarness(Harness)` — new implementation:
  - `run()`: `opencode run --auto --format json --title <item_id> --dir <cwd> "<prompt>"`
  - Budget check: post-run `opencode stats --project <item_id>` to get cost, compare to budget
  - Session cleanup: `opencode session list` to find and delete the session
  - `launcher_script()`: generates `nohup opencode run ... &` script for remote dispatch

**2c. Remove Kerberos**
- Delete `_remote_has_kerberos()` method
- Delete `_remote_has_kerberos` check in `run()` (the `kerberos_ok` dict and blocking logic)
- Delete `_remote_has_kerberos` check in `process_script_item()`
- Remove `"apikeyHelper failed"`, `"no valid kerberos"` from `_classify_failure()`
- Remove `AUTH-EXPIRED` budget labels and related code paths
- Update `prepend_abort_notice` to not reference Kerberos

**2d. Harness-aware prompt loading**
- `process_local()` and `dispatch_remote()` select prompt files based on harness type
- For OpenCode, the prompts should reference `.opencode/agents/` instead of `.claude/agents/` for subagent invocations
- The prompts themselves (`LOOP-PROMPT.md`, `IMPL-PROMPT.md`, `RESOLVE-PROMPT.md`) stay as-is since `subagent_type="critic"` works identically in both CLIs

**2e. Remote dispatch harness selection**
- `dispatch_remote()` reads harness type from config
- Syncs `.opencode/` instead of `.claude/` for OpenCode remote dispatch
- `build_launcher()` generates harness-specific bash scripts

**2f. Cost injection**
- `_inject_session_cost()` stays Claude-only (uses `ccusage`)
- For OpenCode, add `_inject_opencode_cost()` that uses `opencode stats` / `opencode export`

### 3. Prompt files

- `LOOP-PROMPT.md`, `IMPL-PROMPT.md`, `RESOLVE-PROMPT.md` — keep as-is (subagent mechanism is identical)
- Optionally create `LOOP-PROMPT-OPENCODE.md` etc. if OpenCode needs different agent references (but based on research, `subagent_type` works the same)

### 4. Test updates (`test_run_loop.py`)

- Update `_remote_has_kerberos` mocks to no-ops (or remove tests that depend on it)
- Add `TestClaudeHarness` and `TestOpenCodeHarness` unit tests
- Add `TestConfigLoading` tests (valid config, missing file, invalid JSON, missing required keys)
- Update existing tests that mock `_remote_has_kerberos`
- Add tests for harness selection in `process_local()` and `dispatch_remote()`

### 5. Files to create

- `Work-Loop-Items/config.json` (example template)
- `config.json.example` in repo root (for reference)

### 6. Files to modify

- `run-loop.py` — all changes above
- `test_run_loop.py` — all test updates above

### 7. Execution order

1. Config loading + validation (new code, no existing behavior affected)
2. Harness abstraction (refactor existing `run_claude`/`build_launcher` into `ClaudeHarness`)
3. OpenCode harness implementation
4. Kerberos removal
5. Harness-aware prompt/agent file selection
6. Cost injection updates
7. Test updates

### Key design decisions

- **Config is required, no defaults** — loop exits immediately with error if `config.json` is missing
- **SCRIPT_DIR auto-discovery** — `main()` resolves `SCRIPT_DIR` from `__file__`, looks for `config.json` in `work_dir`
- **Backward compat for prompts** — `subagent_type` works in both CLIs, so prompts don't need changes
- **OpenCode session cleanup** — the loop must track and delete sessions to avoid accumulation
- **Budget enforcement for OpenCode** — post-run check via `opencode stats`, less precise but acceptable per your answer

---

