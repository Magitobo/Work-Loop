#!/usr/bin/env python3
"""Tests for run-loop.py — unit tests and optional remote integration test."""

import importlib.util
import os
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


def _remote_has_kerberos(host: str) -> bool:
    """Return True if the remote machine has a valid Kerberos ticket."""
    try:
        result = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes", host, "klist -s"],
            capture_output=True, timeout=10,
        )
        return result.returncode == 0
    except Exception:
        return False


REMOTE_AVAILABLE = _can_reach_remote(REMOTE_HOST) and _remote_has_kerberos(REMOTE_HOST)

# ---------------------------------------------------------------------------
# Sample WORK.md fixture
# ---------------------------------------------------------------------------

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
    return WorkLoop(p, max_budget=10.00)


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
        self.assertIn(f".logs/{ts}_ITEM-001.log", script)

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
        self.assertIn("$RWD/.logs/", self._script())

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
        content = (
            "# Work Loop\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
            f"| MY-ITEM | Task | user@host | {mode} |  |  |  |\n\n"
            "## Done\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
        )
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

        with patch.object(run_loop, '_run', side_effect=fake_run), \
             patch.object(run_loop, 'subprocess') as mock_sub:
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
                 patch.object(run_loop, '_run', return_value=MagicMock(returncode=0)), \
                 patch.object(run_loop, 'subprocess') as mock_sub:
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
                 patch.object(run_loop, '_run', return_value=MagicMock(returncode=0)), \
                 patch.object(run_loop, 'subprocess') as mock_sub:
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
        content = (
            "# Work Loop\n\n"
            "| ID      | Title | Location    | Status | Last Updated | Budget | Log |\n"
            "| ------- | ----- | ----------- | ------ | ------------ | ------ | --- |\n"
            f"| MY-ITEM | Task  | user@remote | {status} |  |  |  |\n\n"
            "## Done\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
        )
        return _make_workloop(tempfile.mkdtemp(), content)

    def _dispatched_mode(self, wl: WorkLoop) -> str | None:
        from unittest.mock import patch
        captured = {}

        def fake_dispatch(item_id, ts_str, remote_host, budget, mode="analyze"):
            captured["mode"] = mode

        with patch.object(WorkLoop, "_remote_has_kerberos", return_value=True), \
             patch.object(WorkLoop, "dispatch_remote", side_effect=fake_dispatch), \
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

        self.wl.prepend_abort_notice("ITEM-001", "2026-05-14", budget=self.wl.max_budget, cause="Kerberos auth expired")

        text = conv.read_text()
        self.assertIn("Kerberos auth expired", text)
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
        content = (
            "# Work Loop\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
            f"{rows}\n\n"
            "## Done\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
        )
        return _make_workloop(tempfile.mkdtemp(), content)

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
        content = (
            "# Work Loop\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
            "| MY-ITEM | Kick off the thing | local | ready |  |  |  |\n\n"
            "## Done\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
        )
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
            content = (
                "# Work Loop\n\n"
                "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
                "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
                "| MY-ITEM | [Linked title](MY-ITEM/CONVERSATION.md) | local | ready |  |  |  |\n\n"
                "## Done\n\n"
                "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
                "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
            )
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

    WORK_MD = (
        "# Work Loop\n\n"
        "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
        "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
        "| MY-ITEM | Original long prompt text | remote-host | in-progress |  |  |  |\n\n"
        "## Done\n\n"
        "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
        "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
    )

    REMOTE_WORK_MD = (
        "# Work Loop\n\n"
        "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
        "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
        "| MY-ITEM | [Concise title](MY-ITEM/CONVERSATION.md) | local | needs-review |  |  |  |\n\n"
        "## Done\n\n"
        "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
        "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
    )

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

        with patch.object(run_loop, 'subprocess') as mock_sub, \
             patch.object(run_loop, '_run') as mock_rrun:
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
        content = (
            "# Work Loop\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
            f"{row_lines}\n\n"
            "## Done\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
        )
        return _make_workloop(tempfile.mkdtemp(), content)

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
        content = (
            "# Work Loop\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
            "| ITEM-A | [A](A/C.md) | local | ready |  |  |  |\n\n"
            "## Done\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
            "| ITEM-B | [B](B/C.md) | user@host | in-progress |  |  |  |\n"
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
        content = (
            "# Work Loop\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
            f"| {item_id} | [{item_id}]({item_id}/C.md) | user@host | in-progress |  | $10.0 | {log_col} |\n\n"
            "## Done\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
        )
        return _make_workloop(tempfile.mkdtemp(), content)

    def test_extracts_from_log_col(self):
        log_col = f"[Log](.logs/{self.TS}_MY-ITEM.log)"
        wl = self._make_wl("MY-ITEM", log_col)
        self.assertEqual(wl._ts_str_from_log_col("MY-ITEM", "user@host"), self.TS)

    def test_returns_none_when_no_log_and_remote_empty(self):
        from unittest.mock import patch, MagicMock
        wl = self._make_wl("MY-ITEM", "")
        with patch.object(run_loop, 'subprocess') as mock_sub:
            r = MagicMock()
            r.stdout = ""
            mock_sub.run.return_value = r
            self.assertIsNone(wl._ts_str_from_log_col("MY-ITEM", "user@host"))

    def test_falls_back_to_remote_glob(self):
        from unittest.mock import patch, MagicMock
        wl = self._make_wl("MY-ITEM", "")
        with patch.object(run_loop, 'subprocess') as mock_sub:
            r = MagicMock()
            r.stdout = f"/home/user/Work-Loop/.logs/{self.TS}_MY-ITEM.log\n"
            mock_sub.run.return_value = r
            self.assertEqual(wl._ts_str_from_log_col("MY-ITEM", "user@host"), self.TS)

    def test_remote_fallback_uses_connect_timeout(self):
        from unittest.mock import patch, MagicMock
        wl = self._make_wl("MY-ITEM", "")
        with patch.object(run_loop, 'subprocess') as mock_sub:
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
        log_dir = Path(tmp) / ".logs"
        log_dir.mkdir(exist_ok=True)
        (log_dir / f"{self.TS}_MY-ITEM.log").write_text(log_content)
        return wl

    def test_detects_auth_from_apikeyhelper(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl_with_log(tmp,
                "apiKeyHelper failed: exited 1: ...\n"
                "Error: No valid Kerberos ticket found.\n"
                "Run: kinit your-username@ENT.TI.COM\n"
                "Failed to authenticate. API Error: 401 Authentication Error\n"
            )
            self.assertEqual(wl._classify_failure("MY-ITEM", self.TS), "auth")

    def test_detects_auth_from_failed_to_authenticate(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl_with_log(tmp, "Failed to authenticate.\n")
            self.assertEqual(wl._classify_failure("MY-ITEM", self.TS), "auth")

    def test_detects_auth_from_no_valid_kerberos(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl_with_log(tmp, "Error: No valid Kerberos ticket found.\n")
            self.assertEqual(wl._classify_failure("MY-ITEM", self.TS), "auth")

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
# TestKerberosExpiredBlocks
# ---------------------------------------------------------------------------

class TestKerberosExpiredBlocks(unittest.TestCase):
    """When Kerberos check fails, item is set to blocked and loop skips it."""

    WORK_MD = (
        "# Work Loop\n\n"
        "| ID      | Title | Location                | Status | Last Updated | Budget | Log |\n"
        "| ------- | ----- | ----------------------- | ------ | ------------ | ------ | --- |\n"
        "| MY-ITEM | Task  | xgemuadm@some-remote-01 | ready  |              |        |     |\n\n"
        "## Done\n\n"
        "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
        "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
    )

    def _run_loop_with_kerberos_mock(self, tmp: str, kerberos_ok: bool) -> WorkLoop:
        from unittest.mock import patch, MagicMock
        wl = _make_workloop(tmp, self.WORK_MD)
        with patch.object(WorkLoop, "_remote_has_kerberos", return_value=kerberos_ok), \
             patch.object(WorkLoop, "dispatch_remote"), \
             patch.object(WorkLoop, "wait_for_remote"):
            wl.run(once=True)
        return wl

    def test_kerberos_expired_sets_status_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._run_loop_with_kerberos_mock(tmp, kerberos_ok=False)
            self.assertEqual(wl.get_col("MY-ITEM", COL_STATUS), "blocked")

    def test_kerberos_expired_does_not_dispatch(self):
        from unittest.mock import patch, MagicMock
        with tempfile.TemporaryDirectory() as tmp:
            wl = _make_workloop(tmp, self.WORK_MD)
            with patch.object(WorkLoop, "_remote_has_kerberos", return_value=False), \
                 patch.object(WorkLoop, "dispatch_remote") as mock_dispatch, \
                 patch.object(WorkLoop, "wait_for_remote"):
                wl.run(once=True)
            mock_dispatch.assert_not_called()

    def test_kerberos_valid_dispatches(self):
        from unittest.mock import patch, MagicMock
        with tempfile.TemporaryDirectory() as tmp:
            wl = _make_workloop(tmp, self.WORK_MD)
            with patch.object(WorkLoop, "_remote_has_kerberos", return_value=True), \
                 patch.object(WorkLoop, "dispatch_remote") as mock_dispatch, \
                 patch.object(WorkLoop, "wait_for_remote"):
                wl.run(once=True)
            mock_dispatch.assert_called_once()


# ---------------------------------------------------------------------------
# TestSyncBackRemote
# ---------------------------------------------------------------------------

class TestSyncBackRemote(unittest.TestCase):

    TS = "2026-06-04_10-00-00"
    WORK_MD = (
        "# Work Loop\n\n"
        "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
        "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
        "| MY-ITEM | Original title | user@host | in-progress |  | $10.0 |"
        " [Log](.logs/2026-06-04_10-00-00_MY-ITEM.log) |\n\n"
        "## Done\n\n"
        "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
        "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
    )

    def _make_wl(self, tmp: str, log_content: str | None = None) -> WorkLoop:
        wl = _make_workloop(tmp, self.WORK_MD)
        item_dir = Path(tmp) / "MY-ITEM"
        item_dir.mkdir()
        (item_dir / "CONVERSATION.md").write_text("## 2026-01-01 | Claude\n\nFindings\n")
        log_dir = Path(tmp) / ".logs"
        log_dir.mkdir(exist_ok=True)
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

        with patch.object(run_loop, 'subprocess') as mock_sub, \
             patch.object(run_loop, '_run') as mock_rrun:
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

    def test_budget_exceeded_on_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl(tmp)
            self._run_sync(wl, "1")
            self.assertIn("EXCEEDED", wl.get_col("MY-ITEM", COL_BUDGET))

    def test_budget_auth_expired_on_auth_failure(self):
        auth_log = (
            "apiKeyHelper failed: exited 1: Warning: ...\n"
            "Error: No valid Kerberos ticket found.\n"
            "Failed to authenticate. API Error: 401 Authentication Error\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl(tmp, log_content=auth_log)
            self._run_sync(wl, "1")
            self.assertIn("AUTH-EXPIRED", wl.get_col("MY-ITEM", COL_BUDGET))
            self.assertNotIn("EXCEEDED", wl.get_col("MY-ITEM", COL_BUDGET))

    def test_abort_notice_has_auth_cause(self):
        auth_log = "apiKeyHelper failed: exited 1: ...\nFailed to authenticate.\n"
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl(tmp, log_content=auth_log)
            self._run_sync(wl, "1")
            text = (Path(tmp) / "MY-ITEM" / "CONVERSATION.md").read_text()
            self.assertIn("Kerberos auth expired", text)

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

    def test_remote_title_captured(self):
        remote_wmd = (
            "# Work Loop\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
            "| MY-ITEM | [Concise title](MY-ITEM/CONVERSATION.md) | local | needs-review |  |  |  |\n\n"
            "## Done\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
        )
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
            log_col = f"[Log](.logs/{self.TS}_MY-ITEM.log)"
        content = (
            "# Work Loop\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
            f"| MY-ITEM | [Task](MY-ITEM/C.md) | user@host | in-progress |  | $10.0 | {log_col} |\n\n"
            "## Done\n\n"
            "| ID | Title | Location | Status | Last Updated | Budget | Log |\n"
            "| -- | ----- | -------- | ------ | ------------ | ------ | --- |\n"
        )
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

        with patch.object(run_loop, 'subprocess') as mock_sub, \
             patch.object(run_loop, '_run') as mock_rrun:
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
            with patch.object(run_loop, 'subprocess') as mock_sub, \
                 patch.object(run_loop, '_run'):
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
            with patch.object(run_loop, 'subprocess') as mock_sub:
                wl.check_stalled_remotes()
                mock_sub.run.assert_not_called()
            self.assertEqual(wl.get_col("MY-ITEM", COL_STATUS), "in-progress")


class TestLoopPromptPortability(unittest.TestCase):
    """LOOP-PROMPT.md must work when deployed to remote hosts with different layouts."""

    LOOP_PROMPT = _HERE / "LOOP-PROMPT.md"

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
             f" {rwd}/.logs/*_{self.ITEM_ID}.log"],
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
        log_dir = REAL_WORK_DIR / ".logs"
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

        with patch.object(WorkLoop, "_remote_has_kerberos", return_value=True), \
             patch.object(WorkLoop, "dispatch_remote", side_effect=fake_dispatch), \
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
        self.assertIn('$RWD/.logs/', script)

    def test_analyze_debug_file_path_contains_ts_and_item(self):
        script = self.wl.build_launcher("ITEM-001", self.TS, budget=10.0, mode="analyze")
        self.assertIn(f".logs/{self.TS}_ITEM-001.debug", script)

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

        with patch.object(run_loop, '_run', side_effect=fake_run), \
             patch.object(run_loop, 'subprocess') as mock_sub:
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
        (Path(tmp) / ".logs").mkdir(exist_ok=True)
        item_dir = Path(tmp) / "MY-ITEM"
        item_dir.mkdir()
        (item_dir / "CONVERSATION.md").write_text("## 2026-01-01 | User\n\nDo it.\n")
        return wl

    def test_success_moves_to_done(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl(tmp)
            with patch.object(WorkLoop, "run_claude", return_value=0):
                wl.process_local("MY-ITEM", 10.0)
            text = (Path(tmp) / "WORK.md").read_text()
            done_idx = text.index("## Done")
            self.assertIn("MY-ITEM", text[done_idx:])
            self.assertNotIn("MY-ITEM", text[:done_idx])

    def test_failure_sets_needs_review(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl(tmp)
            with patch.object(WorkLoop, "run_claude", return_value=1):
                wl.process_local("MY-ITEM", 10.0)
            self.assertEqual(wl.get_col("MY-ITEM", COL_STATUS), "needs-review")

    def test_failure_does_not_move_to_done(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl(tmp)
            with patch.object(WorkLoop, "run_claude", return_value=1):
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
        log_col = f"[Log](.logs/{self.TS}_MY-ITEM.debug)"
        wl = self._make_wl(log_col)
        self.assertEqual(wl._ts_str_from_log_col("MY-ITEM", "user@host"), self.TS)

    def test_extracts_ts_from_log_extension(self):
        log_col = f"[Log](.logs/{self.TS}_MY-ITEM.log)"
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
    return WorkLoop(p, max_budget=10.00)


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
        cfg = wl._parse_runs_md_config("SI-001")
        self.assertEqual(cfg["command"], "bash test_fixtures/stub_test.sh")
        self.assertEqual(cfg["params"], "--arg1")
        self.assertEqual(cfg["location"], "linux:user@host1")
        self.assertEqual(cfg["heartbeat_file"], "run.log")
        self.assertEqual(cfg["timeout"], 4)
        self.assertEqual(cfg["aggregation_script"], "test_fixtures/stub_aggregate.py")
        self.assertIn("{run-id}", cfg["analysis_prompt"])

    def test_multi_location_parsed(self):
        wl = _make_script_item(self.tmp, "SI-001", _MULTI_LOC_RUNS_MD)
        cfg = wl._parse_runs_md_config("SI-001")
        self.assertEqual(cfg["locations"], ["linux:user@host1", "linux:user@host2", "win:user@winhost"])
        self.assertEqual(cfg["location"], "")

    def test_schedule_parsed(self):
        wl = _make_script_item(self.tmp, "SI-001", _SCHEDULED_RUNS_MD)
        cfg = wl._parse_runs_md_config("SI-001")
        self.assertEqual(cfg["schedule"], "30 9 * * 1-5")

    def test_missing_runs_md_returns_defaults(self):
        wl = _make_workloop(self.tmp)
        cfg = wl._parse_runs_md_config("NONEXISTENT")
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
        wl2 = WorkLoop(p, max_budget=10.0)
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
        (Path(tmp) / ".logs").mkdir(exist_ok=True)
        item_dir = Path(tmp) / "MY-ITEM"
        item_dir.mkdir()
        (item_dir / "CONVERSATION.md").write_text("## 2026-01-01 | User\n\nDo it.\n")
        return wl

    def test_abort_status_leaves_abort_after_process_local(self):
        """Status stays 'abort' when watcher kills Claude mid-run."""
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl(tmp)

            def run_claude_aborts(*args, **kwargs):
                wl.update_col("MY-ITEM", COL_STATUS, "abort")
                return 1

            with patch.object(WorkLoop, "run_claude", side_effect=run_claude_aborts):
                wl.process_local("MY-ITEM", 10.0)

            self.assertEqual(wl.get_col("MY-ITEM", COL_STATUS), "abort")

    def test_abort_status_does_not_set_needs_review(self):
        """Aborted items must not land on needs-review."""
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl(tmp)

            def run_claude_aborts(*args, **kwargs):
                wl.update_col("MY-ITEM", COL_STATUS, "abort")
                return 1

            with patch.object(WorkLoop, "run_claude", side_effect=run_claude_aborts):
                wl.process_local("MY-ITEM", 10.0)

            self.assertNotEqual(wl.get_col("MY-ITEM", COL_STATUS), "needs-review")

    def test_abort_prepends_notice(self):
        """process_local writes an abort notice to CONVERSATION.md."""
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl(tmp)

            def run_claude_aborts(*args, **kwargs):
                wl.update_col("MY-ITEM", COL_STATUS, "abort")
                return 1

            with patch.object(WorkLoop, "run_claude", side_effect=run_claude_aborts):
                wl.process_local("MY-ITEM", 10.0)

            text = (Path(tmp) / "MY-ITEM" / "CONVERSATION.md").read_text()
            self.assertIn("Run aborted", text)
            self.assertIn("aborted by user", text)

    def test_nonzero_exit_without_abort_still_sets_needs_review(self):
        """Regression: a non-abort failure still lands on needs-review."""
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl(tmp)
            with patch.object(WorkLoop, "run_claude", return_value=1):
                wl.process_local("MY-ITEM", 10.0)
            self.assertEqual(wl.get_col("MY-ITEM", COL_STATUS), "needs-review")

    def test_watcher_terminates_process_on_abort(self):
        """run_claude's abort watcher calls proc.terminate() when status is 'abort'."""
        from unittest.mock import patch, MagicMock

        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl(tmp)
            # Fast poll interval so the watcher fires without a 3-second wait.
            wl._abort_poll_interval = 0.01
            log_file = Path(tmp) / ".logs" / "test.log"

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
                wl.run_claude("prompt text", log_file, 10.0, item_id="MY-ITEM")

            proc_mock.terminate.assert_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
