# Copyright (c) lintmax-py contributors. Licensed under the MIT License.
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

SKIP_DIRS = frozenset({
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "site-packages",
    "venv",
})

GLOB_EXCLUDES = [f"**/{name}" for name in sorted(SKIP_DIRS)] + ["**/uv.lock"]


def skipped(path: Path) -> bool:
    return any(part in SKIP_DIRS for part in path.parts)
