# Copyright (c) lintmax-py contributors. Licensed under the MIT License.
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import TYPE_CHECKING

import tomllib

if TYPE_CHECKING:
    from pathlib import Path

TIMEOUT = 15
NAME_RE = re.compile(r"^[A-Za-z0-9._-]+")


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
            names.append(match.group(0).lower())
    return sorted(set(names))


def locked(root: Path) -> dict[str, str]:
    lock = root / "uv.lock"
    if not lock.is_file():
        return {}
    data = tomllib.loads(lock.read_text(encoding="utf-8"))
    return {
        str(pkg["name"]).lower(): str(pkg["version"])
        for pkg in data.get("package", [])
        if "name" in pkg and "version" in pkg
    }


def latest(name: str) -> str | None:
    try:
        with urllib.request.urlopen(
            f"https://pypi.org/pypi/{name}/json",
            timeout=TIMEOUT,
        ) as response:
            body = json.load(response)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None
    version = body.get("info", {}).get("version")
    return str(version) if version else None


def behind(root: Path) -> list[str]:
    if skip():
        return []
    pinned = locked(root)
    stale: list[str] = []
    for name in declared(root):
        current = pinned.get(name)
        if current is None:
            continue
        newest = latest(name)
        if newest is not None and newest != current:
            stale.append(f"{name} {current} -> {newest}")
    return stale
