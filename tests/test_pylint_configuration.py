# Copyright (c) lintmax-py contributors. Licensed under the MIT License.
"""Contracts for bounded project configuration of Ruff's argument limit."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

import pytest

from lintmax_py import config, gate, rules

if TYPE_CHECKING:
    from pathlib import Path

    from lintmax_py.proc import Result


class _Toolchain:
    """Minimal managed-tool context for a configuration failure test."""

    def __enter__(self) -> Self:
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> bool:
        return False

    @staticmethod
    def tool(_name: str) -> object:
        return object()


def _ruff_check_argument_count(root: Path, argument_count: int) -> Result:
    """Run the generated Ruff configuration against one generated function.

    Returns:
        The Ruff result for the generated function.

    """
    source = root / "public_contract.py"
    arguments = ", ".join(f"argument_{index}" for index in range(argument_count))
    source.write_text(f"def public_contract({arguments}):\n    pass\n", encoding="utf-8")
    generated = root / "generated-ruff.toml"
    generated.write_text(config.ruff_toml([], root), encoding="utf-8")
    return rules.run(
        [
            "ruff",
            "check",
            "--config",
            str(generated),
            "--select",
            "PLR0913",
            str(source),
        ],
    )


def test_a_project_can_raise_the_argument_limit_to_six_but_not_seven(
    tmp_path: Path,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[tool.ruff.lint.pylint]\nmax-args = 6\n",
        encoding="utf-8",
    )

    six_arguments = _ruff_check_argument_count(tmp_path, 6)
    assert six_arguments.code == 0, six_arguments.out

    seven_arguments = _ruff_check_argument_count(tmp_path, 7)
    assert seven_arguments.code == 1
    assert "too-many-arguments" in seven_arguments.out


def test_an_undeclared_project_keeps_the_default_limit_of_five(tmp_path: Path) -> None:
    six_arguments = _ruff_check_argument_count(tmp_path, 6)
    assert six_arguments.code == 1
    assert "too-many-arguments" in six_arguments.out


@pytest.mark.parametrize("value", ['"six"', "0", "7", "true"])
def test_invalid_project_argument_limits_fail_closed(tmp_path: Path, value: str) -> None:
    (tmp_path / "pyproject.toml").write_text(
        f"[tool.ruff.lint.pylint]\nmax-args = {value}\n",
        encoding="utf-8",
    )

    with pytest.raises(config.ProjectConfigurationError, match="max-args"):
        config.ruff_toml([], tmp_path)


def test_invalid_project_argument_limit_stops_the_gate_before_any_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[tool.ruff.lint.pylint]\nmax-args = 7\n",
        encoding="utf-8",
    )
    toolchain = _Toolchain()
    monkeypatch.setattr(gate.tools, "ensure", lambda: toolchain)
    monkeypatch.setattr(
        gate.rules,
        "inventory",
        lambda _tool: rules.RuffInventory("/managed/ruff", "ruff test", ()),
    )
    monkeypatch.setattr(
        gate,
        "_python_stages",
        lambda *_args, **_kwargs: pytest.fail("invalid configuration must stop before lint stages"),
    )

    assert gate.run_gate(tmp_path, fix=False) == [
        gate.Finding(
            stage="config",
            detail="[tool.ruff.lint.pylint].max-args must be an integer from 1 through 6",
        ),
    ]
