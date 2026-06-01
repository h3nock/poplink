from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from poplink.candidates import extract_candidates
from poplink.cli import _capture_command, _preview_window


class CandidateExtractionTests(unittest.TestCase):
    def test_extracts_supported_local_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "src").mkdir()
            (base / "src" / "App.tsx").write_text("app")
            (base / "README.md").write_text("readme")
            (base / "app").mkdir()
            (base / "app" / "main.py").write_text("python")
            absolute = base / "absolute.md"
            absolute.write_text("absolute")
            spaced_dir = base / "My Project"
            spaced_dir.mkdir()
            (spaced_dir / "file.md").write_text("space")

            text = f"""
            Open {absolute}
            Failure at src/App.tsx:42:8
            [README](README.md)
            "{spaced_dir / "file.md"}"
            File "app/main.py", line 20, in run
            """

            candidates = extract_candidates(text, base)
            displays = [candidate.display for candidate in candidates]

            self.assertIn("absolute.md", displays)
            self.assertIn("src/App.tsx:42:8", displays)
            self.assertIn("README.md", displays)
            self.assertIn("My Project/file.md", displays)
            self.assertIn("app/main.py:20", displays)

    def test_filters_missing_paths_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)

            candidates = extract_candidates("missing/file.py:10", base)

            self.assertEqual(candidates, [])

    def test_filters_directories_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "src").mkdir()
            (base / "src" / "App.tsx").write_text("app")

            candidates = extract_candidates("Open src and src/App.tsx", base)
            displays = [candidate.display for candidate in candidates]

            self.assertNotIn("src", displays)
            self.assertIn("src/App.tsx", displays)

    def test_can_include_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "src").mkdir()

            candidates = extract_candidates("Open ./src", base, include_dirs=True)

            self.assertEqual(candidates[0].display, "src")

    def test_can_include_missing_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)

            candidates = extract_candidates("missing/file.py:10", base, include_missing=True)

            self.assertEqual(candidates[0].display, "missing/file.py:10")

    def test_urls_are_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)

            without_urls = extract_candidates("https://example.com/docs", base)
            with_urls = extract_candidates("https://example.com/docs", base, include_urls=True)

            self.assertEqual(without_urls, [])
            self.assertEqual(with_urls[0].url, "https://example.com/docs")


class CliTests(unittest.TestCase):
    def test_preview_window_keeps_right_side_preview(self) -> None:
        self.assertIn(_preview_window(), {"right,65%,border-left", "right,70%,border-left"})

    def test_tmux_capture_defaults_to_visible_pane_only(self) -> None:
        self.assertEqual(_capture_command(None, False), ["tmux", "capture-pane", "-p", "-J"])

    def test_tmux_capture_can_include_full_history(self) -> None:
        self.assertEqual(_capture_command(None, True), ["tmux", "capture-pane", "-p", "-J", "-S", "-"])

    def test_tmux_capture_can_target_specific_pane(self) -> None:
        self.assertEqual(
            _capture_command("%3", False),
            ["tmux", "capture-pane", "-p", "-J", "-t", "%3"],
        )

    def test_json_mode_uses_input_and_base_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "README.md").write_text("readme")
            pane = base / "pane.txt"
            pane.write_text("[README](README.md)")

            result = subprocess.run(
                [
                    str(ROOT / "bin" / "poplink"),
                    "--input",
                    str(pane),
                    "--base-dir",
                    str(base),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=True,
            )

            payload = json.loads(result.stdout)
            self.assertEqual(payload[0]["display"], "README.md")


if __name__ == "__main__":
    unittest.main()
