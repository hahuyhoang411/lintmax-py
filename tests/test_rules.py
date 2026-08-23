# Copyright (c) lintmax-py contributors. Licensed under the MIT License.
from __future__ import annotations

import pytest

from lintmax_py import rules
from lintmax_py.proc import Result


def test_inventory_rejects_non_object_rules_from_ruff(monkeypatch: pytest.MonkeyPatch) -> None:
    """A JSON list alone is insufficient: later stages require a rule-object schema."""
    monkeypatch.setattr(rules, "run", lambda *_args, **_kwargs: Result(code=0, out="[42]"))

    with pytest.raises(TypeError, match="non-object"):
        rules.inventory()


def test_inventory_preserves_a_valid_rule_object(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        rules,
        "run",
        lambda *_args, **_kwargs: Result(code=0, out='[{"code": "F401", "preview": false}]'),
    )

    assert rules.inventory() == [{"code": "F401", "preview": False}]
