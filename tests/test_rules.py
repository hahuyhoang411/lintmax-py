# Copyright (c) lintmax-py contributors. Licensed under the MIT License.
from __future__ import annotations

import json
import re
import shutil
from typing import TYPE_CHECKING

import pytest

from lintmax_py import cli, config, gate, rules
from lintmax_py.proc import Result

if TYPE_CHECKING:
    from pathlib import Path


def test_inventory_rejects_non_object_rules_from_ruff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A JSON list alone is insufficient: later stages require a rule-object schema."""
    monkeypatch.setattr(
        rules,
        "run",
        lambda *_args, **_kwargs: Result(code=0, out="[42]"),
    )

    with pytest.raises(rules.RuffInventoryUnavailableError, match="non-object"):
        rules.inventory()


def test_inventory_preserves_a_valid_rule_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        rules,
        "run",
        lambda *_args, **_kwargs: Result(
            code=0,
            out='[{"code": "F401", "preview": false}]',
        ),
    )

    inventory = rules.inventory()
    assert inventory == [{"code": "F401", "preview": False}]
    assert rules.selection(inventory) == ["ALL"]


@pytest.mark.parametrize("code", [42, "", "None"])
def test_inventory_rejects_an_unselectable_rule_code(
    code: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A malformed concrete code cannot be replaced by a rule name implicitly."""
    payload = json.dumps(
        [{"name": "pytest-fixture-autouse", "code": code, "preview": True}],
    )
    monkeypatch.setattr(
        rules,
        "run",
        lambda *_args, **_kwargs: Result(code=0, out=payload),
    )

    expected = (
        "ruff rule inventory is incomplete: rule 'pytest-fixture-autouse' has malformed code "
        f"{code!r}. lintmax-py will not substitute its name while a code is present; report this Ruff "
        "inventory defect or use a Ruff release with a complete inventory."
    )
    with pytest.raises(rules.RuffInventoryUnavailableError, match=re.escape(expected)):
        rules.inventory()


def test_generated_config_uses_a_rule_name_when_ruff_has_no_code(
    tmp_path: Path,
) -> None:
    """Config generation revalidates caller-provided inventories before serializing a selector."""
    valid_inventory: list[dict[str, object]] = [
        {"name": "unused-import", "code": "F401", "preview": True},
    ]
    generated = config.ruff_toml(valid_inventory, tmp_path)
    assert 'select = ["ALL", "F401"]' in generated
    assert "None" not in generated

    name_only_inventory: list[dict[str, object]] = [
        {"name": "pytest-fixture-autouse", "code": None, "preview": True},
    ]
    generated = config.ruff_toml(name_only_inventory, tmp_path)
    assert 'select = ["ALL", "pytest-fixture-autouse"]' in generated
    assert "None" not in generated

    inventory: list[dict[str, object]] = [{"name": None, "code": None, "preview": True}]
    with pytest.raises(
        rules.RuffInventoryUnavailableError,
        match="neither a selectable code nor name",
    ):
        config.ruff_toml(inventory, tmp_path)


def test_unknown_rule_name_warning_is_a_gate_finding(tmp_path: Path) -> None:
    """Stage handling remains a defence against an externally supplied invalid config."""
    inventory: list[dict[str, object]] = [
        {"name": "made-up-rule", "code": None, "preview": True},
    ]
    config_path = tmp_path / "ruff.toml"
    config_path.write_text(config.ruff_toml(inventory, tmp_path), encoding="utf-8")
    source = tmp_path / "tests" / "test_module.py"
    source.parent.mkdir()
    source.write_text("", encoding="utf-8")

    result = rules.run(["ruff", "check", "--config", str(config_path), str(source)])

    assert result.code == 0
    assert "Unknown rule selector" in result.out
    assert gate._stage("ruff check", result) == [
        gate.Finding(stage="ruff check", detail=result.out),
    ]


@pytest.mark.parametrize("command", ["rules", "check", "fix"])
def test_unselectable_null_code_rule_blocks_every_public_command(
    command: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Public commands fail before config materialization when Ruff rejects a fallback name."""
    executable = "/frozen/ruff"
    payload = json.dumps(
        [{"name": "made-up-rule", "code": None, "preview": True}],
    )

    def frozen_run(argv: list[str], **_kwargs: object) -> Result:
        if argv == [executable, "rule", "--all", "--output-format", "json"]:
            return Result(code=0, out=payload)
        if argv == [executable, "rule", "made-up-rule"]:
            return Result(
                code=2,
                out="error: invalid value 'made-up-rule' for '[RULE]'",
            )
        pytest.fail(f"unexpected Ruff command: {argv}")

    def fail_materialize(*_args: object, **_kwargs: object) -> None:
        pytest.fail("must not materialize an invalid Ruff config")

    monkeypatch.setattr(rules.shutil, "which", lambda _name: executable)
    monkeypatch.setattr(rules, "run", frozen_run)
    monkeypatch.setattr(gate.tools, "ensure", list)
    monkeypatch.setattr(gate.config, "materialize", fail_materialize)

    argv = [command] if command == "rules" else [command, str(tmp_path)]
    assert cli.main(argv) == 1
    captured = capsys.readouterr()
    expected = (
        "ruff-inventory: ruff rule inventory is incomplete: null-code rule 'made-up-rule' is not selectable "
        "by the Ruff executable that produced the inventory (exit 2): error: invalid value 'made-up-rule' "
        "for '[RULE]'. Report this Ruff inventory defect; lintmax-py cannot claim exhaustive coverage.\n"
    )
    assert captured.err == expected
    assert "all selected" not in captured.out


def test_inventory_rejects_duplicate_selectors(monkeypatch: pytest.MonkeyPatch) -> None:
    """One selector per inventory entry keeps the rule-count and coverage claims meaningful."""
    payload = json.dumps(
        [
            {"name": "first-rule", "code": "F401", "preview": False},
            {"name": "second-rule", "code": "F401", "preview": True},
        ],
    )
    monkeypatch.setattr(
        rules,
        "run",
        lambda *_args, **_kwargs: Result(code=0, out=payload),
    )

    with pytest.raises(
        rules.RuffInventoryUnavailableError,
        match="duplicate selector 'F401'",
    ):
        rules.inventory()


def test_inventory_preserves_the_subprocess_failure_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed Ruff inventory command cannot be mistaken for a complete empty inventory."""
    monkeypatch.setattr(
        rules,
        "run",
        lambda *_args, **_kwargs: Result(code=7, out="ruff internals failed"),
    )

    with pytest.raises(
        rules.RuffInventoryUnavailableError,
        match="ruff rule --all failed with exit 7: ruff internals failed",
    ):
        rules.inventory()


@pytest.mark.parametrize("output", ["not-json", "[]", '{"code": "F401"}'])
def test_inventory_rejects_unusable_ruff_output(
    output: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Malformed or empty inventory output cannot support an exhaustive-coverage claim."""
    monkeypatch.setattr(
        rules,
        "run",
        lambda *_args, **_kwargs: Result(code=0, out=output),
    )

    with pytest.raises(rules.RuffInventoryUnavailableError):
        rules.inventory()


def test_cli_reports_inventory_unavailability_without_a_traceback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The command reports unavailable coverage as a gate failure, not a Python crash."""
    expected = "ruff rule inventory is incomplete: synthetic test failure"
    monkeypatch.setattr(
        cli,
        "run_gate",
        lambda *_args, **_kwargs: _raise_inventory_error(expected),
    )

    assert cli.main(["check", str(tmp_path)]) == 1
    assert capsys.readouterr().err == f"ruff-inventory: {expected}\n"


def test_ruff_0165_null_rule_name_is_selected_and_reported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The captured 0.16.5 inventory selects its null-code preview rule by name."""
    ruff = shutil.which("ruff")
    if ruff is None:
        pytest.skip("Ruff is not installed")
    real_run = rules.run
    version = real_run([ruff, "--version"])
    if version.out != "ruff 0.16.5":
        pytest.skip(f"requires Ruff 0.16.5, found: {version.out or '<unavailable>'}")

    captured_inventory = real_run([ruff, "rule", "--all", "--output-format", "json"])
    assert captured_inventory.code == 0
    rule_name = "pytest-fixture-autouse"
    inventory_rows = json.loads(captured_inventory.out)
    matching_rules = [rule for rule in inventory_rows if rule.get("name") == rule_name]
    null_code_rule = matching_rules[0]
    assert null_code_rule["code"] is None
    captured_name_probe = real_run([ruff, "rule", rule_name])
    assert captured_name_probe.code == 0

    def frozen_run(argv: list[str], **_kwargs: object) -> Result:
        if argv == [ruff, "rule", "--all", "--output-format", "json"]:
            return captured_inventory
        if argv == [ruff, "rule", rule_name]:
            return captured_name_probe
        pytest.fail(f"unexpected Ruff command: {argv}")

    monkeypatch.setattr(
        rules,
        "run",
        frozen_run,
    )
    inventory = rules.inventory()
    generated = config.ruff_toml(inventory, tmp_path)
    config_path = tmp_path / "ruff.toml"
    config_path.write_text(generated, encoding="utf-8")
    source = tmp_path / "test_fixture.py"
    source.write_text(
        "import pytest\n\n\n@pytest.fixture(autouse=True)\ndef fixture() -> None:\n    pass\n",
        encoding="utf-8",
    )

    result = real_run([ruff, "check", "--config", str(config_path), str(source)])
    assert result.code == 1
    assert "pytest-fixture-autouse" in result.out
    assert "Unknown rule selector" not in result.out


def _raise_inventory_error(message: str) -> None:
    raise rules.RuffInventoryUnavailableError(message)
