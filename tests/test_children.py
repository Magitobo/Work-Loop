import os
import shutil
import tempfile
import unittest
import unittest.mock
from datetime import datetime
from pathlib import Path
import json
import re
import sys
import subprocess

from test_helpers import *

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

    def test_work_md_last_updated_when_child_runs(self):
        """process_child updates parent's Last Updated in top-level WORK.md."""
        with tempfile.TemporaryDirectory() as tmp:
            wl = self._make_wl_with_child(tmp)
            today = datetime.now().strftime('%Y-%m-%d')
            self.assertEqual(wl.get_col("PARENT-001", COL_LAST_UPDATED), "")
            with unittest.mock.patch.object(WorkLoop, "_run_harness", return_value=0):
                wl.process_child("PARENT-001", "areas")
            self.assertEqual(wl.get_col("PARENT-001", COL_LAST_UPDATED), today)
            self.assertEqual(wl.get_col("PARENT-001", COL_STATUS), "ready")

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

    def test_resets_stale_running_child_to_scheduled(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = _make_parent_with_children(tmp, "PARENT-001", [
                {"name": "areas", "status": "running", "runs_md": _CHILD_RUNS_MD}
            ])
            # Parent is "ready" (not done), no live harness — stale, has schedule
            wl.resume_running_children()
            wc_path = Path(tmp) / "PARENT-001" / "WORK-CHILDREN.md"
            status = wl._get_child_status(wc_path, "areas")
            self.assertEqual(status, "scheduled")

    def test_resets_stale_running_child_to_ready_without_schedule(self):
        with tempfile.TemporaryDirectory() as tmp:
            runs_md_no_schedule = _CHILD_RUNS_MD.replace("schedule: 0 */6 * * *\n", "")
            wl = _make_parent_with_children(tmp, "PARENT-001", [
                {"name": "areas", "status": "running", "runs_md": runs_md_no_schedule}
            ])
            wl.resume_running_children()
            wc_path = Path(tmp) / "PARENT-001" / "WORK-CHILDREN.md"
            status = wl._get_child_status(wc_path, "areas")
            self.assertEqual(status, "ready")

    def test_keeps_running_child_when_harness_alive(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = _make_parent_with_children(tmp, "PARENT-001", [
                {"name": "areas", "status": "running", "runs_md": _CHILD_RUNS_MD}
            ])
            wl._harness_process_alive = lambda parent_id, child_name: True
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
            self.assertIn("[20260105-002 run](runs/20260105-002/research.md)", text)
            self.assertIn("done", text)

    def test_appends_task_child_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            wl = _make_parent_with_children(tmp, "PARENT-001", [
                {"name": "inbox", "status": "ready", "runs_md": _CHILD_TASK_RUNS_MD}
            ])
            runs_path = Path(tmp) / "PARENT-001" / "children" / "inbox" / "RUNS.md"
            run_dir = runs_path.parent / "runs" / "20260820-001"
            run_dir.mkdir(parents=True)
            (run_dir / "task.md").write_text("## Proposed 3 moves\n")
            log_link = "[Log](../../_logs/2026-08-20_01-00-00_PARENT-001_inbox.log)"
            wl._append_research_run(
                "inbox",
                "20260820-001",
                "Inbox cleanup",
                status="done",
                runs_path=runs_path,
                summary_file="task.md",
                log_link=log_link,
            )
            text = runs_path.read_text()
            self.assertIn("[Inbox cleanup](runs/20260820-001/task.md)", text)
            self.assertIn(log_link, text)


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

