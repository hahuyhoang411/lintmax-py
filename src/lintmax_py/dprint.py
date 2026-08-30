# Copyright (c) lintmax-py contributors. Licensed under the MIT License.
from __future__ import annotations

import hashlib
import http.client
import json
import re
import time
from pathlib import Path

from .proc import filter_text, run

HOST = "https://plugins.dprint.dev/"
TIMEOUT = 15
TTL_SECONDS = 6 * 60 * 60
SUCCESS_STATUS = 200

MARKDOWN_GLOB = "**/*.md"


VERSION_SUFFIX = re.compile(r"[-@]v?\d+\.\d+\.\d+$")
PLUGIN_PATH = re.compile(r"^[a-z0-9][a-z0-9_-]*(?:/[a-z0-9][a-z0-9_-]*)?$")


def plugin_name(file: str) -> str:
    """Strip the VERSION off a plugin's filename, never split at the first separator.

    A plugin whose own name carries a hyphen resolves to the wrong plugin entirely under a
    split-at-the-first-hyphen rule, and the wrong name still LOOKS like a name — so the failure is a
    404 against a plausible URL rather than anything that reads as a parsing bug.

    Returns:
        The plugin's name without its version.

    """
    return VERSION_SUFFIX.sub("", file)


def plugin_path(pinned: str) -> str | None:
    if not pinned.startswith(HOST):
        return None
    tail = pinned[len(HOST) :]
    if "." not in tail:
        return None
    file = tail.rsplit(".", 1)[0]
    if "/" in file:
        owner, rest = file.split("/", 1)
        return f"{owner}/{plugin_name(rest)}"
    return f"dprint/{plugin_name(file)}"


def latest_url(path: str) -> str | None:
    if not PLUGIN_PATH.fullmatch(path):
        return None
    connection = http.client.HTTPSConnection("plugins.dprint.dev", timeout=TIMEOUT)
    try:
        connection.request("GET", f"/{path}/latest.json")
        response = connection.getresponse()
        if response.status != SUCCESS_STATUS:
            return None
        body = json.loads(response.read())
    except (
        http.client.HTTPException,
        TimeoutError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        OSError,
    ):
        return None
    finally:
        connection.close()
    url = body.get("url") if isinstance(body, dict) else None
    return url if isinstance(url, str) and url.startswith(HOST) else None


def _cache_path(seed: list[str]) -> Path:
    key = hashlib.sha256("\n".join(seed).encode()).hexdigest()[:16]
    return Path.home() / ".cache" / "lintmax-py" / f"{key}.plugins"


def _cached(seed: list[str], *, force: bool) -> list[str] | None:
    if force:
        return None
    path = _cache_path(seed)
    if not path.is_file():
        return None
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
        stamped = float(body["stamp"])
        resolved = body["plugins"]
    except (json.JSONDecodeError, KeyError, ValueError, OSError):
        return None
    if time.time() - stamped >= TTL_SECONDS:
        return None
    return [str(p) for p in resolved] if isinstance(resolved, list) else None


def _store(seed: list[str], resolved: list[str]) -> None:
    path = _cache_path(seed)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"stamp": time.time(), "plugins": resolved}),
        encoding="utf-8",
    )


def bump(plugins: list[str], *, force: bool = False) -> list[str]:
    hit = _cached(plugins, force=force)
    if hit is not None:
        return hit
    out: list[str] = []
    for pinned in plugins:
        path = plugin_path(pinned)
        latest = latest_url(path) if path else None
        out.append(latest or pinned)
    _store(plugins, out)
    return out


class MarkdownEnumerationError(RuntimeError):
    """dprint could not name the markdown files the gate must check."""


TABLE_RULE = re.compile(r"^\|(?:\s*:?-+:?\s*\|)+$")
CELL_EDGE = re.compile(r"(?<!\\)\|")
FENCE = re.compile(r"^\s*(?:```|~~~)")


def _is_row(line: str) -> bool:
    text = line.strip()
    return len(text) > 1 and text.startswith("|") and text.endswith("|")


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in CELL_EDGE.split(line.strip())[1:-1]]


def _dashes(cell: str) -> str:
    left = ":" if cell.startswith(":") else ""
    right = ":" if cell.endswith(":") else ""
    return f"{left}---{right}"


def _compact_row(line: str, *, rule: bool) -> str:
    indent = line[: len(line) - len(line.lstrip())]
    body = " | ".join(_dashes(cell) if rule else cell for cell in _cells(line))
    return f"{indent}| {body} |"


def compact_tables(text: str) -> str:
    """Collapse a markdown table's alignment padding to one space at every cell boundary.

    The formatter pads each cell out to its column's widest entry, which lines the table up for
    someone reading the raw file and costs a token per space for the reader this gate is designed
    for — on a wide table more of the file is padding than content, and the rendered document is
    byte-identical either way. Only a genuine table is touched: a row is compacted when the line
    below the header is the delimiter row, so a lone pipe in a paragraph and every line inside a
    fenced block stay exactly as written.

    Returns:
        The text with every table row in its minimal form.

    """
    lines = text.split("\n")
    out = list(lines)
    fenced = False
    index = 0
    while index < len(lines):
        if FENCE.match(lines[index]):
            fenced = not fenced
            index += 1
            continue
        rule = index + 1
        opens = not fenced and _is_row(lines[index]) and rule < len(lines) and bool(TABLE_RULE.match(lines[rule].strip()))
        if not opens:
            index += 1
            continue
        while index < len(lines) and _is_row(lines[index]):
            out[index] = _compact_row(lines[index], rule=index == rule)
            index += 1
    return "\n".join(out)


def markdown_files(root: Path, config: Path, executable: str) -> list[Path]:
    """Ask the formatter which markdown files it would have handled.

    Reproducing that set with a glob diverges the moment a project excludes a directory or ignores
    a generated file: the sweep would rewrite a file the formatter itself never touches.

    Returns:
        The markdown files inside the project, in the formatter's own order.

    Raises:
        MarkdownEnumerationError: dprint could not enumerate its markdown input set.

    """
    listed = run(
        [executable, "output-file-paths", "--config", str(config), MARKDOWN_GLOB],
        cwd=str(root),
    )
    if listed.code != 0:
        detail = listed.out or f"exit {listed.code} with no output"
        message = f"dprint output-file-paths failed: {detail}"
        raise MarkdownEnumerationError(message)
    return [Path(line) for line in listed.out.splitlines() if line.endswith(".md")]


def sweep(root: Path, config: Path, executable: str, *, fix: bool) -> list[str]:
    """Format the markdown the main run leaves out, then compact its tables.

    The main invocation excludes markdown so that its aligned output is never what lands on disk;
    every markdown file is still formatted by the same plugin under the same config here, so
    nothing about the check relaxes — a file that is not in its final form is still a finding.

    Returns:
        The files whose content differs from the wanted form, always empty after a fixing run.

    """
    try:
        files = markdown_files(root, config, executable)
    except MarkdownEnumerationError as error:
        return [str(error)]
    stale: list[str] = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        rendered = filter_text([executable, "fmt", "--stdin", path.name, "--config", str(config)], text)
        if rendered is None:
            stale.append(f"{path}: markdown could not be formatted")
            continue
        wanted = compact_tables(rendered)
        if wanted == text:
            continue
        if fix:
            path.write_text(wanted, encoding="utf-8")
        else:
            stale.append(f"{path}: markdown not formatted (run fix)")
    return stale
