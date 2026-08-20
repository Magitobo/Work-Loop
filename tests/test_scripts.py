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

