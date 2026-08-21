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
        self.assertIn("runs/20260717-001/research.md", text)

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

