# Copyright (c) lintmax-py contributors. Licensed under the MIT License.
from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING

import tomllib

from .proc import Result, run

if TYPE_CHECKING:
    from pathlib import Path

NAME_RE = re.compile(r"^[A-Za-z0-9._-]+")
UPDATE_RE = re.compile(
    r"^Update (?P<name>\S+) v(?P<current>\S+) -> v(?P<newest>\S+)$",
    re.MULTILINE,
)


class ResolutionUnavailableError(RuntimeError):
    """Raised when uv cannot produce the resolver evidence staleness needs.

    A nonzero ``uv lock --upgrade --dry-run`` does not mean that dependencies are current. It
    means the gate has no trustworthy answer, which must fail the check rather than become a
    silent false green.
    """

    def __init__(self, result: Result) -> None:
        self.result = result
        output = result.out or "no output"
        super().__init__(
            f"uv lock --upgrade --dry-run could not establish staleness evidence (exit {result.code}): {output}",
        )


def canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def skip() -> bool:
    return bool(os.environ.get("LINTMAX_SKIP_STALENESS"))


def declared(root: Path) -> list[str]:
    manifest = root / "pyproject.toml"
    if not manifest.is_file():
        return []
    data = tomllib.loads(manifest.read_text(encoding="utf-8"))
    project = data.get("project", {})
    specs = list(project.get("dependencies", []))
    for group in data.get("dependency-groups", {}).values():
        specs += [g for g in group if isinstance(g, str)]
    for extra in project.get("optional-dependencies", {}).values():
        specs += list(extra)
    names = []
    for spec in specs:
        match = NAME_RE.match(spec.strip())
        if match:
            names.append(canonical(match.group(0)))
    return sorted(set(names))


def locked(root: Path) -> dict[str, str]:
    lock = root / "uv.lock"
    if not lock.is_file():
        return {}
    data = tomllib.loads(lock.read_text(encoding="utf-8"))
    return {
        canonical(str(pkg["name"])): str(pkg["version"])
        for pkg in data.get("package", [])
        if "name" in pkg and "version" in pkg
    }


def behind(root: Path, uv_command: tuple[str, ...]) -> list[str]:
    if skip():
        return []
    direct = set(declared(root))
    if not direct or not locked(root):
        return []
    result = run(
        [
            *uv_command,
            "lock",
            "--upgrade",
            "--dry-run",
            "--no-progress",
            "--color",
            "never",
        ],
        cwd=str(root),
        timeout=60,
    )
    if result.code != 0:
        raise ResolutionUnavailableError(result)
    return [
        f"{match['name']} {match['current']} -> {match['newest']}"
        for match in UPDATE_RE.finditer(result.out)
        if canonical(match["name"]) in direct
    ]
