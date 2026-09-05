# Copyright (c) lintmax-py contributors. Licensed under the MIT License.
from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import tomllib

from lintmax_py import gate, rules, tools
from lintmax_py.config import (
    COPYRIGHT_RULE,
    ProjectConfigurationError,
    copyright_notice,
    ruff_toml,
    vulture_allowances,
)
from lintmax_py.gate import DEV_EXTRA_NAMES, _deptry_args
from lintmax_py.proc import Result, run

if TYPE_CHECKING:
    from pathlib import Path

NOTICE = "(?i)Copyright \\\\(c\\\\) Example"


def test_an_undeclared_notice_stands_the_rule_down(tmp_path: Path) -> None:
    assert not copyright_notice(tmp_path)
    assert COPYRIGHT_RULE in ruff_toml([], tmp_path)


def test_a_declared_notice_enforces_the_rule(tmp_path: Path) -> None:
    body = f'[lint.flake8-copyright]\nnotice-rgx = "{NOTICE}"\n'
    (tmp_path / "ruff.toml").write_text(body, encoding="utf-8")
    assert copyright_notice(tmp_path) == NOTICE.replace("\\\\", "\\")
    generated = ruff_toml([], tmp_path)
    assert COPYRIGHT_RULE not in generated


def test_a_runtime_extra_is_not_a_development_group(tmp_path: Path) -> None:
    body = '[project]\nname = "x"\n[project.optional-dependencies]\nreceiver = ["flask"]\n'
    (tmp_path / "pyproject.toml").write_text(body, encoding="utf-8")
    assert "--optional-dependencies-dev-groups" not in _deptry_args(tmp_path)


def test_a_development_named_extra_is_forwarded(tmp_path: Path) -> None:
    body = '[project]\nname = "x"\n[project.optional-dependencies]\ndev = ["pytest"]\n'
    (tmp_path / "pyproject.toml").write_text(body, encoding="utf-8")
    args = _deptry_args(tmp_path)
    assert "--optional-dependencies-dev-groups" in args
    assert "dev" in args
    assert "dev" in DEV_EXTRA_NAMES


def test_a_project_declares_what_the_dead_code_scan_cannot_see(tmp_path: Path) -> None:
    body = '[tool.vulture]\nignore_decorators = ["@app.route"]\nignore_names = ["model_config"]\n'
    (tmp_path / "pyproject.toml").write_text(body, encoding="utf-8")
    assert vulture_allowances(tmp_path) == {
        "ignore_decorators": ["@app.route"],
        "ignore_names": ["model_config"],
    }


def test_a_silent_project_declares_nothing(tmp_path: Path) -> None:
    assert vulture_allowances(tmp_path) == {}


def test_formatter_conflict_is_always_ignored(tmp_path: Path) -> None:
    """Ruff format owns trailing commas, so its conflicting lint rule must stand down."""
    generated = tomllib.loads(ruff_toml([], tmp_path))

    assert "COM812" in generated["lint"]["ignore"]


def test_namespace_packages_are_copied_to_the_generated_ruff_top_level(tmp_path: Path) -> None:
    """Namespace directories define module resolution without changing lint policy."""
    (tmp_path / "src" / "example_plugins").mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text(
        '[tool.ruff]\nnamespace-packages = ["src/example_plugins"]\n',
        encoding="utf-8",
    )

    generated = tomllib.loads(ruff_toml([], tmp_path))

    assert generated["namespace-packages"] == ["src/example_plugins"]


@pytest.mark.parametrize(
    "value",
    [
        '"src/example_plugins"',
        '[""]',
        '["/absolute/package"]',
        '["src/../package"]',
        '["src/*/package"]',
        '["."]',
        '["./"]',
        '["   "]',
        '["missing"]',
    ],
)
def test_invalid_namespace_package_declarations_fail_closed(tmp_path: Path, value: str) -> None:
    """Only existing descendant directories can affect Ruff module resolution."""
    (tmp_path / "pyproject.toml").write_text(
        f"[tool.ruff]\nnamespace-packages = {value}\n",
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigurationError, match="namespace-packages"):
        ruff_toml([], tmp_path)


def test_namespace_packages_reject_files_and_symlink_escapes(tmp_path: Path) -> None:
    """Declared namespace packages must stay as directories inside the checked root."""
    file_path = tmp_path / "module.py"
    file_path.write_text("value = 1\n", encoding="utf-8")
    outside = tmp_path.parent / f"{tmp_path.name}-outside-package"
    outside.mkdir(exist_ok=True)
    escape = tmp_path / "escape"
    escape.symlink_to(outside, target_is_directory=True)
    loop = tmp_path / "loop"
    loop.symlink_to(loop)

    for declaration in ("module.py", "escape", "loop"):
        (tmp_path / "pyproject.toml").write_text(
            f'[tool.ruff]\nnamespace-packages = ["{declaration}"]\n',
            encoding="utf-8",
        )

        with pytest.raises(ProjectConfigurationError, match="namespace-packages"):
            ruff_toml([], tmp_path)


def test_namespace_package_alias_fails_before_ruff_loses_package_context(tmp_path: Path) -> None:
    """A symlink alias makes Ruff miss the real namespace package while scanning the root."""
    packages = tmp_path / "packages"
    packages.mkdir()
    (packages / "extension.py").write_text("value = 1\n", encoding="utf-8")
    alias = tmp_path / "alias"
    alias.symlink_to(packages, target_is_directory=True)
    (tmp_path / "pyproject.toml").write_text(
        '[tool.ruff]\nnamespace-packages = ["alias"]\n',
        encoding="utf-8",
    )
    generated = tmp_path.parent / f"{tmp_path.name}-generated"
    generated.mkdir()
    config = generated / "ruff.toml"
    config.write_text(
        'namespace-packages = ["alias"]\n[lint]\nselect = ["INP001"]\n',
        encoding="utf-8",
    )

    with tools.ensure() as toolchain:
        result = run(
            [toolchain.path("ruff"), "check", "--config", str(config), "."],
            cwd=str(tmp_path),
        )

    assert result.code == 1
    assert "INP001" in result.out
    with pytest.raises(ProjectConfigurationError, match="namespace-packages"):
        ruff_toml([], tmp_path)


def test_namespace_package_rejects_a_symlinked_parent_component(tmp_path: Path) -> None:
    """Every component named by a namespace declaration must be a real project directory."""
    packages = tmp_path / "packages" / "plugin"
    packages.mkdir(parents=True)
    alias_parent = tmp_path / "alias-parent"
    alias_parent.symlink_to(packages.parent, target_is_directory=True)
    (tmp_path / "pyproject.toml").write_text(
        '[tool.ruff]\nnamespace-packages = ["alias-parent/plugin"]\n',
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigurationError, match="namespace-packages"):
        ruff_toml([], tmp_path)


def test_namespace_package_list_has_no_arbitrary_entry_limit(tmp_path: Path) -> None:
    """Every existing descendant directory is valid regardless of how many are declared."""
    names = [f"packages/package_{index}" for index in range(33)]
    for name in names:
        (tmp_path / name).mkdir(parents=True)
    entries = ", ".join(f'"{name}"' for name in names)
    (tmp_path / "pyproject.toml").write_text(
        f"[tool.ruff]\nnamespace-packages = [{entries}]\n",
        encoding="utf-8",
    )

    generated = tomllib.loads(ruff_toml([], tmp_path))

    assert generated["namespace-packages"] == names


def test_invalid_namespace_packages_stop_before_managed_tool_setup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A malformed namespace declaration is a configuration finding, not a toolchain request."""
    (tmp_path / "pyproject.toml").write_text(
        '[tool.ruff]\nnamespace-packages = ["src/*/package"]\n',
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
            detail=(
                "[tool.ruff].namespace-packages must contain existing descendant directories "
                "without symlinks, parent traversal, or globs"
            ),
        ),
    ]
    assert calls == []


def test_formatter_conflict_is_not_duplicated_when_rule_inventory_already_ignores_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Generated Ruff policy lists a formatter conflict exactly once."""
    monkeypatch.setattr(rules, "ignored", lambda: ["D100", "COM812"])

    generated = tomllib.loads(ruff_toml([], tmp_path))

    assert generated["lint"]["ignore"].count("COM812") == 1


def test_managed_ruff_resolves_namespace_packages_from_the_gate_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The gate gives Ruff a root-relative target for namespace package resolution."""
    root = tmp_path / "project"
    root.mkdir()
    (root / "pyproject.toml").write_text(
        '[tool.ruff]\nnamespace-packages = ["plugins"]\n',
        encoding="utf-8",
    )
    source = root / "plugins" / "extension.py"
    source.parent.mkdir()
    source.write_text("value = 1\n", encoding="utf-8")
    generated = tmp_path / "generated"
    generated.mkdir()
    (generated / "ruff.toml").write_text(
        'namespace-packages = ["plugins"]\n[lint]\nselect = ["INP001"]\n',
        encoding="utf-8",
    )

    with tools.ensure() as toolchain:

        def run_managed_ruff(command: list[str], **kwargs: object) -> Result:
            if command[0] != toolchain.path("ruff"):
                return Result(code=0, out="")
            cwd = kwargs.get("cwd")
            assert cwd is None or isinstance(cwd, str)
            return run(command, cwd=cwd)

        monkeypatch.setattr(gate, "run", run_managed_ruff)

        assert gate._python_stages(root, generated, toolchain, fix=False) == []


def test_rules_summary_reports_the_unconditional_formatter_conflict() -> None:
    """The public rule report names Ruff's one unconditional formatter conflict."""
    inventory = rules.RuffInventory("/managed/ruff", "ruff test", ())

    assert "COM812" in rules.summary(inventory)
