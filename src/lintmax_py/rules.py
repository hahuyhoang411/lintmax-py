# Copyright (c) lintmax-py contributors. Licensed under the MIT License.
from __future__ import annotations

import json
import re
import shutil

from .proc import run

DOCSTRING_REQUIRED = ("D100", "D101", "D102", "D103", "D104", "D105", "D106", "D107")
RULE_CODE = re.compile(r"[A-Z]+[0-9]+")
RULE_NAME = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*")


class RuffInventoryUnavailableError(RuntimeError):
    """Ruff could not provide the selectable rule inventory strict coverage requires."""


def _rule_name(rule: dict[str, object]) -> str:
    name = rule.get("name")
    return name if isinstance(name, str) and name else "<unnamed Ruff rule>"


def _unselectable_selector_error(
    rule: dict[str, object],
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


def _selector(rule: dict[str, object]) -> str:
    code = rule.get("code")
    if code is None:
        name = rule.get("name")
        if isinstance(name, str) and RULE_NAME.fullmatch(name):
            return name
        raise _unselectable_selector_error(rule)
    if isinstance(code, str) and RULE_CODE.fullmatch(code):
        return code
    raise _unselectable_selector_error(rule)


def _validated_selectors(rules: list[dict[str, object]]) -> list[str]:
    """Return exactly the selectors that make the supplied inventory independently selectable.

    Returns:
        The validated selector for every supplied rule, in inventory order.

    Raises:
        RuffInventoryUnavailableError: A rule is malformed, unselectable, or duplicates a selector.

    """
    selectors: list[str] = []
    seen: set[str] = set()
    for rule in rules:
        if not isinstance(rule, dict):
            msg = "ruff reported a non-object rule"
            raise RuffInventoryUnavailableError(msg)
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


def _validate_null_code_names(rules: list[dict[str, object]], executable: str) -> None:
    """Verify each code-less fallback selector with the Ruff that reported it.

    Ruff accepts unknown selectors in configuration as warnings, so syntactic validation of a
    code-less name is not enough to support an exhaustive-coverage claim. This bounded probe only
    checks null-code entries against the already resolved executable and inventory snapshot.

    Raises:
        RuffInventoryUnavailableError: Ruff rejects an advertised code-less rule name.

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


def inventory() -> list[dict[str, object]]:
    executable = shutil.which("ruff") or "ruff"
    res = run([executable, "rule", "--all", "--output-format", "json"])
    if res.code != 0:
        msg = f"ruff rule --all failed with exit {res.code}: {res.out}"
        raise RuffInventoryUnavailableError(msg)
    try:
        parsed = json.loads(res.out)
    except json.JSONDecodeError as error:
        msg = f"ruff rule --all returned invalid JSON: {error.msg}: {res.out}"
        raise RuffInventoryUnavailableError(msg) from error
    if not isinstance(parsed, list):
        msg = "ruff rule --all returned a non-list inventory"
        raise RuffInventoryUnavailableError(msg)
    if not parsed:
        msg = "ruff reported an empty rule set"
        raise RuffInventoryUnavailableError(msg)
    inventory: list[dict[str, object]] = []
    for rule in parsed:
        if not isinstance(rule, dict):
            msg = "ruff reported a non-object rule"
            raise RuffInventoryUnavailableError(msg)
        inventory.append({str(key): value for key, value in rule.items()})
    _validated_selectors(inventory)
    _validate_null_code_names(inventory, executable)
    return inventory


def preview_selectors(rules: list[dict[str, object]]) -> list[str]:
    pairs = zip(rules, _validated_selectors(rules), strict=True)
    return sorted(selector for rule, selector in pairs if rule.get("preview"))


def selection(rules: list[dict[str, object]]) -> list[str]:
    return ["ALL", *preview_selectors(rules)]


def ignored() -> list[str]:
    return list(DOCSTRING_REQUIRED)


def summary(rules: list[dict[str, object]]) -> str:
    linters = {str(r.get("linter", "?")) for r in rules}
    preview = preview_selectors(rules)
    return (
        f"ruff rules: {len(rules)} across {len(linters)} linters "
        f"({len(preview)} preview-gated, all selected)\n"
        f"ty rules: all at error severity\n"
        f"disabled: {', '.join(ignored())} (docstring-required family)"
    )
