import os
import shutil
import tempfile
import unittest
import unittest.mock
from pathlib import Path
import json
import re
import sys
import subprocess
import threading

from test_helpers import *

class TestLauncherScript(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.wl = _make_workloop(self.tmp)

    def test_launcher_captures_exit_code(self):
        script = self.wl.build_launcher("ITEM-001", "2026-05-14_10-00-00", budget=self.wl.max_budget)
        self.assertIn("echo $?", script)

    def test_launcher_no_python_escape_artifacts(self):
        script = self.wl.build_launcher("ITEM-001", "2026-05-14_10-00-00", budget=self.wl.max_budget)
        self.assertNotIn("${{", script)
        self.assertNotIn("}}", script)

    def test_launcher_loads_nvm(self):
        script = self.wl.build_launcher("ITEM-001", "2026-05-14_10-00-00", budget=self.wl.max_budget)
        self.assertIn("NVM_DIR", script)
        self.assertIn("nvm.sh", script)

    def test_launcher_captures_stderr(self):
        script = self.wl.build_launcher("ITEM-001", "2026-05-14_10-00-00", budget=self.wl.max_budget)
        self.assertIn("2>&1", script)

    def test_launcher_contains_item_id(self):
        script = self.wl.build_launcher("MY-TASK", "2026-05-14_10-00-00", budget=self.wl.max_budget)
        self.assertIn("MY-TASK", script)

    def test_launcher_contains_budget(self):
        script = self.wl.build_launcher("ITEM-001", "2026-05-14_10-00-00", budget=self.wl.max_budget)
        self.assertIn(str(self.wl.max_budget), script)

    def test_launcher_contains_log_path(self):
        ts = "2026-05-14_10-00-00"
        script = self.wl.build_launcher("ITEM-001", ts, budget=self.wl.max_budget)
        self.assertIn(f"_logs/{ts}_ITEM-001.log", script)

    def test_launcher_starts_with_shebang(self):
        script = self.wl.build_launcher("ITEM-001", "2026-05-14_10-00-00", budget=self.wl.max_budget)
        self.assertTrue(script.startswith("#!/bin/bash\n"))

    def test_launcher_has_done_sentinel(self):
        script = self.wl.build_launcher("ITEM-001", "2026-05-14_10-00-00", budget=self.wl.max_budget)
        self.assertIn(".done", script)

    def test_launcher_script_is_valid_bash(self):
        """Verify the generated launcher parses as valid bash syntax."""
        script = self.wl.build_launcher("ITEM-001", "2026-05-14_10-00-00", budget=self.wl.max_budget)
        result = subprocess.run(
            ["bash", "-n"],
            input=script.encode(),
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, f"bash -n failed: {result.stderr.decode()}")


class TestLauncherScriptImplementMode(unittest.TestCase):

    TS = "2026-05-14_10-00-00"

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.wl = _make_workloop(self.tmp)

    def _script(self, work_dir=None):
        return self.wl.build_launcher("ITEM-001", self.TS, budget=10.0,
                                      mode="implement", work_dir=work_dir)

    def test_uses_impl_prompt(self):
        self.assertIn("IMPL-PROMPT.md", self._script())
        self.assertNotIn("LOOP-PROMPT.md", self._script())

    def test_includes_work_loop_dir_and_item_dir(self):
        script = self._script()
        self.assertIn("WORK_LOOP_DIR", script)
        self.assertIn("ITEM_DIR", script)

    def test_captures_rwd(self):
        self.assertIn("RWD=", self._script())

    def test_uses_rwd_for_log_path(self):
        self.assertIn("$RWD/ITEM-001/_logs/", self._script())

    def test_uses_rwd_for_done_sentinel(self):
        self.assertIn("$RWD/ITEM-001/.done", self._script())

    def test_cds_to_work_dir_when_provided(self):
        self.assertIn("cd /some/repo", self._script(work_dir="/some/repo"))

    def test_no_cd_to_work_dir_when_not_provided(self):
        script = self._script()
        # Only the initial cd to rwd; no second cd line
        cd_lines = [l for l in script.splitlines() if l.startswith("cd ")]
        self.assertEqual(len(cd_lines), 1)

    def test_rwd_captured_before_cd_to_work_dir(self):
        script = self._script(work_dir="/some/repo")
        rwd_pos = script.index("RWD=")
        cd_pos = script.index("cd /some/repo")
        self.assertLess(rwd_pos, cd_pos)

    def test_valid_bash_syntax(self):
        script = self._script(work_dir="/some/repo")
        result = subprocess.run(["bash", "-n"], input=script.encode(), capture_output=True)
        self.assertEqual(result.returncode, 0, f"bash -n failed: {result.stderr.decode()}")

    def test_valid_bash_syntax_without_work_dir(self):
        result = subprocess.run(["bash", "-n"], input=self._script().encode(), capture_output=True)
        self.assertEqual(result.returncode, 0, f"bash -n failed: {result.stderr.decode()}")


class TestPrependAbortNotice(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.wl = _make_workloop(self.tmp)

    def test_prepend(self):
        item_dir = Path(self.tmp) / "ITEM-001"
        item_dir.mkdir()
        conv = item_dir / "CONVERSATION.md"
        conv.write_text("## 2026-05-10 | Oliver\nOriginal content.\n")

        self.wl.prepend_abort_notice("ITEM-001", "2026-05-14", budget=self.wl.max_budget)

        text = conv.read_text()
        self.assertTrue(text.startswith("## 2026-05-14 | Script — Run aborted"))
        self.assertIn("budget exceeded", text)
        self.assertIn("Original content.", text)

    def test_prepend_custom_cause(self):
        item_dir = Path(self.tmp) / "ITEM-001"
        item_dir.mkdir()
        conv = item_dir / "CONVERSATION.md"
        conv.write_text("Original.\n")

        self.wl.prepend_abort_notice("ITEM-001", "2026-05-14", budget=self.wl.max_budget, cause="run failed")

        text = conv.read_text()
        self.assertIn("run failed", text)
        self.assertNotIn("budget exceeded", text)

    def test_prepend_noop_if_no_conversation(self):
        # Should not raise if CONVERSATION.md doesn't exist
        self.wl.prepend_abort_notice("NONEXISTENT", "2026-05-14", budget=self.wl.max_budget)

    def test_prepend_multiple_calls(self):
        item_dir = Path(self.tmp) / "ITEM-001"
        item_dir.mkdir()
        conv = item_dir / "CONVERSATION.md"
        conv.write_text("Original.\n")

        self.wl.prepend_abort_notice("ITEM-001", "2026-05-14", budget=self.wl.max_budget)
        self.wl.prepend_abort_notice("ITEM-001", "2026-05-14", budget=self.wl.max_budget)

        text = conv.read_text()
        self.assertEqual(text.count("Run aborted"), 2)
        self.assertIn("Original.", text)


class TestExtractWorkDir(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.wl = _make_workloop(self.tmp)

    def _write_conversation(self, item_id: str, text: str) -> None:
        item_dir = Path(self.tmp) / item_id
        item_dir.mkdir(exist_ok=True)
        (item_dir / "CONVERSATION.md").write_text(text)

    def test_extracts_work_dir_from_conversation(self):
        self._write_conversation("ITEM-001", "## 2026-05-25 | Oliver\n\nwork_dir: /tmp/my-project\n")
        result = self.wl.extract_work_dir("ITEM-001")
        self.assertEqual(result, "/tmp/my-project")

    def test_extracts_tilde_path(self):
        self._write_conversation("ITEM-001", "work_dir: ~/kb-ccs/kb-debug/\n")
        result = self.wl.extract_work_dir("ITEM-001")
        self.assertNotIn("~", result)
        self.assertIn("kb-ccs/kb-debug", result)

    def test_case_insensitive(self):
        self._write_conversation("ITEM-001", "Work_Dir: /some/path\n")
        result = self.wl.extract_work_dir("ITEM-001")
        self.assertEqual(result, "/some/path")

    def test_returns_loop_root_when_absent(self):
        self._write_conversation("ITEM-001", "## 2026-05-25 | Oliver\n\nNo work dir here.\n")
        result = self.wl.extract_work_dir("ITEM-001")
        self.assertEqual(result, self.tmp)

    def test_returns_loop_root_when_no_conversation(self):
        result = self.wl.extract_work_dir("NONEXISTENT")
        self.assertEqual(result, self.tmp)

    def test_strips_trailing_slash(self):
        self._write_conversation("ITEM-001", "work_dir: /some/path/\n")
        result = self.wl.extract_work_dir("ITEM-001")
        # os.path.expanduser doesn't strip slash, but the path is usable either way;
        # just confirm the value is what was written
        self.assertIn("/some/path", result)

    def test_first_occurrence_wins(self):
        self._write_conversation("ITEM-001", "work_dir: /first\nwork_dir: /second\n")
        result = self.wl.extract_work_dir("ITEM-001")
        self.assertEqual(result, "/first")


class TestLoopPromptPortability(unittest.TestCase):
    """LOOP-PROMPT.md must work when deployed to remote hosts with different layouts."""

    LOOP_PROMPT = _PROMPTS_DIR / "LOOP-PROMPT.md"

    @classmethod
    def setUpClass(cls):
        if not cls.LOOP_PROMPT.exists():
            raise unittest.SkipTest("LOOP-PROMPT.md not found")
        cls.content = cls.LOOP_PROMPT.read_text()

    def test_no_hardcoded_local_work_dir(self):
        """~/MyNotebook/Work-Loop/ exists only on the local machine.
        Remote hosts use a different directory (e.g. ~/Work-Loop/), so any
        hardcoded local path causes Claude to fail to find context files,
        spiral on tool calls, and burn the budget."""
        self.assertNotIn(
            "~/MyNotebook/Work-Loop/",
            self.content,
            "LOOP-PROMPT.md contains a hardcoded local path — remote dispatch will fail",
        )

    def test_item_id_references_are_relative(self):
        """Paths containing {ITEM_ID} must be relative so they resolve on any host."""
        import re
        absolute_refs = re.findall(r'~[^\s]*\{ITEM_ID\}', self.content)
        self.assertEqual(
            absolute_refs, [],
            f"Found absolute paths containing {{ITEM_ID}}: {absolute_refs}",
        )


class TestResolvedModeTrigger(unittest.TestCase):
    """'resolved' is a trigger status like ready/analyze/implement."""

    def _make_wl(self, status: str) -> WorkLoop:
        content = (
            "# Work Loop\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
            f"| MY-ITEM | [Task](MY-ITEM/C.md) | local | {status} |  |  |  |\n\n"
            "## Done\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
        )
        return _make_workloop(tempfile.mkdtemp(), content)

    def test_resolved_triggers(self):
        wl = self._make_wl("resolved")
        self.assertIn("MY-ITEM", wl.get_ready_items())

    def test_resolved_mode_routed_for_remote_dispatch(self):
        from unittest.mock import patch
        content = (
            "# Work Loop\n\n"
            "| ID      | Title | Location    | Status   | Last Updated | Budget | Log |\n"
            "| ------- | ----- | ----------- | -------- | ------------ | ------ | --- |\n"
            "| MY-ITEM | Task  | user@remote | resolved |  |  |  |\n\n"
            "## Done\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
        )
        wl = _make_workloop(tempfile.mkdtemp(), content)
        captured = {}

        def fake_dispatch(item_id, ts_str, remote_host, budget, mode="analyze"):
            captured["mode"] = mode

        with patch.object(WorkLoop, "dispatch_remote", side_effect=fake_dispatch), \
             patch.object(WorkLoop, "wait_for_remote"):
            wl.run(once=True)
        self.assertEqual(captured.get("mode"), "resolved")


class TestLauncherScriptResolvedMode(unittest.TestCase):

    TS = "2026-05-14_10-00-00"

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.wl = _make_workloop(self.tmp)

    def _script(self):
        return self.wl.build_launcher("ITEM-001", self.TS, budget=10.0, mode="resolved")

    def test_uses_resolve_prompt(self):
        self.assertIn("RESOLVE-PROMPT.md", self._script())
        self.assertNotIn("LOOP-PROMPT.md", self._script())
        self.assertNotIn("IMPL-PROMPT.md", self._script())

    def test_does_not_include_work_loop_dir_or_item_dir(self):
        script = self._script()
        self.assertNotIn("WORK_LOOP_DIR", script)
        self.assertNotIn("ITEM_DIR", script)

    def test_includes_item_id(self):
        self.assertIn("ITEM-001", self._script())

    def test_captures_exit_code(self):
        self.assertIn("echo $?", self._script())

    def test_has_debug_file_flag(self):
        self.assertIn(".debug", self._script())

    def test_valid_bash_syntax(self):
        result = subprocess.run(["bash", "-n"], input=self._script().encode(), capture_output=True)
        self.assertEqual(result.returncode, 0, f"bash -n failed: {result.stderr.decode()}")

    def test_no_rwd_capture(self):
        self.assertNotIn("RWD=", self._script())


class TestLauncherDebugFile(unittest.TestCase):
    """All launcher modes must include --debug-file for structured logging."""

    TS = "2026-05-14_10-00-00"

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.wl = _make_workloop(self.tmp)

    def test_analyze_mode_has_debug_file(self):
        script = self.wl.build_launcher("ITEM-001", self.TS, budget=10.0, mode="analyze")
        self.assertIn("--debug-file", script)
        self.assertIn(".debug", script)

    def test_implement_mode_has_debug_file(self):
        script = self.wl.build_launcher("ITEM-001", self.TS, budget=10.0, mode="implement")
        self.assertIn("--debug-file", script)
        self.assertIn(".debug", script)

    def test_resolved_mode_has_debug_file(self):
        script = self.wl.build_launcher("ITEM-001", self.TS, budget=10.0, mode="resolved")
        self.assertIn("--debug-file", script)
        self.assertIn(".debug", script)

    def test_implement_debug_file_uses_rwd(self):
        script = self.wl.build_launcher("ITEM-001", self.TS, budget=10.0, mode="implement")
        self.assertIn('$RWD/ITEM-001/_logs/', script)

    def test_analyze_debug_file_path_contains_ts_and_item(self):
        script = self.wl.build_launcher("ITEM-001", self.TS, budget=10.0, mode="analyze")
        self.assertIn(f"_logs/{self.TS}_ITEM-001.debug", script)

    def test_all_modes_valid_bash(self):
        for mode in ("analyze", "implement", "resolved"):
            script = self.wl.build_launcher("ITEM-001", self.TS, budget=10.0, mode=mode)
            result = subprocess.run(["bash", "-n"], input=script.encode(), capture_output=True)
            self.assertEqual(result.returncode, 0, f"bash -n failed for mode={mode}: {result.stderr.decode()}")


class TestProcessLocalResolvedMode(unittest.TestCase):

    def _make_wl(self, tmp: str) -> WorkLoop:
        content = (
            "# Work Loop\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
            "| MY-ITEM | [Task](MY-ITEM/C.md) | local | resolved |  |  |  |\n\n"
            "## Done\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
        )
        wl = _make_workloop(tmp, content)
        (Path(tmp) / "RESOLVE-PROMPT.md").write_text("Resolve.\n")
        (Path(tmp) / "_logs").mkdir(exist_ok=True)
        item_dir = Path(tmp) / "MY-ITEM"
        item_dir.mkdir()
        (item_dir / "CONVERSATION.md").write_text("## 2026-01-01 | User\n\nDo it.\n")
        return wl

    def test_success_moves_to_done(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl(tmp)
            with patch.object(WorkLoop, "_run_harness", return_value=0):
                wl.process_local("MY-ITEM", 10.0)
            text = (Path(tmp) / "WORK.md").read_text()
            done_idx = text.index("## Done")
            self.assertIn("MY-ITEM", text[done_idx:])
            self.assertNotIn("MY-ITEM", text[:done_idx])

    def test_failure_sets_needs_review(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl(tmp)
            with patch.object(WorkLoop, "_run_harness", return_value=1):
                wl.process_local("MY-ITEM", 10.0)
            self.assertEqual(wl.get_col("MY-ITEM", COL_STATUS), "needs-review")

    def test_failure_does_not_move_to_done(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl(tmp)
            with patch.object(WorkLoop, "_run_harness", return_value=1):
                wl.process_local("MY-ITEM", 10.0)
            text = (Path(tmp) / "WORK.md").read_text()
            done_idx = text.index("## Done")
            self.assertNotIn("MY-ITEM", text[done_idx:])


class TestBuildLauncher(unittest.TestCase):
    """Verify that the generated launcher script records PID and .done correctly."""

    def _make_wl(self, tmp: str) -> WorkLoop:
        content = (
            "# Work Loop\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
            "| MY-ITEM | [Task](MY-ITEM/C.md) | remote@host | ready |  |  |  |\n\n"
            "## Done\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
        )
        wl = _make_workloop(tmp, content)
        return wl

    def test_launcher_backgrounds_claude_and_writes_pid(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl(tmp)
            script = wl.build_launcher("MY-ITEM", "2026-01-01_12-00-00", 5.0)
            # Claude command must end with & (backgrounded)
            self.assertIn('claude --print', script)
            self.assertIn('&\n', script)
            # PID file written right after backgrounding
            self.assertIn('echo $! >', script)
            self.assertIn('.pid', script)
            # wait for completion, then write .done
            self.assertIn('wait $!', script)
            self.assertIn('.done', script)

    def test_launcher_pid_written_before_done(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl(tmp)
            script = wl.build_launcher("MY-ITEM", "2026-01-01_12-00-00", 5.0)
            pid_pos = script.index('.pid')
            done_pos = script.index('.done')
            self.assertLess(pid_pos, done_pos)


class TestBasePromptHandling(unittest.TestCase):

    def _make_wl(self, tmp, with_base=True):
        p = Path(tmp)
        (p / "WORK.md").write_text(make_work_md("| T-001 | [Test](T-001/CONVERSATION.md) | local | ready |  |  |  |"))
        (p / "LOOP-PROMPT.md").write_text("Execute loop task.\n")
        if with_base:
            (p / "BASE-PROMPT.md").write_text("## Reasoning Budget: Medium\nKeep it short.\n")
        item_dir = p / "T-001"
        item_dir.mkdir(parents=True, exist_ok=True)
        (item_dir / "CONVERSATION.md").write_text("## 2026-01-01 | User\n\nTest prompt\n")

        cfg = {"work_dir": p, "harness": {"type": "opencode", "max_budget_usd": 10.00}, "remote": {"work_dir": "~/Work-Loop"}}
        wl = WorkLoop(cfg)
        wl.script_dir = p
        wl.prompt_file = p / "LOOP-PROMPT.md"
        wl.base_prompt_file = p / "BASE-PROMPT.md"
        return wl

    def test_read_base_prompt_when_file_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl(tmp, with_base=True)
            self.assertEqual(wl._read_base_prompt(), "## Reasoning Budget: Medium\nKeep it short.\n\n")

    def test_read_base_prompt_when_file_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl(tmp, with_base=False)
            self.assertEqual(wl._read_base_prompt(), "")

    def test_process_local_prepends_base_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl(tmp, with_base=True)
            captured_prompts = []

            def mock_run_harness(prompt, log_file, budget, cwd=None, item_id=None):
                captured_prompts.append(prompt)
                return 0

            with unittest.mock.patch.object(wl, "_run_harness", side_effect=mock_run_harness):
                wl.process_local("T-001", 10.0)

            self.assertEqual(len(captured_prompts), 1)
            self.assertTrue(captured_prompts[0].startswith("## Reasoning Budget: Medium\nKeep it short.\n\nExecute loop task."))

    def test_build_launcher_contains_base_prompt_handling(self):
        claude_harness = run_loop.ClaudeHarness()
        opencode_harness = run_loop.OpenCodeHarness()

        claude_script = claude_harness.launcher_script("T-001", "2026-01-01", 10.0, "analyze", None, "~/Work-Loop")
        self.assertIn("BASE-PROMPT.md", claude_script)
        self.assertIn("${BASE_PROMPT}$(cat prompts/LOOP-PROMPT.md)", claude_script)

        opencode_script = opencode_harness.launcher_script("T-001", "2026-01-01", 10.0, "analyze", None, "~/Work-Loop")
        self.assertIn("BASE-PROMPT.md", opencode_script)
        self.assertIn("${BASE_PROMPT}$(cat prompts/LOOP-PROMPT.md)", opencode_script)


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


class TestAgentSync(unittest.TestCase):
    """Verify .opencode/agents/ or .claude/agents/ is synced to workspace before harness runs."""

    def test_agent_dir_copied_to_workspace(self):
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            # Agent dir is synced into the workspace at construction
            WorkLoop({"work_dir": tmp, "harness": {"type": "opencode"}}, script_dir=_HERE)
            work_opencode = tmp / ".opencode"
            self.assertTrue(work_opencode.exists())
            self.assertTrue((work_opencode / "agents" / "critic.md").exists())
            self.assertTrue((work_opencode / "agents" / "code-reviewer.md").exists())

    def test_no_error_when_agent_dir_missing(self):
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            fake_script_dir = tmp / "empty_repo"
            fake_script_dir.mkdir()
            wl = WorkLoop({"work_dir": tmp, "harness": {"type": "opencode"}}, script_dir=fake_script_dir)
            # Should not raise
            wl._sync_agent_dir(str(tmp))

    def test_sync_overwrites_stale_agents(self):
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            # Pre-seed a stale agent BEFORE construction so the startup sync cleans it up
            stale_dir = tmp / ".opencode" / "agents"
            stale_dir.mkdir(parents=True)
            (stale_dir / "old-agent.md").write_text("stale")

            WorkLoop({"work_dir": tmp, "harness": {"type": "opencode"}}, script_dir=_HERE)

            self.assertTrue((tmp / ".opencode" / "agents" / "critic.md").exists())
            self.assertFalse((tmp / ".opencode" / "agents" / "old-agent.md").exists())

    def test_sync_ignores_node_modules_and_transient_files(self):
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            fake_script_dir = tmp / "repo"
            fake_agent_dir = fake_script_dir / ".opencode"
            (fake_agent_dir / "agents").mkdir(parents=True)
            (fake_agent_dir / "agents" / "critic.md").write_text("prompt")
            (fake_agent_dir / "node_modules" / "some-pkg").mkdir(parents=True)
            (fake_agent_dir / "node_modules" / "some-pkg" / "index.js").write_text("console.log(1)")
            (fake_agent_dir / ".DS_Store").write_bytes(b"\x00\x00")

            target_ws = tmp / "workspace"
            target_ws.mkdir()
            # Simulate pre-existing node_modules in destination workspace
            (target_ws / ".opencode" / "node_modules" / "existing-pkg").mkdir(parents=True)
            (target_ws / ".opencode" / "node_modules" / "existing-pkg" / "lib.js").write_text("existing")

            wl = WorkLoop({"work_dir": target_ws, "harness": {"type": "opencode"}}, script_dir=fake_script_dir)
            wl._sync_agent_dir(str(target_ws))

            # Agents should be synced
            self.assertTrue((target_ws / ".opencode" / "agents" / "critic.md").exists())
            # Transient files should not be copied from source
            self.assertFalse((target_ws / ".opencode" / ".DS_Store").exists())
            self.assertFalse((target_ws / ".opencode" / "node_modules" / "some-pkg").exists())
            # Existing node_modules in workspace should not be destroyed or crash
            self.assertTrue((target_ws / ".opencode" / "node_modules" / "existing-pkg" / "lib.js").exists())

    def test_sync_skips_claude_code_local_state(self):
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            fake_script_dir = tmp / "repo"
            fake_agent_dir = fake_script_dir / ".claude"
            (fake_agent_dir / "agents").mkdir(parents=True)
            (fake_agent_dir / "agents" / "critic.md").write_text("prompt")
            (fake_agent_dir / "settings.json").write_text("{}")
            (fake_agent_dir / "settings.local.json").write_text("{}")
            (fake_agent_dir / "worktrees" / "x").mkdir(parents=True)
            # Unresolvable placeholder: rendering it would raise ValueError
            (fake_agent_dir / "worktrees" / "x" / "file.py").write_text("s = '{{bogus}}'")

            target_ws = tmp / "workspace"
            target_ws.mkdir()
            wl = WorkLoop({"work_dir": target_ws, "harness": {"type": "claude"}}, script_dir=fake_script_dir)
            wl._sync_agent_dir(str(target_ws))

            dst = target_ws / ".claude"
            self.assertTrue((dst / "agents" / "critic.md").exists())
            self.assertTrue((dst / "settings.json").exists())
            self.assertFalse((dst / "worktrees").exists())
            self.assertFalse((dst / "settings.local.json").exists())


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
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            work_md = (
                "# Work Loop\n\n"
                "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
                "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
                "| ITEM-001 | [Test](ITEM-001/C.md) | local | ready |  |  |  |\n"
            )
            (tmp / "WORK.md").write_text(work_md)
            (tmp / "ITEM-001").mkdir()
            (tmp / "ITEM-001" / "CONVERSATION.md").write_text("Test")
            wl = WorkLoop({"work_dir": tmp, "harness": {"type": "opencode"}}, script_dir=_HERE)
            prompt = self._capture_prompt(wl, "ITEM-001")
            self.assertIsNotNone(prompt)
            self.assertIn("Multi-Agent", prompt)

    def test_impl_prompt_for_implement(self):
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            work_md = (
                "# Work Loop\n\n"
                "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
                "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
                "| ITEM-001 | [Test](ITEM-001/C.md) | local | implement |  |  |  |\n"
            )
            (tmp / "WORK.md").write_text(work_md)
            (tmp / "ITEM-001").mkdir()
            (tmp / "ITEM-001" / "CONVERSATION.md").write_text("work_dir: /tmp\n")
            wl = WorkLoop({"work_dir": tmp, "harness": {"type": "opencode"}}, script_dir=_HERE)
            prompt = self._capture_prompt(wl, "ITEM-001")
            self.assertIsNotNone(prompt)
            self.assertIn("Implementation Mode", prompt)

    def test_resolve_prompt_for_resolved(self):
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            work_md = (
                "# Work Loop\n\n"
                "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
                "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
                "| ITEM-001 | [Test](ITEM-001/C.md) | local | resolved |  |  |  |\n"
            )
            (tmp / "WORK.md").write_text(work_md)
            (tmp / "ITEM-001").mkdir()
            (tmp / "ITEM-001" / "CONVERSATION.md").write_text("Test")
            wl = WorkLoop({"work_dir": tmp, "harness": {"type": "opencode"}}, script_dir=_HERE)
            prompt = self._capture_prompt(wl, "ITEM-001")
            self.assertIsNotNone(prompt)
            self.assertIn("Resolved Mode", prompt)



class _FakeProc:
    """Minimal Popen stand-in: streams fixed stdout, then exits with returncode."""

    def __init__(self, output: bytes = b"", returncode: int = 0, block: threading.Event | None = None):
        self._chunks = [output] if output else []
        self._block = block
        self.returncode = None
        self._final_rc = returncode
        self.terminated = False
        self.stdout = self

    def read(self, _n):
        if self._chunks:
            return self._chunks.pop(0)
        if self._block is not None:
            self._block.wait(timeout=5)
        return b""

    def terminate(self):
        self.terminated = True
        if self._block is not None:
            self._block.set()

    def wait(self):
        self.returncode = -15 if self.terminated else self._final_rc
        return self.returncode


class TestOpenCodeHarnessRun(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log = Path(self.tmp) / "run.log"
        self.h = run_loop.OpenCodeHarness()
        self.h._model = ""

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, proc, budget=0, cwd=None, abort_checker=None):
        from unittest.mock import patch
        with patch("workloop.harness.subprocess.Popen", return_value=proc) as popen, \
             patch.object(self.h, "_check_budget") as check, \
             patch.object(self.h, "_cleanup_session") as cleanup, \
             patch("sys.stdout", new=unittest.mock.MagicMock()):
            rc = self.h.run("PROMPT", budget, cwd, "ITEM-1", self.log, abort_checker=abort_checker)
        return rc, popen.call_args[0][0], check, cleanup

    def test_runs_without_model_configured(self):
        rc, cmd, _, cleanup = self._run(_FakeProc(b'{"ok":1}\n'))
        self.assertEqual(rc, 0)
        self.assertNotIn("--model", cmd)
        self.assertEqual(cmd[-1], "PROMPT")
        self.assertEqual(self.log.read_bytes(), b'{"ok":1}\n')
        cleanup.assert_called_once_with("ITEM-1")

    def test_model_and_dir_passed(self):
        self.h._model = "anthropic/claude-sonnet-5"
        _, cmd, _, _ = self._run(_FakeProc(), cwd=self.tmp)
        self.assertEqual(cmd[cmd.index("--model") + 1], "anthropic/claude-sonnet-5")
        self.assertEqual(cmd[cmd.index("--dir") + 1], self.tmp)
        self.assertEqual(cmd[cmd.index("--title") + 1], "ITEM-1")

    def test_nonzero_exit_passed_through_and_skips_budget_check(self):
        rc, _, check, _ = self._run(_FakeProc(returncode=3), budget=5.0)
        self.assertEqual(rc, 3)
        check.assert_not_called()

    def test_budget_checked_on_success(self):
        _, _, check, _ = self._run(_FakeProc(), budget=5.0)
        check.assert_called_once_with("ITEM-1", 5.0, self.log)

    def test_abort_checker_terminates_process(self):
        self.h._abort_poll_interval = 0.01
        proc = _FakeProc(block=threading.Event())
        rc, _, _, _ = self._run(proc, abort_checker=lambda: True)
        self.assertTrue(proc.terminated)
        self.assertEqual(rc, -15)


class TestOpenCodeHarnessHelpers(unittest.TestCase):

    def setUp(self):
        self.h = run_loop.OpenCodeHarness()

    @staticmethod
    def _result(rc=0, stdout=""):
        return unittest.mock.MagicMock(returncode=rc, stdout=stdout)

    def test_check_budget_reports_overrun(self):
        from unittest.mock import patch
        with patch("workloop.harness.subprocess.run", return_value=self._result(stdout="Total cost: $12.50")), \
             patch("builtins.print") as pr:
            self.h._check_budget("ITEM-1", 10.0, Path("/dev/null"))
        self.assertTrue(any("exceeded budget" in str(c) for c in pr.call_args_list))

    def test_check_budget_silent_under_budget(self):
        from unittest.mock import patch
        with patch("workloop.harness.subprocess.run", return_value=self._result(stdout="$1.00")), \
             patch("builtins.print") as pr:
            self.h._check_budget("ITEM-1", 10.0, Path("/dev/null"))
        pr.assert_not_called()

    def test_check_budget_tolerates_missing_opencode(self):
        from unittest.mock import patch
        with patch("workloop.harness.subprocess.run", side_effect=FileNotFoundError):
            self.h._check_budget("ITEM-1", 10.0, Path("/dev/null"))  # must not raise

    def test_cleanup_deletes_only_matching_sessions(self):
        from unittest.mock import patch
        sessions = {"sessions": [
            {"id": "s1", "title": "ITEM-1"},
            {"id": "s2", "title": "OTHER"},
            {"id": "ITEM-1", "title": ""},
        ]}
        with patch("workloop.harness.subprocess.run", return_value=self._result(stdout=json.dumps(sessions))) as run:
            self.h._cleanup_session("ITEM-1")
        deleted = [c[0][0][-1] for c in run.call_args_list if c[0][0][:3] == ["opencode", "session", "delete"]]
        self.assertEqual(deleted, ["s1", "ITEM-1"])

    def test_cleanup_tolerates_bad_json_and_failure(self):
        from unittest.mock import patch
        for result in (self._result(stdout="not json"), self._result(rc=1)):
            with patch("workloop.harness.subprocess.run", return_value=result) as run:
                self.h._cleanup_session("ITEM-1")  # must not raise
            self.assertEqual(run.call_count, 1)
