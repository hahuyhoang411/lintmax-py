# Copyright (c) lintmax-py contributors. Licensed under the MIT License.
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

from .proc import run

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from .tools import Tool

DOCSTRING_REQUIRED = ("D100", "D101", "D102", "D103", "D104", "D105", "D106", "D107")
FORMATTER_CONFLICTS = ("COM812",)
RULE_CODE = re.compile(r"[A-Z]+[0-9]+")
RULE_NAME = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*")


class RuffInventoryUnavailableError(RuntimeError):
    """Ruff could not provide the selectable rule inventory strict coverage requires."""


@dataclass(frozen=True, slots=True)
class RuffInventory:
    """Rules emitted by one managed Ruff executable at one observed version."""

    executable: str
    version: str
    rules: tuple[Mapping[str, object], ...]


def _rule_name(rule: Mapping[str, object]) -> str:
    name = rule.get("name")
    return name if isinstance(name, str) and name else "<unnamed Ruff rule>"


def _unselectable_selector_error(
    rule: Mapping[str, object],
) -> RuffInventoryUnavailableError:
    code = rule.get("code")
    if code is not None:
        return RuffInventoryUnavailableError(
            f"ruff rule inventory is incomplete: rule {_rule_name(rule)!r} has malformed code {code!r}. "
            "lintmax-py will not substitute its name while a code is present; report this Ruff inventory defect "
            "or use a Ruff release with a complete inventory.",
        )
    return RuffInventoryUnavailableError(
        f"ruff rule inventory is incomplete: rule {_rule_name(rule)!r} has neither a selectable code nor name "
        "lintmax-py cannot claim exhaustive Ruff coverage; report this Ruff inventory defect or use a Ruff "
        "release with a complete inventory.",
    )


def _selector(rule: Mapping[str, object]) -> str:
    code = rule.get("code")
    if code is None:
        name = rule.get("name")
        if isinstance(name, str) and RULE_NAME.fullmatch(name):
            return name
        raise _unselectable_selector_error(rule)
    if isinstance(code, str) and RULE_CODE.fullmatch(code):
        return code
    raise _unselectable_selector_error(rule)


def _validated_selectors(rules: Sequence[Mapping[str, object]]) -> list[str]:
    """Return exactly the selectors that make the supplied inventory independently selectable.

    Returns:
        Selectors in inventory order.

    Raises:
        RuffInventoryUnavailableError: The inventory contains a malformed or duplicate selector.

    """
    selectors: list[str] = []
    seen: set[str] = set()
    for rule in rules:
        selector = _selector(rule)
        if selector in seen:
            msg = (
                f"ruff rule inventory is inconsistent: rule {_rule_name(rule)!r} repeats duplicate selector "
                f"{selector!r}; lintmax-py cannot claim exhaustive Ruff coverage."
            )
            raise RuffInventoryUnavailableError(msg)
        seen.add(selector)
        selectors.append(selector)
    return selectors


def _validate_null_code_names(
    rules: Sequence[Mapping[str, object]],
    executable: str,
) -> None:
    """Verify each code-less fallback selector with the Ruff that reported it.

    Raises:
        RuffInventoryUnavailableError: Ruff rejects an advertised null-code rule name.

    """
    for rule in rules:
        if rule.get("code") is not None:
            continue
        selector = _selector(rule)
        result = run([executable, "rule", selector])
        if result.code != 0:
            detail = result.out or f"exit {result.code} with no output"
            msg = (
                f"ruff rule inventory is incomplete: null-code rule {selector!r} is not selectable by the Ruff "
                f"executable that produced the inventory (exit {result.code}): {detail}. Report this Ruff "
                "inventory defect; lintmax-py cannot claim exhaustive coverage."
            )
            raise RuffInventoryUnavailableError(msg)


def inventory(ruff: Tool) -> RuffInventory:
    """Capture a validated rule inventory from the managed Ruff selected for this invocation.

    Returns:
        The immutable inventory tied to Ruff's executable path and observed version.

    Raises:
        RuffInventoryUnavailableError: Ruff cannot emit or validate a selectable inventory.

    """
    executable = str(ruff.path)
    result = run([executable, "rule", "--all", "--output-format", "json"])
    if result.code != 0:
        msg = f"ruff rule --all failed with exit {result.code}: {result.out}"
        raise RuffInventoryUnavailableError(msg)
    try:
        parsed = json.loads(result.out)
    except json.JSONDecodeError as error:
        msg = f"ruff rule --all returned invalid JSON: {error.msg}: {result.out}"
        raise RuffInventoryUnavailableError(msg) from error
    if not isinstance(parsed, list):
        msg = "ruff rule --all returned a non-list inventory"
        raise RuffInventoryUnavailableError(msg)
    if not parsed:
        msg = "ruff reported an empty rule set"
        raise RuffInventoryUnavailableError(msg)
    captured: list[Mapping[str, object]] = []
    for rule in parsed:
        if not isinstance(rule, dict):
            msg = "ruff reported a non-object rule"
            raise RuffInventoryUnavailableError(msg)
        captured.append(
            MappingProxyType({str(key): value for key, value in rule.items()}),
        )
    _validated_selectors(captured)
    _validate_null_code_names(captured, executable)
    return RuffInventory(
        executable=executable,
        version=ruff.version,
        rules=tuple(captured),
    )


def preview_selectors(rules: Sequence[Mapping[str, object]]) -> list[str]:
    pairs = zip(rules, _validated_selectors(rules), strict=True)
    return sorted(selector for rule, selector in pairs if rule.get("preview"))


def selection(rules: Sequence[Mapping[str, object]]) -> list[str]:
    return ["ALL", *preview_selectors(rules)]


def ignored() -> list[str]:
    return [*DOCSTRING_REQUIRED, *FORMATTER_CONFLICTS]


def summary(inventory: RuffInventory) -> str:
    linters = {str(rule.get("linter", "?")) for rule in inventory.rules}
    preview = preview_selectors(inventory.rules)
    return (
        f"ruff: {inventory.version} at {inventory.executable}\n"
        f"ruff rules: {len(inventory.rules)} across {len(linters)} linters "
        f"({len(preview)} preview-gated, all selected)\n"
        "ty rules: all at error severity\n"
        f"disabled: {', '.join(ignored())} (docstring-required rules; Ruff format conflict)"
    )
