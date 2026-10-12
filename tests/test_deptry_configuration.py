# Copyright (c) lintmax-py contributors. Licensed under the MIT License.
"""Contracts for the runtime-provided modules a project declares to the dependency checker."""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

import pytest

from lintmax_py import config, gate
from lintmax_py.proc import Result, run

if TYPE_CHECKING:
    from pathlib import Path

MANIFEST = '[project]\nname = "probe"\nversion = "0.1.0"\ndependencies = []\n'
RUNTIME_DECLARATION = '[tool.deptry.per_rule_ignores]\nDEP001 = ["meddies_llm_runtime"]\n'


def _deptry(root: Path, imports: str) -> Result:
    """Run deptry exactly as the gate invokes it against one script.

    Returns:
        The deptry result for the project.

    """
    scripts = root / "scripts"
    scripts.mkdir()
    (scripts / "run.py").write_text(imports, encoding="utf-8")
    return run([shutil.which("deptry") or "deptry", *gate._deptry_args(root)], cwd=str(root))


@pytest.mark.skipif(
    shutil.which("deptry") is None,
    reason="the dependency checker itself is what is under test",
)
def test_a_declared_runtime_module_is_not_a_missing_dependency(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(MANIFEST + RUNTIME_DECLARATION, encoding="utf-8")
    config.project_configuration(tmp_path)

    result = _deptry(tmp_path, "import meddies_llm_runtime\nimport meddies_llm_runtime.client\n")

    assert result.code == 0, result.out


@pytest.mark.skipif(
    shutil.which("deptry") is None,
    reason="the dependency checker itself is what is under test",
)
def test_an_undeclared_import_is_still_a_missing_dependency(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(MANIFEST + RUNTIME_DECLARATION, encoding="utf-8")

    result = _deptry(tmp_path, "import meddies_llm_runtime\nimport other_runtime\n")

    assert result.code != 0
    assert "'other_runtime' imported but missing from the dependency definitions" in result.out
    assert "meddies_llm_runtime" not in result.out


def test_ignores_for_other_rules_are_left_to_the_checker(tmp_path: Path) -> None:
    """Only the DEP001 list is bounded here, so a project's other per-rule entries still validate."""
    body = MANIFEST + RUNTIME_DECLARATION + 'DEP002 = ["python-dotenv"]\n'
    (tmp_path / "pyproject.toml").write_text(body, encoding="utf-8")

    assert config.project_configuration(tmp_path) == config.ProjectConfiguration()


@pytest.mark.parametrize(
    "declaration",
    [
        '[tool.deptry.per_rule_ignores]\nDEP001 = "meddies_llm_runtime"\n',
        '[tool.deptry.per_rule_ignores]\nDEP001 = ["meddies_llm_runtime.client"]\n',
        '[tool.deptry.per_rule_ignores]\nDEP001 = ["meddies-llm-runtime"]\n',
        '[tool.deptry.per_rule_ignores]\nDEP001 = ["*"]\n',
        '[tool.deptry.per_rule_ignores]\nDEP001 = [""]\n',
        "[tool.deptry.per_rule_ignores]\nDEP001 = [1]\n",
        "[tool.deptry.per_rule_ignores]\nDEP001 = { meddies_llm_runtime = true }\n",
        "[tool.deptry]\nper_rule_ignores = []\n",
        "[tool]\ndeptry = 1\n",
    ],
)
def test_malformed_runtime_declarations_fail_closed(tmp_path: Path, declaration: str) -> None:
    """The checker matches an exact top-level module name, so any other shape is a dead declaration."""
    (tmp_path / "pyproject.toml").write_text(MANIFEST + declaration, encoding="utf-8")

    with pytest.raises(config.ProjectConfigurationError, match=r"\[tool\.deptry"):
        config.project_configuration(tmp_path)


def test_a_malformed_runtime_declaration_stops_the_gate_before_any_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        MANIFEST + '[tool.deptry.per_rule_ignores]\nDEP001 = ["meddies_llm_runtime.client"]\n',
        encoding="utf-8",
    )
    calls: list[str] = []

    def ensure() -> object:
        calls.append("tools.ensure")
        return object()

    monkeypatch.setattr(gate.tools, "ensure", ensure)

    assert gate.run_gate(tmp_path, fix=False) == [
        gate.Finding(
            stage="config",
            detail="[tool.deptry.per_rule_ignores].DEP001 must be a list of top-level module names",
        ),
    ]
    assert calls == []
