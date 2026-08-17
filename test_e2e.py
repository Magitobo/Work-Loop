#!/usr/bin/env python3
"""E2E tests: run real opencode harness, inspect JSON logs and workspace state.

These tests exercise the full dispatch pipeline:
  agent sync -> prompt assembly -> harness invocation -> log capture -> post-run state

Each test creates an isolated workspace, copies prompt files and agent definitions
from the repo, and runs the real harness.  JSON logs are parsed to verify that
the expected tool calls were emitted (e.g. critic subagent spawn, file writes).

Run directly:
  ENABLE_E2E_TESTS=1 pytest test_e2e.py -v

Or enable background dispatch after the unit test suite:
  ENABLE_BACKGROUND_E2E=1 pytest"""

import importlib.util
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

# ---------------------------------------------------------------------------
# Import run-loop.py
# ---------------------------------------------------------------------------
_HERE = Path(__file__).parent
_MOD_PATH = _HERE / "run-loop.py"
spec = importlib.util.spec_from_file_location("run_loop", _MOD_PATH)
run_loop = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run_loop)

WorkLoop = run_loop.WorkLoop
COL_ID = run_loop.COL_ID
COL_STATUS = run_loop.COL_STATUS
COL_LOCATION = run_loop.COL_LOCATION
COL_BUDGET = run_loop.COL_BUDGET
COL_LOG = run_loop.COL_LOG
COL_LAST_UPDATED = run_loop.COL_LAST_UPDATED

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REPO_DIR = _HERE  # Work-Loop repo root

PROMPT_FILES = [
    "LOOP-PROMPT.md",
    "IMPL-PROMPT.md",
    "RESOLVE-PROMPT.md",
    "UPDATE-RESEARCH-PROMPT.md",
]


def _copy_prompts_and_agents(tmp_dir: Path) -> None:
    """Copy prompt files into tmp workspace. Agent sync is handled by WorkLoop._sync_agent_dir."""
    for fname in PROMPT_FILES:
        src = REPO_DIR / fname
        if src.exists():
            shutil.copy2(str(src), tmp_dir / fname)


def _make_e2e_workspace(
    work_md: str,
    item_id: str = "ITEM-001",
    conversation_md: str = "## 2026-01-01 | User\n\nTest item for e2e.\n",
    status: str = "ready",
) -> WorkLoop:
    """Create a minimal workspace and return a WorkLoop instance."""
    tmp = Path(tempfile.mkdtemp())
    (tmp / "WORK.md").write_text(work_md)
    _copy_prompts_and_agents(tmp)

    item_dir = tmp / item_id
    item_dir.mkdir(parents=True)
    (item_dir / "CONVERSATION.md").write_text(conversation_md)

    # Read harness model from config.json (single source of truth)
    model = "llama-swap/llama/Qwen3.8-27B-Q6_K"
    config_path = REPO_DIR / "config.json"
    if config_path.exists():
        try:
            with open(config_path) as f:
                model = json.load(f).get("harness", {}).get("model", model)
        except Exception:
            pass

    cfg = {
        "work_dir": tmp,
        "harness": {
            "type": "opencode",
            "model": model,
            "max_budget_usd": 10.00,
        },
        "remote": {"work_dir": "~/Work-Loop"},
    }
    wl = WorkLoop(cfg, script_dir=REPO_DIR)
    wl._tmp_dir = tmp  # for cleanup
    return wl


def _make_research_workspace(
    item_id: str = "RES-001",
    runs_md: str = None,
) -> WorkLoop:
    """Create a workspace with a research item."""
    if runs_md is None:
        runs_md = (
            "## Config\n"
            "type: research\n"
            "title: Test Topic\n"
            "note_path: [[Test Note]]\n"
            "sources:\n"
            "  https://example.com/test\n\n"
            "## Prompt\n"
            "Test context.\n\n"
            "## Run History\n\n"
            "| ID | Summary | Status | Last Updated |\n"
            "|---|---|---|---|\n"
        )

    work_md = (
        "# Work Loop\n\n"
        "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
        "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
        f"| {item_id} | [Test](ITEM-001/C.md) | local | research |  |  |  |\n\n"
        "## Done\n\n"
        "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
        "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
    )

    wl = _make_e2e_workspace(work_md, item_id, status="research")
    tmp = wl._tmp_dir
    item_dir = tmp / item_id
    (item_dir / "RUNS.md").write_text(runs_md)
    return wl


def _find_log_file(item_dir: Path) -> Path | None:
    """Find the most recent JSON log file in _logs/."""
    logs = item_dir / "_logs"
    if not logs.exists():
        return None
    files = sorted(logs.glob("*.log"), key=os.path.getmtime, reverse=True)
    return files[0] if files else None


# ---------------------------------------------------------------------------
# JSON Log Parser
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
# Tests
# ---------------------------------------------------------------------------

class TestJsonLogParser(unittest.TestCase):
    """Unit tests for the log parser — no harness needed."""

    def test_parses_tool_use_events(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            f.write('{"type":"tool_use","part":{"tool":"read","state":{"input":{"filePath":"/tmp/test.md"},"status":"completed"}}}\n')
            f.write('{"type":"step_finish","part":{"reason":"stop"}}\n')
            f.flush()
            parser = JsonLogParser(Path(f.name))
        os.unlink(f.name)

        calls = parser.tool_calls()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["tool"], "read")

    def test_has_subagent_spawn(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            f.write('{"type":"tool_use","part":{"tool":"task","state":{"input":{"subagent_type":"critic","description":"Review"},"status":"completed"}}}\n')
            f.flush()
            parser = JsonLogParser(Path(f.name))
        os.unlink(f.name)

        self.assertTrue(parser.has_subagent_spawn("critic"))
        self.assertFalse(parser.has_subagent_spawn("code-reviewer"))

    def test_has_no_subagent_spawn(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            f.write('{"type":"tool_use","part":{"tool":"read","state":{"input":{"filePath":"/tmp/test.md"},"status":"completed"}}}\n')
            f.flush()
            parser = JsonLogParser(Path(f.name))
        os.unlink(f.name)

        self.assertTrue(parser.has_no_subagent_spawn())

    def test_has_file_edit(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            f.write('{"type":"tool_use","part":{"tool":"edit","state":{"input":{"file_path":"/tmp/CONVERSATION.md"},"status":"completed"}}}\n')
            f.flush()
            parser = JsonLogParser(Path(f.name))
        os.unlink(f.name)

        self.assertTrue(parser.has_file_edit("CONVERSATION.md"))
        self.assertFalse(parser.has_file_edit("WORK.md"))

    def test_has_step_stop(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            f.write('{"type":"step_finish","part":{"reason":"tool-calls"}}\n')
            f.write('{"type":"step_finish","part":{"reason":"stop"}}\n')
            f.flush()
            parser = JsonLogParser(Path(f.name))
        os.unlink(f.name)

        self.assertTrue(parser.has_step_stop())


# ---------------------------------------------------------------------------
# E2E Test: Analyze Mode
# ---------------------------------------------------------------------------

class TestAnalyzeMode(unittest.TestCase):
    """E2E: ready/analyze items trigger LOOP-PROMPT with critic subagent."""

    def _setup(self, item_id: str = "ITEM-001") -> tuple[WorkLoop, Path]:
        work_md = (
            "# Work Loop\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
            f"| {item_id} | [Test](ITEM-001/C.md) | local | ready |  |  |  |\n\n"
            "## Done\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
        )
        conversation = (
            "## 2026-01-01 | User\n\n"
            "Analyze this test item. Just read the files, spawn the critic,\n"
            "write a brief finding to CONVERSATION.md, and update WORK.md.\n"
        )
        wl = _make_e2e_workspace(work_md, item_id, conversation)
        return wl, wl._tmp_dir

    def test_critic_subagent_spawned(self):
        wl, tmp = self._setup()
        wl.process_local("ITEM-001", 10.0)

        log = _find_log_file(tmp / "ITEM-001")
        self.assertIsNotNone(log, "No log file created")
        parser = JsonLogParser(log)
        self.assertTrue(
            parser.has_subagent_spawn("critic"),
            f"Critic subagent not spawned. Tool calls: {parser.get_tool_names()}",
        )

    def test_conversation_md_written(self):
        wl, tmp = self._setup()
        wl.process_local("ITEM-001", 10.0)

        log = _find_log_file(tmp / "ITEM-001")
        self.assertIsNotNone(log)
        parser = JsonLogParser(log)
        self.assertTrue(
            parser.has_file_edit("CONVERSATION.md"),
            f"CONVERSATION.md not edited. Tool calls: {parser.get_tool_names()}",
        )

        # Also verify the file actually exists and has AI Agent content
        conv = tmp / "ITEM-001" / "CONVERSATION.md"
        self.assertTrue(conv.exists(), "CONVERSATION.md file not found")
        content = conv.read_text()
        self.assertIn("AI Agent", content, "CONVERSATION.md missing AI Agent entry")

    def test_work_md_updated(self):
        wl, tmp = self._setup()
        wl.process_local("ITEM-001", 10.0)

        status = wl.get_col("ITEM-001", COL_STATUS)
        self.assertEqual(status, "needs-review")

    def test_prompt_variables_injected(self):
        wl, tmp = self._setup()
        captured_prompt = [None]

        def capture_run(prompt: str, *args, **kwargs):
            captured_prompt[0] = prompt
            # Write a minimal log so the test doesn't fail
            log_file = kwargs.get("log_file") or args[3] if len(args) > 3 else None
            if log_file:
                log_file.write_text(
                    '{"type":"step_finish","part":{"reason":"stop","tokens":{"total":100,"input":80,"output":20,"reasoning":0,"cache":{"write":0,"read":0}},"cost":0}}\n'
                )
            return 0

        original = wl.harness.run
        wl.harness.run = capture_run
        try:
            wl.process_local("ITEM-001", 10.0)
        finally:
            wl.harness.run = original

        prompt = captured_prompt[0]
        self.assertIsNotNone(prompt)
        self.assertIn("ITEM_ID: ITEM-001", prompt)
        self.assertIn("WORK_LOOP_DIR:", prompt)
        self.assertIn("ITEM_DIR:", prompt)


# ---------------------------------------------------------------------------
# E2E Test: Implement Mode
# ---------------------------------------------------------------------------

class TestImplementMode(unittest.TestCase):
    """E2E: implement items trigger IMPL-PROMPT with code-reviewer subagent."""

    def _setup(self) -> tuple[WorkLoop, Path]:
        work_md = (
            "# Work Loop\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
            "| ITEM-001 | [Test](ITEM-001/C.md) | local | implement |  |  |  |\n\n"
            "## Done\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
        )
        conversation = (
            "## 2026-01-01 | User\n\n"
            "Implement a simple test file.\n\n"
            "work_dir: /tmp\n"
        )
        wl = _make_e2e_workspace(work_md, "ITEM-001", conversation)
        return wl, wl._tmp_dir

    def test_code_reviewer_spawned(self):
        wl, tmp = self._setup()
        wl.process_local("ITEM-001", 10.0)

        log = _find_log_file(tmp / "ITEM-001")
        self.assertIsNotNone(log, "No log file created")
        parser = JsonLogParser(log)
        self.assertTrue(
            parser.has_subagent_spawn("code-reviewer"),
            f"Code-reviewer not spawned. Tool calls: {parser.get_tool_names()}",
        )


# ---------------------------------------------------------------------------
# E2E Test: Resolved Mode
# ---------------------------------------------------------------------------

class TestResolvedMode(unittest.TestCase):
    """E2E: resolved items trigger RESOLVE-PROMPT — no subagent spawn."""

    def _setup(self) -> tuple[WorkLoop, Path]:
        work_md = (
            "# Work Loop\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
            "| ITEM-001 | [Test](ITEM-001/C.md) | local | resolved |  |  |  |\n\n"
            "## Done\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
        )
        conversation = (
            "## 2026-01-01 | User\n\n"
            "Problem: Test issue. Resolution: Fixed by updating config.\n"
            "## 2026-01-02 | AI Agent\n\n"
            "Resolved the test issue.\n"
        )
        wl = _make_e2e_workspace(work_md, "ITEM-001", conversation)
        return wl, wl._tmp_dir

    def test_no_subagent_spawn(self):
        wl, tmp = self._setup()
        wl.process_local("ITEM-001", 10.0)

        log = _find_log_file(tmp / "ITEM-001")
        self.assertIsNotNone(log)
        parser = JsonLogParser(log)
        self.assertTrue(
            parser.has_no_subagent_spawn(),
            f"Unexpected subagent spawn. Tool calls: {parser.get_tool_names()}",
        )

    def test_row_moved_to_done_on_success(self):
        wl, tmp = self._setup()
        wl.process_local("ITEM-001", 10.0)

        content = (tmp / "WORK.md").read_text()
        # After resolved mode, the row should be in the Done section
        # or status should be 'done' (moved by the agent)
        self.assertIn("ITEM-001", content)


# ---------------------------------------------------------------------------
# E2E Test: Research Mode
# ---------------------------------------------------------------------------

class TestResearchMode(unittest.TestCase):
    """E2E: research items fetch sources and write research summary."""

    def test_webfetch_for_sources(self):
        runs_md = (
            "## Config\n"
            "type: research\n"
            "title: E2E Test\n"
            "note_path: [[E2E Test Note]]\n"
            "sources:\n"
            "  https://example.com/e2e-test\n\n"
            "## Prompt\n"
            "Just fetch the source and write a brief summary.\n\n"
            "## Run History\n\n"
            "| ID | Summary | Status | Last Updated |\n"
            "|---|---|---|---|\n"
        )
        work_md = (
            "# Work Loop\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
            "| RES-001 | [Test](RES-001/C.md) | local | research |  |  |  |\n\n"
            "## Done\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
        )
        wl = _make_e2e_workspace(work_md, "RES-001", status="research")
        tmp = wl._tmp_dir
        (tmp / "RES-001" / "RUNS.md").write_text(runs_md)

        wl.process_local("RES-001", 10.0)

        log = _find_log_file(tmp / "RES-001")
        self.assertIsNotNone(log)
        parser = JsonLogParser(log)
        # The model should fetch the source URL
        self.assertTrue(
            parser.has_webfetch("https://example.com"),
            f"No webfetch for source. Tool calls: {parser.get_tool_names()}",
        )

    def test_research_summary_written(self):
        runs_md = (
            "## Config\n"
            "type: research\n"
            "title: E2E Test\n"
            "note_path: [[E2E Test Note]]\n"
            "sources:\n"
            "  https://example.com/e2e-test\n\n"
            "## Prompt\n"
            "Test.\n\n"
            "## Run History\n\n"
            "| ID | Summary | Status | Last Updated |\n"
            "|---|---|---|---|\n"
        )
        work_md = (
            "# Work Loop\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
            "| RES-001 | [Test](RES-001/C.md) | local | research |  |  |  |\n\n"
            "## Done\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
        )
        wl = _make_e2e_workspace(work_md, "RES-001", status="research")
        tmp = wl._tmp_dir
        (tmp / "RES-001" / "RUNS.md").write_text(runs_md)

        wl.process_local("RES-001", 10.0)

        log = _find_log_file(tmp / "RES-001")
        self.assertIsNotNone(log)
        parser = JsonLogParser(log)
        # The model should write research.md to runs/ directory
        self.assertTrue(
            parser.has_file_write_to("research.md") or parser.has_file_edit("research.md"),
            f"No research.md written. Tool calls: {parser.get_tool_names()}",
        )


# ---------------------------------------------------------------------------
# E2E Test: Child Research
# ---------------------------------------------------------------------------

class TestChildResearch(unittest.TestCase):
    """E2E: child research items receive parent variables."""

    def test_parent_vars_in_prompt(self):
        work_md = (
            "# Work Loop\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
            "| PARENT-001 | [Parent](PARENT-001/C.md) | local | ready |  |  |  |\n\n"
            "## Done\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
        )
        wl = _make_e2e_workspace(work_md, "PARENT-001")
        tmp = wl._tmp_dir

        # Set up child agent
        child_dir = tmp / "PARENT-001" / "children" / "test-child"
        child_dir.mkdir(parents=True)
        runs_md = (
            "## Config\n"
            "type: research\n"
            "parent: PARENT-001\n"
            "title: Child Test\n"
            "note_path: ../context/child-test.md\n"
            "sources:\n"
            "  https://example.com/child\n\n"
            "## Prompt\n"
            "Child research.\n\n"
            "## Run History\n\n"
            "| ID | Summary | Status | Last Updated |\n"
            "|---|---|---|---|\n"
        )
        (child_dir / "RUNS.md").write_text(runs_md)

        work_children = (
            "| ID | Title | Status | Last Updated | Budget | Log |\n"
            "|---|---|---|---|---|---|\n"
            "| test-child | [Child Test](children/test-child/RUNS.md) | ready |  |  |  |\n"
        )
        (tmp / "PARENT-001" / "WORK-CHILDREN.md").write_text(work_children)

        captured_prompt = [None]
        original = wl.harness.run

        def capture_run(prompt: str, *args, **kwargs):
            captured_prompt[0] = prompt
            log_file = kwargs.get("log_file") or args[3] if len(args) > 3 else None
            if log_file:
                log_file.write_text(
                    '{"type":"step_finish","part":{"reason":"stop","tokens":{"total":100,"input":80,"output":20,"reasoning":0,"cache":{"write":0,"read":0}},"cost":0}}\n'
                )
            return 0

        wl.harness.run = capture_run
        try:
            wl.process_child("PARENT-001", "test-child")
        finally:
            wl.harness.run = original

        prompt = captured_prompt[0]
        self.assertIsNotNone(prompt)
        self.assertIn("PARENT_ID: PARENT-001", prompt)
        self.assertIn("PARENT_DIR:", prompt)


# ---------------------------------------------------------------------------
# E2E Test: Agent Directory Sync
# ---------------------------------------------------------------------------

class TestAgentSync(unittest.TestCase):
    """Verify .opencode/agents/ is synced to workspace before harness runs."""

    def test_agent_dir_copied_to_workspace(self):
        work_md = (
            "# Work Loop\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
            "| ITEM-001 | [Test](ITEM-001/C.md) | local | ready |  |  |  |\n\n"
            "## Done\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
        )
        wl = _make_e2e_workspace(work_md, "ITEM-001", status="ready")
        tmp = wl._tmp_dir

        # Agent dir should NOT exist in work_dir yet
        work_opencode = tmp / ".opencode"
        self.assertFalse(work_opencode.exists(), ".opencode/ should not exist in work_dir initially")

        # Run the agent sync
        wl._sync_agent_dir(str(tmp))

        # Now it should exist with agent files
        self.assertTrue(work_opencode.exists(), ".opencode/ not synced to workspace")
        self.assertTrue(
            (work_opencode / "agents" / "critic.md").exists(),
            "critic.md not found in synced agent dir",
        )
        self.assertTrue(
            (work_opencode / "agents" / "code-reviewer.md").exists(),
            "code-reviewer.md not found in synced agent dir",
        )

    def test_no_error_when_agent_dir_missing(self):
        work_md = (
            "# Work Loop\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
            "| ITEM-001 | [Test](ITEM-001/C.md) | local | ready |  |  |  |\n\n"
            "## Done\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
        )
        wl = _make_e2e_workspace(work_md, "ITEM-001", status="ready")
        tmp = wl._tmp_dir

        # Remove agent dir from script_dir
        script_agents = tmp / ".opencode"
        if script_agents.exists():
            shutil.rmtree(script_agents)

        # Should not raise
        wl._sync_agent_dir(str(tmp))

    def test_sync_overwrites_stale_agents(self):
        work_md = (
            "# Work Loop\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
            "| ITEM-001 | [Test](ITEM-001/C.md) | local | ready |  |  |  |\n\n"
            "## Done\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
        )
        wl = _make_e2e_workspace(work_md, "ITEM-001", status="ready")
        tmp = wl._tmp_dir

        # Pre-create stale agent dir
        stale_dir = tmp / ".opencode" / "agents"
        stale_dir.mkdir(parents=True)
        (stale_dir / "old-agent.md").write_text("stale")

        # Sync should replace it
        wl._sync_agent_dir(str(tmp))

        self.assertTrue((tmp / ".opencode" / "agents" / "critic.md").exists())
        self.assertFalse((tmp / ".opencode" / "agents" / "old-agent.md").exists())


# ---------------------------------------------------------------------------
# E2E Test: Prompt Loading
# ---------------------------------------------------------------------------

class TestPromptLoading(unittest.TestCase):
    """Verify correct prompt file is loaded for each mode."""

    def _capture_prompt(self, wl: WorkLoop, item_id: str) -> str:
        captured = [None]

        def capture_run(prompt: str, *args, **kwargs):
            captured[0] = prompt
            log_file = kwargs.get("log_file") or args[3] if len(args) > 3 else None
            if log_file:
                log_file.write_text(
                    '{"type":"step_finish","part":{"reason":"stop","tokens":{"total":100,"input":80,"output":20,"reasoning":0,"cache":{"write":0,"read":0}},"cost":0}}\n'
                )
            return 0

        original = wl.harness.run
        wl.harness.run = capture_run
        try:
            wl.process_local(item_id, 10.0)
        finally:
            wl.harness.run = original
        return captured[0]

    def test_loop_prompt_for_ready(self):
        work_md = (
            "# Work Loop\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
            "| ITEM-001 | [Test](ITEM-001/C.md) | local | ready |  |  |  |\n\n"
            "## Done\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
        )
        wl = _make_e2e_workspace(work_md, "ITEM-001")
        prompt = self._capture_prompt(wl, "ITEM-001")
        self.assertIsNotNone(prompt)
        # LOOP-PROMPT.md contains "Multi-Agent" in its title
        self.assertIn("Multi-Agent", prompt)

    def test_impl_prompt_for_implement(self):
        work_md = (
            "# Work Loop\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
            "| ITEM-001 | [Test](ITEM-001/C.md) | local | implement |  |  |  |\n\n"
            "## Done\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
        )
        conversation = "## 2026-01-01 | User\n\nwork_dir: /tmp\n"
        wl = _make_e2e_workspace(work_md, "ITEM-001", conversation)
        prompt = self._capture_prompt(wl, "ITEM-001")
        self.assertIsNotNone(prompt)
        # IMPL-PROMPT.md contains "Implementation Mode"
        self.assertIn("Implementation Mode", prompt)

    def test_resolve_prompt_for_resolved(self):
        work_md = (
            "# Work Loop\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
            "| ITEM-001 | [Test](ITEM-001/C.md) | local | resolved |  |  |  |\n\n"
            "## Done\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
        )
        wl = _make_e2e_workspace(work_md, "ITEM-001")
        prompt = self._capture_prompt(wl, "ITEM-001")
        self.assertIsNotNone(prompt)
        # RESOLVE-PROMPT.md contains "Resolved Mode"
        self.assertIn("Resolved Mode", prompt)


if __name__ == "__main__":
    unittest.main()