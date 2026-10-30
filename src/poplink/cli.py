from __future__ import annotations

import argparse
import configparser
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

from .candidates import Candidate, extract_candidates

DEFAULT_CAPTURE_LINES = 200


@dataclass(frozen=True)
class CaptureScope:
    mode: str
    lines: int | None = None

    @property
    def description(self) -> str:
        if self.mode == "history":
            return "full scrollback"
        if self.mode == "visible":
            return "visible pane"
        return f"last {self.lines} lines"


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)

    try:
        config = _load_config(args.config)
        scope = _capture_scope(args, config)
        pane_text = _load_input(args, scope)
        base_dir = _base_dir(args)
        candidates = extract_candidates(
            pane_text,
            base_dir,
            include_missing=args.all,
            include_dirs=args.include_dirs or args.all,
            include_urls=args.include_urls or args.all,
        )

        if args.json:
            print(json.dumps([candidate.to_dict() for candidate in candidates], indent=2))
            return 0

        if not candidates:
            print(f"poplink: {_no_candidates_message(scope)}", file=sys.stderr)
            _hold_on_error(args.hold_on_error)
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
        _hold_on_error(args.hold_on_error)
        return error.status


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Open paths and links from the current tmux or Rex pane.")
    parser.add_argument("--backend", choices=("auto", "tmux", "rex"), default="auto", help="capture backend (default: auto; nested tmux takes priority)")
    parser.add_argument("--pane", help="tmux pane id to capture")
    parser.add_argument("--block", help="Rex source block id (required when opening from a floating picker)")
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--lines", type=_positive_int, help=f"scan the last N lines (default: {DEFAULT_CAPTURE_LINES})")
    scope.add_argument("--history", action="store_true", help="scan full scrollback")
    scope.add_argument("--visible", action="store_true", help="scan only the visible pane")
    parser.add_argument("--all", action="store_true", help="include missing paths and URLs")
    parser.add_argument("--include-dirs", action="store_true", help="include directories in addition to files")
    parser.add_argument("--include-urls", action="store_true", help="include HTTP/HTTPS URLs")
    parser.add_argument("--no-preview", action="store_true", help="disable fzf preview")
    parser.add_argument("--hold-on-error", action="store_true", help="wait for Enter before exiting after an error")
    parser.add_argument("--json", action="store_true", help="print extracted candidates as JSON")
    parser.add_argument("--print", action="store_true", help="print selected target instead of opening")
    parser.add_argument("--editor", help="editor command to use")
    parser.add_argument("--config", type=Path, help="config file path")
    parser.add_argument("--input", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--base-dir", type=Path, help=argparse.SUPPRESS)
    return parser


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be an integer") from error
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return parsed


def _no_candidates_message(scope: "CaptureScope") -> str:
    return f"no local files found in {scope.description}; try --history, --include-dirs, or --all"


def _hold_on_error(enabled: bool) -> None:
    if not enabled or not sys.stdin.isatty():
        return
    try:
        input("\nPress enter to close...")
    except EOFError:
        return


def _default_config_path() -> Path:
    config_home = os.environ.get("XDG_CONFIG_HOME")
    if config_home:
        return Path(config_home) / "poplink" / "config.ini"
    return Path.home() / ".config" / "poplink" / "config.ini"


def _load_config(path: Path | None) -> configparser.ConfigParser:
    config = configparser.ConfigParser()
    config_path = path or _default_config_path()
    if not config_path.exists():
        return config

    try:
        with config_path.open() as file:
            config.read_file(file)
    except configparser.Error as error:
        raise PoplinkError(f"failed to parse config {config_path}: {error}") from error
    except OSError as error:
        raise PoplinkError(f"failed to read config {config_path}: {error}") from error
    return config


def _capture_scope(args: argparse.Namespace, config: configparser.ConfigParser) -> CaptureScope:
    if args.history:
        return CaptureScope("history")
    if args.visible:
        return CaptureScope("visible")
    if args.lines is not None:
        return CaptureScope("lines", args.lines)
    return CaptureScope("lines", _configured_capture_lines(config))


def _configured_capture_lines(config: configparser.ConfigParser) -> int:
    if not config.has_option("capture", "lines"):
        return DEFAULT_CAPTURE_LINES

    raw_value = config.get("capture", "lines")
    try:
        lines = int(raw_value)
    except ValueError as error:
        raise PoplinkError("config capture.lines must be an integer") from error
    if lines <= 0:
        raise PoplinkError("config capture.lines must be greater than 0")
    return lines


def _load_input(args: argparse.Namespace, scope: CaptureScope) -> str:
    if args.input:
        return args.input.read_text()

    if _backend(args) == "rex":
        return _capture_rex(args, scope)
    if not shutil.which("tmux"):
        raise PoplinkError("tmux is required", 127)

    command = _capture_command(args.pane, scope)
    result = subprocess.run(command, text=True, capture_output=True)
    if result.returncode != 0:
        raise PoplinkError(result.stderr.strip() or "failed to capture tmux pane")
    return result.stdout


def _backend(args: argparse.Namespace) -> str:
    if args.pane and args.block:
        raise PoplinkError("--pane and --block cannot be combined")
    if args.backend == "rex" and args.pane:
        raise PoplinkError("--pane is only supported by the tmux backend")
    if args.backend == "tmux" and args.block:
        raise PoplinkError("--block is only supported by the Rex backend")
    if args.backend != "auto":
        return args.backend
    if args.block:
        return "rex"
    if args.pane or os.environ.get("TMUX"):
        return "tmux"
    if os.environ.get("REX_SESSION") and os.environ.get("REX_BLOCK"):
        return "rex"
    raise PoplinkError("must be run inside tmux or Rex (or use --input)")


def _rex_command(args: argparse.Namespace) -> list[str]:
    if not shutil.which("rex"):
        raise PoplinkError("rex is required; run inside a Rex terminal", 127)
    if not os.environ.get("REX_SESSION") or not (args.block or os.environ.get("REX_BLOCK")):
        raise PoplinkError("Rex session and source block are required; run inside Rex or pass --block from a Rex popup")
    command = ["rex", "--autostart=false"]
    if os.environ.get("REX_SERVER"):
        command.extend(["--server", os.environ["REX_SERVER"]])
    return command


def _run_rex(command: list[str]) -> str:
    try:
        result = subprocess.run(command, text=True, capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise PoplinkError(f"failed to contact Rex: {error}") from error
    if result.returncode:
        raise PoplinkError(result.stderr.strip() or "Rex request failed")
    return result.stdout


def _rex_terminal_call(args: argparse.Namespace, method: str) -> dict:
    command = _rex_command(args) + [
        "api", "call", "--session", os.environ["REX_SESSION"],
        "com.superlogical.terminal." + method,
        json.dumps({"block_id": args.block or os.environ["REX_BLOCK"], "args": {}}),
    ]
    try:
        result = json.loads(_run_rex(command))
    except json.JSONDecodeError as error:
        raise PoplinkError(f"invalid Rex {method} response") from error
    if not isinstance(result, dict):
        raise PoplinkError(f"invalid Rex {method} response")
    return result


def _capture_rex(args: argparse.Namespace, scope: CaptureScope) -> str:
    if scope.mode == "visible":
        # Rex's text formatter omits blank screen rows and exposes no history
        # boundary. Taking the last terminal-height lines can include history.
        raise PoplinkError("Rex does not expose screen-only capture; use --lines N or --history instead of --visible")
    command = _rex_command(args) + [
        "capture", "--session", os.environ["REX_SESSION"],
        "--block", args.block or os.environ["REX_BLOCK"],
    ]
    # Join soft wraps so references split across terminal rows are recognized.
    command.append("--unwrap")
    text = _run_rex(command)
    if scope.mode == "history":
        return text
    return "\n".join(text.splitlines()[-scope.lines:])


def _capture_command(pane: str | None, scope: "CaptureScope") -> list[str]:
    command = ["tmux", "capture-pane", "-p", "-J"]
    if scope.mode == "history":
        command.extend(["-S", "-"])
    elif scope.mode == "lines":
        command.extend(["-S", f"-{scope.lines}"])
    if pane:
        command.extend(["-t", pane])
    return command


def _base_dir(args: argparse.Namespace) -> Path:
    if args.base_dir:
        return args.base_dir
    if not args.input and _backend(args) == "rex":
        process = _rex_terminal_call(args, "process")
        # Resolve relative paths against the source terminal, not the picker.
        for entry in (process.get("foreground"), process.get("child")):
            if entry and entry.get("cwd"):
                return Path(entry["cwd"])
        raise PoplinkError("cannot determine the Rex source directory; use --base-dir")
    return Path.cwd()


def _select_candidate(candidates: list[Candidate], no_preview: bool) -> Candidate | None:
    if not shutil.which("fzf"):
        raise PoplinkError("fzf is required", 127)

    rows = [_format_row(index, candidate) for index, candidate in enumerate(candidates)]
    command = [
        "fzf",
        "--ansi",
        "--delimiter",
        "\t",
        "--with-nth",
        "2..",
        "--preview-window",
        _preview_window(),
    ]
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
            "case \"$file\" in *.md|*.markdown|*.txt|*.log) wrap='--wrap=character' ;; *) wrap='' ;; esac; "
            "if [ -n \"$line\" ]; then "
            "bat --color=always --style=numbers $wrap --highlight-line \"$line\" \"$file\" 2>/dev/null; "
            "else bat --color=always --style=numbers $wrap \"$file\" 2>/dev/null; fi"
        )
    return None


def _preview_window() -> str:
    columns = shutil.get_terminal_size(fallback=(120, 40)).columns
    if columns >= 150:
        return "right,65%,border-left"
    return "right,70%,border-left"


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

    # Popup editors should not race long-running Neovim instances over ShaDa.
    # Respect an explicit history-file choice supplied through --editor/EDITOR.
    if Path(editor_parts[0]).name == "nvim" and not any(part.startswith("-i") for part in editor_parts[1:]):
        editor_parts.extend(["-i", "NONE"])
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
