from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from poplink.cli import CaptureScope, PoplinkError, _backend, _capture_rex, _parser, main


class RexTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.source = self.base / "source with spaces"
        self.source.mkdir()
        for name in ("old.py", "recent.py", "visible.py"):
            (self.source / name).write_text("fixture\n")
        self.log = self.base / "calls.jsonl"
        # Exercise the real CLI boundary, including argument quoting and source
        # identity. The picker block deliberately differs from the source block.
        rex = self.base / "rex"
        rex.write_text(
            f"#!{sys.executable}\n"
            "import json, os, sys\n"
            "args = sys.argv[1:]\n"
            "with open(os.environ['TEST_REX_LOG'], 'a') as f:\n"
            " f.write(json.dumps(args) + '\\n')\n"
            "if os.environ.get('TEST_REX_FAIL'):\n"
            " print('source block no longer exists', file=sys.stderr); sys.exit(1)\n"
            "if 'capture' in args:\n"
            " assert args[args.index('--block')+1] == 'block:source'\n"
            " print('old.py\\nrecent.py\\nvisible.py')\n"
            "elif 'com.superlogical.terminal.process' in args:\n"
            " assert json.loads(args[-1])['block_id'] == 'block:source'\n"
            " print(json.dumps({'foreground': {'cwd': os.environ['TEST_REX_CWD']}}))\n"
            "elif 'com.superlogical.terminal.size' in args:\n"
            " assert json.loads(args[-1])['block_id'] == 'block:source'\n"
            " print(json.dumps({'rows': 1}))\n"
            "else:\n"
            " sys.exit(2)\n"
        )
        rex.chmod(0o755)
        self.env = patch.dict(os.environ, {
            "PATH": str(self.base),
            "REX_SESSION": "session:test",
            "REX_BLOCK": "block:picker",
            "REX_SERVER": "/tmp/rex test.sock",
            "TEST_REX_LOG": str(self.log),
            "TEST_REX_CWD": str(self.source),
        }, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def candidates(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = main([
                "--block", "block:source", "--json", "--config",
                str(self.base / "missing.ini"), *args,
            ])
        self.assertEqual(status, 0)
        return json.loads(output.getvalue())

    def test_source_block_and_directory_survive_popup_focus_change(self):
        candidates = self.candidates()
        self.assertEqual([c["display"] for c in candidates], ["old.py", "recent.py", "visible.py"])
        self.assertEqual(candidates[-1]["path"], str((self.source / "visible.py").resolve()))
        calls = [json.loads(line) for line in self.log.read_text().splitlines()]
        self.assertTrue(all(call[:3] == ["--autostart=false", "--server", "/tmp/rex test.sock"] for call in calls))
        self.assertTrue(all(call[call.index("--session") + 1] == "session:test" for call in calls))

    def test_recent_lines_exclude_old_references(self):
        self.assertEqual([c["display"] for c in self.candidates("--lines", "2")], ["recent.py", "visible.py"])

    def test_history_keeps_all_references(self):
        self.assertEqual(len(self.candidates("--history")), 3)

    def test_visible_is_rejected_instead_of_including_offscreen_history(self):
        with self.assertRaisesRegex(PoplinkError, "screen-only capture"):
            _capture_rex(_parser().parse_args(["--block", "block:source"]), CaptureScope("visible"))
        self.assertFalse(self.log.exists())

    def test_nested_tmux_takes_priority_unless_rex_explicit(self):
        os.environ["TMUX"] = "nested"
        self.assertEqual(_backend(_parser().parse_args([])), "tmux")
        self.assertEqual(_backend(_parser().parse_args(["--backend", "rex"])), "rex")
        self.assertEqual(_backend(_parser().parse_args(["--block", "block:source"])), "rex")

    def test_plain_rex_is_detected_without_flags(self):
        self.assertEqual(_backend(_parser().parse_args([])), "rex")

    def test_explicit_tmux_pane_selects_tmux(self):
        self.assertEqual(_backend(_parser().parse_args(["--pane", "%3"])), "tmux")

    def test_conflicting_targets_are_rejected(self):
        for argv in (["--pane", "%3", "--block", "block:x"], ["--backend", "rex", "--pane", "%3"]):
            with self.subTest(argv=argv), self.assertRaises(PoplinkError):
                _backend(_parser().parse_args(argv))

    def test_capture_failure_is_reported_without_starting_a_server(self):
        os.environ["TEST_REX_FAIL"] = "1"
        error = io.StringIO()
        with contextlib.redirect_stderr(error):
            status = main(["--block", "block:source", "--json"])
        self.assertEqual(status, 1)
        self.assertIn("source block no longer exists", error.getvalue())

    def test_missing_session_is_rejected_before_capture(self):
        del os.environ["REX_SESSION"]
        with self.assertRaisesRegex(PoplinkError, "session and source block"):
            _capture_rex(_parser().parse_args(["--block", "block:source"]), CaptureScope("history"))
        self.assertFalse(self.log.exists())


if __name__ == "__main__":
    unittest.main()
