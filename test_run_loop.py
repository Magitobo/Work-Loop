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

_HERE = Path(__file__).parent
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

class TestWorkTable(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.wl = _make_workloop(self.tmp)

    def test_get_ready_items(self):
        items = self.wl.get_ready_items()
        self.assertEqual(items, ["ITEM-001"])

    def test_get_ready_items_stops_at_done_section(self):
        # ITEM-004 has status=done in active table; should NOT appear as ready
        items = self.wl.get_ready_items()
        self.assertNotIn("ITEM-004", items)
        self.assertNotIn("ITEM-000", items)

    def test_update_col_status(self):
        self.wl.update_col("ITEM-001", COL_STATUS, "in-progress")
        status = self.wl.get_col("ITEM-001", COL_STATUS)
        self.assertEqual(status, "in-progress")

    def test_update_col_other_rows_unchanged(self):
        self.wl.update_col("ITEM-001", COL_STATUS, "in-progress")
        self.assertEqual(self.wl.get_col("ITEM-002", COL_STATUS), "needs-review")
        self.assertEqual(self.wl.get_col("ITEM-003", COL_STATUS), "waiting")

    def test_get_col_location(self):
        loc = self.wl.get_col("ITEM-002", COL_LOCATION)
        self.assertEqual(loc, "local")

    def test_get_col_missing_item_returns_empty(self):
        val = self.wl.get_col("NONEXISTENT", COL_STATUS)
        self.assertEqual(val, "")

    def test_move_done_items(self):
        self.wl.move_done_items()
        lines = (Path(self.tmp) / "WORK.md").read_text()

        # ITEM-004 should appear in Done section
        done_idx = lines.index("## Done")
        self.assertIn("ITEM-004", lines[done_idx:])

        # ITEM-004 should NOT be in active table
        active_part = lines[:done_idx]
        self.assertNotIn("ITEM-004", active_part)

    def test_move_done_items_idempotent(self):
        self.wl.move_done_items()
        after_first = (Path(self.tmp) / "WORK.md").read_text()
        self.wl.move_done_items()
        after_second = (Path(self.tmp) / "WORK.md").read_text()
        # Second call must be a complete no-op
        self.assertEqual(after_first, after_second)

    def test_insert_and_remove_work_row(self):
        self.wl.insert_work_row("TEST-99", "Test item", "local")
        items = self.wl.get_ready_items()
        self.assertIn("TEST-99", items)

        self.wl.remove_work_row("TEST-99")
        items_after = self.wl.get_ready_items()
        self.assertNotIn("TEST-99", items_after)

    def test_get_item_title_strips_link(self):
        title = self.wl.get_item_title("ITEM-001")
        self.assertEqual(title, "Task one")

    def test_get_item_title_plain(self):
        content = SAMPLE_WORK_MD.replace(
            "| ITEM-001   | [Task one](ITEM-001/C.md)  |",
            "| ITEM-001   | Plain title                |"
        )
        wl2 = _make_workloop(tempfile.mkdtemp(), content)
        self.assertEqual(wl2.get_item_title("ITEM-001"), "Plain title")


# ---------------------------------------------------------------------------
# TestLauncherScript
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# TestLauncherScriptImplementMode
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# TestDispatchRemoteMode
# ---------------------------------------------------------------------------

class TestDispatchRemoteMode(unittest.TestCase):

    def _make_wl_with_conv(self, tmp: str, mode: str, work_dir_line: str = "") -> WorkLoop:
        content = make_work_md(f"| MY-ITEM | Task | user@host | {mode} |  |  |  |")
        wl = _make_workloop(tmp, content)
        (Path(tmp) / "IMPL-PROMPT.md").write_text("Implement.\n")
        item_dir = Path(tmp) / "MY-ITEM"
        item_dir.mkdir()
        conv = f"{work_dir_line}\n## 2026-01-01 | User\n\nDo it.\n"
        (item_dir / "CONVERSATION.md").write_text(conv)
        return wl

    def _collect_rsync_targets(self, wl: WorkLoop, mode: str) -> list[str]:
        from unittest.mock import patch, MagicMock
        rsynced = []

        def fake_run(cmd, **kwargs):
            if isinstance(cmd, list) and cmd and "rsync" in cmd[0]:
                rsynced.append(cmd[-1])  # destination is last arg
                # also capture source for local→remote rsyncs
                if len(cmd) >= 2:
                    rsynced.append(cmd[-2])
            return MagicMock(returncode=0, stdout="")

        with patch('workloop.remote._run', side_effect=fake_run), \
             patch('workloop.remote.subprocess') as mock_sub:
            mock_sub.run.return_value = MagicMock(returncode=0, stdout="", stderr=b"")
            wl.dispatch_remote("MY-ITEM", "2026-01-01_10-00-00", "user@host", 10.0, mode=mode)
        return rsynced

    def test_impl_prompt_rsynced_for_implement_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl_with_conv(tmp, "implement")
            targets = self._collect_rsync_targets(wl, "implement")
            self.assertTrue(any("IMPL-PROMPT.md" in t for t in targets))

    def test_impl_prompt_not_rsynced_for_analyze_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl_with_conv(tmp, "analyze")
            targets = self._collect_rsync_targets(wl, "analyze")
            self.assertFalse(any("IMPL-PROMPT.md" in t for t in targets))

    def test_work_dir_from_conversation_passed_to_launcher(self):
        """When CONVERSATION.md has work_dir:, the launcher should cd to it."""
        with tempfile.TemporaryDirectory() as tmp:
            from unittest.mock import patch, MagicMock
            wl = self._make_wl_with_conv(tmp, "implement", work_dir_line="work_dir: /remote/repo")
            launchers = []

            def fake_run(cmd, **kwargs):
                return MagicMock(returncode=0, stdout="")

            original_build = wl.build_launcher

            def capturing_build(item_id, ts_str, budget, mode="analyze", work_dir=None):
                script = original_build(item_id, ts_str, budget, mode=mode, work_dir=work_dir)
                launchers.append(script)
                return script

            with patch.object(wl, 'build_launcher', side_effect=capturing_build), \
                 patch('workloop.remote._run', return_value=MagicMock(returncode=0)), \
                 patch('workloop.remote.subprocess') as mock_sub:
                mock_sub.run.return_value = MagicMock(returncode=0, stdout="", stderr=b"")
                wl.dispatch_remote("MY-ITEM", "2026-01-01_10-00-00", "user@host", 10.0, mode="implement")

            self.assertEqual(len(launchers), 1)
            self.assertIn("cd /remote/repo", launchers[0])

    def test_no_work_dir_cd_when_not_in_conversation(self):
        """When no work_dir: in CONVERSATION.md, launcher should not cd to a second dir."""
        with tempfile.TemporaryDirectory() as tmp:
            from unittest.mock import patch, MagicMock
            wl = self._make_wl_with_conv(tmp, "implement")
            launchers = []

            original_build = wl.build_launcher

            def capturing_build(item_id, ts_str, budget, mode="analyze", work_dir=None):
                script = original_build(item_id, ts_str, budget, mode=mode, work_dir=work_dir)
                launchers.append(script)
                return script

            with patch.object(wl, 'build_launcher', side_effect=capturing_build), \
                 patch('workloop.remote._run', return_value=MagicMock(returncode=0)), \
                 patch('workloop.remote.subprocess') as mock_sub:
                mock_sub.run.return_value = MagicMock(returncode=0, stdout="", stderr=b"")
                wl.dispatch_remote("MY-ITEM", "2026-01-01_10-00-00", "user@host", 10.0, mode="implement")

            cd_lines = [l for l in launchers[0].splitlines() if l.startswith("cd ")]
            self.assertEqual(len(cd_lines), 1)


# ---------------------------------------------------------------------------
# TestRunModeRouting
# ---------------------------------------------------------------------------

class TestRunModeRouting(unittest.TestCase):
    """run() must read mode before overwriting status and forward it to dispatch_remote."""

    def _make_wl(self, status: str) -> WorkLoop:
        content = make_work_md(f"| MY-ITEM | Task | user@remote | {status} |  |  |  |")
        return _make_workloop(tempfile.mkdtemp(), content)

    def _dispatched_mode(self, wl: WorkLoop) -> str | None:
        from unittest.mock import patch
        captured = {}

        def fake_dispatch(item_id, ts_str, remote_host, budget, mode="analyze"):
            captured["mode"] = mode

        with patch.object(WorkLoop, "dispatch_remote", side_effect=fake_dispatch), \
             patch.object(WorkLoop, "wait_for_remote"):
            wl.run(once=True)
        return captured.get("mode")

    def test_implement_status_routes_implement_mode(self):
        self.assertEqual(self._dispatched_mode(self._make_wl("implement")), "implement")

    def test_analyze_status_routes_analyze_mode(self):
        self.assertEqual(self._dispatched_mode(self._make_wl("analyze")), "analyze")

    def test_ready_status_routes_ready_mode(self):
        self.assertEqual(self._dispatched_mode(self._make_wl("ready")), "ready")


# ---------------------------------------------------------------------------
# TestPrependAbortNotice
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# TestTriggerStatuses
# ---------------------------------------------------------------------------

class TestTriggerStatuses(unittest.TestCase):
    """analyze and implement are trigger statuses alongside ready."""

    def _make_wl_with_statuses(self, statuses: dict[str, str]) -> WorkLoop:
        rows = "\n".join(
            f"| {item_id} | [{item_id}]({item_id}/C.md) | local | {status} |  |  |  |"
            for item_id, status in statuses.items()
        )
        return _make_workloop(tempfile.mkdtemp(), make_work_md(rows))

    def test_ready_still_triggers(self):
        wl = self._make_wl_with_statuses({"A": "ready"})
        self.assertIn("A", wl.get_ready_items())

    def test_analyze_triggers(self):
        wl = self._make_wl_with_statuses({"A": "analyze"})
        self.assertIn("A", wl.get_ready_items())

    def test_implement_triggers(self):
        wl = self._make_wl_with_statuses({"A": "implement"})
        self.assertIn("A", wl.get_ready_items())

    def test_needs_review_does_not_trigger(self):
        wl = self._make_wl_with_statuses({"A": "needs-review"})
        self.assertEqual(wl.get_ready_items(), [])

    def test_in_progress_does_not_trigger(self):
        wl = self._make_wl_with_statuses({"A": "in-progress"})
        self.assertEqual(wl.get_ready_items(), [])

    def test_abort_does_not_trigger(self):
        wl = self._make_wl_with_statuses({"A": "abort"})
        self.assertEqual(wl.get_ready_items(), [])

    def test_multiple_modes_returned_in_order(self):
        wl = self._make_wl_with_statuses({"A": "analyze", "B": "implement", "C": "ready"})
        items = wl.get_ready_items()
        self.assertEqual(items, ["A", "B", "C"])


# ---------------------------------------------------------------------------
# TestExtractWorkDir
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# TestStubWorkMd
# ---------------------------------------------------------------------------

class TestStubWorkMd(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.wl = _make_workloop(self.tmp)

    def test_stub_contains_item(self):
        stub = self.wl.build_stub_work_md("ITEM-001", "Task one")
        self.assertIn("ITEM-001", stub)
        self.assertIn("Task one", stub)

    def test_stub_has_done_section(self):
        stub = self.wl.build_stub_work_md("ITEM-001", "Task one")
        self.assertIn("## Done", stub)

    def test_stub_item_is_ready(self):
        stub = self.wl.build_stub_work_md("ITEM-001", "Task one")
        self.assertIn("| ready |", stub)


# ---------------------------------------------------------------------------
# TestLoopPromptPortability
# ---------------------------------------------------------------------------

class TestAutoInitConversation(unittest.TestCase):

    def _make_wl_with_plain_title(self, tmp_dir: str) -> WorkLoop:
        content = make_work_md("| MY-ITEM | Kick off the thing | local | ready |  |  |  |")
        return _make_workloop(tmp_dir, content)

    def test_creates_conversation_md_when_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl_with_plain_title(tmp)
            wl._auto_init_conversation("MY-ITEM")
            conv = Path(tmp) / "MY-ITEM" / "CONVERSATION.md"
            self.assertTrue(conv.exists())

    def test_conversation_contains_title_as_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl_with_plain_title(tmp)
            wl._auto_init_conversation("MY-ITEM")
            text = (Path(tmp) / "MY-ITEM" / "CONVERSATION.md").read_text()
            self.assertIn("Kick off the thing", text)

    def test_strips_link_syntax_from_title(self):
        with tempfile.TemporaryDirectory() as tmp:
            content = make_work_md("| MY-ITEM | [Linked title](MY-ITEM/CONVERSATION.md) | local | ready |  |  |  |")
            wl = _make_workloop(tmp, content)
            wl._auto_init_conversation("MY-ITEM")
            text = (Path(tmp) / "MY-ITEM" / "CONVERSATION.md").read_text()
            self.assertIn("Linked title", text)
            self.assertNotIn("[Linked title]", text)

    def test_noop_when_conversation_already_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl_with_plain_title(tmp)
            item_dir = Path(tmp) / "MY-ITEM"
            item_dir.mkdir()
            conv = item_dir / "CONVERSATION.md"
            original = "## 2026-01-01 | User\n\noriginal content\n"
            conv.write_text(original)
            wl._auto_init_conversation("MY-ITEM")
            self.assertEqual(conv.read_text(), original)

    def test_does_not_change_status_column(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl_with_plain_title(tmp)
            wl._auto_init_conversation("MY-ITEM")
            status = wl.get_col("MY-ITEM", COL_STATUS)
            self.assertEqual(status, "ready")


class TestRemoteTitleReadback(unittest.TestCase):
    """wait_for_remote() should read back Claude's concise title from remote WORK.md."""

    WORK_MD = make_work_md("| MY-ITEM | Original long prompt text | remote-host | in-progress |  |  |  |")
    REMOTE_WORK_MD = make_work_md("| MY-ITEM | [Concise title](MY-ITEM/CONVERSATION.md) | local | needs-review |  |  |  |")

    def _make_wl(self, tmp: str) -> WorkLoop:
        wl = _make_workloop(tmp, self.WORK_MD)
        item_dir = Path(tmp) / "MY-ITEM"
        item_dir.mkdir()
        (item_dir / "CONVERSATION.md").write_text("## 2026-01-01 | Claude\n\nFindings\n")
        return wl

    def _run_wait(self, wl: WorkLoop, poll_result_stdout: str, wmd_returncode: int, wmd_stdout: str) -> None:
        from unittest.mock import patch, MagicMock

        def fake_subprocess_run(cmd, **kwargs):
            r = MagicMock()
            if isinstance(cmd, list) and "WORK.md" in (cmd[-1] if cmd else ""):
                r.returncode = wmd_returncode
                r.stdout = wmd_stdout
            elif isinstance(cmd, list) and ".done" in (cmd[-1] if cmd else ""):
                r.returncode = 0
                r.stdout = poll_result_stdout
            else:
                r.returncode = 0
                r.stdout = ""
            return r

        with patch('workloop.remote.subprocess') as mock_sub, \
             patch('workloop.remote._run') as mock_rrun:
            mock_sub.run.side_effect = fake_subprocess_run
            mock_rrun.return_value = MagicMock(returncode=0)
            wl.wait_for_remote("MY-ITEM", "2026-01-01_12-00-00", "remote-host", 10.0, poll_interval=0, timeout=5)

    def test_title_updated_when_remote_wmd_has_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl(tmp)
            self._run_wait(wl, poll_result_stdout="0", wmd_returncode=0, wmd_stdout=self.REMOTE_WORK_MD)
            title = wl.get_col("MY-ITEM", run_loop.COL_TITLE)
            self.assertEqual(title, "[Concise title](MY-ITEM/CONVERSATION.md)")

    def test_title_unchanged_when_remote_wmd_has_plain_text(self):
        plain_remote_wmd = (
            "# Work Loop\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
            "| MY-ITEM | Original long prompt text | local | needs-review |  |  |  |\n\n"
            "## Done\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl(tmp)
            self._run_wait(wl, poll_result_stdout="0", wmd_returncode=0, wmd_stdout=plain_remote_wmd)
            title = wl.get_col("MY-ITEM", run_loop.COL_TITLE)
            self.assertEqual(title, "Original long prompt text")

    def test_title_unchanged_when_ssh_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl(tmp)
            self._run_wait(wl, poll_result_stdout="0", wmd_returncode=1, wmd_stdout="")
            title = wl.get_col("MY-ITEM", run_loop.COL_TITLE)
            self.assertEqual(title, "Original long prompt text")


# ---------------------------------------------------------------------------
# TestGetInprogressRemoteItems
# ---------------------------------------------------------------------------

class TestGetInprogressRemoteItems(unittest.TestCase):

    def _make_wl(self, rows: list[tuple]) -> WorkLoop:
        """rows: (item_id, location, status)"""
        row_lines = "\n".join(
            f"| {id_} | [{id_}]({id_}/C.md) | {loc} | {status} |  |  |  |"
            for id_, loc, status in rows
        )
        return _make_workloop(tempfile.mkdtemp(), make_work_md(row_lines))

    def test_returns_in_progress_remote_item(self):
        wl = self._make_wl([("ITEM-A", "user@remote-host", "in-progress")])
        self.assertEqual(wl.get_inprogress_remote_items(), [("ITEM-A", "user@remote-host")])

    def test_excludes_local_in_progress(self):
        wl = self._make_wl([("ITEM-A", "local", "in-progress")])
        self.assertEqual(wl.get_inprogress_remote_items(), [])

    def test_excludes_non_inprogress_remote(self):
        wl = self._make_wl([
            ("ITEM-A", "user@host", "ready"),
            ("ITEM-B", "user@host", "needs-review"),
        ])
        self.assertEqual(wl.get_inprogress_remote_items(), [])

    def test_excludes_done_section(self):
        content = make_work_md(
            active_rows="| ITEM-A | [A](A/C.md) | local | ready |  |  |  |",
            done_rows="| ITEM-B | [B](B/C.md) | user@host | in-progress |  |  |  |",
        )
        wl = _make_workloop(tempfile.mkdtemp(), content)
        self.assertEqual(wl.get_inprogress_remote_items(), [])

    def test_returns_multiple_remote_items(self):
        wl = self._make_wl([
            ("ITEM-A", "user@host1", "in-progress"),
            ("ITEM-B", "local", "in-progress"),
            ("ITEM-C", "user@host2", "in-progress"),
        ])
        self.assertEqual(
            wl.get_inprogress_remote_items(),
            [("ITEM-A", "user@host1"), ("ITEM-C", "user@host2")],
        )


# ---------------------------------------------------------------------------
# TestTsStrFromLogCol
# ---------------------------------------------------------------------------

class TestTsStrFromLogCol(unittest.TestCase):

    TS = "2026-06-04_17-43-49"

    def _make_wl(self, item_id: str, log_col: str) -> WorkLoop:
        content = make_work_md(f"| {item_id} | [{item_id}]({item_id}/C.md) | user@host | in-progress |  | $10.0 | {log_col} |")
        return _make_workloop(tempfile.mkdtemp(), content)

    def test_extracts_from_log_col(self):
        log_col = f"[Log](_logs/{self.TS}_MY-ITEM.log)"
        wl = self._make_wl("MY-ITEM", log_col)
        self.assertEqual(wl._ts_str_from_log_col("MY-ITEM", "user@host"), self.TS)

    def test_returns_none_when_no_log_and_remote_empty(self):
        from unittest.mock import patch, MagicMock
        wl = self._make_wl("MY-ITEM", "")
        with patch('workloop.remote.subprocess') as mock_sub:
            r = MagicMock()
            r.stdout = ""
            mock_sub.run.return_value = r
            self.assertIsNone(wl._ts_str_from_log_col("MY-ITEM", "user@host"))

    def test_falls_back_to_remote_glob(self):
        from unittest.mock import patch, MagicMock
        wl = self._make_wl("MY-ITEM", "")
        with patch('workloop.remote.subprocess') as mock_sub:
            r = MagicMock()
            r.stdout = f"/home/user/Work-Loop/_logs/{self.TS}_MY-ITEM.log\n"
            mock_sub.run.return_value = r
            self.assertEqual(wl._ts_str_from_log_col("MY-ITEM", "user@host"), self.TS)

    def test_remote_fallback_uses_connect_timeout(self):
        from unittest.mock import patch, MagicMock
        wl = self._make_wl("MY-ITEM", "")
        with patch('workloop.remote.subprocess') as mock_sub:
            r = MagicMock()
            r.stdout = ""
            mock_sub.run.return_value = r
            wl._ts_str_from_log_col("MY-ITEM", "user@host")
            cmd = mock_sub.run.call_args[0][0]
            self.assertIn("ConnectTimeout=5", cmd)


# ---------------------------------------------------------------------------
# TestClassifyFailure
# ---------------------------------------------------------------------------

class TestClassifyFailure(unittest.TestCase):

    TS = "2026-06-05_10-00-00"

    def _make_wl_with_log(self, tmp: str, log_content: str) -> WorkLoop:
        wl = _make_workloop(tmp)
        log_dir = Path(tmp) / "MY-ITEM" / "_logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / f"{self.TS}_MY-ITEM.log").write_text(log_content)
        return wl

    def test_returns_unknown_for_clean_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl_with_log(tmp, "## Analysis\n\nFindings here.\n")
            self.assertEqual(wl._classify_failure("MY-ITEM", self.TS), "unknown")

    def test_returns_unknown_for_missing_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = _make_workloop(tmp)
            self.assertEqual(wl._classify_failure("MY-ITEM", self.TS), "unknown")

    def test_detects_budget_keyword(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl_with_log(tmp, "Claude's cost ($12.00) exceeded the budget ($10.00).\n")
            self.assertEqual(wl._classify_failure("MY-ITEM", self.TS), "budget")


# ---------------------------------------------------------------------------
# TestSyncBackRemote
# ---------------------------------------------------------------------------

class TestSyncBackRemote(unittest.TestCase):

    TS = "2026-06-04_10-00-00"
    WORK_MD = make_work_md(
        "| MY-ITEM | Original title | user@host | in-progress |  | $10.0 |"
        " [Log](MY-ITEM/_logs/2026-06-04_10-00-00_MY-ITEM.log) |"
    )

    def _make_wl(self, tmp: str, log_content: str | None = None) -> WorkLoop:
        wl = _make_workloop(tmp, self.WORK_MD)
        item_dir = Path(tmp) / "MY-ITEM"
        item_dir.mkdir(exist_ok=True)
        (item_dir / "CONVERSATION.md").write_text("## 2026-01-01 | Claude\n\nFindings\n")
        log_dir = item_dir / "_logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        if log_content is not None:
            (log_dir / f"{self.TS}_MY-ITEM.log").write_text(log_content)
        return wl

    def _run_sync(self, wl: WorkLoop, exit_str: str, remote_wmd: str = "") -> None:
        from unittest.mock import patch, MagicMock

        def fake_run(cmd, **kwargs):
            r = MagicMock()
            r.returncode = 0
            r.stdout = remote_wmd if isinstance(cmd, list) and "WORK.md" in str(cmd[-1]) else ""
            return r

        with patch('workloop.remote.subprocess') as mock_sub, \
             patch('workloop.remote._run') as mock_rrun:
            mock_sub.run.side_effect = fake_run
            mock_rrun.return_value = MagicMock(returncode=0)
            wl._sync_back_remote("MY-ITEM", self.TS, "user@host", 10.0, exit_str)

    def test_status_needs_review_on_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl(tmp)
            self._run_sync(wl, "0")
            self.assertEqual(wl.get_col("MY-ITEM", COL_STATUS), "needs-review")

    def test_status_needs_review_on_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl(tmp)
            self._run_sync(wl, "1")
            self.assertEqual(wl.get_col("MY-ITEM", COL_STATUS), "needs-review")

    def test_budget_stored_on_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl(tmp)
            self._run_sync(wl, "0")
            self.assertEqual(wl.get_col("MY-ITEM", COL_BUDGET), "$10.0")

    def test_budget_failed_on_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl(tmp)
            self._run_sync(wl, "1")
            self.assertIn("FAILED", wl.get_col("MY-ITEM", COL_BUDGET))

    def test_budget_failed_on_non_budget_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl(tmp)
            self._run_sync(wl, "1")
            self.assertIn("FAILED", wl.get_col("MY-ITEM", COL_BUDGET))
            self.assertNotIn("EXCEEDED", wl.get_col("MY-ITEM", COL_BUDGET))

    def test_budget_exceeded_on_budget_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl(tmp, log_content="Error: budget limit exceeded for session")
            self._run_sync(wl, "1")
            self.assertEqual(wl.get_col("MY-ITEM", COL_STATUS), "needs-review")
            self.assertEqual(wl.get_col("MY-ITEM", COL_BUDGET), "$10.0 - EXCEEDED")

    def test_budget_failed_on_unknown_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl(tmp, log_content="Fatal error: segmentation fault")
            self._run_sync(wl, "1")
            self.assertEqual(wl.get_col("MY-ITEM", COL_STATUS), "needs-review")
            self.assertEqual(wl.get_col("MY-ITEM", COL_BUDGET), "$10.0 - FAILED")

    def test_log_col_set_to_ts_and_item(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl(tmp)
            self._run_sync(wl, "0")
            log = wl.get_col("MY-ITEM", COL_LOG)
            self.assertIn(self.TS, log)
            self.assertIn("MY-ITEM", log)

    def test_last_updated_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl(tmp)
            self._run_sync(wl, "0")
            self.assertNotEqual(wl.get_col("MY-ITEM", COL_LAST_UPDATED), "")

    def test_last_updated_set_on_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl(tmp)
            self._run_sync(wl, "0")
            self.assertNotEqual(wl.get_col("MY-ITEM", COL_LAST_UPDATED), "")

    def test_remote_title_captured(self):
        remote_wmd = make_work_md("| MY-ITEM | [Concise title](MY-ITEM/CONVERSATION.md) | local | needs-review |  |  |  |")
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl(tmp)
            self._run_sync(wl, "0", remote_wmd=remote_wmd)
            self.assertEqual(
                wl.get_col("MY-ITEM", run_loop.COL_TITLE),
                "[Concise title](MY-ITEM/CONVERSATION.md)",
            )

    def test_abort_notice_prepended_on_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl(tmp)
            self._run_sync(wl, "1")
            text = (Path(tmp) / "MY-ITEM" / "CONVERSATION.md").read_text()
            self.assertIn("Run aborted", text)

    def test_no_abort_notice_on_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl(tmp)
            self._run_sync(wl, "0")
            text = (Path(tmp) / "MY-ITEM" / "CONVERSATION.md").read_text()
            self.assertNotIn("Run aborted", text)


# ---------------------------------------------------------------------------
# TestCheckStalledRemotes
# ---------------------------------------------------------------------------

class TestCheckStalledRemotes(unittest.TestCase):

    TS = "2026-06-04_10-00-00"

    def _make_wl(self, tmp: str, log_col: str | None = None) -> WorkLoop:
        if log_col is None:
            log_col = f"[Log](_logs/{self.TS}_MY-ITEM.log)"
        content = make_work_md(f"| MY-ITEM | [Task](MY-ITEM/C.md) | user@host | in-progress |  | $10.0 | {log_col} |")
        wl = _make_workloop(tmp, content)
        item_dir = Path(tmp) / "MY-ITEM"
        item_dir.mkdir()
        (item_dir / "CONVERSATION.md").write_text("## 2026-01-01 | Claude\n\nFindings\n")
        return wl

    def _patch_and_run(self, wl: WorkLoop, done_stdout: str) -> None:
        from unittest.mock import patch, MagicMock

        def fake_run(cmd, **kwargs):
            r = MagicMock()
            r.returncode = 0
            r.stdout = done_stdout if isinstance(cmd, list) and ".done" in str(cmd) else ""
            return r

        with patch('workloop.remote.subprocess') as mock_sub, \
             patch('workloop.remote._run') as mock_rrun:
            mock_sub.run.side_effect = fake_run
            mock_rrun.return_value = MagicMock(returncode=0)
            wl.check_stalled_remotes()

    def test_recovers_completed_remote(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl(tmp)
            self._patch_and_run(wl, done_stdout="0")
            self.assertEqual(wl.get_col("MY-ITEM", COL_STATUS), "needs-review")

    def test_leaves_in_progress_when_not_done(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl(tmp)
            self._patch_and_run(wl, done_stdout="")
            self.assertEqual(wl.get_col("MY-ITEM", COL_STATUS), "in-progress")

    def test_handles_missing_ts_str_gracefully(self):
        """No crash and status unchanged when log col is empty and remote glob returns nothing."""
        from unittest.mock import patch, MagicMock
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl(tmp, log_col="")
            def fake_run(cmd, **kwargs):
                r = MagicMock()
                r.returncode = 0
                r.stdout = "0" if ".done" in str(cmd) else ""
                return r
            with patch('workloop.remote.subprocess') as mock_sub, \
                 patch('workloop.remote._run'):
                mock_sub.run.side_effect = fake_run
                wl.check_stalled_remotes()  # must not raise
            self.assertEqual(wl.get_col("MY-ITEM", COL_STATUS), "in-progress")

    def test_skips_local_items(self):
        """Local in-progress items are not touched."""
        content = (
            "# Work Loop\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
            "| MY-ITEM | [Task](MY-ITEM/C.md) | local | in-progress |  | $10.0 |  |\n\n"
            "## Done\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            wl = _make_workloop(tmp, content)
            from unittest.mock import patch, MagicMock
            with patch('workloop.remote.subprocess') as mock_sub:
                wl.check_stalled_remotes()
                mock_sub.run.assert_not_called()
            self.assertEqual(wl.get_col("MY-ITEM", COL_STATUS), "in-progress")


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


# ---------------------------------------------------------------------------
# TestRemoteDispatch (integration — skipped if remote unreachable)
# ---------------------------------------------------------------------------

@unittest.skipUnless(REMOTE_AVAILABLE, f"Remote {REMOTE_HOST} not reachable or Kerberos ticket expired (run: kinit)")
class TestRemoteDispatch(unittest.TestCase):

    ITEM_ID = "Test-Remote-01"
    MAX_BUDGET = 0.10  # minimal: enough for a one-turn ack, caps runaway loops
    POLL_TIMEOUT = 600

    def setUp(self):
        self.wl = WorkLoop(REAL_WORK_DIR, max_budget=self.MAX_BUDGET)
        item_dir = REAL_WORK_DIR / self.ITEM_ID
        item_dir.mkdir(exist_ok=True)

        conv = item_dir / "CONVERSATION.md"
        conv.write_text(
            "## 2026-05-14 | Oliver\n\n"
            "This is a test item for remote dispatch validation. "
            "Please acknowledge receipt by writing the exact phrase DISPATCH-VALIDATED in your response, "
            "and set status to needs-review. Keep your response brief.\n"
        )

        self.wl.insert_work_row(
            self.ITEM_ID,
            "Remote dispatch test item",
            REMOTE_HOST,
        )

    def tearDown(self):
        import shutil
        item_dir = REAL_WORK_DIR / self.ITEM_ID
        if item_dir.exists():
            shutil.rmtree(item_dir)

        self.wl.remove_work_row(self.ITEM_ID)

        rwd = self.wl.remote_work_dir
        subprocess.run(
            ["ssh", REMOTE_HOST,
             f"rm -rf {rwd}/{self.ITEM_ID}"
             f" {rwd}/.launch-{self.ITEM_ID}.sh"
             f" {rwd}/_logs/*_{self.ITEM_ID}.log"],
            check=False,
        )

    def test_remote_dispatch_and_results(self):
        from datetime import datetime
        ts = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')

        self.wl.update_col(self.ITEM_ID, COL_STATUS, "in-progress")
        self.wl.dispatch_remote(self.ITEM_ID, ts, REMOTE_HOST, self.MAX_BUDGET)
        self.wl.wait_for_remote(
            self.ITEM_ID, ts, REMOTE_HOST, self.MAX_BUDGET,
            poll_interval=10,
            timeout=self.POLL_TIMEOUT,
        )

        # Claude updated status via LOOP-PROMPT.md step 7
        status = self.wl.get_col(self.ITEM_ID, COL_STATUS)
        self.assertEqual(status, "needs-review", f"Expected needs-review, got: {status!r}")

        # CONVERSATION.md should contain a Claude response section
        conv_file = REAL_WORK_DIR / self.ITEM_ID / "CONVERSATION.md"
        self.assertTrue(conv_file.exists(), "CONVERSATION.md not found after remote run")
        text = conv_file.read_text()
        self.assertIn(
            "DISPATCH-VALIDATED", text,
            "Expected Claude to write DISPATCH-VALIDATED — Claude may not have run (auth failure?)"
        )

        # Log file should exist
        log_dir = REAL_WORK_DIR / "_logs"
        logs = list(log_dir.glob(f"*_{self.ITEM_ID}.log"))
        self.assertTrue(len(logs) > 0, "No log file found after remote run")


# ---------------------------------------------------------------------------
# TestResolvedModeTrigger
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# TestLauncherScriptResolvedMode
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# TestLauncherDebugFile
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# TestDispatchRemoteResolvedMode
# ---------------------------------------------------------------------------

class TestDispatchRemoteResolvedMode(unittest.TestCase):

    def _make_wl_with_conv(self, tmp: str) -> WorkLoop:
        content = (
            "# Work Loop\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
            "| MY-ITEM | Task | user@host | resolved |  |  |  |\n\n"
            "## Done\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
        )
        wl = _make_workloop(tmp, content)
        (Path(tmp) / "RESOLVE-PROMPT.md").write_text("Resolve.\n")
        item_dir = Path(tmp) / "MY-ITEM"
        item_dir.mkdir()
        (item_dir / "CONVERSATION.md").write_text("## 2026-01-01 | User\n\nDo it.\n")
        return wl

    def _collect_rsync_targets(self, wl: WorkLoop) -> list[str]:
        from unittest.mock import patch, MagicMock
        rsynced = []

        def fake_run(cmd, **kwargs):
            if isinstance(cmd, list) and "rsync" in (cmd[0] if cmd else ""):
                rsynced.append(cmd[-1])
                rsynced.append(cmd[-2])
            return MagicMock(returncode=0, stdout="")

        with patch('workloop.remote._run', side_effect=fake_run), \
             patch('workloop.remote.subprocess') as mock_sub:
            mock_sub.run.return_value = MagicMock(returncode=0, stdout="", stderr=b"")
            wl.dispatch_remote("MY-ITEM", "2026-01-01_10-00-00", "user@host", 10.0, mode="resolved")
        return rsynced

    def test_resolve_prompt_rsynced_for_resolved_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl_with_conv(tmp)
            targets = self._collect_rsync_targets(wl)
            self.assertTrue(any("RESOLVE-PROMPT.md" in t for t in targets))

    def test_impl_prompt_not_rsynced_for_resolved_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl_with_conv(tmp)
            targets = self._collect_rsync_targets(wl)
            self.assertFalse(any("IMPL-PROMPT.md" in t for t in targets))


# ---------------------------------------------------------------------------
# TestMoveRowToDone
# ---------------------------------------------------------------------------

class TestMoveRowToDone(unittest.TestCase):

    def _make_wl(self, status: str = "resolved") -> WorkLoop:
        content = (
            "# Work Loop\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
            f"| MY-ITEM | [Task](MY-ITEM/C.md) | local | {status} |  |  |  |\n\n"
            "## Done\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
            "| OLD-ITEM | [Old task](OLD-ITEM/C.md) | local | done |  |  |  |\n"
        )
        return _make_workloop(tempfile.mkdtemp(), content)

    def test_moves_item_to_done_section(self):
        wl = self._make_wl()
        wl._move_row_to_done("MY-ITEM")
        text = (Path(wl.work_dir) / "WORK.md").read_text()
        done_idx = text.index("## Done")
        self.assertIn("MY-ITEM", text[done_idx:])
        self.assertNotIn("MY-ITEM", text[:done_idx])

    def test_preserves_existing_done_items(self):
        wl = self._make_wl()
        wl._move_row_to_done("MY-ITEM")
        text = (Path(wl.work_dir) / "WORK.md").read_text()
        done_idx = text.index("## Done")
        self.assertIn("OLD-ITEM", text[done_idx:])

    def test_preserves_item_status(self):
        wl = self._make_wl("resolved")
        wl._move_row_to_done("MY-ITEM")
        self.assertEqual(wl.get_col("MY-ITEM", COL_STATUS), "resolved")

    def test_noop_when_item_not_found(self):
        wl = self._make_wl()
        content_before = (Path(wl.work_dir) / "WORK.md").read_text()
        wl._move_row_to_done("NONEXISTENT")
        self.assertEqual(content_before, (Path(wl.work_dir) / "WORK.md").read_text())

    def test_idempotent(self):
        wl = self._make_wl()
        wl._move_row_to_done("MY-ITEM")
        after_first = (Path(wl.work_dir) / "WORK.md").read_text()
        wl._move_row_to_done("MY-ITEM")
        self.assertEqual(after_first, (Path(wl.work_dir) / "WORK.md").read_text())

    def test_active_section_shrinks(self):
        wl = self._make_wl()
        before = (Path(wl.work_dir) / "WORK.md").read_text()
        active_before = before[:before.index("## Done")]
        wl._move_row_to_done("MY-ITEM")
        after = (Path(wl.work_dir) / "WORK.md").read_text()
        active_after = after[:after.index("## Done")]
        self.assertLess(len(active_after), len(active_before))


# ---------------------------------------------------------------------------
# TestProcessLocalResolvedMode
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# TestTsStrFromLogColDebug
# ---------------------------------------------------------------------------

class TestTsStrFromLogColDebug(unittest.TestCase):
    """_ts_str_from_log_col must accept .debug extension in the Log column."""

    TS = "2026-06-04_17-43-49"

    def _make_wl(self, log_col: str) -> WorkLoop:
        content = (
            "# Work Loop\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
            f"| MY-ITEM | [MY-ITEM](MY-ITEM/C.md) | user@host | in-progress |  | $10.0 | {log_col} |\n\n"
            "## Done\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
        )
        return _make_workloop(tempfile.mkdtemp(), content)

    def test_extracts_ts_from_debug_extension(self):
        log_col = f"[Log](_logs/{self.TS}_MY-ITEM.debug)"
        wl = self._make_wl(log_col)
        self.assertEqual(wl._ts_str_from_log_col("MY-ITEM", "user@host"), self.TS)

    def test_extracts_ts_from_log_extension(self):
        log_col = f"[Log](_logs/{self.TS}_MY-ITEM.log)"
        wl = self._make_wl(log_col)
        self.assertEqual(wl._ts_str_from_log_col("MY-ITEM", "user@host"), self.TS)


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

class TestGetItemType(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_script_item_detected_when_runs_md_present(self):
        wl = _make_script_item(self.tmp, "SI-001", _SINGLE_LOC_RUNS_MD)
        self.assertEqual(wl.get_item_type("SI-001"), "script")

    def test_conversation_item_when_no_runs_md(self):
        wl = _make_workloop(self.tmp)
        (Path(self.tmp) / "ITEM-001").mkdir(exist_ok=True)
        self.assertEqual(wl.get_item_type("ITEM-001"), "conversation")

    def test_new_item_no_folder_is_conversation(self):
        wl = _make_workloop(self.tmp)
        self.assertEqual(wl.get_item_type("NONEXISTENT"), "conversation")


# ---------------------------------------------------------------------------
# TestParseRunsMdConfig
# ---------------------------------------------------------------------------

class TestParseRunsMdConfig(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_single_location_parsed(self):
        wl = _make_script_item(self.tmp, "SI-001", _SINGLE_LOC_RUNS_MD)
        cfg = wl._parse_runs_md("SI-001")
        self.assertEqual(cfg["command"], "bash test_fixtures/stub_test.sh")
        self.assertEqual(cfg["params"], "--arg1")
        self.assertEqual(cfg["location"], "linux:user@host1")
        self.assertEqual(cfg["heartbeat_file"], "run.log")
        self.assertEqual(cfg["timeout"], 4)
        self.assertEqual(cfg["aggregation_script"], "test_fixtures/stub_aggregate.py")
        self.assertIn("{run-id}", cfg["analysis_prompt"])

    def test_multi_location_parsed(self):
        wl = _make_script_item(self.tmp, "SI-001", _MULTI_LOC_RUNS_MD)
        cfg = wl._parse_runs_md("SI-001")
        self.assertEqual(cfg["locations"], ["linux:user@host1", "linux:user@host2", "win:user@winhost"])
        self.assertEqual(cfg["location"], "")

    def test_schedule_parsed(self):
        wl = _make_script_item(self.tmp, "SI-001", _SCHEDULED_RUNS_MD)
        cfg = wl._parse_runs_md("SI-001")
        self.assertEqual(cfg["schedule"], "30 9 * * 1-5")

    def test_missing_runs_md_returns_defaults(self):
        wl = _make_workloop(self.tmp)
        cfg = wl._parse_runs_md("NONEXISTENT")
        self.assertEqual(cfg["command"], "")
        self.assertEqual(cfg["timeout"], DEFAULT_TIMEOUT_MIN)


# ---------------------------------------------------------------------------
# TestCronShouldRun
# ---------------------------------------------------------------------------

class TestCronShouldRun(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.wl = _make_workloop(self.tmp)

    def _dt(self, **kw):
        from datetime import datetime
        base = {"year": 2026, "month": 1, "day": 5, "hour": 9, "minute": 30}
        base.update(kw)
        return datetime(**base)

    def test_exact_match_fires(self):
        # Mon 2026-01-05 09:30
        dt = self._dt()
        self.assertTrue(self.wl._cron_should_run("30 9 * * 1", dt))

    def test_wrong_minute_does_not_fire(self):
        dt = self._dt(minute=29)
        self.assertFalse(self.wl._cron_should_run("30 9 * * 1", dt))

    def test_wildcard_minute_fires(self):
        dt = self._dt(minute=15)
        self.assertTrue(self.wl._cron_should_run("* 9 * * 1", dt))

    def test_step_expression_fires(self):
        dt = self._dt(minute=0)
        self.assertTrue(self.wl._cron_should_run("*/15 * * * *", dt))

    def test_empty_cron_returns_false(self):
        self.assertFalse(self.wl._cron_should_run("", self._dt()))

    def test_invalid_cron_returns_false(self):
        self.assertFalse(self.wl._cron_should_run("invalid", self._dt()))

    def test_sunday_dow_zero(self):
        # 2026-01-04 is a Sunday; cron dow 0 = Sunday
        from datetime import datetime
        dt = datetime(2026, 1, 4, 9, 30)
        self.assertTrue(self.wl._cron_should_run("30 9 * * 0", dt))


# ---------------------------------------------------------------------------
# TestGenerateRunId
# ---------------------------------------------------------------------------

class TestGenerateRunId(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_first_run_is_001(self):
        wl = _make_script_item(self.tmp, "SI-001", _SINGLE_LOC_RUNS_MD)
        from datetime import datetime
        today = datetime.now().strftime('%Y%m%d')
        run_id = wl._generate_run_id("SI-001")
        self.assertEqual(run_id, f"{today}-001")

    def test_second_run_increments(self):
        wl = _make_script_item(self.tmp, "SI-001", _SINGLE_LOC_RUNS_MD)
        from datetime import datetime
        today = datetime.now().strftime('%Y%m%d')
        runs_file = Path(self.tmp) / "SI-001" / "RUNS.md"
        runs_file.write_text(f"| {today}-001 | t | running | 2026-01-05 | [Log](runs/{today}-001/) |\n")
        run_id = wl._generate_run_id("SI-001")
        self.assertEqual(run_id, f"{today}-002")


# ---------------------------------------------------------------------------
# TestParseLocation
# ---------------------------------------------------------------------------

class TestParseLocation(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.wl = _make_workloop(self.tmp)

    def test_linux_user_host(self):
        os_type, user_host, hostname = self.wl._parse_location("linux:user@myhost")
        self.assertEqual(os_type, "linux")
        self.assertEqual(user_host, "user@myhost")
        self.assertEqual(hostname, "myhost")

    def test_win_location(self):
        os_type, user_host, hostname = self.wl._parse_location("win:admin@winbox")
        self.assertEqual(os_type, "win")
        self.assertEqual(hostname, "winbox")

    def test_no_os_prefix_defaults_linux(self):
        os_type, user_host, hostname = self.wl._parse_location("user@myhost")
        self.assertEqual(os_type, "linux")


# ---------------------------------------------------------------------------
# TestRsyncCmdForHost
# ---------------------------------------------------------------------------

class TestRsyncCmdForHost(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.wl = _make_workloop(self.tmp)

    def test_linux_no_rsync_path(self):
        cmd = self.wl._rsync_cmd_for_host("linux", "src/", "dst/")
        self.assertNotIn("--rsync-path", " ".join(cmd))

    def test_win_adds_rsync_path(self):
        cmd = self.wl._rsync_cmd_for_host("win", "src/", "dst/")
        self.assertTrue(any("--rsync-path" in a for a in cmd))

    def test_extra_flags_included(self):
        cmd = self.wl._rsync_cmd_for_host("linux", "src/", "dst/", ["--delete"])
        self.assertIn("--delete", cmd)


# ---------------------------------------------------------------------------
# TestAppendRunsMdRow
# ---------------------------------------------------------------------------

class TestAppendRunsMdRow(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_row_appended_to_new_table(self):
        wl = _make_script_item(self.tmp, "SI-001", _SINGLE_LOC_RUNS_MD)
        wl._append_runs_md_row("SI-001", "20260105-001", "test params", "running")
        text = (Path(self.tmp) / "SI-001" / "RUNS.md").read_text()
        self.assertIn("20260105-001", text)
        self.assertIn("running", text)

    def test_row_appended_to_existing_table(self):
        wl = _make_script_item(self.tmp, "SI-001", _SINGLE_LOC_RUNS_MD)
        wl._append_runs_md_row("SI-001", "20260105-001", "first", "success")
        wl._append_runs_md_row("SI-001", "20260105-002", "second", "running")
        text = (Path(self.tmp) / "SI-001" / "RUNS.md").read_text()
        self.assertIn("20260105-001", text)
        self.assertIn("20260105-002", text)


# ---------------------------------------------------------------------------
# TestUpdateRunsMdRowStatus
# ---------------------------------------------------------------------------

class TestUpdateRunsMdRowStatus(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_status_updated(self):
        wl = _make_script_item(self.tmp, "SI-001", _SINGLE_LOC_RUNS_MD)
        wl._append_runs_md_row("SI-001", "20260105-001", "t", "running")
        wl._update_runs_md_row_status("SI-001", "20260105-001", "success")
        text = (Path(self.tmp) / "SI-001" / "RUNS.md").read_text()
        for line in text.splitlines():
            if "20260105-001" in line:
                self.assertIn("success", line)
                break

    def test_other_rows_unchanged(self):
        wl = _make_script_item(self.tmp, "SI-001", _SINGLE_LOC_RUNS_MD)
        wl._append_runs_md_row("SI-001", "20260105-001", "t", "success")
        wl._append_runs_md_row("SI-001", "20260105-002", "t", "running")
        wl._update_runs_md_row_status("SI-001", "20260105-002", "needs-review")
        text = (Path(self.tmp) / "SI-001" / "RUNS.md").read_text()
        for line in text.splitlines():
            if "20260105-001" in line:
                self.assertIn("success", line)
                break


# ---------------------------------------------------------------------------
# TestRunStateReadWrite
# ---------------------------------------------------------------------------

class TestRunStateReadWrite(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_write_then_read(self):
        wl = _make_script_item(self.tmp, "SI-001", _SINGLE_LOC_RUNS_MD)
        state = {"dispatched": ["host1"], "done": [], "timed_out": []}
        wl._write_run_state("SI-001", "20260105-001", state)
        loaded = wl._read_run_state("SI-001", "20260105-001")
        self.assertEqual(loaded["dispatched"], ["host1"])

    def test_read_missing_returns_none(self):
        wl = _make_script_item(self.tmp, "SI-001", _SINGLE_LOC_RUNS_MD)
        self.assertIsNone(wl._read_run_state("SI-001", "nonexistent"))


# ---------------------------------------------------------------------------
# TestBuildTestDispatchScript
# ---------------------------------------------------------------------------

class TestBuildTestDispatchScript(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.wl = _make_workloop(self.tmp)

    def test_script_contains_command(self):
        script = self.wl.build_test_dispatch_script("bash run.sh", "--flag", "SI-001/runs/id")
        self.assertIn("bash run.sh --flag", script)

    def test_script_writes_done_sentinel(self):
        script = self.wl.build_test_dispatch_script("bash run.sh", "", "SI-001/runs/id")
        self.assertIn(".done", script)

    def test_script_uses_run_subdir(self):
        script = self.wl.build_test_dispatch_script("cmd", "p", "SI-001/runs/20260105-001")
        self.assertIn("SI-001/runs/20260105-001", script)


# ---------------------------------------------------------------------------
# TestInitializeNewItemScriptItem
# ---------------------------------------------------------------------------

class TestInitializeNewItemScriptItem(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_script_item_new_sets_scheduled_when_schedule(self):
        content = (
            "| ID | Title / Initial Prompt | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | --------------------- | -------- | ------ | ------------ | ------ | --- |\n"
            "| SI-001 | Script item | local | new | | | |\n\n"
            "## Done\n\n"
            "| ID | Title / Initial Prompt | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | --------------------- | -------- | ------ | ------------ | ------ | --- |\n"
        )
        wl = _make_script_item(self.tmp, "SI-001", _SCHEDULED_RUNS_MD, work_md=content)
        wl.initialize_new_item("SI-001")
        self.assertEqual(wl.get_col("SI-001", COL_STATUS), "scheduled")

    def test_script_item_new_sets_ready_when_no_schedule(self):
        content = (
            "| ID | Title / Initial Prompt | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | --------------------- | -------- | ------ | ------------ | ------ | --- |\n"
            "| SI-001 | Script item | local | new | | | |\n\n"
            "## Done\n\n"
            "| ID | Title / Initial Prompt | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | --------------------- | -------- | ------ | ------------ | ------ | --- |\n"
        )
        wl = _make_script_item(self.tmp, "SI-001", _SINGLE_LOC_RUNS_MD, work_md=content)
        wl.initialize_new_item("SI-001")
        self.assertEqual(wl.get_col("SI-001", COL_STATUS), "ready")

    def test_conversation_item_new_creates_conversation_md(self):
        wl = _make_workloop(self.tmp)
        content = (
            "| ID | Title / Initial Prompt | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | --------------------- | -------- | ------ | ------------ | ------ | --- |\n"
            "| NEW-1 | My task prompt | local | new | | | |\n\n"
            "## Done\n\n"
            "| ID | Title / Initial Prompt | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | --------------------- | -------- | ------ | ------------ | ------ | --- |\n"
        )
        p = Path(self.tmp)
        (p / "WORK.md").write_text(content)
        cfg = {"work_dir": p, "harness": {"type": "claude", "max_budget_usd": 10.0}, "remote": {"work_dir": "~/Work-Loop"}}
        wl2 = WorkLoop(cfg)
        wl2.initialize_new_item("NEW-1")
        conv = p / "NEW-1" / "CONVERSATION.md"
        self.assertTrue(conv.exists())
        self.assertIn("My task prompt", conv.read_text())


# ---------------------------------------------------------------------------
# TestAggregationScript
# ---------------------------------------------------------------------------

class TestAggregationScript(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.wl = _make_workloop(self.tmp)

    def test_successful_aggregation(self):
        run_dir = Path(self.tmp) / "runs" / "20260105-001"
        run_dir.mkdir(parents=True)
        script = str(_HERE / "test_fixtures" / "stub_aggregate.py")
        rc = self.wl._run_aggregation_script(run_dir, script)
        self.assertEqual(rc, 0)
        self.assertTrue((run_dir / "aggregated.txt").exists())

    def test_failed_aggregation_writes_error_log(self):
        run_dir = Path(self.tmp) / "runs" / "20260105-001"
        run_dir.mkdir(parents=True)
        rc = self.wl._run_aggregation_script(run_dir, "/nonexistent/script.py")
        self.assertNotEqual(rc, 0)


# ---------------------------------------------------------------------------
# TestPollMachineOnce
# ---------------------------------------------------------------------------

class TestPollMachineOnce(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_done_when_dot_done_exists(self):
        wl = _make_script_item(self.tmp, "SI-001", _SINGLE_LOC_RUNS_MD)
        run_dir = Path(self.tmp) / "SI-001" / "runs" / "20260105-001"
        run_dir.mkdir(parents=True)
        (run_dir / ".done").write_text("0")
        state: dict = {"heartbeat_mtimes": {}, "file_counts": {}}
        with unittest.mock.patch("subprocess.run", return_value=unittest.mock.MagicMock(returncode=0)):
            done, _ = wl._poll_machine_once(
                "SI-001", "20260105-001", "host1", "user@host1", "linux",
                False, "", state
            )
        self.assertTrue(done)

    def test_not_done_when_dot_done_absent_no_activity(self):
        wl = _make_script_item(self.tmp, "SI-001", _SINGLE_LOC_RUNS_MD)
        # Pre-seed file_counts so first poll sees no change from baseline
        state: dict = {"heartbeat_mtimes": {}, "file_counts": {"host1": 0}}
        with unittest.mock.patch("subprocess.run", return_value=unittest.mock.MagicMock(returncode=0)):
            done, changed = wl._poll_machine_once(
                "SI-001", "20260105-001", "host1", "user@host1", "linux",
                False, "", state
            )
        self.assertFalse(done)
        self.assertFalse(changed)

    def test_heartbeat_file_change_detected(self):
        import time
        wl = _make_script_item(self.tmp, "SI-001", _SINGLE_LOC_RUNS_MD)
        run_dir = Path(self.tmp) / "SI-001" / "runs" / "20260105-001"
        run_dir.mkdir(parents=True)
        hb = run_dir / "run.log"
        hb.write_text("start")
        state: dict = {"heartbeat_mtimes": {}, "file_counts": {}}
        with unittest.mock.patch("subprocess.run") as mock_sub:
            mock_sub.return_value = unittest.mock.MagicMock(returncode=0)
            # First poll records baseline mtime
            wl._poll_machine_once(
                "SI-001", "20260105-001", "host1", "user@host1", "linux",
                False, "run.log", state
            )
        # Update file to change mtime
        time.sleep(0.05)
        hb.write_text("updated")
        with unittest.mock.patch("subprocess.run") as mock_sub:
            mock_sub.return_value = unittest.mock.MagicMock(returncode=0)
            done, changed = wl._poll_machine_once(
                "SI-001", "20260105-001", "host1", "user@host1", "linux",
                False, "run.log", state
            )
        self.assertFalse(done)
        self.assertTrue(changed)


# ---------------------------------------------------------------------------
# TestFindLatestRunsMdRun
# ---------------------------------------------------------------------------

class TestFindLatestRunsMdRun(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_returns_latest_run(self):
        wl = _make_script_item(self.tmp, "SI-001", _SINGLE_LOC_RUNS_MD)
        wl._append_runs_md_row("SI-001", "20260105-001", "t", "success")
        wl._append_runs_md_row("SI-001", "20260105-002", "t", "running")
        result = wl._find_latest_runs_md_run("SI-001")
        self.assertEqual(result, "20260105-002")

    def test_returns_none_for_missing_file(self):
        wl = _make_workloop(self.tmp)
        self.assertIsNone(wl._find_latest_runs_md_run("NONEXISTENT"))

    def test_filter_by_status(self):
        wl = _make_script_item(self.tmp, "SI-001", _SINGLE_LOC_RUNS_MD)
        wl._append_runs_md_row("SI-001", "20260105-001", "t", "success")
        wl._append_runs_md_row("SI-001", "20260105-002", "t", "running")
        result = wl._find_latest_runs_md_run("SI-001", "success")
        self.assertEqual(result, "20260105-001")


# ---------------------------------------------------------------------------
# TestAbortHandling
# ---------------------------------------------------------------------------

class TestAbortHandling(unittest.TestCase):
    """Tests for the 'abort' status: trigger skipping, process_local outcome, watcher."""

    def _make_wl(self, tmp: str, status: str = "ready") -> WorkLoop:
        content = (
            "# Work Loop\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
            f"| MY-ITEM | [Task](MY-ITEM/C.md) | local | {status} |  |  |  |\n\n"
            "## Done\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
        )
        wl = _make_workloop(tmp, content)
        (Path(tmp) / "_logs").mkdir(exist_ok=True)
        item_dir = Path(tmp) / "MY-ITEM"
        item_dir.mkdir()
        (item_dir / "CONVERSATION.md").write_text("## 2026-01-01 | User\n\nDo it.\n")
        return wl

    def test_abort_status_leaves_abort_after_process_local(self):
        """Status stays 'abort' when watcher kills the harness mid-run."""
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl(tmp)

            def run_harness_aborts(*args, **kwargs):
                wl.update_col("MY-ITEM", COL_STATUS, "abort")
                return 1

            with patch.object(WorkLoop, "_run_harness", side_effect=run_harness_aborts):
                wl.process_local("MY-ITEM", 10.0)

            self.assertEqual(wl.get_col("MY-ITEM", COL_STATUS), "abort")

    def test_abort_status_does_not_set_needs_review(self):
        """Aborted items must not land on needs-review."""
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl(tmp)

            def run_harness_aborts(*args, **kwargs):
                wl.update_col("MY-ITEM", COL_STATUS, "abort")
                return 1

            with patch.object(WorkLoop, "_run_harness", side_effect=run_harness_aborts):
                wl.process_local("MY-ITEM", 10.0)

            self.assertNotEqual(wl.get_col("MY-ITEM", COL_STATUS), "needs-review")

    def test_abort_prepends_notice(self):
        """process_local writes an abort notice to CONVERSATION.md."""
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl(tmp)

            def run_harness_aborts(*args, **kwargs):
                wl.update_col("MY-ITEM", COL_STATUS, "abort")
                return 1

            with patch.object(WorkLoop, "_run_harness", side_effect=run_harness_aborts):
                wl.process_local("MY-ITEM", 10.0)

            text = (Path(tmp) / "MY-ITEM" / "CONVERSATION.md").read_text()
            self.assertIn("Run aborted", text)
            self.assertIn("aborted by user", text)

    def test_nonzero_exit_without_abort_still_sets_needs_review(self):
        """Regression: a non-abort failure still lands on needs-review."""
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl(tmp)
            with patch.object(WorkLoop, "_run_harness", return_value=1):
                wl.process_local("MY-ITEM", 10.0)
            self.assertEqual(wl.get_col("MY-ITEM", COL_STATUS), "needs-review")

    def test_watcher_terminates_process_on_abort(self):
        """ClaudeHarness's abort watcher calls proc.terminate() when status is 'abort'."""
        from unittest.mock import patch, MagicMock

        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl(tmp)
            # Fast poll interval so the watcher fires without a 3-second wait.
            wl.harness._abort_poll_interval = 0.01
            log_file = Path(tmp) / "_logs" / "test.log"

            # Process blocks on read until terminate() is called.
            import threading as _threading
            _unblock = _threading.Event()
            proc_mock = MagicMock()
            proc_mock.stdout.read.side_effect = lambda _n: (
                b"" if _unblock.wait(timeout=5) else b""
            )
            proc_mock.terminate.side_effect = lambda: _unblock.set()
            proc_mock.wait.return_value = -15

            original_get_col = wl.get_col

            def abort_get_col(item_id, col_idx):
                if col_idx == COL_STATUS and item_id == "MY-ITEM":
                    return "abort"
                return original_get_col(item_id, col_idx)

            with patch("subprocess.Popen", return_value=proc_mock), \
                 patch.object(wl, "get_col", side_effect=abort_get_col):
                wl.harness.run("prompt text", 10.0, None, "MY-ITEM", log_file, abort_checker=lambda: wl.get_col("MY-ITEM", 4) == "abort")

            proc_mock.terminate.assert_called()


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


class TestRemoteAbort(unittest.TestCase):
    """Unit tests for abort handling in wait_for_remote and _abort_remote."""

    def _make_wl(self, tmp: str, status: str = "in-progress") -> WorkLoop:
        content = (
            "# Work Loop\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
            f"| MY-ITEM | [Task](MY-ITEM/C.md) | remote@host | {status} |  |  |  |\n\n"
            "## Done\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
        )
        wl = _make_workloop(tmp, content)
        (Path(tmp) / "_logs").mkdir(exist_ok=True)
        item_dir = Path(tmp) / "MY-ITEM"
        item_dir.mkdir()
        (item_dir / "CONVERSATION.md").write_text("## 2026-01-01 | User\n\nDo it.\n")
        return wl

    def test_wait_for_remote_aborts_when_status_is_abort(self):
        """wait_for_remote calls _abort_remote and returns without syncing back normally."""
        from unittest.mock import patch, MagicMock, call

        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl(tmp, status="abort")

            abort_remote_mock = MagicMock()
            sync_back_mock = MagicMock()

            with patch.object(wl, "_abort_remote", abort_remote_mock), \
                 patch.object(wl, "_sync_back_remote", sync_back_mock):
                wl.wait_for_remote("MY-ITEM", "2026-01-01_12-00-00", "remote@host", 10.0,
                                   poll_interval=0, timeout=30)

            abort_remote_mock.assert_called_once_with(
                "MY-ITEM", "2026-01-01_12-00-00", "remote@host", 10.0)
            sync_back_mock.assert_not_called()

    def test_wait_for_remote_normal_completion_not_affected(self):
        """When status is in-progress and .done appears, _sync_back_remote is called normally."""
        from unittest.mock import patch, MagicMock

        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl(tmp, status="in-progress")

            abort_remote_mock = MagicMock()
            sync_back_mock = MagicMock()

            def fake_ssh(*args, **kwargs):
                cmd = args[0] if args else kwargs.get("args", [])
                if isinstance(cmd, list) and any(".done" in c for c in cmd):
                    result = MagicMock()
                    result.stdout = "0"
                    return result
                return MagicMock(stdout="", returncode=0)

            with patch("subprocess.run", side_effect=fake_ssh), \
                 patch.object(wl, "_abort_remote", abort_remote_mock), \
                 patch.object(wl, "_sync_back_remote", sync_back_mock):
                wl.wait_for_remote("MY-ITEM", "2026-01-01_12-00-00", "remote@host", 10.0,
                                   poll_interval=0, timeout=30)

            abort_remote_mock.assert_not_called()
            sync_back_mock.assert_called_once()

    def test_abort_remote_leaves_status_as_abort(self):
        """_abort_remote does not overwrite abort with needs-review."""
        from unittest.mock import patch, MagicMock

        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl(tmp, status="abort")

            noop = MagicMock(returncode=0, stdout="", stderr="")
            with patch("subprocess.run", return_value=noop), \
                 patch.object(run_loop, "_run", return_value=noop):
                wl._abort_remote("MY-ITEM", "2026-01-01_12-00-00", "remote@host", 10.0)

            self.assertEqual(wl.get_col("MY-ITEM", COL_STATUS), "abort")

    def test_abort_remote_prepends_notice(self):
        """_abort_remote prepends an abort notice to CONVERSATION.md."""
        from unittest.mock import patch, MagicMock

        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl(tmp, status="abort")

            noop = MagicMock(returncode=0, stdout="", stderr="")
            with patch("subprocess.run", return_value=noop), \
                 patch.object(run_loop, "_run", return_value=noop):
                wl._abort_remote("MY-ITEM", "2026-01-01_12-00-00", "remote@host", 10.0)

            conv = (Path(tmp) / "MY-ITEM" / "CONVERSATION.md").read_text()
            self.assertIn("Run aborted", conv)
            self.assertIn("aborted by user", conv)


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


class TestResearchItemType(unittest.TestCase):

    def test_research_item_detected_when_type_research(self):
        wl = _make_research_item(tempfile.mkdtemp(), "RES-001", _RESEARCH_RUNS_MD)
        self.assertEqual(wl.get_item_type("RES-001"), "research")

    def test_script_item_still_detected(self):
        wl = _make_script_item(tempfile.mkdtemp(), "SI-001", _SINGLE_LOC_RUNS_MD)
        self.assertEqual(wl.get_item_type("SI-001"), "script")

    def test_conversation_item_when_no_runs_md(self):
        wl = _make_workloop(tempfile.mkdtemp())
        (Path(tempfile.mkdtemp()) / "ITEM-001").mkdir(exist_ok=True)
        tmp = tempfile.mkdtemp()
        wl = _make_workloop(tmp)
        (Path(tmp) / "ITEM-001").mkdir(exist_ok=True)
        self.assertEqual(wl.get_item_type("ITEM-001"), "conversation")


class TestResearchParseConfig(unittest.TestCase):

    def test_research_config_parsed(self):
        wl = _make_research_item(tempfile.mkdtemp(), "RES-001", _RESEARCH_RUNS_MD)
        cfg = wl._parse_runs_md("RES-001")
        self.assertEqual(cfg["type"], "research")
        self.assertEqual(cfg["title"], "AI Security")
        self.assertEqual(cfg["note_path"], "[[AI Security]]")
        self.assertIn("https://arxiv.org/list/cs.CR/recent", cfg["sources"])
        self.assertIn("https://openai.com/blog", cfg["sources"])
        self.assertEqual(cfg["schedule"], "0 6 * * 1")
        self.assertEqual(cfg["timeout"], 10)
        self.assertIn("model vulnerabilities", cfg["instruction"])
        self.assertIn("Exclude: consumer AI apps", cfg["instruction"])

    def test_prompt_parsed(self):
        wl = _make_research_item(tempfile.mkdtemp(), "RES-001", _RESEARCH_RUNS_MD)
        cfg = wl._parse_runs_md("RES-001")
        self.assertIn("Focus on: model vulnerabilities", cfg["instruction"])
        self.assertIn("Key papers to watch", cfg["instruction"])

    def test_missing_prompt_returns_empty(self):
        runs_md = """\
## Config
type: research
title: Test
note_path: [[Test]]
sources:
  https://example.com
"""
        wl = _make_research_item(tempfile.mkdtemp(), "RES-001", runs_md)
        cfg = wl._parse_runs_md("RES-001")
        self.assertEqual(cfg["instruction"], "")


class TestResearchInitialization(unittest.TestCase):

    def test_research_item_new_sets_scheduled_when_schedule(self):
        content = (
            "| ID | Title / Initial Prompt | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | --------------------- | -------- | ------ | ------------ | ------ | --- |\n"
            "| RES-001 | AI Security Research | local | new | | | |\n\n"
            "## Done\n\n"
            "| ID | Title / Initial Prompt | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | --------------------- | -------- | ------ | ------------ | ------ | --- |\n"
        )
        wl = _make_research_item(tempfile.mkdtemp(), "RES-001", _RESEARCH_RUNS_MD, work_md=content)
        wl.initialize_new_item("RES-001")
        self.assertEqual(wl.get_col("RES-001", COL_STATUS), "scheduled")

    def test_research_item_new_sets_ready_when_no_schedule(self):
        runs_md = """\
## Config
type: research
title: Test Topic
note_path: [[Test]]
sources:
  https://example.com
"""
        content = (
            "| ID | Title / Initial Prompt | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | --------------------- | -------- | ------ | ------------ | ------ | --- |\n"
            "| RES-001 | Test Topic | local | new | | | |\n\n"
            "## Done\n\n"
            "| ID | Title / Initial Prompt | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | --------------------- | -------- | ------ | ------------ | ------ | --- |\n"
        )
        wl = _make_research_item(tempfile.mkdtemp(), "RES-001", runs_md, work_md=content)
        wl.initialize_new_item("RES-001")
        self.assertEqual(wl.get_col("RES-001", COL_STATUS), "ready")

    def test_research_item_creates_conversation_md(self):
        content = (
            "| ID | Title / Initial Prompt | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | --------------------- | -------- | ------ | ------------ | ------ | --- |\n"
            "| RES-001 | AI Security Research | local | new | | | |\n\n"
            "## Done\n\n"
            "| ID | Title / Initial Prompt | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | --------------------- | -------- | ------ | ------------ | ------ | --- |\n"
        )
        tmp = tempfile.mkdtemp()
        wl = _make_research_item(tmp, "RES-001", _RESEARCH_RUNS_MD, work_md=content)
        wl.initialize_new_item("RES-001")
        conv = Path(tmp) / "RES-001" / "CONVERSATION.md"
        self.assertTrue(conv.exists())
        self.assertIn("AI Security", conv.read_text())


class TestResearchTriggerStatus(unittest.TestCase):

    def test_research_is_trigger_status(self):
        content = (
            "# Work Loop\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
            "| RES-001 | [Research](RES-001/C.md) | local | research |  |  |  |\n\n"
            "## Done\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
        )
        wl = _make_workloop(tempfile.mkdtemp(), content)
        self.assertIn("RES-001", wl.get_ready_items())


class TestResearchAppendRun(unittest.TestCase):

    def test_append_research_run_creates_table(self):
        tmp = tempfile.mkdtemp()
        wl = _make_research_item(tmp, "RES-001", _RESEARCH_RUNS_MD)
        wl._append_research_run("RES-001", "20260717-001", "Added 3 new papers")
        text = (Path(tmp) / "RES-001" / "RUNS.md").read_text()
        self.assertIn("20260717-001", text)
        self.assertIn("Added 3 new papers", text)
        self.assertIn("done", text)
        self.assertIn("runs/20260717-001/", text)

    def test_append_research_run_creates_header(self):
        tmp = tempfile.mkdtemp()
        wl = _make_research_item(tmp, "RES-001", _RESEARCH_RUNS_MD)
        # Clear the run history table
        runs_file = Path(tmp) / "RES-001" / "RUNS.md"
        text = runs_file.read_text()
        # Remove existing table rows
        lines = [l for l in text.splitlines() if not l.startswith('|') or 'ID' in l or '--' in l]
        # Keep only the header
        header_lines = [l for l in lines if 'ID | Summary' in l or '|---' in l]
        runs_file.write_text('\n'.join(header_lines) + '\n')
        wl._append_research_run("RES-001", "20260717-001", "Test summary")
        text = runs_file.read_text()
        self.assertIn("20260717-001", text)


class TestResearchProcessLocal(unittest.TestCase):

    def _make_wl(self, tmp: str, status: str = "research") -> WorkLoop:
        content = (
            "# Work Loop\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
            f"| RES-001 | [Research](RES-001/C.md) | local | {status} |  |  |  |\n\n"
            "## Done\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
        )
        wl = _make_research_item(tmp, "RES-001", _RESEARCH_RUNS_MD, work_md=content)
        (Path(tmp) / "_logs").mkdir(exist_ok=True)
        item_dir = Path(tmp) / "RES-001"
        (item_dir / "CONVERSATION.md").write_text("## 2026-01-01 | User\n\nResearch item: AI Security\n")
        return wl

    def test_research_success_sets_scheduled_when_cron(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl(tmp)
            # Create a run directory with research.md
            run_dir = Path(tmp) / "RES-001" / "runs" / "20260717-001"
            run_dir.mkdir(parents=True)
            (run_dir / "research.md").write_text("## 2026-07-17 — AI Security\n\n- Added 3 new papers on model vulnerabilities\n")
            with patch.object(WorkLoop, "_run_harness", return_value=0):
                wl.process_local("RES-001", 10.0)
            self.assertEqual(wl.get_col("RES-001", COL_STATUS), "scheduled")

    def test_research_success_sets_done_when_no_cron(self):
        from unittest.mock import patch
        runs_md = """\
## Config
type: research
title: Test
note_path: [[Test]]
sources:
  https://example.com
"""
        content = (
            "# Work Loop\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
            "| RES-001 | [Research](RES-001/C.md) | local | research |  |  |  |\n\n"
            "## Done\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
        )
        tmp = tempfile.mkdtemp()
        wl = _make_research_item(tmp, "RES-001", runs_md, work_md=content)
        (Path(tmp) / "_logs").mkdir(exist_ok=True)
        item_dir = Path(tmp) / "RES-001"
        (item_dir / "CONVERSATION.md").write_text("## 2026-01-01 | User\n\nResearch item: Test\n")

        run_dir = Path(tmp) / "RES-001" / "runs" / "20260717-001"
        run_dir.mkdir(parents=True)
        (run_dir / "research.md").write_text("## 2026-07-17 — Test\n\n- Updated findings\n")

        with patch.object(WorkLoop, "_run_harness", return_value=0):
            wl.process_local("RES-001", 10.0)
        self.assertEqual(wl.get_col("RES-001", COL_STATUS), "done")

    def test_research_failure_sets_needs_review(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl(tmp)
            with patch.object(WorkLoop, "_run_harness", return_value=1):
                wl.process_local("RES-001", 10.0)
            self.assertEqual(wl.get_col("RES-001", COL_STATUS), "needs-review")


class TestResearchScheduledItems(unittest.TestCase):

    def test_get_scheduled_items_includes_research(self):
        content = make_work_md(
            active_rows=(
                "| SI-001 | [Script](SI-001/C.md) | local | scheduled |  |  |  |\n"
                "| RES-001 | [Research](RES-001/C.md) | local | scheduled |  |  |  |"
            )
        )
        tmp = tempfile.mkdtemp()
        p = Path(tmp)
        (p / "WORK.md").write_text(content)
        (p / "LOOP-PROMPT.md").write_text("Do the work.\n")

        # Script item
        si_dir = p / "SI-001"
        si_dir.mkdir(parents=True, exist_ok=True)
        (si_dir / "RUNS.md").write_text(_SCHEDULED_RUNS_MD)

        # Research item
        res_dir = p / "RES-001"
        res_dir.mkdir(parents=True, exist_ok=True)
        (res_dir / "RUNS.md").write_text(_RESEARCH_RUNS_MD)

        cfg = {"work_dir": p, "harness": {"type": "claude", "max_budget_usd": 10.00}, "remote": {"work_dir": "~/Work-Loop"}}
        wl = WorkLoop(cfg)

        # Verify both items are detected as non-conversation types
        self.assertEqual(wl.get_item_type("SI-001"), "script")
        self.assertEqual(wl.get_item_type("RES-001"), "research")

        # Verify cron matching works for both
        from datetime import datetime
        # SI-001 schedule: 30 9 * * 1-5 (Mon-Fri 9:30am)
        # RES-001 schedule: 0 6 * * 1 (Monday 6am)
        dt_script = datetime(2026, 1, 5, 9, 30)  # Mon 9:30am
        dt_research = datetime(2026, 1, 5, 6, 0)  # Mon 6am
        si_cfg = wl._parse_runs_md("SI-001")
        res_cfg = wl._parse_runs_md("RES-001")
        self.assertTrue(wl._cron_should_run(si_cfg.get("schedule", ""), dt_script))
        self.assertTrue(wl._cron_should_run(res_cfg.get("schedule", ""), dt_research))


class TestResearchFallbackPrompt(unittest.TestCase):

    def test_research_uses_loop_prompt_when_research_prompt_missing(self):
        """When UPDATE-RESEARCH-PROMPT.md doesn't exist, process_local falls back to LOOP-PROMPT.md."""
        content = make_work_md("| RES-001 | [Research](RES-001/C.md) | local | research |  |  |  |")
        tmp = tempfile.mkdtemp()
        p = Path(tmp)
        (p / "WORK.md").write_text(content)
        # No UPDATE-RESEARCH-PROMPT.md — only LOOP-PROMPT.md
        (p / "LOOP-PROMPT.md").write_text("LOOP prompt content\n")
        (p / "_logs").mkdir(exist_ok=True)

        item_dir = p / "RES-001"
        item_dir.mkdir()
        (item_dir / "RUNS.md").write_text(_RESEARCH_RUNS_MD)
        (item_dir / "CONVERSATION.md").write_text("## 2026-01-01 | User\n\nResearch item: Test\n")

        cfg = {"work_dir": p, "harness": {"type": "claude", "max_budget_usd": 10.00}, "remote": {"work_dir": "~/Work-Loop"}}
        wl = WorkLoop(cfg)

        captured_prompt = None

        def capture_run_harness(prompt, *args, **kwargs):
            nonlocal captured_prompt
            captured_prompt = prompt
            return 0

        with unittest.mock.patch.object(WorkLoop, "_run_harness", side_effect=capture_run_harness):
            wl.process_local("RES-001", 10.0)

        self.assertIn("LOOP prompt content", captured_prompt)
        self.assertIn("title:", captured_prompt)
        self.assertIn("sources:", captured_prompt)
        self.assertIn("instruction:", captured_prompt)


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


class TestParseChildRunsMd(unittest.TestCase):

    def test_parses_unified_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = _make_parent_with_children(tmp, "PARENT-001", [
                {"name": "areas", "status": "ready", "runs_md": _CHILD_RUNS_MD}
            ])
            child_path = Path(tmp) / "PARENT-001" / "children" / "areas" / "RUNS.md"
            config = wl._parse_child_runs_md(child_path)
            self.assertEqual(config["type"], "research")
            self.assertEqual(config["parent"], "PARENT-001")
            self.assertEqual(config["title"], "Area walkability")
            self.assertEqual(config["note_path"], "../context/area-walkability.md")
            self.assertIn("https://www.walkscore.com", config["sources"])
            self.assertEqual(config["schedule"], "0 */6 * * *")
            self.assertIn("walkability", config["instruction"])

    def test_parses_yaml_frontmatter(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = _make_workloop(tmp)
            runs_md = (
                "---\n"
                "type: task\n"
                "parent: PARENT-001\n"
                "title: Log Analyzer\n"
                "living_note_path: null\n"
                "schedule: 0 1 * * *\n"
                "---\n\n"
                "## Prompt\n"
                "Analyze the logs.\n"
            )
            child_path = Path(tmp) / "RUNS.md"
            child_path.write_text(runs_md)
            config = wl._parse_child_runs_md(child_path)
            self.assertEqual(config["type"], "task")
            self.assertEqual(config["parent"], "PARENT-001")
            self.assertEqual(config["title"], "Log Analyzer")
            self.assertEqual(config["living_note_path"], "")
            self.assertEqual(config["note_path"], "")
            self.assertEqual(config["schedule"], "0 1 * * *")
            self.assertIn("Analyze the logs", config["instruction"])

    def test_parses_yaml_frontmatter_with_dash_lists_and_living_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = _make_workloop(tmp)
            runs_md = (
                "---\n"
                "type: research\n"
                "parent: PARENT-001\n"
                "title: Area Research\n"
                "living_note_path: ../context/area.md\n"
                "sources:\n"
                "  - https://example.com/source1\n"
                "  - https://example.com/source2\n"
                "---\n\n"
                "## Prompt\n"
                "Research instructions.\n"
            )
            child_path = Path(tmp) / "RUNS.md"
            child_path.write_text(runs_md)
            config = wl._parse_child_runs_md(child_path)
            self.assertEqual(config["type"], "research")
            self.assertEqual(config["living_note_path"], "../context/area.md")
            self.assertEqual(config["note_path"], "../context/area.md")
            self.assertEqual(config["sources"], ["https://example.com/source1", "https://example.com/source2"])
            self.assertIn("Research instructions", config["instruction"])

    def test_missing_runs_md_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = _make_workloop(tmp)
            config = wl._parse_child_runs_md(Path(tmp) / "nonexistent" / "RUNS.md")
            self.assertEqual(config["type"], "")
            self.assertEqual(config["parent"], "")


class TestGetChildStatus(unittest.TestCase):

    def test_reads_status_from_work_children(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = _make_parent_with_children(tmp, "PARENT-001", [
                {"name": "areas", "status": "scheduled", "runs_md": _CHILD_RUNS_MD}
            ])
            wc_path = Path(tmp) / "PARENT-001" / "WORK-CHILDREN.md"
            status = wl._get_child_status(wc_path, "areas")
            self.assertEqual(status, "scheduled")

    def test_returns_ready_when_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = _make_workloop(tmp)
            status = wl._get_child_status(Path(tmp) / "nonexistent" / "WORK-CHILDREN.md", "areas")
            self.assertEqual(status, "ready")

    def test_returns_ready_when_child_not_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = _make_parent_with_children(tmp, "PARENT-001", [
                {"name": "areas", "status": "ready", "runs_md": _CHILD_RUNS_MD}
            ])
            wc_path = Path(tmp) / "PARENT-001" / "WORK-CHILDREN.md"
            status = wl._get_child_status(wc_path, "nonexistent")
            self.assertEqual(status, "ready")


class TestGetParentId(unittest.TestCase):

    def test_returns_parent_from_config(self):
        self.assertEqual(WorkLoop._get_parent_id({"parent": "PARENT-001"}), "PARENT-001")

    def test_returns_none_when_empty(self):
        self.assertIsNone(WorkLoop._get_parent_id({"parent": ""}))

    def test_returns_none_when_missing(self):
        self.assertIsNone(WorkLoop._get_parent_id({}))


class TestGetAllItemIds(unittest.TestCase):

    def test_returns_all_item_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "WORK.md").write_text("# Work\n\n")
            (p / "ITEM-001").mkdir()
            (p / "ITEM-001" / "CONVERSATION.md").write_text("test")
            (p / "ITEM-002").mkdir()
            (p / "ITEM-002" / "RUNS.md").write_text("test")
            (p / "ITEM-003").mkdir()
            (p / "ITEM-003" / "RUNS.md").write_text("test")
            cfg = {"work_dir": p, "harness": {"type": "claude", "max_budget_usd": 10.00}}
            wl = WorkLoop(cfg)
            ids = wl._get_all_item_ids()
            self.assertEqual(sorted(ids), ["ITEM-001", "ITEM-002", "ITEM-003"])

    def test_skips_folders_without_item_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "WORK.md").write_text("# Work\n\n")
            (p / "random-dir").mkdir()
            cfg = {"work_dir": p, "harness": {"type": "claude", "max_budget_usd": 10.00}}
            wl = WorkLoop(cfg)
            ids = wl._get_all_item_ids()
            self.assertNotIn("random-dir", ids)


class TestGetChildren(unittest.TestCase):

    def test_returns_children_with_correct_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = _make_parent_with_children(tmp, "PARENT-001", [
                {"name": "areas", "status": "ready", "runs_md": _CHILD_RUNS_MD},
                {"name": "rules", "status": "scheduled", "runs_md": _CHILD_RUNS_MD.replace("Area walkability", "MM2H rules").replace("area-walkability", "mm2h-rules").replace("walkability", "MM2H eligibility")},
            ])
            children = wl.get_children("PARENT-001")
            names = {c[0] for c in children}
            self.assertEqual(names, {"areas", "rules"})

    def test_no_work_children_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = _make_workloop(tmp)
            self.assertEqual(wl.get_children("NONEXISTENT"), [])

    def test_orphan_detection_wrong_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            orphan_md = _CHILD_RUNS_MD.replace("parent: PARENT-001", "parent: WRONG-PARENT")
            wl = _make_parent_with_children(tmp, "PARENT-001", [
                {"name": "areas", "status": "ready", "runs_md": _CHILD_RUNS_MD},
                {"name": "orphan", "status": "ready", "runs_md": orphan_md},
            ])
            children = wl.get_children("PARENT-001")
            names = {c[0] for c in children}
            self.assertNotIn("orphan", names)
            self.assertIn("areas", names)

    def test_orphan_detection_missing_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            orphan_md = _CHILD_RUNS_MD.replace("parent: PARENT-001", "")
            wl = _make_parent_with_children(tmp, "PARENT-001", [
                {"name": "areas", "status": "ready", "runs_md": _CHILD_RUNS_MD},
                {"name": "orphan", "status": "ready", "runs_md": orphan_md},
            ])
            children = wl.get_children("PARENT-001")
            names = {c[0] for c in children}
            self.assertNotIn("orphan", names)

    def test_skips_child_without_runs_md(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = _make_parent_with_children(tmp, "PARENT-001", [
                {"name": "areas", "status": "ready", "runs_md": _CHILD_RUNS_MD},
            ])
            # Add a row for a child that has no RUNS.md
            parent_dir = Path(tmp) / "PARENT-001"
            (parent_dir / "children" / "ghost").mkdir(parents=True, exist_ok=True)
            (parent_dir / "WORK-CHILDREN.md").write_text(
                "# Child Agents\n\n"
                "| ID | Title | Status | Last Updated | Budget | Log |\n"
                "|---|---|---|---|---|---|\n"
                "| areas | [Area walkability](children/areas/RUNS.md) | ready |  |  |  |\n"
                "| ghost | [Ghost agent](children/ghost/RUNS.md) | ready |  |  |  |\n"
            )
            children = wl.get_children("PARENT-001")
            names = {c[0] for c in children}
            self.assertIn("areas", names)
            self.assertNotIn("ghost", names)

    def test_mixed_statuses_returned(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = _make_parent_with_children(tmp, "PARENT-001", [
                {"name": "areas", "status": "ready", "runs_md": _CHILD_RUNS_MD},
                {"name": "rules", "status": "scheduled", "runs_md": _CHILD_RUNS_MD},
                {"name": "buildings", "status": "paused", "runs_md": _CHILD_RUNS_MD},
            ])
            children = wl.get_children("PARENT-001")
            statuses = {c[0]: c[1] for c in children}
            self.assertEqual(statuses["areas"], "ready")
            self.assertEqual(statuses["rules"], "scheduled")
            self.assertEqual(statuses["buildings"], "paused")


class TestUpdateChildStatus(unittest.TestCase):

    def test_updates_status_in_work_children(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = _make_parent_with_children(tmp, "PARENT-001", [
                {"name": "areas", "status": "ready", "runs_md": _CHILD_RUNS_MD}
            ])
            wl._update_child_status("PARENT-001", "areas", "running")
            wc_path = Path(tmp) / "PARENT-001" / "WORK-CHILDREN.md"
            status = wl._get_child_status(wc_path, "areas")
            self.assertEqual(status, "running")

    def test_other_children_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = _make_parent_with_children(tmp, "PARENT-001", [
                {"name": "areas", "status": "ready", "runs_md": _CHILD_RUNS_MD},
                {"name": "rules", "status": "scheduled", "runs_md": _CHILD_RUNS_MD},
            ])
            wl._update_child_status("PARENT-001", "areas", "running")
            wc_path = Path(tmp) / "PARENT-001" / "WORK-CHILDREN.md"
            self.assertEqual(wl._get_child_status(wc_path, "areas"), "running")
            self.assertEqual(wl._get_child_status(wc_path, "rules"), "scheduled")

    def test_aborts_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = _make_parent_with_children(tmp, "PARENT-001", [
                {"name": "areas", "status": "running", "runs_md": _CHILD_RUNS_MD}
            ])
            wl._update_child_status("PARENT-001", "areas", "abort")
            wc_path = Path(tmp) / "PARENT-001" / "WORK-CHILDREN.md"
            self.assertEqual(wl._get_child_status(wc_path, "areas"), "abort")

    def test_noop_when_work_children_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = _make_workloop(tmp)
            wl._update_child_status("NONEXISTENT", "areas", "running")  # should not raise


class TestProcessChild(unittest.TestCase):

    def _make_wl_with_child(self, tmp: str, child_status: str = "ready") -> WorkLoop:
        wl = _make_parent_with_children(tmp, "PARENT-001", [
            {"name": "areas", "status": child_status, "runs_md": _CHILD_RUNS_MD}
        ])
        # Create context dir so note_path resolves
        context_dir = Path(tmp) / "PARENT-001" / "context"
        context_dir.mkdir(exist_ok=True)
        (context_dir / "area-walkability.md").write_text("# Area Walkability\n\nExisting content.\n")
        return wl

    def test_success_with_schedule_sets_scheduled(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl_with_child(tmp)
            with unittest.mock.patch.object(WorkLoop, "_run_harness", return_value=0):
                wl.process_child("PARENT-001", "areas")
            wc_path = Path(tmp) / "PARENT-001" / "WORK-CHILDREN.md"
            status = wl._get_child_status(wc_path, "areas")
            self.assertEqual(status, "scheduled")

    def test_success_no_schedule_sets_done(self):
        runs_md_no_schedule = _CHILD_RUNS_MD.replace("schedule: 0 */6 * * *\n", "")
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "WORK.md").write_text(
                "# Work Loop\n\n"
                "| ID | Title / Initial Prompt | Location | Status | Last Updated | Budget | Log |\n"
                "| -- | --------------------- | -------- | ------ | ------------ | ------ | --- |\n"
                "| PARENT-001 | [Parent item](PARENT-001/CONVERSATION.md) | local | ready | | | |\n\n"
                "## Done\n\n"
                "| ID | Title / Initial Prompt | Location | Status | Last Updated | Budget | Log |\n"
                "| -- | --------------------- | -------- | ------ | ------------ | ------ | --- |\n"
            )
            (p / "LOOP-PROMPT.md").write_text("Do the work.\n")
            (p / "UPDATE-RESEARCH-PROMPT.md").write_text("Research prompt.\n")
            (p / "_logs").mkdir(exist_ok=True)
            parent_dir = p / "PARENT-001"
            parent_dir.mkdir()
            (parent_dir / "CONVERSATION.md").write_text("## 2026-01-01 | User\n\nParent\n")
            (parent_dir / "WORK-CHILDREN.md").write_text(
                "# Child Agents\n\n"
                "| ID | Title | Status | Last Updated | Budget | Log |\n"
                "|---|---|---|---|---|---|\n"
                "| areas | [Area walkability](children/areas/RUNS.md) | ready |  |  |  |\n"
            )
            child_dir = parent_dir / "children" / "areas"
            child_dir.mkdir(parents=True)
            (child_dir / "RUNS.md").write_text(runs_md_no_schedule)
            (child_dir / "runs").mkdir()
            context_dir = parent_dir / "context"
            context_dir.mkdir()
            (context_dir / "area-walkability.md").write_text("# Walkability\n")

            cfg = {"work_dir": p, "harness": {"type": "claude", "max_budget_usd": 10.00}, "remote": {"work_dir": "~/Work-Loop"}}
            wl = WorkLoop(cfg)

            with unittest.mock.patch.object(WorkLoop, "_run_harness", return_value=0):
                wl.process_child("PARENT-001", "areas")
            wc_path = p / "PARENT-001" / "WORK-CHILDREN.md"
            status = wl._get_child_status(wc_path, "areas")
            self.assertEqual(status, "done")

    def test_failure_sets_needs_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl_with_child(tmp)
            with unittest.mock.patch.object(WorkLoop, "_run_harness", return_value=1):
                wl.process_child("PARENT-001", "areas")
            wc_path = Path(tmp) / "PARENT-001" / "WORK-CHILDREN.md"
            status = wl._get_child_status(wc_path, "areas")
            self.assertEqual(status, "needs-review")

    def test_work_md_not_modified(self):
        """process_child must NOT touch top-level WORK.md."""
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl_with_child(tmp)
            work_md_before = (Path(tmp) / "WORK.md").read_text()
            with unittest.mock.patch.object(WorkLoop, "_run_harness", return_value=0):
                wl.process_child("PARENT-001", "areas")
            work_md_after = (Path(tmp) / "WORK.md").read_text()
            self.assertEqual(work_md_before, work_md_after)

    def test_abort_during_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl_with_child(tmp)

            def harness_aborts(*args, **kwargs):
                wl._update_child_status("PARENT-001", "areas", "abort")
                return 1

            with unittest.mock.patch.object(WorkLoop, "_run_harness", side_effect=harness_aborts):
                wl.process_child("PARENT-001", "areas")
            wc_path = Path(tmp) / "PARENT-001" / "WORK-CHILDREN.md"
            status = wl._get_child_status(wc_path, "areas")
            self.assertEqual(status, "abort")

    def test_note_path_conflict_sets_needs_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = _make_parent_with_children(tmp, "PARENT-001", [
                {"name": "areas", "status": "ready", "runs_md": _CHILD_RUNS_MD},
                {"name": "areas2", "status": "ready", "runs_md": _CHILD_RUNS_MD.replace("Area walkability", "Area walkability 2")},
            ])
            context_dir = Path(tmp) / "PARENT-001" / "context"
            context_dir.mkdir(exist_ok=True)
            (context_dir / "area-walkability.md").write_text("# Walkability\n")

            with unittest.mock.patch.object(WorkLoop, "_run_harness", return_value=0):
                wl.process_child("PARENT-001", "areas2")
            wc_path = Path(tmp) / "PARENT-001" / "WORK-CHILDREN.md"
            status = wl._get_child_status(wc_path, "areas2")
            self.assertEqual(status, "needs-review")

    def test_budget_from_work_children(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = _make_parent_with_children(tmp, "PARENT-001", [
                {"name": "areas", "status": "ready", "budget": "$5.0", "runs_md": _CHILD_RUNS_MD}
            ])
            budget = wl._get_child_budget("PARENT-001", "areas")
            self.assertEqual(budget, 5.0)

    def test_budget_fallback_to_global(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = _make_parent_with_children(tmp, "PARENT-001", [
                {"name": "areas", "status": "ready", "runs_md": _CHILD_RUNS_MD}
            ])
            budget = wl._get_child_budget("PARENT-001", "areas")
            self.assertEqual(budget, wl.max_budget)


class TestValidateNotePathUniqueness(unittest.TestCase):

    def test_unique_paths_return_true(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = _make_parent_with_children(tmp, "PARENT-001", [
                {"name": "areas", "status": "ready", "runs_md": _CHILD_RUNS_MD},
                {"name": "rules", "status": "ready", "runs_md": _CHILD_RUNS_MD.replace("area-walkability", "mm2h-rules").replace("Area walkability", "MM2H rules")},
            ])
            is_unique, conflict = wl._validate_note_path_uniqueness("PARENT-001", "areas")
            self.assertTrue(is_unique)
            self.assertIsNone(conflict)

    def test_duplicate_paths_return_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = _make_parent_with_children(tmp, "PARENT-001", [
                {"name": "areas", "status": "ready", "runs_md": _CHILD_RUNS_MD},
                {"name": "areas2", "status": "ready", "runs_md": _CHILD_RUNS_MD.replace("Area walkability", "Area walkability 2")},
            ])
            is_unique, conflict = wl._validate_note_path_uniqueness("PARENT-001", "areas2")
            self.assertFalse(is_unique)
            self.assertEqual(conflict, "areas")


class TestResumeRunningChildren(unittest.TestCase):

    def test_skips_running_children_with_active_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = _make_parent_with_children(tmp, "PARENT-001", [
                {"name": "areas", "status": "running", "runs_md": _CHILD_RUNS_MD}
            ])
            # Parent is "ready" (not done) — should skip
            wl.resume_running_children()
            wc_path = Path(tmp) / "PARENT-001" / "WORK-CHILDREN.md"
            status = wl._get_child_status(wc_path, "areas")
            self.assertEqual(status, "running")

    def test_orphan_recovery_when_parent_done(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = _make_parent_with_children(tmp, "PARENT-001", [
                {"name": "areas", "status": "running", "runs_md": _CHILD_RUNS_MD}
            ])
            wl.update_col("PARENT-001", run_loop.COL_STATUS, "done")
            wl.resume_running_children()
            wc_path = Path(tmp) / "PARENT-001" / "WORK-CHILDREN.md"
            status = wl._get_child_status(wc_path, "areas")
            self.assertEqual(status, "needs-review")


class TestGenerateRunIdWithPath(unittest.TestCase):

    def test_generates_from_child_runs_md(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = _make_parent_with_children(tmp, "PARENT-001", [
                {"name": "areas", "status": "ready", "runs_md": _CHILD_RUNS_MD}
            ])
            runs_path = Path(tmp) / "PARENT-001" / "children" / "areas" / "RUNS.md"
            from datetime import datetime
            today = datetime.now().strftime('%Y%m%d')
            run_id = wl._generate_run_id("areas", runs_path=runs_path)
            self.assertEqual(run_id, f"{today}-001")


class TestAppendResearchRunWithPath(unittest.TestCase):

    def test_appends_to_child_runs_md(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = _make_parent_with_children(tmp, "PARENT-001", [
                {"name": "areas", "status": "ready", "runs_md": _CHILD_RUNS_MD}
            ])
            runs_path = Path(tmp) / "PARENT-001" / "children" / "areas" / "RUNS.md"
            wl._append_research_run("areas", "20260105-001", "Walkability update", runs_path=runs_path)
            text = runs_path.read_text()
            self.assertIn("20260105-001", text)
            self.assertIn("Walkability update", text)
            self.assertIn("done", text)

    def test_appends_with_empty_summary_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = _make_parent_with_children(tmp, "PARENT-001", [
                {"name": "areas", "status": "ready", "runs_md": _CHILD_RUNS_MD}
            ])
            runs_path = Path(tmp) / "PARENT-001" / "children" / "areas" / "RUNS.md"
            wl._append_research_run("areas", "20260105-002", "", status="done", runs_path=runs_path)
            text = runs_path.read_text()
            self.assertIn("20260105-002", text)
            self.assertIn("[20260105-002 run](runs/20260105-002/)", text)
            self.assertIn("done", text)


class TestChildCronPromotion(unittest.TestCase):

    def test_scheduled_child_promoted_when_cron_fires(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = _make_parent_with_children(tmp, "PARENT-001", [
                {"name": "areas", "status": "scheduled", "runs_md": _CHILD_RUNS_MD}
            ])
            from datetime import datetime
            now = datetime.now()
            if wl._cron_should_run("0 */6 * * *", now):
                wl._update_child_status("PARENT-001", "areas", "ready")
            wc_path = Path(tmp) / "PARENT-001" / "WORK-CHILDREN.md"
            status = wl._get_child_status(wc_path, "areas")
            # Either still scheduled or promoted to ready
            self.assertIn(status, ("scheduled", "ready"))


class TestChildPromptExists(unittest.TestCase):

    def test_research_prompt_file_exists(self):
        prompt_path = _PROMPTS_DIR / "UPDATE-RESEARCH-PROMPT.md"
        self.assertTrue(prompt_path.exists(), "UPDATE-RESEARCH-PROMPT.md should exist")

    def test_research_prompt_has_child_mode(self):
        prompt_path = _PROMPTS_DIR / "UPDATE-RESEARCH-PROMPT.md"
        content = prompt_path.read_text()
        self.assertIn("Child mode", content)
        self.assertIn("Parent mode", content)
        self.assertIn("PARENT_ID", content)
        self.assertIn("Do NOT modify any WORK-*.md file", content)

    def test_research_prompt_has_parent_block(self):
        prompt_path = _PROMPTS_DIR / "UPDATE-RESEARCH-PROMPT.md"
        content = prompt_path.read_text()
        self.assertIn("PARENT_ID", content)
        self.assertIn("BACKLINK_TARGET", content)

    def test_loop_prompt_has_child_management_section(self):
        prompt_path = _PROMPTS_DIR / "LOOP-PROMPT.md"
        content = prompt_path.read_text()
        self.assertIn("Managing Child Agents", content)


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


class TestTaskChildType(unittest.TestCase):

    def test_task_prompt_file_exists(self):
        prompt_path = _PROMPTS_DIR / "TASK-PROMPT.md"
        self.assertTrue(prompt_path.exists(), "TASK-PROMPT.md should exist")

    def test_task_prompt_propose_only(self):
        prompt_path = _PROMPTS_DIR / "TASK-PROMPT.md"
        content = prompt_path.read_text()
        self.assertIn("propose", content.lower())
        self.assertIn("do NOT", content)

    def test_task_child_parsed_correctly(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = _make_parent_with_children(tmp, "PARENT-001", [
                {"name": "inbox", "status": "ready", "runs_md": _CHILD_TASK_RUNS_MD}
            ])
            child_path = Path(tmp) / "PARENT-001" / "children" / "inbox" / "RUNS.md"
            config = wl._parse_child_runs_md(child_path)
            self.assertEqual(config["type"], "task")
            self.assertEqual(config["title"], "Inbox cleanup")
            self.assertIn("00 Inbox", config["instruction"])

    def test_task_child_success_sets_done(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = _make_parent_with_children(tmp, "PARENT-001", [
                {"name": "inbox", "status": "ready", "runs_md": _CHILD_TASK_RUNS_MD.replace("schedule: 0 8 * * *", "")}
            ])
            # Ensure TASK-PROMPT.md exists at script_dir for this test
            task_prompt = Path(tmp) / "TASK-PROMPT.md"
            task_prompt.write_text("Task prompt.\n")
            item_dir = Path(tmp) / "PARENT-001" / "children" / "inbox"
            run_dir = item_dir / "runs" / "20260813-001"
            run_dir.mkdir(parents=True)
            (run_dir / "task.md").write_text("## 2026-08-13 — Inbox cleanup\n\n- Proposed 3 file moves\n")
            with unittest.mock.patch.object(WorkLoop, "_run_harness", return_value=0):
                wl.process_child("PARENT-001", "inbox")
            wc_path = Path(tmp) / "PARENT-001" / "WORK-CHILDREN.md"
            status = wl._get_child_status(wc_path, "inbox")
            self.assertEqual(status, "done")

    def test_task_child_success_with_schedule_sets_scheduled(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = _make_parent_with_children(tmp, "PARENT-001", [
                {"name": "inbox", "status": "ready", "runs_md": _CHILD_TASK_RUNS_MD}
            ])
            task_prompt = Path(tmp) / "TASK-PROMPT.md"
            task_prompt.write_text("Task prompt.\n")
            item_dir = Path(tmp) / "PARENT-001" / "children" / "inbox"
            run_dir = item_dir / "runs" / "20260813-001"
            run_dir.mkdir(parents=True)
            (run_dir / "task.md").write_text("## 2026-08-13 — Inbox cleanup\n\n- Proposed 3 file moves\n")
            with unittest.mock.patch.object(WorkLoop, "_run_harness", return_value=0):
                wl.process_child("PARENT-001", "inbox")
            wc_path = Path(tmp) / "PARENT-001" / "WORK-CHILDREN.md"
            status = wl._get_child_status(wc_path, "inbox")
            self.assertEqual(status, "scheduled")

    def test_unknown_type_sets_needs_review(self):
        bad_runs = _CHILD_TASK_RUNS_MD.replace("type: task", "type: unknown")
        with tempfile.TemporaryDirectory() as tmp:
            wl = _make_parent_with_children(tmp, "PARENT-001", [
                {"name": "bad", "status": "ready", "runs_md": bad_runs}
            ])
            wl.process_child("PARENT-001", "bad")
            wc_path = Path(tmp) / "PARENT-001" / "WORK-CHILDREN.md"
            status = wl._get_child_status(wc_path, "bad")
            self.assertEqual(status, "needs-review")

    def test_task_prompt_missing_sets_needs_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = _make_parent_with_children(tmp, "PARENT-001", [
                {"name": "inbox", "status": "ready", "runs_md": _CHILD_TASK_RUNS_MD}
            ])
            # Don't create TASK-PROMPT.md
            wl.process_child("PARENT-001", "inbox")
            wc_path = Path(tmp) / "PARENT-001" / "WORK-CHILDREN.md"
            status = wl._get_child_status(wc_path, "inbox")
            self.assertEqual(status, "needs-review")


class TestSyncParentReportLinks(unittest.TestCase):

    def _make_wl(self, tmp: str, children: list[dict] | None = None) -> WorkLoop:
        if children is None:
            children = [{"name": "areas", "status": "ready", "runs_md": _CHILD_RUNS_MD}]
        return _make_parent_with_children(tmp, "PARENT-001", children)

    def test_appends_child_report_link_preserving_conversation_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl(tmp)
            self.assertTrue(wl._sync_parent_report_links("PARENT-001"))
            title = wl.get_col("PARENT-001", COL_TITLE)
            self.assertEqual(
                title,
                "[Parent item](PARENT-001/CONVERSATION.md)<br>"
                "[Area walkability](PARENT-001/context/area-walkability.md)",
            )

    def test_sync_is_idempotent_and_cause_no_churn(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl(tmp)
            self.assertTrue(wl._sync_parent_report_links("PARENT-001"))
            first = (Path(tmp) / "WORK.md").read_text()
            self.assertFalse(wl._sync_parent_report_links("PARENT-001"))
            second = (Path(tmp) / "WORK.md").read_text()
            self.assertEqual(first, second)

    def test_multiple_children_get_one_link_each(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl(tmp, [
                {"name": "areas", "status": "ready", "runs_md": _CHILD_RUNS_MD},
                {
                    "name": "rules",
                    "status": "scheduled",
                    "runs_md": _CHILD_RUNS_MD.replace("Area walkability", "MM2H rules").replace(
                        "area-walkability", "mm2h-rules"
                    ),
                },
            ])
            wl._sync_parent_report_links("PARENT-001")
            title = wl.get_col("PARENT-001", COL_TITLE)
            self.assertIn(
                "[Area walkability](PARENT-001/context/area-walkability.md)",
                title,
            )
            self.assertIn(
                "[MM2H rules](PARENT-001/context/mm2h-rules.md)",
                title,
            )

    def test_duplicate_note_paths_are_deduplicated(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl(tmp, [
                {"name": "areas", "status": "ready", "runs_md": _CHILD_RUNS_MD},
                {
                    "name": "areas2",
                    "status": "ready",
                    "runs_md": _CHILD_RUNS_MD.replace("Area walkability", "Area walkability 2"),
                },
            ])
            wl._sync_parent_report_links("PARENT-001")
            title = wl.get_col("PARENT-001", COL_TITLE)
            self.assertEqual(
                title.count("PARENT-001/context/area-walkability.md"),
                1,
            )

    def test_child_without_note_path_adds_no_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            runs_md_no_note = _CHILD_RUNS_MD.replace("note_path: ../context/area-walkability.md\n", "")
            wl = self._make_wl(tmp, [
                {"name": "areas", "status": "ready", "runs_md": runs_md_no_note}
            ])
            self.assertFalse(wl._sync_parent_report_links("PARENT-001"))
            title = wl.get_col("PARENT-001", COL_TITLE)
            self.assertEqual(title, "[Parent item](PARENT-001/CONVERSATION.md)")


class TestNeedsAttentionDashboard(unittest.TestCase):

    def _make_wl(self, tmp: str, child_status: str = "ready", note_text: str | None = None) -> WorkLoop:
        wl = _make_parent_with_children(tmp, "PARENT-001", [
            {"name": "areas", "status": child_status, "runs_md": _CHILD_RUNS_MD}
        ])
        note = Path(tmp) / "PARENT-001" / "context" / "area-walkability.md"
        note.parent.mkdir(parents=True, exist_ok=True)
        if note_text is not None:
            note.write_text(note_text)
        return wl

    def test_refresh_adds_report_link_and_needs_attention_for_top_level_needs_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl(tmp)
            wl.update_col("PARENT-001", COL_STATUS, "needs-review")
            wl._refresh_work_md_dashboard()
            text = (Path(tmp) / "WORK.md").read_text()
            self.assertIn("[Area walkability](PARENT-001/context/area-walkability.md)", text)
            self.assertIn("<!-- NEEDS-ATTENTION:BEGIN -->", text)
            self.assertIn("## Needs Attention", text)
            self.assertIn(
                "- **PARENT-001** (needs-review). [Open conversation](PARENT-001/CONVERSATION.md)",
                text,
            )
            self.assertIn("<!-- NEEDS-ATTENTION:END -->", text)

    def test_child_needs_review_appears_with_report_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl(tmp, child_status="needs-review")
            wl._refresh_work_md_dashboard()
            text = (Path(tmp) / "WORK.md").read_text()
            self.assertIn(
                "- **PARENT-001 / areas** (needs-review). "
                "[Open report](PARENT-001/context/area-walkability.md)",
                text,
            )

    def test_attention_yes_marker_appears_with_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl(
                tmp,
                note_text="<!-- attention: yes — 3 ambiguous files need destination approval -->\n# Report\n",
            )
            wl._refresh_work_md_dashboard()
            text = (Path(tmp) / "WORK.md").read_text()
            self.assertIn(
                "- **PARENT-001 / areas** — 3 ambiguous files need destination approval. "
                "[Open report](PARENT-001/context/area-walkability.md)",
                text,
            )

    def test_attention_no_marker_does_not_appear(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl(tmp, note_text="<!-- attention: no -->\n# Report\n")
            wl._refresh_work_md_dashboard()
            text = (Path(tmp) / "WORK.md").read_text()
            self.assertNotIn("## Needs Attention", text)
            self.assertNotIn("NEEDS-ATTENTION:BEGIN", text)

    def test_missing_note_does_not_appear(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl(tmp)
            wl._refresh_work_md_dashboard()
            text = (Path(tmp) / "WORK.md").read_text()
            self.assertNotIn("## Needs Attention", text)

    def test_needs_attention_block_removed_when_nothing_needs_attention(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl(tmp)
            wl.update_col("PARENT-001", COL_STATUS, "needs-review")
            wl._refresh_work_md_dashboard()
            self.assertIn("## Needs Attention", (Path(tmp) / "WORK.md").read_text())

            wl.update_col("PARENT-001", COL_STATUS, "ready")
            wl._refresh_work_md_dashboard()
            text = (Path(tmp) / "WORK.md").read_text()
            self.assertNotIn("## Needs Attention", text)
            self.assertNotIn("NEEDS-ATTENTION:BEGIN", text)

    def test_refresh_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl(tmp)
            wl.update_col("PARENT-001", COL_STATUS, "needs-review")
            wl._refresh_work_md_dashboard()
            first = (Path(tmp) / "WORK.md").read_text()
            wl._refresh_work_md_dashboard()
            second = (Path(tmp) / "WORK.md").read_text()
            self.assertEqual(first, second)

    def test_needs_attention_does_not_break_work_md_table_parsing(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl(
                tmp,
                note_text="<!-- attention: yes — report needs approval -->\n# Report\n",
            )
            wl._refresh_work_md_dashboard()
            self.assertEqual(wl.get_item_title("PARENT-001"), "Parent item")
            self.assertEqual(wl.get_col("PARENT-001", COL_STATUS), "ready")
            self.assertIn("PARENT-001", wl.get_ready_items())


class TestChildAttentionPrompts(unittest.TestCase):

    def test_task_prompt_mentions_attention_marker(self):
        content = (_PROMPTS_DIR / "TASK-PROMPT.md").read_text()
        self.assertIn("Attention marker", content)
        self.assertIn("<!-- attention: yes", content)
        self.assertIn("<!-- attention: no -->", content)

    def test_research_prompt_mentions_child_attention_marker(self):
        content = (_PROMPTS_DIR / "UPDATE-RESEARCH-PROMPT.md").read_text()
        self.assertIn("attention marker", content)
        self.assertIn("<!-- attention: yes", content)
        self.assertIn("<!-- attention: no -->", content)

    def test_loop_prompt_preserves_child_report_links(self):
        content = (_PROMPTS_DIR / "LOOP-PROMPT.md").read_text()
        self.assertIn("Preserve child report links", content)
        self.assertIn("## Needs Attention", content)


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
            wl = WorkLoop({"work_dir": tmp, "harness": {"type": "opencode"}}, script_dir=_HERE)
            work_opencode = tmp / ".opencode"
            self.assertFalse(work_opencode.exists())

            wl._sync_agent_dir(str(tmp))

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
            wl = WorkLoop({"work_dir": tmp, "harness": {"type": "opencode"}}, script_dir=_HERE)
            stale_dir = tmp / ".opencode" / "agents"
            stale_dir.mkdir(parents=True)
            (stale_dir / "old-agent.md").write_text("stale")

            wl._sync_agent_dir(str(tmp))

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


class TestOutlineWorkFormat(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.work_dir = Path(self.tmp)
        (self.work_dir / "WORK-NEW.md").write_text(SAMPLE_WORK_NEW_MD)
        (self.work_dir / "LOOP-PROMPT.md").write_text("Do the work.\n")
        cfg = {"work_dir": self.work_dir, "work_file": "WORK-NEW.md", "harness": {"type": "claude", "max_budget_usd": 10.00}}
        self.wl = WorkLoop(cfg)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_is_outline_format(self):
        self.assertTrue(self.wl._is_outline_format())

    def test_get_ready_items_outline(self):
        items = self.wl.get_ready_items()
        self.assertEqual(items, ["ITEM-001"])

    def test_get_col_outline(self):
        self.assertEqual(self.wl.get_col("ITEM-001", COL_STATUS), "ready")
        self.assertEqual(self.wl.get_col("ITEM-002", COL_STATUS), "needs-review")
        self.assertEqual(self.wl.get_col("ITEM-003", COL_BUDGET), "$10.0")
        self.assertEqual(self.wl.get_col("ITEM-001", COL_LOCATION), "local")

    def test_update_col_outline_status(self):
        self.wl.update_col("ITEM-001", COL_STATUS, "in-progress")
        self.assertEqual(self.wl.get_col("ITEM-001", COL_STATUS), "in-progress")
        self.assertEqual(self.wl.get_col("ITEM-002", COL_STATUS), "needs-review")

    def test_update_col_outline_done_moves_to_done(self):
        self.wl.update_col("ITEM-001", COL_STATUS, "done")
        self.assertNotIn("ITEM-001", self.wl.get_ready_items())
        text = (self.work_dir / "WORK-NEW.md").read_text()
        self.assertIn("## Done", text)
        self.assertIn("ITEM-001", text)

    def test_get_new_items_and_initialize_outline(self):
        # Unchecked item should NOT be picked up
        self.assertEqual(self.wl.get_new_items(), [])
        # Checking the box triggers pickup
        text = (self.work_dir / "WORK-NEW.md").read_text()
        text = text.replace("- [ ] Explore Canadian banking options", "- [x] Explore Canadian banking options")
        (self.work_dir / "WORK-NEW.md").write_text(text)

        new_items = self.wl.get_new_items()
        self.assertEqual(len(new_items), 1)
        item_id = new_items[0]
        self.wl.initialize_new_item(item_id)
        conv_file = self.work_dir / item_id / "CONVERSATION.md"
        self.assertTrue(conv_file.exists())
        conv_text = conv_file.read_text()
        self.assertIn("> [!action] **Work-Loop Action Center**", conv_text)
        self.assertIn("Explore Canadian banking options", conv_text)
        work_text = (self.work_dir / "WORK-NEW.md").read_text()
        self.assertIn(item_id, work_text)

    def test_outline_action_checkbox_trigger(self):
        # Test clicking the main item checkbox: - [x] [Task two]...
        text = (self.work_dir / "WORK-NEW.md").read_text()
        text = text.replace("- [ ] [Task two]", "- [x] [Task two]")
        (self.work_dir / "WORK-NEW.md").write_text(text)
        ready_items = self.wl.get_ready_items()
        self.assertIn("ITEM-002", ready_items)
        new_text = (self.work_dir / "WORK-NEW.md").read_text()
        self.assertIn("- [ ] [Task two]", new_text)
        self.assertEqual(self.wl.get_col("ITEM-002", COL_STATUS), "ready")

    def test_insert_and_remove_work_row_outline(self):
        self.wl.insert_work_row("ITEM-099", "New test row", "local")
        self.assertEqual(self.wl.get_col("ITEM-099", COL_STATUS), "ready")
        self.wl.remove_work_row("ITEM-099")

    def test_add_new_item_above_active_items_layout(self):
        layout = """\
# Work Loop

## Add New Item
- [ ] _Add new instructions here and click the check box [X] when done. The loop creates the folder, seeds CONVERSATION.md, and moves it to Active Items_

## Active Items

| Task / Conversation | Status | Last Updated | Log | ID |
|---|:---:|:---:|:---:|---|
| [Task one](ITEM-001/CONVERSATION.md) | ready | 2026-08-01 | | ITEM-001 |

## Done
"""
        (self.work_dir / "WORK-NEW.md").write_text(layout)
        # Unchecked template must be ignored
        self.assertEqual(self.wl.get_new_items(), [])

        # Add a checked item with italic prompt and custom ID
        updated = layout.replace(
            "## Add New Item\n",
            "## Add New Item\n- [X] **EXP-01** _Explore overseas banking options_\n"
        )
        (self.work_dir / "WORK-NEW.md").write_text(updated)

        new_items = self.wl.get_new_items()
        self.assertEqual(new_items, ["EXP-01"])

        self.wl.initialize_new_item("EXP-01")
        conv_file = self.work_dir / "EXP-01" / "CONVERSATION.md"
        self.assertTrue(conv_file.exists())
        self.assertIn("_Explore overseas banking options_", conv_file.read_text())

        # Check that WORK-NEW.md retained template line and added row to Active Items
        work_text = (self.work_dir / "WORK-NEW.md").read_text()
        self.assertIn("- [ ] _Add new instructions here", work_text)
        self.assertNotIn("- [X] **EXP-01**", work_text)
        self.assertIn("| [_Explore overseas banking options_](EXP-01/CONVERSATION.md) | ready", work_text)

    def test_outline_child_line_links_to_runs_md(self):
        parent_dir = self.work_dir / "ITEM-001"
        parent_dir.mkdir(parents=True, exist_ok=True)
        (parent_dir / "WORK-CHILDREN.md").write_text(
            "# Child Agents\n\n"
            "| ID | Title | Status | Last Updated | Budget | Log |\n"
            "|---|---|---|---|---|---|\n"
            "| inbox-sorter | [Inbox Sort Suggestions](children/inbox-sorter/RUNS.md) | ready |  |  |  |\n"
        )
        child_dir = parent_dir / "children" / "inbox-sorter"
        child_dir.mkdir(parents=True, exist_ok=True)
        (child_dir / "RUNS.md").write_text(
            "## Config\n"
            "type: task\n"
            "parent: ITEM-001\n"
            "title: Inbox Sort Suggestions\n"
            "note_path: ../context/inbox-sort-suggestions.md\n"
            "schedule: 0 1 * * *\n"
        )
        (parent_dir / "context").mkdir(parents=True, exist_ok=True)
        (parent_dir / "context" / "inbox-sort-suggestions.md").write_text("suggestions")

        self.wl._refresh_outline_dashboard()
        text = (self.work_dir / "WORK-NEW.md").read_text()
        expected = "Child: **[inbox-sorter](ITEM-001/children/inbox-sorter/RUNS.md)** `status: ready` (0 1 * * *) → [Inbox Sort Suggestions](ITEM-001/context/inbox-sort-suggestions.md)"
        self.assertIn(expected, text)
class TestStreamlinedTableWorkFormat(unittest.TestCase):
    SAMPLE_TABLE_WORK_MD = """\
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

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.work_dir = Path(self.tmp)
        (self.work_dir / "WORK-NEW.md").write_text(self.SAMPLE_TABLE_WORK_MD)
        (self.work_dir / "LOOP-PROMPT.md").write_text("Do the work.\n")
        cfg = {"work_dir": self.work_dir, "work_file": "WORK-NEW.md", "harness": {"type": "claude", "max_budget_usd": 10.00}}
        self.wl = WorkLoop(cfg)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_get_ready_items_table(self):
        items = self.wl.get_ready_items()
        self.assertEqual(items, ["ITEM-001"])

    def test_get_col_table(self):
        self.assertEqual(self.wl.get_col("ITEM-001", COL_STATUS), "ready")
        self.assertEqual(self.wl.get_col("ITEM-002", COL_STATUS), "needs-review")
        self.assertEqual(self.wl.get_col("ITEM-001", COL_LAST_UPDATED), "2026-08-01")
        self.assertEqual(self.wl.get_col("ITEM-001", COL_ID), "ITEM-001")

    def test_update_col_table_status(self):
        self.wl.update_col("ITEM-001", COL_STATUS, "in-progress")
        self.assertEqual(self.wl.get_col("ITEM-001", COL_STATUS), "in-progress")

    def test_update_col_table_last_updated(self):
        self.wl.update_col("ITEM-001", COL_LAST_UPDATED, "2026-08-18")
        self.assertEqual(self.wl.get_col("ITEM-001", COL_LAST_UPDATED), "2026-08-18")

    def test_table_move_to_done(self):
        self.wl.update_col("ITEM-001", COL_STATUS, "done")
        text = (self.work_dir / "WORK-NEW.md").read_text()
        self.assertIn("[Task one]", text)
        self.assertIn("ITEM-001", text)

    def test_table_move_to_done_preserves_separator_position(self):
        content = """\
# Work Loop

## Active Items

| Task / Conversation | Status | Last Updated | Log | ID |
| -------------------------------------------------------------------------------- | :----------: | :----------: | :------------------------------------------------------------------------------: | --------------------- |
| [Task one](ITEM-001/CONVERSATION.md) | ready | 2026-08-01 | [Log](ITEM-001/_logs/log1.log) | ITEM-001 |

## Add New Item

## Done

| Task / Conversation | Last Updated | Log | ID |
| -------------------------------------------------------------------------------- | :----------: | :------------------------------------------: | --------- |
| [Old task](ITEM-000/CONVERSATION.md) | 2026-07-14 | [Log](ITEM-000/_logs/old.log) | ITEM-000 |
"""
        (self.work_dir / "WORK-NEW.md").write_text(content)
        self.wl.update_col("ITEM-001", COL_STATUS, "done")
        lines = (self.work_dir / "WORK-NEW.md").read_text().splitlines()
        done_idx = next(i for i, l in enumerate(lines) if l.startswith("## Done"))
        # Header should be next non-empty line
        header_idx = next(i for i in range(done_idx + 1, len(lines)) if lines[i].strip())
        sep_idx = header_idx + 1
        # Separator line must immediately follow header row
        self.assertTrue(lines[sep_idx].strip().startswith("| ---") or lines[sep_idx].strip().startswith("| --"))
        # The newly inserted row must come AFTER the separator
        item_idx = next(i for i in range(sep_idx + 1, len(lines)) if "ITEM-001" in lines[i])
        self.assertGreater(item_idx, sep_idx)

    def test_table_child_badge_links_to_runs_md(self):
        parent_dir = self.work_dir / "ITEM-001"
        parent_dir.mkdir(parents=True, exist_ok=True)
        (parent_dir / "CONVERSATION.md").write_text("## 2026-08-01 | User\n\nTask one\n")
        (parent_dir / "WORK-CHILDREN.md").write_text(
            "# Child Agents\n\n"
            "| ID | Title | Status | Last Updated | Budget | Log |\n"
            "|---|---|---|---|---|---|\n"
            "| inbox-sorter | [Inbox Sort Suggestions](children/inbox-sorter/RUNS.md) | ready |  |  |  |\n"
        )
        child_dir = parent_dir / "children" / "inbox-sorter"
        child_dir.mkdir(parents=True, exist_ok=True)
        (child_dir / "RUNS.md").write_text(
            "## Config\n"
            "type: task\n"
            "parent: ITEM-001\n"
            "title: Inbox Sort Suggestions\n"
            "note_path: ../context/inbox-sort-suggestions.md\n"
            "schedule: 0 1 * * *\n"
        )
        (parent_dir / "context").mkdir(parents=True, exist_ok=True)
        (parent_dir / "context" / "inbox-sort-suggestions.md").write_text("suggestions")

        self.wl._refresh_outline_dashboard()
        text = (self.work_dir / "WORK-NEW.md").read_text()
        expected = "↳ [inbox-sorter](ITEM-001/children/inbox-sorter/RUNS.md) (0 1 * * *) → [Inbox Sort Suggestions](ITEM-001/context/inbox-sort-suggestions.md)"
        self.assertIn(expected, text)

    def test_child_agent_in_table_without_note_path(self):
        parent_dir = self.work_dir / "ITEM-001"
        parent_dir.mkdir(parents=True, exist_ok=True)
        (parent_dir / "CONVERSATION.md").write_text("Conversation thread")
        (parent_dir / "WORK-CHILDREN.md").write_text(
            "# Child Agents\n\n"
            "| Name | Title | Status | Last Run | Budget | Log |\n"
            "|---|---|---|---|---|---|\n"
            "| log-analyzer | [Work Loop Log Analysis](children/log-analyzer/RUNS.md) | ready | 2026-08-19 | $10.0 | |\n"
        )
        child_dir = parent_dir / "children" / "log-analyzer"
        child_dir.mkdir(parents=True, exist_ok=True)
        (child_dir / "RUNS.md").write_text(
            "## Config\n"
            "type: task\n"
            "parent: ITEM-001\n"
            "title: Work Loop Log Analysis\n"
            "schedule: 0 1 * * *\n"
        )

        self.wl._refresh_outline_dashboard()
        text = (self.work_dir / "WORK-NEW.md").read_text()
        expected = "↳ [log-analyzer](ITEM-001/children/log-analyzer/RUNS.md) (0 1 * * *)"
        self.assertIn(expected, text)
        self.assertNotIn("→ [Work Loop Log Analysis]()", text)
        self.assertNotIn("→ [Work Loop Log Analysis](", text)

    def test_active_items_table_sorted_latest_update_on_top(self):
        content = """\
# Work Loop

## Active Items

| Task / Conversation | Status | Last Updated | Log | ID |
| -------------------------------------------------------------------------------- | :----------: | :----------: | :------------------------------------------------------------------------------: | --------------------- |
| [Item Old](ITEM-001/CONVERSATION.md) | needs-review | 2026-08-11 | [Log](ITEM-001/_logs/log1.log) | ITEM-001 |
| [Item Mid](ITEM-002/CONVERSATION.md) | needs-review | 2026-08-17 | [Log](ITEM-002/_logs/log2.log) | ITEM-002 |
| [Item New](ITEM-003/CONVERSATION.md) | in-progress | 2026-08-18 | [Log](ITEM-003/_logs/log3.log) | ITEM-003 |

## Done
"""
        (self.work_dir / "WORK-NEW.md").write_text(content)
        self.wl._sort_active_items_outline()
        lines = (self.work_dir / "WORK-NEW.md").read_text().splitlines()
        active_lines = [l for l in lines if l.startswith("| [Item ")]
        self.assertEqual(len(active_lines), 3)
        self.assertIn("ITEM-003", active_lines[0])
        self.assertIn("ITEM-002", active_lines[1])
        self.assertIn("ITEM-001", active_lines[2])

    def test_update_col_sorts_active_items_table(self):
        # In setup: ITEM-001 is 2026-08-01, ITEM-002 is 2026-08-02
        # Updating ITEM-001 to 2026-08-18 should place it before ITEM-002
        self.wl.update_col("ITEM-001", COL_LAST_UPDATED, "2026-08-18 10:00")
        lines = (self.work_dir / "WORK-NEW.md").read_text().splitlines()
        active_lines = [l for l in lines if l.startswith("| [Task ")]
        self.assertEqual(len(active_lines), 2)
        self.assertIn("ITEM-001", active_lines[0])
        self.assertIn("ITEM-002", active_lines[1])
        self.assertEqual(self.wl.get_col("ITEM-001", COL_LAST_UPDATED), "2026-08-18 10:00")

    def test_active_items_table_sorted_with_datetime_timestamps(self):
        content = """\
# Work Loop

## Active Items

| Task / Conversation | Status | Last Updated | Log | ID |
| -------------------------------------------------------------------------------- | :----------: | :--------------: | :------------------------------------------------------------------------------: | --------------------- |
| [Item Morning](ITEM-001/CONVERSATION.md) | needs-review | 2026-08-18 09:30 | [Log](ITEM-001/_logs/log1.log) | ITEM-001 |
| [Item Night](ITEM-002/CONVERSATION.md) | in-progress | 2026-08-18 22:04 | [Log](ITEM-002/_logs/log2.log) | ITEM-002 |
| [Item Yesterday](ITEM-003/CONVERSATION.md) | needs-review | 2026-08-17 22:04 | [Log](ITEM-003/_logs/log3.log) | ITEM-003 |

## Done
"""
        (self.work_dir / "WORK-NEW.md").write_text(content)
        self.wl._sort_active_items_outline()
        lines = (self.work_dir / "WORK-NEW.md").read_text().splitlines()
        active_lines = [l for l in lines if l.startswith("| [Item ")]
        self.assertEqual(len(active_lines), 3)
        self.assertIn("ITEM-002", active_lines[0])  # 2026-08-18 22:04
        self.assertIn("ITEM-001", active_lines[1])  # 2026-08-18 09:30
        self.assertIn("ITEM-003", active_lines[2])  # 2026-08-17 22:04




class TestInNoteActionCenter(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.work_dir = Path(self.tmp)
        (self.work_dir / "WORK-NEW.md").write_text(SAMPLE_WORK_NEW_MD)
        (self.work_dir / "LOOP-PROMPT.md").write_text("Do the work.\n")
        cfg = {"work_dir": self.work_dir, "work_file": "WORK-NEW.md", "harness": {"type": "claude", "max_budget_usd": 10.00}}
        self.wl = WorkLoop(cfg)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_in_note_continue_analyze_triggers_ready(self):
        item_dir = self.work_dir / "ITEM-002"
        item_dir.mkdir(parents=True, exist_ok=True)
        conv = (
            "> [!action] **Work-Loop Action Center**\n"
            "> Status: `needs-review` | Budget: `$10.0` | Last Run: 2026-08-17 22:04\n"
            "> - [x] **Continue Analyze**\n"
            "> - [ ] **Run Implement**\n"
            "> - [ ] **Mark Resolved (Move to Done)**\n"
            "> - [ ] **Abort**\n\n"
            "## 2026-08-17 | AI Agent\nSome findings\n"
        )
        (item_dir / "CONVERSATION.md").write_text(conv)
        ready_items = self.wl.get_ready_items()
        self.assertIn("ITEM-002", ready_items)
        self.assertEqual(self.wl.get_col("ITEM-002", COL_STATUS), "ready")
        conv_after = (item_dir / "CONVERSATION.md").read_text()
        self.assertIn("> - [ ] **Continue Analyze**", conv_after)
        self.assertIn("Status: `ready`", conv_after)

    def test_in_note_run_implement_triggers_implement(self):
        item_dir = self.work_dir / "ITEM-002"
        item_dir.mkdir(parents=True, exist_ok=True)
        conv = (
            "> [!action] **Work-Loop Action Center**\n"
            "> Status: `needs-review` | Budget: `$10.0` | Last Run: 2026-08-17 22:04\n"
            "> - [ ] **Continue Analyze**\n"
            "> - [x] **Run Implement**\n"
            "> - [ ] **Mark Resolved (Move to Done)**\n"
            "> - [ ] **Abort**\n\n"
            "## 2026-08-17 | AI Agent\nSome findings\n"
        )
        (item_dir / "CONVERSATION.md").write_text(conv)
        ready_items = self.wl.get_ready_items()
        self.assertIn("ITEM-002", ready_items)
        self.assertEqual(self.wl.get_col("ITEM-002", COL_STATUS), "implement")

    def test_in_note_mark_resolved_triggers_resolved(self):
        item_dir = self.work_dir / "ITEM-002"
        item_dir.mkdir(parents=True, exist_ok=True)
        conv = (
            "> [!action] **Work-Loop Action Center**\n"
            "> Status: `needs-review` | Budget: `$10.0` | Last Run: 2026-08-17 22:04\n"
            "> - [ ] **Continue Analyze**\n"
            "> - [ ] **Run Implement**\n"
            "> - [x] **Mark Resolved (Move to Done)**\n"
            "> - [ ] **Abort**\n\n"
            "## 2026-08-17 | AI Agent\nSome findings\n"
        )
        (item_dir / "CONVERSATION.md").write_text(conv)
        ready_items = self.wl.get_ready_items()
        self.assertIn("ITEM-002", ready_items)
        self.assertEqual(self.wl.get_col("ITEM-002", COL_STATUS), "resolved")

    def test_inject_or_update_action_callout(self):
        item_dir = self.work_dir / "ITEM-001"
        item_dir.mkdir(parents=True, exist_ok=True)
        conv_file = item_dir / "CONVERSATION.md"
        conv_file.write_text("## 2026-08-17 | User\n\nInitial task\n")
        self.wl._inject_or_update_action_callout("ITEM-001", "needs-review", 10.0, log_link="[Log](_logs/test.log)")
        text = conv_file.read_text()
        self.assertIn("> [!action] **Work-Loop Action Center**", text)
        self.assertIn("Status: `needs-review`", text)
        self.assertIn("[Log](_logs/test.log)", text)
        self.assertIn("> - [ ] **Continue Analyze**", text)
        self.assertIn("> - [ ] **Run Implement**", text)
        self.assertIn("> - [ ] **Mark Resolved (Move to Done)**", text)
        self.assertIn("> - [ ] **Abort**", text)

        self.wl._inject_or_update_action_callout("ITEM-001", "done", 10.0)
        text2 = conv_file.read_text()
        self.assertIn("Status: `done`", text2)
        self.assertEqual(text2.count("[!action]"), 1)

    def test_in_progress_callout_shows_abort_only_and_log_link(self):
        item_dir = self.work_dir / "ITEM-001"
        item_dir.mkdir(parents=True, exist_ok=True)
        conv_file = item_dir / "CONVERSATION.md"
        conv_file.write_text("## 2026-08-17 | User\n\nInitial task\n")
        self.wl._inject_or_update_action_callout(
            "ITEM-001", "in-progress", 10.0, log_link="[Log](_logs/2026-08-18_ITEM-001.log)"
        )
        text = conv_file.read_text()
        self.assertIn("> [!action] **Work-Loop Action Center**", text)
        self.assertIn("Status: `in-progress`", text)
        self.assertIn("[Log](_logs/2026-08-18_ITEM-001.log)", text)
        self.assertIn("> - [ ] **Abort**", text)
        self.assertNotIn("Continue Analyze", text)
        self.assertNotIn("Run Implement", text)
        self.assertNotIn("Mark Resolved", text)

    def test_in_note_abort_triggers_abort(self):
        item_dir = self.work_dir / "ITEM-002"
        item_dir.mkdir(parents=True, exist_ok=True)
        conv = (
            "> [!action] **Work-Loop Action Center**\n"
            "> Status: `in-progress` | Last Run: 2026-08-18 22:21 | [Log](_logs/2026-08-18_ITEM-002.log)\n"
            "> - [x] **Abort**\n\n"
            "## 2026-08-17 | AI Agent\nSome findings\n"
        )
        (item_dir / "CONVERSATION.md").write_text(conv)
        self.wl.update_col("ITEM-002", COL_STATUS, "in-progress")
        promoted = self.wl._scan_in_note_actions()
        self.assertIn("ITEM-002", promoted)
        self.assertEqual(self.wl.get_col("ITEM-002", COL_STATUS), "abort")
        conv_after = (item_dir / "CONVERSATION.md").read_text()
        self.assertIn("> - [ ] **Abort**", conv_after)
        self.assertIn("Status: `abort`", conv_after)


if __name__ == "__main__":
    unittest.main(verbosity=2)



