# Copyright (c) lintmax-py contributors. Licensed under the MIT License.
from __future__ import annotations

import os
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import] reason: the gate's whole job is driving child linters
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Result:
    code: int
    out: str


def run(
    argv: list[str],
    cwd: str | None = None,
    timeout: int = 1800,
    env: dict[str, str] | None = None,
) -> Result:
    if shutil.which(argv[0]) is None:
        return Result(code=127, out=f"{argv[0]}: not installed")
    try:
        done = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
            argv,
            cwd=cwd,
            env=os.environ | env if env is not None else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return Result(code=124, out=f"{argv[0]}: timed out after {timeout}s")
    except OSError as err:
        return Result(code=126, out=f"{argv[0]}: {err}")
    return Result(code=done.returncode, out=(done.stdout + done.stderr).strip())


def filter_text(argv: list[str], text: str, timeout: int = 1800) -> str | None:
    """Run a child as a text filter and return ONLY what it wrote to stdout.

    `run` merges stderr into its output and strips the result, which is right for a stage's report
    and wrong for a file's content: one deprecation line on stderr would be appended to the file,
    and the strip would drop the trailing newline every formatter is required to leave.

    Returns:
        The child's stdout, or nothing when the tool is missing or the run failed.

    """
    if shutil.which(argv[0]) is None:
        return None
    try:
        done = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
            argv,
            input=text,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    return done.stdout if done.returncode == 0 else None
