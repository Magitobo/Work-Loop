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

from test_helpers import *

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



class TestRunLoopRouting(unittest.TestCase):
    """run(once=True) must route each item type to the right processor."""

    _EVERY_MINUTE_SCRIPT = (
        "## Config\n\nCommand: echo\nSchedule: * * * * *\nLocation: linux:user@host1\n"
    )

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _wl(self, rows: str, runs_md: dict[str, str] | None = None) -> WorkLoop:
        wl = _make_workloop(self.tmp, make_work_md(rows))
        for item_id, text in (runs_md or {}).items():
            d = Path(self.tmp) / item_id
            d.mkdir(parents=True, exist_ok=True)
            (d / "RUNS.md").write_text(text)
        return wl

    def _run_once(self, wl: WorkLoop):
        from unittest.mock import patch
        mocks = {}
        with patch.object(WorkLoop, "process_local") as mocks["process_local"], \
             patch.object(WorkLoop, "process_script_item") as mocks["process_script_item"], \
             patch.object(WorkLoop, "dispatch_remote") as mocks["dispatch_remote"], \
             patch.object(WorkLoop, "wait_for_remote") as mocks["wait_for_remote"], \
             patch.object(WorkLoop, "process_child") as mocks["process_child"]:
            wl.run(once=True)
        return mocks

    def test_research_item_runs_locally(self):
        wl = self._wl("| RES-1 | R | local | ready |  |  |  |", {"RES-1": _RESEARCH_RUNS_MD})
        m = self._run_once(wl)
        m["process_local"].assert_called_once()
        self.assertEqual(m["process_local"].call_args[0][0], "RES-1")
        m["process_script_item"].assert_not_called()

    def test_script_item_routes_to_script_processor(self):
        wl = self._wl("| SI-1 | S | local | ready |  |  |  |", {"SI-1": _SINGLE_LOC_RUNS_MD})
        m = self._run_once(wl)
        m["process_script_item"].assert_called_once_with("SI-1")
        m["process_local"].assert_not_called()

    def test_remote_conversation_sets_in_progress_and_log(self):
        wl = self._wl("| C-1 | C | user@host | ready |  |  |  |")
        m = self._run_once(wl)
        m["dispatch_remote"].assert_called_once()
        m["wait_for_remote"].assert_called_once()
        self.assertEqual(wl.get_col("C-1", COL_STATUS), "in-progress")
        self.assertIn("C-1/_logs/", wl.get_col("C-1", COL_LOG))

    def test_local_conversation_runs_locally(self):
        wl = self._wl("| C-1 | C | local | analyze |  |  |  |")
        m = self._run_once(wl)
        m["process_local"].assert_called_once()
        m["dispatch_remote"].assert_not_called()

    def test_scheduled_script_promoted_and_processed(self):
        wl = self._wl("| SI-1 | S | local | scheduled |  |  |  |", {"SI-1": self._EVERY_MINUTE_SCRIPT})
        m = self._run_once(wl)
        self.assertEqual(wl.get_col("SI-1", COL_STATUS), "ready")
        m["process_script_item"].assert_called_once_with("SI-1")

    def test_ready_child_processed(self):
        wl = _make_parent_with_children(self.tmp, "PARENT-001", [
            {"name": "walk", "runs_md": _CHILD_RUNS_MD, "status": "ready"},
            {"name": "idle", "runs_md": _CHILD_RUNS_MD, "status": "needs-review"},
        ])
        m = self._run_once(wl)
        m["process_child"].assert_called_once_with("PARENT-001", "walk")

    def test_idle_when_nothing_ready(self):
        from unittest.mock import patch
        wl = self._wl("| C-1 | C | local | needs-review |  |  |  |")

        def stop(_secs):
            wl._stop = True

        with patch("workloop.core.time.sleep", side_effect=stop) as sleep, \
             patch.object(WorkLoop, "process_local") as local, \
             patch("builtins.print"):
            wl.run(once=True)
        sleep.assert_called_once_with(5)
        local.assert_not_called()
