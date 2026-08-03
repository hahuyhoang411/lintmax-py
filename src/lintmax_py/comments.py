# Copyright (c) lintmax-py contributors. Licensed under the MIT License.
from __future__ import annotations

import io
import tokenize
from typing import TYPE_CHECKING

from .paths import sources

if TYPE_CHECKING:
    from pathlib import Path

SURVIVORS = (
    "#!",
    "# Copyright",
    "# SPDX-",
    "# noqa",
    "# ruff:",
    "# ty:",
    "# type:",
    "# pragma:",
    "# fmt:",
    "# isort:",
    "# reason:",
    "# -*-",
)


def survives(text: str) -> bool:
    stripped = text.strip()
    return any(stripped.startswith(prefix) for prefix in SURVIVORS)


def strip_text(source: str) -> str:
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return source
    doomed: dict[int, list[tuple[int, int]]] = {}
    for tok in tokens:
        if tok.type != tokenize.COMMENT or survives(tok.string):
            continue
        doomed.setdefault(tok.start[0], []).append((tok.start[1], tok.end[1]))
    if not doomed:
        return source
    lines = source.splitlines(keepends=True)
    out: list[str] = []
    for number, line in enumerate(lines, start=1):
        spans = doomed.get(number)
        if spans is None:
            out.append(line)
            continue
        body = line.rstrip("\r\n")
        ending = line[len(body) :]
        for start, end in sorted(spans, reverse=True):
            body = body[:start] + body[end:]
        if not body.strip():
            continue
        out.append(body.rstrip() + ending)
    return "".join(out)


def strip_tree(root: Path) -> int:
    changed = 0
    for path in sources(root):
        original = path.read_text(encoding="utf-8")
        rewritten = strip_text(original)
        if rewritten != original:
            path.write_text(rewritten, encoding="utf-8")
            changed += 1
    return changed


def offenders(root: Path) -> list[str]:
    found: list[str] = []
    for path in sources(root):
        text = path.read_text(encoding="utf-8")
        if strip_text(text) != text:
            found.append(str(path))
    return found
