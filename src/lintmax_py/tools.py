# Copyright (c) lintmax-py contributors. Licensed under the MIT License.
from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path

from .proc import have, run

TOOLS = {
    "ruff": "ruff",
    "ty": "ty",
    "vulture": "vulture",
    "deptry": "deptry",
    "pip-audit": "pip-audit",
    "typos": "typos",
    "shellcheck-py": "shellcheck",
    "shfmt-py": "shfmt",
    "dprint-py": "dprint",
}
REFRESH_TTL_SECONDS = 24 * 60 * 60


def is_ci() -> bool:
    return any(os.environ.get(name) for name in ("CI", "GITHUB_ACTIONS"))


def stamp() -> Path:
    key = hashlib.sha256(b"lintmax-py-refresh").hexdigest()[:16]
    return Path.home() / ".cache" / "lintmax-py" / f"{key}.refresh"


def fresh() -> bool:
    if is_ci():
        return False
    path = stamp()
    if not path.is_file():
        return False
    try:
        stamped = float(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    return (time.time() - stamped) < REFRESH_TTL_SECONDS


def mark() -> None:
    path = stamp()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(time.time()), encoding="utf-8")


def ensure() -> list[str]:
    missing: list[str] = []
    refresh = not fresh()
    for package, exe in TOOLS.items():
        if not refresh and have(exe):
            continue
        res = run(["uv", "tool", "install", "--quiet", f"{package}@latest"], timeout=900)
        if not have(exe):
            reason = res.out or f"exit {res.code}"
            missing.append(f"{exe}: install of {package} did not produce it ({reason})")
    if refresh:
        mark()
    return missing


def executables() -> list[str]:
    return sorted(TOOLS.values())
