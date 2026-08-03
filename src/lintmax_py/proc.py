# Copyright (c) lintmax-py contributors. Licensed under the MIT License.
from __future__ import annotations

import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import] reason: the gate's whole job is driving child linters
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Result:
    code: int
    out: str


def run(argv: list[str], cwd: str | None = None, timeout: int = 1800) -> Result:
    if shutil.which(argv[0]) is None:
        return Result(code=127, out=f"{argv[0]}: not installed")
    try:
        done = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
            argv,
            cwd=cwd,
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


def have(exe: str) -> bool:
    return shutil.which(exe) is not None
