from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import re
from typing import Iterable


MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)\n]+)\)")
PYTHON_TRACE_RE = re.compile(r'File "([^"]+)", line (\d+)')
QUOTED_RE = re.compile(r"""["'`]([^"'`\n]+)["'`]""")
URL_RE = re.compile(r"https?://[^\s)>'\"`]+")
TOKEN_RE = re.compile(
    r"""
    (?P<target>
        (?:~|/|\.\.?/|[A-Za-z0-9_.-]+/)
        [^\s<>"'`]+
        |
        [A-Za-z0-9_.-]+\.[A-Za-z0-9][A-Za-z0-9_.-]*
        (?::\d+){0,2}
    )
    """,
    re.VERBOSE,
)
LOCATION_RE = re.compile(r"^(?P<path>.*?)(?::(?P<line>\d+)(?::(?P<column>\d+))?)$")

TRAILING_PUNCTUATION = ".,;)]}"


@dataclass(frozen=True)
class Candidate:
    kind: str
    path: Path | None
    url: str | None
    line: int | None
    column: int | None
    display: str
    original: str

    @property
    def key(self) -> tuple[str, str, int | None, int | None]:
        target = self.url if self.kind == "url" else str(self.path)
        return (self.kind, target or "", self.line, self.column)

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "path": str(self.path) if self.path is not None else None,
            "url": self.url,
            "line": self.line,
            "column": self.column,
            "display": self.display,
            "original": self.original,
        }


def extract_candidates(
    text: str,
    base_dir: Path,
    *,
    include_missing: bool = False,
    include_urls: bool = False,
) -> list[Candidate]:
    base_dir = base_dir.expanduser().resolve()
    candidates: list[Candidate] = []

    for line in text.splitlines():
        protected_spans = _protected_spans(line)
        trace_spans = [match.span() for match in PYTHON_TRACE_RE.finditer(line)]
        candidates.extend(_markdown_candidates(line, base_dir, include_missing))
        candidates.extend(_python_trace_candidates(line, base_dir, include_missing))
        candidates.extend(_quoted_candidates(line, base_dir, include_missing, trace_spans))
        candidates.extend(_token_candidates(line, base_dir, include_missing, protected_spans))
        if include_urls:
            candidates.extend(_url_candidates(line))

    return _dedupe(candidates)


def _markdown_candidates(line: str, base_dir: Path, include_missing: bool) -> Iterable[Candidate]:
    for match in MARKDOWN_LINK_RE.finditer(line):
        target = _strip_wrapping(match.group(1).strip())
        if _looks_like_url(target):
            continue
        candidate = _candidate_from_target(target, base_dir, "markdown", match.group(0), include_missing)
        if candidate:
            yield candidate


def _python_trace_candidates(line: str, base_dir: Path, include_missing: bool) -> Iterable[Candidate]:
    for match in PYTHON_TRACE_RE.finditer(line):
        target = f"{match.group(1)}:{match.group(2)}"
        candidate = _candidate_from_target(target, base_dir, "trace", match.group(0), include_missing)
        if candidate:
            yield candidate


def _quoted_candidates(
    line: str,
    base_dir: Path,
    include_missing: bool,
    protected_spans: list[tuple[int, int]],
) -> Iterable[Candidate]:
    for match in QUOTED_RE.finditer(line):
        if _overlaps(match.span(), protected_spans):
            continue
        target = match.group(1).strip()
        if _looks_like_url(target) or not _looks_path_like(target):
            continue
        candidate = _candidate_from_target(target, base_dir, "quoted", match.group(0), include_missing)
        if candidate:
            yield candidate


def _token_candidates(
    line: str,
    base_dir: Path,
    include_missing: bool,
    protected_spans: list[tuple[int, int]],
) -> Iterable[Candidate]:
    for match in TOKEN_RE.finditer(line):
        if _overlaps(match.span(), protected_spans):
            continue
        target = _strip_trailing_punctuation(match.group("target"))
        if _looks_like_url(target) or not _looks_path_like(target):
            continue
        candidate = _candidate_from_target(target, base_dir, "path", target, include_missing)
        if candidate:
            yield candidate


def _url_candidates(line: str) -> Iterable[Candidate]:
    for match in URL_RE.finditer(line):
        url = _strip_trailing_punctuation(match.group(0))
        yield Candidate(
            kind="url",
            path=None,
            url=url,
            line=None,
            column=None,
            display=url,
            original=match.group(0),
        )


def _candidate_from_target(
    target: str,
    base_dir: Path,
    kind: str,
    original: str,
    include_missing: bool,
) -> Candidate | None:
    target = _strip_wrapping(_strip_trailing_punctuation(target.strip()))
    if not target:
        return None

    path_text, line, column = _split_location(target)
    path = _resolve_path(path_text, base_dir)
    if not include_missing and not path.exists():
        return None

    return Candidate(
        kind=kind,
        path=path,
        url=None,
        line=line,
        column=column,
        display=_display_path(path, base_dir, line, column),
        original=original,
    )


def _split_location(target: str) -> tuple[str, int | None, int | None]:
    match = LOCATION_RE.match(target)
    if not match:
        return target, None, None

    path = match.group("path")
    if not path:
        return target, None, None

    line = int(match.group("line"))
    column = int(match.group("column")) if match.group("column") else None
    return path, line, column


def _resolve_path(path_text: str, base_dir: Path) -> Path:
    expanded = os.path.expanduser(path_text)
    path = Path(expanded)
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def _display_path(path: Path, base_dir: Path, line: int | None, column: int | None) -> str:
    try:
        display = str(path.relative_to(base_dir))
    except ValueError:
        display = str(path)

    if line is not None:
        display = f"{display}:{line}"
    if column is not None:
        display = f"{display}:{column}"
    return display


def _dedupe(candidates: Iterable[Candidate]) -> list[Candidate]:
    seen: set[tuple[str, str, int | None, int | None]] = set()
    result: list[Candidate] = []
    for candidate in candidates:
        if candidate.key in seen:
            continue
        seen.add(candidate.key)
        result.append(candidate)
    return result


def _protected_spans(line: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for regex in (MARKDOWN_LINK_RE, PYTHON_TRACE_RE, QUOTED_RE, URL_RE):
        spans.extend(match.span() for match in regex.finditer(line))
    return spans


def _overlaps(span: tuple[int, int], protected_spans: list[tuple[int, int]]) -> bool:
    start, end = span
    return any(start < protected_end and end > protected_start for protected_start, protected_end in protected_spans)


def _strip_wrapping(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'`":
        return value[1:-1]
    return value


def _strip_trailing_punctuation(value: str) -> str:
    while value and value[-1] in TRAILING_PUNCTUATION:
        value = value[:-1]
    return value


def _looks_like_url(value: str) -> bool:
    return value.startswith(("http://", "https://"))


def _looks_path_like(value: str) -> bool:
    if _looks_like_url(value):
        return False
    return (
        value.startswith(("/", "~/", "./", "../"))
        or "/" in value
        or bool(re.search(r"\.[A-Za-z0-9][A-Za-z0-9_.-]*(?::\d+){0,2}$", value))
    )
