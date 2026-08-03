# Copyright (c) lintmax-py contributors. Licensed under the MIT License.
from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path

from .proc import have, run

UV_TOOLS = ("ruff", "ty", "vulture", "deptry", "pip-audit")
NATIVE_TOOLS = ("dprint", "typos", "shellcheck", "shfmt")
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
    except ValueError:
        return False
    return (time.time() - stamped) < REFRESH_TTL_SECONDS


def mark() -> None:
    path = stamp()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(time.time()), encoding="utf-8")


def ensure() -> list[str]:
    missing: list[str] = []
    refresh = not fresh()
    for tool in UV_TOOLS:
        if refresh or not have(tool):
            res = run(["uv", "tool", "install", "--quiet", f"{tool}@latest"], timeout=600)
            if res.code != 0 and not have(tool):
                missing.append(f"{tool}: install failed ({res.out})")
    for tool in NATIVE_TOOLS:
        if have(tool):
            continue
        if have("brew"):
            run(["brew", "install", "--quiet", tool], timeout=900)
        if not have(tool):
            missing.append(f"{tool}: not installed and could not be installed")
    if refresh:
        mark()
    return missing
