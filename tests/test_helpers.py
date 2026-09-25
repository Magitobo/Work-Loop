#!/usr/bin/env python3
"""Tests for run-loop.py — unit tests and optional remote integration test."""

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

# ---------------------------------------------------------------------------
# Import run-loop.py (hyphen in name prevents normal import)
# ---------------------------------------------------------------------------

_HERE = Path(__file__).parent.parent
_PROMPTS_DIR = _HERE / "prompts" if (_HERE / "prompts").is_dir() else _HERE
_MOD_PATH = _HERE / "run-loop.py"

spec = importlib.util.spec_from_file_location("run_loop", _MOD_PATH)
run_loop = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run_loop)

WorkLoop = run_loop.WorkLoop
COL_ID = run_loop.COL_ID
COL_TITLE = run_loop.COL_TITLE
COL_STATUS = run_loop.COL_STATUS
COL_LOCATION = run_loop.COL_LOCATION
COL_BUDGET = run_loop.COL_BUDGET
COL_LOG = run_loop.COL_LOG
COL_LAST_UPDATED = run_loop.COL_LAST_UPDATED

# ---------------------------------------------------------------------------
# Remote availability check
# ---------------------------------------------------------------------------

REMOTE_HOST = "xgemuadm@tgleh-ublts-08"
REAL_WORK_DIR = _HERE


def _can_reach_remote(host: str) -> bool:
    try:
        result = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes", host, "true"],
            capture_output=True, timeout=10,
        )
        return result.returncode == 0
    except Exception:
        return False


REMOTE_AVAILABLE = _can_reach_remote(REMOTE_HOST)

# ---------------------------------------------------------------------------
# WORK.md Table Header and Fixtures
# ---------------------------------------------------------------------------

TABLE_HEADER = (
    "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
    "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
)


def make_work_md(active_rows: str = "", done_rows: str = "") -> str:
    """Helper to build a standard WORK.md string with active and done sections."""
    active_section = f"{active_rows}\n" if active_rows and not active_rows.endswith("\n") else active_rows
    done_section = f"{done_rows}\n" if done_rows and not done_rows.endswith("\n") else done_rows
    return (
        f"# Work Loop\n\n"
        f"{TABLE_HEADER}"
        f"{active_section}\n"
        f"## Done\n\n"
        f"{TABLE_HEADER}"
        f"{done_section}"
    )


SAMPLE_WORK_MD = """\
# Work Loop

<!-- Status values: waiting | ready | in-progress | needs-review | blocked | done -->

| ID         | Title                      | Location | Status       | Last Updated | Budget | Log |
| ---------- | -------------------------- | -------- | ------------ | ------------ | ------ | --- |
| ITEM-001   | [Task one](ITEM-001/C.md)  | local    | ready        |              |        |     |
| ITEM-002   | [Task two](ITEM-002/C.md)  | local    | needs-review | 2026-05-10   | $10.00 |     |
| ITEM-003   | [Task three](ITEM-003/C.md)| local    | waiting      |              |        |     |
| ITEM-004   | [Task four](ITEM-004/C.md) | local    | done         |              |        |     |

## Done

| ID         | Title                      | Location | Status | Last Updated | Budget | Log |
| ---------- | -------------------------- | -------- | ------ | ------------ | ------ | --- |
| ITEM-000   | [Old task](ITEM-000/C.md)  | local    | done   | 2026-05-01   | $5.00  |     |
"""


def _make_workloop(tmp_dir: str, content: str = SAMPLE_WORK_MD) -> WorkLoop:
    p = Path(tmp_dir)
    (p / "WORK.md").write_text(content)
    (p / "LOOP-PROMPT.md").write_text("Do the work.\n")
    cfg = {"work_dir": p, "harness": {"type": "claude", "max_budget_usd": 10.00}, "remote": {"work_dir": "~/Work-Loop"}}
    return WorkLoop(cfg)


# ---------------------------------------------------------------------------
# TestWorkTable
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# TestLauncherScript
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# TestLauncherScriptImplementMode
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# TestDispatchRemoteMode
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# TestRunModeRouting
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# TestPrependAbortNotice
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# TestTriggerStatuses
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# TestExtractWorkDir
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# TestStubWorkMd
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# TestLoopPromptPortability
# ---------------------------------------------------------------------------





# ---------------------------------------------------------------------------
# TestGetInprogressRemoteItems
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# TestTsStrFromLogCol
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# TestClassifyFailure
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# TestSyncBackRemote
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# TestCheckStalledRemotes
# ---------------------------------------------------------------------------





# ---------------------------------------------------------------------------
# TestRemoteDispatch (integration — skipped if remote unreachable)
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# TestResolvedModeTrigger
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# TestLauncherScriptResolvedMode
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# TestLauncherDebugFile
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# TestDispatchRemoteResolvedMode
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# TestMoveRowToDone
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# TestProcessLocalResolvedMode
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# TestTsStrFromLogColDebug
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# Script item constants
# ---------------------------------------------------------------------------

RUNS_COL_ID = run_loop.RUNS_COL_ID
RUNS_COL_STATUS = run_loop.RUNS_COL_STATUS
DEFAULT_TIMEOUT_MIN = run_loop.DEFAULT_TIMEOUT_MIN
POLL_CYCLES_PER_MIN = run_loop.POLL_CYCLES_PER_MIN

# ---------------------------------------------------------------------------
# Helpers for script item tests
# ---------------------------------------------------------------------------

_SCRIPT_WORK_MD = """\
# Work Loop

| ID | Title / Initial Prompt | Location | Status | Last Updated | Budget | Log |
| -- | --------------------- | -------- | ------ | ------------ | ------ | --- |
| SI-001 | [Script item one](SI-001/CONVERSATION.md) | local | new | | | |
| CONV-001 | [Conversation item](CONV-001/CONVERSATION.md) | local | new | | | |

## Done

| ID | Title / Initial Prompt | Location | Status | Last Updated | Budget | Log |
| -- | --------------------- | -------- | ------ | ------------ | ------ | --- |
"""

_SINGLE_LOC_RUNS_MD = """\
## Config

Command: bash test_fixtures/stub_test.sh
Params: --arg1
Location: linux:user@host1
Heartbeat File: run.log
Timeout: 4
Aggregation Script: test_fixtures/stub_aggregate.py
Analysis Prompt: Analyze {run-id} results in runs/{run-id}/
"""

_MULTI_LOC_RUNS_MD = """\
## Config

Command: bash test_fixtures/stub_test.sh
Params:
Locations:
  linux:user@host1
  linux:user@host2
  win:user@winhost
Heartbeat File: run.log
Timeout: 4
"""

_SCHEDULED_RUNS_MD = """\
## Config

Command: bash test_fixtures/stub_test.sh
Schedule: 30 9 * * 1-5
Location: linux:user@host1
"""


def _make_script_item(tmp_dir: str, item_id: str, runs_md_content: str, work_md: str = _SCRIPT_WORK_MD) -> WorkLoop:
    p = Path(tmp_dir)
    (p / "WORK.md").write_text(work_md)
    (p / "LOOP-PROMPT.md").write_text("Do the work.\n")
    item_dir = p / item_id
    item_dir.mkdir(parents=True, exist_ok=True)
    (item_dir / "RUNS.md").write_text(runs_md_content)
    cfg = {"work_dir": p, "harness": {"type": "claude", "max_budget_usd": 10.00}, "remote": {"work_dir": "~/Work-Loop"}}
    return WorkLoop(cfg)


# ---------------------------------------------------------------------------
# TestGetItemType
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# TestParseRunsMdConfig
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# TestCronShouldRun
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# TestGenerateRunId
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# TestParseLocation
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# TestRsyncCmdForHost
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# TestAppendRunsMdRow
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# TestUpdateRunsMdRowStatus
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# TestRunStateReadWrite
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# TestBuildTestDispatchScript
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# TestInitializeNewItemScriptItem
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# TestAggregationScript
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# TestPollMachineOnce
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# TestFindLatestRunsMdRun
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# TestAbortHandling
# ---------------------------------------------------------------------------







# ---------------------------------------------------------------------------
# TestResearchItemType
# ---------------------------------------------------------------------------

_RESEARCH_RUNS_MD = """\
## Config
type: research
title: AI Security
note_path: [[AI Security]]
sources:
  https://arxiv.org/list/cs.CR/recent
  https://openai.com/blog
schedule: 0 6 * * 1
timeout: 10

## Prompt
Focus on: model vulnerabilities, alignment failures, supply chain risks
Exclude: consumer AI apps, chatbot features
Key papers to watch: [[AI Security/Papers]]

## Run History

| ID | Summary | Status | Last Updated |
|---|---|---|---|
"""

_RESEARCH_WORK_MD = """\
# Work Loop

| ID | Title / Initial Prompt | Location | Status | Last Updated | Budget | Log |
| -- | --------------------- | -------- | ------ | ------------ | ------ | --- |
| RES-001 | [AI Security Research](RES-001/CONVERSATION.md) | local | new | | | |

## Done

| ID | Title / Initial Prompt | Location | Status | Last Updated | Budget | Log |
| -- | --------------------- | -------- | ------ | ------------ | ------ | --- |
"""


def _make_research_item(tmp_dir: str, item_id: str, runs_md_content: str, work_md: str = _RESEARCH_WORK_MD) -> WorkLoop:
    p = Path(tmp_dir)
    (p / "WORK.md").write_text(work_md)
    (p / "LOOP-PROMPT.md").write_text("Do the work.\n")
    item_dir = p / item_id
    item_dir.mkdir(parents=True, exist_ok=True)
    (item_dir / "RUNS.md").write_text(runs_md_content)
    cfg = {"work_dir": p, "harness": {"type": "claude", "max_budget_usd": 10.00}, "remote": {"work_dir": "~/Work-Loop"}}
    return WorkLoop(cfg)


















# ---------------------------------------------------------------------------
# Child agent constants
# ---------------------------------------------------------------------------

CH_ID = run_loop.CH_ID
CH_TITLE = run_loop.CH_TITLE
CH_STATUS = run_loop.CH_STATUS
CH_LAST_UPDATED = run_loop.CH_LAST_UPDATED
CH_BUDGET = run_loop.CH_BUDGET
CH_LOG = run_loop.CH_LOG


def _make_parent_with_children(tmp_dir: str, parent_id: str, children: list[dict]) -> WorkLoop:
    """Create a parent item with WORK-CHILDREN.md and child agent directories.

    Each child dict should have: name, runs_md, status, budget (optional).
    """
    p = Path(tmp_dir)
    work_md = (
        "# Work Loop\n\n"
        "| ID | Title / Initial Prompt | Location | Status | Last Updated | Budget | Log |\n"
        "| -- | --------------------- | -------- | ------ | ------------ | ------ | --- |\n"
        f"| {parent_id} | [Parent item]({parent_id}/CONVERSATION.md) | local | ready | | | |\n\n"
        "## Done\n\n"
        "| ID | Title / Initial Prompt | Location | Status | Last Updated | Budget | Log |\n"
        "| -- | --------------------- | -------- | ------ | ------------ | ------ | --- |\n"
    )
    (p / "WORK.md").write_text(work_md)
    (p / "LOOP-PROMPT.md").write_text("Do the work.\n")
    (p / "UPDATE-RESEARCH-PROMPT.md").write_text("Research prompt.\n")
    (p / "_logs").mkdir(exist_ok=True)

    parent_dir = p / parent_id
    parent_dir.mkdir(parents=True, exist_ok=True)
    (parent_dir / "CONVERSATION.md").write_text(f"## 2026-01-01 | User\n\nParent item: research\n")

    # Build WORK-CHILDREN.md
    children_lines = [
        "# Child Agents\n",
        "",
        "| ID | Title | Status | Last Updated | Budget | Log |",
        "|---|---|---|---|---|---|",
    ]
    for ch in children:
        title = ch.get('runs_md', '').split('\n')
        title_line = next((l for l in title if l.startswith('title:')), ch['name'])
        title_val = title_line.split(':', 1)[1].strip() if ':' in title_line else ch['name']
        budget = ch.get('budget', '')
        children_lines.append(
            f"| {ch['name']} | [{title_val}](children/{ch['name']}/RUNS.md) | {ch['status']} |  | {budget} |  |"
        )
    children_lines.append("")
    (parent_dir / "WORK-CHILDREN.md").write_text('\n'.join(children_lines))

    # Create child directories and RUNS.md
    children_dir = parent_dir / "children"
    for ch in children:
        child_dir = children_dir / ch['name']
        child_dir.mkdir(parents=True, exist_ok=True)
        (child_dir / "RUNS.md").write_text(ch['runs_md'])
        (child_dir / "runs").mkdir(parents=True, exist_ok=True)

    cfg = {"work_dir": p, "harness": {"type": "claude", "max_budget_usd": 10.00}, "remote": {"work_dir": "~/Work-Loop"}}
    return WorkLoop(cfg)


_CHILD_RUNS_MD = """\
## Config
type: research
parent: PARENT-001
title: Area walkability
note_path: ../context/area-walkability.md
sources:
  https://www.walkscore.com
schedule: 0 */6 * * *

## Prompt
Evaluate walkability for KL neighborhoods.

## Run History

| ID | Summary | Status | Last Updated | Log |
|---|---|---|---|---|
"""




























_CHILD_TASK_RUNS_MD = """\
## Config
type: task
parent: PARENT-001
title: Inbox cleanup
note_path: ../context/inbox-suggestions.md
schedule: 0 8 * * *

## Prompt
Scan the 00 Inbox folder. Suggest folder moves.

## Run History

| ID | Summary | Status | Last Updated | Log |
|---|---|---|---|---|
"""












# ---------------------------------------------------------------------------
# JSON Log Parser & Unit Tests
# ---------------------------------------------------------------------------

class JsonLogParser:
    """Parse opencode JSON-format logs and extract tool call sequences."""

    def __init__(self, log_path: Path):
        self.events: list[dict] = []
        self.raw = log_path.read_text()
        for line in self.raw.split("\n"):
            line = re.sub(r"\x1b\[[0-9;]*m", "", line).strip()
            if not line or not line.startswith("{"):
                continue
            try:
                self.events.append(json.loads(line))
            except json.JSONDecodeError:
                pass

    def tool_calls(self) -> list[dict]:
        """Return all tool_use events with tool name, args, and status."""
        result = []
        for e in self.events:
            if e.get("type") != "tool_use":
                continue
            part = e.get("part", {})
            state = part.get("state", {})
            result.append({
                "tool": part.get("tool", ""),
                "input": state.get("input", {}),
                "status": state.get("status", ""),
            })
        return result

    def has_subagent_spawn(self, subagent_type: str) -> bool:
        """Check if a task tool call spawned the given subagent."""
        return any(
            c["tool"] == "task"
            and c["input"].get("subagent_type") == subagent_type
            for c in self.tool_calls()
        )

    def has_no_subagent_spawn(self) -> bool:
        """Check that no task tool calls were made."""
        return not any(c["tool"] == "task" for c in self.tool_calls())

    def has_file_edit(self, path_suffix: str) -> bool:
        """Check if a file matching suffix was edited or written."""
        for c in self.tool_calls():
            if c["tool"] not in ("edit", "write"):
                continue
            fp = c["input"].get("filePath") or c["input"].get("file_path", "")
            if path_suffix in fp:
                return True
        return False

    def has_read(self, path_suffix: str) -> bool:
        """Check if a file matching suffix was read."""
        for c in self.tool_calls():
            if c["tool"] != "read":
                continue
            fp = c["input"].get("filePath") or c["input"].get("file_path", "")
            if path_suffix in fp:
                return True
        return False

    def has_webfetch(self, url_prefix: str) -> bool:
        """Check if a webfetch call targeted the given URL prefix."""
        return any(
            c["tool"] == "webfetch"
            and c["input"].get("url", "").startswith(url_prefix)
            for c in self.tool_calls()
        )

    def has_file_write_to(self, path_suffix: str) -> bool:
        """Check if a write (not edit) was made to a path matching suffix."""
        for c in self.tool_calls():
            if c["tool"] != "write":
                continue
            fp = c["input"].get("filePath") or c["input"].get("file_path", "")
            if path_suffix in fp:
                return True
        return False

    def has_step_stop(self) -> bool:
        """Final step_finish has reason='stop'."""
        finishes = [e for e in self.events if e.get("type") == "step_finish"]
        return finishes and finishes[-1]["part"].get("reason") == "stop"

    def total_tool_calls(self) -> int:
        return len(self.tool_calls())

    def get_tool_names(self) -> list[str]:
        return [c["tool"] for c in self.tool_calls()]









# ---------------------------------------------------------------------------
# TestOutlineWorkFormat & TestInNoteActionCenter
# ---------------------------------------------------------------------------

SAMPLE_WORK_NEW_MD = """\
# Work Loop

## How to use

### Status Values
- `ready` / `analyze` — Analysis agent
- `implement` — Implementation agent
- `resolved` — Summarizes final problem and resolution
- `abort` — Kills running job immediately

## Active Items

- [ ] [Task one](ITEM-001/CONVERSATION.md) · `status: ready` · [Log](ITEM-001/_logs/log1.log) · `ITEM-001`
- [ ] [Task two](ITEM-002/CONVERSATION.md) · `status: needs-review` · [Log](ITEM-002/_logs/log2.log) · `ITEM-002`
- [ ] [Task three](ITEM-003/CONVERSATION.md) · `status: waiting` · `ITEM-003`

## Add New Item
- [ ] Explore Canadian banking options

## Done

- [x] [Old task](ITEM-000/CONVERSATION.md) · [Log](ITEM-000/_logs/old.log) · `ITEM-000`
"""


# Streamlined table format (the shipped templates/WORK.md layout): column order
# differs from the legacy COL_* indices, so scanners must go through the
# format-aware parser.
SAMPLE_STREAMLINED_WORK_MD = """\
# Work Loop

## How to use

### Status Values
- ready / analyze — Analysis agent
- implement — Implementation agent
- resolved — Summarizes final problem and resolution

## Active Items

| Task / Conversation | Status | Last Updated | Log | ID |
|---|:---:|:---:|:---:|---|
| [Task one](ITEM-001/CONVERSATION.md) | ready | 2026-08-01 | [Log](ITEM-001/_logs/log1.log) | ITEM-001 |
| [Task two](ITEM-002/CONVERSATION.md) | needs-review | 2026-08-02 | [Log](ITEM-002/_logs/log2.log) | ITEM-002 |

## Add New Item
- [ ] Explore Canadian banking options

## Done

| Task / Conversation | Last Updated | Log | ID |
|---|:---:|:---:|---|
| [Old task](ITEM-000/CONVERSATION.md) | 2026-07-14 | [Log](ITEM-000/_logs/old.log) | ITEM-000 |
"""


_STREAMLINED_SCRIPT_WORK_MD = """\
# Work Loop

## Active Items

| Task / Conversation | Status | Last Updated | Log | ID |
|---|:---:|:---:|:---:|---|
| [Scheduled script](SI-001/RUNS.md) | scheduled | 2026-08-01 |  | SI-001 |
| [Running script](SI-002/RUNS.md) | running | 2026-08-01 |  | SI-002 |
| [Conversation](CONV-001/CONVERSATION.md) | scheduled | 2026-08-01 |  | CONV-001 |

## Done

| Task / Conversation | Last Updated | Log | ID |
|---|:---:|:---:|---|
| [Old script](SI-000/RUNS.md) | 2026-07-01 |  | SI-000 |
"""








if __name__ == "__main__":
    unittest.main(verbosity=2)



__all__ = ['JsonLogParser', '_HERE', '_PROMPTS_DIR', '_MOD_PATH', 'spec', 'run_loop', 'WorkLoop', 'COL_ID', 'COL_TITLE', 'COL_STATUS', 'COL_LOCATION', 'COL_BUDGET', 'COL_LOG', 'COL_LAST_UPDATED', 'REMOTE_HOST', 'REAL_WORK_DIR', '_can_reach_remote', 'REMOTE_AVAILABLE', 'TABLE_HEADER', 'make_work_md', 'SAMPLE_WORK_MD', '_make_workloop', 'RUNS_COL_ID', 'RUNS_COL_STATUS', 'DEFAULT_TIMEOUT_MIN', 'POLL_CYCLES_PER_MIN', '_SCRIPT_WORK_MD', '_SINGLE_LOC_RUNS_MD', '_MULTI_LOC_RUNS_MD', '_SCHEDULED_RUNS_MD', '_make_script_item', '_RESEARCH_RUNS_MD', '_RESEARCH_WORK_MD', '_make_research_item', 'CH_ID', 'CH_TITLE', 'CH_STATUS', 'CH_LAST_UPDATED', 'CH_BUDGET', 'CH_LOG', '_make_parent_with_children', '_CHILD_RUNS_MD', '_CHILD_TASK_RUNS_MD', 'SAMPLE_WORK_NEW_MD', 'SAMPLE_STREAMLINED_WORK_MD', '_STREAMLINED_SCRIPT_WORK_MD']
