# Copyright (c) lintmax-py contributors. Licensed under the MIT License.
from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

from . import rules
from .dprint import bump

LINE_LENGTH = 123

DPRINT_SEED = [
    "https://plugins.dprint.dev/json-0.23.0.wasm",
    "https://plugins.dprint.dev/markdown-0.22.1.wasm",
    "https://plugins.dprint.dev/toml-0.7.0.wasm",
    "https://plugins.dprint.dev/dockerfile-0.4.1.wasm",
    "https://plugins.dprint.dev/g-plane/pretty_yaml-v0.6.0.wasm",
    "https://plugins.dprint.dev/g-plane/malva-v0.16.0.wasm",
    "https://plugins.dprint.dev/g-plane/markup_fmt-v0.27.3.wasm",
    "https://plugins.dprint.dev/g-plane/pretty_graphql-v0.2.3.wasm",
    "https://plugins.dprint.dev/bartlomieju/lax-sql-0.3.0.wasm",
]

EXCLUDES = [
    "**/.venv",
    "**/__pycache__",
    "**/.git",
    "**/dist",
    "**/build",
    "**/.ruff_cache",
    "**/node_modules",
    "**/uv.lock",
]


def ruff_toml(inventory: list[dict[str, object]]) -> str:
    select = json.dumps(rules.selection(inventory))
    ignore = json.dumps(rules.ignored())
    return (
        "preview = true\n"
        f"line-length = {LINE_LENGTH}\n"
        f"exclude = {json.dumps(EXCLUDES)}\n"
        "[lint]\n"
        f"select = {select}\n"
        f"ignore = {ignore}\n"
        "[lint.flake8-quotes]\n"
        'inline-quotes = "double"\n'
        "[lint.flake8-copyright]\n"
        "notice-rgx = '(?i)Copyright\\s+(\\(c\\)|©)'\n"
        "[format]\n"
        "docstring-code-format = true\n"
    )


def dprint_json() -> str:
    return json.dumps(
        {
            "lineWidth": LINE_LENGTH,
            "indentWidth": 2,
            "useTabs": False,
            "newLineKind": "lf",
            "includes": ["**/*"],
            "excludes": EXCLUDES,
            "plugins": bump(DPRINT_SEED),
        },
        indent=2,
    )


def typos_toml() -> str:
    return "[default]\ncheck-filename = true\ncheck-file = true\n"


def materialize(inventory: list[dict[str, object]]) -> tuple[Path, str]:
    root = Path(tempfile.mkdtemp(prefix="lintmax-py-"))
    written = {
        "ruff.toml": ruff_toml(inventory),
        "dprint.json": dprint_json(),
        "typos.toml": typos_toml(),
    }
    for name, body in written.items():
        (root / name).write_text(body, encoding="utf-8")
    digest = hashlib.sha256("".join(written.values()).encode()).hexdigest()
    return root, digest
