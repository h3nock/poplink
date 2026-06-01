from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

from .candidates import Candidate, extract_candidates


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)

    try:
        pane_text = _load_input(args)
        base_dir = _base_dir(args)
        candidates = extract_candidates(
            pane_text,
            base_dir,
            include_missing=args.all,
            include_urls=args.include_urls or args.all,
        )

        if args.json:
            print(json.dumps([candidate.to_dict() for candidate in candidates], indent=2))
            return 0

        if not candidates:
            print("poplink: no local file paths found in pane", file=sys.stderr)
            return 1

        selected = _select_candidate(candidates, args.no_preview)
        if selected is None:
            return 0

        if args.print:
            print(_target_text(selected))
            return 0

        return _open_candidate(selected, args.editor)
    except PoplinkError as error:
        print(f"poplink: {error}", file=sys.stderr)
        return error.status


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Open paths and links from the current tmux pane.")
    parser.add_argument("--pane", help="tmux pane id to capture")
    parser.add_argument("--history", action="store_true", help="scan full tmux scrollback instead of only the visible pane")
    parser.add_argument("--all", action="store_true", help="include missing paths and URLs")
    parser.add_argument("--include-urls", action="store_true", help="include HTTP/HTTPS URLs")
    parser.add_argument("--no-preview", action="store_true", help="disable fzf preview")
    parser.add_argument("--json", action="store_true", help="print extracted candidates as JSON")
    parser.add_argument("--print", action="store_true", help="print selected target instead of opening")
    parser.add_argument("--editor", help="editor command to use")
    parser.add_argument("--input", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--base-dir", type=Path, help=argparse.SUPPRESS)
    return parser


def _load_input(args: argparse.Namespace) -> str:
    if args.input:
        return args.input.read_text()

    if not os.environ.get("TMUX"):
        raise PoplinkError("must be run inside tmux")
    if not shutil.which("tmux"):
        raise PoplinkError("tmux is required", 127)

    command = _capture_command(args.pane, args.history)
    result = subprocess.run(command, text=True, capture_output=True)
    if result.returncode != 0:
        raise PoplinkError(result.stderr.strip() or "failed to capture tmux pane")
    return result.stdout


def _capture_command(pane: str | None, include_history: bool) -> list[str]:
    command = ["tmux", "capture-pane", "-p", "-J"]
    if include_history:
        command.extend(["-S", "-"])
    if pane:
        command.extend(["-t", pane])
    return command


def _base_dir(args: argparse.Namespace) -> Path:
    if args.base_dir:
        return args.base_dir
    return Path.cwd()


def _select_candidate(candidates: list[Candidate], no_preview: bool) -> Candidate | None:
    if not shutil.which("fzf"):
        raise PoplinkError("fzf is required", 127)

    rows = [_format_row(index, candidate) for index, candidate in enumerate(candidates)]
    command = ["fzf", "--ansi", "--delimiter", "\t", "--with-nth", "2.."]
    if not no_preview:
        preview = _preview_command()
        if preview:
            command.extend(["--preview", preview])

    result = subprocess.run(
        command,
        input="\n".join(rows),
        text=True,
        capture_output=True,
    )
    if result.returncode == 130:
        return None
    if result.returncode != 0:
        return None

    selected = result.stdout.split("\t", 1)[0].strip()
    if not selected:
        return None
    return candidates[int(selected)]


def _format_row(index: int, candidate: Candidate) -> str:
    detail = candidate.kind
    if candidate.line is not None:
        detail = f"{detail}:line"
    return f"{index}\t{candidate.display}\t{detail}"


def _preview_command() -> str | None:
    if shutil.which("bat"):
        return (
            "file=$(printf '%s' {} | cut -f2 | sed -E 's/:([0-9]+)(:[0-9]+)?$//'); "
            "line=$(printf '%s' {} | cut -f2 | sed -nE 's/.*:([0-9]+)(:[0-9]+)?$/\\1/p'); "
            "if [ -n \"$line\" ]; then "
            "bat --color=always --style=numbers --highlight-line \"$line\" \"$file\" 2>/dev/null; "
            "else bat --color=always --style=numbers \"$file\" 2>/dev/null; fi"
        )
    return None


def _open_candidate(candidate: Candidate, editor: str | None) -> int:
    if candidate.kind == "url":
        if not shutil.which("open"):
            raise PoplinkError("open command is required for URLs", 127)
        return subprocess.run(["open", candidate.url or ""]).returncode

    if candidate.path is None:
        raise PoplinkError("selected candidate has no path")

    editor_command = editor or os.environ.get("EDITOR") or "nvim"
    editor_parts = shlex.split(editor_command)
    if not editor_parts:
        raise PoplinkError("editor command is empty")
    if not shutil.which(editor_parts[0]):
        raise PoplinkError(f"editor not found: {editor_parts[0]}", 127)

    command = editor_parts + _editor_target_args(candidate)
    return subprocess.run(command).returncode


def _editor_target_args(candidate: Candidate) -> list[str]:
    path = str(candidate.path)
    if candidate.line is None:
        return [path]
    if candidate.column is None:
        return [f"+{candidate.line}", path]
    return [f"+call cursor({candidate.line}, {candidate.column})", path]


def _target_text(candidate: Candidate) -> str:
    if candidate.kind == "url":
        return candidate.url or ""
    if candidate.path is None:
        return ""
    text = str(candidate.path)
    if candidate.line is not None:
        text = f"{text}:{candidate.line}"
    if candidate.column is not None:
        text = f"{text}:{candidate.column}"
    return text


class PoplinkError(Exception):
    def __init__(self, message: str, status: int = 1) -> None:
        super().__init__(message)
        self.status = status
