# Copyright (c) lintmax-py contributors. Licensed under the MIT License.
from __future__ import annotations

import json

from .proc import run

DOCSTRING_REQUIRED = ("D100", "D101", "D102", "D103", "D104", "D105", "D106", "D107")


def inventory() -> list[dict[str, object]]:
    res = run(["ruff", "rule", "--all", "--output-format", "json"])
    if res.code != 0:
        msg = f"ruff rule --all failed: {res.out}"
        raise RuntimeError(msg)
    parsed: object = json.loads(res.out)
    if not isinstance(parsed, list) or not parsed:
        msg = "ruff reported an empty rule set"
        raise RuntimeError(msg)
    inventory: list[dict[str, object]] = []
    for rule in parsed:
        if not isinstance(rule, dict):
            msg = "ruff reported a malformed rule set"
            raise TypeError(msg)
        inventory.append({str(key): value for key, value in rule.items()})
    return inventory


def preview_codes(rules: list[dict[str, object]]) -> list[str]:
    return sorted(str(r["code"]) for r in rules if r.get("preview"))


def selection(rules: list[dict[str, object]]) -> list[str]:
    return ["ALL", *preview_codes(rules)]


def ignored() -> list[str]:
    return list(DOCSTRING_REQUIRED)


def summary(rules: list[dict[str, object]]) -> str:
    linters = {str(r.get("linter", "?")) for r in rules}
    preview = preview_codes(rules)
    return (
        f"ruff rules: {len(rules)} across {len(linters)} linters "
        f"({len(preview)} preview-gated, all selected)\n"
        f"ty rules: all at error severity\n"
        f"disabled: {', '.join(ignored())} (docstring-required family)"
    )
