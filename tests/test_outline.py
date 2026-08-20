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

