# Copyright (c) lintmax-py contributors. Licensed under the MIT License.
"""Contracts for bounded project configuration of Ruff's target Python version."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

import pytest
import tomllib

from lintmax_py import config, gate, rules, tools

if TYPE_CHECKING:
    from pathlib import Path

    from lintmax_py.proc import Result


RUFF_0165_VERSION = "ruff 0.16.5"
RUFF_0165_TARGET_VERSIONS = (
    "py37",
    "py38",
    "py39",
    "py310",
    "py311",
    "py312",
    "py313",
    "py314",
)


def _ruff_check_tomllib_import_order(root: Path, executable: Path) -> Result:
    """Run generated config on an import whose classification needs Python 3.11.

    Returns:
        The import-order result emitted by Ruff.

    """
    source = root / "imports.py"
    source.write_text("import tomllib\nfrom pathlib import Path\n", encoding="utf-8")
    generated = root / "generated-ruff.toml"
    generated.write_text(config.ruff_toml([], root), encoding="utf-8")
    return rules.run(
        [
            str(executable),
            "check",
            "--config",
            str(generated),
            "--select",
            "I001",
            str(source),
        ],
    )


def test_target_version_classifies_tomllib_as_a_standard_library_module(
    tmp_path: Path,
) -> None:
    """A Python 3.12 declaration corrects Ruff's default Python 3.10 classification."""
    with tools.ensure() as toolchain:
        ruff = toolchain.tool("ruff")
        if ruff.version != RUFF_0165_VERSION:
            pytest.skip(f"requires managed Ruff {RUFF_0165_VERSION}, found: {ruff.version}")
        default_result = _ruff_check_tomllib_import_order(tmp_path, ruff.path)

        assert default_result.code == 1
        assert "unsorted-imports" in default_result.out

        (tmp_path / "pyproject.toml").write_text(
            '[tool.ruff]\ntarget-version = "py312"\n',
            encoding="utf-8",
        )

        result = _ruff_check_tomllib_import_order(tmp_path, ruff.path)

        assert result.code == 0, result.out


def test_target_version_accepts_every_value_supported_by_managed_ruff(
    tmp_path: Path,
) -> None:
    """Generated configuration accepts each target enum value from Ruff 0.16.5."""
    for target_version in RUFF_0165_TARGET_VERSIONS:
        (tmp_path / "pyproject.toml").write_text(
            f'[tool.ruff]\ntarget-version = "{target_version}"\n',
            encoding="utf-8",
        )

        generated = config.ruff_toml([], tmp_path)

        assert f'target-version = "{target_version}"' in generated


@pytest.mark.parametrize(
    "value",
    ['"py315"', '"3.12"', '""', "true", "312", '["py312"]'],
)
def test_invalid_project_target_versions_fail_closed(tmp_path: Path, value: str) -> None:
    """Only the managed Ruff target-version enum crosses the project boundary."""
    (tmp_path / "pyproject.toml").write_text(
        f"[tool.ruff]\ntarget-version = {value}\n",
        encoding="utf-8",
    )

    with pytest.raises(config.ProjectConfigurationError, match="target-version"):
        config.ruff_toml([], tmp_path)


def test_unrelated_project_ruff_settings_never_override_managed_configuration(
    tmp_path: Path,
) -> None:
    """The target version is the sole project Ruff setting copied into generated config."""
    (tmp_path / "pyproject.toml").write_text(
        """[tool.ruff]
target-version = "py312"
preview = false
required-version = "==0.1.0"
src = ["untrusted"]
exclude = ["untrusted.py"]
extend-exclude = ["also-untrusted.py"]
include = ["untrusted/**/*.py"]

[tool.ruff.lint]
select = ["F401"]
ignore = ["I001"]
extend-select = ["E501"]
extend-ignore = ["D100"]

[tool.ruff.format]
quote-style = "single"
""",
        encoding="utf-8",
    )

    generated = tomllib.loads(config.ruff_toml([], tmp_path))

    assert generated["target-version"] == "py312"
    assert generated["preview"] is True
    assert generated["exclude"] == config.EXCLUDES
    assert "required-version" not in generated
    assert "src" not in generated
    assert "include" not in generated
    assert "extend-exclude" not in generated
    assert generated["lint"]["select"] != ["F401"]
    assert generated["lint"]["ignore"] != ["I001"]
    assert "extend-select" not in generated["lint"]
    assert "extend-ignore" not in generated["lint"]
    assert generated["format"]["docstring-code-format"] is True
    assert "quote-style" not in generated["format"]


def test_absent_target_version_keeps_lintmax_default_configuration(
    tmp_path: Path,
) -> None:
    """No target-version declaration leaves the generated configuration unchanged."""
    generated = tomllib.loads(config.ruff_toml([], tmp_path))

    assert "target-version" not in generated


class _Toolchain:
    """Minimal managed-tool context for a configuration-failure test."""

    def __enter__(self) -> Self:
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> bool:
        return False

    @staticmethod
    def tool(_name: str) -> object:
        return object()


def test_invalid_target_version_stops_the_gate_before_analyzer_stages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invalid target declarations become config findings before Ruff or other analyzers run."""
    (tmp_path / "pyproject.toml").write_text('[tool.ruff]\ntarget-version = "py315"\n', encoding="utf-8")
    toolchain = _Toolchain()
    monkeypatch.setattr(gate.tools, "ensure", lambda: toolchain)
    monkeypatch.setattr(
        gate.rules,
        "inventory",
        lambda _tool: rules.RuffInventory("/managed/ruff", "ruff 0.16.5", ()),
    )
    monkeypatch.setattr(
        gate,
        "_python_stages",
        lambda *_args, **_kwargs: pytest.fail("invalid configuration must stop before analyzer stages"),
    )
    monkeypatch.setattr(
        gate,
        "_repo_stages",
        lambda *_args, **_kwargs: pytest.fail("invalid configuration must stop before analyzer stages"),
    )

    assert gate.run_gate(tmp_path, fix=False) == [
        gate.Finding(
            stage="config",
            detail="[tool.ruff].target-version must be one of: py37, py38, py39, py310, py311, py312, py313, py314",
        ),
    ]


def test_invalid_target_version_stops_before_toolchain_or_inventory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Malformed target configuration must fail before the managed toolchain is touched."""
    (tmp_path / "pyproject.toml").write_text(
        '[tool.ruff]\ntarget-version = "py315"\n',
        encoding="utf-8",
    )
    calls: list[str] = []
    toolchain = _Toolchain()

    def ensure() -> _Toolchain:
        calls.append("tools.ensure")
        return toolchain

    def inventory(_tool: object) -> rules.RuffInventory:
        calls.append("rules.inventory")
        return rules.RuffInventory("/managed/ruff", RUFF_0165_VERSION, ())

    monkeypatch.setattr(gate.tools, "ensure", ensure)
    monkeypatch.setattr(gate.rules, "inventory", inventory)

    assert gate.run_gate(tmp_path, fix=False) == [
        gate.Finding(
            stage="config",
            detail="[tool.ruff].target-version must be one of: py37, py38, py39, py310, py311, py312, py313, py314",
        ),
    ]
    assert calls == []
