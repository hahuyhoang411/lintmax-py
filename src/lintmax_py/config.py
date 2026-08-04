# Copyright (c) lintmax-py contributors. Licensed under the MIT License.
from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

import tomllib

from . import rules
from .dprint import bump
from .paths import GLOB_EXCLUDES

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

EXCLUDES = GLOB_EXCLUDES

TEST_GLOBS = ("**/tests/**/*.py", "**/test_*.py", "**/*_test.py", "**/conftest.py")
TEST_IGNORES = ("S101", "PLR2004", "INP001", "PLC2701", "SLF001")
"""Rules whose own purpose statement excludes test code, scoped to test files ONLY.

`assert` is pytest's assertion API rather than a production shortcut, a test's expected value IS a
literal so naming it only restates the assertion, a test directory carries no `__init__.py` by
design, and a test that never reaches its subject's internals cannot pin them. Nothing that ships
loses a rule: every one of these stays enforced on every other file in the tree.
"""


def _test_scoping() -> str:
    body = json.dumps(list(TEST_IGNORES))
    return "".join(f"{json.dumps(glob)} = {body}\n" for glob in TEST_GLOBS)


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
        f"[lint.per-file-ignores]\n{_test_scoping()}"
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


VOCABULARY_FILES = ("typos.toml", "_typos.toml", ".typos.toml", "pyproject.toml")
VOCABULARY_TABLES = ("extend-words", "extend-identifiers")


def vocabulary(root: Path) -> dict[str, dict[str, str]]:
    """Read the project's own spelling dictionary from the config the speller itself discovers.

    A spell checker with no project dictionary reports every domain noun a codebase owns — a client
    name, a product name, a protocol token — as a misspelling, and the only escapes are renaming the
    domain or turning the stage off. Neither is acceptable, so the dictionary is merged in. The
    speller resolves one config file and offers no inheritance, and the gate passes its own generated
    config, so a project file would otherwise be ignored entirely.

    Only the two vocabulary tables are read. The switches stay owned by the gate, so a project can
    name the words it uses and cannot weaken the check that reads them.

    Returns:
        The vocabulary tables present in the first config file that carries the speller's section.

    """
    for name in VOCABULARY_FILES:
        section = _typos_section(root / name)
        if section is None:
            continue
        found: dict[str, dict[str, str]] = {}
        for table in VOCABULARY_TABLES:
            entries = section.get(table)
            if isinstance(entries, dict):
                found[table] = {str(word): str(correction) for word, correction in entries.items()}
        if found:
            return found
    return {}


def _typos_section(path: Path) -> dict[str, object] | None:
    try:
        parsed = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None
    node = parsed.get("tool", {}).get("typos") if path.name == "pyproject.toml" else parsed
    if not isinstance(node, dict):
        return None
    default = node.get("default")
    return default if isinstance(default, dict) else None


def typos_toml(root: Path) -> str:
    body = "[default]\ncheck-filename = true\ncheck-file = true\n"
    for table, entries in vocabulary(root).items():
        body += f"[default.{table}]\n"
        body += "".join(f"{json.dumps(word)} = {json.dumps(correction)}\n" for word, correction in sorted(entries.items()))
    return body


def materialize(inventory: list[dict[str, object]], root: Path) -> tuple[Path, str]:
    cfg_root = Path(tempfile.mkdtemp(prefix="lintmax-py-"))
    written = {
        "ruff.toml": ruff_toml(inventory),
        "dprint.json": dprint_json(),
        "typos.toml": typos_toml(root),
    }
    for name, body in written.items():
        (cfg_root / name).write_text(body, encoding="utf-8")
    digest = hashlib.sha256("".join(written.values()).encode()).hexdigest()
    return cfg_root, digest
