# Copyright (c) lintmax-py contributors. Licensed under the MIT License.
"""A project's own tool sections may declare facts but cannot switch a managed check off."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from lintmax_py import config, gate, tools
from lintmax_py.proc import Result, run

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

MANIFEST = '[project]\nname = "probe"\nversion = "0.1.0"\nrequires-python = ">=3.12"\ndependencies = []\n'
MISSPELLED = "te" + "h"
DECLARED = "reci" + "eve"
"""Words the speller rejects, assembled so the gate's own spell check of this file never sees them."""


@pytest.fixture
def toolchain() -> Iterator[tools.Toolchain]:
    with tools.ensure() as managed:
        yield managed


def _project(tmp_path: Path, pyproject: str, files: dict[str, str]) -> tuple[Path, Path]:
    """Write a project and the generated configs the stages under test read.

    Returns:
        The project root and the generated config directory.

    """
    root = tmp_path / "project"
    root.mkdir()
    (root / "pyproject.toml").write_text(MANIFEST + pyproject, encoding="utf-8")
    for name, body in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    generated = tmp_path / "generated"
    generated.mkdir()
    (generated / "ty.toml").write_text(config.ty_toml(config.project_configuration(root)), encoding="utf-8")
    (generated / "typos.toml").write_text(config.typos_toml(root), encoding="utf-8")
    return root, generated


def _only(monkeypatch: pytest.MonkeyPatch, toolchain: tools.Toolchain, name: str) -> None:
    """Run one managed tool for real and report every other stage clean."""
    executable = toolchain.path(name)

    def runner(command: list[str], **kwargs: object) -> Result:
        if command[0] != executable:
            return Result(code=0, out="")
        cwd = kwargs.get("cwd")
        assert cwd is None or isinstance(cwd, str)
        return run(command, cwd=cwd)

    monkeypatch.setattr(gate, "run", runner)
    monkeypatch.setattr(gate.dprint, "sweep", lambda *_args, **_kwargs: [])


def _details(
    stages: Callable[..., list[gate.Finding]],
    root: Path,
    generated: Path,
    toolchain: tools.Toolchain,
) -> str:
    return "\n".join(finding.detail for finding in stages(root, generated, toolchain, fix=False))


def test_ty_ignores_project_rule_overrides_and_source_excludes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    toolchain: tools.Toolchain,
) -> None:
    root, generated = _project(
        tmp_path,
        '[[tool.ty.overrides]]\ninclude = ["pkg/b.py"]\n[tool.ty.overrides.rules]\nunresolved-reference = "ignore"\n'
        '[tool.ty.src]\nexclude = ["pkg/c.py"]\n',
        {"pkg/b.py": "print(undefined_name)\n", "pkg/c.py": 'y: int = "s"\n'},
    )
    _only(monkeypatch, toolchain, "ty")

    details = _details(gate._python_stages, root, generated, toolchain)

    assert "undefined_name" in details
    assert "c.py" in details


def test_ty_still_honours_a_declared_runtime_module(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    toolchain: tools.Toolchain,
) -> None:
    root, generated = _project(
        tmp_path,
        '[tool.ty.analysis]\nallowed-unresolved-imports = ["example_runtime.**"]\n',
        {"pkg/run.py": "import example_runtime.client\nimport other_runtime\n"},
    )
    _only(monkeypatch, toolchain, "ty")

    details = _details(gate._python_stages, root, generated, toolchain)

    assert "other_runtime" in details
    assert "example_runtime" not in details


def test_typos_ignores_a_project_typos_file_but_keeps_its_vocabulary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    toolchain: tools.Toolchain,
) -> None:
    root, generated = _project(
        tmp_path,
        f'[tool.typos.default.extend-words]\n{DECLARED} = "{DECLARED}"\n',
        {
            "_typos.toml": '[files]\nextend-exclude = ["src"]\n',
            "src/a.py": f"{MISSPELLED} = 1\n{DECLARED} = 2\n",
        },
    )
    _only(monkeypatch, toolchain, "typos")

    details = _details(gate._repo_stages, root, generated, toolchain)

    assert f"`{MISSPELLED}` should be" in details
    assert DECLARED not in details


def test_shellcheck_ignores_a_project_rc_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    toolchain: tools.Toolchain,
) -> None:
    root, generated = _project(
        tmp_path,
        "",
        {".shellcheckrc": "disable=all\n", "s.sh": "#!/bin/bash\necho $1\n"},
    )
    _only(monkeypatch, toolchain, "shellcheck")

    assert "SC2086" in _details(gate._repo_stages, root, generated, toolchain)


@pytest.mark.parametrize("key", ["ignore", "exclude", "extend_exclude", "ignore_notebooks"])
def test_a_deptry_switch_is_a_configuration_finding(tmp_path: Path, key: str) -> None:
    value = "true" if key == "ignore_notebooks" else '["DEP001"]'
    (tmp_path / "pyproject.toml").write_text(MANIFEST + f"[tool.deptry]\n{key} = {value}\n", encoding="utf-8")

    with pytest.raises(config.ProjectConfigurationError, match=f"remove {key}"):
        config.project_configuration(tmp_path)


def test_deptry_facts_are_accepted(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        MANIFEST
        + '[tool.deptry]\nknown_first_party = ["probe"]\n'
        + '[tool.deptry.per_rule_ignores]\nDEP001 = ["example_runtime"]\nDEP002 = ["openvino"]\n'
        + '[tool.deptry.package_module_name_map]\npillow = ["PIL"]\n',
        encoding="utf-8",
    )

    config.project_configuration(tmp_path)


@pytest.mark.parametrize(("key", "pattern"), [("ignore_names", "*"), ("ignore_decorators", "@*")])
def test_a_wildcard_only_vulture_allowance_is_a_configuration_finding(tmp_path: Path, key: str, pattern: str) -> None:
    (tmp_path / "pyproject.toml").write_text(MANIFEST + f'[tool.vulture]\n{key} = ["{pattern}"]\n', encoding="utf-8")

    with pytest.raises(config.ProjectConfigurationError, match=f"tool.vulture].{key}"):
        config.project_configuration(tmp_path)


def test_named_vulture_allowances_are_accepted(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        MANIFEST + '[tool.vulture]\nignore_decorators = ["@app.route"]\nignore_names = ["model_config", "test_*"]\n',
        encoding="utf-8",
    )

    config.project_configuration(tmp_path)


@pytest.mark.parametrize("pattern", ['"**"', '"*.client"', '"!example_runtime"', '"example runtime"', "3"])
def test_an_unresolved_import_pattern_must_start_with_a_module_name(tmp_path: Path, pattern: str) -> None:
    (tmp_path / "pyproject.toml").write_text(
        MANIFEST + f"[tool.ty.analysis]\nallowed-unresolved-imports = [{pattern}]\n",
        encoding="utf-8",
    )

    with pytest.raises(config.ProjectConfigurationError, match="allowed-unresolved-imports"):
        config.project_configuration(tmp_path)


def test_unresolved_import_patterns_reach_the_generated_ty_config(
    tmp_path: Path,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        MANIFEST + '[tool.ty.analysis]\nallowed-unresolved-imports = ["example_runtime", "example_runtime.*.client"]\n',
        encoding="utf-8",
    )

    generated = config.ty_toml(config.project_configuration(tmp_path))

    assert generated == '[analysis]\nallowed-unresolved-imports = ["example_runtime", "example_runtime.*.client"]\n'
