from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from poplink.candidates import Candidate
from poplink.cli import _open_candidate


class EditorHistoryTests(unittest.TestCase):
    def test_neovim_popup_isolates_history_and_preserves_file_location(self):
        candidate = Candidate("path", Path("/tmp/example.py"), None, 42, 8, "example.py:42:8", "example.py:42:8")
        with patch("poplink.cli.shutil.which", return_value="/bin/nvim"), patch(
            "poplink.cli.subprocess.run", return_value=subprocess.CompletedProcess([], 0)
        ) as run:
            self.assertEqual(_open_candidate(candidate, "nvim"), 0)
        run.assert_called_once_with(["nvim", "-i", "NONE", "+call cursor(42, 8)", "/tmp/example.py"])

    def test_explicit_neovim_history_file_is_respected(self):
        candidate = Candidate("path", Path("/tmp/example.py"), None, None, None, "example.py", "example.py")
        for editor, arguments in (
            ("nvim -i '/tmp/my history'", ["nvim", "-i", "/tmp/my history"]),
            ("nvim -i/tmp/history", ["nvim", "-i/tmp/history"]),
            ("vim", ["vim"]),
        ):
            with self.subTest(editor=editor), patch("poplink.cli.shutil.which", return_value="/bin/editor"), patch(
                "poplink.cli.subprocess.run", return_value=subprocess.CompletedProcess([], 0)
            ) as run:
                _open_candidate(candidate, editor)
                run.assert_called_once_with(arguments + ["/tmp/example.py"])


if __name__ == "__main__":
    unittest.main()
