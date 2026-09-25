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



class TestGetInprogressRemoteItemsOutline(unittest.TestCase):
    """Regression: remote recovery must work with outline-format WORK.md."""

    CONTENT = """\
# Work Loop

## Active Items

- [ ] [Remote task](ITEM-A/CONVERSATION.md) · `status: in-progress` · `location: user@host1` · `ITEM-A`
- [ ] [Local task](ITEM-B/CONVERSATION.md) · `status: in-progress` · `ITEM-B`
- [ ] [Remote ready](ITEM-C/CONVERSATION.md) · `status: ready` · `location: user@host2` · `ITEM-C`

## Done

- [x] [Old](ITEM-D/CONVERSATION.md) · `status: in-progress` · `location: user@host3` · `ITEM-D`
"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.wl = _make_workloop(self.tmp, self.CONTENT)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_returns_only_active_in_progress_remote_items(self):
        self.assertEqual(self.wl.get_inprogress_remote_items(), [("ITEM-A", "user@host1")])

    def test_streamlined_table_has_no_remote_items(self):
        wl = _make_workloop(self.tmp, SAMPLE_STREAMLINED_WORK_MD.replace("| ready |", "| in-progress |"))
        self.assertEqual(wl.get_inprogress_remote_items(), [])
