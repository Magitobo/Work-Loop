import json
import shutil
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from test_helpers import *

from workloop.config import load_config


class TestLoadConfig(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.path = self.tmp / "config.json"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _load(self, content=None):
        if content is not None:
            self.path.write_text(content if isinstance(content, str) else json.dumps(content))
        with unittest.mock.patch("builtins.print"):
            return load_config(self.path)

    def test_valid_config_loads(self):
        cfg = {"work_dir": "/x", "harness": {"type": "opencode", "model": "m"}}
        self.assertEqual(self._load(cfg), cfg)

    def test_missing_file_exits(self):
        with self.assertRaises(SystemExit):
            self._load()

    def test_invalid_json_exits(self):
        with self.assertRaises(SystemExit):
            self._load("{not json")

    def test_missing_required_keys_exit(self):
        for cfg in ({"harness": {"type": "claude"}}, {"work_dir": "/x"}, {"work_dir": "/x", "harness": {}}):
            with self.subTest(cfg=cfg), self.assertRaises(SystemExit):
                self._load(cfg)

    def test_unknown_harness_type_exits(self):
        with self.assertRaises(SystemExit):
            self._load({"work_dir": "/x", "harness": {"type": "gpt"}})


class TestInitVaultCli(unittest.TestCase):
    """run-loop.py --init-vault resolves vault and work_dir from the target path."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _init(self, target: Path | None):
        argv = ["run-loop.py", "--init-vault"] + ([str(target)] if target else [])
        with unittest.mock.patch.object(sys, "argv", argv), \
             unittest.mock.patch("workloop.scaffold.scaffold_vault", return_value={"created": [], "updated": []}) as sv, \
             unittest.mock.patch.object(run_loop, "WorkLoop") as wl, \
             unittest.mock.patch("builtins.print"):
            run_loop.main()
        wl.assert_not_called()  # --init-vault must not start the loop
        return sv.call_args

    def test_obsidian_vault(self):
        vault = self.tmp / "Vault"
        (vault / ".obsidian").mkdir(parents=True)
        call = self._init(vault)
        self.assertEqual(call[0][0], vault / "02-Work-Loop-Items")
        self.assertEqual(call[1]["vault_dir"], vault)

    def test_items_dir(self):
        items = self.tmp / "Vault" / "Work-Loop-Items"
        items.mkdir(parents=True)
        call = self._init(items)
        self.assertEqual(call[0][0], items)
        self.assertEqual(call[1]["vault_dir"], items.parent)

    def test_plain_dir_treated_as_vault(self):
        call = self._init(self.tmp)
        self.assertEqual(call[0][0], self.tmp / "02-Work-Loop-Items")
        self.assertEqual(call[1]["vault_dir"], self.tmp)

    def test_missing_path_exits(self):
        with self.assertRaises(SystemExit):
            self._init(None)


if __name__ == "__main__":
    unittest.main()
