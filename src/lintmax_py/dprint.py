# Copyright (c) lintmax-py contributors. Licensed under the MIT License.
from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

HOST = "https://plugins.dprint.dev/"
TIMEOUT = 15
TTL_SECONDS = 6 * 60 * 60


def plugin_name(file: str) -> str:
    for sep in ("-", "@"):
        if sep in file:
            file = file.split(sep, 1)[0]
    return file


def plugin_path(pinned: str) -> str | None:
    if not pinned.startswith(HOST):
        return None
    tail = pinned[len(HOST) :]
    if "." not in tail:
        return None
    file = tail.rsplit(".", 1)[0]
    if "/" in file:
        owner, rest = file.split("/", 1)
        return f"{owner}/{plugin_name(rest)}"
    return f"dprint/{plugin_name(file)}"


def latest_url(path: str) -> str | None:
    try:
        with urllib.request.urlopen(f"{HOST}{path}/latest.json", timeout=TIMEOUT) as response:  # ruff: ignore[suspicious-url-open-usage]
            body = json.load(response)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None
    url = body.get("url") if isinstance(body, dict) else None
    return url if isinstance(url, str) and url.startswith(HOST) else None


def _cache_path(seed: list[str]) -> Path:
    key = hashlib.sha256("\n".join(seed).encode()).hexdigest()[:16]
    return Path.home() / ".cache" / "lintmax-py" / f"{key}.plugins"


def _cached(seed: list[str], *, force: bool) -> list[str] | None:
    if force:
        return None
    path = _cache_path(seed)
    if not path.is_file():
        return None
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
        stamped = float(body["stamp"])
        resolved = body["plugins"]
    except (json.JSONDecodeError, KeyError, ValueError, OSError):
        return None
    if time.time() - stamped >= TTL_SECONDS:
        return None
    return [str(p) for p in resolved] if isinstance(resolved, list) else None


def _store(seed: list[str], resolved: list[str]) -> None:
    path = _cache_path(seed)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"stamp": time.time(), "plugins": resolved}),
        encoding="utf-8",
    )


def bump(plugins: list[str], *, force: bool = False) -> list[str]:
    hit = _cached(plugins, force=force)
    if hit is not None:
        return hit
    out: list[str] = []
    for pinned in plugins:
        path = plugin_path(pinned)
        latest = latest_url(path) if path else None
        out.append(latest or pinned)
    _store(plugins, out)
    return out
