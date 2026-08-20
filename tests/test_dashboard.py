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

